from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from interest_growth_native import PracticeOrigin

from ..db import (
    LearningNoteModel,
    MasteryEvidenceModel,
    PracticeAttemptModel,
    PracticeItemModel,
    TutorPersonaModel,
    LearningActivityModel,
    EntityAreaBindingModel,
    PersonaScopeModel,
    TopicModel,
    get_session_factory,
)
from ..features import feature_enabled
from ..learning_assets import (
    create_learning_note,
    create_practice_item,
    promote_attempt_to_mastery_evidence,
    record_practice_attempt,
)
from ..plugins import require_plugin_access
from ..serializers import model_dict
from ..domains import (bind_persona_to_current_area, filter_rows_to_current_area, get_domain_context, persona_ids_for_current_area, require_entity_in_current_area, resolve_area)
from ..schemas import LearningActivityCreate, MasteryEvidenceInvalidationRequest
from ..native_execution import get_native_bundle, resolve_native_context

router = APIRouter(tags=['learning-assets'])


class PracticeCreate(BaseModel):
    topic_id: str | None = None
    concept_id: str | None = None
    prompt: str = Field(min_length=1)
    question_type: str = 'open'
    options: dict[str, str] = {}
    reference_answer: str = ''
    explanation: str = ''
    difficulty: str = ''
    status: str = Field(default='active', pattern='^(active|archived)$')


class AttemptCreate(BaseModel):
    answer: str = ''
    is_correct: bool | None = None
    feedback: str = ''
    tutor_session_id: str | None = None


class EvidencePromote(BaseModel):
    note: str = ''


class PracticeProposalRequest(BaseModel):
    topic_id: str | None = None
    concept_id: str | None = None
    topic: str = Field(min_length=1)
    material: str = Field(min_length=1)
    count: int = Field(default=3, ge=1, le=10)


class NoteCreate(BaseModel):
    topic_id: str | None = None
    concept_id: str | None = None
    title: str = Field(min_length=1)
    body_markdown: str = ''
    note_type: str = 'learning_note'


class NoteUpdate(BaseModel):
    title: str | None = None
    body_markdown: str | None = None
    note_type: str | None = None
    status: str | None = Field(default=None, pattern='^(active|archived)$')


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ''
    content: str = ''


def _require(flag: str, plugin: str, *, read=(), write=(), risks=()) -> None:
    require_plugin_access(plugin, read=read, write=write, risks=risks)
    if not feature_enabled(flag):
        raise HTTPException(503, f'{flag} disabled')


@router.get('/practice')
def list_practice(concept_id: str | None = None, topic_id: str | None = None, include_archived: bool = False):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('practice_item','practice_attempt'))
    with get_session_factory()() as db:
        stmt = select(PracticeItemModel).order_by(PracticeItemModel.created_at.desc())
        if not include_archived: stmt = stmt.where(PracticeItemModel.status == 'active')
        if concept_id: stmt = stmt.where(PracticeItemModel.concept_id == concept_id)
        if topic_id: stmt = stmt.where(PracticeItemModel.topic_id == topic_id)
        items = filter_rows_to_current_area(db, db.scalars(stmt).all(), "practice_item")
        output = []
        for item in items:
            attempts = list(db.scalars(select(PracticeAttemptModel).where(PracticeAttemptModel.practice_item_id == item.id).order_by(PracticeAttemptModel.created_at)).all())
            output.append({'item': model_dict(item), 'attempts': [model_dict(x) for x in attempts]})
        return {'practice': output, 'mastery_rule': 'attempts_are_evidence_candidates_not_automatic_mastery'}


@router.post('/practice')
def add_practice(body: PracticeCreate):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('topic','concept'), write=('practice_item',))
    try:
        row = create_practice_item(**body.model_dump(), origin='local')
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return model_dict(row)


@router.put('/practice/{item_id}')
def update_practice(item_id: str, body: PracticeCreate):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('practice_item',), write=('practice_item',))
    with get_session_factory()() as db:
        row = db.get(PracticeItemModel, item_id)
        if not row: raise HTTPException(404, 'practice item not found')
        try: require_entity_in_current_area(db, 'practice_item', item_id)
        except ValueError as exc: raise HTTPException(404, 'practice item not found in current area') from exc
        for key, value in body.model_dump(exclude_unset=True).items(): setattr(row, key, value)
        db.commit(); db.refresh(row); return model_dict(row)


@router.post('/practice/{item_id}/archive')
def archive_practice(item_id: str):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('practice_item',), write=('practice_item',))
    with get_session_factory()() as db:
        row = db.get(PracticeItemModel, item_id)
        if not row: raise HTTPException(404, 'practice item not found')
        try: require_entity_in_current_area(db, 'practice_item', item_id)
        except ValueError as exc: raise HTTPException(404, 'practice item not found in current area') from exc
        row.status = 'archived'; db.commit(); db.refresh(row); return model_dict(row)


