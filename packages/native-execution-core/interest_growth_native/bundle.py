from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

from .book import NativeBookExecutor
from .capabilities import *
from .cowriter import NativeCoWriterExecutor
from .execution_store import SQLiteExecutionStore
from .knowledge import NativeRetrievalEngine
from .rag import RagEngineRegistry
from .learning import NativeGuidedLearningExecutor
from .llm import LLMClient,UnavailableLLM
from .math_animator import NativeMathAnimator
from .memory import AgentMemoryExecutor
from .notebook import NativeNotebookExecutor,NativeQuestionNotebookExecutor
from .research import NativeResearchExecutor
from .solve import NativeSolveExecutor
from .tools import ToolRegistry,ToolSpec
from .tutor import NativeTutorExecutor
from .usage import ObservedLLMClient,UsageSink
from .visualize import NativeVisualizationExecutor
from .web_tools import SafeWebFetcher,CrossrefPaperSearch
from .contracts import KnowledgeResolver

@dataclass(frozen=True,slots=True)
class NativeExecutionConfig:
    max_tool_rounds:int=8
    recover_stale_running_on_startup:bool=True

class NativeEngineBundle:
    """Execution composition only. It owns no canonical product entities."""
    provider_id="native.interest-growth"

    def __init__(
        self,
        *,
        knowledge_resolver:KnowledgeResolver,
        store:SQLiteExecutionStore,
        llm:LLMClient|None=None,
        config:NativeExecutionConfig|None=None,
        product_tool_hooks:dict[str,Callable]|None=None,
        usage_sink:UsageSink|None=None,
        rag_registry:RagEngineRegistry|None=None,
    ):
        self.config=config or NativeExecutionConfig()
        base_llm=llm or UnavailableLLM()
        self.llm=base_llm;self.store=store
        if self.config.recover_stale_running_on_startup:self.store.recover_stale_running()
        self.retrieval=NativeRetrievalEngine(knowledge_resolver,rag_registry)
        self.memory=AgentMemoryExecutor(store)
        self.web_fetcher=SafeWebFetcher();self.paper_search=CrossrefPaperSearch()
        self.capabilities=CapabilityRegistry();self.tools=ToolRegistry()
        self._register_capabilities();self._register_tools(product_tool_hooks or {})
        observed=lambda cap:ObservedLLMClient(base_llm,capability_id=cap,sink=usage_sink)
        self.research=NativeResearchExecutor(observed(CAP_RESEARCH),self.retrieval,tools=self.tools)
        self.learning=NativeGuidedLearningExecutor(observed(CAP_MASTERY))
        self.notebook=NativeNotebookExecutor()
        self.question_notebook=NativeQuestionNotebookExecutor(observed(CAP_PRACTICE))
        self.cowriter=NativeCoWriterExecutor(observed(CAP_COWRITER))
        self.book=NativeBookExecutor(observed(CAP_BOOK))
        self.visualize=NativeVisualizationExecutor()
        self.solve=NativeSolveExecutor(observed(CAP_DEEP_SOLVE))
        self.math_animator=NativeMathAnimator()
        self.tutor=NativeTutorExecutor(
            store=store,llm=observed(CAP_TUTOR),capabilities=self.capabilities,
            tools=self.tools,max_tool_rounds=self.config.max_tool_rounds,
        )

    def _register_capabilities(self):
        self.capabilities.register(CapabilitySpec(
            CAP_MASTERY,("reason","brainstorm"),False,
            lambda c:PromptBlock("Mastery","Use questions to expose understanding boundaries; never auto-update host Mastery.")
        ))
        self.capabilities.register(CapabilitySpec(
            CAP_DEEP_SOLVE,("reason","brainstorm"),False,
            lambda c:PromptBlock("Deep Solve","Use a committed plan, checkable step results and bounded replanning.")
        ))
        self.capabilities.register(CapabilitySpec(
            CAP_KNOWLEDGE,("rag",),True,
            lambda c:PromptBlock("Knowledge","Use current-Area host-owned sources. Retrieval remains candidate_not_evidence.")
        ))
        self.capabilities.register(CapabilitySpec(
            CAP_RESEARCH,("rag","paper_search","web_fetch","reason","brainstorm"),False,
            lambda c:PromptBlock("Research",c.domain_policy.research_instructions or "Separate fact, inference, practice and unknowns.")
        ))

    def _register_tools(self,hooks):
        self.tools.register(ToolSpec(
            "ask_user","Pause and ask for missing information.",
            {"type":"object","properties":{
                "question":{"type":"string"},
                "choices":{"type":"array","items":{"type":"string"}},
                "questions":{"type":"array","items":{"type":"object"}},
            },"required":["question"]},
            lambda c,a:a,
        ))
        def rag_handler(c,a):
            return [
                {**x.public_source(),"text":x.text}
                for x in self.retrieval.retrieve(
                    c,kb_ids=c.knowledge_base_ids,query=str(a["query"]),
                    top_k=int(a.get("top_k",6))
                )
            ]
        self.tools.register(ToolSpec(
            "rag","Retrieve candidate context from host-owned current-Area KB snapshots.",
            {"type":"object","properties":{
                "query":{"type":"string"},
                "top_k":{"type":"integer","minimum":1,"maximum":20}
            },"required":["query"]},
            rag_handler,required_capability=CAP_KNOWLEDGE,read_resource="knowledge",
            source_projector=lambda result:[
                {k:v for k,v in item.items() if k!="text"}
                | {"excerpt":str(item.get("text",""))[:1200]}
                for item in result if isinstance(item,dict)
            ],
        ))
        self.tools.register(ToolSpec(
            "read_memory","Read auxiliary execution memory.",
            {"type":"object","properties":{}},
            lambda c,a:[{"layer":x.layer,"kind":x.kind,"content":x.content} for x in self.memory.read(c)],
            read_resource="agent_memory",
        ))
        self.tools.register(ToolSpec(
            "web_fetch","Fetch one explicitly reviewed public HTTPS URL; redirects are not followed.",
            {"type":"object","properties":{"url":{"type":"string"}},"required":["url"]},
            lambda c,a:self.web_fetcher.fetch(str(a["url"])),
            required_capability=CAP_RESEARCH,risk="network",
        ))
        self.tools.register(ToolSpec(
            "paper_search","Search Crossref for candidate scholarly sources.",
            {"type":"object","properties":{
                "query":{"type":"string"},
                "limit":{"type":"integer","minimum":1,"maximum":20}
            },"required":["query"]},
            lambda c,a:[
                {"title":x.title,"url":x.url,"snippet":x.snippet,"provider":x.provider,"status":x.status}
                for x in self.paper_search.search(str(a["query"]),limit=int(a.get("limit",8)))
            ],
            required_capability=CAP_RESEARCH,risk="network",
        ))
        hook_policy={
            "read_skill":{"read_resource":"skills"},
            "read_source":{"read_resource":"sources"},
            "web_search":{"required_capability":CAP_RESEARCH,"risk":"network"},
            "reason":{"risk":"llm"},
            "brainstorm":{"risk":"llm"},
        }
        for name in ("read_skill","read_source","web_search","reason","brainstorm"):
            if name in hooks:
                policy=hook_policy[name]
                self.tools.register(ToolSpec(
                    name,f"Trusted host product hook: {name}.",
                    {"type":"object","additionalProperties":True},hooks[name],
                    required_capability=policy.get("required_capability",""),
                    read_resource=policy.get("read_resource",""),
                    risk=policy.get("risk",""),
                ))

    def health(self):
        ai_available=bool(getattr(self.llm,"available",False))
        return {
            "provider":self.provider_id,
            "version":"0.6.0rc2",
            "owns_canonical_product_data":False,
            "llm_available":ai_available,
            "degraded_capabilities":[] if ai_available else [
                "tutor","research","deep_question","question_notebook",
                "cowriter","deep_solve","book_expand",
            ],
            "local_capabilities":[
                "retrieval","mastery_path","notebook_proposal","book_scaffold",
                "visualize_plan","math_animator_plan","aux_memory",
            ],
        }

InterestGrowthNativeProvider=NativeEngineBundle
