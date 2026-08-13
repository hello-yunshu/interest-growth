from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.llm import LLMStreamEvent,LLMResponse
from .helpers import StaticResolver,ctx,kb,store

class LengthStream:
    available=True
    def __init__(self):self.n=0
    def stream(self,**kwargs):
        self.n+=1
        if self.n==1:
            yield LLMStreamEvent("answer_delta",text="Part1")
            yield LLMStreamEvent("done",finish_reason="length",usage={"prompt_tokens":2,"completion_tokens":1,"total_tokens":3})
        else:
            assert "Continue exactly" in str(kwargs["messages"])
            yield LLMStreamEvent("answer_delta",text="Part2")
            yield LLMStreamEvent("done",finish_reason="stop",usage={"prompt_tokens":3,"completion_tokens":1,"total_tokens":4})
    def complete(self,**kwargs):raise AssertionError

class Sink:
    def __init__(self):self.events=[]
    def record(self,e):self.events.append(e)

def test_stream_length_continuation_preserves_answer_and_is_bounded():
    llm=LengthStream();sink=Sink()
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=llm,usage_sink=sink)
    out=b.tutor.start(ctx(user_message="x").child(config_overrides={"max_stream_continuations":2}))
    assert out.run.assistant_text=="Part1Part2"
    assert llm.n==2
    assert len(sink.events)==2
    assert sink.events[0].total_tokens==3 and sink.events[1].total_tokens==4

class CompleteUsage:
    available=True
    def complete(self,**kwargs):
        return LLMResponse("ok",usage={"prompt_tokens":5,"completion_tokens":2,"total_tokens":7})

def test_complete_usage_sink_receives_tokens():
    sink=Sink()
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=CompleteUsage(),usage_sink=sink)
    b.research.preview_outline(ctx(),question="x")
    assert sink.events and sink.events[0].input_tokens==5 and sink.events[0].total_tokens==7
