from enum import StrEnum


class EnergyMode(StrEnum):
    LIGHT = "light"
    NORMAL = "normal"
    DEEP = "deep"


class QuestionState(StrEnum):
    CAPTURED = "captured"
    EXPLORING = "exploring"
    ACTIVE_TOPIC = "active_topic"
    PAUSED = "paused"
    CLOSED = "closed"
    RETURNED = "returned"


class MasteryState(StrEnum):
    UNFAMILIAR = "unfamiliar"
    FAMILIAR = "familiar"
    EXPLAIN = "explain"
    EXAMPLE = "example"
    DISTINGUISH = "distinguish"
    TRANSFER = "transfer"
    EVIDENCE_BOUNDARY = "evidence_boundary"
    STABLE_EXPRESSION = "stable_expression"


MASTERY_ORDER = {
    MasteryState.UNFAMILIAR: 0,
    MasteryState.FAMILIAR: 1,
    MasteryState.EXPLAIN: 2,
    MasteryState.EXAMPLE: 3,
    MasteryState.DISTINGUISH: 4,
    MasteryState.TRANSFER: 5,
    MasteryState.EVIDENCE_BOUNDARY: 6,
    MasteryState.STABLE_EXPRESSION: 7,
}


class VerificationState(StrEnum):
    UNVERIFIED = "unverified"
    AI_SUMMARY_ONLY = "ai_summary_only"
    SOURCE_IDENTIFIED = "source_identified"
    HUMAN_VERIFIED = "human_verified"


class Publishability(StrEnum):
    STABLE = "stable"
    SUPPORTED_WITH_CAUTION = "supported_with_caution"
    LIMITED = "limited"
    CONTROVERSIAL = "controversial"
    INTERNAL_ONLY = "internal_only"
    NOT_PUBLISHABLE = "not_publishable"


class CapabilityStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(StrEnum):
    NOTE = "note"
    RESEARCH_REPORT = "research_report"
    CONCEPT_CARD = "concept_card"
    ARTICLE = "article"
    XHS_PACK = "xhs_pack"
    IMAGE_PROMPT = "image_prompt"
    IMAGE = "image"
    VIDEO_PROMPT = "video_prompt"
    VIDEO = "video"
    CONCEPT_MAP = "concept_map"
    REVIEW = "review"
    EXPORT = "export"
