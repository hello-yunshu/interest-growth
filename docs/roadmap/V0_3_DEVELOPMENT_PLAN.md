# v0.3.1 Development Plan — Independent Learning Runtime

**Status: all Gates A–F implemented; release verification is the remaining gate.**

This plan is derived from the independent-product audits. Work is ordered by product ownership and dependency, not upstream feature visibility. DeepTutor is one optional provider implementation.

## Gate 0 — Provider boundary

1. No vendored/forked DeepTutor source or direct `import deeptutor`.
2. No Psychology product plugin hard-depends on `integration.deeptutor`.
3. Provider calls require deployment enablement **and** Integration-plugin enablement.
4. Disabling the provider must preserve local Knowledge/Practice/Note/Persona/Tutor Session/Living Book records and routes.
5. Product branding remains provider-neutral; provider names belong only in integration/configuration surfaces.

## Gate A — Runtime correctness (P0) · COMPLETE

1. Split DeepTutor errors into transport/protocol/capability/rejected/cancelled.
2. Add semantic EventNormalizer; only answer-visible content can build final text.
3. Add session-aware turn methods and explicit resume/cancel/regenerate/user-reply messages.
4. Add TutorSession/TutorTurn tables and REST APIs.
5. Add Psychology Tutor WebSocket proxy with bidirectional `wait_for_input` handling.
6. Add contract tests covering tool/progress/source events, wait/reply, reconnect cursor and no semantic-error fallback.

Exit: an interactive mocked Mastery turn can ask, receive an answer, resume and complete without answer pollution.

## Gate B — RAG correctness (P0/P1) · COMPLETE

1. Add KnowledgeIngestionRun.
2. Replace fake per-Source index readiness with mapping + run status.
3. Use collision-safe upstream filenames.
4. Add multi-file create and one-run rebuild.
5. Match upstream task identity before claiming completion.
6. Validate supported extensions when DeepTutor is enabled; local storage remains available when upstream is disabled/unreachable.
7. Normalize and persist RetrievalCandidate citations to local Source IDs.

Exit: two same-named PDFs can coexist, rebuild uses one ingestion task, and citation candidates trace back to local Source.

## Gate C — Learning evidence (P1) · COMPLETE

1. Add PracticeItem/PracticeAttempt.
2. Import DeepTutor Question Notebook/quiz results when available.
3. Add explicit Mastery evidence promotion, never automatic Mastery change.
4. Add LearningNote and Notebook projection.
5. Add TutorPersona local model and DeepTutor persona sync.

Exit: a Concept can have session-guided questions, attempts, notes and explicit evidence without hidden state changes.

## Gate D — Expression workspace (P1) · COMPLETE

1. Add WritingDocument/Revision.
2. Add selection-aware rewrite/shorten/expand with grounding.
3. Add accept/reject diff semantics.
4. Keep Publish Guard downstream of accepted writing.

Exit: content can be surgically revised with review history and no automatic publication.

## Gate E — Living knowledge (P1/P2) · COMPLETE

1. Add LivingBook/Chapter and source fingerprints.
2. Compile from local Concepts/Claims/Notes/Practice/Artifacts.
3. Mark chapters stale on source/claim changes.
4. Add optional DeepTutor Book assist without making upstream book storage canonical.
5. Productize Visualize artifacts.
6. Expose auxiliary DeepTutor Memory Graph/audit view.

Exit: the user's long-term psychology knowledge can become an update-aware living book.

## Gate F — Plugin and operational hardening (P1/P2) · COMPLETE

1. PermissionBroker and declared-access checks for new plugin service operations.
2. Refresh plugin manifests/feature flags for tutor-runtime, notebook, practice, persona, co-writer, living-book.
3. Expand self-audit for source privacy, executable plugin prohibition, localhost defaults and unsafe path fields.
4. Update architecture/status/release docs.
5. Clean git baseline, archive only tracked files, extract and re-run all gates.

## Non-goals for v0.3

- No automatic counseling/diagnosis/treatment decisions.
- No autonomous social publishing.
- No arbitrary third-party executable plugins.
- No requirement to copy DeepTutor Partners/Voice/Multi-user/Math Animator into the psychology main workflow.
- No requirement that DeepTutor Memory replace Growth Memory.
