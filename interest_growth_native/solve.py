from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any
from .capabilities import CAP_DEEP_SOLVE
from .context import NativeRunContext
from .errors import ProviderUnavailable,ValidationError
from .llm import LLMClient
from .signals import LearningActivityCandidate

@dataclass(frozen=True,slots=True)
class SolveStep:
    id:str;title:str;instruction:str;status:str="planned";result_summary:str=""
@dataclass(frozen=True,slots=True)
class SolvePlan:
    problem:str;steps:tuple[SolveStep,...];assumptions:tuple[str,...]=();status:str="planned";validation_errors:tuple[str,...]=()
@dataclass(frozen=True,slots=True)
class SolveResult:
    problem:str;plan:SolvePlan;reasoning_summary:str;answer:str;checks:tuple[str,...];replans_used:int;partial:bool;activity:LearningActivityCandidate

class NativeSolveExecutor:
    def __init__(self,llm:LLMClient,*,max_replans=1):self.llm=llm;self.max_replans=max(0,min(int(max_replans),3))
    def _require(self,c):
        c.require_capability(CAP_DEEP_SOLVE);c.permission_scope.require_risk("llm")
        if not getattr(self.llm,"available",False):raise ProviderUnavailable("deep solve requires configured LLM")
    @staticmethod
    def _parse(t):
        try:v=json.loads(t)
        except Exception:return None
        return v if isinstance(v,dict) else None
    def _structured(self,messages,schema):
        r=self.llm.complete(messages=messages,temperature=.1);p=self._parse(r.text)
        if p is not None:return p
        r=self.llm.complete(messages=[{"role":"system","content":f"Repair as JSON only: {schema}"},{"role":"user","content":r.text}],temperature=0);return self._parse(r.text)
    def plan(self,c,*,problem,max_steps=6):
        self._require(c);p=self._structured([{"role":"system","content":"Create checkable solve plan JSON: steps title/instruction and assumptions. No private chain-of-thought."},{"role":"user","content":problem}],'{"steps":[{"title":"...","instruction":"..."}],"assumptions":[]}')
        if not p:return SolvePlan(problem,(),status="needs_human_edit",validation_errors=("plan_invalid",))
        steps=[]
        for i,x in enumerate((p.get("steps") or [])[:max_steps]):
            if isinstance(x,dict) and x.get("title") and x.get("instruction"):steps.append(SolveStep(f"S{i+1}",str(x["title"]),str(x["instruction"])))
        assumptions=tuple(str(x) for x in (p.get("assumptions") or [])[:6])
        return SolvePlan(problem,tuple(steps),assumptions,"ready" if len(steps)>=2 else "needs_human_edit",(() if len(steps)>=2 else ("plan_requires_two_steps",)))
    def solve(self,c,*,problem,plan=None,max_replans=None):
        self._require(c);active=plan or self.plan(c,problem=problem)
        if active.status!="ready":raise ValidationError("solve plan requires review")
        budget=self.max_replans if max_replans is None else max(0,min(int(max_replans),3));queue=list(active.steps);done=[];replans=0;partial=False
        while queue:
            s=queue.pop(0);p=self._structured([{"role":"system","content":'Execute exactly one plan step. JSON {"result_summary":"public/checkable","status":"completed|blocked","blocker":""}. No hidden reasoning.'},{"role":"user","content":f"Problem:{problem}\nStep:{s.title}\nInstruction:{s.instruction}\nCompleted:{[(x.title,x.result_summary) for x in done]}"}],'{"result_summary":"...","status":"completed|blocked","blocker":""}')
            status=str((p or {}).get("status") or "blocked");summary=str((p or {}).get("result_summary") or "");blocker=str((p or {}).get("blocker") or "")
            executed=SolveStep(s.id,s.title,s.instruction,status,summary)
            if status=="completed" and summary:done.append(executed);continue
            if replans>=budget:done.append(SolveStep(s.id,s.title,s.instruction,"blocked",summary));partial=True;break
            replans+=1;rp=self._structured([{"role":"system","content":'Replan remaining work only. JSON {"revised_steps":[{"title":"...","instruction":"..."}]}'},{"role":"user","content":f"Problem:{problem}\nCompleted:{[(x.title,x.result_summary) for x in done]}\nBlocker:{blocker}\nRemaining:{[(x.title,x.instruction) for x in queue]}"}],'{"revised_steps":[]}')
            revised=[]
            for i,x in enumerate((rp or {}).get("revised_steps") or []):
                if isinstance(x,dict) and x.get("title") and x.get("instruction"):revised.append(SolveStep(f"R{i+1}",str(x["title"]),str(x["instruction"])))
            if not revised:partial=True;done.append(SolveStep(s.id,s.title,s.instruction,"blocked",summary));break
            queue=revised
        final=self.llm.complete(messages=[{"role":"system","content":"Produce final answer using only public step summaries and state uncertainty if partial."},{"role":"user","content":f"Problem:{problem}\nSteps:{[(x.title,x.status,x.result_summary) for x in done]}"}],temperature=.1).text
        act=LearningActivityCandidate(c.area_id,c.session_id,CAP_DEEP_SOLVE,"deep_solve","Completed bounded solve plan",metadata={"steps":len(done),"replans":replans,"partial":partial})
        return SolveResult(problem,SolvePlan(problem,tuple(done),active.assumptions,"partial" if partial else "completed"),"; ".join(f"{x.title}: {x.result_summary}" for x in done if x.result_summary),final,("all conditions considered","units/boundaries checked","conclusion supported by public step summaries","uncertainty explicit"),replans,partial,act)
