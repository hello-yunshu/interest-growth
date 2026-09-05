from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .db import (
    ConceptModel,
    TopicModel,
    TutorPersonaModel,
    TutorSessionModel,
    TutorTurnModel,
    get_session_factory,
)
from .knowledge import resolve_upstream_kb_names
from .domains import DEFAULT_DOMAIN_PACK, domain_skill_names, filter_rows_to_current_area, get_domain_context, persona_ids_for_current_area, require_entity_in_current_area


def bundled_tutor_skill_names(domain_pack_id: str | None = None) -> set[str]:
    """Names allowed by one Domain Pack without requiring database state.

    ``None`` intentionally means the current default Psychology pack so contract-level
    validation remains a pure operation before application lifespan has initialized
    Interest Area tables. Runtime call sites must pass the active Area pack explicitly.
    """
    return set(domain_skill_names(domain_pack_id or DEFAULT_DOMAIN_PACK))


def normalize_tutor_skills(skills: list[str] | None, *, domain_pack_id: str | None = None) -> list[str]:
    allowed = bundled_tutor_skill_names(domain_pack_id)
    out: list[str] = []
    for raw in skills or []:
        name = str(raw or "").strip()
        if not name:
            continue
        if name not in allowed:
            raise ValueError(f"unknown bundled tutor skill: {name}")
        if name not in out:
            out.append(name)
    return out


ALLOWED_TUTOR_CAPABILITIES = {
    "chat",
    "deep_question",
    "mastery_path",
    "deep_research",
    "visualize",
}

# User-selectable native tutor tools exposed by the general-interest product.
ALLOWED_TUTOR_TOOLS = {
    "brainstorm",
    "web_search",
    "paper_search",
    "web_fetch",
    "reason",
}


