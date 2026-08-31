from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..db import CareerExperimentModel, get_session_factory
from ..events import emit
from ..domains import filter_rows_to_current_area, require_entity_in_current_area, get_domain_context
from ..features import feature_enabled
from ..plugins import require_plugin_access
from ..schemas import CareerExperimentCreate, CareerExperimentUpdate
from ..serializers import model_dict

router = APIRouter(tags=["career-exploration"])


def _require_career(*, read=(), write=()):
    require_plugin_access("capability.career", read=read, write=write)
    if not feature_enabled("FEATURE_CAREER"):
        raise HTTPException(503, "career feature disabled")


@router.get("/career/experiments")
def list_experiments():
    _require_career(read=("career_experiment",))
    with get_session_factory()() as db:
        rows = filter_rows_to_current_area(db, db.scalars(
            select(CareerExperimentModel).order_by(CareerExperimentModel.created_at.desc())
        ).all(), "career_experiment")
        return {"experiments": [model_dict(x) for x in rows]}


@router.post("/career/experiments")
def create_experiment(body: CareerExperimentCreate):
    _require_career(write=("career_experiment",))
    row = CareerExperimentModel(**body.model_dump())
    with get_session_factory()() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    emit("career.experiment_created", {"experiment_id": row.id, "direction": row.direction})
    return model_dict(row)


@router.put("/career/experiments/{experiment_id}")
def update_experiment(experiment_id: str, body: CareerExperimentUpdate):
    _require_career(read=("career_experiment",), write=("career_experiment",))
    with get_session_factory()() as db:
        row = db.get(CareerExperimentModel, experiment_id)
        if not row:
            raise HTTPException(404, "career experiment not found")
        try:
            require_entity_in_current_area(db, "career_experiment", experiment_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        for key, value in body.model_dump(exclude_none=True).items():
            setattr(row, key, value)
        db.commit()
        db.refresh(row)
    emit("career.experiment_updated", {"experiment_id": row.id, "status": row.status})
    return model_dict(row)


@router.get("/career/summary")
def career_summary():
    _require_career(read=("career_experiment",))
    with get_session_factory()() as db:
        rows = filter_rows_to_current_area(db, db.scalars(select(CareerExperimentModel)).all(), "career_experiment")
    completed = [x for x in rows if x.status == "completed" and x.interest_after is not None]
    directions: dict[str, dict] = {}
    for row in completed:
        bucket = directions.setdefault(row.direction, {"experiments": 0, "interest_change": 0})
        bucket["experiments"] += 1
        bucket["interest_change"] += row.interest_after - row.interest_before
    context = get_domain_context()
    ranked = sorted(directions.items(), key=lambda item: (item[1]["interest_change"], item[1]["experiments"]), reverse=True)
    top_change = ranked[0][1]["interest_change"] if ranked else None
    ties = [name for name, value in ranked if value["interest_change"] == top_change] if ranked else []
    direction = ties[0] if len(ties) == 1 else None
    confidence = "low" if len(completed) < 3 or len(ties) != 1 else ("medium" if len(completed) < 6 else "high")
    basis = (
        f"仅基于 {len(completed)} 个已完成实验的兴趣前后变化；未完成实验不会进入信号。"
        if completed else "还没有已完成实验，因此暂不形成方向信号。"
    )
    return {
        "area": {"id": context.area_id, "name": context.area_name},
        "principle": "方向判断来自当前兴趣领域中反复、可逆的真实实验，而不是一次想象中的匹配。",
        "completed_experiments": len(completed),
        "directions": directions,
        "most_promising_direction": direction,
        "signal": {
            "direction": direction,
            "confidence": confidence,
            "basis": basis,
            "sample_size": len(completed),
            "ties": ties,
        },
    }
