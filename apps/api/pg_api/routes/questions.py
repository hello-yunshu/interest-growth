from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from pg_domain import QuestionState

from ..db import GrowthEventModel, QuestionModel, TopicModel, get_session_factory
from ..engines import quick_explore_question
from ..domains import filter_rows_to_current_area, get_domain_context, require_entity_in_current_area
from ..events import emit
from ..plugins import require_plugin_access
from ..schemas import QuestionCreate, QuestionUpdate, QuickExploreRequest, TopicCreate, TopicUpdate
from ..serializers import model_dict
from ..question_transitions import InvalidQuestionTransition, QuestionTransitionService

router = APIRouter(tags=["curiosity"])


@router.post("/questions")
def create_question(body: QuestionCreate):
    require_plugin_access("capability.curiosity", write=("question",))
    row = QuestionModel(
        question=body.question,
        source_context=body.source_context,
        interest_level=body.interest_level,
        energy_mode=body.energy_mode.value,
        notes=body.notes,
        state=QuestionState.CAPTURED.value,
    )
    with get_session_factory()() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    emit("question.created", {"question_id": row.id, "interest_level": row.interest_level})
    return model_dict(row)


@router.get("/questions")
def list_questions(state: str | None = None, limit: int = 50):
    require_plugin_access("capability.curiosity", read=("question",))
    limit = max(1, min(limit, 200))
    with get_session_factory()() as db:
        stmt = select(QuestionModel).order_by(QuestionModel.updated_at.desc()).limit(limit)
        if state:
            stmt = stmt.where(QuestionModel.state == state)
        rows = filter_rows_to_current_area(db, db.scalars(stmt).all(), "question")
        return {"questions": [model_dict(x) for x in rows]}


@router.get("/questions/{question_id}")
def get_question(question_id: str):
    require_plugin_access("capability.curiosity", read=("question",))
    with get_session_factory()() as db:
        row = db.get(QuestionModel, question_id)
        if not row:
            raise HTTPException(404, "question not found")
        try:
            require_entity_in_current_area(db, "question", question_id)
        except ValueError as exc:
            raise HTTPException(404, "question not found in current area") from exc
        return model_dict(row)


@router.patch("/questions/{question_id}")
def update_question(question_id: str, body: QuestionUpdate):
    require_plugin_access("capability.curiosity", read=("question",), write=("question",))
    with get_session_factory()() as db:
        row = db.get(QuestionModel, question_id)
        if not row:
            raise HTTPException(404, "question not found")
        try:
            require_entity_in_current_area(db, "question", question_id)
        except ValueError as exc:
            raise HTTPException(404, "question not found in current area") from exc
        if body.state is not None:
            raise HTTPException(409, {
                "code": "question_state_transition_required",
                "detail": "Use the explicit lifecycle endpoint; generic PATCH cannot change state.",
            })
        for field, value in body.model_dump(exclude_unset=True).items():
            if hasattr(value, "value"):
                value = value.value
            setattr(row, field, value)
        db.commit()
        db.refresh(row)
        return model_dict(row)


@router.post("/questions/{question_id}/quick-explore")
async def quick_explore(question_id: str, body: QuickExploreRequest):
    require_plugin_access("capability.curiosity", read=("question",), write=("question",), risks=("network", "llm"))
    with get_session_factory()() as db:
        row = db.get(QuestionModel, question_id)
        if not row:
            raise HTTPException(404, "question not found")
        try:
            require_entity_in_current_area(db, "question", question_id)
        except ValueError as exc:
            raise HTTPException(404, "question not found in current area") from exc
        try:
            QuestionTransitionService.transition(row, QuestionState.EXPLORING.value)
        except InvalidQuestionTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        question = row.question
    result = await quick_explore_question(question, body.focus, get_domain_context())
    emit("question.exploring", {"question_id": question_id, "provider": result["provider"]})
    return {"question_id": question_id, "state": QuestionState.EXPLORING.value, "exploration": result}


@router.post("/questions/{question_id}/close")
def close_question(question_id: str):
    require_plugin_access("capability.curiosity", read=("question",), write=("question",))
    with get_session_factory()() as db:
        row = db.get(QuestionModel, question_id)
        if not row:
            raise HTTPException(404, "question not found")
        try:
            require_entity_in_current_area(db, "question", question_id)
        except ValueError as exc:
            raise HTTPException(404, "question not found in current area") from exc
        try:
            QuestionTransitionService.transition(row, QuestionState.CLOSED.value)
        except InvalidQuestionTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        db.refresh(row)
    emit("question.closed", {"question_id": question_id})
    return model_dict(row)


@router.post("/questions/{question_id}/pause")
def pause_question(question_id: str):
    require_plugin_access("capability.curiosity", read=("question",), write=("question",))
    with get_session_factory()() as db:
        row = db.get(QuestionModel, question_id)
        if not row:
            raise HTTPException(404, "question not found")
        try:
            require_entity_in_current_area(db, "question", question_id)
        except ValueError as exc:
            raise HTTPException(404, "question not found in current area") from exc
        try:
            QuestionTransitionService.transition(row, QuestionState.PAUSED.value)
        except InvalidQuestionTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        db.refresh(row)
    emit("topic.paused", {"question_id": question_id})
    return model_dict(row)


