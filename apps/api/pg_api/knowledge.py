from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from pg_artifacts import LocalFilesystemStorage
from pg_shared import get_settings

from .domains import require_entity_in_current_area

from .db import (
    KnowledgeBaseModel,
    KnowledgeSourceIndexModel,
    RetrievalCandidateModel,
    SourceModel,
    get_session_factory,
)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._()\-\u4e00-\u9fff]+")


def source_storage() -> LocalFilesystemStorage:
    return LocalFilesystemStorage(get_settings().source_storage_root)


def safe_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", Path(name).name).strip("._")
    return (cleaned or "source.bin")[:180]


def source_file_path(source: SourceModel) -> Path:
    if not source.local_file:
        raise ValueError("source has no local file")
    path = Path(source.local_file)
    if path.is_absolute():
        raise ValueError("absolute local source paths are forbidden")
    return source_storage().path_for(source.local_file)


def store_source_bytes(filename: str, content: bytes) -> str:
    key = f"sources/{uuid4()}/{safe_filename(filename)}"
    source_storage().put_bytes(key, content)
    return key


def upstream_name_for(name: str, db_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower()[:70] or "interest"
    return f"pg-{slug}-{db_id[:8]}"


def upstream_filename_for(source_id: str, filename: str) -> str:
    """Collision-safe filename that still leaves the original name human-readable."""
    return f"pg_{source_id[:8]}__{safe_filename(filename)}"


def resolve_upstream_kb_names(ids: list[str]) -> tuple[list[str], list[str]]:
    if not ids:
        return [], []
    names: list[str] = []
    warnings: list[str] = []
    with get_session_factory()() as db:
        for kb_id in ids:
            kb = db.get(KnowledgeBaseModel, kb_id)
            if not kb:
                raise ValueError(f"unknown knowledge base: {kb_id}")
            require_entity_in_current_area(db, "knowledge_base", kb_id)
            names.append(kb.upstream_name)
            if kb.status != "ready":
                warnings.append(
                    f"Knowledge base {kb.name} status={kb.status}; retrieval may be incomplete."
                )
    return names, warnings


def _source_dicts(value: Any, parent_key: str = "") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    source_keys = {"sources", "citations", "references", "source_documents"}
    if isinstance(value, dict):
        if parent_key in source_keys:
            found.append(value)
        for key, child in value.items():
            key_l = str(key).lower()
            if key_l in source_keys:
                if isinstance(child, list):
                    for item in child:
                        if isinstance(item, dict):
                            found.append(item)
                elif isinstance(child, dict):
                    found.append(child)
            if key_l in source_keys or key_l in {
                "trace", "normalized_trace", "metadata", "data", "final", "result"
            }:
                found.extend(_source_dicts(child, key_l))
    elif isinstance(value, list):
        for child in value:
            found.extend(_source_dicts(child, parent_key))
    return found


def _pick_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text:
                return text
    return ""


def persist_retrieval_candidates(
    *,
    raw: dict[str, Any],
    knowledge_base_id: str,
    query: str,
    capability_run_id: str | None = None,
    tutor_turn_id: str | None = None,
) -> list[RetrievalCandidateModel]:
    candidates = _source_dicts(raw)
    with get_session_factory()() as db:
        mappings = db.query(KnowledgeSourceIndexModel).filter_by(
            knowledge_base_id=knowledge_base_id
        ).all()
        by_name = {Path(m.upstream_file_name).name: m.source_id for m in mappings if m.upstream_file_name}
        rows: list[RetrievalCandidateModel] = []
        seen: set[tuple[str, str, str, str]] = set()
        for item in candidates:
            filename = _pick_text(
                item,
                ("filename", "file_name", "file", "source_file", "path", "name"),
            )
            base_name = Path(filename).name if filename else ""
            source_id = by_name.get(base_name)
            page = _pick_text(item, ("page", "page_number", "page_num"))
            section = _pick_text(item, ("section", "location", "chapter", "heading"))
            location = " · ".join(x for x in ([f"p.{page}" if page else "", section]) if x)
            excerpt = _pick_text(item, ("snippet", "excerpt", "text", "content", "quote"))
            signature = (source_id or "", base_name, location, excerpt[:300])
            if signature in seen:
                continue
            seen.add(signature)
            row = RetrievalCandidateModel(
                capability_run_id=capability_run_id,
                tutor_turn_id=tutor_turn_id,
                knowledge_base_id=knowledge_base_id,
                source_id=source_id,
                query=query,
                upstream_file_name=base_name,
                location=location,
                excerpt=excerpt[:12000],
                metadata_json=item,
                status="candidate_not_evidence",
            )
            db.add(row)
            rows.append(row)
        db.commit()
        for row in rows:
            db.refresh(row)
        return rows
