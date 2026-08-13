# Interest Growth v0.6.0 — Native Execution Product

This release turns the v0.5 General Interest Host plus v0.6 native execution core into one runnable product.

## Product changes

- Native execution is registered in the FastAPI Host and packaged import paths.
- Migration 11 installs persistent execution-only Tutor checkpoint, public event and auxiliary memory tables.
- New Knowledge Bases default to `native-lexical`; four native local retrieval engines are built in.
- Host-owned Source files are parsed locally and projected into read-only native snapshots.
- Native retrieval results persist as Host `RetrievalCandidate` rows with `candidate_not_evidence` status.
- Tutor UI uses native Host endpoints and preserves canonical `TutorSession` / `TutorTurn` history.
- Domain, global/Area capability and manifest permission boundaries fail closed for native runs.
- Tutor, Research, Learning, Practice, Co-Writer, Living Book, Memory, Visualize and Knowledge execute through the built-in Native Core.
- Migration 12 removes retired runtime settings and marks legacy external indexes for explicit native rebuild.
- Validation desktop builds initialize the disabled updater safely and allow packaged sidecar first-launch validation time, preventing launch-time updater panic and false Core timeout.

## Configuration

Local retrieval and other deterministic local capabilities do not require an AI key. Configure a DeepSeek-compatible API key in the desktop settings to enable native AI Tutor and Research execution. Secrets remain in the OS credential store and are never returned to the renderer.

## Verification boundary

Source tests, production Web build, browser interaction, desktop sidecar smoke and native bundle construction are reported independently. Signed/notarized distribution and real Windows validation require the corresponding signing credentials and target OS.