@router.post("/questions/{question_id}/return")
def return_question(question_id: str):
    require_plugin_access("capability.curiosity", read=("question",), write=("question",))
    with get_session_factory()() as db:
        row = db.get(QuestionModel, question_id)
        if not row:
            raise HTTPException(404, "question not found")
        try:
            require_entity_in_current_area(db, "question", question_id)
        except ValueError as exc:
            raise HTTPException(404, "question not found in current area") from exc
        try:
            QuestionTransitionService.transition(row, QuestionState.RETURNED.value)
        except InvalidQuestionTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        db.refresh(row)
    emit("question.returned", {"question_id": row.id, "returned_count": row.returned_count})
    return model_dict(row)


@router.post("/questions/{question_id}/promote")
def promote_to_topic(question_id: str):
    require_plugin_access("capability.curiosity", read=("question", "topic"), write=("question", "topic"))
    with get_session_factory()() as db:
        q = db.get(QuestionModel, question_id)
        if not q:
            raise HTTPException(404, "question not found")
        try:
            require_entity_in_current_area(db, "question", question_id)
        except ValueError as exc:
            raise HTTPException(404, "question not found in current area") from exc
        existing = db.scalar(select(TopicModel).where(TopicModel.question_id == question_id))
        if existing:
            return model_dict(existing)
        topic = TopicModel(question_id=q.id, title=q.question[:300], description=q.notes)
        try:
            QuestionTransitionService.transition(q, QuestionState.ACTIVE_TOPIC.value)
        except InvalidQuestionTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(topic)
        db.commit()
        db.refresh(topic)
    emit("topic.activated", {"topic_id": topic.id, "question_id": q.id})
    return model_dict(topic)


@router.post("/topics")
def create_topic(body: TopicCreate):
    require_plugin_access("capability.curiosity", read=("question",), write=("topic",))
    row = TopicModel(title=body.title, description=body.description, question_id=body.question_id)
    with get_session_factory()() as db:
        if body.question_id and not db.get(QuestionModel, body.question_id):
            raise HTTPException(404, "question not found")
        if body.question_id:
            try:
                require_entity_in_current_area(db, "question", body.question_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        db.add(row)
        db.commit()
        db.refresh(row)
    emit("topic.activated", {"topic_id": row.id, "question_id": row.question_id})
    return model_dict(row)


@router.patch("/topics/{topic_id}")
def update_topic(topic_id: str, body: TopicUpdate):
    require_plugin_access("capability.curiosity", read=("topic",), write=("topic",))
    with get_session_factory()() as db:
        row = db.get(TopicModel, topic_id)
        if not row:
            raise HTTPException(404, "topic not found")
        try:
            require_entity_in_current_area(db, "topic", topic_id)
        except ValueError as exc:
            raise HTTPException(404, "topic not found in current area") from exc
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(row, key, value.strip() if isinstance(value, str) else value)
        db.commit(); db.refresh(row)
        return model_dict(row)


@router.post("/topics/{topic_id}/archive")
def archive_topic(topic_id: str):
    require_plugin_access("capability.curiosity", read=("topic",), write=("topic",))
    with get_session_factory()() as db:
        row = db.get(TopicModel, topic_id)
        if not row:
            raise HTTPException(404, "topic not found")
        try:
            require_entity_in_current_area(db, "topic", topic_id)
        except ValueError as exc:
            raise HTTPException(404, "topic not found in current area") from exc
        row.status = "archived"
        db.commit(); db.refresh(row)
        return model_dict(row)


@router.post("/topics/{topic_id}/restore")
def restore_topic(topic_id: str):
    require_plugin_access("capability.curiosity", read=("topic",), write=("topic",))
    with get_session_factory()() as db:
        row = db.get(TopicModel, topic_id)
        if not row:
            raise HTTPException(404, "topic not found")
        try:
            require_entity_in_current_area(db, "topic", topic_id)
        except ValueError as exc:
            raise HTTPException(404, "topic not found in current area") from exc
        row.status = "active"
        db.commit(); db.refresh(row)
        return model_dict(row)


@router.get("/topics")
def list_topics(limit: int = 50, include_archived: bool = False):
    require_plugin_access("capability.curiosity", read=("topic",))
    with get_session_factory()() as db:
        stmt = select(TopicModel).order_by(TopicModel.updated_at.desc()).limit(min(limit, 200))
        if not include_archived:
            stmt = stmt.where(TopicModel.status != "archived")
        rows = db.scalars(stmt).all()
        rows = filter_rows_to_current_area(db, rows, "topic")
        return {"topics": [model_dict(x) for x in rows]}


@router.get("/dashboard")
def dashboard():
    require_plugin_access("capability.curiosity", read=("question", "topic", "growth_event"))
    with get_session_factory()() as db:
        questions = filter_rows_to_current_area(db, db.scalars(
            select(QuestionModel).where(QuestionModel.active.is_(True)).order_by(QuestionModel.updated_at.desc()).limit(100)
        ).all(), "question")[:5]
        topics = filter_rows_to_current_area(db, db.scalars(
            select(TopicModel).where(TopicModel.status == "active").order_by(TopicModel.updated_at.desc()).limit(100)
        ).all(), "topic")[:3]
        growth = filter_rows_to_current_area(db, db.scalars(
            select(GrowthEventModel).order_by(GrowthEventModel.created_at.desc()).limit(100)
        ).all(), "growth_event")[:5]
        return {
            "recent_questions": [model_dict(x) for x in questions],
            "active_topics": [model_dict(x) for x in topics],
            "micro_progress": [model_dict(x) for x in growth],
            "area": {"id": get_domain_context().area_id, "name": get_domain_context().area_name, "domain_pack_id": get_domain_context().domain_pack_id},
            "design_note": "No streaks. No publishing KPI. Pause and return are valid states.",
        }
