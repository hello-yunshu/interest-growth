from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.contracts import KnowledgeBaseSnapshot, SourceLocator, SourceTextSnapshot
from interest_growth_native.errors import ExactRagProvenanceError, LegacyEngineReviewRequired
from interest_growth_native.rag import (
    GraphRagExactAdapter,
    LightRagExactAdapter,
    LlamaIndexExactAdapter,
    PageIndexExactAdapter,
    RagEngineRegistry,
)
from interest_growth_native.rag.types import RetrievalCandidate
from .helpers import StaticResolver, ctx, store


def snapshot(engine_id: str) -> KnowledgeBaseSnapshot:
    return KnowledgeBaseSnapshot(
        "kb-1",
        "a",
        "Reviewed adapters",
        engine_id,
        (
            SourceTextSnapshot(
                "source/one",
                "a",
                "same.pdf",
                "Alpha durable retrieval source.",
                "fp-one",
                SourceLocator(filename="same.pdf", page=1),
                original_bytes=b"%PDF-reviewed-one",
                media_type="application/pdf",
            ),
            SourceTextSnapshot(
                "source one",
                "a",
                "same.pdf",
                "Beta collision source.",
                "fp-two",
                SourceLocator(filename="same.pdf", page=2),
                original_bytes=b"%PDF-reviewed-two",
                media_type="application/pdf",
            ),
        ),
        fingerprint="kb-fp",
    )


def retrieve(adapter, engine_id: str):
    registry = RagEngineRegistry()
    registry.register_exact(adapter)
    bundle = NativeEngineBundle(
        knowledge_resolver=StaticResolver([snapshot(engine_id)]),
        store=store(),
        rag_registry=registry,
    )
    return bundle.retrieval.retrieve(ctx(), kb_ids=["kb-1"], query="durable", top_k=2)


def test_every_unregistered_legacy_id_requires_review_and_never_uses_native_factory():
    registry = RagEngineRegistry()
    for engine_id in sorted(registry.LEGACY):
        migration = registry.legacy_migration(engine_id)
        assert migration.status == "requires_review"
        assert registry.exact(engine_id) is None
        with pytest.raises(KeyError):
            registry.native_factory(engine_id)
        bundle = NativeEngineBundle(
            knowledge_resolver=StaticResolver([snapshot(engine_id)]),
            store=store(),
            rag_registry=registry,
        )
        with pytest.raises(LegacyEngineReviewRequired):
            bundle.retrieval.retrieve(ctx(), kb_ids=["kb-1"], query="durable")


def test_llamaindex_adapter_calls_vector_store_index_and_maps_metadata():
    class Document:
        def __init__(self, *, text, id_, metadata):
            self.text, self.id_, self.metadata = text, id_, metadata

    class Node:
        node_id = "llama-node"

        def __init__(self, document):
            self.metadata = document.metadata
            self.text = document.text

        def get_content(self):
            return self.text

    class Index:
        documents = None

        @classmethod
        def from_documents(cls, documents, **kwargs):
            cls.documents = documents
            return cls()

        def as_retriever(self, **kwargs):
            return SimpleNamespace(retrieve=lambda query: [SimpleNamespace(node=Node(self.documents[0]), score=0.91)])

    adapter = LlamaIndexExactAdapter(runtime=SimpleNamespace(Document=Document, VectorStoreIndex=Index))
    result = retrieve(adapter, "llamaindex")
    assert len(Index.documents) == 2
    assert all(document.text.startswith(("Alpha", "Beta")) for document in Index.documents)
    assert result[0].source_id == "source/one"
    assert result[0].filename == "same.pdf"
    assert result[0].engine_id == "llamaindex"


