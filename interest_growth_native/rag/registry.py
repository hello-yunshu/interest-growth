from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol

from ..contracts import KnowledgeBaseSnapshot
from ..errors import LegacyEngineReviewRequired
from .native import (
    NativeLexicalIndex, NativeLightGraphIndex,
    NativeConceptGraphIndex, NativeHeadingIndex,
)

@dataclass(frozen=True, slots=True)
class RagEngineDescriptor:
    id: str
    kind: str
    exact_upstream_equivalent: bool
    description: str = ""

@dataclass(frozen=True, slots=True)
class LegacyEngineMigration:
    engine_id: str
    status: str
    message: str
    suggested_native: str = ""

class ExactRagAdapter(Protocol):
    """Exact third-party algorithm adapter.

    Exact adapters receive the original host Source snapshots + engine config,
    not already-lost text chunks, so LlamaIndex/LightRAG/GraphRAG/PageIndex
    implementations can own their real ingestion semantics without becoming
    canonical product owners.
    """
    engine_id: str
    def build(self, kb: KnowledgeBaseSnapshot) -> Any: ...
    def retrieve(self, built: Any, *, query: str, top_k: int): ...

class RagEngineRegistry:
    LEGACY = frozenset({"llamaindex","lightrag","graphrag","pageindex"})
    def __init__(self):
        self._native = {
            "native-lexical": NativeLexicalIndex,
            "native-lightgraph": NativeLightGraphIndex,
            "native-concept-graph": NativeConceptGraphIndex,
            "native-heading": NativeHeadingIndex,
        }
        self._exact: dict[str, ExactRagAdapter] = {}

    def register_exact(self, adapter: ExactRagAdapter):
        if adapter.engine_id not in self.LEGACY:
            raise ValueError("exact adapters are reserved for reviewed legacy/third-party engine IDs")
        self._exact[adapter.engine_id] = adapter

    def list(self):
        native = [
            RagEngineDescriptor(k,"native",False,"Interest Growth lightweight native retrieval")
            for k in self._native
        ]
        exact = [
            RagEngineDescriptor(k,"exact-adapter",True,"Reviewed exact third-party adapter")
            for k in sorted(self._exact)
        ]
        return tuple(native+exact)

    def native_factory(self, engine_id):
        if engine_id in self._native: return self._native[engine_id]
        raise KeyError(engine_id)

    def exact(self, engine_id):
        return self._exact.get(engine_id)

    def legacy_migration(self, engine_id):
        if engine_id not in self.LEGACY: return None
        if engine_id in self._exact:
            return LegacyEngineMigration(engine_id,"exact_adapter_available","Exact adapter registered.")
        suggestions = {
            "llamaindex":"native-lexical",
            "lightrag":"native-lightgraph",
            "graphrag":"native-concept-graph",
            "pageindex":"native-heading",
        }
        return LegacyEngineMigration(
            engine_id, "requires_review",
            "No exact adapter is registered. Silent algorithm substitution is forbidden.",
            suggestions[engine_id],
        )
