from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable

import yaml
from sqlalchemy import select

from pg_shared import resource_root

from .area_context import current_area_selector
from .db import (
    AreaCapabilitySettingModel,
    CapabilityRunModel,
    ClaimModel,
    ClaimVersionModel,
    ConceptModel,
    DomainEventRecordModel,
    DomainPackModel,
    EntityAreaBindingModel,
    EvidenceModel,
    GroundingRefModel,
    GrowthEventModel,
    GrowthMemoryModel,
    InterestAreaModel,
    KnowledgeBaseModel,
    KnowledgeIngestionRunModel,
    KnowledgeSourceIndexModel,
    LearningActivityModel,
    LearningNoteModel,
    LivingBookChapterModel,
    LivingBookModel,
    MasteryEvidenceModel,
    MasteryProfileModel,
    MasteryRecordModel,
    PracticeAttemptModel,
    PracticeItemModel,
    QuestionModel,
    ReflectionModel,
    RetrievalCandidateModel,
    SourceModel,
    TopicModel,
    TutorPersonaModel,
    TutorSessionModel,
    TutorTurnModel,
    WritingDocumentModel,
    WritingRevisionModel,
    ArtifactModel,
    CareerExperimentModel,
    PersonaScopeModel,
    get_session_factory,
)

DEFAULT_AREA_SLUG = "psychology"
DEFAULT_DOMAIN_PACK = "psychology"
GENERAL_DOMAIN_PACK = "general"


@dataclass(slots=True)
class DomainContext:
    area_id: str
    area_slug: str
    area_name: str
    domain_pack_id: str
    domain_name: str
    description: str
    policy: dict[str, Any]
    default_capabilities: dict[str, bool]
    skills: list[str]
    personas: list[str]
    mastery_profile_id: str

    @property
    def research(self) -> dict[str, Any]:
        return dict(self.policy.get("research") or {})

    @property
    def quick_explore(self) -> dict[str, Any]:
        return dict(self.policy.get("quick_explore") or {})

    @property
    def content(self) -> dict[str, Any]:
        return dict(self.policy.get("content") or {})


SCOPED_MODELS: dict[str, type] = {
    "question": QuestionModel,
    "topic": TopicModel,
    "source": SourceModel,
    "evidence": EvidenceModel,
    "claim": ClaimModel,
    "claim_version": ClaimVersionModel,
    "concept": ConceptModel,
    "mastery": MasteryRecordModel,
    "domain_event": DomainEventRecordModel,
    "growth_event": GrowthEventModel,
    "growth_memory": GrowthMemoryModel,
    "reflection": ReflectionModel,
    "artifact": ArtifactModel,
    "practice_item": PracticeItemModel,
    "practice_attempt": PracticeAttemptModel,
    "mastery_evidence": MasteryEvidenceModel,
    "learning_note": LearningNoteModel,
    "tutor_persona": TutorPersonaModel,
    "writing_document": WritingDocumentModel,
    "writing_revision": WritingRevisionModel,
    "living_book": LivingBookModel,
    "living_book_chapter": LivingBookChapterModel,
    "tutor_session": TutorSessionModel,
    "tutor_turn": TutorTurnModel,
    "capability_run": CapabilityRunModel,
    "knowledge_base": KnowledgeBaseModel,
    "knowledge_source_index": KnowledgeSourceIndexModel,
    "knowledge_ingestion_run": KnowledgeIngestionRunModel,
    "retrieval_candidate": RetrievalCandidateModel,
    "career_experiment": CareerExperimentModel,
}
MODEL_ENTITY_TYPES = {model: entity_type for entity_type, model in SCOPED_MODELS.items()}


def _domain_root() -> Path:
    return resource_root() / "domains"


def load_domain_specs() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(_domain_root().glob("*/domain.yaml")):
        payload = yaml.safe_load(path.read_text("utf-8")) or {}
        pack_id = str(payload.get("id") or path.parent.name).strip()
        if not pack_id:
            continue
        payload["_root"] = str(path.parent)
        result[pack_id] = payload
    return result


