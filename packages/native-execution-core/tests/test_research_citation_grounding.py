import hashlib
import json

from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.contracts import KnowledgeBaseSnapshot, SourceLocator, SourceTextSnapshot
from interest_growth_native.knowledge import _source_fp, _split_source
from interest_growth_native.llm import LLMResponse
from interest_growth_native.research import ResearchSubtopic
from .helpers import StaticResolver, ctx, kb, store


class QueueLLM:
    available = True

    def __init__(self, values):
        self.values = list(values)

    def complete(self, **kwargs):
        v = self.values.pop(0)
        return LLMResponse(json.dumps(v) if isinstance(v, dict) else str(v))


def _rag_citation_id(source):
    fp = _source_fp(source)
    chunk = _split_source("k", source)[0]
    return "C-" + hashlib.sha256(f"rag|{source.source_id}|{chunk.id}|{fp}".encode()).hexdigest()[:12]


def _multi_source_kb(texts):
    sources = tuple(
        SourceTextSnapshot(
            f"src{i}", "a", f"s{i}.md", text,
            locator=SourceLocator(filename=f"s{i}.md"),
        )
        for i, text in enumerate(texts)
    )
    return KnowledgeBaseSnapshot("k", "a", "KB", "native-lexical", sources)


def _run(answers, kb_snap=None):
    llm = QueueLLM(answers)
    resolver = StaticResolver([kb_snap]) if kb_snap else StaticResolver([kb()])
    b = NativeEngineBundle(knowledge_resolver=resolver, store=store(), llm=llm)
    preview = b.research.preview_outline(ctx(), question="paint")
    return b.research.run_confirmed(
        ctx(), question=preview.refined_topic,
        subtopics=preview.subtopics, kb_ids=("k",) if kb_snap else (),
    )


def _multi_source_kb(texts):
    sources = tuple(
        SourceTextSnapshot(
            f"src{i}", "a", f"s{i}.md", text,
            locator=SourceLocator(filename=f"s{i}.md"),
        )
        for i, text in enumerate(texts)
    )
    return KnowledgeBaseSnapshot("k", "a", "KB", "native-lexical", sources)


_PREVIEW = {"refined_topic": "paint", "clarification_questions": [],
            "subtopics": [{"title": "paint method", "overview": "b"}, {"title": "paint limits", "overview": "d"}]}


def _legal_block(cids):
    return {"summary": "s", "claims": [{"text": "c1", "citation_ids": [cids[0]]}], "append_topics": []}


def test_legal_citations_pass():
    kb_snap = _multi_source_kb(["paint alpha", "paint beta"])
    cids = [_rag_citation_id(s) for s in kb_snap.sources]
    out = _run([_PREVIEW, _legal_block(cids), _legal_block(cids), "report"], kb_snap=kb_snap)
    assert out.partial is False
    block = out.blocks[0]
    assert block.status == "completed"
    assert block.citation_ids == (cids[0],)
    assert block.claims[0].grounding_status == "grounded"


def test_hallucinated_citation_rejected_as_partial():
    kb_snap = _multi_source_kb(["paint alpha"])
    cids = [_rag_citation_id(s) for s in kb_snap.sources]
    out = _run(
        [
            _PREVIEW,
            {"summary": "s", "claims": [{"text": "c1", "citation_ids": ["C-NOT-EXIST"]}], "append_topics": []},
            {"summary": "s", "claims": [{"text": "c2", "citation_ids": ["C-NOT-EXIST"]}], "append_topics": []},
            "report",
        ],
        kb_snap=kb_snap,
    )
    assert len(cids) == 1
    assert out.partial is True
    block = out.blocks[0]
    assert block.status == "partial"
    assert block.error_type == "invalid_grounding"
    assert block.claims[0].grounding_status == "invalid_grounding"
    assert block.citation_ids == ()


def test_citation_ids_reflect_only_actually_used_candidates():
    kb_snap = _multi_source_kb(["paint one", "paint two", "paint three", "paint four", "paint five", "paint six"])
    cids = [_rag_citation_id(s) for s in kb_snap.sources]
    assert len(cids) == 6
    out = _run(
        [
            _PREVIEW,
            {
                "summary": "s",
                "claims": [
                    {"text": "c1", "citation_ids": [cids[0]]},
                    {"text": "c2", "citation_ids": [cids[4]]},
                ],
                "append_topics": [],
            },
            _legal_block(cids),
            "report",
        ],
        kb_snap=kb_snap,
    )
    block = out.blocks[0]
    assert block.status == "completed"
    assert sorted(block.citation_ids) == sorted([cids[0], cids[4]])
    assert sorted(block.candidate_ids) == sorted(cids)


def test_ungrounded_factual_claim_is_not_evidence():
    out = _run(
        [
            _PREVIEW,
            {"summary": "s", "claims": [{"text": "factual-looking statement without citation"}], "append_topics": []},
            {"summary": "s", "claims": [{"text": "also ungrounded"}], "append_topics": []},
            "report",
        ]
    )
    block = out.blocks[0]
    assert block.claims[0].grounding_status == "ungrounded"
    assert block.citation_ids == ()
    assert out.status == "candidate_not_evidence"
    assert all(x.status == "candidate_not_evidence" for x in out.citations)
