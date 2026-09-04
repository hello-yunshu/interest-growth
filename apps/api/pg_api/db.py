from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
import os
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from pg_shared import get_settings

def now_utc() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class SchemaMigration(Base):
    """Single current-schema marker; historical versions are not supported."""
    __tablename__ = "schema_migrations"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PluginStateModel(Base):
    __tablename__ = "plugin_states"
    plugin_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    installed_version: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(32), default="enabled", nullable=False)
    previous_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class FeatureFlagModel(Base):
    __tablename__ = "feature_flags"
    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class DomainPackModel(Base):
    __tablename__ = "domain_packs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    description: Mapped[str] = mapped_column(Text, default="")
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    default_capabilities: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    default_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_personas: Mapped[list[str]] = mapped_column(JSON, default=list)
    builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MasteryProfileModel(Base):
    __tablename__ = "mastery_profiles"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    domain_pack_id: Mapped[str] = mapped_column(ForeignKey("domain_packs.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    states: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class InterestAreaModel(Base):
    __tablename__ = "interest_areas"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    domain_pack_id: Mapped[str] = mapped_column(ForeignKey("domain_packs.id"), index=True)
    mastery_profile_id: Mapped[str] = mapped_column(String(120), default="")
    icon: Mapped[str] = mapped_column(String(80), default="sparkles")
    accent: Mapped[str] = mapped_column(String(40), default="neutral")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class AreaCapabilitySettingModel(Base):
    __tablename__ = "area_capability_settings"
    __table_args__ = (UniqueConstraint("area_id", "plugin_id", name="uq_area_capability"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    area_id: Mapped[str] = mapped_column(ForeignKey("interest_areas.id"), index=True)
    plugin_id: Mapped[str] = mapped_column(String(160), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(32), default="domain_default")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class EntityAreaBindingModel(Base):
    __tablename__ = "entity_area_bindings"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "area_id", name="uq_entity_area_binding"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    area_id: Mapped[str] = mapped_column(ForeignKey("interest_areas.id"), index=True)
    sharing: Mapped[str] = mapped_column(String(24), default="private", index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PersonaScopeModel(Base):
    __tablename__ = "persona_scopes"
    __table_args__ = (UniqueConstraint("persona_id", "scope_type", "scope_id", name="uq_persona_scope"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(ForeignKey("tutor_personas.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(32), default="domain_pack", index=True)
    scope_id: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class LearningActivityModel(Base):
    __tablename__ = "learning_activities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    area_id: Mapped[str] = mapped_column(ForeignKey("interest_areas.id"), index=True)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    activity_type: Mapped[str] = mapped_column(String(48), default="practice", index=True)
    objective: Mapped[str] = mapped_column(Text, default="")
    artifact_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    self_assessment: Mapped[str] = mapped_column(Text, default="")
    feedback: Mapped[str] = mapped_column(Text, default="")
    observation: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class GroundingRefModel(Base):
    __tablename__ = "grounding_refs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    area_id: Mapped[str] = mapped_column(ForeignKey("interest_areas.id"), index=True)
    owner_type: Mapped[str] = mapped_column(String(48), index=True)
    owner_id: Mapped[str] = mapped_column(String(80), index=True)
    ref_type: Mapped[str] = mapped_column(String(48), index=True)
    ref_id: Mapped[str] = mapped_column(String(80), index=True)
    role: Mapped[str] = mapped_column(String(40), default="grounding")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class QuestionModel(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    source_context: Mapped[str] = mapped_column(Text, default="")
    interest_level: Mapped[int] = mapped_column(Integer, default=3)
    state: Mapped[str] = mapped_column(String(32), default="captured", index=True)
    energy_mode: Mapped[str] = mapped_column(String(16), default="normal")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    returned_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class TopicModel(Base):
    __tablename__ = "topics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    interest_boundary: Mapped[str] = mapped_column(String(32), default="topic")
    competence_boundary: Mapped[str] = mapped_column(String(48), default="learning_only")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class SourceModel(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="web")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publisher: Mapped[str] = mapped_column(String(300), default="")
    doi: Mapped[str] = mapped_column(String(160), default="")
    pmid: Mapped[str] = mapped_column(String(80), default="")
    isbn: Mapped[str] = mapped_column(String(80), default="")
    canonical_url: Mapped[str] = mapped_column(Text, default="")
    local_file: Mapped[str] = mapped_column(Text, default="")
    full_text_available: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_summary_only: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EvidenceModel(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(60), default="summary")
    excerpt_or_summary: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(String(300), default="")
    supports_claim: Mapped[bool] = mapped_column(Boolean, default=True)
    strength: Mapped[str] = mapped_column(String(32), default="unknown")
    limitations: Mapped[str] = mapped_column(Text, default="")
    verification_state: Mapped[str] = mapped_column(String(32), default="unverified")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ClaimModel(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source_level: Mapped[str] = mapped_column(String(32), default="mixed")
    publishability: Mapped[str] = mapped_column(String(40), default="internal_only")
    verification_state: Mapped[str] = mapped_column(String(32), default="unverified")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ClaimVersionModel(Base):
    __tablename__ = "claim_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    contradicting_evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    limitations: Mapped[str] = mapped_column(Text, default="")
    reason_for_revision: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ConceptModel(Base):
    __tablename__ = "concepts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    definition: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list[str]] = mapped_column(JSON, default=list)
    counterexamples: Mapped[list[str]] = mapped_column(JSON, default=list)
    confused_with: Mapped[list[str]] = mapped_column(JSON, default=list)
    related_claims: Mapped[list[str]] = mapped_column(JSON, default=list)
    related_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MasteryRecordModel(Base):
    __tablename__ = "mastery_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    state: Mapped[str] = mapped_column(String(40), default="unfamiliar")
    evidence_note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class DomainEventRecordModel(Base):
    __tablename__ = "domain_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    subscriber_errors: Mapped[list[str]] = mapped_column(JSON, default=list)


class GrowthEventModel(Base):
    __tablename__ = "growth_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class GrowthMemoryModel(Base):
    __tablename__ = "growth_memory"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    layer: Mapped[str] = mapped_column(String(20), index=True)  # g1_raw | g2_structured | g3_long_term
    memory_type: Mapped[str] = mapped_column(String(80), index=True)
    key: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ReflectionModel(Base):
    __tablename__ = "reflections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    period_start: Mapped[str] = mapped_column(String(20), default="")
    period_end: Mapped[str] = mapped_column(String(20), default="")
    attracted_question: Mapped[str] = mapped_column(Text, default="")
    interest_drain: Mapped[str] = mapped_column(Text, default="")
    understanding_change: Mapped[str] = mapped_column(Text, default="")
    continue_topic: Mapped[str] = mapped_column(Text, default="")
    next_energy_mode: Mapped[str] = mapped_column(String(16), default="normal")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PracticeItemModel(Base):
    __tablename__ = "practice_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(40), default="open")
    options: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(40), default="")
    origin: Mapped[str] = mapped_column(String(40), default="local")
    upstream_session_id: Mapped[str] = mapped_column(String(160), default="")
    upstream_turn_id: Mapped[str] = mapped_column(String(160), default="")
    upstream_question_id: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PracticeAttemptModel(Base):
    __tablename__ = "practice_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    practice_item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id"), index=True)
    tutor_session_id: Mapped[str | None] = mapped_column(ForeignKey("tutor_sessions.id"), nullable=True, index=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="")
    evidence_promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MasteryEvidenceModel(Base):
    __tablename__ = "mastery_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), default="practice_attempt")
    reference_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    verified_by_user: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidation_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class LearningNoteModel(Base):
    __tablename__ = "learning_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, default="")
    note_type: Mapped[str] = mapped_column(String(40), default="learning_note")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    upstream_notebook_id: Mapped[str] = mapped_column(String(160), default="")
    upstream_record_id: Mapped[str] = mapped_column(String(160), default="")
    sync_status: Mapped[str] = mapped_column(String(32), default="local_only")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class TutorPersonaModel(Base):
    __tablename__ = "tutor_personas"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    upstream_name: Mapped[str] = mapped_column(String(80), default="")
    sync_status: Mapped[str] = mapped_column(String(32), default="local_only")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class WritingDocumentModel(Base):
    __tablename__ = "writing_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class WritingRevisionModel(Base):
    __tablename__ = "writing_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("writing_documents.id"), index=True)
    instruction: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(32), default="rewrite")
    tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    selected_text: Mapped[str] = mapped_column(Text, default="")
    replacement_text: Mapped[str] = mapped_column(Text, default="")
    selection_start: Mapped[int] = mapped_column(Integer, default=0)
    selection_end: Mapped[int] = mapped_column(Integer, default=0)
    base_sha256: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="proposed", index=True)
    engine: Mapped[str] = mapped_column(String(48), default="")
    upstream_operation_id: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LivingBookModel(Base):
    __tablename__ = "living_books"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    intent: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    knowledge_base_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    upstream_book_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    projection_status: Mapped[str] = mapped_column(String(32), default="local_only")
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    spine_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class LivingBookChapterModel(Base):
    __tablename__ = "living_book_chapters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    book_id: Mapped[str] = mapped_column(ForeignKey("living_books.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    source_refs: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="current", index=True)
    stale_reason: Mapped[str] = mapped_column(Text, default="")
    upstream_page_id: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class TutorSessionModel(Base):
    __tablename__ = "tutor_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    upstream_session_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    knowledge_base_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    skill_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    persona_name: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class TutorTurnModel(Base):
    __tablename__ = "tutor_turns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tutor_session_id: Mapped[str] = mapped_column(ForeignKey("tutor_sessions.id"), index=True)
    capability: Mapped[str] = mapped_column(String(80), default="chat", index=True)
    upstream_turn_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized_events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    answer_text: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pending_input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapabilityRunModel(Base):
    __tablename__ = "capability_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    engine: Mapped[str] = mapped_column(String(80), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeBaseModel(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    rag_provider: Mapped[str] = mapped_column(String(48), default="native-lexical")
    upstream_name: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), default="local_only", index=True)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class KnowledgeSourceIndexModel(Base):
    __tablename__ = "knowledge_source_indexes"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "source_id", name="uq_knowledge_source_mapping"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_base_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    upstream_file_name: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    task_id: Mapped[str] = mapped_column(String(160), default="")
    parse_preview: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(48), default="native-lexical")
    error: Mapped[str] = mapped_column(Text, default="")
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class KnowledgeIngestionRunModel(Base):
    __tablename__ = "knowledge_ingestion_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_base_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(48), default="native-lexical")
    operation: Mapped[str] = mapped_column(String(32), default="sync")
    upstream_task_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    task_identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RetrievalCandidateModel(Base):
    __tablename__ = "retrieval_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    capability_run_id: Mapped[str | None] = mapped_column(ForeignKey("capability_runs.id"), nullable=True, index=True)
    tutor_turn_id: Mapped[str | None] = mapped_column(ForeignKey("tutor_turns.id"), nullable=True, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text, default="")
    upstream_file_name: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="candidate_not_evidence", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CareerExperimentModel(Base):
    __tablename__ = "career_experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    direction: Mapped[str] = mapped_column(String(120), index=True)
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    experiment: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    interest_before: Mapped[int] = mapped_column(Integer, default=3)
    interest_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competence_boundary: Mapped[str] = mapped_column(String(48), default="learning_only")
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    reflection: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class OwnerModel(Base):
    """Single-owner account. Exactly one row exists once bootstrapped.

    Only the salted password hash is stored; the raw password never leaves
    the enrollment/login request. The database itself enforces the singleton
    through the unique `singleton` marker so that concurrent bootstraps can
    never create more than one owner.
    """

    __tablename__ = "auth_owners"
    __table_args__ = (UniqueConstraint("singleton", name="ux_auth_owners_singleton"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    singleton: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class DeviceModel(Base):
    """A named, revocable registered device (one device session)."""

    __tablename__ = "auth_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(40), default="")
    app_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class DeviceAccessTokenModel(Base):
    """Short-lived access credential. Stores only a SHA-256 digest."""

    __tablename__ = "auth_access_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("auth_devices.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeviceRefreshTokenModel(Base):
    """Rotated per-device renewal credential. Stores only a SHA-256 digest.

    Refresh rotates the credential: issuing a new one invalidates the
    previous one unless it was already replaced.
    """

    __tablename__ = "auth_refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("auth_devices.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class SecurityEventModel(Base):
    """Bounded, audit-safe authentication metadata. Never credentials/bodies."""

    __tablename__ = "security_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("auth_devices.id"), nullable=True, index=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    detail_json: Mapped[dict[str, Any]] = mapped_column("detail", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)


class ServerMetadataModel(Base):
    """Single-row, stable server identity (v0.7 Gate C).

    ``server_instance_id`` is a random, unguessable but non-secret UUID that is
    generated exactly once when the row is first created. It is never derived
    from hostname, password or tokens, is preserved across restarts and
    backup/restore, and is never regenerated after initialization. The unique
    ``singleton`` marker enforces exactly one row, mirroring the single-owner
    invariant used by ``auth_owners``.
    """

    __tablename__ = "server_metadata"
    __table_args__ = (UniqueConstraint("singleton", name="ux_server_metadata_singleton"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    server_instance_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    server_display_name: Mapped[str] = mapped_column(String(120), default="Interest Growth Server")
    singleton: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


DEFAULT_SERVER_DISPLAY_NAME = "Interest Growth Server"


_engine = None
_SessionLocal = None
_current_url = None


def get_engine(database_url: str | None = None):
    global _engine, _SessionLocal, _current_url
    url = database_url or get_settings().database_url
    if _engine is None or _current_url != url:
        if url.startswith("sqlite"):
            # check_same_thread: FastAPI serves requests on multiple threads.
            # timeout: SQLite is a single-writer database; concurrent refresh
            # rotations must wait for the writer instead of failing instantly.
            kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}}
        else:
            kwargs = {}
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
        _current_url = url
    return _engine


def get_session_factory(database_url: str | None = None):
    get_engine(database_url)
    return _SessionLocal


def _table_exists(engine, name: str) -> bool:
    return name in inspect(engine).get_table_names()


def _create_native_execution_tables(engine) -> None:
    """Create the current native execution tables for a fresh database."""
    statements = (
        """
        CREATE TABLE native_tutor_checkpoint (
            id TEXT PRIMARY KEY,
            area_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            state TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 0,
            user_message TEXT NOT NULL,
            assistant_text TEXT NOT NULL DEFAULT '',
            selected_capability TEXT,
            wait_payload_json TEXT,
            execution_snapshot_json TEXT,
            parent_run_id TEXT,
            host_session_id TEXT,
            host_turn_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX idx_native_checkpoint_area_session ON native_tutor_checkpoint(area_id, session_id)",
        """
        CREATE UNIQUE INDEX uq_native_active_turn_per_session
        ON native_tutor_checkpoint(area_id, session_id)
        WHERE state IN ('running', 'waiting_input')
        """,
        """
        CREATE TABLE native_run_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES native_tutor_checkpoint(id) ON DELETE CASCADE,
            area_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_native_event_run ON native_run_event(run_id, seq)",
        """
        CREATE TABLE native_aux_memory (
            id TEXT PRIMARY KEY,
            area_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            source_run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX idx_native_aux_memory_area_session ON native_aux_memory(area_id, session_id, created_at)",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _ensure_server_identity(db) -> ServerMetadataModel:
    """Return the single server identity row, creating it exactly once."""
    row = db.scalar(select(ServerMetadataModel).limit(1))
    if row is None:
        row = ServerMetadataModel(
            server_instance_id=str(uuid4()),
            server_display_name=get_settings().server_display_name,
        )
        db.add(row)
        db.flush()
    return row


def get_server_identity() -> dict[str, str]:
    """Stable, non-secret server identity for API responses (Gate C).

    The identity is generated once on first initialization (fresh install or
    current schema marker), never changes across restarts or backup/restore, and is
    never derived from hostname or credentials. A concurrent first call is
    collapsed by the unique singleton index.
    """
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        row = db.scalar(select(ServerMetadataModel).limit(1))
        if row is None:
            row = ServerMetadataModel(
                server_instance_id=str(uuid4()),
                server_display_name=get_settings().server_display_name,
            )
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = db.scalar(select(ServerMetadataModel).limit(1))
        return {
            "server_instance_id": row.server_instance_id,
            "server_display_name": row.server_display_name,
        }


CURRENT_SCHEMA_VERSION = 15


def init_db(database_url: str | None = None) -> None:
    from .scoping import install_area_scoping_hooks
    install_area_scoping_hooks()
    engine = get_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    if "schema_migrations" not in tables and tables:
        raise RuntimeError(
            "existing database format is unsupported by this release; "
            "create a fresh current database"
        )
    fresh = not tables
    if fresh:
        # This release is current-schema-only: unsupported database formats fail closed.
        Base.metadata.create_all(engine)
        _create_native_execution_tables(engine)
        with get_session_factory(database_url)() as db:
            db.info["skip_area_scope"] = True
            _ensure_server_identity(db)
            db.add(SchemaMigration(version=CURRENT_SCHEMA_VERSION))
            db.commit()
        from .domains import seed_domain_packs_and_default_area
        seed_domain_packs_and_default_area()
        return

    with get_session_factory(database_url)() as db:
        versions = {int(v) for v in db.scalars(select(SchemaMigration.version)).all()}
    if versions != {CURRENT_SCHEMA_VERSION}:
        raise RuntimeError(
            "existing database format is unsupported by this release; "
            "create a fresh current database"
        )


def reset_engine_for_tests() -> None:
    global _engine, _SessionLocal, _current_url
    if _engine is not None:
        _engine.dispose()
    _engine = _SessionLocal = _current_url = None


def db_dependency():
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