@router.post('/practice/{item_id}/restore')
def restore_practice(item_id: str):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('practice_item',), write=('practice_item',))
    with get_session_factory()() as db:
        row = db.get(PracticeItemModel, item_id)
        if not row: raise HTTPException(404, 'practice item not found')
        try: require_entity_in_current_area(db, 'practice_item', item_id)
        except ValueError as exc: raise HTTPException(404, 'practice item not found in current area') from exc
        row.status = 'active'; db.commit(); db.refresh(row); return model_dict(row)


@router.delete('/practice/{item_id}')
def delete_practice(item_id: str):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('practice_item', 'practice_attempt'), write=('practice_item', 'practice_attempt'))
    with get_session_factory()() as db:
        row = db.get(PracticeItemModel, item_id)
        if not row: raise HTTPException(404, 'practice item not found')
        try: require_entity_in_current_area(db, 'practice_item', item_id)
        except ValueError as exc: raise HTTPException(404, 'practice item not found in current area') from exc
        attempts = db.scalars(select(PracticeAttemptModel).where(PracticeAttemptModel.practice_item_id == item_id)).all()
        promoted = [x.id for x in attempts if x.evidence_promoted]
        if promoted:
            raise HTTPException(409, {'code': 'practice_has_promoted_attempts', 'attempt_ids': promoted, 'detail': 'Withdraw promoted evidence before deleting this practice item.'})
        for attempt in attempts: db.delete(attempt)
        db.query(EntityAreaBindingModel).filter(EntityAreaBindingModel.entity_type == 'practice_item', EntityAreaBindingModel.entity_id == item_id).delete(synchronize_session=False)
        db.delete(row); db.commit()
    return {'id': item_id, 'deleted': True, 'attempts_deleted': len(attempts)}


@router.post('/practice/propose')
async def propose_practice(body: PracticeProposalRequest, request: Request):
    try:
        context = resolve_native_context(request, 'practice.run')
        proposals = get_native_bundle().practice.propose(
            context,
            topic=body.topic,
            material=body.material,
            count=body.count,
            concept_ids=([body.concept_id] if body.concept_id else []),
            origin=PracticeOrigin('native_proposal'),
        )
        rows = [create_practice_item(
            topic_id=body.topic_id,
            concept_id=body.concept_id,
            prompt=item.prompt,
            question_type=item.question_type,
            options={str(index + 1): value for index, value in enumerate(item.options)},
            reference_answer=item.expected_answer,
            explanation=item.answer_guide,
            origin='native-proposal',
        ) for item in proposals]
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'proposals': [model_dict(x) for x in rows], 'count': len(rows), 'review_required': True}


@router.post('/practice/{item_id}/attempts')
def add_attempt(item_id: str, body: AttemptCreate):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('practice_item','tutor_session'), write=('practice_attempt',))
    try:
        row = record_practice_attempt(item_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return model_dict(row)


@router.post('/practice/attempts/{attempt_id}/promote-evidence')
def promote_attempt(attempt_id: str, body: EvidencePromote):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('practice_attempt','practice_item','concept','mastery'), write=('mastery_evidence',))
    try:
        evidence, mastery = promote_attempt_to_mastery_evidence(attempt_id, body.note)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        'evidence': model_dict(evidence),
        'mastery': model_dict(mastery) if mastery else None,
        'mastery_changed': False,
        'rule': 'human-visible evidence is recorded; mastery state is unchanged until explicitly updated',
    }


@router.get('/mastery-evidence')
def list_mastery_evidence(concept_id: str | None = None, include_invalidated: bool = False):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('mastery_evidence',))
    with get_session_factory()() as db:
        stmt = select(MasteryEvidenceModel).order_by(MasteryEvidenceModel.created_at.desc())
        if not include_invalidated: stmt = stmt.where(MasteryEvidenceModel.status == 'active')
        if concept_id: stmt = stmt.where(MasteryEvidenceModel.concept_id == concept_id)
        rows = filter_rows_to_current_area(db, db.scalars(stmt).all(), 'mastery_evidence')
        return {'evidence': [model_dict(x) for x in rows]}


@router.post('/mastery-evidence/{evidence_id}/invalidate')
def invalidate_mastery_evidence(evidence_id: str, body: MasteryEvidenceInvalidationRequest):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('mastery_evidence',), write=('mastery_evidence',))
    with get_session_factory()() as db:
        row = db.get(MasteryEvidenceModel, evidence_id)
        if not row: raise HTTPException(404, 'mastery evidence not found')
        try: require_entity_in_current_area(db, 'mastery_evidence', evidence_id)
        except ValueError as exc: raise HTTPException(404, 'mastery evidence not found in current area') from exc
        row.status = 'invalidated'; row.verified_by_user = False; row.invalidated_at = datetime.now(UTC); row.invalidation_reason = body.reason.strip()
        db.commit(); db.refresh(row); return model_dict(row)


