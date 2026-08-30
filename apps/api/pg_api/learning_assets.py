from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .db import (
    ConceptModel,
    LearningNoteModel,
    MasteryEvidenceModel,
    MasteryRecordModel,
    PracticeAttemptModel,
    PracticeItemModel,
    TopicModel,
    TutorPersonaModel,
    TutorSessionModel,
    get_session_factory,
)
from .domains import require_entity_in_current_area, seed_domain_personas


def seed_tutor_personas() -> None:
    # Current startup entrypoint for the bundled tutor personas.
    seed_domain_personas()


def create_practice_item(**kwargs: Any) -> PracticeItemModel:
    with get_session_factory()() as db:
        topic_id = kwargs.get('topic_id')
        concept_id = kwargs.get('concept_id')
        if topic_id and not db.get(TopicModel, topic_id):
            raise ValueError('topic not found')
        if topic_id:
            require_entity_in_current_area(db, 'topic', topic_id)
        if concept_id:
            concept = db.get(ConceptModel, concept_id)
            if not concept:
                raise ValueError('concept not found')
            require_entity_in_current_area(db, 'concept', concept_id)
            if topic_id and concept.topic_id and concept.topic_id != topic_id:
                raise ValueError('concept does not belong to topic')
            if not topic_id:
                kwargs['topic_id'] = concept.topic_id
        row = PracticeItemModel(**kwargs)
        db.add(row)
        db.commit(); db.refresh(row)
        return row


def record_practice_attempt(practice_item_id: str, *, answer: str, is_correct: bool | None,
                            feedback: str = '', tutor_session_id: str | None = None) -> PracticeAttemptModel:
    with get_session_factory()() as db:
        if not db.get(PracticeItemModel, practice_item_id):
            raise ValueError('practice item not found')
        require_entity_in_current_area(db, 'practice_item', practice_item_id)
        if tutor_session_id:
            if not db.get(TutorSessionModel, tutor_session_id):
                raise ValueError('tutor session not found')
            require_entity_in_current_area(db, 'tutor_session', tutor_session_id)
        row = PracticeAttemptModel(
            practice_item_id=practice_item_id,
            tutor_session_id=tutor_session_id,
            answer=answer,
            is_correct=is_correct,
            feedback=feedback,
        )
        db.add(row); db.commit(); db.refresh(row)
        return row


def promote_attempt_to_mastery_evidence(attempt_id: str, note: str = '') -> tuple[MasteryEvidenceModel, MasteryRecordModel | None]:
    with get_session_factory()() as db:
        attempt = db.get(PracticeAttemptModel, attempt_id)
        if not attempt:
            raise ValueError('practice attempt not found')
        require_entity_in_current_area(db, 'practice_attempt', attempt_id)
        item = db.get(PracticeItemModel, attempt.practice_item_id)
        if not item or not item.concept_id:
            raise ValueError('practice item is not linked to a concept')
        require_entity_in_current_area(db, 'practice_item', item.id)
        require_entity_in_current_area(db, 'concept', item.concept_id)
        existing = db.scalar(select(MasteryEvidenceModel).where(
            MasteryEvidenceModel.evidence_type == 'practice_attempt',
            MasteryEvidenceModel.reference_id == attempt.id,
        ))
        if existing:
            mastery = db.scalar(select(MasteryRecordModel).where(MasteryRecordModel.concept_id == item.concept_id))
            return existing, mastery
        evidence_note = note.strip() or (
            f"Practice response recorded; correctness={attempt.is_correct}. "
            "This is evidence to review, not an automatic mastery promotion."
        )
        evidence = MasteryEvidenceModel(
            concept_id=item.concept_id,
            evidence_type='practice_attempt',
            reference_id=attempt.id,
            note=evidence_note,
            verified_by_user=True,
        )
        attempt.evidence_promoted = True
        db.add(evidence); db.commit(); db.refresh(evidence)
        mastery = db.scalar(select(MasteryRecordModel).where(MasteryRecordModel.concept_id == item.concept_id))
        return evidence, mastery


def create_learning_note(**kwargs: Any) -> LearningNoteModel:
    with get_session_factory()() as db:
        if kwargs.get('topic_id') and not db.get(TopicModel, kwargs['topic_id']):
            raise ValueError('topic not found')
        if kwargs.get('topic_id'):
            require_entity_in_current_area(db, 'topic', kwargs['topic_id'])
        if kwargs.get('concept_id') and not db.get(ConceptModel, kwargs['concept_id']):
            raise ValueError('concept not found')
        if kwargs.get('concept_id'):
            require_entity_in_current_area(db, 'concept', kwargs['concept_id'])
        row = LearningNoteModel(**kwargs)
        db.add(row); db.commit(); db.refresh(row)
        return row
