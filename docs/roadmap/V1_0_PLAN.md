# Interest Growth v1.0.0 — Release Plan

> **Status:** normative Gate R2 §17 (API/Schema Freeze) artifact.
> **Scope:** from the current `feat/v0.7-android-release-closure` branch to **v1.0.0 Stable**, gated entirely by remote GitHub Actions clean-runner evidence. Local runs are debug evidence only.

## Execution order (frozen, do not reorder)

```
R0 v0.7 closure        → DONE (see PROJECT_STATUS §Gate R0)
R1 product completion  → DONE (see PROJECT_STATUS §Gate R1)
R2 release hardening   → IN PROGRESS (this document tracks it)
main PR + merge
v1.0.0-rc.1 tag        → full remote Actions
independent audit
fix if needed → next RC
v1.0.0 tag             → full remote Actions
sign + verify
release-gate
publish GitHub Release
final audit / report
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
| 14.1 | Reliability soak (refresh/revoke loop, repeated restart, backup/restore repeat) | `tests/security/test_remote_auth_soak.py` (new) | committed, CI host gate |
| 14.2 | Concurrency (single-flight refresh, owner singleton, backup lock) | existing + soak | committed |
| 14.4 | Android upload: no full base64 copy | android_bridge.rs + test | committed |
| 15 | Observability: structured server logs, no credential logging, frozen error codes, user-facing stable code + retry guidance | error-code taxonomy test (new) + remote.js | committed, CI host gate |
| 16 | Provider contract over deterministic mock server (chat/stream/timeout/rate-limit/malformed/unavailable) | `tests/contracts/test_provider_mock_server_contract.py` | committed, CI host gate |
| 17 | API/Schema freeze: version single-source consistency + `V1_0_RELEASE_CRITERIA.md` + `V1_0_PLAN.md` | `scripts/verify_version_consistency.py` + this doc | committed, CI host gate |

## Remaining work queue (current, in order)

1. Commit §16 provider-contract test (skip the .md prompt files — never commit the prompt).
2. §17: version-consistency check wired into `verify.py`; release docs (this pair).
3. §15: error-code taxonomy frozen regression test (10 required codes + no-credential-leak) and structured-logging no-secret assertion.
4. §14: soak tests — multi-round refresh/revoke, backup/restore repeat, restart recovery.
5. Push → remote CI + docker-integration + build-artifacts.
6. Main PR → merge → v1.0.0-rc.1 tag → full RC Actions → independent audit.
7. v1.0.0 tag → full Stable Actions → sign/verify → release-gate → publish.

## Definition of done (summary)

Stable requires: `BLOCKER = 0`, `HIGH = 0`, RC + Stable tag Actions green, Android signed + emulator product flow, server remote integration + clean backup/restore, desktop packages built, cross-device verified, migration fixtures verified, release docs complete (see `docs/releases/V1_0_RELEASE_CRITERIA.md`).
