# Interest Growth v0.5 → v0.6 RC2 Host Merge Checklist

RC2 package completion and a full host release are separate gates.

## A. Verify the frozen host

Expected baseline:
- v0.5.0
- commit `2c7141e7677fd48d12087159911cd60a51168502`
- ZIP SHA-256 `524ed7868220567805626cdae316f35d6a896ecb35758f5ced2c32c07203a358`

Do not merge against an unknown tree and then call it the verified v0.5 upgrade.

## B. Preserve v0.5 ownership

The host remains canonical owner of:
- InterestArea / EntityAreaBinding / AreaCapabilitySetting;
- Source / KnowledgeBase lifecycle / KnowledgeIngestionRun;
- Evidence / Claim / ClaimVersion / verification;
- Concept / Mastery / PracticeItem / PracticeAttempt / MasteryEvidence;
- LearningNote;
- Persona/Domain Pack Skills;
- WritingDocument / Revision;
- LivingBook / Chapter staleness/reverification;
- Growth Memory / Reflection;
- Human Review / content approval.

Do not replace these with RC2 execution tables.

## C. Register migration 11

Register `migrations/0011_native_execution_state.sql` in the **real** host
migration ledger. It adds only:
- `native_tutor_checkpoint`
- `native_run_event`
- `native_aux_memory`

Required:
- real v0.5 DB upgrade test;
- all old entity counts preserved;
- failure injection proves atomic rollback;
- persistent runtime never creates schema implicitly.

## D. Bind Engine Contracts

Wire host contracts to:
- `NativeResearchExecutor`
- `NativeRetrievalEngine`
- `NativeDocumentParser` where fallback parsing is suitable
- `NativeGuidedLearningExecutor`
- `NativeTutorExecutor`
- `NativeQuestionNotebookExecutor`
- `NativeCoWriterExecutor`
- `NativeBookExecutor`
- `NativeVisualizationExecutor`
- `NativeSolveExecutor`

Exact third-party RAG algorithms must use reviewed exact adapters; never silently
reinterpret legacy engine IDs.

## E. Compile context from the host

Every execution context must include:
- current Area;
- Area Capability settings;
- explicit global plugin lifecycle (no wildcard default);
- active Domain Pack → DomainPolicy;
- PermissionBroker output;
- host TutorSession/TutorTurn binding;
- selected KB IDs;
- Persona/Skill fingerprints;
- user-enabled Tool/network choices.

## F. Preserve v0.3 Tutor invariants

Before cutover prove:
- only answer-visible content is canonical answer;
- Tool narration does not pollute answer;
- `wait_for_input` resumes the same execution snapshot;
- `seq/after_seq` reconnect does not duplicate deltas;
- RAG produces sanitized `sources`;
- raw Tool bodies/private reasoning are not public Activity Trace;
- cancel is terminal under late Provider output;
- exceptions terminalize ERROR;
- stale RUNNING recovers after process restart;
- server-owned pending question IDs/options override model-authored values.

## G. Preserve v0.3 RAG/learning/writing invariants

Prove:
- whole-KB task ID truth remains `KnowledgeIngestionRun`;
- Source aliases cannot collide in an external engine;
- RetrievalCandidate maps to local Source and location;
- retrieval never creates Evidence;
- supporting Skill bytes change package fingerprint;
- Notebook/Practice independent lifecycle;
- Practice correctness never auto-promotes Mastery;
- stale Co-Writer proposals cannot overwrite a newer Revision;
- Living Book source/claim fingerprint changes still mark canonical chapters stale;
- Agent Memory does not become Growth Memory.

## H. Retire DeepTutor default execution

Before declaring Native cutover:
- no Capability Plugin hard-depends on `integration.deeptutor`;
- active business orchestration has no direct `pg_deeptutor` construction;
- DeepTutor, if temporarily kept, is explicit compatibility-only/default-off;
- desktop/compose startup does not require its sidecar;
- UI does not present native lightweight RAG as exact LightRAG/GraphRAG/PageIndex.

## I. Final release gates

Run:
1. original v0.5 **104 tests**;
2. all RC2 tests;
3. route→capability→permission meta-test;
4. Area direct-ID isolation audit;
5. browser E2E:
   Area switch → RAG → Tutor → wait/resume → reconnect → content → switch Area;
6. rapid Area-switch stale-response race;
7. production Next build;
8. committed npm/Cargo lockfile checks;
9. final merged archive re-extraction and complete revalidation;
10. target-OS PyInstaller/Tauri build/sign/notarization as a separate native gate.

A package copy alone is never “host merge complete”.
