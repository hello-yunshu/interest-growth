# Interest Growth v0.6.0 RC2 Native Execution Core — Final Audit

## Verdict

**RC2 execution package: PASS for source-level Host Integration.**

It supersedes both:
1. the rejected first `native-learning-runtime` prototype; and
2. the pre-RC2 Native Execution Core that still regressed several v0.3 Tutor/RAG/Skill contracts.

This file preserves the standalone RC2 package audit boundary. The frozen
v0.5.0 Host was subsequently supplied, verified, and physically merged at the
repository root. The current merged result is audited in the root
`docs/FINAL_RC2_AUDIT.md`; this package remains independently verifiable and is
not a second Host.

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

## Historical package-to-Host boundary (now completed at repository root)

The standalone package originally required the real v0.5 Host for these gates;
the repository-root integration has now completed them:
- real migration ledger registration;
- removal/compat isolation of actual `pg_deeptutor` orchestration call sites;
- preserving actual Host TutorSession/TutorTurn, KnowledgeIngestionRun,
  Practice/MasteryEvidence, WritingRevision and LivingBook compiler code;
- original 104 v0.5 tests + RC2 tests together;
- real Browser/Next/desktop integration gates.


## Current standalone package verification snapshot

- collected pytest tests: **70**
- all 70 passed
- `scripts/verify.py`: PASS
- runtime direct `deeptutor` imports: 0
- runtime hardcoded Psychology policy terms: 0
- TODO/FIXME/NotImplemented runtime placeholders: 0
- native canonical duplicate tables: 0
- persistent native tables: exactly checkpoint/event/aux-memory
- v0.3 A–K regression mapping: test-gated/documented
- migration SQL package resource: byte-identical to release migration
- production migration runner `executescript()`: absent
- global Capability wildcard production default: absent
