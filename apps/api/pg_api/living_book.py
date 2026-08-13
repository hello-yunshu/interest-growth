from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import delete, select

from .db import (
    ClaimModel, ClaimVersionModel, ConceptModel, EvidenceModel, LearningNoteModel, LearningActivityModel,
    LivingBookChapterModel, LivingBookModel, PracticeItemModel, SourceModel, TopicModel,
    get_session_factory,
)
from .knowledge import resolve_upstream_kb_names
from .domains import filter_rows_to_current_area, require_entity_in_current_area, resolve_area
from .native_execution import get_native_bundle


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def create_book(*, topic_id: str, title: str, intent: str = '', knowledge_base_ids: list[str] | None = None) -> LivingBookModel:
    with get_session_factory()() as db:
        if not db.get(TopicModel, topic_id): raise ValueError('topic not found')
        require_entity_in_current_area(db, 'topic', topic_id)
        resolve_upstream_kb_names(list(knowledge_base_ids or []))
        row = LivingBookModel(topic_id=topic_id, title=title.strip(), intent=intent,
                              knowledge_base_ids=list(dict.fromkeys(knowledge_base_ids or [])))
        db.add(row); db.commit(); db.refresh(row); return row


def _claim_bundle(db, claim: ClaimModel) -> dict[str, Any] | None:
    version = db.get(ClaimVersionModel, claim.current_version_id) if claim.current_version_id else None
    if not version: return None
    source_ids: set[str] = set()
    for eid in list(version.supporting_evidence or []) + list(version.contradicting_evidence or []):
        evidence = db.get(EvidenceModel, eid)
        if evidence: source_ids.add(evidence.source_id)
    return {
        'id': claim.id, 'statement': version.statement, 'limitations': version.limitations,
        'verification_state': claim.verification_state, 'source_ids': sorted(source_ids),
        'version': version.version,
    }


def compile_local_book(book_id: str) -> tuple[LivingBookModel, list[LivingBookChapterModel]]:
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        if not book: raise ValueError('living book not found')
        require_entity_in_current_area(db, 'living_book', book_id)
        topic = db.get(TopicModel, book.topic_id)
        concepts = list(db.scalars(select(ConceptModel).where(ConceptModel.topic_id == book.topic_id).order_by(ConceptModel.created_at)).all())
        claims = list(db.scalars(select(ClaimModel).where(ClaimModel.topic_id == book.topic_id).order_by(ClaimModel.created_at)).all())
        notes = list(db.scalars(select(LearningNoteModel).where(LearningNoteModel.topic_id == book.topic_id).order_by(LearningNoteModel.created_at)).all())
        practice = filter_rows_to_current_area(db, db.scalars(select(PracticeItemModel).where(PracticeItemModel.topic_id == book.topic_id).order_by(PracticeItemModel.created_at)).all(), 'practice_item')
        area = resolve_area(db=db)
        activities = list(db.scalars(select(LearningActivityModel).where(LearningActivityModel.area_id == area.id, LearningActivityModel.topic_id == book.topic_id).order_by(LearningActivityModel.created_at)).all())
        claim_bundles = [x for c in claims if (x := _claim_bundle(db, c))]
        db.execute(delete(LivingBookChapterModel).where(LivingBookChapterModel.book_id == book_id))
        chapters: list[LivingBookChapterModel] = []
        targets = concepts or [None]
        for i, concept in enumerate(targets, 1):
            related_claims = [x for x in claim_bundles if concept is None or x['id'] in (concept.related_claims or [])]
            if concept is not None and not related_claims:
                related_claims = claim_bundles
            related_notes = [n for n in notes if concept is None or n.concept_id in {None, concept.id}]
            related_practice = [p for p in practice if concept is None or p.concept_id == concept.id]
            source_ids = sorted({sid for c in related_claims for sid in c['source_ids']})
            refs = {
                'concepts': [concept.id] if concept else [],
                'claims': [c['id'] for c in related_claims],
                'sources': source_ids,
                'notes': [n.id for n in related_notes],
                'practice': [p.id for p in related_practice],
                'activities': [a.id for a in activities],
            }
            payload = {
                'concept': {'id': concept.id, 'name': concept.name, 'definition': concept.definition,
                            'examples': concept.examples, 'counterexamples': concept.counterexamples,
                            'confused_with': concept.confused_with} if concept else None,
                'claims': related_claims,
                'notes': [{'id': n.id, 'title': n.title, 'body': n.body_markdown, 'updated_at': n.updated_at} for n in related_notes],
                'practice': [{'id': p.id, 'prompt': p.prompt, 'updated': str(p.created_at)} for p in related_practice],
                'activities': [{'id': a.id, 'type': a.activity_type, 'objective': a.objective, 'observation': a.observation, 'self_assessment': a.self_assessment} for a in activities],
            }
            title = concept.name if concept else (topic.title if topic else book.title)
            lines = [f'# {title}']
            if concept:
                lines += ['', concept.definition or '（尚未写入本地定义）']
                if concept.examples: lines += ['', '## 例子', *[f'- {x}' for x in concept.examples]]
                if concept.counterexamples: lines += ['', '## 反例', *[f'- {x}' for x in concept.counterexamples]]
            if related_claims:
                lines += ['', '## 当前 Claim']
                for c in related_claims:
                    lines.append(f"- {c['statement']}  `[{c['verification_state']}]`")
                    if c['limitations']: lines.append(f"  - 限制：{c['limitations']}")
            if related_notes:
                lines += ['', '## 我的学习笔记']
                for n in related_notes: lines += [f'### {n.title}', n.body_markdown]
            if related_practice:
                lines += ['', '## 可继续检验的问题', *[f"- {p.prompt}" for p in related_practice]]
            if activities:
                lines += ['', '## 学习 / 实践活动']
                for a in activities:
                    lines.append(f'- [{a.activity_type}] {a.objective or a.observation or a.self_assessment or a.status}')
            chapter = LivingBookChapterModel(
                book_id=book_id, order_index=i, title=title,
                summary=(concept.definition[:240] if concept else book.intent[:240]),
                content_markdown='\n'.join(lines).strip(), source_refs=refs,
                source_fingerprint=_sha(payload), status='current',
            )
            db.add(chapter); chapters.append(chapter)
        db.flush()
        book.source_fingerprint = _sha([c.source_fingerprint for c in chapters])
        book.status = 'compiled'
        db.commit(); db.refresh(book)
        for c in chapters: db.refresh(c)
        return book, chapters


