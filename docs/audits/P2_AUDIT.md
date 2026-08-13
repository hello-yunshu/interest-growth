# P2 Audit · Research & Evidence

**Decision:** PASS WITH LIVE-ENGINE NOTE

## Verified locally

- deterministic Research Plan exists even when engines fail;
- research selection order: DeepTutor → DeepSeek limited → manual workspace;
- no-engine run is retained as `degraded`, not dropped;
- Source candidates never enter as verified; `POST /sources` cannot inject `verified=true` either;
- unverified Source cannot create `human_verified` Evidence;
- Claim requires known Evidence IDs;
- Claim verification requires at least one supporting Evidence and rechecks both Evidence and Source human-verification state;
- Claim revisions append ClaimVersion, preserve v1, and automatically invalidate the previous `human_verified` state until the new current version is reviewed;
- browser Research workspace supports Source verification, Evidence creation/selection, Claim create/revise, explicit Skeptic Pass, and human verify;
- Skeptic Pass is persisted as `psychology-skeptic` CapabilityRun and checks support-chain verification, AI-summary-only dependencies, counter/boundary evidence, limitations, confidence/evidence mismatch, absolute/diagnostic/causal wording; it never changes Claim verification state;
- DeepTutor stable contract tests cover discovery, SSE result/error semantics, and ResearchEngine cancellation delegation when an upstream turn id is available.

## Live-engine note

No DeepTutor instance/API credential was available in this sandbox, so a real remote deep_research was not executed. This is intentionally covered by deterministic contract tests and fallback tests, but a live smoke test remains required before claiming a specific external deployment is operational.
