from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from pg_domain import CapabilityStatus

from ..db import (
    CapabilityRunModel,
    EntityAreaBindingModel,
    KnowledgeBaseModel,
    KnowledgeIngestionRunModel,
    KnowledgeSourceIndexModel,
    RetrievalCandidateModel,
    SourceModel,
    TopicModel,
    get_session_factory,
)
from ..events import emit
from ..domains import filter_rows_to_current_area, require_entity_in_current_area, get_domain_context
from ..features import feature_enabled
from ..knowledge import (
    safe_filename,
    source_file_path,
    store_source_bytes,
    upstream_filename_for,
    upstream_name_for,
)
from ..plugins import require_plugin_access
from ..native_execution import HostKnowledgeResolver, get_native_bundle, resolve_native_context
from ..native_execution import EXACT_RAG_ENGINES
from ..schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeRetrieveRequest
from ..serializers import model_dict

router = APIRouter(tags=["knowledge-rag"])

NATIVE_ENGINES = {"native-lexical", "native-lightgraph", "native-concept-graph", "native-heading"}
_NATIVE_PROVIDERS = [
    {"id": "native-lexical", "name": "Native Lexical", "configured": True, "ingestion_supported": True, "native": True, "description": "内置本地 BM25 风格检索；默认路径，无需外部服务。"},
    {"id": "native-lightgraph", "name": "Native LightGraph", "configured": True, "ingestion_supported": True, "native": True, "description": "内置轻量词项关系图检索。"},
    {"id": "native-concept-graph", "name": "Native Concept Graph", "configured": True, "ingestion_supported": True, "native": True, "description": "内置概念邻接增强检索。"},
    {"id": "native-heading", "name": "Native Heading", "configured": True, "ingestion_supported": True, "native": True, "description": "内置标题结构增强检索。"},
]


def _exact_adapter(provider: str):
    return get_native_bundle().retrieval.registry.exact(provider)


def _require_selectable_engine(provider: str) -> None:
    if provider in NATIVE_ENGINES:
        return
    if provider in EXACT_RAG_ENGINES and _exact_adapter(provider) is not None:
        return
    if provider in EXACT_RAG_ENGINES:
        raise HTTPException(409, detail={
            "code": "requires_review",
            "engine_id": provider,
            "message": "No reviewed exact adapter is configured; silent native substitution is forbidden.",
        })
    raise HTTPException(422, "unknown knowledge engine")


def _require_egress_consent(provider: str, settings: dict | None) -> None:
    if provider not in NATIVE_ENGINES and not bool((settings or {}).get("external_data_egress_confirmed")):
        raise HTTPException(409, detail={
            "code": "external_data_egress_confirmation_required",
            "message": "该检索引擎需要把资料发送到第三方服务处理。首次同步前请明确确认。",
        })


def _provider_catalog() -> list[dict]:
    providers = list(_NATIVE_PROVIDERS)
    registry = get_native_bundle().retrieval.registry
    for engine_id in sorted(EXACT_RAG_ENGINES):
        adapter = registry.exact(engine_id)
        providers.append({
            "id": engine_id,
            "name": engine_id,
            "configured": adapter is not None,
            "ingestion_supported": adapter is not None,
            "native": False,
            "requires_data_egress_confirmation": True,
            "exact_upstream_equivalent": adapter is not None,
            "status": "exact_adapter_available" if adapter is not None else "requires_review",
            "upstream_distribution": getattr(adapter, "upstream_distribution", ""),
            "reviewed_version": getattr(adapter, "reviewed_version", ""),
            "description": (
                "Reviewed exact third-party adapter."
                if adapter is not None else
                "Not configured; this ID will not fall back to a native algorithm."
            ),
        })
    return providers
def _require_knowledge_feature(*, read=(), write=(), risks=()) -> None:
    require_plugin_access("capability.knowledge", read=read, write=write, risks=risks)
    if not feature_enabled("FEATURE_KNOWLEDGE_RAG"):
        raise HTTPException(503, "knowledge/RAG feature disabled")


@router.get("/knowledge/providers")
async def knowledge_providers():
    _require_knowledge_feature()
    return {"engine_available": True, "native_default": "native-lexical", "providers": _provider_catalog()}


