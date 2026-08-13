from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.web_tools import SearchHit
from interest_growth_native.llm import LLMResponse
from .helpers import StaticResolver,ctx,kb,store

class ResearchLLM:
    available=True
    def __init__(self):self.n=0
    def complete(self,**kwargs):
        self.n+=1
        if self.n==1:return LLMResponse('{"summary":"block","append_topics":[]}')
        return LLMResponse("report")

class FakePaper:
    def search(self,query,*,limit=8):
        return [SearchHit("Paper","https://example.com/p","candidate snippet","fake")]

def test_research_network_candidate_is_explicit_opt_in_and_stays_candidate():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([]),store=store(),llm=ResearchLLM())
    b.paper_search=FakePaper()
    # No enabled_tools -> network candidate is not used.
    out=b.research.run_confirmed(
        ctx(),question="q",subtopics=(__import__("interest_growth_native.research",fromlist=["ResearchSubtopic"]).ResearchSubtopic("t"),),
        kb_ids=(),
    )
    assert not out.citations

    llm=ResearchLLM()
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([]),store=store(),llm=llm)
    b.paper_search=FakePaper()
    c=ctx().child(enabled_tools=frozenset({"paper_search"}))
    out=b.research.run_confirmed(
        c,question="q",subtopics=(__import__("interest_growth_native.research",fromlist=["ResearchSubtopic"]).ResearchSubtopic("t"),),
        kb_ids=(),
    )
    assert out.citations and out.citations[0].source_type=="paper_search"
    assert out.citations[0].status=="candidate_not_evidence"
