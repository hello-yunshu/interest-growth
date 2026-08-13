from __future__ import annotations
from dataclasses import dataclass
from .capabilities import CAP_BOOK
from .context import NativeRunContext
from .contracts import GroundingRefSnapshot
from .errors import ProviderUnavailable
from .llm import LLMClient
from .signals import LearningActivityCandidate

@dataclass(frozen=True,slots=True)
class BookChapterProposal:
    ordinal:int
    title:str
    purpose:str
    grounding_refs:tuple[GroundingRefSnapshot,...]
    source_fingerprints:tuple[str,...]
    status:str="proposal"

    def stale_against(self,current_fingerprints:dict[tuple[str,str],str])->bool:
        """Execution-side advisory only; host LivingBook compiler remains authoritative."""
        for ref in self.grounding_refs:
            if not ref.fingerprint:
                continue
            current=current_fingerprints.get((ref.ref_type,ref.ref_id))
            if current is None or current!=ref.fingerprint:
                return True
        return False

@dataclass(frozen=True,slots=True)
class BookProposal:
    title:str
    purpose:str
    chapters:tuple[BookChapterProposal,...]
    activity:LearningActivityCandidate
    status:str="proposal"

class NativeBookExecutor:
    """Proposal executor only; host LivingBook/Chapter compiler remains canonical."""
    def __init__(self,llm:LLMClient):self.llm=llm

    def scaffold(self,context:NativeRunContext,*,title:str,purpose:str,chapter_hints=None,grounding_refs=()):
        context.require_capability(CAP_BOOK)
        hints=chapter_hints or ("Why this matters","Core structure","Practice and examples","Reflection and transfer")
        refs=tuple(grounding_refs);fps=tuple(sorted({x.fingerprint for x in refs if x.fingerprint}))
        chapters=tuple(BookChapterProposal(i+1,str(h),str(purpose),refs,fps) for i,h in enumerate(hints))
        act=LearningActivityCandidate(context.area_id,context.session_id,CAP_BOOK,"book_scaffold","Prepared a reviewable Living Book scaffold")
        return BookProposal(title,purpose,chapters,act)

    def expand_chapter(self,context:NativeRunContext,*,chapter:BookChapterProposal,source_context:str):
        context.require_capability(CAP_BOOK);context.permission_scope.require_risk("llm")
        if not getattr(self.llm,"available",False):raise ProviderUnavailable("book expansion requires configured LLM")
        return self.llm.complete(messages=[
            {"role":"system","content":"Draft a chapter proposal grounded only in supplied context. Preserve uncertainty and citations/grounding labels; do not mark it accepted."},
            {"role":"user","content":f"Chapter: {chapter.title}\nPurpose: {chapter.purpose}\nContext:\n{source_context}"},
        ],temperature=.3).text
