from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..db import (
    ClaimVersionModel,
    ConceptModel,
    GrowthEventModel,
    GrowthMemoryModel,
    MasteryRecordModel,
    QuestionModel,
    ReflectionModel,
    get_session_factory,
)
from ..events import emit
from ..domains import filter_rows_to_current_area, get_domain_context, resolve_area
from ..features import require_feature
from ..plugins import require_plugin_access
from ..schemas import ReflectionCreate
from ..serializers import model_dict

router = APIRouter(tags=["growth-reflection"])


def _upsert_memory(db, *, key: str, layer: str, memory_type: str, value: dict, confidence: float, source_refs: list[str]):
    area = resolve_area(db=db)
    scoped_key = f"area:{area.id}:{key}"
    row = db.scalar(select(GrowthMemoryModel).where(GrowthMemoryModel.key == scoped_key))
    if row is None:
        row = GrowthMemoryModel(
            key=scoped_key,
            layer=layer,
            memory_type=memory_type,
            value_json=value,
            confidence=confidence,
            source_refs=source_refs,
        )
        db.add(row)
    else:
        row.layer = layer
        row.memory_type = memory_type
        row.value_json = value
        row.confidence = confidence
        row.source_refs = source_refs
        row.status = "active"
    return row


def refresh_growth_memory_records() -> dict:
    """Build inspectable G1/G2/G3 memories from owned data.

    This deliberately avoids storing transient emotion guesses. G1 is a compact trace
    index over persisted raw events; G2 contains structured ability/return records; G3
    is a cautious long-term synthesis whose confidence stays low with little history.
    """
    with get_session_factory()() as db:
        events = filter_rows_to_current_area(db, db.scalars(select(GrowthEventModel).order_by(GrowthEventModel.created_at.desc()).limit(500)).all(), "growth_event")
        mastery_rows = filter_rows_to_current_area(db, db.scalars(select(MasteryRecordModel)).all(), "mastery")
        returned_questions = filter_rows_to_current_area(db, db.scalars(
            select(QuestionModel).where(QuestionModel.returned_count > 0).order_by(QuestionModel.updated_at.desc()).limit(50)
        ).all(), "question")
        revisions = filter_rows_to_current_area(db, db.scalars(select(ClaimVersionModel).where(ClaimVersionModel.version > 1)).all(), "claim_version")
        reflections = filter_rows_to_current_area(db, db.scalars(select(ReflectionModel).order_by(ReflectionModel.created_at.desc()).limit(50)).all(), "reflection")

        counts: dict[str, int] = {}
        for event in events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        g1 = _upsert_memory(
            db,
            key="g1:trace-summary",
            layer="g1_raw",
            memory_type="trace_index",
            value={"event_counts": counts, "event_sample_size": len(events)},
            confidence=1.0,
            source_refs=[e.id for e in events[:100]],
        )
        # SQLAlchemy column defaults are assigned on flush. G3 references the
        # persisted G1 record, so ensure its id exists before building G3.
        db.flush()

        g2_count = 0
        for mastery in mastery_rows:
            concept = db.get(ConceptModel, mastery.concept_id)
            _upsert_memory(
                db,
                key=f"g2:mastery:{mastery.concept_id}",
                layer="g2_structured",
                memory_type="concept_mastery",
                value={
                    "concept_id": mastery.concept_id,
                    "concept_name": concept.name if concept else "unknown",
                    "state": mastery.state,
                    "evidence_note": mastery.evidence_note,
                },
                confidence=0.8 if mastery.evidence_note.strip() else 0.55,
                source_refs=[mastery.id],
            )
            g2_count += 1

        for question in returned_questions:
            _upsert_memory(
                db,
                key=f"g2:return-interest:{question.id}",
                layer="g2_structured",
                memory_type="returned_interest",
                value={
                    "question_id": question.id,
                    "question": question.question,
                    "returned_count": question.returned_count,
                    "energy_mode": question.energy_mode,
                },
                confidence=min(0.9, 0.5 + 0.1 * question.returned_count),
                source_refs=[question.id],
            )
            g2_count += 1

        long_term_value = {
            "returns": sum(q.returned_count for q in returned_questions),
            "claim_revisions": len(revisions),
            "mastery_records": len(mastery_rows),
            "reflections": len(reflections),
            "research_completed": counts.get("research.completed", 0),
            "interpretation": (
                "这是基于可追溯行为/学习记录的暂定成长模型；它描述变化信号，不把短期状态当作人格或能力定论。"
            ),
        }
        signal_n = sum([
            long_term_value["returns"],
            long_term_value["claim_revisions"],
            long_term_value["mastery_records"],
            long_term_value["reflections"],
            long_term_value["research_completed"],
        ])
        g3 = _upsert_memory(
            db,
            key="g3:long-term-growth-model",
            layer="g3_long_term",
            memory_type="long_term_growth_model",
            value=long_term_value,
            confidence=min(0.85, 0.3 + signal_n * 0.03),
            source_refs=[g1.id],
        )
        db.commit()
        db.refresh(g1)
        db.refresh(g3)
        return {"g1": model_dict(g1), "g2_records": g2_count, "g3": model_dict(g3)}