def book_bundle(book_id: str) -> tuple[LivingBookModel, list[LivingBookChapterModel]]:
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        if not book: raise ValueError('living book not found')
        require_entity_in_current_area(db, 'living_book', book_id)
        chapters = list(db.scalars(select(LivingBookChapterModel).where(LivingBookChapterModel.book_id == book_id).order_by(LivingBookChapterModel.order_index)).all())
        return book, chapters


async def project_book(book_id: str, native_context) -> LivingBookModel:
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        if not book: raise ValueError('living book not found')
        require_entity_in_current_area(db, 'living_book', book_id)
        resolve_upstream_kb_names(book.knowledge_base_ids)
        concepts = list(db.scalars(select(ConceptModel).where(ConceptModel.topic_id == book.topic_id).order_by(ConceptModel.created_at)).all())
        hints = [x.name for x in concepts] or None
        intent = book.intent or f'将“{book.title}”整理为可交互学习书；保留来源、实践记录与当前理解边界。'
        title = book.title
    result = get_native_bundle().book.scaffold(
        native_context, title=title, purpose=intent, chapter_hints=hints,
    )
    proposal = asdict(result)
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        book.upstream_book_id = ''
        book.proposal_json = proposal
        book.projection_status = 'proposal_pending_review'
        db.commit(); db.refresh(book); return book


async def confirm_projected_proposal(book_id: str, proposal: dict[str, Any] | None = None) -> LivingBookModel:
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        if not book or not book.proposal_json: raise ValueError('living book has no proposal')
        require_entity_in_current_area(db, 'living_book', book_id)
        payload = proposal if proposal is not None else book.proposal_json
        chapters = list(payload.get('chapters') or [])
        book.proposal_json = payload
        book.spine_json = {
            'schema': 'interest-growth.book-spine.v1',
            'title': str(payload.get('title') or book.title),
            'purpose': str(payload.get('purpose') or book.intent),
            'chapters': chapters,
            'review_required': True,
        }
        book.projection_status = 'spine_pending_review'
        db.commit(); db.refresh(book); return book


async def confirm_projected_spine(book_id: str, spine: dict[str, Any] | None = None, *, auto_compile: bool = False) -> tuple[LivingBookModel, dict[str, Any]]:
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        if not book or not book.spine_json: raise ValueError('living book has no reviewed spine')
        require_entity_in_current_area(db, 'living_book', book_id)
        payload = spine if spine is not None else book.spine_json
        book.spine_json = payload
        book.projection_status = 'accepted'
        db.commit(); db.refresh(book)
    if auto_compile:
        compiled, chapters = compile_local_book(book_id)
        return compiled, {'status': 'compiled', 'chapter_count': len(chapters), 'provider': 'native.interest-growth'}
    return book, {'status': 'accepted', 'provider': 'native.interest-growth'}


def mark_chapters_stale_for_claim(claim_id: str, reason: str) -> int:
    count = 0
    with get_session_factory()() as db:
        for row in db.scalars(select(LivingBookChapterModel)).all():
            if claim_id in list((row.source_refs or {}).get('claims') or []):
                row.status = 'stale'; row.stale_reason = reason; count += 1
        if count: db.commit()
    return count
