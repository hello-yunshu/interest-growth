from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .capabilities import CAP_MASTERY
from .context import NativeRunContext
from .errors import ProviderUnavailable, ValidationError
from .llm import LLMClient
from .signals import LearningActivityCandidate

@dataclass(frozen=True,slots=True)
class MasteryPath:
    goal:str
    current_stage:str
    stages:tuple[dict[str,Any],...]
    suggested_next:str
    activity:LearningActivityCandidate
    authoritative:bool=False

@dataclass(frozen=True,slots=True)
class DeepQuestionResult:
    question:str
    rationale:str
    expected_evidence:tuple[str,...]
    activity:LearningActivityCandidate
    authoritative:bool=False

class NativeGuidedLearningExecutor:
    def __init__(self,llm:LLMClient):self.llm=llm

    def mastery_path(self,context:NativeRunContext,*,goal:str,current_stage:str):
        context.require_capability(CAP_MASTERY)
        profile=context.domain_policy.mastery_profile
        if not profile:raise ValidationError("DomainPolicy mastery_profile is empty")
        if current_stage not in profile:raise ValidationError("current_stage not in DomainPolicy mastery_profile")
        idx=profile.index(current_stage);nxt=profile[min(idx+1,len(profile)-1)]
        stages=tuple({"id":s,"completed":i<idx,"current":i==idx} for i,s in enumerate(profile))
        act=LearningActivityCandidate(context.area_id,context.session_id,CAP_MASTERY,"mastery_path",f"Reviewed mastery path for {goal}",metadata={"current_stage":current_stage,"suggested_next":nxt})
        return MasteryPath(goal,current_stage,stages,nxt,act,False)

    def deep_question(self,context:NativeRunContext,*,concept:str,stage:str):
        context.require_capability(CAP_MASTERY);context.permission_scope.require_risk("llm")
        if not getattr(self.llm,"available",False):raise ProviderUnavailable("deep question requires configured LLM")
        system="Generate one concise question that exposes understanding boundaries. Return only the question. Never auto-claim mastery."
        if context.domain_policy.learning_instructions:system+="\nDomain policy:\n"+context.domain_policy.learning_instructions
        q=self.llm.complete(messages=[{"role":"system","content":system},{"role":"user","content":f"Concept: {concept}\nStage: {stage}"}],temperature=.35).text.strip()
        act=LearningActivityCandidate(context.area_id,context.session_id,CAP_MASTERY,"deep_question",f"Generated a mastery-evidence candidate question for {concept}",metadata={"stage":stage})
        return DeepQuestionResult(q,"Candidate prompt only; host evidence policy decides Mastery.",("explanation","transfer/application","error correction or boundary statement"),act,False)
