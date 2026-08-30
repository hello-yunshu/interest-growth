from __future__ import annotations
from pathlib import Path
import pytest

from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.capabilities import CAP_NOTEBOOK,CAP_PRACTICE,CAP_COWRITER
from interest_growth_native.contracts import GroundingRefSnapshot,PracticeOrigin,KnowledgeBaseSnapshot,SourceTextSnapshot
from interest_growth_native.errors import StaleProposalError
from interest_growth_native.llm import LLMResponse
from interest_growth_native.skills import load_skill_directory
from .helpers import StaticResolver,ctx,kb,store

class Simple:
    available=True
    def complete(self,**kwargs):return LLMResponse("Q?\nANSWER: A")

def test_rag_candidate_preserves_v03_locator_and_fingerprint():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb(page=12,source_fp="source-v1")]),store=store(),llm=Simple())
    x=b.retrieval.retrieve(ctx(),kb_ids=["k"],query="wet paper",top_k=1)[0]
    assert x.kb_id=="k" and x.source_id=="src"
    assert x.source_fingerprint=="source-v1"
    assert x.locator.page==12 and x.locator.section=="sec"
    assert x.engine_id=="native-lexical"
    assert x.status=="candidate_not_evidence"

def test_rag_cache_uses_effective_source_fingerprint_when_kb_fingerprint_blank():
    resolver=StaticResolver([kb(text="alpha unique",fingerprint="",source_fp="")])
    b=NativeEngineBundle(knowledge_resolver=resolver,store=store(),llm=Simple())
    assert b.retrieval.retrieve(ctx(),kb_ids=["k"],query="alpha")
    resolver.kbs["k"]=kb(text="beta changed",fingerprint="",source_fp="")
    assert b.retrieval.retrieve(ctx(),kb_ids=["k"],query="beta")
    assert not b.retrieval.retrieve(ctx(),kb_ids=["k"],query="alpha")

def test_unregistered_rag_id_is_rejected_without_old_version_fallback():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb(engine="lightrag")]),store=store(),llm=Simple())
    with pytest.raises(KeyError, match="unknown RAG engine"):
        b.retrieval.retrieve(ctx(),kb_ids=["k"],query="x")

def test_skill_package_fingerprint_changes_when_supporting_file_changes(tmp_path):
    root=tmp_path/"skill";(root/"references").mkdir(parents=True)
    (root/"SKILL.md").write_text("---\nname: test-skill\ndescription: test\n---\n# Test\nBody","utf-8")
    ref=root/"references"/"a.md";ref.write_text("A","utf-8")
    a=load_skill_directory(root)
    ref.write_text("B","utf-8")
    b=load_skill_directory(root)
    assert a.fingerprint!=b.fingerprint
    assert a.references==("references/a.md",)

def test_notebook_remains_available_when_practice_is_disabled():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    c=ctx(caps={CAP_NOTEBOOK},global_caps={CAP_NOTEBOOK})
    note=b.notebook.propose_note(c,title="N",body="Body")
    assert note.status=="proposal"

def test_practice_proposal_is_structured_and_never_auto_mastery():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    out=b.question_notebook.propose(ctx(),topic="x",material="m",count=1,concept_ids=["c1"],origin=PracticeOrigin("tutor","turn","s","t"))
    item=out[0]
    assert item.question_type=="open_response"
    assert item.expected_answer=="A"
    assert item.concept_ids==("c1",)
    assert item.mastery_effect=="none_until_attempt_review"

class EditLLM:
    available=True
    def complete(self,**kwargs):return LLMResponse("new text")

def test_cowriter_stale_guard_checks_revision_document_and_selection():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=EditLLM())
    c=ctx()
    doc="hello ABC world"
    p=b.cowriter.propose_selection_edit(c,base_revision_id="r1",current_document_text=doc,selection_start=6,selection_end=9,instruction="rewrite")
    assert p.validate_current_base(current_revision_id="r1",current_document_text=doc)
    with pytest.raises(StaleProposalError):
        p.validate_current_base(current_revision_id="r2",current_document_text=doc)
    changed="HELLO ABC world"
    with pytest.raises(StaleProposalError):
        p.validate_current_base(current_revision_id="r1",current_document_text=changed)

def test_book_proposal_carries_grounding_fingerprints_but_stays_proposal():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    ref=GroundingRefSnapshot("source","s1","fp1","Source")
    out=b.book.scaffold(ctx(),title="Book",purpose="learn",chapter_hints=["A"],grounding_refs=[ref])
    ch=out.chapters[0]
    assert ch.grounding_refs==(ref,)
    assert ch.source_fingerprints==("fp1",)
    assert out.status=="proposal"

def test_book_proposal_can_surface_grounding_staleness_without_owning_canonical_book():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store(),llm=Simple())
    ref=GroundingRefSnapshot("claim","c1","claim-v1","Claim")
    ch=b.book.scaffold(ctx(),title="B",purpose="p",chapter_hints=["C"],grounding_refs=[ref]).chapters[0]
    assert ch.stale_against({("claim","c1"):"claim-v1"}) is False
    assert ch.stale_against({("claim","c1"):"claim-v2"}) is True
