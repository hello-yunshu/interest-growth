# Interest Growth v1.0.0 — Release Plan

> **Status:** normative Gate R2 §17 (API/Schema Freeze) artifact.
> **Scope:** from the current `feat/v0.7-android-release-closure` branch to **v1.0.0 Stable**, gated entirely by remote GitHub Actions clean-runner evidence. Local runs are debug evidence only.

## Execution order (frozen, do not reorder)

```
R0 v0.7 closure        → DONE (see PROJECT_STATUS §Gate R0)
R1 product completion  → DONE (see PROJECT_STATUS §Gate R1)
R2 release hardening   → DONE (see PROJECT_STATUS §Gate R2)
main PR + merge        → DONE (PR #6 → main `4aea601`)
v1.0.0-rc.1 tag        → DONE (`877734d`); full RC Actions SUCCESS (run `32000632965`)
independent audit      → DONE (BLOCKER=0, HIGH=0)
signing secrets        → DONE (self-signed keystore configured; fail-closed sign gate PASS)
RC1 published          → DONE (prerelease; signed APK + SPDX + SHA256SUMS + verification report)
independent audit RC2  → DONE (HIGH-1/2/3 + credential/reliability/supply-chain MEDIUMs in `c6e3b7a`)
v1.0.0-rc.2            → FAILED (run `32014725731`; APK+emulator gate) — UI/IPC smoke driver not invoked; never published
v1.0.0-rc.3            → DONE (`ab2cfc4`, tag `v1.0.0-rc.3`); full RC Actions SUCCESS (run `32016776864`, 18/18 jobs), android UI/IPC smoke PASS, published prerelease
soak / review          → next
v1.0.0 tag             → pending (after RC soak/review; non-prerelease)
sign + verify          → pending (Android keystore ready; Windows/macOS remain external blockers)
release-gate           → pending
publish GitHub Release → pending
final audit / report   → pending
```

## R2 — Release Hardening tracking

The plan below is the normative R2 checklist. Each row records the artifact and its remote Actions evidence (run ID + SHA) once proven. Rows without a run are NOT done.

| § | Item | Artifact | Remote evidence |
|---|---|---|---|
| 9.1 | Migration fixtures (frozen v0.4.1→v0.7) | `tests/migrations/*` + fixtures | committed, CI host gate |
| 9.2 | Migration idempotency | migration tests | committed, CI host gate |
| 9.3 | Downgrade policy (backup before upgrade, no downgrade) | docs + tests | committed |
| 9.4 | Backup/restore clean (create → destroy → clean → restore → migrate → verify → smoke) | `scripts/ci/verify_docker_integration.sh` + `tests/security/test_backup_restore.py` | committed; docker-integration run |
| 9.5 | Corruption/failure fail-closed (missing file, checksum, schema failure, torn bundle) | `test_backup_restore.py` | committed, CI host gate |
| 10.1 | Actions remote server vertical slice | docker-integration + release | run |
| 10.2 | Android emulator real remote vertical slice | `emulator-e2e.yml` / `release.yml android-emulator` | run |
| 10.3 | Physical Android policy (CI emulator normative; physical = post-release field) | release-criteria | documented here |
| 10.4 | Cross-device (A create → B read, revoke, backup/restore) | cross-device job | run |
| 11.1 | Windows x64 installer + smoke + checksum | `build-artifacts.yml windows-build` | run |
| 11.2 | macOS arm64 .app/DMG + audit | `build-artifacts.yml macos-build` | run |
| 12.1 | Actions pinning + permissions | `ci.yml`/`release.yml` | committed, actionlint |
| 12.2 | Dependency security (pip/npm/cargo) | `security-dependency` job | run |
| 12.3 | Secret scan | repo-integrity + audit scripts | committed |
| 12.4 | SBOM | release job SPDX | run at release |
| 12.5 | Provenance | attest-build-provenance | run at release |
| 13.1 | Android APK audit (aapt required, fail-closed) | `scripts/ci/verify_android_apk.sh --require-aapt` | run |
| 13.4 | Server bundle (compose, env example, backup/restore tools) | release assets | run at release |
| 14.1 | Reliability soak (refresh/revoke loop, repeated restart, backup/restore repeat) | `tests/security/test_remote_auth_soak.py` | committed `38fd534` |
| 14.2 | Concurrency (single-flight refresh, owner singleton, backup lock) | existing + soak | committed |
| 14.4 | Android upload: no full base64 copy | android_bridge.rs + test | committed |
| 15 | Observability: structured server logs, no credential logging, frozen error codes, user-facing stable code + retry guidance | `apps/web/lib/runtime/test/error-code-taxonomy.test.mjs` + remote.js | committed `2c9eedc`, CI host gate |
| 16 | Provider contract over deterministic mock server (chat/stream/timeout/rate-limit/malformed/unavailable) | `tests/contracts/test_provider_mock_server_contract.py` | committed `b9fcd83`, CI host gate |
| 17 | API/Schema freeze: version single-source consistency + `V1_0_RELEASE_CRITERIA.md` + `V1_0_PLAN.md` | `scripts/verify_version_consistency.py` + this doc | committed `b9fcd83`, CI host gate |

## Remaining work queue (current, in order)

1. Push → remote CI + docker-integration + build-artifacts.
2. Main PR → merge → v1.0.0-rc.1 tag → full RC Actions → independent audit.
3. v1.0.0 tag → full Stable Actions → sign/verify → release-gate → publish.

## Definition of done (summary)

Stable requires: `BLOCKER = 0`, `HIGH = 0`, RC + Stable tag Actions green, Android signed + emulator product flow, server remote integration + clean backup/restore, desktop packages built, cross-device verified, migration fixtures verified, release docs complete (see `docs/releases/V1_0_RELEASE_CRITERIA.md`).
