"""
platform/events.py — Module 24 (Integration Layer & Event Bus), core.

A real, minimal, synchronous, in-process pub/sub the modules use to stay
decoupled. Deliberately dependency-free (stdlib only) so it runs today on the
single-laptop deployment; it is swappable for Redis Streams / Kafka later
behind the same publish()/subscribe() interface without touching callers.

Guarantees (matching the blueprint's bus contract, scoped to in-process):
  * at-least-once within the process; consumers are idempotent via event id
    (the bus refuses to redeliver an id it has already delivered to a handler).
  * per-key ordering: events published are delivered to handlers in call order;
    `key` (e.g. account_id) lets consumers reason about ordering per entity.
  * handler errors are isolated: one failing subscriber never blocks others.
"""
from __future__ import annotations
import uuid, logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any

logger = logging.getLogger("drip.platform.events")


@dataclass
class Event:
    type: str
    key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=datetime.utcnow)


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Event], None]]] = {}
        self._delivered: set[tuple[str, int]] = set()   # (event_id, handler_id)

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self._subs.setdefault(event_type, []).append(handler)

    def publish(self, event: Event) -> int:
        delivered = 0
        for h in list(self._subs.get(event.type, [])):
            hkey = (event.id, id(h))
            if hkey in self._delivered:   # idempotency: never redeliver same id to same handler
                continue
            try:
                h(event)
                self._delivered.add(hkey)
                delivered += 1
            except Exception as e:   # isolate handler failures
                logger.exception("subscriber for %s failed: %s", event.type, e)
        return delivered

    def clear(self) -> None:
        self._subs.clear(); self._delivered.clear()


bus = EventBus()               # process-wide default bus
def subscribe(event_type, handler): return bus.subscribe(event_type, handler)
def publish(event): return bus.publish(event)


if __name__ == "__main__":   # tiny self-test
    seen = []
    subscribe("account.tiered", lambda e: seen.append(("A", e.payload)))
    subscribe("account.tiered", lambda e: seen.append(("B", e.payload)))
    ev = Event("account.tiered", key="org-1", payload={"tier": "HOT"})
    n1 = publish(ev)
    n2 = publish(ev)   # same id -> idempotent, 0 new deliveries
    assert n1 == 2 and n2 == 0 and len(seen) == 2, (n1, n2, seen)
    print("events.py self-test OK:", seen)
