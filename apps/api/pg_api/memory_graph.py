from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .db import GrowthMemoryModel, get_session_factory
from .domains import filter_rows_to_current_area, get_domain_context


def local_growth_graph() -> dict[str, Any]:
    with get_session_factory()() as db:
        rows = filter_rows_to_current_area(db, db.scalars(select(GrowthMemoryModel).order_by(GrowthMemoryModel.layer, GrowthMemoryModel.updated_at.desc())).all(), "growth_memory")
    nodes = []
    edges = []
    for row in rows:
        node_id = f"growth:{row.id}"
        nodes.append({
            'id': node_id, 'system': 'growth_memory', 'layer': row.layer,
            'type': row.memory_type, 'key': row.key, 'confidence': row.confidence,
            'status': row.status, 'authoritative': True,
        })
        for ref in row.source_refs or []:
            edges.append({'from': node_id, 'to': str(ref), 'type': 'derived_from_local_ref'})
    context = get_domain_context()
    return {'area': {'id': context.area_id, 'name': context.area_name}, 'nodes': nodes, 'edges': edges}


def native_auxiliary_graph(context) -> dict[str, Any]:
    from .native_execution import get_native_bundle
    return {'available': True, **get_native_bundle().memory.audit_graph(context)}
