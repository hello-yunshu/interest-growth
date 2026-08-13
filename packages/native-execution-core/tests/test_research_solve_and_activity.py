import json
from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.llm import LLMResponse
from interest_growth_native.research import ResearchSubtopic
from .helpers import StaticResolver,ctx,kb,store

class QueueLLM:
    available=True
    def __init__(self,values):self.values=list(values)
    def complete(self,**kwargs):
        v=self.values.pop(0)
        return LLMResponse(json.dumps(v) if isinstance(v,dict) else str(v))

def test_deep_research_outline_blocks_and_candidate_citations():
    llm=QueueLLM([
        {"refined_topic":"wet paint","clarification_questions":[],"subtopics":[{"title":"method","overview":"how"},{"title":"limits","overview":"when"}]},
        {"summary":"method summary","claims":[{"text":"c1","citation_ids":["C-rag1"]}],"append_topics":[]},
        {"summary":"limits summary","claims":[{"text":"c2","citation_ids":[]}],"append_topics":[]},
        "report",
    ])
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb(text="wet paper method limits")]),store=store(),llm=llm)
    preview=b.research.preview_outline(ctx(),question="paint")
    assert preview.status=="ready_for_review"
    out=b.research.run_confirmed(ctx(),question=preview.refined_topic,subtopics=preview.subtopics,kb_ids=("k",))
    assert len(out.blocks)==2 and out.status=="candidate_not_evidence"
    assert out.citations and all(x.status=="candidate_not_evidence" for x in out.citations)
    assert out.activity.authoritative is False
    first=out.blocks[0]
    # The fixture cites a candidate id that is not among supplied ids, so the block
    # must be marked invalid grounding rather than silently accepted.
    assert first.claims[0].grounding_status=="invalid_grounding"
    assert first.status=="partial"
    assert first.citation_ids==()
    assert out.blocks[1].claims[0].grounding_status=="ungrounded"

def test_deep_solve_plan_step_and_final_check():
    llm=QueueLLM([
        {"steps":[{"title":"A","instruction":"a"},{"title":"B","instruction":"b"}],"assumptions":[]},
        {"result_summary":"ra","status":"completed","blocker":""},
        {"result_summary":"rb","status":"completed","blocker":""},
        "final",
    ])
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=llm)
    out=b.solve.solve(ctx(),problem="x")
    assert out.plan.status=="completed" and out.partial is False
    assert [x.result_summary for x in out.plan.steps]==["ra","rb"]
