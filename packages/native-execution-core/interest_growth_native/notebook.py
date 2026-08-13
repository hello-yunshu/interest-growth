from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .capabilities import CAP_NOTEBOOK,CAP_PRACTICE
from .context import NativeRunContext
from .contracts import PracticeOrigin,GroundingRefSnapshot
from .errors import ProviderUnavailable
from .llm import LLMClient
from .signals import LearningActivityCandidate

@dataclass(frozen=True,slots=True)
class NoteProposal:
    title:str
    body:str
    grounding_refs:tuple[GroundingRefSnapshot,...]
    activity:LearningActivityCandidate
    status:str="proposal"

@dataclass(frozen=True,slots=True)
class PracticeProposal:
    prompt:str
    question_type:str
    options:tuple[str,...]
    expected_answer:str
    answer_guide:str
    concept_ids:tuple[str,...]
    origin:PracticeOrigin
    grounding_refs:tuple[GroundingRefSnapshot,...]
    activity:LearningActivityCandidate
    status:str="proposal"
    mastery_effect:str="none_until_attempt_review"

class NativeNotebookExecutor:
    def propose_note(self,context:NativeRunContext,*,title:str,body:str,grounding_refs=()):
        context.require_capability(CAP_NOTEBOOK)
        act=LearningActivityCandidate(context.area_id,context.session_id,CAP_NOTEBOOK,"learning_note_proposal",f"Prepared note proposal: {title}")
        return NoteProposal(title.strip(),body.strip(),tuple(grounding_refs),act)

class NativeQuestionNotebookExecutor:
    def __init__(self,llm:LLMClient):self.llm=llm
    def propose(self,context:NativeRunContext,*,topic:str,material:str,count=3,concept_ids=(),origin:PracticeOrigin|None=None,grounding_refs=()):
        context.require_capability(CAP_PRACTICE);context.permission_scope.require_risk("llm")
        if not getattr(self.llm,"available",False):raise ProviderUnavailable("practice proposal requires configured LLM")
        count=max(1,min(int(count),10));out=[]
        origin=origin or PracticeOrigin("manual")
        for i in range(count):
            response=self.llm.complete(messages=[
                {"role":"system","content":"Generate one diagnostic practice item. Format: QUESTION then a newline 'ANSWER: ...'. Do not claim mastery."},
                {"role":"user","content":f"Topic: {topic}\nMaterial: {material}\nItem {i+1}"},
            ],temperature=.4).text
            if "\nANSWER:" in response:
                prompt,expected=response.split("\nANSWER:",1)
            else:
                prompt,expected=response,"Review against host rubric."
            act=LearningActivityCandidate(context.area_id,context.session_id,CAP_PRACTICE,"practice_proposal",f"Prepared practice proposal for {topic}",metadata={"index":i})
            out.append(PracticeProposal(prompt.strip(),"open_response",(),expected.strip(),"Attempt independently, then compare reasoning.",tuple(concept_ids),origin,tuple(grounding_refs),act))
        return tuple(out)
