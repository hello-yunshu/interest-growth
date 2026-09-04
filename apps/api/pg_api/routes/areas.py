from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..db import AreaCapabilitySettingModel, DomainPackModel, InterestAreaModel, MasteryProfileModel, get_session_factory
from ..domains import (
    area_summary,
    create_interest_area,
    get_domain_context,
    resolve_area,
    set_area_capability,
    mastery_profile_summary,
    current_mastery_profile,
)
from ..schemas import AreaCapabilityUpdate, InterestAreaCreate, InterestAreaUpdate
from ..serializers import model_dict
from ..plugins import get_plugin_runtime

router = APIRouter(tags=["interest-areas"])


@router.get("/areas")
def list_areas(include_archived: bool = False):
    with get_session_factory()() as db:
        stmt = select(InterestAreaModel).order_by(InterestAreaModel.position, InterestAreaModel.created_at)
        if not include_archived:
            stmt = stmt.where(InterestAreaModel.archived.is_(False))
        rows = db.scalars(stmt).all()
        return {"areas": [area_summary(row) for row in rows]}


@router.post("/areas")
def add_area(body: InterestAreaCreate):
    try:
        row = create_interest_area(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return area_summary(row)


@router.get("/areas/current")
def current_area():
    try:
        context = get_domain_context()
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "area": {
            "id": context.area_id,
            "slug": context.area_slug,
            "name": context.area_name,
            "domain_pack_id": context.domain_pack_id,
            "domain_name": context.domain_name,
            "mastery_profile_id": context.mastery_profile_id,
        },
        "mastery_profile": mastery_profile_summary(current_mastery_profile()),
        "domain": {
            "description": context.description,
            "skills": context.skills,
            "personas": context.personas,
            "research": context.research,
            "quick_explore": context.quick_explore,
            "content": context.content,
        },
    }


@router.patch("/areas/{area_id}")
def update_area(area_id: str, body: InterestAreaUpdate):
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        row = db.get(InterestAreaModel, area_id)
        if row is None:
            raise HTTPException(404, "interest area not found")
        if row.is_default and body.archived is True:
            raise HTTPException(409, "default interest area cannot be archived")
        for key, value in body.model_dump(exclude_none=True).items():
            setattr(row, key, value)
        db.commit(); db.refresh(row)
        return area_summary(row)


@router.post("/areas/{area_id}/restore")
def restore_area(area_id: str):
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        row = db.get(InterestAreaModel, area_id)
        if row is None:
            raise HTTPException(404, "interest area not found")
        row.archived = False
        db.commit(); db.refresh(row)
        return area_summary(row)


@router.get("/areas/{area_id}/capabilities")
def list_area_capabilities(area_id: str):
    with get_session_factory()() as db:
        area = db.get(InterestAreaModel, area_id)
        if area is None:
            raise HTTPException(404, "interest area not found")
        rows = db.scalars(select(AreaCapabilitySettingModel).where(
            AreaCapabilitySettingModel.area_id == area_id
        ).order_by(AreaCapabilitySettingModel.plugin_id)).all()
        return {"area_id": area_id, "capabilities": [model_dict(x) for x in rows]}


@router.put("/areas/{area_id}/capabilities/{plugin_id:path}")
def update_area_capability(area_id: str, plugin_id: str, body: AreaCapabilityUpdate):
    runtime = get_plugin_runtime()
    if plugin_id not in runtime.manifests:
        raise HTTPException(404, {"code": "unknown_plugin", "plugin": plugin_id})
    if not plugin_id.startswith("capability."):
        raise HTTPException(400, {
            "code": "not_area_capability",
            "plugin": plugin_id,
            "detail": "Interest Area overrides apply only to capability.* plugins; core/provider lifecycle is global.",
        })
    try:
        return model_dict(set_area_capability(area_id, plugin_id, body.enabled))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/domain-packs")
def list_domain_packs():
    with get_session_factory()() as db:
        packs = db.scalars(select(DomainPackModel).order_by(DomainPackModel.id)).all()
        profiles = db.scalars(select(MasteryProfileModel).order_by(MasteryProfileModel.id)).all()
        by_pack: dict[str, list[dict]] = {}
        for profile in profiles:
            by_pack.setdefault(profile.domain_pack_id, []).append(model_dict(profile))
        return {
            "domain_packs": [
                {**model_dict(pack), "mastery_profiles": by_pack.get(pack.id, [])}
                for pack in packs
            ]
        }
