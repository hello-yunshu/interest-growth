# Reviewed Exact RAG Adapters

Interest Growth keeps third-party engine IDs exact. `llamaindex`, `lightrag`,
`graphrag`, and `pageindex` are never aliases for the four lightweight native
engines. An unregistered ID reports `requires_review`; an installed but
incompatible dependency reports a reviewed-version error.

## Runtime contract

All exact adapters implement the same Host boundary:

1. receive one whole-KB `KnowledgeBaseSnapshot` containing original Host Source
   text, fingerprints, locators, metadata and (when present) original bytes;
2. send collision-safe upstream names containing a sanitized Source ID plus a
   stable Source-ID hash;
3. invoke the actual third-party indexing and retrieval API;
4. return `RetrievalCandidate` rows mapped back to the canonical local KB ID,
   Source ID, original filename, fingerprint and locator;
5. reject every unmappable upstream result instead of inventing provenance;
6. leave `KnowledgeIngestionRun` in the Host as the authoritative whole-KB
   operation record; third-party indexes remain disposable projections;
7. retain `candidate_not_evidence` status for every retrieval result.

Adapters are optional and default-off. Installing a package alone does not
select an engine. The Host composition root must explicitly register a reviewed
adapter with its required model, embedding, storage and secret configuration.

## Reviewed bindings

| Engine ID | Upstream binding | Reviewed API line | Network/local behavior | Operational impact |
|---|---|---|---|---|
| `llamaindex` | `Document` → `VectorStoreIndex.from_documents` → `as_retriever().retrieve` | `llama-index-core` 0.14.x | Can be local only when its configured embedding/model stack is local and cached | Core wheel is large; embedding integration and model assets add size. In-memory default is not a durability contract. |
| `lightrag` | `LightRAG.initialize_storages` → `ainsert` → structured `aquery_data` | `lightrag-hku` 1.5.x | Can be local-first with local LLM/embedding/storage; hosted model/storage configuration adds network use | Heavy graph/vector/KV/doc-status stack, persistent workspaces, model cost and substantial transitive dependencies. |
| `graphrag` | `load_config` → `graphrag.api.build_index` → `local_search` with generated parquet tables | `graphrag` 3.1.x | Model/embedding configuration determines network use; output is a large rebuildable local projection | Highest indexing cost and runtime footprint; upstream warns that indexing can be expensive. Prompt/config changes require review and rebuild. |
| `pageindex` | `PageIndexClient.submit_document` → status polling → retrieval polling | `pageindex` 0.1.3 SDK | Cloud API; original document bytes leave the self-hosted boundary only after explicit server-side configuration | Small SDK, but network, API-key, document-retention, privacy and service-availability impacts apply. Not offline/local-first. |

The optional dependency groups are `rag-llamaindex`, `rag-lightrag`,
`rag-graphrag`, and `rag-pageindex`. They are deliberately excluded from the
default desktop/server install so a local-first installation does not silently
gain model downloads, external uploads or a much larger attack surface.

## License, maintenance and security review

The reviewed upstream repositories declare MIT licenses. Interest Growth does
not vendor their source, model weights or notices; installers must preserve the
upstream packages' license/NOTICE obligations and re-audit transitive licenses.

- LlamaIndex: <https://github.com/run-llama/llama_index>
- LightRAG: <https://github.com/HKUDS/LightRAG>
- Microsoft GraphRAG: <https://github.com/microsoft/graphrag>
- PageIndex: <https://github.com/VectifyAI/PageIndex>

Before moving an adapter to a new API line:

- inspect the upstream changelog, security advisories and package provenance;
- update `reviewed_version` and the optional dependency range together;
- rerun whole-document, same-name collision and provenance regression tests;
- exercise the real package in an isolated environment with the intended
  model/storage configuration;
- document data egress, persistence, deletion and offline behavior;
- measure installed/image size and indexing resource use;
- keep secrets in Host/server secret storage, never KB settings, renderer state,
  logs, URLs or Git.

GraphRAG and LightRAG execute complex model-driven indexing over untrusted
documents. Their working directories must be private and resource-bounded.
PageIndex sends original bytes to an external service and therefore requires a
separate user-visible data-egress review. None of these adapters upgrades a
retrieval result into Evidence.
