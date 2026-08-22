#!/usr/bin/env python3
"""Fail closed when reviewed exact-RAG dependency APIs drift."""
from __future__ import annotations

import inspect
import json
from importlib import metadata

from graphrag import api as graphrag_api
from graphrag.config.load_config import load_config
from lightrag import LightRAG, QueryParam
from llama_index.core import Document, VectorStoreIndex
from pageindex import PageIndexClient


def main() -> int:
    versions = {
        name: metadata.version(name)
        for name in ("llama-index-core", "lightrag-hku", "graphrag", "pageindex")
    }
    expected = {
        "llama-index-core": "0.14.",
        "lightrag-hku": "1.5.",
        "graphrag": "3.1.",
        "pageindex": "0.2.8",
    }
    for name, prefix in expected.items():
        if not versions[name].startswith(prefix):
            raise SystemExit(f"{name} {versions[name]} is outside reviewed line {prefix}")

    assert callable(Document)
    assert callable(VectorStoreIndex.from_documents)
    assert callable(LightRAG)
    assert callable(QueryParam)
    assert inspect.iscoroutinefunction(LightRAG.initialize_storages)
    assert inspect.iscoroutinefunction(LightRAG.ainsert)
    assert inspect.iscoroutinefunction(LightRAG.aquery_data)
    assert callable(load_config)
    assert inspect.iscoroutinefunction(graphrag_api.build_index)
    assert inspect.iscoroutinefunction(graphrag_api.local_search)
    assert callable(PageIndexClient)
    for method in ("submit_document", "get_document", "get_tree", "submit_query", "get_retrieval"):
        assert callable(getattr(PageIndexClient, method))

    print(json.dumps(versions, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
