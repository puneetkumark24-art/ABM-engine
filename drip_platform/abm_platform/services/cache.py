"""
cache.py — Redis-backed cache + rate limiter with an in-memory fallback (Gap-3).

Uses Redis when REDIS_URL is set and reachable; otherwise degrades to a
process-local dict/TTL implementation so dev, tests, and single-node runs work
with zero Redis. The interface is identical either way, so wiring code never
branches on backend.

Provides:
  cache_get / cache_set / cache_delete   TTL key/value (JSON-serialized)
  cached(ttl)                            decorator for pure read functions
  rate_limit(key, limit, window)         fixed-window limiter -> (allowed, remaining)
  segment cache helpers                  cache dynamic-segment membership

Wired into: dynamic-segment resolution (hot, recomputed often) and an API
rate-limit dependency.
"""
from __future__ import annotations
import json
import os
import time
import threading
from functools import wraps
from typing import Any, Callable, Optional

_REDIS = None
_REDIS_TRIED = False


def _redis():
    global _REDIS, _REDIS_TRIED
    if _REDIS_TRIED:
        return _REDIS
    _REDIS_TRIED = True
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis  # type: ignore
        client = redis.Redis.from_url(url, socket_connect_timeout=1, decode_responses=True)
        client.ping()
        _REDIS = client
    except Exception:
        _REDIS = None
    return _REDIS


# ── in-memory fallback ───────────────────────────────────────
_MEM: dict[str, tuple[float, str]] = {}   # key -> (expires_at, json)
_MEM_LOCK = threading.Lock()


def _mem_get(key: str) -> Optional[str]:
    with _MEM_LOCK:
        v = _MEM.get(key)
        if not v:
            return None
        exp, val = v
        if exp and exp < time.time():
            _MEM.pop(key, None)
            return None
        return val


def _mem_set(key: str, val: str, ttl: int) -> None:
    with _MEM_LOCK:
        _MEM[key] = (time.time() + ttl if ttl else 0, val)


# ── public cache API ─────────────────────────────────────────
def cache_get(key: str) -> Any:
    r = _redis()
    raw = r.get(key) if r else _mem_get(key)
    return json.loads(raw) if raw is not None else None


def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    raw = json.dumps(value, default=str)
    r = _redis()
    if r:
        r.set(key, raw, ex=ttl if ttl else None)
    else:
        _mem_set(key, raw, ttl)


def cache_delete(key: str) -> None:
    r = _redis()
    if r:
        r.delete(key)
    else:
        with _MEM_LOCK:
            _MEM.pop(key, None)


def cached(ttl: int = 300, key_prefix: str = ""):
    """Decorator: cache a function's return by its args. Use only for pure reads."""
    def deco(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{key_prefix}:{fn.__name__}:{hash((args[1:] if args else (), tuple(sorted(kwargs.items()))))}"
            hit = cache_get(key)
            if hit is not None:
                return hit
            val = fn(*args, **kwargs)
            cache_set(key, val, ttl)
            return val
        return wrapper
    return deco


# ── rate limiter (fixed window) ──────────────────────────────
def rate_limit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """Returns (allowed, remaining). Fixed-window counter; atomic on Redis."""
    bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
    r = _redis()
    if r:
        n = r.incr(bucket)
        if n == 1:
            r.expire(bucket, window_seconds)
        return (n <= limit), max(0, limit - n)
    # in-memory
    cur = cache_get(bucket) or 0
    cur += 1
    cache_set(bucket, cur, window_seconds)
    return (cur <= limit), max(0, limit - cur)


def backend_name() -> str:
    return "redis" if _redis() else "in-memory-fallback"


# ── segment membership cache (wired into marketing) ──────────
def cache_segment(audience_id: str, member_ids: list[str], ttl: int = 120) -> None:
    cache_set(f"seg:{audience_id}", member_ids, ttl)


def get_cached_segment(audience_id: str) -> Optional[list[str]]:
    return cache_get(f"seg:{audience_id}")


def invalidate_segment(audience_id: str) -> None:
    cache_delete(f"seg:{audience_id}")
