# Psychology Growth v0.3.1 — Independent Learning Runtime Blueprint

Status: historical v0.3 blueprint; superseded current runtime facts are in
`docs/architecture/01_ARCHITECTURE.md`, `docs/decisions/0006-native-only-product-execution.md`
and `docs/development/DEVELOPMENT_CONTRACT.md`.
Date: 2026-08-12
Historical compatibility target: DeepTutor v1.5.11. DeepTutor is not part of
the current Native Tutor runtime or current release dependency.

## 1. Why v0.3 exists

Psychology Growth owns Questions, Topics, Sources, Evidence, Claims, Concepts, Mastery, Growth Memory and publication approval. This historical blueprint recorded an optional external DeepTutor provider; later native-only closure moved the canonical Tutor runtime into Interest Growth. The provider-boundary principles remain useful, but the diagram and current-tense runtime claims below are historical.

v0.3 therefore changes the integration unit from **capability call** to **tutor session**.

## 2. Non-negotiable product laws

1. **Independent Product** — no fork/distribution/downstream identity, no vendored DeepTutor source, and no DeepTutor domain types in product tables or public contracts.
2. **Own-Data-First** — local Source/Note/Claim/Mastery/Book content remains canonical; upstream indexes/sessions are rebuildable execution state.
3. **Human-Review-Gated** — retrieval is not Evidence, practice success is not automatic Mastery, generated prose is not automatically publishable.
4. **Interactive but interruptible** — turns may pause for input, resume, cancel, reconnect, or be abandoned without corrupting product facts.
5. **Event-semantic** — tool/progress/source events never masquerade as final answer text.
6. **Capability-scoped fallback** — only transport/protocol failures may fall back to compatibility SSE; semantic capability failures must remain failures.
7. **Traceable personalization** — auxiliary provider memory/persona can help an agent, but Growth Memory remains authoritative and inspectable.
8. **Plugin-first** — notebook, practice, co-writer, living-book and tutor-runtime are independently disableable.
9. **Provider-is-not-parent** — no Psychology product plugin may hard-depend on `integration.deeptutor`; disabling that provider cannot disable local canonical capabilities.

## 3. Runtime architecture

```text
Web UI
  │
  ├─ REST: durable product records
  │
  └─ Psychology Tutor WebSocket
       │
       ▼
Tutor Runtime (product)
  ├─ TutorSession (local durable owner)
  ├─ TutorTurn (local execution trace)
  ├─ EventNormalizer
  ├─ ContextResolver
  └─ CapabilityProviderTurnAdapter (DeepTutor implementation today)
       │
       ▼
Optional capability provider
(current implementation: DeepTutor /api/v1/ws)
  ├─ start_turn
  ├─ subscribe/resume
  ├─ wait_for_input
  ├─ submit_user_reply
  ├─ cancel_turn
  └─ regenerate
```

The browser never needs external-provider credentials. Psychology Growth maps local KB IDs, Persona IDs and Skill IDs to generic upstream references. Current DeepTutor session/turn IDs are adapter references only, never product identity.

## 4. Event contract

Normalized product events:

- `answer_delta` — visible final-answer text only.
- `thinking` — optional hidden/diagnostic trace, never appended to answer.
- `activity` — stage/progress/observation/tool call/result.
- `sources` — provenance candidates.
- `wait_for_input` — structured learner interaction request.
- `result` — structured capability result.
- `done` — terminal status.
- `error` — typed transport/protocol/capability/rejected/cancelled failure.

Only `answer_delta` contributes to assembled answer text. `sources` feeds RetrievalCandidate/Provenance. `wait_for_input` is relayed to the UI and the same upstream turn is resumed with `submit_user_reply`.

## 5. Tutor session domain

`TutorSession`
- local id
- Topic / Concept scope
- upstream provider session id (DeepTutor today)
- active persona
- selected local knowledge bases
- selected skills
- status: active / paused / closed
- timestamps

`TutorTurn`
- local session id
- capability
- upstream turn id
- status: running / awaiting_input / completed / failed / cancelled / rejected
- input snapshot
- normalized trace
- answer text / structured result
- sequence cursor for reconnect
- pending input schema

Session continuity is product-visible: another learning action on the same Concept can reuse an external provider session when available while local Mastery remains independent.

## 6. RAG ingestion model

