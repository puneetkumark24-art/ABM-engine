"""
uuid7.py — time-ordered UUIDv7 generator (P0-D, RFC 9562).

The schema's random UUIDv4 text PKs cause B-tree fragmentation and write
amplification on 100M-row tables (each insert lands on a random leaf page).
UUIDv7 embeds a millisecond timestamp in the high bits, so new ids sort roughly
by creation time and inserts append to the right of the index — sequential,
cache-friendly, no page splits. Store as native `uuid` in Postgres (half the
width of text, index-friendly); keep string(36) on SQLite dev.

Migration strategy (documented, not auto-applied): new event/timeline tables use
uuid7() defaults + native uuid columns from birth; existing hot tables are
re-typed during their partitioning rebuild. This module is the id source.
"""
from __future__ import annotations
import os
import time
import uuid


def uuid7() -> str:
    """RFC 9562 UUIDv7: 48-bit unix-ms | ver 7 | 12-bit rand | var | 62-bit rand."""
    unix_ms = int(time.time() * 1000)
    rand = bytearray(os.urandom(10))
    b = bytearray(unix_ms.to_bytes(6, "big")) + rand
    b[6] = (b[6] & 0x0F) | 0x70   # version 7
    b[8] = (b[8] & 0x3F) | 0x80   # RFC 4122 variant
    return str(uuid.UUID(bytes=bytes(b)))


def uuid7_time(u: str) -> float:
    """Extract the creation time (unix seconds) from a UUIDv7 — useful for
    range checks / debugging."""
    raw = uuid.UUID(u).bytes
    unix_ms = int.from_bytes(raw[:6], "big")
    return unix_ms / 1000.0
