from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.llm import LLMResponse
from .helpers import StaticResolver,ctx,kb,store

class Ask:
    available=True
    def complete(self,**kwargs):
        return LLMResponse("",({
            "id":"q1","name":"ask_user",
            "arguments":{"question":"model q","questions":[{"id":"fake","text":"fake"}]},
        },))

def test_server_owned_pending_question_overrides_model_ids_and_options():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Ask())
    c=ctx(user_message="quiz").child(server_tool_bindings={
        "ask_user":{
            "question":"canonical",
            "questions":[{"id":"host-q1","text":"canonical","options":["A","B"]}],
        }
    })
    out=b.tutor.start(c)
    ev=next(x for x in b.tutor.replay(c,out.run.id) if x.type=="wait_for_input")
    assert ev.payload["question"]=="canonical"
    assert ev.payload["questions"][0]["id"]=="host-q1"
    assert "fake" not in str(ev.payload)

class ToolThenFinish:
    available=True
    def __init__(self):self.n=0
    def complete(self,**kwargs):
        self.n+=1
        if self.n==1:return LLMResponse("",({"id":"r","name":"reason","arguments":{}},))
        return LLMResponse("done")

def test_public_activity_never_contains_raw_tool_result_body():
    marker="SENSITIVE_RAW_TOOL_RESULT"
    b=NativeEngineBundle(
        knowledge_resolver=StaticResolver([kb()]),store=store(),llm=ToolThenFinish(),
        product_tool_hooks={"reason":lambda c,a:{"raw":marker}},
    )
    out=b.tutor.start(ctx(user_message="x"))
    public=[x.as_dict() for x in b.tutor.replay(ctx(),out.run.id)]
    assert marker not in str(public)
    activity=[x for x in public if x["type"]=="activity" and x["payload"].get("kind")=="tool_result"]
    assert activity and activity[0]["payload"]["result_type"]=="dict"