def _load_persona_specs(pack_id: str) -> list[dict[str, str]]:
    path = _domain_root() / pack_id / "personas" / "personas.yaml"
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text("utf-8")) or {}
    return [dict(x) for x in payload.get("personas", []) if isinstance(x, dict)]


def domain_skill_roots(pack_id: str) -> list[Path]:
    roots = [_domain_root() / GENERAL_DOMAIN_PACK / "skills"]
    if pack_id != GENERAL_DOMAIN_PACK:
        roots.append(_domain_root() / pack_id / "skills")
    return [p for p in roots if p.exists()]


def domain_skill_names(pack_id: str) -> list[str]:
    names: list[str] = []
    for root in domain_skill_roots(pack_id):
        for path in sorted(root.glob("*/SKILL.md")):
            name = path.parent.name
            try:
                text_value = path.read_text("utf-8")
                if text_value.startswith("---"):
                    _, frontmatter, _ = text_value.split("---", 2)
                    payload = yaml.safe_load(frontmatter) or {}
                    name = str(payload.get("name") or name).strip()
            except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                pass
            if name not in names:
                names.append(name)
    return names


def seed_domain_packs_and_default_area() -> None:
    specs = load_domain_specs()
    if GENERAL_DOMAIN_PACK not in specs or DEFAULT_DOMAIN_PACK not in specs:
        raise RuntimeError("general and psychology domain packs are required")
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        for pack_id, spec in specs.items():
            policy = {
                "research": dict(spec.get("research") or {}),
                "quick_explore": dict(spec.get("quick_explore") or {}),
                "content": dict(spec.get("content") or {}),
            }
            row = db.get(DomainPackModel, pack_id)
            values = dict(
                name=str(spec.get("name") or pack_id),
                version=str(spec.get("version") or "1.0.0"),
                description=str(spec.get("description") or ""),
                policy_json=policy,
                default_capabilities=dict(spec.get("capabilities") or {}),
                default_skills=list(spec.get("skills") or []),
                default_personas=list(spec.get("personas") or []),
                builtin=True,
            )
            if row is None:
                row = DomainPackModel(id=pack_id, **values)
                db.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            for profile in list(spec.get("mastery_profiles") or []):
                if not isinstance(profile, dict) or not profile.get("id"):
                    continue
                pid = str(profile["id"])
                p = db.get(MasteryProfileModel, pid)
                values_p = dict(
                    domain_pack_id=pack_id,
                    name=str(profile.get("name") or pid),
                    description=str(profile.get("description") or ""),
                    states=[str(x) for x in profile.get("states", [])],
                    is_default=bool(profile.get("default", False)),
                )
                if p is None:
                    db.add(MasteryProfileModel(id=pid, **values_p))
                else:
                    for key, value in values_p.items():
                        setattr(p, key, value)
        db.flush()
        area = db.scalar(select(InterestAreaModel).where(InterestAreaModel.slug == DEFAULT_AREA_SLUG))
        psych_spec = specs[DEFAULT_DOMAIN_PACK]
        if area is None:
            area = InterestAreaModel(
                slug=DEFAULT_AREA_SLUG,
                name="心理学",
                description="默认兴趣领域；保留证据驱动、诊断边界和人工审核策略。",
                domain_pack_id=DEFAULT_DOMAIN_PACK,
                mastery_profile_id=str(psych_spec.get("mastery_profile") or "psychology:conceptual-evidence"),
                icon="brain",
                accent="indigo",
                is_default=True,
                position=0,
            )
            db.add(area)
            db.flush()
        # Exactly one default is preferable; do not archive user-created areas.
        for other in db.scalars(select(InterestAreaModel)).all():
            other.is_default = other.id == area.id
        _ensure_area_capability_defaults(db, area, psych_spec)
        db.commit()
    seed_domain_personas()


