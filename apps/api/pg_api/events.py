from __future__ import annotations

from pg_event_bus import DomainEvent, EventBus

from .db import ArtifactModel, DomainEventRecordModel, GrowthEventModel, get_session_factory
from .features import feature_enabled
from .plugins import is_plugin_enabled

bus = EventBus()


def _growth_handler(event: DomainEvent) -> None:
    if not feature_enabled("FEATURE_GROWTH_FEEDBACK") or not is_plugin_enabled("capability.growth-feedback"):
        return
    messages = {
        "question.returned": "你重新主动回到了一个曾暂停的问题。回归本身就是有效的学习进展。",
        "claim.revised": "你修正了一条 Claim：理解从“记住结论”向“能根据证据调整观点”推进。",
        "mastery.updated": "一个概念的掌握证据发生了变化，系统记录的是能力变化而不是打卡次数。",
        "research.completed": "一次研究形成了可保存的结果；是否继续形成内容由你决定。",
        "reflection.completed": "你完成了一次对兴趣、精力与理解变化的回顾。",
        "misconception.resolved": "一个混淆被澄清，这属于真实的理解变化。",
    }
    if event.type not in messages:
        return
    with get_session_factory()() as db:
        db.add(GrowthEventModel(event_type=event.type, message=messages[event.type], payload=event.payload))
        db.commit()


for _event_type in [
    "question.returned",
    "claim.revised",
    "mastery.updated",
    "research.completed",
    "reflection.completed",
    "misconception.resolved",
]:
    bus.subscribe(_event_type, _growth_handler)


def _content_invalidation_handler(event: DomainEvent) -> None:
    """A revised Claim invalidates prior approval of dependent publish artifacts."""
    if event.type not in {"claim.revised", "claim.reverification_required"} or not is_plugin_enabled("capability.content-studio"):
        return
    claim_id = str(event.payload.get("claim_id") or "")
    if not claim_id:
        return
    with get_session_factory()() as db:
        rows = db.query(ArtifactModel).filter(ArtifactModel.kind.in_(["xhs_pack", "article"])).all()
        changed = False
        for row in rows:
            metadata = dict(row.metadata_json or {})
            if claim_id not in list(metadata.get("claim_ids") or []):
                continue
            metadata["review_needed"] = True
            metadata["review_reason"] = (
                "linked_claim_revised" if event.type == "claim.revised" else "linked_claim_reverification_required"
            )
            metadata["invalidated_by_claim_id"] = claim_id
            row.metadata_json = metadata
            row.approved_at = None
            changed = True
        if changed:
            db.commit()


bus.subscribe("claim.revised", _content_invalidation_handler)
bus.subscribe("claim.reverification_required", _content_invalidation_handler)


def _living_book_invalidation_handler(event: DomainEvent) -> None:
    if event.type not in {"claim.revised", "claim.reverification_required"} or not is_plugin_enabled("capability.living-book"):
        return
    claim_id = str(event.payload.get("claim_id") or "")
    if not claim_id:
        return
    from .living_book import mark_chapters_stale_for_claim
    mark_chapters_stale_for_claim(claim_id, event.type)


bus.subscribe("claim.revised", _living_book_invalidation_handler)
bus.subscribe("claim.reverification_required", _living_book_invalidation_handler)


def emit(event_type: str, payload: dict) -> DomainEvent:
    event = DomainEvent(type=event_type, payload=payload)
    errors = bus.publish(event)
    with get_session_factory()() as db:
        db.add(DomainEventRecordModel(
            id=event.id,
            type=event.type,
            payload=event.payload,
            schema_version=event.schema_version,
            occurred_at=event.occurred_at,
            subscriber_errors=[f"{type(e).__name__}: {e}" for e in errors],
        ))
        db.commit()
    return event
