from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from pg_domain import EnergyMode, MasteryState, Publishability, QuestionState, VerificationState


class QuestionCreate(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    source_context: str = ""
    interest_level: int = Field(default=3, ge=1, le=5)
    energy_mode: EnergyMode = EnergyMode.NORMAL
    notes: str = ""


class QuestionUpdate(BaseModel):
    question: str | None = None
    source_context: str | None = None
    interest_level: int | None = Field(default=None, ge=1, le=5)
    energy_mode: EnergyMode | None = None
    notes: str | None = None
    state: QuestionState | None = None


class QuickExploreRequest(BaseModel):
    focus: str = ""


class TopicCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str = ""
    question_id: str | None = None


class SourceCreate(BaseModel):
    topic_id: str | None = None
    source_type: str = "web"
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    publisher: str = ""
    doi: str = ""
    pmid: str = ""
    isbn: str = ""
    canonical_url: str = ""
    ai_summary_only: bool = False
    notes: str = ""


class SourceInvalidationRequest(BaseModel):
    reason: str = Field(default="source verification revoked", min_length=2, max_length=1000)


class EvidenceCreate(BaseModel):
    source_id: str
    evidence_type: str = "summary"
    excerpt_or_summary: str = Field(min_length=2)
    location: str = ""
    supports_claim: bool = True
    strength: str = "unknown"
    limitations: str = ""
    verification_state: VerificationState = VerificationState.UNVERIFIED


class ClaimCreate(BaseModel):
    topic_id: str
    statement: str = Field(min_length=2)
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    limitations: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    publishability: Publishability = Publishability.INTERNAL_ONLY


class ClaimRevisionCreate(BaseModel):
    statement: str = Field(min_length=2)
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    limitations: str = ""
    reason_for_revision: str = Field(min_length=2)
    confidence: float | None = Field(default=None, ge=0, le=1)
    publishability: Publishability | None = None


class ConceptCreate(BaseModel):
    topic_id: str | None = None
    name: str
    definition: str = ""
    examples: list[str] = Field(default_factory=list)
    counterexamples: list[str] = Field(default_factory=list)
    confused_with: list[str] = Field(default_factory=list)
    related_claims: list[str] = Field(default_factory=list)
    related_sources: list[str] = Field(default_factory=list)


class MasteryUpdate(BaseModel):
    state: str = Field(min_length=1, max_length=40)
    evidence_note: str = ""


class ReflectionCreate(BaseModel):
    period_start: str = ""
    period_end: str = ""
    attracted_question: str = ""
    interest_drain: str = ""
    understanding_change: str = ""
    continue_topic: str = ""
    next_energy_mode: EnergyMode = EnergyMode.NORMAL
    notes: str = ""


class ResearchRequest(BaseModel):
    topic_id: str | None = None
    question: str = Field(min_length=2)
    depth: str = Field(default="normal", pattern="^(light|normal|deep|standard)$")
    persist_sources: bool = True
    knowledge_base_ids: list[str] = Field(default_factory=list)
    use_domain_skills: bool = True


class GroundingRefInput(BaseModel):
    ref_type: str = Field(pattern="^(claim|source|note|practice|activity|book_chapter|artifact|project)$")
    ref_id: str = Field(min_length=1, max_length=80)
    role: str = "grounding"


class ContentPackRequest(BaseModel):
    topic_id: str
    claim_ids: list[str] = Field(default_factory=list)
    grounding_refs: list[GroundingRefInput] = Field(default_factory=list)
    target_audience: str = ""
    platform: str = "xhs"
    format: str = "cards"


class ContentGuardRequest(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class CardRenderRequest(BaseModel):
    topic_id: str | None = None
    layout: str = Field(default="three_points", pattern="^(cover|three_points|comparison|evidence|checklist|closing)$")
    title: str
    points: list[str] = Field(default_factory=list, max_length=6)
    footer: str = "人工审核后发布"


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = ""
    rag_provider: str = Field(
        default="native-lexical",
        pattern="^(native-lexical|native-lightgraph|native-concept-graph|native-heading|llamaindex|pageindex|graphrag|lightrag)$",
    )


class KnowledgeBaseUpdate(BaseModel):
    description: str | None = None
    rag_provider: str | None = Field(
        default=None,
        pattern="^(native-lexical|native-lightgraph|native-concept-graph|native-heading|llamaindex|pageindex|graphrag|lightrag)$",
    )


class KnowledgeRetrieveRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    use_evidence_skill: bool = True


class LearningAssistRequest(BaseModel):
    knowledge_base_ids: list[str] = Field(default_factory=list)
    focus: str = ""


class CareerExperimentCreate(BaseModel):
    direction: str = Field(min_length=2, max_length=120)
    hypothesis: str = ""
    experiment: str = ""
    interest_before: int = Field(default=3, ge=1, le=5)
    competence_boundary: str = "learning_only"


class CareerExperimentUpdate(BaseModel):
    evidence: str | None = None
    interest_after: int | None = Field(default=None, ge=1, le=5)
    competence_boundary: str | None = None
    status: str | None = Field(default=None, pattern="^(planned|active|paused|completed|abandoned)$")
    reflection: str | None = None


class FeatureFlagUpdate(BaseModel):
    enabled: bool


class TutorSessionCreate(BaseModel):
    title: str = Field(default="", max_length=300)
    topic_id: str | None = None
    concept_id: str | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list)
    skill_names: list[str] = Field(default_factory=list)
    persona_name: str = Field(default="", max_length=80)


class TutorSessionContextUpdate(BaseModel):
    knowledge_base_ids: list[str] | None = None
    skill_names: list[str] | None = None
    persona_name: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=300)


class InterestAreaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")
    description: str = ""
    domain_pack_id: str = "general"
    icon: str = "sparkles"
    accent: str = "neutral"


class InterestAreaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    icon: str | None = None
    accent: str | None = None
    archived: bool | None = None


class AreaCapabilityUpdate(BaseModel):
    enabled: bool


class LearningActivityCreate(BaseModel):
    topic_id: str | None = None
    activity_type: str = Field(default="practice", max_length=48)
    objective: str = ""
    artifact_refs: list[str] = Field(default_factory=list)
    self_assessment: str = ""
    feedback: str = ""
    observation: str = ""
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    status: str = Field(default="completed", pattern="^(planned|active|paused|completed|abandoned)$")
