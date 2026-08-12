from fastapi import FastAPI,Request
from fastapi.testclient import TestClient

from interest_growth_native.api import create_native_router
from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.capabilities import CAP_KNOWLEDGE
from interest_growth_native.llm import LLMResponse
from .helpers import StaticResolver,ctx,kb,store

class Simple:
    available=True
    def complete(self,**kwargs):return LLMResponse("answer")

def resolver(request:Request,operation:str):return ctx()

def test_api_exposes_after_seq_reconnect_and_no_canonical_kb_crud():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    app=FastAPI();app.include_router(create_native_router(b,context_resolver=resolver));c=TestClient(app)
    assert c.get("/api/native-execution/health").status_code==200
    assert c.post("/api/native-execution/knowledge-bases",json={"name":"x"}).status_code==404
    start=c.post("/api/native-execution/tutor",json={"user_message":"x"})
    assert start.status_code==200
    run_id=start.json()["run"]["id"]
    events=c.get(f"/api/native-execution/tutor/{run_id}/events").json()
    pivot=events[0]["seq"]
    tail=c.get(f"/api/native-execution/tutor/{run_id}/events",params={"after_seq":pivot}).json()
    assert tail and all(x["seq"]>pivot for x in tail)

def test_api_mastery_profile_cannot_be_client_overridden():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    app=FastAPI();app.include_router(create_native_router(b,context_resolver=resolver));c=TestClient(app)
    r=c.post("/api/native-execution/learning/mastery-path",json={"goal":"x","current_stage":"practice","mastery_profile":["evil"]})
    assert r.status_code==200
    assert r.json()["stages"][0]["id"]=="unfamiliar"

def test_api_returns_503_when_ai_provider_unavailable():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store())
    app=FastAPI();app.include_router(create_native_router(b,context_resolver=resolver));c=TestClient(app)
    assert c.post("/api/native-execution/research",json={"question":"x","kb_ids":[]}).status_code==503