def _ensure_area_capability_defaults(db, area: InterestAreaModel, spec: dict[str, Any] | None = None) -> None:
    if spec is None:
        spec = load_domain_specs().get(area.domain_pack_id, {})
    defaults = dict(spec.get("capabilities") or {})
    for plugin_id, enabled in defaults.items():
        row = db.scalar(
            select(AreaCapabilitySettingModel).where(
                AreaCapabilitySettingModel.area_id == area.id,
                AreaCapabilitySettingModel.plugin_id == plugin_id,
            )
        )
        if row is None:
            db.add(AreaCapabilitySettingModel(
                area_id=area.id,
                plugin_id=plugin_id,
                enabled=bool(enabled),
                source="domain_default",
            ))


def seed_domain_personas() -> None:
    specs = load_domain_specs()
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        for pack_id in specs:
            for spec in _load_persona_specs(pack_id):
                name = str(spec.get("name") or "").strip()
                if not name:
                    continue
                persona = db.scalar(select(TutorPersonaModel).where(TutorPersonaModel.name == name))
                values = {
                    "description": str(spec.get("description") or ""),
                    "content": str(spec.get("content") or ""),
                    "builtin": True,
                }
                if persona is None:
                    persona = TutorPersonaModel(name=name, **values)
                    db.add(persona)
                    db.flush()
                else:
                    for key, value in values.items():
                        setattr(persona, key, value)
                scope = db.scalar(
                    select(PersonaScopeModel).where(
                        PersonaScopeModel.persona_id == persona.id,
                        PersonaScopeModel.scope_type == "domain_pack",
                        PersonaScopeModel.scope_id == pack_id,
                    )
                )
                if scope is None:
                    db.add(PersonaScopeModel(persona_id=persona.id, scope_type="domain_pack", scope_id=pack_id))
        db.commit()


def get_default_area(db=None) -> InterestAreaModel:
    owns = db is None
    db = db or get_session_factory()()
    try:
        row = db.scalar(select(InterestAreaModel).where(InterestAreaModel.is_default.is_(True), InterestAreaModel.archived.is_(False)))
        if row is None:
            row = db.scalar(select(InterestAreaModel).where(InterestAreaModel.slug == DEFAULT_AREA_SLUG))
        if row is None:
            raise RuntimeError("default interest area is missing")
        return row
    finally:
        if owns:
            db.close()


def resolve_area(selector: str | None = None, db=None) -> InterestAreaModel:
    owns = db is None
    db = db or get_session_factory()()
    try:
        raw = (selector if selector is not None else current_area_selector()).strip()
        if not raw:
            return get_default_area(db)
        row = db.get(InterestAreaModel, raw)
        if row is None:
            row = db.scalar(select(InterestAreaModel).where(InterestAreaModel.slug == raw))
        if row is None or row.archived:
            raise ValueError(f"unknown or archived interest area: {raw}")
        return row
    finally:
        if owns:
            db.close()


def get_domain_context(selector: str | None = None) -> DomainContext:
    with get_session_factory()() as db:
        area = resolve_area(selector, db)
        pack = db.get(DomainPackModel, area.domain_pack_id)
        if pack is None:
            raise RuntimeError(f"domain pack missing: {area.domain_pack_id}")
        return DomainContext(
            area_id=area.id,
            area_slug=area.slug,
            area_name=area.name,
            domain_pack_id=pack.id,
            domain_name=pack.name,
            description=pack.description,
            policy=dict(pack.policy_json or {}),
            default_capabilities=dict(pack.default_capabilities or {}),
            skills=domain_skill_names(pack.id),
            personas=list(pack.default_personas or []),
            mastery_profile_id=area.mastery_profile_id,
        )


