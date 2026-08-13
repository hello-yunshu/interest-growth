from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

_installed = False


def install_area_scoping_hooks() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Session, "before_flush")
    def _bind_new_entities(session: Session, flush_context, instances) -> None:  # noqa: ARG001
        if session.info.get("skip_area_scope"):
            return
        from .db import EntityAreaBindingModel, new_id
        from .domains import MODEL_ENTITY_TYPES, bind_entity, resolve_area

        snapshot = list(session.new)
        if not snapshot:
            return
        area = resolve_area(db=session)
        for obj in snapshot:
            if isinstance(obj, EntityAreaBindingModel):
                continue
            entity_type = MODEL_ENTITY_TYPES.get(type(obj))
            if not entity_type:
                continue
            entity_id = getattr(obj, "id", None)
            if not entity_id:
                entity_id = new_id()
                setattr(obj, "id", entity_id)
            bind_entity(session, entity_type, str(entity_id), area_id=area.id)
