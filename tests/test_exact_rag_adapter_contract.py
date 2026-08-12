from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.rag.types import RetrievalCandidate
from interest_growth_native.contracts import KnowledgeBaseSnapshot,SourceTextSnapshot,SourceLocator
from .helpers import StaticResolver,ctx,store

class FakeExact:
    engine_id="lightrag"
    def __init__(self):self.seen=None
    def build(self,kb):
        self.seen=kb
        return {"ok":True}
    def retrieve(self,built,*,query,top_k):
        s=self.seen.sources[0]
        return [RetrievalCandidate(
            "c","k",s.source_id,s.fingerprint,s.filename,1.0,s.text,0,
            SourceLocator(filename=s.filename,page=1),"lightrag",
        )]

def test_exact_adapter_receives_whole_kb_once_and_collision_safe_source_names():
    kb=KnowledgeBaseSnapshot(
        "k","a","KB","lightrag",
        (
            SourceTextSnapshot("s1","a","paper.pdf","alpha","fp1"),
            SourceTextSnapshot("s2","a","paper.pdf","beta","fp2"),
        ),
    )
    resolver=StaticResolver([kb]);b=NativeEngineBundle(knowledge_resolver=resolver,store=store())
    adapter=FakeExact();b.retrieval.registry.register_exact(adapter)
    out=b.retrieval.retrieve(ctx(),kb_ids=["k"],query="alpha")
    assert adapter.seen is not None
    assert len(adapter.seen.sources)==2
    names=[x.filename for x in adapter.seen.sources]
    assert len(names)==len(set(names))
    assert names[0].startswith("s1__") and names[1].startswith("s2__")
    assert out[0].source_id=="s1"
