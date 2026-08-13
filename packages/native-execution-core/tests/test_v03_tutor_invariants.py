from __future__ import annotations
import threading
import pytest

from interest_growth_native.bundle import NativeEngineBundle,NativeExecutionConfig
from interest_growth_native.capabilities import CAP_KNOWLEDGE
from interest_growth_native.errors import InvalidStateTransition
from interest_growth_native.llm import LLMResponse,LLMStreamEvent
from .helpers import StaticResolver,ctx,kb,store

class NarrationToolThenAnswer:
    available=True
    def __init__(self):self.n=0
    def complete(self,**kwargs):
        self.n+=1
        if self.n==1:
            return LLMResponse("Let me inspect that first.",(
                {"id":"t1","name":"reason","arguments":{"q":"x"}},
            ))
        return LLMResponse("Final answer.")

def test_v03_final_answer_excludes_tool_round_narration():
    b=NativeEngineBundle(
        knowledge_resolver=StaticResolver([kb()]),store=store(),
        llm=NarrationToolThenAnswer(),product_tool_hooks={"reason":lambda c,a:{"ok":True}},
    )
    out=b.tutor.start(ctx(user_message="question"))
    assert out.run.state=="completed"
    assert out.run.assistant_text=="Final answer."
    answer_text="".join(
        e.payload["text"] for e in b.tutor.replay(ctx(),out.run.id)
        if e.type=="answer_delta"
    )
    assert answer_text=="Final answer."
    assert "inspect" not in answer_text

class ToolAskResumeLLM:
    available=True
    def __init__(self):self.n=0;self.resume_messages=None
    def complete(self,**kwargs):
        self.n+=1
        if self.n==1:
            return LLMResponse("checking",(
                {"id":"r1","name":"reason","arguments":{"query":"x"}},
            ))
        if self.n==2:
            return LLMResponse("",(
                {"id":"q1","name":"ask_user","arguments":{"question":"Need input?"}},
            ))
        self.resume_messages=kwargs["messages"]
        return LLMResponse("continued with context")

def test_v03_wait_resume_preserves_pre_wait_tool_result_same_turn():
    llm=ToolAskResumeLLM()
    b=NativeEngineBundle(
        knowledge_resolver=StaticResolver([kb()]),store=store(),llm=llm,
        product_tool_hooks={"reason":lambda c,a:{"marker":"TOOLCTX"}},
    )
    first=b.tutor.start(ctx(user_message="start"))
    assert first.run.state=="waiting_input"
    resumed=b.tutor.resume(ctx(),run_id=first.run.id,user_input="yes")
    assert resumed.run.state=="completed"
    serial=str(llm.resume_messages)
    assert "TOOLCTX" in serial
    assert resumed.run.id==first.run.id

def test_v03_replay_sequence_cursor_is_incremental_and_no_duplicates():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    out=b.tutor.start(ctx(user_message="x"))
    all_events=b.tutor.replay(ctx(),out.run.id)
    seqs=[x.seq for x in all_events]
    assert seqs==sorted(seqs) and len(seqs)==len(set(seqs))
    pivot=seqs[len(seqs)//2]
    tail=b.tutor.replay(ctx(),out.run.id,after_seq=pivot)
    assert tail and all(x.seq>pivot for x in tail)
    assert {x.seq for x in tail}.isdisjoint({x for x in seqs if x<=pivot})

class RagThenAnswer:
    available=True
    def __init__(self):self.n=0
    def complete(self,**kwargs):
        self.n+=1
        if self.n==1:return LLMResponse("",({"id":"rag1","name":"rag","arguments":{"query":"soft edges"}},))
        return LLMResponse("Use wet paper.")

def test_v03_rag_tool_emits_sources_provenance():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb(page=7)]),store=store(),llm=RagThenAnswer())
    c=ctx(user_message="how",selected_capability=CAP_KNOWLEDGE,knowledge_base_ids=("k",))
    out=b.tutor.start(c)
    events=b.tutor.replay(c,out.run.id)
    source_event=next(x for x in events if x.type=="sources")
    src=source_event.payload["sources"][0]
    assert src["source_id"]=="src"
    assert src["location"]["page"]==7
    assert src["status"]=="candidate_not_evidence"
    assert "text" not in src
    assert "excerpt" in src

class ExplicitStreaming:
    available=True
    def stream(self,**kwargs):
        yield LLMStreamEvent("answer_delta",text="A")
        yield LLMStreamEvent("answer_delta",text="B")
        yield LLMStreamEvent("done",finish_reason="stop")
    def complete(self,**kwargs):raise AssertionError("stream path expected")

def test_real_semantic_stream_preserves_multiple_answer_delta_events():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=ExplicitStreaming())
    out=b.tutor.start(ctx(user_message="x"))
    deltas=[x.payload["text"] for x in b.tutor.replay(ctx(),out.run.id) if x.type=="answer_delta"]
    assert deltas==["A","B"]
    assert out.run.assistant_text=="AB"

class Simple:
    available=True
    def complete(self,**kwargs):return LLMResponse("answer")

class Boom:
    available=True
    def complete(self,**kwargs):raise RuntimeError("boom")

def test_exception_terminalizes_as_error_and_sink_failure_is_isolated():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Boom())
    assert b.tutor.start(ctx(user_message="x")).run.state=="error"
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    out=b.tutor.start(ctx(user_message="x"),event_sink=lambda e:(_ for _ in ()).throw(RuntimeError("sink")))
    assert out.run.state=="completed"

def test_cancel_is_terminal_under_late_llm_return():
    entered=threading.Event();release=threading.Event()
    class Blocking:
        available=True
        def complete(self,**kwargs):
            entered.set();release.wait(2);return LLMResponse("late")
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Blocking())
    holder={}
    th=threading.Thread(target=lambda:holder.setdefault("r",b.tutor.start(ctx(user_message="x"))))
    th.start();assert entered.wait(1)
    with b.store.connect() as conn:
        rid=conn.execute("SELECT id FROM native_tutor_checkpoint WHERE state='running'").fetchone()[0]
    b.tutor.cancel(ctx(),rid);release.set();th.join(3)
    assert b.store.load(rid,area_id="a").state=="cancelled"
    assert holder["r"].run.state=="cancelled"
    assert not [e for e in b.tutor.replay(ctx(),rid) if e.type=="answer_delta" and e.payload.get("text")=="late"]

class Asking:
    available=True
    def complete(self,**kwargs):
        return LLMResponse("",({"id":"q","name":"ask_user","arguments":{"question":"q"}},))

def test_one_active_turn_and_stale_running_recovery():
    s=store()
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=s,llm=Asking())
    first=b.tutor.start(ctx(user_message="x"));assert first.run.state=="waiting_input"
    with pytest.raises(InvalidStateTransition):b.tutor.start(ctx(user_message="y"))
    s2=store();orphan=s2.create_run(area_id="a",session_id="orphan",user_message="x")
    NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=s2,llm=Simple(),config=NativeExecutionConfig(recover_stale_running_on_startup=True))
    assert s2.load(orphan.id,area_id="a").state=="error"

def test_waiting_turn_cannot_resume_if_selected_capability_was_disabled():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Asking())
    c=ctx(user_message="x",selected_capability="capability.mastery")
    first=b.tutor.start(c)
    disabled=ctx(caps={x for x in c.area_capabilities if x!="capability.mastery"},
                 global_caps=c.global_capabilities)
    from interest_growth_native.errors import CapabilityUnavailable
    with pytest.raises(CapabilityUnavailable):
        b.tutor.resume(disabled,run_id=first.run.id,user_input="x")
