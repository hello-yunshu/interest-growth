from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.engine import make_url

from interest_growth_native import (
    DomainPolicy,
    KnowledgeBaseSnapshot,
    NativeEngineBundle,
    NativeRunContext,
    PermissionScope,
    SourceLocator,
    SourceTextSnapshot,
    SQLiteExecutionStore,
)
from interest_growth_native.api import create_native_router
from interest_growth_native.capabilities import (
    CAP_BOOK,
    CAP_COWRITER,
    CAP_DEEP_SOLVE,
    CAP_KNOWLEDGE,
    CAP_MASTERY,
    CAP_NOTEBOOK,
    CAP_PRACTICE,
    CAP_RESEARCH,
    CAP_TUTOR,
    CAP_VISUALIZE,
)
from interest_growth_native.parsing import NativeDocumentParser
from interest_growth_native.llm import OpenAICompatibleClient, UnavailableLLM
from pg_shared import get_settings

from .db import (
    EntityAreaBindingModel,
    KnowledgeBaseModel,
    KnowledgeSourceIndexModel,
    SourceModel,
    get_session_factory,
)
from .domains import current_mastery_states, get_domain_context
from .knowledge import source_file_path
from .plugins import get_plugin_runtime, require_capability_operation, require_plugin_access


HOST_TO_NATIVE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "capability.tutor-runtime": (CAP_TUTOR, CAP_DEEP_SOLVE),
    "capability.research-evidence": (CAP_RESEARCH,),
    "capability.knowledge": (CAP_KNOWLEDGE,),
    "capability.mastery": (CAP_MASTERY,),
    "capability.practice": (CAP_PRACTICE,),
    "capability.learning-notebook": (CAP_NOTEBOOK,),
    "capability.co-writer": (CAP_COWRITER,),
    "capability.living-book": (CAP_BOOK,),
    "capability.concept-graph": (CAP_VISUALIZE,),
}

EXACT_RAG_ENGINES = frozenset({"llamaindex", "lightrag", "graphrag", "pageindex"})

OPERATION_POLICIES: dict[str, dict[str, Any]] = {
    "knowledge.read": {
        "plugin": "capability.knowledge",
        "read": ("knowledge_base", "knowledge_mapping", "source"),
        "scope_read": ("knowledge",),
    },
    "knowledge.external": {
        "plugin": "capability.knowledge",
        "feature": "FEATURE_KNOWLEDGE_RAG",
        "read": ("knowledge_base", "knowledge_mapping", "source"),
        "write": ("knowledge_mapping", "knowledge_ingestion_run", "capability_run", "retrieval_candidate"),
        "risks": ("llm", "network"),
        "scope_read": ("knowledge",),
        "scope_risks": ("llm", "network"),
    },
    "research.run": {
        "plugin": "capability.research-evidence",
        "feature": "FEATURE_DEEP_RESEARCH",
        "read": ("knowledge_base", "source", "capability_run"),
        "write": ("capability_run",),
        "risks": ("llm", "network"),
        "scope_read": ("knowledge",),
        "scope_risks": ("llm", "network"),
    },
    "tutor.read": {
        "plugin": "capability.tutor-runtime",
        "feature": "FEATURE_TUTOR_RUNTIME",
        "read": ("tutor_session", "tutor_turn"),
        "scope_read": ("tutor",),
    },
    "tutor.write": {
        "plugin": "capability.tutor-runtime",
        "feature": "FEATURE_TUTOR_RUNTIME",
        "read": (
            "tutor_session", "tutor_turn", "knowledge_base", "knowledge_mapping",
            "source", "auxiliary_agent_memory",
        ),
        "write": ("tutor_session", "tutor_turn", "capability_run"),
        "risks": ("llm", "network"),
        "scope_read": ("tutor", "knowledge", "agent_memory"),
        "scope_write": ("tutor",),
        "scope_risks": ("llm", "network"),
    },
    "learning.run": {
        "plugin": "capability.mastery",
        "feature": "FEATURE_FLEXIBLE_MASTERY",
        "read": ("mastery", "concept", "topic"),
        "write": ("capability_run",),
        "risks": ("llm",),
        "scope_risks": ("llm",),
    },
    "notebook.run": {
        "plugin": "capability.learning-notebook",
        "feature": "FEATURE_LEARNING_NOTEBOOK",
        "read": ("learning_note",),
        "write": ("learning_note",),
    },
    "practice.run": {
        "plugin": "capability.practice",
        "feature": "FEATURE_PRACTICE",
        "read": ("practice_item", "concept", "topic"),
        "write": ("practice_item",),
        "risks": ("llm",),
        "scope_risks": ("llm",),
    },
    "cowriter.run": {
        "plugin": "capability.co-writer",
        "feature": "FEATURE_CO_WRITER",
        "read": ("writing_document", "writing_revision"),
        "write": ("writing_revision",),
        "risks": ("llm",),
        "scope_risks": ("llm",),
    },
    "book.run": {
        "plugin": "capability.living-book",
        "feature": "FEATURE_LIVING_BOOK",
        "read": ("living_book", "living_book_chapter"),
        "write": ("living_book", "living_book_chapter"),
        "risks": ("llm",),
        "scope_risks": ("llm",),
    },
    "visualize.run": {
        "plugin": "capability.concept-graph",
        "feature": "FEATURE_VISUALIZE",
        "read": ("concept",),
        "write": ("artifact", "capability_run"),
    },
    "solve.run": {
        "plugin": "capability.tutor-runtime",
        "read": ("tutor_session", "tutor_turn"),
        "write": ("capability_run",),
        "risks": ("llm",),
        "scope_risks": ("llm",),
    },
    "memory.read": {
        "plugin": "capability.memory-graph",
        "feature": "FEATURE_MEMORY_GRAPH",
        "read": ("auxiliary_agent_memory",),
        "scope_read": ("agent_memory",),
    },
}


