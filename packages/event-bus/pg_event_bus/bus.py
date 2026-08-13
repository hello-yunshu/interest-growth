from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4


@dataclass(slots=True, frozen=True)
class DomainEvent:
    type: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = 1


Handler = Callable[[DomainEvent], None]


class EventBus:
    """Small synchronous bus with explicit subscriptions.

    Persistence is handled by the API event recorder so the bus stays framework-agnostic.
    A failed subscriber does not stop subsequent subscribers; errors are returned to caller.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> list[Exception]:
        errors: list[Exception] = []
        for handler in [*self._handlers.get(event.type, []), *self._handlers.get("*", [])]:
            try:
                handler(event)
            except Exception as exc:  # plugin isolation boundary
                errors.append(exc)
        return errors
