from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any

from sqlalchemy import select


from .db import TopicModel, WritingDocumentModel, WritingRevisionModel, get_session_factory
from .knowledge import resolve_upstream_kb_names
from .domains import filter_rows_to_current_area, require_entity_in_current_area
from .native_execution import get_native_bundle


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def create_document(*, title: str, content_markdown: str = '', topic_id: str | None = None) -> WritingDocumentModel:
    with get_session_factory()() as db:
        if topic_id and not db.get(TopicModel, topic_id):
            raise ValueError('topic not found')
        if topic_id:
            require_entity_in_current_area(db, 'topic', topic_id)
        row = WritingDocumentModel(title=title.strip(), content_markdown=content_markdown, topic_id=topic_id)
        db.add(row); db.commit(); db.refresh(row); return row


def update_document(document_id: str, **updates: Any) -> WritingDocumentModel:
    with get_session_factory()() as db:
        row = db.get(WritingDocumentModel, document_id)
        if not row: raise ValueError('writing document not found')
        require_entity_in_current_area(db, 'writing_document', document_id)
        for key, value in updates.items():
            if value is not None: setattr(row, key, value)
        db.commit(); db.refresh(row); return row


async def propose_revision(
    document_id: str,
    *,
    native_context,
    selected_text: str,
    instruction: str = '',
    mode: str = 'rewrite',
    tools: list[str] | None = None,
    knowledge_base_id: str | None = None,
) -> WritingRevisionModel:
    allowed_modes = {'rewrite', 'shorten', 'expand', 'none'}
    if mode not in allowed_modes: raise ValueError('unsupported edit mode')
    tools = [x for x in list(dict.fromkeys(tools or [])) if x in {'rag', 'web'}]
    with get_session_factory()() as db:
        document = db.get(WritingDocumentModel, document_id)
        if not document: raise ValueError('writing document not found')
        require_entity_in_current_area(db, 'writing_document', document_id)
        base = document.content_markdown
        start = base.find(selected_text)
        if not selected_text or start < 0: raise ValueError('selected text is not present in current document')
        end = start + len(selected_text)
        base_revision_id = f"{document.id}:{document.updated_at.isoformat()}"
    if 'rag' in tools:
        if not knowledge_base_id: raise ValueError('rag edit requires a local knowledge_base_id')
        resolve_upstream_kb_names([knowledge_base_id])

    proposal = get_native_bundle().cowriter.propose_selection_edit(
        native_context,
        base_revision_id=base_revision_id,
        current_document_text=base,
        selection_start=start,
        selection_end=end,
        instruction=f"模式：{mode}。{instruction or '保持原意并提高可读性'}",
        surrounding_context=(f"可用工具：{', '.join(tools)}；知识库：{knowledge_base_id or '无'}"),
    )
    replacement = proposal.proposed.strip()
    engine = 'native.interest-growth'
    operation_id = ''
    if not replacement:
        raise RuntimeError('Co-Writer returned empty replacement')

    row = WritingRevisionModel(
        document_id=document_id,
        instruction=instruction,
        mode=mode,
        tools=tools,
        selected_text=selected_text,
        replacement_text=replacement,
        selection_start=start,
        selection_end=end,
        base_sha256=_hash(base),
        status='proposed',
        engine=engine,
        upstream_operation_id=operation_id,
    )
    with get_session_factory()() as db:
        db.add(row); db.commit(); db.refresh(row); return row


def decide_revision(revision_id: str, *, accept: bool) -> tuple[WritingRevisionModel, WritingDocumentModel]:
    with get_session_factory()() as db:
        revision = db.get(WritingRevisionModel, revision_id)
        if not revision: raise ValueError('writing revision not found')
        require_entity_in_current_area(db, 'writing_revision', revision_id)
        if revision.status != 'proposed': raise ValueError('revision already decided')
        document = db.get(WritingDocumentModel, revision.document_id)
        if not document: raise ValueError('writing document not found')
        if accept:
            current = document.content_markdown
            if _hash(current) != revision.base_sha256:
                raise ValueError('document changed after revision proposal; generate a new revision')
            if current[revision.selection_start:revision.selection_end] != revision.selected_text:
                raise ValueError('selected text no longer matches current document')
            document.content_markdown = (
                current[:revision.selection_start] + revision.replacement_text + current[revision.selection_end:]
            )
            revision.status = 'accepted'
        else:
            revision.status = 'rejected'
        revision.decided_at = datetime.now(UTC)
        db.commit(); db.refresh(revision); db.refresh(document)
        return revision, document


def list_documents() -> list[WritingDocumentModel]:
    with get_session_factory()() as db:
        return filter_rows_to_current_area(db, db.scalars(select(WritingDocumentModel).order_by(WritingDocumentModel.updated_at.desc())).all(), 'writing_document')


def document_bundle(document_id: str) -> tuple[WritingDocumentModel, list[WritingRevisionModel]]:
    with get_session_factory()() as db:
        doc = db.get(WritingDocumentModel, document_id)
        if not doc: raise ValueError('writing document not found')
        require_entity_in_current_area(db, 'writing_document', document_id)
        revisions = list(db.scalars(select(WritingRevisionModel).where(WritingRevisionModel.document_id == document_id).order_by(WritingRevisionModel.created_at.desc())).all())
        return doc, revisions
