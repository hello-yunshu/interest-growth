from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from pg_plugin_runtime import PermissionBroker, PluginPermissionDenied, PluginRuntime, PluginStateRecord
from pg_shared import resource_root

from .db import PluginStateModel, get_session_factory

PROJECT_ROOT = resource_root()
_runtime: PluginRuntime | None = None

LEGACY_PLUGIN_IDS: dict[str, str] = {
    "psychology.growth-core": "core.interest-growth",
    "psychology.curiosity": "capability.curiosity",
    "psychology.research-evidence": "capability.research-evidence",
    "psychology.knowledge-rag": "capability.knowledge",
    "psychology.flexible-mastery": "capability.mastery",
    "psychology.concept-graph": "capability.concept-graph",
    "psychology.growth-feedback": "capability.growth-feedback",
    "psychology.reflection": "capability.reflection",
    "psychology.content-studio": "capability.content-studio",
    "psychology.media-prompt": "capability.media-prompt",
    "psychology.career": "capability.career",
    "psychology.co-writer": "capability.co-writer",
    "psychology.practice": "capability.practice",
    "psychology.learning-notebook": "capability.learning-notebook",
    "psychology.tutor-persona": "capability.tutor-persona",
    "psychology.tutor-runtime": "capability.tutor-runtime",
    "psychology.living-book": "capability.living-book",
    "psychology.memory-graph": "capability.memory-graph",
}


def canonical_plugin_id(plugin_id: str) -> str:
    return LEGACY_PLUGIN_IDS.get(plugin_id, plugin_id)


def migrate_legacy_plugin_states() -> None:
    """Copy persisted v0.4.1 psychology.* state to neutral capability IDs.

    Old rows remain as compatibility history; runtime discovery only loads current manifests.
    """
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        for legacy_id, current_id in LEGACY_PLUGIN_IDS.items():
            old = db.get(PluginStateModel, legacy_id)
            current = db.get(PluginStateModel, current_id)
            if old is None or current is not None:
                continue
            db.add(PluginStateModel(
                plugin_id=current_id,
                enabled=old.enabled,
                installed_version=old.installed_version,
                lifecycle_state=old.lifecycle_state,
                previous_version=old.previous_version,
            ))
        db.commit()


def _get_state(plugin_id: str) -> PluginStateRecord | None:
    plugin_id = canonical_plugin_id(plugin_id)
    with get_session_factory()() as db:
        row = db.get(PluginStateModel, plugin_id)
        if not row:
            return None
        return PluginStateRecord(
            row.plugin_id, row.enabled, row.installed_version, row.lifecycle_state, row.previous_version
        )


def _set_state(state: PluginStateRecord) -> None:
    plugin_id = canonical_plugin_id(state.plugin_id)
    with get_session_factory()() as db:
        row = db.get(PluginStateModel, plugin_id)
        if row:
            row.enabled = state.enabled
            row.installed_version = state.installed_version
            row.lifecycle_state = state.lifecycle_state
            row.previous_version = state.previous_version
        else:
            db.add(PluginStateModel(
                plugin_id=plugin_id,
                enabled=state.enabled,
                installed_version=state.installed_version,
                lifecycle_state=state.lifecycle_state,
                previous_version=state.previous_version,
            ))
        db.commit()


def get_plugin_runtime(refresh: bool = False) -> PluginRuntime:
    global _runtime
    if _runtime is None or refresh:
        _runtime = PluginRuntime(PROJECT_ROOT / "plugins", _get_state, _set_state)
        _runtime.discover()
        _runtime.install_defaults()
    return _runtime


def is_plugin_enabled(plugin_id: str) -> bool:
    return get_plugin_runtime().is_enabled(canonical_plugin_id(plugin_id))


def is_plugin_available_in_current_area(plugin_id: str) -> bool:
    plugin_id = canonical_plugin_id(plugin_id)
    if not is_plugin_enabled(plugin_id):
        return False
    if plugin_id.startswith("capability."):
        try:
            from .domains import area_capability_enabled
            return area_capability_enabled(plugin_id)
        except (RuntimeError, ValueError):
            return False
    return True


def require_plugin(plugin_id: str) -> None:
    plugin_id = canonical_plugin_id(plugin_id)
    if not is_plugin_enabled(plugin_id):
        raise HTTPException(status_code=503, detail={"code": "plugin_disabled", "plugin": plugin_id})
    if plugin_id.startswith("capability."):
        from .domains import area_capability_enabled, resolve_area
        try:
            area = resolve_area()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "unknown_interest_area", "detail": str(exc)}) from exc
        if not area_capability_enabled(plugin_id, area.id):
            raise HTTPException(status_code=503, detail={
                "code": "capability_disabled_for_area",
                "plugin": plugin_id,
                "area_id": area.id,
            })


def permission_broker() -> PermissionBroker:
    return PermissionBroker(get_plugin_runtime())


def require_plugin_resource(plugin_id: str, operation: str, resource: str) -> None:
    plugin_id = canonical_plugin_id(plugin_id)
    try:
        permission_broker().require_resource(plugin_id, operation, resource)
    except PluginPermissionDenied as exc:
        raise HTTPException(status_code=403, detail={"code": "plugin_permission_denied", "detail": str(exc)}) from exc


def require_plugin_risk(plugin_id: str, capability: str) -> None:
    plugin_id = canonical_plugin_id(plugin_id)
    try:
        permission_broker().require_risk(plugin_id, capability)
    except PluginPermissionDenied as exc:
        raise HTTPException(status_code=403, detail={"code": "plugin_permission_denied", "detail": str(exc)}) from exc


def require_plugin_access(
    plugin_id: str,
    *,
    read: tuple[str, ...] | list[str] = (),
    write: tuple[str, ...] | list[str] = (),
    risks: tuple[str, ...] | list[str] = (),
) -> None:
    """Enforce first-party plugin availability plus declared capability boundaries.

    This is deliberately not a hostile-code sandbox. It ensures trusted product routes
    cannot silently exceed the resources and high-risk capabilities declared by their
    manifests, while Interest Area enable/disable remains enforced by ``require_plugin``.
    """
    require_plugin(plugin_id)
    for resource in read:
        require_plugin_resource(plugin_id, "read", resource)
    for resource in write:
        require_plugin_resource(plugin_id, "write", resource)
    for capability in risks:
        require_plugin_risk(plugin_id, capability)
