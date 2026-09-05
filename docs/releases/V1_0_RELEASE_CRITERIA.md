# Interest Growth v1.0.0 — Release Criteria

> **Status:** normative Gate R2 §17 (API/Schema Freeze) artifact.
> **Source of truth order:** Accepted ADR → frozen Runtime/Security Contract → this document → audit conclusions → historical blueprints.

This document freezes what "Interest Growth v1.0.0 Stable" means before the 1.0 RC is cut. It is the acceptance contract for Gate R3 (1.0 RC) and Gate R4 (1.0 Stable). Any change to this contract after an RC is cut requires a new RC, not an in-place edit.

---

## 1. Product definition (frozen)

1.0's formally supported scope (master prompt §2.1):

- General Interest Core (non-psychology journey must work)
- Psychology Domain Pack (default, not Core)
- Interest Areas (strict isolation)
- Curiosity
- Research / Evidence / Claim (human review preserved)
- Knowledge / RAG (rebuildable derived index; Host canonical)
- Tutor
- Learning / Practice / Mastery (AI never declares mastery)
- Growth Feedback / Reflection (no streak/days/pages metrics)
- Living Book
- Co-Writer
- Content Studio (human-review + export; auto-publish is NOT a 1.0 gate)
- Publish Guard
- Artifact / Export

Formally supported runtimes: `desktop-local`, `desktop-remote`, `android-remote`.
Formally supported deployments: desktop local-sidecar, self-hosted single-owner server, Android remote client.

## 2. Architecture invariants (frozen, non-negotiable)

- Native-only product runtime: the standalone `interest_growth_native` Core is the only workflow runtime. DeepTutor runtime must remain absent.
- Host DB is the only canonical product truth; RAG index is rebuildable derived data.
- Interest Area / Capability Plugin / Domain Pack / Capability Provider remain separate layers.
- Provider (DeepSeek/OpenAI-compatible) is model transport only; it never owns product state.
- Human review gates: RetrievalCandidate ≠ Evidence, AI Answer ≠ Mastery, Proposal ≠ Accepted state.
- Psychology safety boundary: not diagnosis, not automated treatment; human-review public content.
- desktop token / App-Data / credential boundaries preserved; exact migration compatibility preserved.

## 3. Frozen contracts (Gate R2 §17)

Before any 1.0 RC:

- Runtime IDs: `desktop-local`, `desktop-remote`, `android-remote`, `browser-remote`.
- API version: `1` (server `API_VERSION`, client `SUPPORTED_API_VERSION`).
- Capability contract: `/api/system/capabilities` shape with `api_version`, `min_client_version`, `server_version`, `runtime_modes`, `server_instance_id`, `auth`.
- Auth session contract: owner bootstrap (single), device sessions, access/refresh rotation (single-use, atomic), per-device revoke, login expiry / identity-changed / update-required semantics.
- Backup format version: `1`; manifest carries `format_version`, `product`, `schema_version`, `created_at`, checksums. Restore rejects future format, wrong product, corrupt checksum.
- Canonical domain schema: versioned by `schema_migrations`; current schema `16`.
- Public Native capability names: frozen `PLATFORM_CAPABILITIES` vocabulary; `DESKTOP_ONLY_CAPABILITIES` asserted false on non-desktop runtimes.
- Migration semantics: purely additive; upgrade creates a backup; downgrade not supported; old clients must not silently open a new schema.
- Remote error taxonomy (§15, frozen): `NETWORK_UNAVAILABLE`, `SERVER_UNAVAILABLE`, `RATE_LIMITED`, `LOGIN_EXPIRED`, `IDENTITY_CHANGED`, `UPDATE_REQUIRED`, `UNSUPPORTED_SERVER`, `CREDENTIAL_PERSISTENCE_FAILURE`, `PROTOCOL_ERROR`, `RUNTIME_MODE_DENIED`.

### 3.1 Version single-source consistency