def normalize_tutor_tools(tools: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in tools or []:
        name = str(raw or "").strip()
        if not name:
            continue
        if name not in ALLOWED_TUTOR_TOOLS:
            raise ValueError(f"unsupported tutor tool: {name}")
        if name not in normalized:
            normalized.append(name)
    return normalized


def create_tutor_session(
    *,
    title: str = "",
    topic_id: str | None = None,
    concept_id: str | None = None,
    knowledge_base_ids: list[str] | None = None,
    skill_names: list[str] | None = None,
    persona_id: str | None = None,
    persona_name: str = "",
) -> TutorSessionModel:
    domain_pack_id = get_domain_context().domain_pack_id
    with get_session_factory()() as db:
        if topic_id and not db.get(TopicModel, topic_id):
            raise ValueError("topic not found")
        if topic_id:
            require_entity_in_current_area(db, 'topic', topic_id)
        if concept_id:
            concept = db.get(ConceptModel, concept_id)
            if not concept:
                raise ValueError("concept not found")
            require_entity_in_current_area(db, 'concept', concept_id)
            if topic_id and concept.topic_id and concept.topic_id != topic_id:
                raise ValueError("concept does not belong to topic")
            if not topic_id:
                topic_id = concept.topic_id
        # Resolve now so invalid local KB ids never get persisted as sticky context.
        resolve_upstream_kb_names(list(knowledge_base_ids or []))
        allowed_personas = persona_ids_for_current_area(db)
        persona = None
        if persona_id:
            persona = db.scalar(select(TutorPersonaModel).where(TutorPersonaModel.id == persona_id))
            if persona is None or persona.id not in allowed_personas:
                raise ValueError("persona not found in current Interest Area persona library")
            if persona_name.strip() and persona.name != persona_name.strip():
                raise ValueError("persona_id and persona_name refer to different personas")
        elif persona_name.strip():
            matches = db.scalars(select(TutorPersonaModel).where(
                TutorPersonaModel.name == persona_name.strip(),
                TutorPersonaModel.id.in_(allowed_personas),
            )).all()
            if len(matches) != 1:
                raise ValueError("persona name is ambiguous; select a persona by id")
            persona = matches[0]
        row = TutorSessionModel(
            title=title.strip(),
            topic_id=topic_id,
            concept_id=concept_id,
            knowledge_base_ids=list(dict.fromkeys(knowledge_base_ids or [])),
            skill_names=normalize_tutor_skills(skill_names, domain_pack_id=domain_pack_id),
            persona_id=persona.id if persona else None,
            persona_name=persona.name if persona else "",
            status="active",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def tutor_session_context(session_id: str) -> dict[str, Any]:
    with get_session_factory()() as db:
        row = db.get(TutorSessionModel, session_id)
        if not row:
            raise ValueError("tutor session not found")
        require_entity_in_current_area(db, "tutor_session", session_id)
        kb_names, warnings = resolve_upstream_kb_names(row.knowledge_base_ids)
        concept = db.get(ConceptModel, row.concept_id) if row.concept_id else None
        return {
            "session": row,
            "upstream_kb_names": kb_names,
            "warnings": warnings,
            "concept": concept,
        }


def create_tutor_turn(
    session_id: str,
    capability: str,
    input_json: dict[str, Any],
) -> TutorTurnModel:
    if capability not in ALLOWED_TUTOR_CAPABILITIES:
        raise ValueError(f"unsupported tutor capability: {capability}")
    with get_session_factory()() as db:
        session = db.get(TutorSessionModel, session_id)
        if not session:
            raise ValueError("tutor session not found")
        require_entity_in_current_area(db, "tutor_session", session_id)
        if session.status == "closed":
            raise ValueError("tutor session is closed")
        row = TutorTurnModel(
            tutor_session_id=session_id,
            capability=capability,
            status="running",
            input_json=input_json,
        )
        session.last_active_at = datetime.now(UTC)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def record_upstream_event(
    local_turn_id: str,
    normalized: dict[str, Any],
) -> TutorTurnModel:
    """Persist one normalized upstream event without making it product truth."""
    safe_event = {k: v for k, v in normalized.items() if k != "raw"}
    category = safe_event.get("category")
    with get_session_factory()() as db:
        turn = db.get(TutorTurnModel, local_turn_id)
        if not turn:
            raise ValueError("tutor turn not found")
        require_entity_in_current_area(db, "tutor_turn", local_turn_id)
        session = db.get(TutorSessionModel, turn.tutor_session_id)
        events = list(turn.normalized_events or [])
        events.append(safe_event)
        # Keep the durable trace bounded; complete raw execution remains upstream.
        turn.normalized_events = events[-1000:]
        if safe_event.get("turn_id"):
            turn.upstream_turn_id = str(safe_event["turn_id"])
        if safe_event.get("session_id") and session:
            session.upstream_session_id = str(safe_event["session_id"])
        turn.last_seq = max(turn.last_seq or 0, int(safe_event.get("seq") or 0))

        if category == "answer_delta":
            turn.answer_text = (turn.answer_text or "") + str(safe_event.get("content") or "")
        elif category == "result":
            turn.result_json = {
                "content": safe_event.get("content") or "",
                "metadata": safe_event.get("metadata") or {},
            }
        elif category == "wait_for_input":
            turn.status = "awaiting_input"
            turn.pending_input_json = {
                "content": safe_event.get("content") or "",
                "metadata": safe_event.get("metadata") or {},
            }
        elif category == "error":
            status = str(safe_event.get("status") or (safe_event.get("metadata") or {}).get("status") or "failed")
            turn.status = status if status in {"failed", "cancelled", "rejected"} else "failed"
            turn.error = str(safe_event.get("content") or "Tutor execution error")
            turn.completed_at = datetime.now(UTC)
        elif category == "done" or safe_event.get("terminal"):
            status = str(safe_event.get("status") or "completed")
            turn.status = status if status in {"completed", "failed", "cancelled", "rejected"} else "completed"
            turn.pending_input_json = {}
            turn.completed_at = datetime.now(UTC)
        elif turn.status == "awaiting_input" and category not in {"session", "activity"}:
            # Any meaningful post-reply output shows the same turn has resumed.
            turn.status = "running"
            turn.pending_input_json = {}

        if session:
            session.last_active_at = datetime.now(UTC)
        db.commit()
        db.refresh(turn)
        return turn


def mark_turn_resumed(local_turn_id: str) -> TutorTurnModel:
    with get_session_factory()() as db:
        turn = db.get(TutorTurnModel, local_turn_id)
        if not turn:
            raise ValueError("tutor turn not found")
        require_entity_in_current_area(db, "tutor_turn", local_turn_id)
        if turn.status == "awaiting_input":
            turn.status = "running"
            turn.pending_input_json = {}
        db.commit()
        db.refresh(turn)
        return turn


def close_tutor_session(session_id: str) -> TutorSessionModel:
    with get_session_factory()() as db:
        row = db.get(TutorSessionModel, session_id)
        if not row:
            raise ValueError("tutor session not found")
        require_entity_in_current_area(db, "tutor_session", session_id)
        row.status = "closed"
        row.last_active_at = datetime.now(UTC)
        db.commit()
        db.refresh(row)
        return row


def list_tutor_sessions() -> list[TutorSessionModel]:
    with get_session_factory()() as db:
        rows = list(
            db.scalars(
                select(TutorSessionModel)
                .order_by(TutorSessionModel.last_active_at.desc())
                .limit(200)
            ).all()
        )
        return filter_rows_to_current_area(db, rows, "tutor_session")


def list_tutor_turns(session_id: str) -> list[TutorTurnModel]:
    with get_session_factory()() as db:
        if not db.get(TutorSessionModel, session_id):
            raise ValueError("tutor session not found")
        require_entity_in_current_area(db, "tutor_session", session_id)
        return list(
            db.scalars(
                select(TutorTurnModel)
                .where(TutorTurnModel.tutor_session_id == session_id)
                .order_by(TutorTurnModel.created_at)
            ).all()
        )
