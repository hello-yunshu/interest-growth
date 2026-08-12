from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass(frozen=True, slots=True)
class LearningActivityCandidate:
    area_id: str
    session_id: str
    capability_id: str
    activity_type: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    authoritative: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