All current-version fields must agree with the canonical product version in `pyproject.toml`. `MIN_CLIENT_VERSION` is separately validated as a compatibility floor and is not required to equal `SERVER_VERSION`. These rules are enforced by `scripts/verify_version_consistency.py` (wired into `scripts/verify.py` → CI `host` gate):

- `pyproject.toml` → `project.version` (canonical)
- `apps/api/pg_api/remote_auth.py` → `SERVER_VERSION`, `MIN_CLIENT_VERSION`
- `apps/desktop/src-tauri/Cargo.toml` → `package.version`
- `apps/desktop/src-tauri/tauri.conf.json` → `version`
- `apps/desktop/package.json` → `version`
- `apps/web/package.json` → `version`
- `apps/web/lib/runtime/contract.js` → `CLIENT_VERSION`

After the freeze, 1.x evolution is backward-compatible additive only; breaking changes go to 2.0 or an explicit migration.

#### Erratum / clarification: minimum client version

`MIN_CLIENT_VERSION` is a compatibility floor, not a mirror of
`SERVER_VERSION`. It may remain lower than the current server/client version
when older clients are still supported, and it must only be raised when the
compatibility policy intentionally drops those clients. The invariant is:

```text
MIN_CLIENT_VERSION <= SERVER_VERSION
```

Changing this floor after an RC is a compatibility-policy change and therefore
requires the normal RC review; it must not be changed merely to make the
version strings look identical.

## 4. Gates for 1.0 RC (Gate R3)

- All Release Gate jobs green on the exact RC tag commit (never "main was green").
- Tag SHA == artifact build SHA.
- `BLOCKER = 0`, `HIGH = 0`. MEDIUM only if documented, owned, non-release-blocking and not data-corruption/security-bypass/auth/upgrade-failure.
- No `continue-on-error` on required gates; NOT RUN ≠ PASS.

## 5. Gates for 1.0 Stable (Gate R4)

- RC full remote Actions green; Stable tag full remote Actions green.
- Android: signed release APK (same-certificate install/upgrade verified), remote product flow on the emulator verified.
- Server: remote integration verified; backup/restore clean verified.
- Desktop: Windows x64 + macOS arm64 packages build and pass artifact audit.
- Cross-device: desktop-remote + Android emulator against the same server verified.
- Migration fixtures verified; release docs complete.

## 6. Definition of Done (master prompt §53)

All of: architecture intact, host canonical, P0–P4 journey complete, general interest works, psychology safety works, all three runtimes work, Android RuntimeConnect/compat/secure-storage/streaming-upload/export/minimal-capability correct, remote auth/revoke/refresh secure, cross-device verified, migration fixtures pass, backup clean restore pass, upgrade-in-place pass, desktop/Android builds pass, emulator product flow pass, repo integrity + source manifest + Python 3.11/3.12 + native core + RAG + web + rust + security gates pass, tag SHA == artifact SHA, release-gate green, SHA256SUMS + SBOM/provenance + release verification generated.

### 6.1 Publication evidence integrity

The caller-side publication job must verify the downloaded `formal-release-assets`
bundle with `sha256sum -c SHA256SUMS.txt` before using any asset. After the
exact-SHA Stable Candidate proof is resolved, it appends the Candidate SHA/run,
final tag/tag SHA and Final Release run identity to
`Vx_y_RELEASE_VERIFICATION.md`, regenerates `SHA256SUMS.txt`, and verifies the
final checksum file again before attestation and publication. Stable Candidate
identity is `NOT APPLICABLE` for RC releases, never an inferred or fabricated
value.

## 7. External blockers (recorded honestly, never masked)

Official 1.0 desktop signing assets require credentials the Coding Agent cannot fabricate:

- Windows Authenticode certificate
- Apple Developer ID / notarization credentials

If absent: complete all source/workflow work, keep signing fail-closed, and report the blocker explicitly. Ad-hoc signatures must never be described as official signing.
