from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

@dataclass(frozen=True, slots=True)
class DomainPolicy:
    domain_pack_id: str
    research_instructions: str = ""
    research_limitations: tuple[str, ...] = ()
    learning_instructions: str = ""
    mastery_profile: tuple[str, ...] = (
        "unfamiliar", "familiar", "understand", "practice",
        "apply", "reflect", "transfer", "self_directed",
    )
    content_instructions: str = ""
    safety_instructions: str = ""
    version: str = ""

@dataclass(frozen=True, slots=True)
class SourceLocator:
    filename: str = ""
    page: int | None = None
    section: str = ""
    char_start: int | None = None
    char_end: int | None = None
    slide: int | None = None
    sheet: str = ""
    cell_range: str = ""

@dataclass(frozen=True, slots=True)
class SourceTextSnapshot:
    source_id: str
    area_id: str
    filename: str
    text: str
    fingerprint: str = ""
    locator: SourceLocator = field(default_factory=SourceLocator)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class KnowledgeBaseSnapshot:
    kb_id: str
    area_id: str
    name: str
    engine_id: str
    sources: tuple[SourceTextSnapshot, ...]
    fingerprint: str = ""
    engine_config: dict[str, Any] = field(default_factory=dict)

class KnowledgeResolver(Protocol):
    def resolve(
        self,
        *,
        area_id: str,
        kb_ids: Iterable[str],
    ) -> tuple[KnowledgeBaseSnapshot, ...]: ...

@dataclass(frozen=True, slots=True)
class SkillRequirements:
    bins: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    sandbox: str = ""

@dataclass(frozen=True, slots=True)
class SkillRuntimeEnvironment:
    bins: frozenset[str] = frozenset()
    env: frozenset[str] = frozenset()
    sandboxes: frozenset[str] = frozenset()

@dataclass(frozen=True, slots=True)
class SkillSnapshot:
    id: str
    title: str
    body: str
    description: str = ""
    always_on: bool = False
    references: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    fingerprint: str = ""
    tags: tuple[str, ...] = ()
    requires: SkillRequirements = field(default_factory=SkillRequirements)

@dataclass(frozen=True, slots=True)
class PersonaSnapshot:
    id: str
    name: str
    instructions: str
    domain_pack_id: str
    fingerprint: str = ""

@dataclass(frozen=True, slots=True)
class HostTutorBinding:
    tutor_session_id: str
    tutor_turn_id: str

@dataclass(frozen=True, slots=True)
class GroundingRefSnapshot:
    ref_type: str
    ref_id: str
    fingerprint: str = ""
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class PracticeOrigin:
    origin_type: str
    origin_id: str = ""
    session_id: str = ""
    turn_id: str = ""
