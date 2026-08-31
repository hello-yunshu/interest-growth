from __future__ import annotations

from fastapi import HTTPException

from .db import FeatureFlagModel, get_session_factory

DEFAULT_FLAGS = {
    "FEATURE_TUTOR_RUNTIME": True,
    "FEATURE_PRACTICE": True,
    "FEATURE_LEARNING_NOTEBOOK": True,
    "FEATURE_TUTOR_PERSONA": True,
    "FEATURE_CO_WRITER": True,
    "FEATURE_LIVING_BOOK": True,
    "FEATURE_MEMORY_GRAPH": True,
    "FEATURE_DEEP_RESEARCH": True,
    "FEATURE_KNOWLEDGE_RAG": True,
    "FEATURE_GROWTH_FEEDBACK": True,
    "FEATURE_FLEXIBLE_MASTERY": True,
    "FEATURE_CONCEPT_GRAPH": True,
    "FEATURE_CONTENT_STUDIO": True,
    "FEATURE_MEDIA_PROMPT": True,
    "FEATURE_LOCAL_CARD_RENDERER": True,
    "FEATURE_VISUALIZE": True,
    "FEATURE_CAREER": True,
}


def seed_feature_flags() -> None:
    with get_session_factory()() as db:
        for name, enabled in DEFAULT_FLAGS.items():
            if db.get(FeatureFlagModel, name) is None:
                db.add(FeatureFlagModel(name=name, enabled=enabled))
        db.commit()


def feature_enabled(name: str) -> bool:
    with get_session_factory()() as db:
        row = db.get(FeatureFlagModel, name)
        return bool(row and row.enabled)


def require_feature(name: str) -> None:
    if not feature_enabled(name):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "feature_disabled",
                "feature": name,
                "detail": f"Feature {name} is disabled",
                "recoverable": True,
            },
        )
