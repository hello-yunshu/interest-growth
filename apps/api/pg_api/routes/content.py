from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import json
import zipfile
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..content import (
    build_publish_pack,
    maybe_enhance_publish_pack,
    persist_publish_pack,
    publish_guard_for_claim_ids,
    render_svg_card,
    get_storage,
)
from ..db import ArtifactModel, GroundingRefModel, get_session_factory
from ..events import emit
from ..domains import filter_rows_to_current_area, require_entity_in_current_area, resolve_area
from ..features import feature_enabled
from ..plugins import is_plugin_enabled, require_plugin_access
from ..schemas import CardRenderRequest, ContentGuardRequest, ContentPackRequest
from ..serializers import model_dict

router = APIRouter(tags=["content-studio"])


@router.post("/content/packs")
async def create_content_pack(body: ContentPackRequest):
    require_plugin_access("capability.content-studio", read=("topic", "claim", "claim_version", "evidence", "source", "learning_note", "practice_item", "practice_attempt", "learning_activity", "living_book_chapter", "artifact", "project", "grounding_ref"), write=("artifact", "grounding_ref"), risks=("network", "llm"))
    if not feature_enabled("FEATURE_CONTENT_STUDIO"):
        raise HTTPException(503, "content studio disabled")
    try:
        pack = build_publish_pack(
            body.topic_id,
            body.claim_ids,
            body.target_audience,
            body.platform,
            grounding_refs=[x.model_dump() for x in body.grounding_refs],
            include_media_prompts=(
                feature_enabled("FEATURE_MEDIA_PROMPT")
                and is_plugin_enabled("capability.media-prompt")
            ),
        )
        pack = await maybe_enhance_publish_pack(pack)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    pack_id, base = persist_publish_pack(pack)
    artifact = ArtifactModel(
        id=pack_id,
        topic_id=body.topic_id,
        kind="xhs_pack" if body.platform == "xhs" else "article",
        key=f"{base}/publish.json",
        title=pack["title_candidates"][0],
        metadata_json={
            "base": base,
            "risk_count": len(pack["risk_review"]),
            "platform": body.platform,
            "claim_ids": body.claim_ids,
            "grounding_refs": [x.model_dump() for x in body.grounding_refs],
            "domain_pack_id": pack.get("area",{}).get("domain_pack_id"),
            "ready_for_publication": bool(pack.get("ready_for_publication")),
        },
        human_review_required=True,
    )
    with get_session_factory()() as db:
        db.add(artifact)
        db.flush()
        area = resolve_area(db=db)
        for ref in body.grounding_refs:
            db.add(GroundingRefModel(area_id=area.id, owner_type="artifact", owner_id=artifact.id, ref_type=ref.ref_type, ref_id=ref.ref_id, role=ref.role))
        for claim_id in body.claim_ids:
            db.add(GroundingRefModel(area_id=area.id, owner_type="artifact", owner_id=artifact.id, ref_type="claim", ref_id=claim_id, role="evidence"))
        db.commit()
        db.refresh(artifact)
    emit("content.created", {"artifact_id": artifact.id, "topic_id": body.topic_id})
    return {"artifact": model_dict(artifact), "pack": pack}


@router.post("/content/guard")
def run_publish_guard(body: ContentGuardRequest):
    require_plugin_access("capability.content-studio", read=("claim", "claim_version", "evidence", "source"))
    return {"issues": publish_guard_for_claim_ids(body.text, body.claim_ids)}