def create_interest_area(*, name: str, slug: str, description: str = "", domain_pack_id: str = GENERAL_DOMAIN_PACK,
                         icon: str = "sparkles", accent: str = "neutral") -> InterestAreaModel:
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.strip().lower()).strip("-")
    if not slug:
        raise ValueError("area slug is required")
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        if db.get(DomainPackModel, domain_pack_id) is None:
            raise ValueError("domain pack not found")
        if db.scalar(select(InterestAreaModel).where(InterestAreaModel.slug == slug)):
            raise ValueError("area slug already exists")
        profile = db.scalar(select(MasteryProfileModel).where(
            MasteryProfileModel.domain_pack_id == domain_pack_id,
            MasteryProfileModel.is_default.is_(True),
        ))
        row = InterestAreaModel(
            slug=slug,
            name=name.strip(),
            description=description.strip(),
            domain_pack_id=domain_pack_id,
            mastery_profile_id=profile.id if profile else "",
            icon=icon,
            accent=accent,
            position=(db.query(InterestAreaModel).count() + 1),
        )
        db.add(row)
        db.flush()
        _ensure_area_capability_defaults(db, row)
        db.commit()
        db.refresh(row)
        return row


def area_capability_enabled(plugin_id: str, selector: str | None = None) -> bool:
    with get_session_factory()() as db:
        area = resolve_area(selector, db)
        row = db.scalar(select(AreaCapabilitySettingModel).where(
            AreaCapabilitySettingModel.area_id == area.id,
            AreaCapabilitySettingModel.plugin_id == plugin_id,
        ))
        if row is not None:
            return bool(row.enabled)
        pack = db.get(DomainPackModel, area.domain_pack_id)
        return bool((pack.default_capabilities or {}).get(plugin_id, True)) if pack else True


def set_area_capability(area_id: str, plugin_id: str, enabled: bool) -> AreaCapabilitySettingModel:
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        area = db.get(InterestAreaModel, area_id)
        if area is None:
            raise ValueError("interest area not found")
        row = db.scalar(select(AreaCapabilitySettingModel).where(
            AreaCapabilitySettingModel.area_id == area_id,
            AreaCapabilitySettingModel.plugin_id == plugin_id,
        ))
        if row is None:
            row = AreaCapabilitySettingModel(area_id=area_id, plugin_id=plugin_id, enabled=enabled, source="user")
            db.add(row)
        else:
            row.enabled = enabled
            row.source = "user"
        db.commit(); db.refresh(row); return row


def entity_area_ids(db, entity_type: str, entity_id: str) -> list[str]:
    return list(db.scalars(select(EntityAreaBindingModel.area_id).where(
        EntityAreaBindingModel.entity_type == entity_type,
        EntityAreaBindingModel.entity_id == str(entity_id),
    )).all())


def primary_entity_area_id(db, entity_type: str, entity_id: str) -> str | None:
    row = db.scalar(select(EntityAreaBindingModel).where(
        EntityAreaBindingModel.entity_type == entity_type,
        EntityAreaBindingModel.entity_id == str(entity_id),
        EntityAreaBindingModel.is_primary.is_(True),
    ))
    return row.area_id if row else None


def bind_entity(db, entity_type: str, entity_id: str, *, area_id: str | None = None,
                sharing: str = "private", is_primary: bool = True) -> EntityAreaBindingModel:
    area_id = area_id or resolve_area(db=db).id
    existing = db.scalar(select(EntityAreaBindingModel).where(
        EntityAreaBindingModel.entity_type == entity_type,
        EntityAreaBindingModel.entity_id == str(entity_id),
        EntityAreaBindingModel.area_id == area_id,
    ))
    if existing:
        return existing
    row = EntityAreaBindingModel(
        entity_type=entity_type,
        entity_id=str(entity_id),
        area_id=area_id,
        sharing=sharing,
        is_primary=is_primary,
    )
    db.add(row)
    return row


def current_area_entity_ids(db, entity_type: str) -> set[str]:
    area = resolve_area(db=db)
    return set(db.scalars(select(EntityAreaBindingModel.entity_id).where(
        EntityAreaBindingModel.entity_type == entity_type,
        EntityAreaBindingModel.area_id == area.id,
    )).all())


