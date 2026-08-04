"""Engine tick mutual exclusion — and the lock-stranding regression guard.

The v4 hardening candidate proposed serializing whole engine ticks with a
PostgreSQL session advisory lock taken on the SQLAlchemy `Session` itself, on
the reasoning that a transaction-scoped lock would be released too early by the
tick's internal commits. The first half of that reasoning is right; the
implementation is not.

A session advisory lock belongs to the specific backend connection that took
it. A `Session` returns its connection to the pool on `commit()`, and this tick
commits internally more than once. Measured against a real disposable
PostgreSQL, under two concurrent ticks the Session came back on a DIFFERENT
backend in 3 of 4 runs -- so `pg_advisory_unlock` ran on the wrong connection,
returned false, and the lock was never released. Stranded locks accumulate on
idle pooled connections; once every connection in the pool holds one, every
future tick reports "another engine tick is already running" and the engine
silently stops dispatching. It looks exactly like an idle engine, which is what
makes it dangerous.

The shipped implementation holds the lock on a dedicated connection pinned for
the tick's duration. This suite proves the property that actually matters --
after concurrent ticks, NO lock is left behind -- so the Session-based version
cannot be reintroduced without turning this red.

Postgres-only (advisory locks don't exist on SQLite); the SQLite path uses a
process-local lock, checked separately below.
"""
import os
import sys
import threading

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import sqlalchemy as sa  # noqa: E402
from abm_platform.services import orchestrator  # noqa: E402

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + detail) if detail else "")


def _locks_held(engine) -> int:
    """Count advisory locks on the tick key, asked from an INDEPENDENT
    connection so we observe the server's real state, not our own session's."""
    with engine.connect() as c:
        return c.execute(sa.text(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
            "AND ((classid::bigint << 32) | objid::bigint) = :k"),
            {"k": orchestrator._PG_TICK_LOCK_KEY}).scalar()


def run_pg():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        print("… advisory-lock checks skipped (needs PostgreSQL)")
        return

    from sqlalchemy.orm import sessionmaker
    # A small pool, like a real API process — this is what makes a stranded
    # lock fatal rather than merely wasteful.
    engine = sa.create_engine(url, pool_size=5)
    Session = sessionmaker(bind=engine)

    entered, overlaps = [], []
    inside = threading.Event()
    guard = threading.Lock()

    def fake_tick(label):
        """The real lock wrapper around a body that commits internally,
        which is precisely what breaks a Session-held lock."""
        db = Session()
        handle = orchestrator._acquire_tick_lock(db)
        if handle is None:
            db.close()
            return False
        try:
            with guard:
                entered.append(label)
                if inside.is_set():
                    overlaps.append(label)
                inside.set()
            for _ in range(3):
                db.execute(sa.text("SELECT 1"))
                db.commit()
            with guard:
                inside.clear()
            return True
        finally:
            orchestrator._release_tick_lock(handle)
            db.close()

    # ── two ticks racing, three times over ──────────────────────────────
    winners = []
    for round_no in range(3):
        barrier = threading.Barrier(2, timeout=20)
        outcome = {}

        def race(n):
            barrier.wait()
            outcome[n] = fake_tick(f"r{round_no}t{n}")

        threads = [threading.Thread(target=race, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        winners.append(sum(1 for v in outcome.values() if v))

    check("exactly one tick wins each race", all(w == 1 for w in winners),
          f"winners per round: {winners}")
    check("no two ticks were ever inside the tick body at once", not overlaps,
          f"overlaps: {overlaps}")
    # The regression guard. With the lock held on the Session this is where the
    # Session-based implementation failed, leaving 1 stranded lock per race.
    check("NO advisory lock is stranded after concurrent ticks",
          _locks_held(engine) == 0,
          f"locks still held on key: {_locks_held(engine)}")

    # ── and the engine still runs afterwards, same process, same pool ───
    later = [fake_tick(f"later{i}") for i in range(4)]
    check("later ticks are not jammed by a leaked lock", all(later),
          f"results: {later}")
    check("no lock left behind at the end", _locks_held(engine) == 0)
    engine.dispose()


def run_sqlite_path():
    """The dev/test path: a process-local lock, released on the way out."""
    if orchestrator._LOCAL_TICK_LOCK.locked():          # pragma: no cover
        orchestrator._LOCAL_TICK_LOCK.release()

    class _FakeBind:
        dialect = type("d", (), {"name": "sqlite"})()

    class _FakeSession:
        def get_bind(self):
            return _FakeBind()

    db = _FakeSession()
    first = orchestrator._acquire_tick_lock(db)
    check("SQLite: first tick acquires the process lock", first is not None)
    second = orchestrator._acquire_tick_lock(db)
    check("SQLite: a concurrent tick is refused", second is None)
    orchestrator._release_tick_lock(first)
    third = orchestrator._acquire_tick_lock(db)
    check("SQLite: lock is reusable after release", third is not None)
    orchestrator._release_tick_lock(third)
    check("SQLite: lock is free at the end", not orchestrator._LOCAL_TICK_LOCK.locked())


def run():
    run_sqlite_path()
    run_pg()
    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed  "
          f"[DB: {os.environ.get('DATABASE_URL', '?').split(':')[0]}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_tick_lock():
    assert run()
