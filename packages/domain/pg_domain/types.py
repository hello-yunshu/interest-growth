from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import CapabilityStatus


@dataclass(slots=True)
class ResearchPlan:
    question: str
    brief: str
    subquestions: list[str] = field(default_factory=list)
    desired_sources: list[str] = field(default_factory=list)
    depth: str = "normal"
    knowledge_bases: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NormalizedSource:
    title: str
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    source_type: str = "web"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResearchResult:
    status: CapabilityStatus
    provider: str
    report: str
    sources: list[NormalizedSource] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    run_id: str | None = None
