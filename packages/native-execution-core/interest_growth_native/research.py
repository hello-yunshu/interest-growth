from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any, Iterable

from .capabilities import CAP_KNOWLEDGE,CAP_RESEARCH
from .context import NativeRunContext
from .errors import ProviderUnavailable
from .knowledge import NativeRetrievalEngine
from .llm import LLMClient
from .signals import LearningActivityCandidate
from .tools import ToolRegistry

@dataclass(frozen=True,slots=True)
class ResearchSubtopic:
    title:str;overview:str=""

@dataclass(frozen=True,slots=True)
class ResearchOutlinePreview:
    refined_topic:str
    subtopics:tuple[ResearchSubtopic,...]
    clarification_questions:tuple[str,...]
    status:str
    validation_errors:tuple[str,...]
    activity:LearningActivityCandidate

@dataclass(frozen=True,slots=True)
class ResearchCitation:
    id:str;source_type:str;source_ref:str;title:str="";url:str="";excerpt:str="";status:str="candidate_not_evidence"

@dataclass(frozen=True,slots=True)
class ResearchBlockResult:
    id:str;title:str;overview:str;summary:str;citation_ids:tuple[str,...]
    appended_topics:tuple[ResearchSubtopic,...]=()
    status:str="completed";error_type:str=""

@dataclass(frozen=True,slots=True)
class ResearchResult:
    question:str;answer:str;subquestions:tuple[str,...]
    candidates:tuple[dict[str,Any],...]
    limitations:tuple[str,...]
    activity:LearningActivityCandidate
    blocks:tuple[ResearchBlockResult,...]=()
    citations:tuple[ResearchCitation,...]=()
    partial:bool=False
    failed_blocks:tuple[str,...]=()
    outline_status:str="confirmed"
    status:str="candidate_not_evidence"