@router.get("/growth/events")
def list_growth_events(limit: int = 100):
    require_plugin_access("capability.growth-feedback", read=("growth_event",))
    require_feature("FEATURE_GROWTH_FEEDBACK")
    with get_session_factory()() as db:
        rows = filter_rows_to_current_area(db, db.scalars(
            select(GrowthEventModel).order_by(GrowthEventModel.created_at.desc()).limit(min(limit, 300))
        ).all(), "growth_event")
        return {"events": [model_dict(x) for x in rows]}


@router.post("/growth/memory/refresh")
def refresh_growth_memory():
    require_plugin_access("capability.growth-feedback", read=("growth_event", "mastery", "claim_version", "question", "reflection", "concept", "growth_memory"), write=("growth_memory",))
    require_feature("FEATURE_GROWTH_FEEDBACK")
    return refresh_growth_memory_records()


@router.get("/growth/memory")
def list_growth_memory(layer: str | None = None):
    require_plugin_access("capability.growth-feedback", read=("growth_memory",))
    require_feature("FEATURE_GROWTH_FEEDBACK")
    with get_session_factory()() as db:
        stmt = select(GrowthMemoryModel).where(GrowthMemoryModel.status == "active").order_by(
            GrowthMemoryModel.layer, GrowthMemoryModel.updated_at.desc()
        )
        if layer:
            stmt = stmt.where(GrowthMemoryModel.layer == layer)
        rows = filter_rows_to_current_area(db, db.scalars(stmt.limit(300)).all(), "growth_memory")
        return {"memory": [model_dict(x) for x in rows]}


@router.get("/growth/narrative")
def growth_narrative():
    require_plugin_access("capability.growth-feedback", read=("growth_event", "mastery", "claim_version", "question", "reflection", "concept", "growth_memory"), write=("growth_memory",))
    require_feature("FEATURE_GROWTH_FEEDBACK")
    # Keep Growth Memory inspectable and current whenever the user asks for a narrative.
    refresh_growth_memory_records()
    with get_session_factory()() as db:
        events = filter_rows_to_current_area(db, db.scalars(select(GrowthEventModel).order_by(GrowthEventModel.created_at.desc()).limit(50)).all(), "growth_event")
        mastery = filter_rows_to_current_area(db, db.scalars(select(MasteryRecordModel)).all(), "mastery")
        revisions = filter_rows_to_current_area(db, db.scalars(select(ClaimVersionModel).where(ClaimVersionModel.version > 1)).all(), "claim_version")

    returns = sum(1 for e in events if e.event_type == "question.returned")
    mastery_changes = sum(1 for e in events if e.event_type == "mastery.updated")
    research = sum(1 for e in events if e.event_type == "research.completed")
    parts = []
    if returns:
        parts.append(f"你有 {returns} 次主动回到曾中断问题的记录，这说明兴趣能够被重新唤起，而不是只能依赖连续打卡。")
    if revisions:
        parts.append(f"你已经留下 {len(revisions)} 次 Claim 修订记录，观点开始具有版本历史，而不是被新结论覆盖。")
    if mastery_changes:
        parts.append(f"系统记录到 {mastery_changes} 次概念掌握证据变化；这些变化关注‘能解释/能区分/能判断证据’而不是刷题次数。")
    if research:
        parts.append(f"完成了 {research} 次研究闭环；是否进一步转成内容并不影响它作为学习成果成立。")
    if not parts:
        parts.append("目前还没有足够的成长事件生成长期叙事。先记录一个真实问题即可，不需要为了‘有数据’强行完成任务。")
    context = get_domain_context()
    return {"area": {"id": context.area_id, "name": context.area_name, "domain_pack_id": context.domain_pack_id}, "narrative": "\n\n".join(parts), "signals": {
        "returns": returns,
        "claim_revisions": len(revisions),
        "mastery_records": len(mastery),
        "research_completed": research,
    }}


@router.post("/reflections")
def create_reflection(body: ReflectionCreate):
    require_plugin_access("capability.reflection", write=("reflection",))
    row = ReflectionModel(**body.model_dump())
    row.next_energy_mode = body.next_energy_mode.value
    with get_session_factory()() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    emit("reflection.completed", {"reflection_id": row.id, "next_energy_mode": row.next_energy_mode})
    return model_dict(row)


@router.get("/reflections")
def list_reflections(limit: int = 50):
    require_plugin_access("capability.reflection", read=("reflection",))
    with get_session_factory()() as db:
        rows = filter_rows_to_current_area(db, db.scalars(
            select(ReflectionModel).order_by(ReflectionModel.created_at.desc()).limit(min(limit, 200))
        ).all(), "reflection")
        return {"reflections": [model_dict(x) for x in rows]}
