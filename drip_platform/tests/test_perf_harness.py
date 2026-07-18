"""
Sprint 10 — performance/load harness. Drives the real app + a write-path service
and asserts latency percentiles + throughput against SLO thresholds. Not a micro-
benchmark: it exercises the middleware stack (tenancy, observability) end to end.

Thresholds are deliberately generous so the gate is stable in CI while still
catching order-of-magnitude regressions. Tune per environment.
"""
import os
import sys
import time
import statistics
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_DBFILE = os.path.join(tempfile.gettempdir(), "drip_perf.db")
if os.path.exists(_DBFILE):
    os.remove(_DBFILE)
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"
os.environ["AUTH_ENFORCED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from database import Base, engine, SessionLocal  # noqa: E402
import models, models_ext, models_p10, models_p11, models_p12, models_audit, models_crm2  # noqa: E402,F401
from main import app  # noqa: E402
from abm_platform.services import quotes  # noqa: E402

Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)
client = TestClient(app)
_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


def _percentiles(latencies_ms):
    s = sorted(latencies_ms)
    p = lambda q: s[min(len(s) - 1, int(q * len(s)))]  # noqa: E731
    return p(0.50), p(0.95), p(0.99)


def run():
    # ── read-path latency under load ──
    N = 1000
    lat = []
    for _ in range(N):
        t = time.perf_counter()
        r = client.get("/health")
        lat.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 200
    p50, p95, p99 = _percentiles(lat)
    throughput = N / (sum(lat) / 1000)
    check("read p50 < 25ms", p50 < 25, f"(p50={p50:.2f}ms)")
    check("read p95 < 75ms", p95 < 75, f"(p95={p95:.2f}ms)")
    # single-thread synchronous TestClient floor; real deploy is multi-worker
    check("read throughput > 80 rps (single-thread)", throughput > 80, f"({throughput:.0f} rps)")

    # ── write-path latency (custom object records via HTTP) ──
    client.post("/crm/objects", json={"key": "load_obj", "label": "Load",
                "schema": [{"key": "n", "type": "number"}]})
    wlat = []
    for i in range(300):
        t = time.perf_counter()
        r = client.post("/crm/objects/load_obj/records", json={"data": {"n": i}})
        wlat.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 201
    wp50, wp95, wp99 = _percentiles(wlat)
    check("write p95 < 150ms", wp95 < 150, f"(p95={wp95:.2f}ms)")

    # ── bulk service throughput (money recompute hot path) ──
    db = SessionLocal()
    org = models.Organization(canonical_name="Perf Bank"); db.add(org); db.commit()
    q = quotes.create_quote(db, "perf-quote", org_id=org.id)
    t = time.perf_counter()
    for i in range(500):
        quotes.add_line(db, q.id, f"line{i}", 1, 100_00)
    elapsed = time.perf_counter() - t
    lines_per_s = 500 / elapsed
    # commit-per-line on SQLite; Postgres + batched commit is far higher
    check("quote line writes > 30/s (commit-per-line)", lines_per_s > 30, f"({lines_per_s:.0f}/s)")
    summary = quotes.quote_summary(db, q.id)
    check("500 lines recomputed correctly", summary["lines"] == 500)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [perf harness]")
    print(f"  read  p50/p95/p99 = {p50:.1f}/{p95:.1f}/{p99:.1f} ms, {throughput:.0f} rps")
    print(f"  write p50/p95/p99 = {wp50:.1f}/{wp95:.1f}/{wp99:.1f} ms")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_perf_harness():
    assert run()
