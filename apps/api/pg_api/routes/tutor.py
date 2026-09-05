from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from interest_growth_native import HostTutorBinding
from interest_growth_native.capabilities import CAP_KNOWLEDGE, CAP_MASTERY, CAP_RESEARCH

from ..domains import get_domain_context, persona_ids_for_current_area, require_entity_in_current_area
from ..db import TutorPersonaModel, TutorSessionModel, TutorTurnModel, get_session_factory
from ..features import feature_enabled
from ..knowledge import resolve_upstream_kb_names
from ..plugins import require_plugin_access
from ..native_execution import get_native_bundle, resolve_native_context
from ..schemas import TutorSessionContextUpdate, TutorSessionCreate
from ..serializers import model_dict
from ..tutor import (
    ALLOWED_TUTOR_CAPABILITIES,
    close_tutor_session,
    create_tutor_session,
    create_tutor_turn,
    list_tutor_sessions,
    list_tutor_turns,
    mark_turn_resumed,
    normalize_tutor_skills,
    record_upstream_event,
)

router = APIRouter(tags=["tutor-runtime"])


class NativeTutorTurnRequest(BaseModel):
    content: str = Field(min_length=1, max_length=50000)
    capability: str = "chat"


class NativeTutorResumeRequest(BaseModel):
    text: str = ""
    answers: list[dict[str, Any]] = Field(default_factory=list)


def _require_tutor_runtime(*, read=(), write=()) -> None:
    require_plugin_access("capability.tutor-runtime", read=read, write=write)
    if not feature_enabled("FEATURE_TUTOR_RUNTIME"):
        raise HTTPException(503, "tutor runtime disabled")


def _turn_for_current_session(db, turn_id: str, session_id: str) -> TutorTurnModel | None:
    """Load a browser-supplied turn id only when it belongs to this Area + Session."""
    if not turn_id:
        return None
    turn = db.get(TutorTurnModel, turn_id)
    if turn is None or turn.tutor_session_id != session_id:
        return None
    try:
        require_entity_in_current_area(db, "tutor_turn", turn_id)
    except ValueError:
        return None
    return turn


