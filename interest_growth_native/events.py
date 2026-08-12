from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

PUBLIC_EVENT_TYPES = frozenset({
    "answer_delta", "thinking", "activity", "sources",
    "wait_for_input", "result", "done", "error",
})

@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    type: str
    run_id: str
    area_id: str
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self):
        if self.type not in PUBLIC_EVENT_TYPES:
            raise ValueError(f"non-public/unknown event type: {self.type}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "run_id": self.run_id,
            "area_id": self.area_id,
            "session_id": self.session_id,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }
