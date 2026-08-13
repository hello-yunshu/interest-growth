# Psychology Growth v0.3.0 · Native Learning Runtime

v0.3 turns DeepTutor integration from a collection of high-value one-shot calls into a session-aware psychology learning runtime while preserving the product's independent data/evidence model.

## Major changes

### Native Tutor Runtime
- local TutorSession/TutorTurn ownership;
- semantic DeepTutor stream normalization;
- final answer only from answer-visible content;
- `wait_for_input → submit_user_reply` on the same turn;
- resume/cancel/regenerate transport support;
- typed DeepTutor transport/protocol/capability/rejected/cancelled errors;
- compatibility SSE only for transport/protocol failures;
- psychology product tool allowlist.

### RAG correctness and provenance
- `KnowledgeIngestionRun` owns whole-KB async task truth;
- Source↔KB mapping no longer pretends to be per-document index progress;
- collision-safe upstream filenames;
- one multi-file disaster rebuild;
- task-id mismatch cannot falsely report completion;
- RetrievalCandidate persists citation/location metadata and maps to local Source when possible;
- retrieval remains `candidate_not_evidence`.

### Learning evidence
- PracticeItem / PracticeAttempt / MasteryEvidence;
- DeepTutor Question Notebook import;
- explicit evidence promotion, never automatic Mastery change;
- local LearningNote with Notebook projection;
- local versionable TutorPersona with DeepTutor projection.

### Co-Writer
- local WritingDocument is canonical;
- selection-aware rewrite/shorten/expand proposals;
- optional RAG/Web grounding;
- explicit Accept/Reject;
- base SHA-256 prevents stale AI proposals from overwriting newer text.

### Living Book / Memory / Visualize
- local LivingBook + Chapter source refs/fingerprints;
- Claim revision/reverification marks dependent chapters stale;
- DeepTutor Book proposal and spine both require explicit confirmation;
- Growth Memory authoritative vs DeepTutor Memory auxiliary graph;
- Visualize produces reviewable `psychology.visual.v1` manifests/artifacts.

### Plugin and deployment hardening
- 19 first-party plugin manifests;
- PermissionBroker enforces declared brokered resource/risk capabilities;
- explicitly not a hostile-code sandbox;
- local Skill Package SHA covers supporting files while public DeepTutor Skills CRUD limitation is reported honestly;
- API Dockerfile includes `python-multipart` required for UploadFile routes;
- project metadata/Web/API versions aligned to 0.3.0;
- loopback-only Compose default retained.

## Upgrade from v0.2

ORM diff confirms v0.3 is additive relative to v0.2: existing tables have no added/removed columns; v0.3 adds new tables. A real upgrade check created a v0.2 DB, inserted a sentinel Question, initialized v0.3 against the same DB and retained the row while adding the v0.3 schema.

The schema ledger is still a lightweight additive bootstrap mechanism, not general Alembic-style migration infrastructure. Future non-additive schema changes require explicit tested migrations.

## Automated verification before archive freeze

- pytest: 53/53 PASS
- compileall: PASS
- self-audit: PASS
- Web JS/JSX parser: 16 files, 0 parse failures
- YAML parse: 21 files PASS
- v0.2→v0.3 DB upgrade sentinel: PASS
- empty v0.3 DB: 33 tables
- plugins: 19
- Feature Flags: 20
- bundled Personas: 4
- OpenAPI: 101 paths / 119 operations
- TODO/FIXME/NotImplemented in product code: none found
- no tracked private DB/source/artifact payloads

The exact final ZIP is independently re-extracted and rechecked during release packaging; its SHA/report live beside the delivered archive.

## Not live-verified in this sandbox

Docker binary is unavailable; DeepTutor v1.5.11 is not locally installed/running; release checks do not consume the user's DeepSeek key; the Web node dependency tree is absent. Therefore real Compose startup, real DeepTutor/DeepSeek calls and Next production/browser E2E remain deployment-host live gates and are not falsely called PASS.