@router.get("/knowledge/bases")
def list_knowledge_bases():
    _require_knowledge_feature(read=("knowledge_base", "knowledge_mapping"))
    with get_session_factory()() as db:
        rows = filter_rows_to_current_area(db, db.scalars(select(KnowledgeBaseModel).order_by(KnowledgeBaseModel.created_at.desc())).all(), "knowledge_base")
        output = []
        for row in rows:
            mappings = db.scalars(
                select(KnowledgeSourceIndexModel).where(KnowledgeSourceIndexModel.knowledge_base_id == row.id)
            ).all()
            output.append({
                **model_dict(row),
                "source_count": len(mappings),
                "ready_count": sum(1 for m in mappings if m.status in {"present", "ready"}),
                "mapping_note": "Source mappings do not represent independent RAG indexes; ingestion_runs hold processing truth.",
            })
        return {"knowledge_bases": output}


@router.post("/knowledge/bases")
def create_knowledge_base(body: KnowledgeBaseCreate):
    _require_knowledge_feature(write=("knowledge_base",))
    _require_selectable_engine(body.rag_provider)
    _require_egress_consent(body.rag_provider, {"external_data_egress_confirmed": body.external_data_egress_confirmed})
    with get_session_factory()() as db:
        row = KnowledgeBaseModel(
            name=body.name,
            description=body.description,
            rag_provider=body.rag_provider,
            upstream_name="pending",
            status="local_only",
            settings_json={"external_data_egress_confirmed": body.external_data_egress_confirmed},
        )
        db.add(row)
        db.flush()
        row.upstream_name = upstream_name_for(row.name, row.id)
        db.commit()
        db.refresh(row)
    emit("knowledge_base.created", {"knowledge_base_id": row.id, "provider": row.rag_provider})
    return model_dict(row)


