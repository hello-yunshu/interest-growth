from __future__ import annotations
import difflib,hashlib
from dataclasses import dataclass
from .capabilities import CAP_COWRITER
from .context import NativeRunContext
from .contracts import GroundingRefSnapshot
from .errors import ProviderUnavailable,StaleProposalError,ValidationError
from .llm import LLMClient
from .signals import LearningActivityCandidate

def sha(text:str)->str:return hashlib.sha256(text.encode("utf-8")).hexdigest()

@dataclass(frozen=True,slots=True)
class WritingProposal:
    base_revision_id:str
    base_document_fingerprint:str
    selection_start:int
    selection_end:int
    selection_fingerprint:str
    original:str
    proposed:str
    instruction:str
    diff:str
    grounding_refs:tuple[GroundingRefSnapshot,...]
    activity:LearningActivityCandidate
    accepted:bool=False

    def validate_current_base(self,*,current_revision_id:str,current_document_text:str):
        if current_revision_id!=self.base_revision_id:raise StaleProposalError("document revision changed")
        if sha(current_document_text)!=self.base_document_fingerprint:raise StaleProposalError("document fingerprint changed")
        if not (0<=self.selection_start<=self.selection_end<=len(current_document_text)):
            raise StaleProposalError("selection range no longer valid")
        selected=current_document_text[self.selection_start:self.selection_end]
        if sha(selected)!=self.selection_fingerprint:raise StaleProposalError("selection changed")
        return True

class NativeCoWriterExecutor:
    def __init__(self,llm:LLMClient):self.llm=llm

    def propose_selection_edit(self,context:NativeRunContext,*,base_revision_id:str,current_document_text:str,selection_start:int,selection_end:int,instruction:str,grounding_refs=(),surrounding_context=""):
        context.require_capability(CAP_COWRITER);context.permission_scope.require_risk("llm")
        if not getattr(self.llm,"available",False):raise ProviderUnavailable("Co-Writer requires configured LLM")
        if not (base_revision_id and 0<=selection_start<=selection_end<=len(current_document_text)):raise ValidationError("invalid base revision/selection")
        selection=current_document_text[selection_start:selection_end]
        system="You are a writing assistant. Return only the proposed replacement. Never silently accept or overwrite canonical text."
        prompt=f"Instruction: {instruction}\nContext: {surrounding_context}\nTarget:\n{selection}"
        proposed=self.llm.complete(messages=[{"role":"system","content":system},{"role":"user","content":prompt}],temperature=.3).text
        diff="\n".join(difflib.unified_diff(selection.splitlines(),proposed.splitlines(),fromfile="current",tofile="proposal",lineterm=""))
        act=LearningActivityCandidate(context.area_id,context.session_id,CAP_COWRITER,"cowriter_proposal","Prepared a reviewable writing revision proposal",metadata={"base_revision_id":base_revision_id})
        return WritingProposal(base_revision_id,sha(current_document_text),selection_start,selection_end,sha(selection),selection,proposed,instruction,diff,tuple(grounding_refs),act,False)