def filter_rows_to_current_area(db, rows: Iterable[Any], entity_type: str) -> list[Any]:
    rows = list(rows)
    if not rows:
        return []
    allowed = current_area_entity_ids(db, entity_type)
    return [row for row in rows if str(getattr(row, "id", "")) in allowed]


def require_entity_in_current_area(db, entity_type: str, entity_id: str, *, allow_shared: bool = True) -> None:
    area = resolve_area(db=db)
    rows = db.scalars(select(EntityAreaBindingModel).where(
        EntityAreaBindingModel.entity_type == entity_type,
        EntityAreaBindingModel.entity_id == str(entity_id),
        EntityAreaBindingModel.area_id == area.id,
    )).all()
    if rows:
        return
    if allow_shared:
        shared = db.scalar(select(EntityAreaBindingModel).where(
            EntityAreaBindingModel.entity_type == entity_type,
            EntityAreaBindingModel.entity_id == str(entity_id),
            EntityAreaBindingModel.sharing == "shared",
        ))
        if shared:
            return
    raise ValueError(f"{entity_type} does not belong to current interest area")


def area_summary(area: InterestAreaModel) -> dict[str, Any]:
    with get_session_factory()() as db:
        pack = db.get(DomainPackModel, area.domain_pack_id)
        settings = db.scalars(select(AreaCapabilitySettingModel).where(
            AreaCapabilitySettingModel.area_id == area.id
        )).all()
        return {
            "id": area.id,
            "slug": area.slug,
            "name": area.name,
            "description": area.description,
            "domain_pack_id": area.domain_pack_id,
            "domain_name": pack.name if pack else area.domain_pack_id,
            "mastery_profile_id": area.mastery_profile_id,
            "icon": area.icon,
            "accent": area.accent,
            "is_default": area.is_default,
            "archived": area.archived,
            "position": area.position,
            "capabilities": {row.plugin_id: bool(row.enabled) for row in settings},
        }


def persona_ids_for_current_area(db) -> set[str]:
    area = resolve_area(db=db)
    domain_ids = set(db.scalars(select(PersonaScopeModel.persona_id).where(
        PersonaScopeModel.scope_type == "domain_pack",
        PersonaScopeModel.scope_id == area.domain_pack_id,
    )).all())
    area_ids = set(db.scalars(select(PersonaScopeModel.persona_id).where(
        PersonaScopeModel.scope_type == "interest_area",
        PersonaScopeModel.scope_id == area.id,
    )).all())
    global_ids = set(db.scalars(select(PersonaScopeModel.persona_id).where(
        PersonaScopeModel.scope_type == "global",
    )).all())
    return domain_ids | area_ids | global_ids


def bind_persona_to_current_area(db, persona_id: str) -> PersonaScopeModel:
    area = resolve_area(db=db)
    row = db.scalar(select(PersonaScopeModel).where(
        PersonaScopeModel.persona_id == persona_id,
        PersonaScopeModel.scope_type == "interest_area",
        PersonaScopeModel.scope_id == area.id,
    ))
    if row is None:
        row = PersonaScopeModel(persona_id=persona_id, scope_type="interest_area", scope_id=area.id)
        db.add(row)
    return row


def current_mastery_profile(db=None) -> MasteryProfileModel:
    owns = db is None
    db = db or get_session_factory()()
    try:
        area = resolve_area(db=db)
        row = db.get(MasteryProfileModel, area.mastery_profile_id) if area.mastery_profile_id else None
        if row is None:
            row = db.scalar(select(MasteryProfileModel).where(
                MasteryProfileModel.domain_pack_id == area.domain_pack_id,
                MasteryProfileModel.is_default.is_(True),
            ))
        if row is None:
            raise RuntimeError("mastery profile missing for interest area")
        return row
    finally:
        if owns:
            db.close()


def current_mastery_states() -> list[str]:
    return list(current_mastery_profile().states or [])


def mastery_profile_summary(profile: MasteryProfileModel) -> dict[str, Any]:
    """Serialize the active profile without making the renderer infer a domain."""
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "states": [{"id": state, "label": state} for state in (profile.states or [])],
    }
