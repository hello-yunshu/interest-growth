from pathlib import Path
import pytest

from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.contracts import SkillRuntimeEnvironment,PersonaSnapshot
from interest_growth_native.personas import compile_persona_context
from interest_growth_native.skills import load_skill_directory,skill_availability,compile_skill_manifest
from .helpers import StaticResolver,ctx,kb,store

def test_skill_requires_fail_closed_and_always_body_only_injects_when_available(tmp_path):
    root=tmp_path/"s";root.mkdir()
    (root/"SKILL.md").write_text(
        "---\nname: guarded\ndescription: Guarded\nalways: true\nrequires:\n  bins: [definitely-missing-bin-xyz]\n  env: [MISSING_ENV_XYZ]\n  sandbox: shell\n---\n# Guarded\nRule body",
        "utf-8",
    )
    skill=load_skill_directory(root)
    env=SkillRuntimeEnvironment()
    status=skill_availability(skill,env)
    assert status.available is False
    manifest,always,fp=compile_skill_manifest([skill],env)
    assert "unavailable:" in manifest
    assert "Rule body" not in always
    assert fp

def test_persona_domain_scope_is_checked_and_fingerprinted():
    p=PersonaSnapshot("p","P","Instructions","special")
    with pytest.raises(ValueError):compile_persona_context(p,domain_pack_id="general")
    text,fp=compile_persona_context(p,domain_pack_id="special")
    assert text=="Instructions" and fp

def test_agent_memory_is_auxiliary_and_area_session_scoped():
    s=store();b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=s)
    c=ctx()
    r=b.memory.write(c,layer="working",kind="summary",content="x",source_run_id="r1")
    assert b.memory.read(c)[0].content=="x"
    graph=b.memory.audit_graph(c)
    assert graph["authoritative_growth_memory"] is False
    assert any(n["id"]==f"memory:{r.id}" for n in graph["nodes"])
    assert b.memory.read(ctx(area="b"))==()

def test_visualize_is_generic_versioned_reviewable_artifact():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store())
    art=b.visualize.plan(ctx(),title="Map",content="A -> B")
    assert art.spec["schema_version"]=="interest-growth.visual.v1"
    assert art.review_required is True
