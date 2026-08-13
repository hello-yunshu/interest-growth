# v0.6 Native Execution — Stable Source Gate Audit

**Audit date:** 2026-08-13
**Scope:** closing the v0.6 Research Candidate to release candidate (RC) into a
stable **source** state, and recording exactly what is verified vs. not.

## 1. Outcome

The v0.6 stable **source** gate is PASS. This is a source-and-test decision; it
does **not** claim a binary release. Native packaging (PyInstaller sidecar,
macOS `.app`/DMG, Windows Setup) remains a separate external binary gate that
is not re-verified in this audit.

## 2. Resolved v0.6 release-candidate findings

### P1 — Research claim/citation grounding — Resolved

`ResearchBlockResult.citation_ids` now means *actually-used* candidate
citations, not *all retrieved candidates*. The structured output requires the
model to declare `claims[].citation_ids`; Native Core validates
`used_citation_ids ⊆ supplied_candidate_ids`, marks unknown IDs as
`invalid_grounding`, and refuses to present a block as `completed` when
grounding is invalid. Ungrounded factual claims carry an explicit
`grounding_status`. `candidate_ids` retains the full retrieved set for
compatibility. Host `persist_sources` still writes `verified = false` even when
a Research citation is used (`candidate_not_evidence` preserved).

### P2 — Tutor pause/resume permission revocation — Resolved

Resume no longer reuses the snapshot grant as future executable grants.
`effective_future_grants = snapshot_granted_tools ∩ current_granted_tools`, so
a permission revoked while paused (network, capability, scope, Area) is
re-enforced on resume, while tools granted *after* pause do not auto-expand an
older turn. Already-executed Tool Results are preserved as history.

### P3 — OpenAI-compatible transport error normalization — Resolved

A stable taxonomy maps transport failures without leaking secrets:
`ProviderAuthError` (401/403), `ProviderRateLimited` (429), `ProviderTimeout`
(timeout), `ProviderProtocolError` (invalid JSON / unexpected schema),
`ProviderUnavailable` (DNS/connection/5xx). Exception messages never echo
Authorization headers, API keys or tokens.

### P4 — SafeWebFetcher DNS TOCTOU — Resolved

The hostname is resolved once, every returned target must be public, and the
connection is pinned to the validated IP via a custom TLS transport that still
preserves SNI and certificate hostname verification (no `verify=False`, no
IP-URL/host-header tricks). Redirects stay disabled; private/RFC1918/link-local/
loopback/reserved/IPv6-loopback targets and DNS rebinding are blocked.

### P5 — Native Core single source — Resolved

`verify_native_core_sync.py` (wired into CI) fails on any byte-for-byte drift
between the root `interest_growth_native` and the standalone
`packages/native-execution-core` mirror. `sync_native_core.py` propagates the
shared audit scripts; the mirror is currently IN SYNC.

### P6 — GitHub Actions immutable pin — Resolved

All third-party Actions are pinned to full upstream commit SHAs with
human-readable version comments; each SHA was verified against the upstream tag.

## 3. Verified in this audit

- Host Python suite: **234 passed**.
- Native Execution Core standalone suite: **97 passed**.
- Native Core single-source mirror check: PASS (IN SYNC).
- Python compileall: PASS.
- Architectural self-audit: PASS.
- Area isolation, PermissionBroker (read/write/network/llm removal → 403),
  Candidate/Evidence boundary, migration (fresh + v0.4.1) regressions: PASS.
- Exact RAG adapter contract/reviewed smoke: PASS.
- Web ESLint `--max-warnings=0`: PASS.
- Web static production build: PASS (15 static pages).
- Rust `cargo check --locked`: PASS.

## 4. Not claimed by this audit

- No PyInstaller sidecar rebuild, macOS `.app`/DMG, or Windows package was
  produced or re-verified here.
- No Developer ID / notarization, and no real-public-TLS or remote-hostname
  exercise was performed.
- Android remains NOT STARTED (Gate C/D).

See `V0_7_IMPLEMENTATION_AUDIT.md` for the v0.7 Gate B close and remaining
Gate C/D next order.