def _entity_belongs_to_area(db, entity_type: str, entity_id: str, area_id: str) -> bool:
    direct = db.scalar(select(EntityAreaBindingModel.id).where(
        EntityAreaBindingModel.entity_type == entity_type,
        EntityAreaBindingModel.entity_id == str(entity_id),
        EntityAreaBindingModel.area_id == area_id,
    ))
    if direct:
        return True
    shared = db.scalar(select(EntityAreaBindingModel.id).where(
        EntityAreaBindingModel.entity_type == entity_type,
        EntityAreaBindingModel.entity_id == str(entity_id),
        EntityAreaBindingModel.sharing == "shared",
    ))
    return bool(shared)


class HostKnowledgeResolver:
    """Project Host-owned Sources into read-only native retrieval snapshots."""

    def __init__(self) -> None:
        self.parser = NativeDocumentParser()

    def resolve(self, *, area_id: str, kb_ids) -> tuple[KnowledgeBaseSnapshot, ...]:
        requested = tuple(dict.fromkeys(str(x) for x in kb_ids if str(x).strip()))
        if not requested:
            return ()
        snapshots: list[KnowledgeBaseSnapshot] = []
        with get_session_factory()() as db:
            db.info["skip_area_scope"] = True
            for kb_id in requested:
                kb = db.get(KnowledgeBaseModel, kb_id)
                if kb is None or not _entity_belongs_to_area(db, "knowledge_base", kb_id, area_id):
                    continue
                mappings = db.scalars(select(KnowledgeSourceIndexModel).where(
                    KnowledgeSourceIndexModel.knowledge_base_id == kb_id,
                )).all()
                sources: list[SourceTextSnapshot] = []
                for mapping in mappings:
                    source = db.get(SourceModel, mapping.source_id)
                    if source is None or not _entity_belongs_to_area(db, "source", source.id, area_id):
                        continue
                    parsed_text = ""
                    parser_name = "metadata"
                    filename = source.title or source.id
                    fingerprint_payload = ""
                    original_bytes = b""
                    media_type = ""
                    if source.local_file:
                        path = source_file_path(source)
                        source_bytes = path.read_bytes()
                        parsed = self.parser.parse(path)
                        parsed_text = parsed.text
                        parser_name = parsed.parser
                        filename = path.name
                        fingerprint_payload = hashlib.sha256(source_bytes).hexdigest()
                        if kb.rag_provider in EXACT_RAG_ENGINES:
                            original_bytes = source_bytes
                            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    elif source.notes.strip():
                        parsed_text = source.notes.strip()
                        fingerprint_payload = hashlib.sha256(parsed_text.encode("utf-8")).hexdigest()
                    if not parsed_text.strip():
                        continue
                    sources.append(SourceTextSnapshot(
                        source_id=source.id,
                        area_id=area_id,
                        filename=filename,
                        text=parsed_text,
                        fingerprint=fingerprint_payload,
                        locator=SourceLocator(filename=filename),
                        metadata={
                            "title": source.title,
                            "canonical_url": source.canonical_url,
                            "parser": parser_name,
                            "mapping_id": mapping.id,
                            "verification_state": "verified" if source.verified else "unverified",
                        },
                        original_bytes=original_bytes,
                        media_type=media_type,
                    ))
                kb_fingerprint = hashlib.sha256(
                    "|".join(f"{s.source_id}:{s.fingerprint}" for s in sources).encode("utf-8")
                ).hexdigest()
                snapshots.append(KnowledgeBaseSnapshot(
                    kb_id=kb.id,
                    area_id=area_id,
                    name=kb.name,
                    engine_id=kb.rag_provider,
                    sources=tuple(sources),
                    fingerprint=kb_fingerprint,
                    engine_config=dict(kb.settings_json or {}),
                ))
        return tuple(snapshots)