@router.post("/content/cards/render")
def render_card(body: CardRenderRequest):
    require_plugin_access("capability.media-prompt", read=("topic",), write=("artifact",))
    if not feature_enabled("FEATURE_LOCAL_CARD_RENDERER"):
        raise HTTPException(503, "local card renderer disabled")
    artifact_id = str(uuid4())
    key = f"cards/{artifact_id}.svg"
    svg = render_svg_card(body.title, body.points, body.footer, body.layout)
    get_storage().put_text(key, svg)
    if body.topic_id:
        with get_session_factory()() as db:
            try:
                require_entity_in_current_area(db, 'topic', body.topic_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
    row = ArtifactModel(
        id=artifact_id,
        topic_id=body.topic_id,
        kind="image",
        key=key,
        title=body.title,
        metadata_json={"mime_type": "image/svg+xml", "layout": body.layout},
        human_review_required=True,
    )
    with get_session_factory()() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    emit("artifact.created", {"artifact_id": row.id, "kind": row.kind})
    return {"artifact": model_dict(row), "svg": svg}


@router.get("/artifacts")
def list_artifacts(topic_id: str | None = None, include_archived: bool = False):
    require_plugin_access("capability.content-studio", read=("artifact",))
    with get_session_factory()() as db:
        stmt = select(ArtifactModel).order_by(ArtifactModel.created_at.desc()).limit(200)
        if topic_id:
            stmt = stmt.where(ArtifactModel.topic_id == topic_id)
        if not include_archived:
            stmt = stmt.where(ArtifactModel.status == "active")
        return {"artifacts": [model_dict(x) for x in filter_rows_to_current_area(db, db.scalars(stmt).all(), "artifact")]}


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str):
    require_plugin_access("capability.content-studio", read=("artifact", "grounding_ref"))
    with get_session_factory()() as db:
        row = db.get(ArtifactModel, artifact_id)
        if not row:
            raise HTTPException(404, "artifact not found")
        try:
            require_entity_in_current_area(db, "artifact", artifact_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        payload: dict[str, object] = {"artifact": model_dict(row)}
        refs = db.scalars(select(GroundingRefModel).where(
            GroundingRefModel.owner_type == "artifact",
            GroundingRefModel.owner_id == artifact_id,
        )).all()
        payload["grounding_refs"] = [model_dict(ref) for ref in refs]
        metadata = dict(row.metadata_json or {})
        if row.key and row.kind not in {"export"}:
            try:
                raw = get_storage().read_text(row.key)
                payload["content"] = raw if len(raw) <= 50000 else raw[:50000]
                payload["content_truncated"] = len(raw) > 50000
            except (OSError, UnicodeDecodeError):
                payload["content"] = None
        if metadata.get("mime_type") == "image/svg+xml":
            payload["preview_url"] = f"/api/visual-artifacts/{artifact_id}/preview"
        return payload


@router.post("/artifacts/{artifact_id}/archive")
def archive_artifact(artifact_id: str):
    require_plugin_access("capability.content-studio", read=("artifact",), write=("artifact",))
    with get_session_factory()() as db:
        row = db.get(ArtifactModel, artifact_id)
        if not row:
            raise HTTPException(404, "artifact not found")
        try:
            require_entity_in_current_area(db, "artifact", artifact_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        row.status = "archived"
        db.commit(); db.refresh(row)
        return model_dict(row)


@router.post("/artifacts/{artifact_id}/restore")
def restore_artifact(artifact_id: str):
    require_plugin_access("capability.content-studio", read=("artifact",), write=("artifact",))
    with get_session_factory()() as db:
        row = db.get(ArtifactModel, artifact_id)
        if not row:
            raise HTTPException(404, "artifact not found")
        try:
            require_entity_in_current_area(db, "artifact", artifact_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        row.status = "active"
        db.commit(); db.refresh(row)
        return model_dict(row)


@router.delete("/artifacts/{artifact_id}")
def delete_artifact(artifact_id: str):
    require_plugin_access("capability.content-studio", read=("artifact",), write=("artifact",))
    with get_session_factory()() as db:
        row = db.get(ArtifactModel, artifact_id)
        if not row:
            raise HTTPException(404, "artifact not found")
        try:
            require_entity_in_current_area(db, "artifact", artifact_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        key = row.key
        db.query(GroundingRefModel).filter(
            GroundingRefModel.owner_type == "artifact",
            GroundingRefModel.owner_id == artifact_id,
        ).delete(synchronize_session=False)
        db.delete(row)
        db.commit()
    if key:
        path = get_storage().path_for(key)
        if path.is_file():
            path.unlink()
    emit("artifact.deleted", {"artifact_id": artifact_id})
    return {"id": artifact_id, "deleted": True}


@router.post("/artifacts/{artifact_id}/approve")
def approve_artifact(artifact_id: str):
    require_plugin_access("capability.content-studio", read=("artifact",), write=("artifact",))
    # Human approval is a gate, not an external publish action.
    with get_session_factory()() as db:
        row = db.get(ArtifactModel, artifact_id)
        if not row:
            raise HTTPException(404, "artifact not found")
        try:
            require_entity_in_current_area(db, "artifact", artifact_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if row.kind in {"xhs_pack", "article"}:
            metadata = dict(row.metadata_json or {})
            if metadata.get("review_needed"):
                raise HTTPException(409, "linked Claim was revised; regenerate the pack before approval")
            try:
                pack = json.loads(get_storage().read_text(row.key))
            except Exception as exc:
                raise HTTPException(409, "publish pack is missing or unreadable") from exc
            if not pack.get("ready_for_publication"):
                raise HTTPException(409, "publish guard is blocking this pack; revise claims/evidence first")
        row.approved_at = datetime.now(UTC)
        db.commit()
        db.refresh(row)
    emit("content.approved", {"artifact_id": row.id})
    return {**model_dict(row), "external_publish_performed": False}


@router.get("/artifacts/{artifact_id}/export")
def export_artifact(artifact_id: str):
    require_plugin_access("capability.content-studio", read=("artifact",), write=("artifact",))
    with get_session_factory()() as db:
        row = db.get(ArtifactModel, artifact_id)
        if not row:
            raise HTTPException(404, "artifact not found")
        try:
            require_entity_in_current_area(db, "artifact", artifact_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        metadata = dict(row.metadata_json or {})
        if metadata.get("review_needed"):
            raise HTTPException(409, "artifact needs review because a linked Claim changed")
        if row.human_review_required and row.approved_at is None:
            raise HTTPException(409, "human review approval required before export")
        base = metadata.get("base")
        if not base:
            raise HTTPException(409, "artifact is not an exportable publish pack")
        topic_id = row.topic_id
        title = row.title or "publish-pack"

    base_path = get_storage().path_for(base)
    if not base_path.exists() or not base_path.is_dir():
        raise HTTPException(404, "publish pack files are missing")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(base_path.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(base_path).as_posix())
    payload = buffer.getvalue()
    export_row = ArtifactModel(
        topic_id=topic_id,
        kind="export",
        key=f"exports/{artifact_id}.zip",
        title=f"Export · {title}",
        metadata_json={"source_artifact_id": artifact_id, "size": len(payload)},
        human_review_required=False,
        approved_at=datetime.now(UTC),
    )
    get_storage().put_bytes(export_row.key, payload)
    with get_session_factory()() as db:
        db.add(export_row)
        db.commit()
        db.refresh(export_row)
    emit("artifact.created", {"artifact_id": export_row.id, "kind": "export"})
    filename = f"interest-growth-{artifact_id}.zip"
    return StreamingResponse(
        iter([payload]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
