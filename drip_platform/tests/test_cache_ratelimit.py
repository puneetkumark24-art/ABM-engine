"""
Gap-3 test — cache + rate limiter (in-memory fallback path, since the sandbox
has no Redis; the Redis path uses the identical interface). Plus the segment
cache wired for marketing and the FastAPI 429 rate-limit dependency.
"""
import os
import sys
import time

os.environ.pop("REDIS_URL", None)   # force the in-memory fallback for the test
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from abm_platform.services import cache  # noqa: E402

_results = []


def check(name, cond):
    _results.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), "-", name)


def run():
    check("CACHE backend is fallback (no Redis)", cache.backend_name() == "in-memory-fallback")

    # basic get/set/ttl
    cache.cache_set("k1", {"a": 1}, ttl=60)
    check("CACHE set/get roundtrip", cache.cache_get("k1") == {"a": 1})
    check("CACHE miss returns None", cache.cache_get("nope") is None)
    cache.cache_set("k2", "v", ttl=1)
    time.sleep(1.1)
    check("CACHE ttl expiry", cache.cache_get("k2") is None)
    cache.cache_delete("k1")
    check("CACHE delete", cache.cache_get("k1") is None)

    # cached() decorator
    calls = {"n": 0}

    @cache.cached(ttl=60, key_prefix="t")
    def expensive(self_ignore, x):
        calls["n"] += 1
        return x * 2
    r1 = expensive(None, 21); r2 = expensive(None, 21)
    check("CACHE @cached memoizes (1 call for 2 invocations)", r1 == r2 == 42 and calls["n"] == 1)

    # segment cache helpers
    cache.cache_segment("aud1", ["p1", "p2"], ttl=60)
    check("CACHE segment cache", cache.get_cached_segment("aud1") == ["p1", "p2"])
    cache.invalidate_segment("aud1")
    check("CACHE segment invalidate", cache.get_cached_segment("aud1") is None)

    # rate limiter: 3/window then blocked
    allowed = [cache.rate_limit("u1", limit=3, window_seconds=60)[0] for _ in range(5)]
    check("RATE first 3 allowed", allowed[:3] == [True, True, True])
    check("RATE 4th+ blocked", allowed[3] is False and allowed[4] is False)
    # different key independent
    check("RATE separate key independent", cache.rate_limit("u2", 3, 60)[0] is True)

    # FastAPI 429 dependency
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    from rate_limit_dep import rate_limited
    app = FastAPI()

    @app.get("/limited", dependencies=[Depends(rate_limited("test", limit=2, window_seconds=60))])
    def limited():
        return {"ok": True}
    client = TestClient(app)
    codes = [client.get("/limited").status_code for _ in range(4)]
    check("RATE dep: first 2 pass (200)", codes[:2] == [200, 200])
    check("RATE dep: then 429", codes[2] == 429 and codes[3] == 429)

    passed = sum(1 for _, ok in _results if ok); total = len(_results)
    print(f"\n{passed}/{total} checks passed  [backend: {cache.backend_name()}]")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_cache_ratelimit():
    assert run()