def _native_capability_sets(area_id: str) -> tuple[frozenset[str], frozenset[str]]:
    runtime = get_plugin_runtime()
    global_caps: set[str] = set()
    area_caps: set[str] = set()
    from .domains import area_capability_enabled

    for host_id, native_ids in HOST_TO_NATIVE_CAPABILITIES.items():
        if runtime.is_enabled(host_id):
            global_caps.update(native_ids)
            if area_capability_enabled(host_id, area_id):
                area_caps.update(native_ids)
    return frozenset(area_caps), frozenset(global_caps)


def _domain_policy() -> DomainPolicy:
    domain = get_domain_context()
    research = domain.research
    content = domain.content
    return DomainPolicy(
        domain_pack_id=domain.domain_pack_id,
        research_instructions=str(research.get("planner_system") or ""),
        research_limitations=tuple(str(x) for x in research.get("limitations") or ()),
        learning_instructions=str(domain.quick_explore.get("system") or ""),
        mastery_profile=tuple(current_mastery_states()),
        content_instructions=str(content.get("factual_claim_policy") or ""),
        safety_instructions="\n".join(str(x) for x in content.get("risk_rules") or ()),
        version=f"{domain.domain_pack_id}:{domain.mastery_profile_id}",
    )


def resolve_native_context(request: Request, operation: str) -> NativeRunContext:
    try:
        policy = OPERATION_POLICIES[operation]
    except KeyError as exc:
        raise ValueError(f"unknown native operation: {operation}") from exc
    require_capability_operation(
        policy["plugin"],
        feature=policy.get("feature"),
        read=policy.get("read", ()),
        write=policy.get("write", ()),
        risks=policy.get("risks", ()),
    )
    domain = get_domain_context()
    area_caps, global_caps = _native_capability_sets(domain.area_id)
    session_id = (
        request.headers.get("X-PG-Native-Session")
        or request.headers.get("X-PG-Tutor-Session")
        or "native-http"
    ).strip()
    return NativeRunContext(
        area_id=domain.area_id,
        session_id=session_id,
        domain_policy=_domain_policy(),
        area_capabilities=area_caps,
        global_capabilities=global_caps,
        permission_scope=PermissionScope(
            resources_read=frozenset(policy.get("scope_read", ())),
            resources_write=frozenset(policy.get("scope_write", ())),
            risks=frozenset(policy.get("scope_risks", ())),
        ),
        metadata={"host_operation": operation, "provider": "native.interest-growth"},
    )


_bundle: NativeEngineBundle | None = None
_bundle_database_url = ""


def _sqlite_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
        raise RuntimeError("native execution currently requires the Host SQLite database")
    if not url.database or url.database == ":memory:":
        raise RuntimeError("native execution requires a persistent Host SQLite database")
    path = Path(url.database)
    return path if path.is_absolute() else path.resolve()


def get_native_bundle(*, refresh: bool = False) -> NativeEngineBundle:
    global _bundle, _bundle_database_url
    settings = get_settings()
    if refresh or _bundle is None or _bundle_database_url != settings.database_url:
        llm = (
            OpenAICompatibleClient(
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
                model=settings.deepseek_model,
                timeout=settings.deepseek_timeout_seconds,
            )
            if settings.deepseek_api_key.strip()
            else UnavailableLLM()
        )
        _bundle = NativeEngineBundle(
            knowledge_resolver=HostKnowledgeResolver(),
            store=SQLiteExecutionStore(_sqlite_path(settings.database_url)),
            llm=llm,
        )
        _bundle_database_url = settings.database_url
    return _bundle


def reset_native_bundle_for_tests() -> None:
    global _bundle, _bundle_database_url
    _bundle = None
    _bundle_database_url = ""


class _LazyNativeBundle:
    def __getattr__(self, name: str):
        return getattr(get_native_bundle(), name)


router = create_native_router(_LazyNativeBundle(), context_resolver=resolve_native_context)