@router.post("/tutor/sessions")
def create_session(body: TutorSessionCreate):
    _require_tutor_runtime(read=("topic", "knowledge_base", "tutor_persona"), write=("tutor_session",))
    try:
        row = create_tutor_session(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return model_dict(row)


@router.get("/tutor/sessions")
def sessions(include_archived: bool = False):
    _require_tutor_runtime(read=("tutor_session",))
    rows = list_tutor_sessions()
    if not include_archived: rows = [row for row in rows if row.status != "archived"]
    return {"sessions": [model_dict(x) for x in rows]}


@router.get("/tutor/sessions/{session_id}")
def session_detail(session_id: str):
    _require_tutor_runtime(read=("tutor_session", "tutor_turn"))
    with get_session_factory()() as db:
        row = db.get(TutorSessionModel, session_id)
        if not row:
            raise HTTPException(404, "tutor session not found")
        try:
            require_entity_in_current_area(db, "tutor_session", session_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        turns = db.scalars(
            select(TutorTurnModel)
            .where(TutorTurnModel.tutor_session_id == session_id)
            .order_by(TutorTurnModel.created_at)
        ).all()
        return {"session": model_dict(row), "turns": [model_dict(x) for x in turns]}


@router.patch("/tutor/sessions/{session_id}")
def update_session_context(session_id: str, body: TutorSessionContextUpdate):
    _require_tutor_runtime(read=("tutor_session", "knowledge_base", "tutor_persona"), write=("tutor_session",))
    with get_session_factory()() as db:
        row = db.get(TutorSessionModel, session_id)
        if not row:
            raise HTTPException(404, "tutor session not found")
        try:
            require_entity_in_current_area(db, "tutor_session", session_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if body.knowledge_base_ids is not None:
            try:
                resolve_upstream_kb_names(body.knowledge_base_ids)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            row.knowledge_base_ids = list(dict.fromkeys(body.knowledge_base_ids))
        if body.skill_names is not None:
            try:
                row.skill_names = normalize_tutor_skills(body.skill_names, domain_pack_id=get_domain_context().domain_pack_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        if body.persona_id is not None or body.persona_name is not None:
            allowed = persona_ids_for_current_area(db)
            persona = None
            persona_name = (body.persona_name or '').strip()
            if body.persona_id:
                persona = db.scalar(select(TutorPersonaModel).where(TutorPersonaModel.id == body.persona_id))
                if persona is None or persona.id not in allowed:
                    raise HTTPException(400, 'persona not found in current Interest Area persona library')
                if persona_name and persona.name != persona_name:
                    raise HTTPException(409, 'persona_id and persona_name refer to different personas')
            elif persona_name:
                matches = db.scalars(select(TutorPersonaModel).where(
                    TutorPersonaModel.name == persona_name,
                    TutorPersonaModel.id.in_(allowed),
                )).all()
                if not matches:
                    raise HTTPException(400, 'persona not found in current Interest Area persona library')
                if len(matches) > 1:
                    raise HTTPException(409, 'persona name is ambiguous; select a persona by id')
                persona = matches[0]
            row.persona_id = persona.id if persona else None
            row.persona_name = persona.name if persona else ''
        if body.title is not None:
            row.title = body.title.strip()
        row.last_active_at = datetime.now(UTC)
        db.commit()
        db.refresh(row)
        return model_dict(row)


@router.post("/tutor/sessions/{session_id}/close")
def close_session(session_id: str):
    _require_tutor_runtime(read=("tutor_session",), write=("tutor_session",))
    try:
        return model_dict(close_tutor_session(session_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

@router.post("/tutor/sessions/{session_id}/archive")
def archive_session(session_id: str):
    _require_tutor_runtime(read=("tutor_session",), write=("tutor_session",))
    with get_session_factory()() as db:
        row = db.get(TutorSessionModel, session_id)
        if not row: raise HTTPException(404, "tutor session not found")
        try: require_entity_in_current_area(db, "tutor_session", session_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        row.status = "archived"; db.commit(); db.refresh(row); return model_dict(row)

@router.post("/tutor/sessions/{session_id}/restore")
def restore_session(session_id: str):
    _require_tutor_runtime(read=("tutor_session",), write=("tutor_session",))
    with get_session_factory()() as db:
        row = db.get(TutorSessionModel, session_id)
        if not row: raise HTTPException(404, "tutor session not found")
        try: require_entity_in_current_area(db, "tutor_session", session_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        row.status = "active"; db.commit(); db.refresh(row); return model_dict(row)

@router.delete("/tutor/sessions/{session_id}")
def delete_session(session_id: str):
    _require_tutor_runtime(read=("tutor_session", "tutor_turn"), write=("tutor_session", "tutor_turn"))
    with get_session_factory()() as db:
        row = db.get(TutorSessionModel, session_id)
        if not row: raise HTTPException(404, "tutor session not found")
        try: require_entity_in_current_area(db, "tutor_session", session_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        turns = db.scalars(select(TutorTurnModel).where(TutorTurnModel.tutor_session_id == session_id)).all()
        active_turns = [turn for turn in turns if turn.upstream_turn_id and turn.status in {"running", "awaiting_input"}]
        if active_turns:
            raise HTTPException(409, {
                "code": "active_turn_exists",
                "detail": "Cancel every active Native Tutor turn before deleting this session.",
                "turn_ids": [turn.id for turn in active_turns],
            })
        for turn in turns: db.delete(turn)
        db.delete(row); db.commit()
    return {"id": session_id, "deleted": True, "turns_deleted": len(turns)}


@router.get("/tutor/sessions/{session_id}/turns")
def turns(session_id: str):
    _require_tutor_runtime(read=("tutor_session", "tutor_turn"))
    try:
        return {"turns": [model_dict(x) for x in list_tutor_turns(session_id)]}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def _native_selected_capability(capability: str, kb_ids: list[str]) -> str | None:
    if capability == "deep_research":
        return CAP_RESEARCH
    if capability in {"deep_question", "mastery_path"}:
        return CAP_MASTERY
    if capability == "chat" and kb_ids:
        return CAP_KNOWLEDGE
    return None


def _native_public_event(event) -> dict[str, Any]:
    payload = dict(event.payload or {})
    content = str(
        payload.get("text")
        or payload.get("question")
        or payload.get("message")
        or ("Tutor runtime failed" if event.type == "error" else "")
    )
    return {
        "type": event.type,
        "category": event.type,
        "content": content,
        "metadata": payload,
        "seq": event.seq or 0,
        "turn_id": event.run_id,
        "status": payload.get("state") or "",
        "terminal": event.type == "done",
        "provider": "native.interest-growth",
    }


def _persist_native_events(local_turn_id: str, events) -> None:
    for event in events:
        record_upstream_event(local_turn_id, _native_public_event(event))


def _native_turn_context(request: Request, session: TutorSessionModel, turn: TutorTurnModel, *, content: str = ""):
    base = resolve_native_context(request, "tutor.write")
    with get_session_factory()() as db:
        persona = None
        if session.persona_id:
            persona = db.scalar(select(TutorPersonaModel).where(
                TutorPersonaModel.id == session.persona_id,
                TutorPersonaModel.id.in_(persona_ids_for_current_area(db)),
            ))
            if persona is None:
                raise ValueError("tutor session persona is no longer available in the current Interest Area")
        elif session.persona_name:
            # Compatibility for sessions created before persona_id became canonical.
            matches = db.scalars(select(TutorPersonaModel).where(
                TutorPersonaModel.name == session.persona_name,
                TutorPersonaModel.id.in_(persona_ids_for_current_area(db)),
            )).all()
            if len(matches) > 1:
                raise ValueError("legacy tutor session persona name is ambiguous; update the session")
            persona = matches[0] if matches else None
        prior = db.scalars(select(TutorTurnModel).where(
            TutorTurnModel.tutor_session_id == session.id,
            TutorTurnModel.id != turn.id,
        ).order_by(TutorTurnModel.created_at.desc()).limit(12)).all()
    history: list[dict[str, str]] = []
    for item in reversed(prior):
        prompt = str((item.input_json or {}).get("content") or "")
        if prompt:
            history.append({"role": "user", "content": prompt})
        if item.answer_text:
            history.append({"role": "assistant", "content": item.answer_text})
    selected = _native_selected_capability(turn.capability, list(session.knowledge_base_ids or []))
    return base.child(
        session_id=session.id,
        user_message=content,
        selected_capability=selected,
        knowledge_base_ids=tuple(session.knowledge_base_ids or ()),
        conversation_history=tuple(history),
        persona_context=persona.content if persona else "",
        skills_manifest="\n".join(str(x) for x in (session.skill_names or ())),
        host_tutor=HostTutorBinding(session.id, turn.id),
    )


@router.post("/tutor/sessions/{session_id}/native-turns")
def native_turn_start(session_id: str, body: NativeTutorTurnRequest, request: Request):
    _require_tutor_runtime(
        read=("tutor_session", "tutor_turn", "knowledge_base", "knowledge_mapping", "source", "tutor_persona", "auxiliary_agent_memory"),
        write=("tutor_turn", "capability_run"),
    )
    if body.capability not in ALLOWED_TUTOR_CAPABILITIES:
        raise HTTPException(422, "unsupported tutor capability")
    with get_session_factory()() as db:
        session = db.get(TutorSessionModel, session_id)
        if session is None:
            raise HTTPException(404, "tutor session not found")
        try:
            require_entity_in_current_area(db, "tutor_session", session_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        session_data = model_dict(session)
    turn = create_tutor_turn(session_id, body.capability, {
        "content": body.content.strip(),
        "knowledge_base_ids": session_data.get("knowledge_base_ids") or [],
        "persona_name": session_data.get("persona_name") or "",
        "persona_id": session_data.get("persona_id"),
        "skill_names": session_data.get("skill_names") or [],
        "provider": "native.interest-growth",
    })
    session = TutorSessionModel(**{
        key: value for key, value in session_data.items()
        if key in TutorSessionModel.__table__.columns.keys()
    })
    context = _native_turn_context(request, session, turn, content=body.content.strip())
    result = get_native_bundle().tutor.start(context)
    _persist_native_events(turn.id, result.events)
    with get_session_factory()() as db:
        persisted = db.get(TutorTurnModel, turn.id)
        return {
            "turn": model_dict(persisted),
            "run": {
                "id": result.run.id,
                "state": result.run.state,
                "version": result.run.version,
            },
            "events": [_native_public_event(x) for x in result.events],
        }


@router.get("/tutor/sessions/{session_id}/native-turns/{turn_id}/events")
def native_turn_events(session_id: str, turn_id: str, request: Request, after_seq: int = 0):
    _require_tutor_runtime(read=("tutor_session", "tutor_turn"))
    with get_session_factory()() as db:
        turn = _turn_for_current_session(db, turn_id, session_id)
        if turn is None or not turn.upstream_turn_id:
            raise HTTPException(404, "native tutor turn not found")
        run_id = turn.upstream_turn_id
    context = resolve_native_context(request, "tutor.read").child(session_id=session_id)
    events = get_native_bundle().tutor.replay(context, run_id, after_seq=after_seq)
    return {"events": [_native_public_event(x) for x in events]}


@router.post("/tutor/sessions/{session_id}/native-turns/{turn_id}/resume")
def native_turn_resume(session_id: str, turn_id: str, body: NativeTutorResumeRequest, request: Request):
    with get_session_factory()() as db:
        turn = _turn_for_current_session(db, turn_id, session_id)
        session = db.get(TutorSessionModel, session_id)
        if turn is None or session is None or not turn.upstream_turn_id:
            raise HTTPException(404, "native tutor turn not found")
        run_id = turn.upstream_turn_id
        session_data = model_dict(session)
    session = TutorSessionModel(**{
        key: value for key, value in session_data.items()
        if key in TutorSessionModel.__table__.columns.keys()
    })
    context = _native_turn_context(request, session, turn)
    result = get_native_bundle().tutor.resume(
        context, run_id=run_id, user_input=body.text, answers=body.answers
    )
    mark_turn_resumed(turn_id)
    _persist_native_events(turn_id, result.events)
    return {"run": {"id": result.run.id, "state": result.run.state}, "events": [_native_public_event(x) for x in result.events]}


@router.post("/tutor/sessions/{session_id}/native-turns/{turn_id}/cancel")
def native_turn_cancel(session_id: str, turn_id: str, request: Request):
    with get_session_factory()() as db:
        turn = _turn_for_current_session(db, turn_id, session_id)
        if turn is None or not turn.upstream_turn_id:
            raise HTTPException(404, "native tutor turn not found")
        run_id = turn.upstream_turn_id
    context = resolve_native_context(request, "tutor.write").child(session_id=session_id)
    run = get_native_bundle().tutor.cancel(context, run_id)
    events = get_native_bundle().tutor.replay(context, run_id, after_seq=0)
    _persist_native_events(turn_id, [x for x in events if (x.seq or 0) > (turn.last_seq or 0)])
    return {"run": {"id": run.id, "state": run.state}}
