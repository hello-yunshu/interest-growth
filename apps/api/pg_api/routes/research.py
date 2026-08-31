from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from pg_domain import CapabilityStatus
from interest_growth_native.research import ResearchSubtopic
from interest_growth_native.errors import ProviderExecutionError, ProviderUnavailable

from ..db import (
    CapabilityRunModel,
    ClaimModel,
    ClaimVersionModel,
    EvidenceModel,
    KnowledgeBaseModel,
    SourceModel,
    TopicModel,
    get_session_factory,
)
from ..engines import ManualResearchEngine
from ..domains import get_domain_context, filter_rows_to_current_area, require_entity_in_current_area
from ..events import emit
from ..features import require_feature
from ..plugins import require_plugin_access
from ..native_execution import get_native_bundle, resolve_native_context
from ..review import review_claim
from ..schemas import (
    ClaimCreate,
    ClaimRevisionCreate,
    EvidenceCreate,
    ResearchRequest,
    SourceCreate,
    SourceInvalidationRequest,
)
from ..serializers import model_dict

router = APIRouter(tags=["research-evidence"])


def _resolve_knowledge_base_ids(ids: list[str]) -> tuple[list[str], list[str]]:
    if not ids:
        return [], []
    with get_session_factory()() as db:
        resolved: list[str] = []
        warnings: list[str] = []
        for kb_id in ids:
            kb = db.get(KnowledgeBaseModel, kb_id)
            if not kb:
                raise HTTPException(400, {"code": "unknown_knowledge_base", "id": kb_id})
            try:
                require_entity_in_current_area(db, "knowledge_base", kb_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            resolved.append(kb.id)
            if kb.status != "ready":
                warnings.append(f"Knowledge base {kb.name} status={kb.status}; retrieval may be incomplete.")
        return resolved, warnings


def _resolve_domain_skills(enabled: bool) -> tuple[list[str], list[str]]:
    context = get_domain_context()
    requested = list(context.skills)
    if not enabled or not requested:
        return [], []
    return requested, []


def _approved_outline(plan: dict, question: str, depth: str):
    """Convert the reviewed UI snapshot into the exact native run input."""
    refined = str(plan.get("question") or plan.get("brief") or question).strip()
    topics = []
    for item in plan.get("subquestions") or []:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("question") or "").strip()
            overview = str(item.get("overview") or "").strip()
        else:
            title, overview = str(item).strip(), ""
        if title:
            topics.append(ResearchSubtopic(title, overview))
    if len(topics) < 2:
        raise HTTPException(422, {"code": "validation_error", "detail": "approved_plan needs at least two subquestions"})
    snapshot = dict(plan)
    snapshot.update({"question": refined, "depth": depth, "approved": True})
    return refined, tuple(topics[:8]), snapshot



@router.post("/research/plan")
async def create_research_plan(body: ResearchRequest, request: Request):
    require_feature("FEATURE_DEEP_RESEARCH")
    try:
        context = resolve_native_context(request, "research.run")
        if body.approved_plan:
            refined, approved_topics, approved_snapshot = _approved_outline(body.approved_plan, body.question, body.depth)
            preview = type("ApprovedPreview", (), {
                "refined_topic": refined,
                "subtopics": approved_topics,
                "status": "approved_by_user",
                "clarification_questions": (),
            })()
        else:
            preview = get_native_bundle().research.preview_outline(
                context, question=body.question, max_subtopics=5 if body.depth == "deep" else 3,
            )
            approved_snapshot = None
        kb_ids, kb_warnings = _resolve_knowledge_base_ids(body.knowledge_base_ids)
        skills, skill_warnings = _resolve_domain_skills(body.use_domain_skills)
        plan = {
            "question": preview.refined_topic,
            "brief": preview.refined_topic,
            "subquestions": [x.title for x in preview.subtopics],
            "desired_sources": ["local knowledge", "primary/original material", "counter-evidence"],
            "knowledge_bases": kb_ids,
            "skills": skills,
            "depth": body.depth,
            "clarification_questions": list(preview.clarification_questions),
            "review_status": preview.status,
        }
        if approved_snapshot:
            plan = {**approved_snapshot, **plan, "subquestions": [x.title for x in approved_topics]}
        status = {"engine": "native.interest-growth", "degraded": False, "warnings": kb_warnings + skill_warnings}
    except HTTPException:
        raise
    except (ProviderUnavailable, ProviderExecutionError):
        # Provider failure may keep the planning workspace usable, but a disabled
        # product gate never enters this branch.
        engine = ManualResearchEngine({"domain_name": get_domain_context().domain_name, "research": get_domain_context().research})
        plan = await engine.create_plan(body.question, body.depth)
        status = {"engine": "manual-workspace", "degraded": True, "reason": "engine planning failed"}
        plan = asdict(plan)
    return {"plan": plan, "engine_status": status}


