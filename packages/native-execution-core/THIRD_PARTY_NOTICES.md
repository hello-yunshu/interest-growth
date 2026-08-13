# Third-Party Notice

Interest Growth Native Execution Core is an independent implementation. Its
Python dependencies retain their respective upstream licenses and terms.

The runtime does not vendor or import a third-party tutor workflow engine. A
future adapter that incorporates third-party source code must preserve every
applicable license, copyright and NOTICE obligation.

The optional reviewed exact adapters call, but do not vendor:

- `llama-index-core` 0.14.x;
- `lightrag-hku` 1.5.x;
- Microsoft `graphrag` 3.1.x;
- Vectify AI `pageindex` 0.1.3.

Their reviewed upstream repositories declare MIT licenses. They remain
default-off because their model, embedding, storage, network, data-egress,
runtime-size and security impacts differ materially from the lightweight native
engines. See the Host document `docs/architecture/EXACT_RAG_ADAPTERS.md`.
