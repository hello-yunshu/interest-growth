from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from pg_shared import get_settings

from ..db import FeatureFlagModel, get_server_identity, get_session_factory
from ..engines import integration_status
from ..features import DEFAULT_FLAGS, feature_enabled
from ..domains import area_capability_enabled, get_domain_context
from ..plugins import get_plugin_runtime
from ..memory_graph import native_auxiliary_graph, local_growth_graph
from ..schemas import FeatureFlagUpdate
from ..native_execution import resolve_native_context
from ..remote_auth import API_VERSION, MIN_CLIENT_VERSION, PRODUCT_NAME, SERVER_VERSION, owner_configured

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "interest-growth-api", "version": SERVER_VERSION, "desktop_mode": get_settings().app_env == "desktop"}


@router.get("/system/capabilities")
def system_capabilities():
    settings = get_settings()
    identity = get_server_identity()
    return {
        "product": PRODUCT_NAME,
        "server_version": SERVER_VERSION,
        "api_version": API_VERSION,
        "min_client_version": MIN_CLIENT_VERSION,
        "server_instance_id": identity["server_instance_id"],
        "server_display_name": identity["server_display_name"],
        "runtime_modes": ["desktop-local", "desktop-remote", "android-remote", "browser-remote"],
        "auth": {
            "mode": "single_owner_devices" if settings.remote_auth_enabled else "none",
            "enabled": settings.remote_auth_enabled,
            "owner_configured": owner_configured() if settings.remote_auth_enabled else False,
        },
        "online_first": True,
        "offline_sync": False,
        "public_health": True,
    }


@router.get("/system/capability-state")
def system_capability_state():
    """Return the same fail-closed inputs used by executable capability gates."""
    context = get_domain_context()
    runtime = get_plugin_runtime()
    plugin_rows = runtime.list_status()
    return {
        "area": {"id": context.area_id, "slug": context.area_slug, "name": context.area_name},
        "features": {name: feature_enabled(name) for name in DEFAULT_FLAGS},
        "plugins": {
            row["manifest"]["id"]: {
                "installed": row["installed"],
                "enabled": row["enabled"],
                "lifecycle_state": row["lifecycle_state"],
                "area_enabled": area_capability_enabled(row["manifest"]["id"], context.area_id)
                if row["manifest"]["id"].startswith("capability.") else True,
            }
            for row in plugin_rows
        },
    }


@router.get("/system/desktop-runtime")
def desktop_runtime_info():
    settings = get_settings()
    return {
        "desktop_mode": settings.app_env == "desktop",
        "version": SERVER_VERSION,
        "data_root": settings.app_data_root,
        "token_required": bool(settings.desktop_token),
        "product": "Interest Growth",
    }


@router.get("/system/integrations")
async def integrations():
    return await integration_status()


@router.get("/plugins")
def list_plugins():
    return {"plugins": get_plugin_runtime().list_status()}


@router.post("/plugins/{plugin_id}/install")
def install_plugin(plugin_id: str):
    runtime = get_plugin_runtime()
    if plugin_id not in runtime.manifests:
        raise HTTPException(404, "plugin not found")
    try:
        runtime.install(plugin_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"plugin_id": plugin_id, "lifecycle_state": "installed", "data_preserved": True}


@router.post("/plugins/{plugin_id}/uninstall")
def uninstall_plugin(plugin_id: str):
    runtime = get_plugin_runtime()
    if plugin_id not in runtime.manifests:
        raise HTTPException(404, "plugin not found")
    try:
        runtime.uninstall(plugin_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"plugin_id": plugin_id, "lifecycle_state": "uninstalled", "data_preserved": True}


@router.post("/plugins/{plugin_id}/update")
def update_plugin(plugin_id: str):
    runtime = get_plugin_runtime()
    if plugin_id not in runtime.manifests:
        raise HTTPException(404, "plugin not found")
    try:
        runtime.update(plugin_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    state = next(x for x in runtime.list_status() if x["manifest"]["id"] == plugin_id)
    return {"plugin_id": plugin_id, "lifecycle_state": state["lifecycle_state"], "installed_version": state["installed_version"], "previous_version": state["previous_version"]}


@router.post("/plugins/{plugin_id}/rollback")
def rollback_plugin(plugin_id: str):
    runtime = get_plugin_runtime()
    if plugin_id not in runtime.manifests:
        raise HTTPException(404, "plugin not found")
    try:
        runtime.rollback(plugin_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    state = next(x for x in runtime.list_status() if x["manifest"]["id"] == plugin_id)
    return {"plugin_id": plugin_id, "lifecycle_state": state["lifecycle_state"], "installed_version": state["installed_version"], "previous_version": state["previous_version"]}


@router.post("/plugins/{plugin_id}/enable")
def enable_plugin(plugin_id: str):
    runtime = get_plugin_runtime()
    if plugin_id not in runtime.manifests:
        raise HTTPException(404, "plugin not found")
    try:
        runtime.enable(plugin_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"plugin_id": plugin_id, "enabled": True}


@router.post("/plugins/{plugin_id}/disable")
def disable_plugin(plugin_id: str):
    runtime = get_plugin_runtime()
    if plugin_id not in runtime.manifests:
        raise HTTPException(404, "plugin not found")
    try:
        runtime.disable(plugin_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"plugin_id": plugin_id, "enabled": False, "data_preserved": True}


@router.get("/features")
def list_features():
    with get_session_factory()() as db:
        rows = db.scalars(select(FeatureFlagModel).order_by(FeatureFlagModel.name)).all()
        return {"features": [{"name": r.name, "enabled": r.enabled} for r in rows]}


@router.put("/features/{name}")
def update_feature(name: str, body: FeatureFlagUpdate):
    with get_session_factory()() as db:
        row = db.get(FeatureFlagModel, name)
        if row is None:
            raise HTTPException(404, "feature flag not found")
        row.enabled = body.enabled
        db.commit()
        return {"name": row.name, "enabled": row.enabled}


@router.get("/memory/graph")
async def memory_graph(request: Request):
    context = resolve_native_context(request, "memory.read")
    local = local_growth_graph()
    auxiliary = native_auxiliary_graph(context)
    return {
        "ownership": "Growth Memory is authoritative. Native execution memory is auxiliary agent-work memory only.",
        "local_growth_memory": local,
        "native_auxiliary": auxiliary,
    }