@router.post("/research/run")
async def run_research(body: ResearchRequest, request: Request):
    require_feature("FEATURE_DEEP_RESEARCH")
    if body.topic_id:
        with get_session_factory()() as db:
            if not db.get(TopicModel, body.topic_id):
                raise HTTPException(404, "topic not found")
            try:
                require_entity_in_current_area(db, "topic", body.topic_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    # Validate local product-owned references before persisting a RUNNING capability row.
    # A bad KB id is a request error, not an upstream execution failure, and must never
    # leave a stranded run in the ledger.
    kb_ids, kb_warnings = _resolve_knowledge_base_ids(body.knowledge_base_ids)
    skills, skill_warnings = _resolve_domain_skills(body.use_domain_skills)

    engine_status = {"engine": "native.interest-growth", "degraded": False}
    run = CapabilityRunModel(
        topic_id=body.topic_id,
        capability="research",
        engine="native.interest-growth",
        status=CapabilityStatus.RUNNING.value,
        input_json=body.model_dump(),
    )
    with get_session_factory()() as db:
        db.add(run)
        db.commit()
        db.refresh(run)

    try:
        context = resolve_native_context(request, "research.run")
        if body.approved_plan:
            refined, approved_topics, approved_snapshot = _approved_outline(body.approved_plan, body.question, body.depth)
            preview = type("ApprovedPreview", (), {
                "refined_topic": refined,
                "subtopics": approved_topics,
                "status": "approved_by_user",
            })()
        else:
            preview = get_native_bundle().research.preview_outline(
                context, question=body.question, max_subtopics=5 if body.depth == "deep" else 3,
            )
            approved_snapshot = None
        result = get_native_bundle().research.run_confirmed(
            context,
            question=preview.refined_topic,
            subtopics=preview.subtopics,
            kb_ids=kb_ids,
            max_queue=8 if body.depth == "deep" else 4,
            outline_status=preview.status,
        )
        plan = {
            "question": preview.refined_topic,
            "brief": preview.refined_topic,
            "subquestions": [x.title for x in preview.subtopics],
            "desired_sources": ["local knowledge", "primary/original material", "counter-evidence"],
            "knowledge_bases": kb_ids,
            "skills": skills,
            "depth": body.depth,
        }
        if approved_snapshot:
            plan = {**approved_snapshot, **plan, "subquestions": [x.title for x in approved_topics]}
        limitations = list(result.limitations) + kb_warnings + skill_warnings
        candidates = list(result.candidates)
        report = result.answer
        provider = "native.interest-growth"
        result_status = CapabilityStatus.DEGRADED.value if result.partial else CapabilityStatus.COMPLETED.value
    except (ProviderUnavailable, ProviderExecutionError) as exc:
        # An unavailable optional LLM transport keeps the product-owned manual workspace usable.
        manual = ManualResearchEngine({"domain_name": get_domain_context().domain_name, "research": get_domain_context().research})
        manual_plan = await manual.create_plan(body.question, body.depth)
        manual_plan.knowledge_bases = kb_ids
        manual_plan.skills = skills
        fallback = await manual.run(manual_plan)
        plan = asdict(manual_plan)
        limitations = list(fallback.limitations) + kb_warnings + skill_warnings + [f"Native execution unavailable: {type(exc).__name__}"]
        candidates = []
        report = fallback.report
        provider = "manual-workspace"
        result_status = CapabilityStatus.DEGRADED.value
        engine_status = {"engine": "manual-workspace", "degraded": True, "reason": type(exc).__name__}

    source_ids: list[str] = []
    if body.persist_sources and candidates:
        with get_session_factory()() as db:
            for candidate in candidates:
                if candidate.get("kind") == "tool_failure":
                    continue
                source = SourceModel(
                    topic_id=body.topic_id,
                    source_type="web" if candidate.get("url") else "local",
                    title=str(candidate.get("title") or candidate.get("filename") or candidate.get("source_id") or "Research candidate"),
                    authors=[],
                    year=None,
                    canonical_url=str(candidate.get("url") or candidate.get("canonical_url") or ""),
                    ai_summary_only=False,
                    verified=False,
                    notes="Candidate source imported from research engine; human verification pending.",
                )
                db.add(source)
                db.flush()
                source_ids.append(source.id)
            db.commit()

    output = {
        "plan": plan,
        "report": report,
        "source_ids": source_ids,
        "source_candidates": candidates,
        "provider": provider,
        "limitations": limitations,
        "upstream_turn_id": "",
    }
    with get_session_factory()() as db:
        row = db.get(CapabilityRunModel, run.id)
        row.engine = provider
        row.status = result_status
        row.output_json = output
        row.limitations = limitations
        row.completed_at = datetime.now(UTC)
        db.commit()
        db.refresh(row)
    emit("research.completed", {"run_id": run.id, "topic_id": body.topic_id, "status": result_status})
    return {"run": model_dict(row), "result": output, "engine_status": engine_status}


@router.get("/research/runs")
def list_runs(topic_id: str | None = None):
    require_plugin_access("capability.research-evidence", read=("capability_run",))
    with get_session_factory()() as db:
        stmt = select(CapabilityRunModel).order_by(CapabilityRunModel.created_at.desc()).limit(100)
        if topic_id:
            stmt = stmt.where(CapabilityRunModel.topic_id == topic_id)
        rows = filter_rows_to_current_area(db, db.scalars(stmt).all(), "capability_run")
        return {"runs": [model_dict(x) for x in rows]}


@router.post("/sources")
def create_source(body: SourceCreate):
    require_plugin_access("capability.research-evidence", read=("topic",), write=("source",))
    with get_session_factory()() as db:
        if body.topic_id and not db.get(TopicModel, body.topic_id):
            raise HTTPException(404, "topic not found")
        if body.topic_id:
            try:
                require_entity_in_current_area(db, "topic", body.topic_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        # Verification is a separate human action. Creation can never smuggle a
        # verified state through request data.
        row = SourceModel(**body.model_dump(), verified=False, verified_at=None)
        db.add(row)
        db.commit()
        db.refresh(row)
        return model_dict(row)


@router.get("/sources")
def list_sources(topic_id: str | None = None):
    require_plugin_access("capability.research-evidence", read=("source",))
    with get_session_factory()() as db:
        stmt = select(SourceModel).order_by(SourceModel.created_at.desc()).limit(200)
        if topic_id:
            stmt = stmt.where(SourceModel.topic_id == topic_id)
        rows = filter_rows_to_current_area(db, db.scalars(stmt).all(), "source")
        return {"sources": [model_dict(x) for x in rows]}


@router.post("/sources/{source_id}/verify")
def verify_source(source_id: str):
    require_plugin_access("capability.research-evidence", read=("source",), write=("source",))
    with get_session_factory()() as db:
        row = db.get(SourceModel, source_id)
        if not row:
            raise HTTPException(404, "source not found")
        try:
            require_entity_in_current_area(db, "source", source_id)
        except ValueError as exc:
            raise HTTPException(404, "source not found in current area") from exc
        row.verified = True
        row.verified_at = datetime.now(UTC)
        row.ai_summary_only = False
        db.commit()
        db.refresh(row)
        return model_dict(row)


@router.post("/sources/{source_id}/invalidate")
def invalidate_source(source_id: str, body: SourceInvalidationRequest):
    """Revoke source verification and transitively require dependent Claims/content to be reviewed again.

    This is intentionally conservative: verification is never sticky when its source-level basis is revoked.
    The source and historical ClaimVersions are retained; only verification state is invalidated.
    """
    require_plugin_access("capability.research-evidence", read=("source", "evidence", "claim", "claim_version"), write=("source", "evidence", "claim"))
    affected_claims: list[str] = []
    affected_evidence: list[str] = []
    with get_session_factory()() as db:
        source = db.get(SourceModel, source_id)
        if not source:
            raise HTTPException(404, "source not found")
        try:
            require_entity_in_current_area(db, "source", source_id)
        except ValueError as exc:
            raise HTTPException(404, "source not found in current area") from exc
        source.verified = False
        source.verified_at = None
        note = f"Verification revoked: {body.reason.strip()}"
        source.notes = (source.notes.rstrip() + "\n" + note).strip() if source.notes else note

        evidence_rows = db.scalars(select(EvidenceModel).where(EvidenceModel.source_id == source_id)).all()
        evidence_ids = {row.id for row in evidence_rows}
        for evidence in evidence_rows:
            evidence.verified = False
            evidence.verification_state = "source_identified"
            affected_evidence.append(evidence.id)

        if evidence_ids:
            claims = db.scalars(select(ClaimModel)).all()
            for claim in claims:
                if not claim.current_version_id:
                    continue
                version = db.get(ClaimVersionModel, claim.current_version_id)
                if not version:
                    continue
                refs = set(version.supporting_evidence or []) | set(version.contradicting_evidence or [])
                if refs.isdisjoint(evidence_ids):
                    continue
                claim.verification_state = "unverified"
                claim.last_verified_at = None
                affected_claims.append(claim.id)
        db.commit()
        db.refresh(source)
        source_payload = model_dict(source)

    for claim_id in affected_claims:
        emit(
            "claim.reverification_required",
            {
                "claim_id": claim_id,
                "source_id": source_id,
                "reason": body.reason.strip(),
            },
        )
    emit(
        "source.invalidated",
        {
            "source_id": source_id,
            "reason": body.reason.strip(),
            "affected_evidence_ids": affected_evidence,
            "affected_claim_ids": affected_claims,
        },
    )
    return {
        "source": source_payload,
        "affected_evidence_ids": affected_evidence,
        "affected_claim_ids": affected_claims,
    }


@router.post("/evidence")
def create_evidence(body: EvidenceCreate):
    require_plugin_access("capability.research-evidence", read=("source",), write=("evidence",))
    with get_session_factory()() as db:
        source = db.get(SourceModel, body.source_id)
        if not source:
            raise HTTPException(404, "source not found")
        try:
            require_entity_in_current_area(db, "source", body.source_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        row = EvidenceModel(**body.model_dump())
        row.verification_state = body.verification_state.value
        row.verified = body.verification_state.value == "human_verified"
        if row.verified and (not source.verified or source.ai_summary_only):
            raise HTTPException(
                409,
                "source must be human-verified original/source-level material before evidence can be human_verified",
            )
        db.add(row)
        db.commit()
        db.refresh(row)
        return model_dict(row)


@router.get("/evidence")
def list_evidence(source_id: str | None = None):
    require_plugin_access("capability.research-evidence", read=("evidence",))
    with get_session_factory()() as db:
        stmt = select(EvidenceModel).order_by(EvidenceModel.created_at.desc()).limit(300)
        if source_id:
            stmt = stmt.where(EvidenceModel.source_id == source_id)
        rows = filter_rows_to_current_area(db, db.scalars(stmt).all(), "evidence")
        return {"evidence": [model_dict(x) for x in rows]}


def _validate_evidence_ids(db, ids: list[str]) -> None:
    missing = [eid for eid in ids if db.get(EvidenceModel, eid) is None]
    if missing:
        raise HTTPException(400, {"code": "unknown_evidence", "ids": missing})
    wrong_area: list[str] = []
    for eid in ids:
        try:
            require_entity_in_current_area(db, "evidence", eid)
        except ValueError:
            wrong_area.append(eid)
    if wrong_area:
        raise HTTPException(409, {"code": "cross_area_evidence_not_allowed", "ids": wrong_area})


@router.post("/claims")
def create_claim(body: ClaimCreate):
    require_plugin_access("capability.research-evidence", read=("topic", "evidence"), write=("claim", "claim_version"))
    with get_session_factory()() as db:
        if not db.get(TopicModel, body.topic_id):
            raise HTTPException(404, "topic not found")
        try:
            require_entity_in_current_area(db, "topic", body.topic_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        _validate_evidence_ids(db, body.supporting_evidence + body.contradicting_evidence)
        claim = ClaimModel(
            topic_id=body.topic_id,
            confidence=body.confidence,
            publishability=body.publishability.value,
            verification_state="unverified",
        )
        db.add(claim)
        db.flush()
        version = ClaimVersionModel(
            claim_id=claim.id,
            version=1,
            statement=body.statement,
            supporting_evidence=body.supporting_evidence,
            contradicting_evidence=body.contradicting_evidence,
            limitations=body.limitations,
            reason_for_revision="initial claim",
        )
        db.add(version)
        db.flush()
        claim.current_version_id = version.id
        db.commit()
        db.refresh(claim)
        db.refresh(version)
    emit("claim.created", {"claim_id": claim.id, "topic_id": claim.topic_id})
    return {"claim": model_dict(claim), "version": model_dict(version)}


@router.get("/claims")
def list_claims(topic_id: str | None = None):
    require_plugin_access("capability.research-evidence", read=("claim", "claim_version"))
    with get_session_factory()() as db:
        stmt = select(ClaimModel).order_by(ClaimModel.updated_at.desc()).limit(200)
        if topic_id:
            stmt = stmt.where(ClaimModel.topic_id == topic_id)
        claims = []
        for claim in filter_rows_to_current_area(db, db.scalars(stmt).all(), "claim"):
            version = db.get(ClaimVersionModel, claim.current_version_id) if claim.current_version_id else None
            claims.append({"claim": model_dict(claim), "current_version": model_dict(version) if version else None})
        return {"claims": claims}


@router.post("/claims/{claim_id}/revisions")
def revise_claim(claim_id: str, body: ClaimRevisionCreate):
    require_plugin_access("capability.research-evidence", read=("claim", "claim_version", "evidence"), write=("claim", "claim_version"))
    with get_session_factory()() as db:
        claim = db.get(ClaimModel, claim_id)
        if not claim:
            raise HTTPException(404, "claim not found")
        try:
            require_entity_in_current_area(db, "claim", claim_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        _validate_evidence_ids(db, body.supporting_evidence + body.contradicting_evidence)
        max_version = db.scalar(
            select(func.max(ClaimVersionModel.version)).where(ClaimVersionModel.claim_id == claim_id)
        ) or 0
        version = ClaimVersionModel(
            claim_id=claim_id,
            version=max_version + 1,
            statement=body.statement,
            supporting_evidence=body.supporting_evidence,
            contradicting_evidence=body.contradicting_evidence,
            limitations=body.limitations,
            reason_for_revision=body.reason_for_revision,
        )
        db.add(version)
        db.flush()
        claim.current_version_id = version.id
        if body.confidence is not None:
            claim.confidence = body.confidence
        if body.publishability is not None:
            claim.publishability = body.publishability.value
        # Verification belongs to the current version, not the Claim identity.
        # Any revision therefore invalidates the previous human verification.
        claim.verification_state = "unverified"
        claim.last_verified_at = None
        db.commit()
        db.refresh(claim)
        db.refresh(version)
    emit("claim.revised", {"claim_id": claim.id, "version": version.version, "reason": body.reason_for_revision})
    return {"claim": model_dict(claim), "version": model_dict(version)}


@router.post("/claims/{claim_id}/skeptic-pass")
def skeptic_pass(claim_id: str):
    require_plugin_access("capability.research-evidence", read=("claim", "claim_version", "evidence", "source"), write=("capability_run",))
    with get_session_factory()() as db:
        claim = db.get(ClaimModel, claim_id)
        if not claim or not claim.current_version_id:
            raise HTTPException(404, "claim not found")
        try:
            require_entity_in_current_area(db, "claim", claim_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        version = db.get(ClaimVersionModel, claim.current_version_id)
        if version is None:
            raise HTTPException(409, "claim current version is missing")
        result = review_claim(db, claim, version)
        run = CapabilityRunModel(
            topic_id=claim.topic_id,
            capability="skeptic-review",
            engine="local-rules",
            status=CapabilityStatus.COMPLETED.value,
            input_json={
                "claim_id": claim.id,
                "version_id": version.id,
                "version": version.version,
            },
            output_json=result,
            limitations=[
                "Deterministic structural review only; it does not replace source reading or human verification."
            ],
            completed_at=datetime.now(UTC),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
    emit(
        "claim.skeptic_reviewed",
        {"claim_id": claim.id, "version": version.version, "status": result["status"], "run_id": run.id},
    )
    return {"review": result, "run": model_dict(run)}


@router.post("/claims/{claim_id}/verify")
def verify_claim(claim_id: str):
    require_plugin_access("capability.research-evidence", read=("claim", "claim_version", "evidence", "source"), write=("claim",))
    with get_session_factory()() as db:
        claim = db.get(ClaimModel, claim_id)
        if not claim or not claim.current_version_id:
            raise HTTPException(404, "claim not found")
        try:
            require_entity_in_current_area(db, "claim", claim_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        version = db.get(ClaimVersionModel, claim.current_version_id)
        if not version.supporting_evidence:
            raise HTTPException(409, "claim has no supporting evidence")
        evidence = [db.get(EvidenceModel, eid) for eid in version.supporting_evidence]
        if not all(ev and ev.verified for ev in evidence):
            raise HTTPException(409, "all supporting evidence must be human_verified")
        source_rows = [db.get(SourceModel, ev.source_id) for ev in evidence if ev]
        if not all(src and src.verified and not src.ai_summary_only for src in source_rows):
            raise HTTPException(409, "all supporting evidence must still point to human-verified source material")
        claim.verification_state = "human_verified"
        claim.last_verified_at = datetime.now(UTC)
        db.commit()
        db.refresh(claim)
    emit("claim.verified", {"claim_id": claim.id})
    return model_dict(claim)


@router.get("/claims/reverification")
def claims_requiring_reverification(stale_days: int = 180):
    """Return Claims whose current evidence chain needs renewed human review.

    Staleness is a review queue signal, not an assertion that the finding is false.
    """
    require_plugin_access("capability.research-evidence", read=("claim", "claim_version", "evidence", "source"))
    stale_days = max(1, min(int(stale_days), 3650))
    cutoff = datetime.now(UTC) - timedelta(days=stale_days)
    items: list[dict] = []
    with get_session_factory()() as db:
        for claim in filter_rows_to_current_area(db, db.scalars(select(ClaimModel).order_by(ClaimModel.updated_at.desc())).all(), "claim"):
            reasons: list[str] = []
            version = db.get(ClaimVersionModel, claim.current_version_id) if claim.current_version_id else None
            if version is None:
                reasons.append("missing_current_version")
            else:
                support = [db.get(EvidenceModel, eid) for eid in (version.supporting_evidence or [])]
                if not support:
                    reasons.append("no_supporting_evidence")
                if any(ev is None or not ev.verified for ev in support):
                    reasons.append("supporting_evidence_not_human_verified")
                sources = [db.get(SourceModel, ev.source_id) for ev in support if ev is not None]
                if any(src is None or not src.verified or src.ai_summary_only for src in sources):
                    reasons.append("source_verification_missing_or_revoked")
            if claim.verification_state != "human_verified":
                reasons.append("claim_not_human_verified")
            if claim.last_verified_at is None:
                reasons.append("never_verified_current_version")
            else:
                verified_at = claim.last_verified_at
                if verified_at.tzinfo is None:
                    verified_at = verified_at.replace(tzinfo=UTC)
                if verified_at < cutoff:
                    reasons.append("verification_stale")
            if reasons:
                items.append({
                    "claim": model_dict(claim),
                    "current_version": model_dict(version) if version else None,
                    "reasons": list(dict.fromkeys(reasons)),
                })
    return {"stale_days": stale_days, "claims": items}


@router.get("/claims/{claim_id}/versions")
def claim_versions(claim_id: str):
    require_plugin_access("capability.research-evidence", read=("claim", "claim_version"))
    with get_session_factory()() as db:
        claim = db.get(ClaimModel, claim_id)
        if claim is None:
            raise HTTPException(404, "claim not found")
        try:
            require_entity_in_current_area(db, "claim", claim_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        rows = db.scalars(
            select(ClaimVersionModel)
            .where(ClaimVersionModel.claim_id == claim_id)
            .order_by(ClaimVersionModel.version)
        ).all()
        return {"versions": [model_dict(x) for x in rows]}
