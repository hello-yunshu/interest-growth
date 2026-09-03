from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from pg_domain import CapabilityStatus

from ..content import get_storage
from ..db import (
    ArtifactModel,
    CapabilityRunModel,
    ClaimModel,
    ClaimVersionModel,
    ConceptModel,
    EvidenceModel,
    EntityAreaBindingModel,
    MasteryRecordModel,
    MasteryEvidenceModel,
    PracticeAttemptModel,
    PracticeItemModel,
    SourceModel,
    TopicModel,
    get_session_factory,
)
from ..events import emit
from ..features import feature_enabled, require_feature
from interest_growth_native.errors import ProviderUnavailable, ProviderExecutionError
from ..native_execution import get_native_bundle, resolve_native_context
from ..plugins import require_plugin_access
from ..schemas import ConceptCreate, ConceptUpdate, LearningAssistRequest, MasteryUpdate
from ..visuals import build_visual_manifest
from ..serializers import model_dict
from ..domains import (current_mastery_profile, filter_rows_to_current_area, get_domain_context, require_entity_in_current_area)

router = APIRouter(tags=["learning-growth"])


def _find_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("report", "content", "answer", "response", "text", "final_answer"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
        for child in value.values():
            found = _find_text(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_text(child)
            if found:
                return found
    return ""


def _concept_context(concept: ConceptModel, mastery: MasteryRecordModel | None, focus: str) -> str:
    return (
        f"概念：{concept.name}\n"
        f"当前定义：{concept.definition or '待完善'}\n"
        f"例子：{concept.examples}\n反例：{concept.counterexamples}\n"
        f"易混淆：{concept.confused_with}\n"
        f"当前掌握度：{mastery.state if mastery else 'unfamiliar'}\n"
        f"已有掌握证据：{mastery.evidence_note if mastery else ''}\n"
        f"本次关注：{focus or '帮助我理解、练习、区分、迁移，并明确当前边界'}"
    )


def _save_run(
    *,
    topic_id: str | None,
    capability: str,
    engine: str,
    status: str,
    input_json: dict[str, Any],
    output_json: dict[str, Any],
    limitations: list[str] | None = None,
) -> CapabilityRunModel:
    row = CapabilityRunModel(
        topic_id=topic_id,
        capability=capability,
        engine=engine,
        status=status,
        input_json=input_json,
        output_json=output_json,
        limitations=limitations or [],
        completed_at=datetime.now(UTC),
    )
    with get_session_factory()() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.post("/concepts")
def create_concept(body: ConceptCreate):
    require_plugin_access("capability.mastery", read=("topic",), write=("concept", "mastery"))
    require_feature("FEATURE_FLEXIBLE_MASTERY")
    with get_session_factory()() as db:
        if body.topic_id and not db.get(TopicModel, body.topic_id):
            raise HTTPException(404, "topic not found")
        if body.topic_id:
            try:
                require_entity_in_current_area(db, "topic", body.topic_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        row = ConceptModel(**body.model_dump())
        db.add(row)
        db.flush()
        profile = current_mastery_profile(db)
        initial_state = (profile.states or ["unfamiliar"])[0]
        mastery = MasteryRecordModel(concept_id=row.id, state=initial_state)
        db.add(mastery)
        db.commit()
        db.refresh(row)
        db.refresh(mastery)
        return {"concept": model_dict(row), "mastery": model_dict(mastery)}


@router.get("/concepts")
def list_concepts(topic_id: str | None = None, include_archived: bool = False):
    require_plugin_access("capability.mastery", read=("concept", "mastery"))
    with get_session_factory()() as db:
        stmt = select(ConceptModel).order_by(ConceptModel.updated_at.desc()).limit(200)
        if not include_archived:
            stmt = stmt.where(ConceptModel.status == "active")
        if topic_id:
            stmt = stmt.where(ConceptModel.topic_id == topic_id)
        output = []
        for concept in filter_rows_to_current_area(db, db.scalars(stmt).all(), "concept"):
            mastery = db.scalar(select(MasteryRecordModel).where(MasteryRecordModel.concept_id == concept.id))
            output.append({"concept": model_dict(concept), "mastery": model_dict(mastery) if mastery else None})
        return {"concepts": output}


@router.put("/concepts/{concept_id}/mastery")
def update_mastery(concept_id: str, body: MasteryUpdate):
    require_plugin_access("capability.mastery", read=("concept", "mastery"), write=("mastery",))
    require_feature("FEATURE_FLEXIBLE_MASTERY")
    with get_session_factory()() as db:
        concept = db.get(ConceptModel, concept_id)
        if not concept:
            raise HTTPException(404, "concept not found")
        try:
            require_entity_in_current_area(db, "concept", concept_id)
        except ValueError as exc:
            raise HTTPException(404, "concept not found in current area") from exc
        profile = current_mastery_profile(db)
        states = list(profile.states or [])
        if body.state not in states:
            raise HTTPException(400, {"code": "invalid_mastery_state", "allowed": states, "profile": profile.id})
        mastery = db.scalar(select(MasteryRecordModel).where(MasteryRecordModel.concept_id == concept_id))
        if mastery is None:
            old_state = states[0] if states else "unfamiliar"
            mastery = MasteryRecordModel(concept_id=concept_id, state=body.state)
            db.add(mastery)
        else:
            old_state = mastery.state
            mastery.state = body.state
        if body.evidence_note is not None:
            mastery.evidence_note = body.evidence_note
        db.commit()
        db.refresh(mastery)
    old_index = states.index(old_state) if old_state in states else -1
    new_index = states.index(body.state) if body.state in states else old_index
    emit(
        "mastery.updated",
        {
            "concept_id": concept_id,
            "concept_name": concept.name,
            "from": old_state,
            "to": body.state,
            "increased": new_index > old_index,
            "profile": profile.id,
            "evidence_note": mastery.evidence_note,
        },
    )
    return model_dict(mastery)


async def _concept_assist(concept_id: str, body: LearningAssistRequest, capability: str, request: Request):
    with get_session_factory()() as db:
        concept = db.get(ConceptModel, concept_id)
        if not concept:
            raise HTTPException(404, "concept not found")
        try:
            require_entity_in_current_area(db, "concept", concept_id)
        except ValueError as exc:
            raise HTTPException(404, "concept not found in current area") from exc
        mastery = db.scalar(select(MasteryRecordModel).where(MasteryRecordModel.concept_id == concept_id))
        topic_id = concept.topic_id
        concept_text = _concept_context(concept, mastery, body.focus)
        current_stage = mastery.state if mastery else current_mastery_profile(db).states[0]
    # Resolve the guard outside the degradation boundary. Feature/plugin/area/
    # permission errors are product decisions and must fail closed, never become
    # a misleading degraded success.
    native_context = resolve_native_context(request, "learning.run")
    try:
        if capability == "mastery_path":
            native = get_native_bundle().learning.mastery_path(
                native_context, goal=concept.name, current_stage=current_stage,
            )
            result = {
                "text": f"当前阶段：{native.current_stage}；建议下一步：{native.suggested_next}",
                "path": asdict(native),
                "knowledge_bases": list(body.knowledge_base_ids),
                "skills": list(get_domain_context().skills),
            }
        elif capability == "deep_question":
            native = get_native_bundle().learning.deep_question(
                native_context, concept=concept_text, stage=current_stage,
            )
            result = {
                "text": native.question,
                "rationale": native.rationale,
                "expected_evidence": list(native.expected_evidence),
                "knowledge_bases": list(body.knowledge_base_ids),
                "skills": list(get_domain_context().skills),
            }
        else:
            raise ValueError(capability)
        row = _save_run(
            topic_id=topic_id,
            capability=f"native-{capability}",
            engine="native.interest-growth",
            status=CapabilityStatus.COMPLETED.value,
            input_json={"concept_id": concept_id, **body.model_dump()},
            output_json=result,
            limitations=["学习辅助输出不会自动改变 Host 的 Mastery 状态。"],
        )
        return {"run": model_dict(row), "result": result, "warnings": []}
    except (ProviderUnavailable, ProviderExecutionError) as exc:
        fallback = {
            "text": "原生学习辅助暂不可用；本地 Mastery 记录保持不变，可继续阅读、练习、项目或人工学习。",
            "degraded": True,
            "reason": type(exc).__name__,
        }
        row = _save_run(
            topic_id=topic_id,
            capability=f"native-{capability}",
            engine="local-fallback",
            status=CapabilityStatus.DEGRADED.value,
            input_json={"concept_id": concept_id, **body.model_dump()},
            output_json=fallback,
            limitations=[str(exc)[:300]],
        )
        return {"run": model_dict(row), "result": fallback}


@router.post("/concepts/{concept_id}/guided-path")
async def guided_path(concept_id: str, body: LearningAssistRequest, request: Request):
    return await _concept_assist(concept_id, body, "mastery_path", request)


@router.post("/concepts/{concept_id}/deep-question")
async def deep_question(concept_id: str, body: LearningAssistRequest, request: Request):
    return await _concept_assist(concept_id, body, "deep_question", request)


@router.put("/concepts/{concept_id}")
def update_concept(concept_id: str, body: ConceptUpdate):
    require_plugin_access("capability.mastery", read=("concept", "topic", "claim", "source"), write=("concept",))
    with get_session_factory()() as db:
        concept = db.get(ConceptModel, concept_id)
        if concept is None:
            raise HTTPException(404, "concept not found")
        try:
            require_entity_in_current_area(db, "concept", concept_id)
        except ValueError as exc:
            raise HTTPException(404, "concept not found in current area") from exc
        values = body.model_dump(exclude_unset=True)
        if "topic_id" in values and values["topic_id"]:
            topic = db.get(TopicModel, values["topic_id"])
            if topic is None:
                raise HTTPException(404, "topic not found")
            try:
                require_entity_in_current_area(db, "topic", values["topic_id"])
            except ValueError as exc:
                raise HTTPException(409, "topic not found in current area") from exc
        for field, entity_type in (("related_claims", "claim"), ("related_sources", "source")):
            if field in values:
                ids = list(dict.fromkeys(str(x) for x in values[field]))
                for entity_id in ids:
                    try:
                        require_entity_in_current_area(db, entity_type, entity_id)
                    except ValueError as exc:
                        raise HTTPException(409, {"code": "area_scope_mismatch", "entity_type": entity_type, "entity_id": entity_id}) from exc
                values[field] = ids
        for field, value in values.items():
            setattr(concept, field, value)
        db.commit()
        db.refresh(concept)
        return model_dict(concept)


@router.post("/concepts/{concept_id}/archive")
def archive_concept(concept_id: str):
    require_plugin_access("capability.mastery", read=("concept",), write=("concept",))
    with get_session_factory()() as db:
        concept = db.get(ConceptModel, concept_id)
        if not concept:
            raise HTTPException(404, "concept not found")
        try:
            require_entity_in_current_area(db, "concept", concept_id)
        except ValueError as exc:
            raise HTTPException(404, "concept not found in current area") from exc
        concept.status = "archived"
        db.commit(); db.refresh(concept)
        return model_dict(concept)


@router.post("/concepts/{concept_id}/restore")
def restore_concept(concept_id: str):
    require_plugin_access("capability.mastery", read=("concept",), write=("concept",))
    with get_session_factory()() as db:
        concept = db.get(ConceptModel, concept_id)
        if not concept:
            raise HTTPException(404, "concept not found")
        try:
            require_entity_in_current_area(db, "concept", concept_id)
        except ValueError as exc:
            raise HTTPException(404, "concept not found in current area") from exc
        concept.status = "active"
        db.commit(); db.refresh(concept)
        return model_dict(concept)


@router.delete("/concepts/{concept_id}")
def delete_concept(concept_id: str, force: bool = False):
    require_plugin_access("capability.mastery", read=("concept", "mastery", "practice_item", "mastery_evidence"), write=("concept", "mastery", "practice_item", "mastery_evidence"))
    with get_session_factory()() as db:
        concept = db.get(ConceptModel, concept_id)
        if not concept:
            raise HTTPException(404, "concept not found")
        try:
            require_entity_in_current_area(db, "concept", concept_id)
        except ValueError as exc:
            raise HTTPException(404, "concept not found in current area") from exc
        mastery = db.scalar(select(MasteryRecordModel).where(MasteryRecordModel.concept_id == concept_id))
        practice = db.scalars(select(PracticeItemModel).where(PracticeItemModel.concept_id == concept_id)).all()
        evidence = db.scalars(select(MasteryEvidenceModel).where(MasteryEvidenceModel.concept_id == concept_id)).all()
        dependencies = {
            "mastery": bool(mastery),
            "practice_items": len(practice),
            "mastery_evidence": len(evidence),
            "related_claims": len(concept.related_claims or []),
            "related_sources": len(concept.related_sources or []),
        }
        if any(dependencies.values()) and not force:
            raise HTTPException(409, {"code": "concept_has_dependencies", "dependencies": dependencies, "detail": "Archive the concept or explicitly confirm cascade deletion."})
        if force:
            for item in practice:
                for attempt in db.scalars(select(PracticeAttemptModel).where(PracticeAttemptModel.practice_item_id == item.id)).all():
                    db.delete(attempt)
                db.delete(item)
            if mastery:
                db.delete(mastery)
            for row in evidence:
                db.delete(row)
        db.query(EntityAreaBindingModel).filter(
            EntityAreaBindingModel.entity_type == "concept",
            EntityAreaBindingModel.entity_id == concept_id,
        ).delete(synchronize_session=False)
        db.delete(concept)
        db.commit()
    return {"id": concept_id, "deleted": True, "dependencies": dependencies}


@router.post("/concepts/{concept_id}/visualize")
async def visualize_concept(concept_id: str, body: LearningAssistRequest, request: Request):
    require_feature("FEATURE_VISUALIZE")
    with get_session_factory()() as db:
        concept = db.get(ConceptModel, concept_id)
        if not concept:
            raise HTTPException(404, "concept not found")
        try:
            require_entity_in_current_area(db, "concept", concept_id)
        except ValueError as exc:
            raise HTTPException(404, "concept not found in current area") from exc
        topic_id = concept.topic_id
        mastery = db.scalar(select(MasteryRecordModel).where(MasteryRecordModel.concept_id == concept_id))
        concept_text = _concept_context(concept, mastery, body.focus)
    native_context = resolve_native_context(request, "visualize.run")
    try:
        visual = get_native_bundle().visualize.plan(
            native_context, title=concept.name, content=concept_text, kind="concept_map",
        )
        raw = visual.spec
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    artifact_id = str(uuid4())
    manifest = build_visual_manifest(
        raw, concept_id=concept.id, concept_name=concept.name, knowledge_bases=body.knowledge_base_ids
    )
    base = f"visualize/{artifact_id}"
    key = f"{base}/manifest.json"
    get_storage().put_text(key, json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    get_storage().put_text(f"{base}/raw.json", json.dumps(raw, ensure_ascii=False, indent=2, default=str))
    artifact = ArtifactModel(
        id=artifact_id,
        topic_id=topic_id,
        kind="visual_explanation",
        key=key,
        title=f"原生可视化 · {concept.name}",
        metadata_json={
            "provider": "native.interest-growth",
            "capability": "visualize",
            "concept_id": concept.id,
            "base": base,
            "preview_kind": manifest["preview_kind"],
            "asset_count": len(manifest["assets"]),
            "warnings": [],
        },
        human_review_required=True,
    )
    with get_session_factory()() as db:
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
    emit("artifact.created", {"artifact_id": artifact.id, "kind": artifact.kind})
    return {"artifact": model_dict(artifact), "result": raw, "warnings": []}


@router.get("/graph")
def concept_graph(topic_id: str | None = None):
    require_plugin_access("capability.concept-graph", read=("concept", "claim", "claim_version", "evidence", "source"))
    require_feature("FEATURE_CONCEPT_GRAPH")
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    with get_session_factory()() as db:
        concept_stmt = select(ConceptModel)
        claim_stmt = select(ClaimModel)
        source_stmt = select(SourceModel)
        if topic_id:
            concept_stmt = concept_stmt.where(ConceptModel.topic_id == topic_id)
            claim_stmt = claim_stmt.where(ClaimModel.topic_id == topic_id)
            source_stmt = source_stmt.where(SourceModel.topic_id == topic_id)
        concepts = filter_rows_to_current_area(db, db.scalars(concept_stmt).all(), "concept")
        claims = filter_rows_to_current_area(db, db.scalars(claim_stmt).all(), "claim")
        sources = filter_rows_to_current_area(db, db.scalars(source_stmt).all(), "source")
        source_ids = {x.id for x in sources}
        for c in concepts:
            nodes.append({"id": c.id, "type": "concept", "label": c.name})
            for related in c.related_claims:
                edges.append({"from": c.id, "to": related, "type": "related_claim"})
            for related in c.related_sources:
                edges.append({"from": c.id, "to": related, "type": "related_source"})
            for confused in c.confused_with:
                virtual_id = f"confused:{confused}"
                nodes.append({"id": virtual_id, "type": "concept_hint", "label": confused})
                edges.append({"from": c.id, "to": virtual_id, "type": "confused_with"})
        for claim in claims:
            version = db.get(ClaimVersionModel, claim.current_version_id) if claim.current_version_id else None
            nodes.append({
                "id": claim.id,
                "type": "claim",
                "label": version.statement if version else claim.id,
                "verification_state": claim.verification_state,
            })
            if version:
                for eid in version.supporting_evidence:
                    evidence = db.get(EvidenceModel, eid)
                    if evidence:
                        evidence_node = f"evidence:{eid}"
                        nodes.append({"id": evidence_node, "type": "evidence", "label": evidence.excerpt_or_summary[:100]})
                        edges.append({"from": evidence_node, "to": claim.id, "type": "supports"})
                        edges.append({"from": evidence.source_id, "to": evidence_node, "type": "contains"})
                for eid in version.contradicting_evidence:
                    evidence = db.get(EvidenceModel, eid)
                    if evidence:
                        evidence_node = f"evidence:{eid}"
                        nodes.append({"id": evidence_node, "type": "evidence", "label": evidence.excerpt_or_summary[:100]})
                        edges.append({"from": evidence_node, "to": claim.id, "type": "contradicts"})
                        edges.append({"from": evidence.source_id, "to": evidence_node, "type": "contains"})
        for source in sources:
            nodes.append({"id": source.id, "type": "source", "label": source.title, "verified": source.verified})
    # de-dupe nodes because one Evidence can be used by several Claims.
    dedup = {node["id"]: node for node in nodes}
    return {"nodes": list(dedup.values()), "edges": edges}


@router.get("/visual-artifacts/{artifact_id}/preview")
def visual_artifact_preview(artifact_id: str):
    require_plugin_access("capability.concept-graph", read=("artifact",))
    require_feature("FEATURE_VISUALIZE")
    with get_session_factory()() as db:
        row = db.get(ArtifactModel, artifact_id)
        if not row or row.kind not in {"visual_explanation", "concept_map"}:
            raise HTTPException(404, "visual artifact not found")
        try:
            require_entity_in_current_area(db, "artifact", artifact_id)
        except ValueError as exc:
            raise HTTPException(404, "visual artifact not found in current area") from exc
    try:
        manifest = json.loads(get_storage().read_text(row.key))
    except Exception as exc:
        raise HTTPException(409, "visual manifest missing or unreadable") from exc
    return {"artifact": model_dict(row), "manifest": manifest}
