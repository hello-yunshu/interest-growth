# Changelog

All notable changes to the public package are recorded here. This file does
not invent commit history for unpublished work.

## 1.0.3 — v1.0.3 Stable target (2026-08-21)

**Status**: pending remote Actions verification (single unified Stable matrix,
see `Interest_Growth_最终稳定版_v1.0.1_最终统一Actions验收_完整执行提示词.md`).

`v1.0.1` and `v1.0.2` were never published (no GitHub Release was created), so
per the immutable-tag governance the fixes below ship as the next patch `1.0.3`.

**Fixes over the v1.0.1 tag SHA**:
- Android `x86_64` Rust compile fix — `__system_property_get` buffer must be
  typed `[c_char; 92]` (matches the `*mut c_char` signature on every Android
  target; `c_char` is `u8` on `aarch64` but `i8` on `x86_64`).
- Deterministic packaged-binary resolver — the macOS main app is resolved from
  `bundle/macos/<App>.app/Contents/MacOS/<CFBundleExecutable>` and hidden Cargo
  metadata is excluded, so startup smoke can no longer launch the Python
  sidecar or a build helper quasicom.
- **Production security fix** — `CiFlags.kt` no longer leaks WebView remote
  debugging: `ENABLE_WEBVIEW_REMOTE_DEBUGGING` is `false`, so the published
  production APK and normal builds always disable it (the `true` default was
  an internal test artifact flag and is confined to the throwaway x86_64
  emulator APK).
- Version bump `1.0.2 → 1.0.3` with `MIN_CLIENT_VERSION` kept at `1.0.0`
  (patch release, no protocol/API break); Android `versionCode` advanced to
  `1000005` (monotonic; `1000004` is skipped — versionCode must not contain
  the digit `4`).

## 1.0.2 — (unpublished)

Never published. Android `versionCode` was advanced to `1000003` but a
production security defect (CiFlags.kt `ENABLE_WEBVIEW_REMOTE_DEBUGGING=true`)
was found before any release created; all fixes ship in `1.0.3`.

## 1.0.1 — v1.0.1 Stable (2026-08-20)

**Status**: Stable closure merged into `main` at `422c0f1` (PR #14). Version
bump `1.0.0 → 1.0.1`; `MIN_CLIENT_VERSION` remains `1.0.0` (patch release, no
protocol/API break). All remote Actions gates green on the merged main.

**Android hardening (§6)**:
- fail-closed byte upload on Android (`byteUploadAllowed=false`; the upload
  throws before `file.arrayBuffer()`);
- immutable `getDesktopRuntimeMode()` on Android; `setDesktopRuntimeMode()`
  rejects;
- fresh-install resume resolves to `RESET` (sessionStatus-first pure
  `resumeSessionDecision()`);
- plugin surface cfg-gated per `target_os`; updater / runtime-mode commands
  reject on Android; capability-surface audit test added.

**Release pipeline**:
- `gh release create --verify-tag` + explicit tag→SHA fail-closed binding;
- `server-bundle` job (`interest-growth-server-<version>.tar.gz`);
- Windows/macOS/server assets attached to the release; single `SHA256SUMS.txt`
  over exactly the attached assets (debug APK never included);
- actionlint pinned to an immutable image digest.

**Android**: `versionCode` `1000001 → 1000002` (monotonic, gate-checked).

## 1.0.0 — v1.0.0-rc.1 (2026-08-17)

**Published**: v1.0.0 release candidate 1, prerelease, at
https://github.com/hello-yunshu/interest-growth/releases with a signed
Android arm64 APK, SPDX SBOM, SHA256SUMS and a verification report.

**Release evidence**: GitHub Actions run `32000632965` — all gates PASS on
the tag commit (`877734d`, tag SHA == build SHA): repository integrity,
Python host, Web/ClientRuntime, Rust, Docker integration, dependency
security, **Android signed release APK + static verification** (signing
keystore secrets now configured; APK Signature Scheme v2), and the **Android
emulator real remote vertical slice** (login → … → logout_revoke, all
`ok=true`, `result=PASS`), then publish.

### 1.0 highlights

- **Native-only product execution** — Interest Growth Native Core is the sole
  workflow runtime; Host DB remains the only canonical product truth; DeepSeek
  / OpenAI-compatible providers are model transport only.
- **General Interest Core** — curiosity → research/evidence/claim → learning →
  growth → optional expression journeys work without Psychology entities.
- **Research / Evidence / Claim** — human-review gate, claim version history,
  citation provenance, invalidated-evidence downgrade.
- **Learning / Practice / Mastery** — accepted-progression only; AI never
  auto-promotes Mastery.
- **Content Studio** — human-review gate before export; no auto-publish.
- **Self-hosted server** — single-owner bootstrap, named device sessions,
  atomic single-use refresh rotation, per-device revocation, consistent
  DB+Source+Artifact backup/restore with fail-closed corruption handling.
- **Cross-device ClientRuntime** — desktop-local / desktop-remote /
  android-remote with a frozen runtime vocabulary, secure credential
  boundaries and a stable remote error taxonomy.
- **Android remote client** — streaming/SAF upload, artifact export/download,
  minimal capability scope, Keystore-backed renewal credential, fail-closed
  network security.
- **Release pipeline** — remote Actions as the only release evidence:
  migration fixtures, clean backup/restore, provider-contract mock server,
  version/schema freeze, reliability soak, Windows/macOS packages, Android
  emulator + signed APK gates.

### 0.7 development

- Optional self-hosted single-owner Docker server used by Windows, macOS and
  Android clients (additive mode; local-first desktop contract preserved).
- Gates B1–B4: atomic refresh rotation, DB-enforced owner singleton,
  maintenance/write-locked consistent backup, staged rollback-safe restore.
- Gate C ClientRuntime: frozen `runtimeId` vocabulary, orthogonal platform
  adapters, connection state machine, SemVer/compatibility checks, secure
  credential boundary.
- Gate D: desktop remote UX + native broker security closure.
- Gate E: Android runtime, Keystore store, lifecycle, minimal capability scope.
- Server instance identity and schema migrations 13–15.

## 0.6.0-rc2 — 2026-08-12

- Restored the reviewed v0.3 Tutor, RAG, Skill, writing, and reconnect
  invariants in the General Interest architecture.
- Added the native execution architecture while preserving Host canonical data
  ownership.
- Removed DeepTutor as a runtime requirement and retained it only as a reviewed
  compatibility reference.
- Enforced exact-adapter semantics for legacy third-party RAG engine IDs.
- Added public repository hygiene, security, contribution, and reproducible CI
  gates for Python 3.11 and 3.12.
