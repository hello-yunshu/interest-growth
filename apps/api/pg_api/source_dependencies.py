from __future__ import annotations

"""Canonical source dependency propagation for invalidation and deletion."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .db import (
    ArtifactModel,
    ClaimModel,
    ClaimVersionModel,
    EvidenceModel,
    GroundingRefModel,
    KnowledgeIngestionRunModel,
    KnowledgeSourceIndexModel,
    LivingBookChapterModel,
    LivingBookModel,
    RetrievalCandidateModel,
    SourceModel,
)


def _refs_contain(values: Any, wanted: set[str]) -> bool:
    if not values:
        return False
    if isinstance(values, dict):
        return any(_refs_contain(value, wanted) for value in values.values())
    if isinstance(values, (list, tuple, set)):
        return any(str(value) in wanted or _refs_contain(value, wanted) for value in values)
    return str(values) in wanted


def invalidate_source_dependencies(db, source_id: str, *, reason: str) -> dict[str, list[str]]:
    """Invalidate every downstream object that is grounded in ``source_id``.

    This function intentionally does not delete anything. Both the user-facing
    invalidate and delete paths call it so verification state cannot diverge.
    Relationships are followed through Evidence, ClaimVersion and GroundingRef
    records; IDs embedded in unrelated fields are not treated as dependencies.
    """
    evidence_rows = list(db.scalars(select(EvidenceModel).where(EvidenceModel.source_id == source_id)).all())
    evidence_ids = {row.id for row in evidence_rows}
    affected_evidence = [row.id for row in evidence_rows]
    affected_claims: list[str] = []
    affected_artifacts: list[str] = []
    affected_books: list[str] = []
    affected_chapters: list[str] = []

    for evidence in evidence_rows:
        evidence.verified = False
        evidence.verification_state = "source_identified"

    for claim in db.scalars(select(ClaimModel)).all():
        versions = db.scalars(select(ClaimVersionModel).where(ClaimVersionModel.claim_id == claim.id)).all()
        if not any(
            evidence_ids.intersection(set(version.supporting_evidence or []) | set(version.contradicting_evidence or []))
            for version in versions
        ):
            continue
        claim.status = "draft"
        claim.verification_state = "unverified"
        claim.last_verified_at = None
        affected_claims.append(claim.id)

    # GroundingRef is the canonical artifact dependency. A claim ref is also
    # invalidated when that claim depends on this source.
    claim_ids = set(affected_claims)
    artifact_refs = db.scalars(select(GroundingRefModel).where(GroundingRefModel.owner_type == "artifact")).all()
    for ref in artifact_refs:
        if ref.ref_type != "source" and not (ref.ref_type == "claim" and ref.ref_id in claim_ids):
            continue
        artifact = db.get(ArtifactModel, ref.owner_id)
        if artifact is None:
            continue
        metadata = dict(artifact.metadata_json or {})
        metadata["review_needed"] = True
        metadata["review_reason"] = reason
        artifact.metadata_json = metadata
        artifact.approved_at = None
        artifact.human_review_required = True
        if artifact.id not in affected_artifacts:
            affected_artifacts.append(artifact.id)

    for book in db.scalars(select(LivingBookModel)).all():
        if any(
            _refs_contain(chapter.source_refs, {source_id})
            for chapter in db.scalars(select(LivingBookChapterModel).where(LivingBookChapterModel.book_id == book.id)).all()
        ):
            book.status = "stale"
            affected_books.append(book.id)

    for chapter in db.scalars(select(LivingBookChapterModel)).all():
        if _refs_contain(chapter.source_refs, {source_id}) or any(
            claim_id in list((chapter.source_refs or {}).get("claims") or []) for claim_id in claim_ids
        ):
            chapter.status = "stale"
            chapter.stale_reason = reason
            affected_chapters.append(chapter.id)

    return {
        "evidence_ids": affected_evidence,
        "claim_ids": affected_claims,
        "artifact_ids": affected_artifacts,
        "book_ids": affected_books,
        "chapter_ids": affected_chapters,
    }


def remove_source_derivatives(db, source_id: str) -> dict[str, Any]:
    """Remove source-owned derivatives after dependency invalidation."""
    mappings = list(db.scalars(select(KnowledgeSourceIndexModel).where(KnowledgeSourceIndexModel.source_id == source_id)).all())
    candidates = list(db.scalars(select(RetrievalCandidateModel).where(RetrievalCandidateModel.source_id == source_id)).all())
    evidence = list(db.scalars(select(EvidenceModel).where(EvidenceModel.source_id == source_id)).all())
    now = datetime.now(UTC)
    for run in db.scalars(select(KnowledgeIngestionRunModel)).all():
        if source_id in (run.source_ids or []):
            run.state = "failed"
            run.error = "source deleted"
            run.completed_at = now
    for row in [*mappings, *candidates, *evidence]:
        db.delete(row)
    db.query(GroundingRefModel).filter(
        GroundingRefModel.ref_type == "source", GroundingRefModel.ref_id == source_id
    ).delete(synchronize_session=False)
    return {
        "mappings": len(mappings),
        "candidates": len(candidates),
        "evidence": len(evidence),
        "knowledge_base_ids": sorted({row.knowledge_base_id for row in [*mappings, *candidates]}),
    }
