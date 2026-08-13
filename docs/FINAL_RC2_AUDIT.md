# Interest Growth v0.6.0 RC2 Native Execution Core — Final Audit

## Verdict

**RC2 execution package: PASS for source-level Host Integration.**

It supersedes both:
1. the rejected first `native-learning-runtime` prototype; and
2. the pre-RC2 Native Execution Core that still regressed several v0.3 Tutor/RAG/Skill contracts.

The frozen v0.5.0 Host archive was later supplied and verified at SHA-256
`524ed7868220567805626cdae316f35d6a896ecb35758f5ced2c32c07203a358`.
The merged Host source now contains the execution integration, migration ledger,
canonical Host bindings and combined regression suite. Native packaging and
target-device release proof remain separate gates.

## High-risk regressions closed

- Tool narration cannot enter final answer unless the provider explicitly labels
  the segment answer-visible.
- Pause/resume persists messages and completed Tool results and continues the
  same pending `ask_user` call.
- Event replay is cursor-based (`seq`, `after_seq`).
- RAG usage produces sanitized public Source provenance.
- Source/locator/fingerprint metadata survives retrieval.
- empty KB fingerprint cannot cause stale index reuse after Source changes.
- supporting Skill file changes invalidate the Skill package fingerprint.
- global Capability lifecycle is mandatory/fail-closed.
- trusted host Tools are permission-filtered before being offered to the model.
- Co-Writer revision-level stale-base protection is restored.
- parser/resource limits and OOXML natural ordering are enforced.
- exact RAG adapters receive whole-KB original Source snapshots, not lossy chunks.
- streaming `finish_reason=length` has bounded continuation.
- packaged Wheel contains its execution migration resource.

## Automated source verification

The final source directory is required to pass:
- compileall for runtime/scripts/tests;
- static no-DeepTutor-import and no domain-policy leak scan;
- no arbitrary code-execution surface scan;
- exact public Tutor event contract;
- migration/resource byte equality;
- atomic migration policy;
- complete pytest suite;
- exact archive re-extraction;
- source manifest verification;
- Wheel build/install/import/store smoke.

## Completed Host boundary

- migration 11 is registered in the real Host migration ledger;
- active legacy provider orchestration was removed through migration 12;
- Host TutorSession/TutorTurn, KnowledgeIngestionRun, Practice/MasteryEvidence,
  WritingRevision and LivingBook ownership remains canonical;
- combined Host, native-contract, architecture, integration and security tests
  run from the merged source tree;
- Web production build and desktop source-contract gates run separately from
  target-OS signing/notarization proof.

## Exact RAG follow-up

Reviewed optional adapters now bind LlamaIndex, LightRAG, Microsoft GraphRAG and
PageIndex IDs to their actual upstream APIs. Unregistered IDs return
`requires_review`; no legacy ID has a native fallback map. Whole-KB snapshots,
collision-safe external names and fail-closed provenance mapping are test-gated.


## Final merged source-tree verification snapshot

- frozen v0.5 archive: exact SHA-256, **246 files**, original **104 tests passed**
- merged pytest tests: **192 collected, 192 passed**
- `scripts/verify.py`: PASS
- strict Host audit: P0 0, P1 0, ready for native cutover
- Web lint and 15-page static production build: PASS
- desktop Rust `cargo check --locked`: PASS with a temporary sidecar placeholder
- reviewed upstream dependency/API smoke: PASS for all four exact RAG adapters
- runtime direct `deeptutor` imports: 0
- runtime hardcoded Psychology policy terms: 0
- TODO/FIXME/NotImplemented runtime placeholders: 0
- native canonical duplicate tables: 0
- persistent native tables: exactly checkpoint/event/aux-memory
- v0.3 A–K regression mapping: test-gated/documented
- migration SQL package resource: byte-identical to release migration
- production migration runner `executescript()`: absent
- global Capability wildcard production default: absent