def test_lightrag_adapter_calls_real_api_shape_with_whole_documents(tmp_path):
    class LightRAG:
        last = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.inputs = None
            LightRAG.last = self

        async def initialize_storages(self):
            self.initialized = True

        async def ainsert(self, inputs, *, ids, file_paths):
            self.inputs, self.ids, self.file_paths = inputs, ids, file_paths

        async def aquery_data(self, query, params):
            return {
                "status": "success",
                "data": {"chunks": [{
                    "content": self.inputs[0],
                    "file_path": self.file_paths[0],
                    "chunk_id": "light-chunk",
                    "reference_id": "ref-1",
                    "score": 0.88,
                }]},
            }

    class QueryParam:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    adapter = LightRagExactAdapter(
        storage_root=tmp_path,
        rag_kwargs={"llm_model_func": object(), "embedding_func": object()},
        runtime=SimpleNamespace(LightRAG=LightRAG, QueryParam=QueryParam),
    )
    result = retrieve(adapter, "lightrag")
    assert LightRAG.last.initialized
    assert LightRAG.last.inputs == [
        "Alpha durable retrieval source.", "Beta collision source."
    ]
    assert len(set(LightRAG.last.file_paths)) == 2
    assert result[0].source_id == "source/one"
    assert result[0].raw_citation["reference_id"] == "ref-1"


def test_graphrag_adapter_calls_build_and_local_search_and_joins_documents(tmp_path):
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "settings.yaml").write_text("models: {}\n", encoding="utf-8")

    class Frame:
        def __init__(self, rows):
            self.rows = rows

        def to_dict(self, orient):
            assert orient == "records"
            return list(self.rows)

    class Runtime:
        def __init__(self):
            self.api = self
            self.pd = SimpleNamespace()
            self.input_name = ""
            self.local_called = False

        def load_config(self, workspace):
            self.input_name = next((Path(workspace) / "input").iterdir()).name
            return {"workspace": str(workspace)}

        async def build_index(self, *, config):
            self.built = config
            return [SimpleNamespace(errors=[])]

        def read_table(self, output, name, *, required):
            rows = {
                "documents": [{"id": "doc-1", "title": self.input_name}],
                "text_units": [{"id": "unit-1", "document_ids": ["doc-1"], "text": "GraphRAG exact context"}],
                "entities": [],
                "relationships": [],
                "communities": [],
                "community_reports": [],
                "covariates": [],
            }[name]
            return Frame(rows)

        async def local_search(self, **kwargs):
            self.local_called = True
            return "answer ignored", {"sources": Frame([{"id": "unit-1", "score": 0.77}])}

    runtime = Runtime()
    adapter = GraphRagExactAdapter(
        storage_root=tmp_path / "data",
        settings_root=settings,
        runtime=runtime,
    )
    result = retrieve(adapter, "graphrag")
    assert runtime.local_called
    assert result[0].text == "GraphRAG exact context"
    assert result[0].source_id == "source/one"


def test_pageindex_adapter_uploads_original_bytes_and_maps_each_doc(tmp_path):
    class Client:
        last = None

        def __init__(self, *, api_key):
            self.api_key = api_key
            self.documents = {}
            Client.last = self

        def submit_document(self, path):
            doc_id = f"doc-{len(self.documents) + 1}"
            self.documents[doc_id] = (Path(path).name, Path(path).read_bytes())
            return {"doc_id": doc_id}

        def get_tree_result(self, doc_id):
            return {"status": "completed", "doc_id": doc_id}

        def submit_retrieval_query(self, doc_id, query, thinking=False):
            return {"retrieval_id": f"retrieval-{doc_id}"}

        def get_retrieval_result(self, retrieval_id):
            return {
                "status": "completed",
                "result": [{"node_id": retrieval_id, "text": "PageIndex exact context", "page": 3, "score": 0.8}],
            }

    adapter = PageIndexExactAdapter(
        api_key="server-secret",
        storage_root=tmp_path,
        runtime=SimpleNamespace(PageIndexClient=Client),
        poll_interval=0,
        timeout=1,
    )
    result = retrieve(adapter, "pageindex")
    assert {content for _, content in Client.last.documents.values()} == {
        b"%PDF-reviewed-one", b"%PDF-reviewed-two"
    }
    assert {item.source_id for item in result} == {"source/one", "source one"}
    assert all(item.filename == "same.pdf" for item in result)


def test_exact_adapter_result_with_unknown_source_is_rejected():
    class Bad:
        engine_id = "lightrag"
        upstream_distribution = "reviewed"
        reviewed_version = "reviewed"

        def build(self, kb):
            return kb

        def retrieve(self, built, *, query, top_k):
            return [RetrievalCandidate(
                "bad", built.kb_id, "unknown", "", "unknown", 1.0, "bad", 0,
                SourceLocator(), self.engine_id,
            )]

    with pytest.raises(ExactRagProvenanceError):
        retrieve(Bad(), "lightrag")
