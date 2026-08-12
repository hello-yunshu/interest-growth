from pathlib import Path
import re,pytest

from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.capabilities import *
from interest_growth_native.context import NativeRunContext,PermissionScope
from interest_growth_native.contracts import DomainPolicy
from interest_growth_native.errors import CapabilityUnavailable,ProviderUnavailable,ValidationError
from interest_growth_native.llm import LLMResponse
from interest_growth_native.tools import ToolSpec
from .helpers import StaticResolver,ctx,kb,store

class Simple:
    available=True
    def complete(self,**kwargs):return LLMResponse("answer")

def test_runtime_has_no_deeptutor_import_or_domain_specific_policy():
    root=Path(__file__).resolve().parents[1]/"interest_growth_native";hits=[]
    for p in root.rglob("*.py"):
        t=p.read_text("utf-8")
        if re.search(r"^\s*(from|import)\s+deeptutor\b",t,re.M):hits.append(str(p))
        if re.search(r"\bPsychology\b|心理学",t,re.I):hits.append(str(p)+":domain")
    assert hits==[]

def test_global_lifecycle_is_fail_closed_not_star_default():
    with pytest.raises(TypeError):
        NativeRunContext(
            area_id="a",session_id="s",domain_policy=DomainPolicy("general"),
            area_capabilities=frozenset({CAP_TUTOR}),
        )
    c=NativeRunContext(
        area_id="a",session_id="s",domain_policy=DomainPolicy("general"),
        area_capabilities=frozenset({CAP_TUTOR}),global_capabilities=frozenset(),
    )
    with pytest.raises(ValidationError):c.validate()

def test_disabled_capability_cannot_execute_direct_executor():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    c=ctx(caps=set(),global_caps=ctx().global_capabilities)
    with pytest.raises(CapabilityUnavailable):b.research.research(c,question="x")

def test_available_capability_is_not_automatically_selected():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    c=ctx(selected_capability=None)
    assert b.capabilities.selected(c) is None
    assert set(b.tutor._granted_tools(c))!={"ask_user","rag"}

def test_model_cannot_call_registered_but_unoffered_tool():
    executed=[]
    class Hallucinating:
        available=True
        def complete(self,**kwargs):return LLMResponse("",({"id":"x","name":"secret","arguments":{}},))
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Hallucinating())
    b.tools.register(ToolSpec("secret","not offered",{"type":"object"},lambda c,a:executed.append(1)))
    out=b.tutor.start(ctx(user_message="x"))
    assert out.run.state=="error" and executed==[]

def test_no_llm_is_explicit_degraded_not_fake_success():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store())
    h=b.health()
    assert h["llm_available"] is False and "research" in h["degraded_capabilities"]
    with pytest.raises(ProviderUnavailable):b.research.research(ctx(),question="x")

def test_domain_mastery_profile_is_authoritative():
    c=ctx(domain=DomainPolicy("special",mastery_profile=("concept","evidence","transfer")))
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store())
    out=b.learning.mastery_path(c,goal="x",current_stage="evidence")
    assert [x["id"] for x in out.stages]==["concept","evidence","transfer"]
    assert out.suggested_next=="transfer"

def test_execution_schema_contains_only_execution_auxiliary_tables():
    sql=(Path(__file__).resolve().parents[1]/"migrations/0011_native_execution_state.sql").read_text("utf-8").lower()
    for banned in ("native_kb","native_skill","native_persona","native_book","native_mastery","native_writing","native_evidence"):
        assert banned not in sql
    assert "native_tutor_checkpoint" in sql and "native_run_event" in sql and "native_aux_memory" in sql