class NativeResearchExecutor:
    def __init__(self,llm:LLMClient,retrieval:NativeRetrievalEngine,*,tools:ToolRegistry|None=None):
        self.llm=llm;self.retrieval=retrieval;self.tools=tools
    def _require(self,c):
        c.require_capability(CAP_RESEARCH);c.permission_scope.require_risk("llm")
        if not getattr(self.llm,"available",False):raise ProviderUnavailable("research requires configured LLM")
    @staticmethod
    def _parse(text):
        try:v=json.loads(text)
        except Exception:return None
        return v if isinstance(v,dict) else None
    def _structured(self,c,*,messages,schema_hint,temperature=.15):
        self._require(c);r=self.llm.complete(messages=messages,temperature=temperature);p=self._parse(r.text)
        if p is not None:return p,()
        repair=self.llm.complete(messages=[{"role":"system","content":f"Repair into JSON only with shape {schema_hint}."},{"role":"user","content":r.text}],temperature=0)
        p=self._parse(repair.text);return p,(() if p is not None else ("structured_output_invalid",))
    def preview_outline(self,c,*,question,clarification_answers=(),max_subtopics=5):
        max_subtopics=max(2,min(int(max_subtopics),8))
        sys=f"Plan a research task. Return JSON refined_topic, clarification_questions (0-4), subtopics (2-{max_subtopics}, each title/overview). Candidates are not verified Evidence."
        if c.domain_policy.research_instructions:sys+="\nDomain policy:\n"+c.domain_policy.research_instructions
        user=f"Question: {question}"
        if clarification_answers:user+="\nClarifications:\n- "+"\n- ".join(str(x) for x in clarification_answers)
        p,errors=self._structured(c,messages=[{"role":"system","content":sys},{"role":"user","content":user}],schema_hint='{"refined_topic":"...","clarification_questions":[],"subtopics":[{"title":"...","overview":"..."}]}')
        validation=list(errors);refined=question.strip();qs=();topics=[]
        if p:
            refined=str(p.get("refined_topic") or refined).strip()
            if isinstance(p.get("clarification_questions"),list):qs=tuple(str(x).strip() for x in p["clarification_questions"][:4] if str(x).strip())
            if isinstance(p.get("subtopics"),list):
                for x in p["subtopics"][:max_subtopics]:
                    if isinstance(x,dict) and str(x.get("title") or "").strip():topics.append(ResearchSubtopic(str(x["title"]).strip(),str(x.get("overview") or "").strip()))
        if len(topics)<2:
            validation.append("outline_requires_two_subtopics");topics=[ResearchSubtopic(refined,"Core definitions and direct evidence"),ResearchSubtopic(f"Limits and alternatives for {refined}","Counter-evidence and boundary conditions")]
        status="ready_for_review" if not validation else "needs_human_edit"
        act=LearningActivityCandidate(c.area_id,c.session_id,CAP_RESEARCH,"research_outline_preview",f"Prepared research outline: {refined}",metadata={"status":status})
        return ResearchOutlinePreview(refined,tuple(topics),qs,status,tuple(dict.fromkeys(validation)),act)
    def _collect_candidates(self,c,kb_ids,query,top_k=6):
        raw=[];cit=[]
        if kb_ids:
            c.require_capability(CAP_KNOWLEDGE)
            for x in self.retrieval.retrieve(c,kb_ids=kb_ids,query=query,top_k=top_k):
                cid="C-"+hashlib.sha256(f"rag|{x.source_id}|{x.chunk_id}|{x.source_fingerprint}".encode()).hexdigest()[:12]
                raw.append({"citation_id":cid,"kind":"rag",**x.public_source()})
                cit.append(ResearchCitation(cid,"local_source",x.source_id,x.filename,"",x.text[:1400]))
        if self.tools is not None:
            names={x.name for x in self.tools.list()}
            for tool_name in ("paper_search","web_search"):
                if tool_name not in names:
                    continue
                spec=self.tools.get(tool_name)
                if not spec.eligible(c):
                    continue
                try:
                    value=self.tools.execute_granted(
                        c,granted_names={tool_name},name=tool_name,
                        args={"query":query,"limit":top_k},
                    )
                except Exception as exc:
                    raw.append({"kind":"tool_failure","tool":tool_name,"error_type":type(exc).__name__,"status":"unavailable"})
                    continue
                if not isinstance(value,list):
                    continue
                for hit in value[:top_k]:
                    if not isinstance(hit,dict):continue
                    url=str(hit.get("url") or "").strip()
                    title=str(hit.get("title") or "").strip()
                    snippet=str(hit.get("snippet") or hit.get("text") or "")[:1400]
                    ref=url or title
                    if not ref:continue
                    cid="C-"+hashlib.sha256(f"{tool_name}|{ref}|{snippet[:300]}".encode()).hexdigest()[:12]
                    raw.append({"citation_id":cid,"kind":tool_name,"title":title,"url":url,"excerpt":snippet,"status":"candidate_not_evidence"})
                    cit.append(ResearchCitation(cid,tool_name,ref,title,url,snippet))
        return raw,cit
    def _run_block(self,c,*,bid,topic,root,kb_ids):
        raw,cits=self._collect_candidates(c,kb_ids,topic.title)
        context="\n\n".join(f"[{x['citation_id']}]\n{x.get('excerpt','')}" for x in raw)
        p,errors=self._structured(c,messages=[{"role":"system","content":"Research one confirmed block. Return JSON summary and append_topics (0-2). Use supplied citation IDs only; never call candidates verified Evidence."},{"role":"user","content":f"Root: {root}\nBlock: {topic.title}\nOverview: {topic.overview}\nCandidates:\n{context or '(none)'}"}],schema_hint='{"summary":"...","append_topics":[{"title":"...","overview":"..."}]}',temperature=.25)
        if p is None:return ResearchBlockResult(bid,topic.title,topic.overview,"",tuple(x.id for x in cits),(), "partial","structured_output_invalid"),tuple(cits),tuple(raw)
        summary=str(p.get("summary") or "").strip();app=[]
        if isinstance(p.get("append_topics"),list):
            for x in p["append_topics"][:2]:
                if isinstance(x,dict) and str(x.get("title") or "").strip():app.append(ResearchSubtopic(str(x["title"]).strip(),str(x.get("overview") or "").strip()))
        status="completed" if summary and not errors else "partial"
        return ResearchBlockResult(bid,topic.title,topic.overview,summary,tuple(x.id for x in cits),tuple(app),status,("" if status=="completed" else (errors[0] if errors else "missing_summary"))),tuple(cits),tuple(raw)
    def run_confirmed(self,c,*,question,subtopics,kb_ids=(),max_queue=8,outline_status="host_confirmed"):
        self._require(c);queue=list(subtopics);seen={x.title.strip().lower() for x in queue};blocks=[];citations={};candidates=[];failed=[];counter=0
        while queue and counter<max_queue:
            topic=queue.pop(0);counter+=1
            block,cits,raw=self._run_block(c,bid=f"B{counter}",topic=topic,root=question,kb_ids=tuple(kb_ids));blocks.append(block);candidates.extend(raw)
            for x in cits:citations[x.id]=x
            if block.status!="completed":failed.append(block.id)
            for new in block.appended_topics:
                key=new.title.strip().lower()
                if key and key not in seen and len(queue)+counter<max_queue:seen.add(key);queue.append(new)
        section_text="\n\n".join(f"## {b.title}\n{b.summary}" for b in blocks)
        report=self.llm.complete(messages=[{"role":"system","content":"Write a concise research report with introduction, sections and conclusion from confirmed block summaries. Preserve uncertainty; candidate citations are not verified Evidence."},{"role":"user","content":f"Question: {question}\nBlocks:\n{section_text}"}],temperature=.2).text
        partial=bool(failed or queue)
        act=LearningActivityCandidate(c.area_id,c.session_id,CAP_RESEARCH,"deep_research",f"Completed research execution for {question}",metadata={"blocks":len(blocks),"partial":partial})
        return ResearchResult(question,report,tuple(x.title for x in subtopics),tuple(candidates),tuple(c.domain_policy.research_limitations),act,tuple(blocks),tuple(citations.values()),partial,tuple(failed),outline_status)
    def research(self,c,*,question,kb_ids=(),depth="normal"):
        preview=self.preview_outline(c,question=question,max_subtopics=5 if depth=="deep" else 3)
        return self.run_confirmed(c,question=preview.refined_topic,subtopics=preview.subtopics,kb_ids=tuple(kb_ids),max_queue=8 if depth=="deep" else 4,outline_status="auto_confirmed_compat")