@router.get('/notes')
def list_notes(topic_id: str | None = None, concept_id: str | None = None, include_archived: bool = False):
    _require('FEATURE_LEARNING_NOTEBOOK', 'capability.learning-notebook', read=('learning_note',))
    with get_session_factory()() as db:
        stmt = select(LearningNoteModel).order_by(LearningNoteModel.updated_at.desc())
        if not include_archived: stmt = stmt.where(LearningNoteModel.status == 'active')
        if topic_id: stmt = stmt.where(LearningNoteModel.topic_id == topic_id)
        if concept_id: stmt = stmt.where(LearningNoteModel.concept_id == concept_id)
        rows = filter_rows_to_current_area(db, db.scalars(stmt).all(), 'learning_note')
        return {'notes': [model_dict(x) for x in rows]}


@router.post('/notes')
def add_note(body: NoteCreate):
    _require('FEATURE_LEARNING_NOTEBOOK', 'capability.learning-notebook', read=('topic','concept'), write=('learning_note',))
    try:
        return model_dict(create_learning_note(**body.model_dump()))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put('/notes/{note_id}')
def update_note(note_id: str, body: NoteUpdate):
    _require('FEATURE_LEARNING_NOTEBOOK', 'capability.learning-notebook', read=('learning_note',), write=('learning_note',))
    with get_session_factory()() as db:
        row = db.get(LearningNoteModel, note_id)
        if not row: raise HTTPException(404, 'learning note not found')
        try:
            require_entity_in_current_area(db, 'learning_note', note_id)
        except ValueError as exc:
            raise HTTPException(404, 'learning note not found in current area') from exc
        for key, value in body.model_dump(exclude_none=True).items(): setattr(row, key, value)
        if row.sync_status == 'projected': row.sync_status = 'local_changed'
        db.commit(); db.refresh(row); return model_dict(row)


@router.post('/notes/{note_id}/archive')
def archive_note(note_id: str):
    return update_note(note_id, NoteUpdate(status='archived'))


@router.post('/notes/{note_id}/restore')
def restore_note(note_id: str):
    return update_note(note_id, NoteUpdate(status='active'))


@router.delete('/notes/{note_id}')
def delete_note(note_id: str):
    _require('FEATURE_LEARNING_NOTEBOOK', 'capability.learning-notebook', read=('learning_note',), write=('learning_note',))
    with get_session_factory()() as db:
        row = db.get(LearningNoteModel, note_id)
        if not row: raise HTTPException(404, 'learning note not found')
        try: require_entity_in_current_area(db, 'learning_note', note_id)
        except ValueError as exc: raise HTTPException(404, 'learning note not found in current area') from exc
        db.query(EntityAreaBindingModel).filter(EntityAreaBindingModel.entity_type == 'learning_note', EntityAreaBindingModel.entity_id == note_id).delete(synchronize_session=False)
        db.delete(row); db.commit()
    return {'id': note_id, 'deleted': True}


@router.get('/activities')
def list_learning_activities(topic_id: str | None = None, activity_type: str | None = None):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('learning_activity',))
    with get_session_factory()() as db:
        area = resolve_area(db=db)
        stmt = select(LearningActivityModel).where(LearningActivityModel.area_id == area.id).order_by(LearningActivityModel.created_at.desc())
        if topic_id:
            stmt = stmt.where(LearningActivityModel.topic_id == topic_id)
        if activity_type:
            stmt = stmt.where(LearningActivityModel.activity_type == activity_type)
        return {'activities': [model_dict(x) for x in db.scalars(stmt).all()]}


@router.post('/activities')
def add_learning_activity(body: LearningActivityCreate):
    _require('FEATURE_PRACTICE', 'capability.practice', read=('topic',), write=('learning_activity',))
    with get_session_factory()() as db:
        area = resolve_area(db=db)
        if body.topic_id:
            if not db.get(TopicModel, body.topic_id):
                raise HTTPException(404, 'topic not found')
            try:
                require_entity_in_current_area(db, 'topic', body.topic_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        row = LearningActivityModel(area_id=area.id, **body.model_dump())
        db.add(row); db.commit(); db.refresh(row)
        return model_dict(row)

@router.get('/personas')
def list_personas():
    _require('FEATURE_TUTOR_PERSONA', 'capability.tutor-persona', read=('tutor_persona',))
    with get_session_factory()() as db:
        allowed = persona_ids_for_current_area(db)
        rows = [x for x in db.scalars(select(TutorPersonaModel).order_by(TutorPersonaModel.name)).all() if x.id in allowed]
        return {'personas': [model_dict(x) for x in rows], 'domain_pack_id': get_domain_context().domain_pack_id}


@router.post('/personas')
def add_persona(body: PersonaCreate):
    _require('FEATURE_TUTOR_PERSONA', 'capability.tutor-persona', read=('tutor_persona',), write=('tutor_persona',))
    with get_session_factory()() as db:
        row = TutorPersonaModel(**body.model_dump(), builtin=False)
        db.add(row); db.flush(); bind_persona_to_current_area(db, row.id); db.commit(); db.refresh(row); return model_dict(row)