@router.delete("/knowledge/bases/{kb_id}")
def delete_knowledge_base(kb_id: str):
    _require_knowledge_feature(read=("knowledge_base", "knowledge_mapping", "knowledge_ingestion_run", "retrieval_candidate"), write=("knowledge_base", "knowledge_mapping", "knowledge_ingestion_run", "retrieval_candidate"))
    with get_session_factory()() as db:
        kb = db.get(KnowledgeBaseModel, kb_id)
        if not kb: raise HTTPException(404, "knowledge base not found")
        try: require_entity_in_current_area(db, "knowledge_base", kb_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        mappings = db.scalars(select(KnowledgeSourceIndexModel).where(KnowledgeSourceIndexModel.knowledge_base_id == kb_id)).all()
        candidates = db.scalars(select(RetrievalCandidateModel).where(RetrievalCandidateModel.knowledge_base_id == kb_id)).all()
        runs = db.scalars(select(KnowledgeIngestionRunModel).where(KnowledgeIngestionRunModel.knowledge_base_id == kb_id)).all()
        for row in [*mappings, *candidates, *runs]: db.delete(row)
        db.query(EntityAreaBindingModel).filter(EntityAreaBindingModel.entity_type == "knowledge_base", EntityAreaBindingModel.entity_id == kb_id).delete(synchronize_session=False)
        db.delete(kb); db.commit()
    get_native_bundle().retrieval.invalidate(kb_id)
    emit("knowledge_base.deleted", {"knowledge_base_id": kb_id, "source_files_preserved": True})
    return {"id": kb_id, "deleted": True, "source_files_preserved": True, "mappings_deleted": len(mappings), "candidates_deleted": len(candidates)}


@router.put("/knowledge/bases/{kb_id}")
def update_knowledge_base(kb_id: str, body: KnowledgeBaseUpdate):
    _require_knowledge_feature(read=("knowledge_base", "knowledge_mapping"), write=("knowledge_base",))
    with get_session_factory()() as db:
        row = db.get(KnowledgeBaseModel, kb_id)
        if not row:
            raise HTTPException(404, "knowledge base not found")
        try:
            require_entity_in_current_area(db, "knowledge_base", kb_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if body.description is not None:
            row.description = body.description
        if body.rag_provider is not None and body.rag_provider != row.rag_provider:
            _require_selectable_engine(body.rag_provider)
            mapped = db.scalar(
                select(KnowledgeSourceIndexModel).where(
                    KnowledgeSourceIndexModel.knowledge_base_id == row.id,
                    KnowledgeSourceIndexModel.status.in_(["syncing", "present", "processing", "ready"]),
                )
            )
            if mapped:
                raise HTTPException(
                    409,
                    "RAG provider is bound when indexed; create a new knowledge base or rebuild explicitly.",
                )
            row.rag_provider = body.rag_provider
        if body.external_data_egress_confirmed is True:
            settings = dict(row.settings_json or {})
            settings["external_data_egress_confirmed"] = True
            row.settings_json = settings
        db.commit()
        db.refresh(row)
        return model_dict(row)


@router.post("/knowledge/sources/upload")
async def upload_source_file(
    file: UploadFile = File(...),
    topic_id: str = Form(""),
    title: str = Form(""),
    source_type: str = Form("document"),
):
    _require_knowledge_feature(read=("topic",), write=("source",))
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(413, "file exceeds 100 MiB product upload limit")
    topic_ref = topic_id.strip() or None
    # Validate DB references before writing the immutable original file so a bad
    # request cannot leave an orphaned private upload on disk.
    if topic_ref:
        with get_session_factory()() as db:
            if not db.get(TopicModel, topic_ref):
                raise HTTPException(404, "topic not found")
            try:
                require_entity_in_current_area(db, "topic", topic_ref)
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc
    local_key = store_source_bytes(file.filename or "source.bin", content)
    with get_session_factory()() as db:
        row = SourceModel(
            topic_id=topic_ref,
            source_type=source_type,
            title=title.strip() or safe_filename(file.filename or "source"),
            local_file=local_key,
            full_text_available=True,
            verified=False,
            notes="Locally owned source file; the native index is a rebuildable derivative.",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    emit("source.uploaded", {"source_id": row.id, "topic_id": row.topic_id})
    return model_dict(row)


@router.get("/knowledge/sources/{source_id}/file")
def download_source_file(source_id: str):
    _require_knowledge_feature(read=("source",))
    with get_session_factory()() as db:
        source = db.get(SourceModel, source_id)
        if not source:
            raise HTTPException(404, "source not found")
        try:
            require_entity_in_current_area(db, "source", source_id)
            path = source_file_path(source)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if not path.exists():
            raise HTTPException(404, "local source file missing")
        return FileResponse(path, filename=path.name)


@router.post("/knowledge/bases/{kb_id}/sources/{source_id}/link")
def link_source(kb_id: str, source_id: str):
    _require_knowledge_feature(read=("knowledge_base", "source", "knowledge_mapping"), write=("knowledge_mapping",))
    with get_session_factory()() as db:
        kb = db.get(KnowledgeBaseModel, kb_id)
        source = db.get(SourceModel, source_id)
        if not kb or not source:
            raise HTTPException(404, "knowledge base or source not found")
        try:
            require_entity_in_current_area(db, "knowledge_base", kb_id)
            require_entity_in_current_area(db, "source", source_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if not source.local_file:
            raise HTTPException(409, "source has no locally-owned file to index")
        existing = db.scalar(
            select(KnowledgeSourceIndexModel).where(
                KnowledgeSourceIndexModel.knowledge_base_id == kb_id,
                KnowledgeSourceIndexModel.source_id == source_id,
            )
        )
        if existing:
            return model_dict(existing)
        path = source_file_path(source)
        row = KnowledgeSourceIndexModel(
            knowledge_base_id=kb_id,
            source_id=source_id,
            upstream_file_name=upstream_filename_for(source.id, path.name),
            status="linked",
            provider=kb.rag_provider,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    emit("knowledge_source.linked", {"knowledge_base_id": kb_id, "source_id": source_id})
    return model_dict(row)


@router.post("/knowledge/bases/{kb_id}/sources/{source_id}/unlink")
@router.delete("/knowledge/bases/{kb_id}/sources/{source_id}")
def unlink_source(kb_id: str, source_id: str):
    _require_knowledge_feature(read=("knowledge_base", "source", "knowledge_mapping", "retrieval_candidate"), write=("knowledge_mapping", "retrieval_candidate"))
    with get_session_factory()() as db:
        kb = db.get(KnowledgeBaseModel, kb_id); source = db.get(SourceModel, source_id)
        if not kb or not source: raise HTTPException(404, "knowledge base or source not found")
        try:
            require_entity_in_current_area(db, "knowledge_base", kb_id)
            require_entity_in_current_area(db, "source", source_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        mapping = db.scalar(select(KnowledgeSourceIndexModel).where(KnowledgeSourceIndexModel.knowledge_base_id == kb_id, KnowledgeSourceIndexModel.source_id == source_id))
        if mapping: db.delete(mapping)
        candidates = db.scalars(select(RetrievalCandidateModel).where(RetrievalCandidateModel.knowledge_base_id == kb_id, RetrievalCandidateModel.source_id == source_id)).all()
        for candidate in candidates: db.delete(candidate)
        remaining = db.scalar(select(KnowledgeSourceIndexModel.id).where(KnowledgeSourceIndexModel.knowledge_base_id == kb_id))
        kb.status = "ready" if remaining else "local_only"
        db.commit()
    get_native_bundle().retrieval.invalidate(kb_id)
    emit("knowledge_source.unlinked", {"knowledge_base_id": kb_id, "source_id": source_id})
    return {"knowledge_base_id": kb_id, "source_id": source_id, "unlinked": True, "source_file_preserved": True, "candidates_deleted": len(candidates)}


@router.post("/knowledge/bases/{kb_id}/sources/{source_id}/sync")
async def sync_source(kb_id: str, source_id: str, request: Request):
    _require_knowledge_feature(read=("knowledge_base", "source", "knowledge_mapping"), write=("knowledge_mapping", "knowledge_ingestion_run"))
    # Linking is idempotent and makes rebuild semantics explicit before network I/O.
    link_source(kb_id, source_id)
    with get_session_factory()() as db:
        kb = db.get(KnowledgeBaseModel, kb_id)
        provider = kb.rag_provider if kb else ""
        settings = dict(kb.settings_json or {}) if kb else {}
    _require_egress_consent(provider, settings)
    if provider in NATIVE_ENGINES:
        area_id = get_domain_context().area_id
        snapshots = HostKnowledgeResolver().resolve(area_id=area_id, kb_ids=(kb_id,))
        if not snapshots or source_id not in {x.source_id for x in snapshots[0].sources}:
            raise HTTPException(409, "source could not be parsed by the native document parser")
        now = datetime.now(UTC)
        with get_session_factory()() as db:
            mapping = db.scalar(select(KnowledgeSourceIndexModel).where(
                KnowledgeSourceIndexModel.knowledge_base_id == kb_id,
                KnowledgeSourceIndexModel.source_id == source_id,
            ))
            kb = db.get(KnowledgeBaseModel, kb_id)
            run = KnowledgeIngestionRunModel(
                knowledge_base_id=kb_id,
                source_ids=[source_id],
                provider=provider,
                operation="native-parse",
                state="completed",
                task_identity_verified=True,
                progress_json={"mode": "native", "parsed_sources": 1},
                completed_at=now,
            )
            db.add(run)
            mapping.status = "ready"
            mapping.provider = provider
            mapping.task_id = ""
            mapping.error = ""
            mapping.indexed_at = now
            kb.status = "ready"
            kb.last_synced_at = now
            db.commit()
            db.refresh(run)
            mapping_id = mapping.id
        get_native_bundle().retrieval.invalidate(kb_id)
        emit("knowledge_source.native_ready", {"knowledge_base_id": kb_id, "source_id": source_id})
        return {
            "mode": "native",
            "mapping_id": mapping_id,
            "ingestion_run_id": run.id,
            "status": "completed",
            "provider": provider,
        }
    if provider in EXACT_RAG_ENGINES:
        _require_selectable_engine(provider)
        return await rebuild(kb_id, request)
    raise HTTPException(409, "unsupported knowledge engine; select a configured engine and rebuild")


@router.post("/knowledge/bases/{kb_id}/retrieve")
async def retrieve_from_knowledge_base(kb_id: str, body: KnowledgeRetrieveRequest, request: Request):
    """Direct grounded exploration over one Host-owned KB.

    The output is deliberately a retrieval candidate, not Evidence. Promotion into
    Evidence still requires a Source/location check and the human verification path.
    """
    _require_knowledge_feature(read=("knowledge_base", "knowledge_mapping", "source"), write=("capability_run", "retrieval_candidate"))
    with get_session_factory()() as db:
        kb = db.get(KnowledgeBaseModel, kb_id)
        if not kb:
            raise HTTPException(404, "knowledge base not found")
        try:
            require_entity_in_current_area(db, "knowledge_base", kb_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        kb_status = kb.status
        provider = kb.rag_provider
        settings = dict(kb.settings_json or {})
        topic_ids = [
            source.topic_id
            for source in (
                db.get(SourceModel, idx.source_id)
                for idx in db.scalars(
                    select(KnowledgeSourceIndexModel).where(
                        KnowledgeSourceIndexModel.knowledge_base_id == kb_id
                    )
                ).all()
            )
            if source and source.topic_id
        ]
        topic_id = topic_ids[0] if len(set(topic_ids)) == 1 else None
    if provider in NATIVE_ENGINES or provider in EXACT_RAG_ENGINES:
        _require_selectable_engine(provider)
        _require_egress_consent(provider, settings)
        context = resolve_native_context(
            request, "knowledge.external" if provider in EXACT_RAG_ENGINES else "knowledge.read"
        )
        candidates = get_native_bundle().retrieval.retrieve(
            context, kb_ids=(kb_id,), query=body.query, top_k=6
        )
        public = [candidate.public_source() for candidate in candidates]
        output = {
            "knowledge_base_id": kb_id,
            "provider": provider,
            "warnings": [] if kb_status == "ready" else [f"knowledge base status={kb_status}"],
            "evidence_status": "candidate_not_evidence",
            "answer": "",
            "sources": public,
        }
        run = CapabilityRunModel(
            topic_id=topic_id,
            capability="knowledge-retrieve",
            engine="native.interest-growth",
            status=CapabilityStatus.COMPLETED.value,
            input_json={"query": body.query, "knowledge_base_id": kb_id},
            output_json=output,
            limitations=["Retrieval candidates require human review before promotion to Evidence."],
            completed_at=datetime.now(UTC),
        )
        with get_session_factory()() as db:
            db.add(run)
            db.flush()
            rows = []
            for candidate, item in zip(candidates, public):
                location_data = item.get("location") or {}
                location = " · ".join(
                    str(x) for x in (
                        f"p.{location_data.get('page')}" if location_data.get("page") else "",
                        location_data.get("section") or "",
                    ) if x
                )
                row = RetrievalCandidateModel(
                    capability_run_id=run.id,
                    knowledge_base_id=kb_id,
                    source_id=candidate.source_id,
                    query=body.query,
                    upstream_file_name=candidate.filename,
                    location=location,
                    excerpt=candidate.text[:12000],
                    metadata_json=item,
                    status="candidate_not_evidence",
                )
                db.add(row)
                rows.append(row)
            db.commit()
            db.refresh(run)
            for row in rows:
                db.refresh(row)
        output["provenance_candidates"] = [model_dict(x) for x in rows]
        emit("knowledge.retrieved", {"knowledge_base_id": kb_id, "run_id": run.id, "candidate_count": len(rows), "provider": provider})
        return {"run": model_dict(run), "result": output}
    raise HTTPException(409, "unsupported knowledge engine; select a configured engine and rebuild")


@router.get("/knowledge/bases/{kb_id}/indexes")
def list_indexes(kb_id: str):
    _require_knowledge_feature(read=("knowledge_base", "knowledge_mapping", "source"))
    with get_session_factory()() as db:
        if not db.get(KnowledgeBaseModel, kb_id):
            raise HTTPException(404, "knowledge base not found")
        try:
            require_entity_in_current_area(db, "knowledge_base", kb_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        rows = db.scalars(
            select(KnowledgeSourceIndexModel)
            .where(KnowledgeSourceIndexModel.knowledge_base_id == kb_id)
            .order_by(KnowledgeSourceIndexModel.created_at)
        ).all()
        output = []
        for row in rows:
            source = db.get(SourceModel, row.source_id)
            output.append({"index": model_dict(row), "source": model_dict(source) if source else None})
        return {"indexes": output, "semantics": "source_to_kb_mappings_not_independent_indexes"}


@router.post("/knowledge/indexes/{index_id}/refresh")
async def refresh_index(index_id: str):
    _require_knowledge_feature(read=("knowledge_mapping",), write=("knowledge_mapping", "knowledge_ingestion_run"))
    with get_session_factory()() as db:
        index = db.get(KnowledgeSourceIndexModel, index_id)
        if not index:
            raise HTTPException(404, "index mapping not found")
        try:
            require_entity_in_current_area(db, "knowledge_source_index", index_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if index.provider in NATIVE_ENGINES:
            return {
                "index_id": index_id,
                "status": index.status,
                "provider": index.provider,
                "mode": "native-local",
            }
    raise HTTPException(409, "unsupported knowledge index; rebuild with a configured engine")


@router.get("/knowledge/indexes/{index_id}/preview")
async def index_preview(index_id: str):
    _require_knowledge_feature(read=("knowledge_base", "knowledge_mapping", "source"), write=("knowledge_mapping",))
    with get_session_factory()() as db:
        index = db.get(KnowledgeSourceIndexModel, index_id)
        if not index:
            raise HTTPException(404, "index mapping not found")
        try:
            require_entity_in_current_area(db, "knowledge_source_index", index_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        kb = db.get(KnowledgeBaseModel, index.knowledge_base_id)
        if not kb:
            raise HTTPException(404, "knowledge base not found")
        provider = kb.rag_provider
        source = db.get(SourceModel, index.source_id)
        if provider in NATIVE_ENGINES:
            if source is None or not source.local_file:
                raise HTTPException(409, "native source file is unavailable")
            parsed = HostKnowledgeResolver().parser.parse(source_file_path(source))
            preview = parsed.text[:20000]
            index.parse_preview = preview
            db.commit()
            return {
                "index_id": index_id,
                "preview": preview,
                "truncated": len(parsed.text) > len(preview),
                "provider": provider,
                "parser": parsed.parser,
            }
    raise HTTPException(409, "unsupported knowledge index; rebuild with a configured engine")


@router.post("/knowledge/bases/{kb_id}/rebuild")
async def rebuild(kb_id: str, request: Request):
    _require_knowledge_feature(read=("knowledge_base", "knowledge_mapping", "source"), write=("knowledge_base", "knowledge_mapping", "knowledge_ingestion_run"))
    with get_session_factory()() as db:
        kb = db.get(KnowledgeBaseModel, kb_id)
        if not kb: raise HTTPException(404, "knowledge base not found")
        try: require_entity_in_current_area(db, "knowledge_base", kb_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        provider = kb.rag_provider
    if provider in NATIVE_ENGINES or provider in EXACT_RAG_ENGINES:
        _require_selectable_engine(provider)
        area_id = get_domain_context().area_id
        snapshots = HostKnowledgeResolver().resolve(area_id=area_id, kb_ids=(kb_id,))
        if not snapshots or not snapshots[0].sources:
            raise HTTPException(409, "knowledge base has no parseable Host sources")
        source_ids = [x.source_id for x in snapshots[0].sources]
        mode = "native" if provider in NATIVE_ENGINES else "exact-adapter"
        operation = "native-rebuild" if provider in NATIVE_ENGINES else "exact-whole-kb-rebuild"
        context = resolve_native_context(
            request, "knowledge.external" if provider in EXACT_RAG_ENGINES else "knowledge.read"
        )
        now = datetime.now(UTC)
        with get_session_factory()() as db:
            kb = db.get(KnowledgeBaseModel, kb_id)
            run = KnowledgeIngestionRunModel(
                knowledge_base_id=kb_id,
                source_ids=source_ids,
                provider=provider,
                operation=operation,
                state="running",
                task_identity_verified=True,
                progress_json={"mode": mode, "whole_kb": True, "source_count": len(source_ids)},
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            run_id = run.id
        try:
            get_native_bundle().retrieval.invalidate(kb_id)
            get_native_bundle().retrieval.prepare(context, kb_ids=(kb_id,))
        except Exception as exc:
            with get_session_factory()() as db:
                failed = db.get(KnowledgeIngestionRunModel, run_id)
                failed.state = "failed"
                failed.error = f"{type(exc).__name__}: {exc}"[:2000]
                failed.completed_at = datetime.now(UTC)
                db.commit()
            raise HTTPException(503, detail={
                "code": "exact_adapter_failed" if provider in EXACT_RAG_ENGINES else "native_rebuild_failed",
                "engine_id": provider,
                "message": str(exc),
            }) from exc
        with get_session_factory()() as db:
            kb = db.get(KnowledgeBaseModel, kb_id)
            run = db.get(KnowledgeIngestionRunModel, run_id)
            run.state = "completed"
            run.completed_at = now
            for mapping in db.scalars(select(KnowledgeSourceIndexModel).where(
                KnowledgeSourceIndexModel.knowledge_base_id == kb_id,
                KnowledgeSourceIndexModel.source_id.in_(source_ids),
            )).all():
                mapping.status = "ready"
                mapping.provider = provider
                mapping.error = ""
                mapping.indexed_at = now
            kb.status = "ready"
            kb.last_synced_at = now
            db.commit()
            db.refresh(run)
        result = {
            "mode": f"{mode}-rebuild-from-owned-sources",
            "ingestion_run_id": run.id,
            "source_count": len(source_ids),
            "provider": provider,
            "status": "completed",
        }
        emit("knowledge_base.rebuilt", {"knowledge_base_id": kb_id, "source_count": len(source_ids), "provider": provider})
        return result
    raise HTTPException(409, "unsupported knowledge engine; select a configured engine and rebuild")


@router.get("/knowledge/bases/{kb_id}/ingestion-runs")
def list_ingestion_runs(kb_id: str):
    _require_knowledge_feature(read=("knowledge_base", "knowledge_ingestion_run"))
    with get_session_factory()() as db:
        if not db.get(KnowledgeBaseModel, kb_id):
            raise HTTPException(404, "knowledge base not found")
        try:
            require_entity_in_current_area(db, "knowledge_base", kb_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        rows = db.scalars(
            select(KnowledgeIngestionRunModel)
            .where(KnowledgeIngestionRunModel.knowledge_base_id == kb_id)
            .order_by(KnowledgeIngestionRunModel.created_at.desc())
            .limit(100)
        ).all()
        return {"ingestion_runs": [model_dict(x) for x in rows]}


@router.post("/knowledge/ingestion-runs/{run_id}/refresh")
async def refresh_ingestion_run(run_id: str):
    _require_knowledge_feature(read=("knowledge_ingestion_run",), write=("knowledge_ingestion_run", "knowledge_mapping", "knowledge_base"))
    with get_session_factory()() as db:
        run = db.get(KnowledgeIngestionRunModel, run_id)
        if not run: raise HTTPException(404, "ingestion run not found")
        try: require_entity_in_current_area(db, "knowledge_ingestion_run", run_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        if run.provider in NATIVE_ENGINES or run.provider in EXACT_RAG_ENGINES:
            return {
                "ingestion_run_id": run_id,
                "status": run.state,
                "task_identity_verified": run.task_identity_verified,
                "progress": run.progress_json,
                "provider": run.provider,
            }
    raise HTTPException(409, "unsupported ingestion engine")


@router.get("/knowledge/retrieval-candidates")
def retrieval_candidates(capability_run_id: str | None = None, knowledge_base_id: str | None = None):
    _require_knowledge_feature(read=("retrieval_candidate",))
    with get_session_factory()() as db:
        stmt = select(RetrievalCandidateModel).order_by(RetrievalCandidateModel.created_at.desc()).limit(200)
        if capability_run_id:
            stmt = stmt.where(RetrievalCandidateModel.capability_run_id == capability_run_id)
        if knowledge_base_id:
            stmt = stmt.where(RetrievalCandidateModel.knowledge_base_id == knowledge_base_id)
        rows = filter_rows_to_current_area(db, db.scalars(stmt).all(), "retrieval_candidate")
        return {"candidates": [model_dict(x) for x in rows]}