v0.2's per-source `KnowledgeSourceIndex.status` is demoted to a source-to-KB mapping. Indexing truth moves to `KnowledgeIngestionRun`.

```text
Source (canonical original)
  │
  ├─ KnowledgeSourceMapping
  │      └─ unique upstream filename: pg_<source-id>__<filename>
  │
  └─ KnowledgeIngestionRun
         source_ids[]
         upstream_task_id
         provider
         state
         upstream_progress
```

A KB rebuild is one multi-file ingestion request, not N overlapping background uploads. A run may be marked completed only when the upstream progress task id matches the run's task id (or the upstream response lacks task identity and the product explicitly records that limitation).

## 7. Retrieval provenance

`RetrievalCandidate` stores:
- capability run id / tutor turn id
- local KB id
- local Source id when resolvable
- upstream filename
- page/section/location
- excerpt/snippet
- raw citation metadata
- state=`candidate_not_evidence`

Promotion to Evidence remains an explicit human action and requires Source/location review.

## 8. Learning evidence

Flexible Mastery remains canonical. v0.3 adds:

`PracticeItem`
- Concept
- question id / type / options / expected answer
- origin (local or named external provider)
- source session/turn

`PracticeAttempt`
- user answer
- correctness (when known)
- AI judgment
- explanation
- created at
- `mastery_evidence_candidate=true`

A correct answer never automatically changes Mastery. The UI offers an explicit “use as mastery evidence” action that writes a human-visible evidence note.

## 9. Learning Notes / Notebook bridge

`LearningNote` is a local intermediate artifact for thoughts that are not yet Claims:
- Topic / Concept
- title
- markdown body
- note type
- status
- optional upstream notebook/record mapping

External Notebook integrations are projection/context surfaces, not the canonical note store; DeepTutor is the current implementation.

## 10. Personas

`TutorPersona` is local and versionable; provider adapters may project it (currently to DeepTutor PERSONA.md). Personas shape behavior/voice; Skills shape workflow. Bundled defaults:
- psychology-peer
- psychology-research-assistant
- psychology-socratic-tutor
- psychology-evidence-reviewer

## 11. Co-Writer

`WritingDocument` stores local markdown. `WritingRevision` records selection, instruction, before/after, grounding refs, and accept/reject state.

An external Co-Writer is used as an editing provider when available (currently DeepTutor); deterministic/local or DeepSeek fallback may be used only for prose transformation. Accepted revisions update local text; rejected revisions remain trace records.

## 12. Living Book

`LivingBook` and `LivingBookChapter` are local learning artifacts compiled from owned Sources/Claims/Notes/Practice/Concepts. An external Book provider may assist outline/block generation (currently DeepTutor), but local source fingerprints determine staleness.

Minimum v0.3 block types:
- text
- callout
- concept
- evidence
- quiz reference
- visual artifact reference
- user note

A source/Claim revision marks dependent chapter blocks stale rather than silently rewriting them.

## 13. Memory Graph and Visual Artifacts

External agent memory remains read-only/auxiliary by default; the current bridge reads DeepTutor Memory. v0.3 exposes trace/audit relationships as an auxiliary Memory Graph while Growth Memory remains canonical.

Visualize output is normalized into a `visual_manifest.json` artifact plus referenced output files/HTML when available. Raw adapter JSON is preserved only as diagnostic metadata.

## 14. Plugin security

First-party plugin manifests remain deploy-driven. v0.3 introduces `PermissionBroker` for product service calls:
- resource patterns (source/evidence/claim/note/artifact/session)
- operation (read/write/network/llm/shell)
- plugin id
- deny by default for undeclared operations when brokered APIs are used

This is not a hostile-code sandbox; third-party executable plugins remain unsupported. It prevents first-party/plugin service code from silently exceeding declared product permissions and prepares for future external integrations.

## 15. Completion definition

v0.3 is complete when:
- unified events cannot contaminate final answer text;
- interactive turns can pause/resume/cancel/reconnect;
- local tutor sessions persist upstream IDs without surrendering ownership;
- RAG rebuild is one multi-file ingestion run with unique source identity;
- retrieval citations normalize to local Source where possible;
- practice and notes have durable local workflows;
- persona, co-writer and living-book surfaces are product usable with safe fallback;
- memory/visualize outputs are inspectable artifacts;
- plugin permission broker is enforced at new plugin-owned service boundaries;
- regression, contract, security and clean-archive verification pass.
