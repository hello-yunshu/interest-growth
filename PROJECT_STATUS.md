# Project Status

**Product:** Interest Growth
**Release branch:** `feat/v0.7-android-release-closure` → target **v1.0.0 Stable**
**Default Domain Pack:** Psychology
**Runtime:** Tauri 2 desktop shell + static Next.js/React + local Python/FastAPI Core
**Execution order:** Gate R0 (v0.7 Closure) → R1 (Product Completion) → R2 (Release Hardening) → R3 (1.0 RC) → R4 (1.0 Stable). See `Interest_Growth_v1.0.0_远程Actions完整推进与正式发布_总执行提示词.md`.

## Source candidate status

v0.6 Host integration is implemented. Product packaging/runtime verification is tracked separately:

- General Interest Core + Interest Areas: implemented;
- General + Psychology Domain Packs: implemented;
- Domain-scoped Skills/Personas/Mastery policy: implemented;
- neutral `core.interest-growth` / `capability.*` plugin namespace: implemented;
- migrations 8–12 and v0.4.1 legacy backfill: implemented;
- Area HTTP scoping and direct-ID guards: implemented;
- General LearningActivity/GroundingRef: implemented;
- Area capability composition: implemented;
- route-level PermissionBroker enforcement: implemented;
- Native-only product execution: implemented;
- v0.4/v0.4.1 desktop + Beautiful AI Interface boundaries: preserved.
- migration 11 native execution state: implemented;
- Host-owned native Knowledge Source parse/sync/rebuild/retrieve: implemented;
- native Tutor start/replay/resume/cancel with canonical Host Session/Turn: implemented;
- retired external tutor-runtime paths: removed with explicit schema migration;
- native DomainPolicy, Area capability and PermissionScope compilation: implemented.

## v0.7 implementation status (2026-08-14)

- Runtime/auth/version, threat, deployment, client and APK contracts: documented.
- Single-owner bootstrap/login, named device sessions, access/refresh tokens and per-device revocation: implemented with automated coverage.
- Atomic single-use refresh-token rotation (Gate B1): implemented and concurrency-tested.
- Database-enforced owner singleton (Gate B2): implemented via migration 14 and concurrency-tested.
- Maintenance/write lock for consistent DB + Source + Artifact backup (Gate B3): implemented and regression-tested.
- Staged rollback-safe restore (Gate B4): implemented and regression-tested across failure paths.
- Authenticated remote Compose profile: implemented as loopback HTTP; external Nginx and optional Caddy terminate client-facing TLS.
- DB + Source + Artifact backup/restore bundle tooling: implemented.
- Docker API/Web images: build and boot; health/capability/Web return 200 and an unauthenticated protected route returns 401.
- Gate B (B1–B4) is closed at the source-and-test gate level.
- Gate C ClientRuntime foundation: implemented — frozen `runtimeId` vocabulary, orthogonal platform adapters, connection state machine, SemVer/compatibility checks, URL normalization, runtime-scoped storage, secure credential boundary and retry policy under `apps/web/lib/runtime/`; Rust `runtime_mode.rs` decides `desktop-local`/`desktop-remote` with no sidecar spawn in remote mode; server instance identity (migration 15) implemented. Contract coverage: 59 JS pure tests, 39 Rust mode/remote-transport + broker integration tests, 6 server-identity tests.
- Gate D §D5–D7 desktop remote UX + native broker security closure: implemented at source level — runtime mode selection (This device / Self-hosted server), server enrollment, owner bootstrap, login/logout, device listing/revoke and connection status via `RuntimeConnect` on the System page; provider settings gated to desktop-local; data-location visual distinction; explicit restart boundary with no silent local/server merge. Active/pending runtime separated (data location follows the active runtime only); connection state machine drives the transport (terminal-state mutations fail closed); native broker blocks redirects, strips renderer-supplied dangerous headers via a positive allowlist, bounds uploads, single-flights refresh with credential-persistence recovery, verifies identity before sending credentials and reports truthful logout revoke results. Real public-TLS-server enrollment and real packaged Windows/macOS regression remain to be exercised.
- Gate C/D final closure round (2026-08-14, last recorded round): all remaining HIGH/MEDIUM/P11 findings of the prior audit are closed with directed tests — a business 401 truly forces a refresh (the rejected access credential is never reused even when locally unexpired; generation-based single flight makes 20 concurrent 401s share exactly one rotation and exactly one retry); restart with a stored refresh credential is NOT LoginExpired (`auth_expired` only after an explicit server denial, with an automatic native recovery attempt at startup); credentials are only sent after a FRESH native probe (TOCTOU closed; probe results are display cache only); server metadata is parsed strictly fail-closed (missing/empty/malformed fields → PROTOCOL_ERROR); connection state has ONE source of truth (`ConnectionStateMachine.subscribe()`, `RuntimeConnect` no longer keeps a second verdict); native remote commands are gated to the active desktop-remote runtime with a frozen HTTP method allowlist; refresh rotation survives keyring failure AND a crash (durable pending + active two-slot keyring, legacy key name kept for exact migration compatibility); session writes never `try_lock`; response metadata headers (etag/last-modified) reach the renderer through the safe allowlist; Offline is recoverable; every remote error carries a stable code (`NETWORK_UNAVAILABLE`/`LOGIN_EXPIRED`/`IDENTITY_CHANGED`/`UPDATE_REQUIRED`/`UNSUPPORTED_SERVER`/`CREDENTIAL_PERSISTENCE_FAILURE`/`PROTOCOL_ERROR`/`RUNTIME_MODE_DENIED`/`INTERNAL_ERROR`) the renderer classifies, never guessing from message text.
- Gate E mobile adaptation contract: implemented at source level — frozen `PLATFORM_CAPABILITIES` vocabulary and a `DESKTOP_ONLY_CAPABILITIES` gate (sidecar, token, vaults, updater, window controls, provider secrets) asserted false on every non-desktop runtime; `android-remote` assigns the renewal credential to Android Keystore and declares document picker / share sheet / suspend-resume lifecycle / biometric unlock as planned adapters.
- Gate E Android runtime + secure store + lifecycle + network security (2026-08-15): implemented at source and compiled for the Android target. The Android shell is always `android-remote` (`runtime_mode::android_remote_mode()`, no sidecar, no desktop keyring/vaults/updater/window plugins, desktop-only plugins compiled out under `cfg(not(target_os="android"))`); the renewal credential uses the Android-Keystore-backed store (`AndroidKeystoreStore`, two-slot active/pending with the same per-server/per-device namespace and honest NoEntry-vs-backend classification as desktop); release Android network security is fail-closed (`network_security_config.xml`, `cleartextTrafficPermitted=false`, no trust-anchor override). `aarch64-linux-android` release build compiles (`tauri android build --apk --target aarch64`).
- Android toolchain + signed release APK (Gates E/F): established a persistent Docker Android build environment (JDK 17, Android SDK 36/NDK 27, Rust Android targets, cargo-ndk, Tauri CLI 2.11.4, Tencent/rsproxy mirrors, persisted Gradle/Cargo volumes). A **signed universal release APK** is produced (`app-universal-release.apk`, arm64-v8a, 25 MB, APK Signature Scheme v2, cert SHA-256 `66871e86…aa66f`, APK SHA-256 `01ce82e4…92024`); APK hygiene checked (no Python sidecar, no secrets, no bootstrap token, no desktop updater, single canonical `.so` per ABI).
- Android emulator / physical device / upgrade-in-place / cross-device proof (Gates E–F–G): **NOT RUN** — no Android emulator image and no physical device are available in the current environment; these remain an explicit hardware boundary and must not be inferred as PASS. Real public-TLS-server enrollment and packaged desktop regression also remain to be exercised.
- 2026-08-15 regression: 66 ClientRuntime JS tests (contract) + controller tests passed (`node --test lib/runtime/test/*.test.mjs`), 52 Rust host tests passed (`cargo test` — runtime-mode, remote broker, credential-store classification, version parser, connection state, Android namespace), `aarch64-linux-android` release build compiled and the signed APK passed `apksigner verify --verbose --print-certs` (v2).

## v1.0 — Gate R0 (v0.7 Closure) execution (2026-08-16)

Source closure for the R0 release gates, up to commit `cc1add3`:

- **R0 §4 desktop-local startup regression fixed**: `remote.rs` resolves an appropriate remote broker runtime ID even for `desktop-local` (`broker_expected_runtime_id`), so Tauri setup survives while native remote commands remain gated by `ensure_remote_mode`. This closed the packaged desktop-local startup crash.
- **R0.5/R0.6 Android streaming upload/export**: file/directory uploading and Artifact download/export moved from renderer base64 materialization to bounded file-backed streaming over SAF handles (`android_bridge.rs`), eliminating the 100 MiB renderer base64 path and keeping binary integrity for text/PDF/ZIP/image.
- **R0 Android lifecycle + navigation**: real Android Back handling (WebView history) and foreground/background/resume with session re-evaluation on resume (`MainActivity.kt`).
- **R0.7/R0.8 Android minimal capability scope**: minimized Android capabilities and app-owned FileProvider scope.
- **R0 §4 packaged desktop-local startup smoke CI**: added `scripts/ci/verify_packaged_startup.sh` and wired it into `build-artifacts.yml` for both **Windows x64** and **macOS arm64** bundles (app process survives startup + `psychology-growth-core` sidecar spawned). Binary paths use the Cargo package name (`interest-growth-desktop`).
- **Release hardening**: `release.yml` dropped the debug APK from release assets and added tag→SHA binding; `SOURCE_MANIFEST.sha256` regenerated.

### Remote GitHub Actions evidence (head `cc1add3f94a3ccd4c97a3895ff58ed8001f41dd3`)

- **CI** — run `31897145932`: **success**.
- **Build Artifacts** — run `31897145902`: **success**, including `Packaged desktop-local startup smoke (Windows)` and `Packaged desktop-local startup smoke (macOS)` both **success** (sidecar health verified).

**R0 exit criteria met**: packaged desktop-local startup is verified on Windows + macOS in clean remote Actions. Remaining to R1: emulator product-flow evidence (hardware/toolchain boundary, see Gate R1).

## v1.0 — Gate R1 (Product Completion + Web/UX) execution (2026-08-16)

Remote Actions evidence at head `f52cfff`:

- **CI** — run `31899835437`: **success**. `verify.py` runs pytest from the repo root, so the new R1 product-loop suite (`tests/integration/test_gate_r1_product_loops.py`, 10 tests) is collected and executed remotely: growth feedback (returned/claim.revised events, no streak metrics), weekly review narrative, unreviewed-retrieval-candidate cannot be evidence, invalidated-evidence downgrade, claim version/citation provenance, all curiosity energy modes, question-without-research promotion, Content Studio human-review gate (export blocked → approve → export OK), and a general photography journey across curiosity/research/learning/growth/content without Psychology entities.
- **Web E2E (UX closure)** — run `31899835432`: **success**. Playwright over 8 core pages × 4 viewports (360×800 / 390×844 / 768×1024 / 1440×900): no horizontal overflow, axe-core (wcag2a/2aa/21a/21aa) no critical/serious violations, and network-unavailable error state renders without white screen / raw stack trace.
- **Build Artifacts** — run `31899835417`: **success**.

**R1 exit criteria met**: P0–P4 product-loop gaps closed and verified remotely; Web/UX closure gate (responsive + accessibility + error states) green in clean remote Actions. Per the master prompt, the Android emulator real vertical slice is a **Gate R2** item (see §10.2), not an R1 gate.

Normative execution status and next order live in `docs/audits/V0_7_IMPLEMENTATION_AUDIT.md` and `docs/roadmap/V0_7_SELF_HOSTED_CROSS_DEVICE_PLAN.md`.

## v1.0 — Gate R2 (Release Hardening) execution (2026-08-16)

Source + remote Actions closure for the R2 release gates, at branch tip `f197079` (PR #6 → main):

- **§9.1–§9.5 Data/Migration hardening**: frozen migration fixtures + idempotency, downgrade policy, clean create→destroy→clean→restore→migrate→verify→smoke backup/restore (`scripts/ci/verify_docker_integration.sh` + `tests/security/test_backup_restore.py`), and fail-closed corruption/failure paths — committed `d89f061` (supply-chain/APK gates), `5631b9c`, `ccb6fee`, `1d6a448`.
- **§16 Provider contract over a deterministic mock server**: `tests/contracts/test_provider_mock_server_contract.py` (13 tests) covers chat/completion, streaming, timeout, rate limit, auth, malformed and structured output across both `OpenAICompatibleClient` and `DeepSeekProvider` transports, so CI never depends on a live LLM service — committed `b9fcd83`.
- **§17 API/Schema freeze**: `scripts/verify_version_consistency.py` enforces a single version source (pyproject 0.7.0) across server/client/API/backup-format and is wired into `verify.py`; normative `docs/releases/V1_0_RELEASE_CRITERIA.md` + `docs/roadmap/V1_0_PLAN.md` committed `b9fcd83`.
- **§15 Observability/error recovery**: `apps/web/lib/runtime/test/error-code-taxonomy.test.mjs` freezes the 10 user-facing error codes from the release criteria and their stable connection-event (retry) mapping; INTERNAL_ERROR stays a non-terminal catch-all; unknown/fuzzy payloads stay retryable transport failures — committed `2c9eedc`. Server security events already assert never-storing credentials (`test_security_events_never_store_credentials`).
- **§14 Reliability soak**: `tests/security/test_remote_auth_soak.py` — 40-round atomic refresh rotations (single live credential per device), sequential revokes never leaking into survivors, repeated engine-reset restarts preserving owner/devices/live tokens, and three backup→destroy→restore cycles with stable server identity — committed `38fd534`.
- SOURCE_MANIFEST regenerated (`f197079`).

### Remote GitHub Actions evidence (branch tip `f197079`)

- **CI** — run `31913347228`: **success** (includes version-consistency check + full pytest + new §14/§16 suites).
- **Build Artifacts** — run `31913347170`: **success** (Windows x64 + macOS arm64 packages, sidecar smoke).
- **Web E2E (UX closure)** — run `31913347230`: **success**.

**R2 exit criteria**: §14–§17 committed and green in clean remote Actions on the branch. Full release matrix (docker-integration, Android emulator, cross-device, APK audit) runs at the RC/Stable tag via `release.yml`.

## Verified source/runtime facts

- frozen v0.5 Host archive: exact SHA-256 verified, **246 files**, original **104 tests PASS**;
- merged Host/native regression suite: **234 tests PASS**;
- standalone Native Execution Core verification: **97 tests PASS**;
- reviewed exact RAG API smoke: LlamaIndex 0.14, LightRAG 1.5, GraphRAG 3.1 and PageIndex 0.1.3 PASS;
- compileall: PASS;
- self-audit: PASS;
- Web ESLint and production static build: PASS (**15 static pages**);
- browser product flow: PASS (Home, System, Tutor and Research expose Native Core + optional DeepSeek only; retired runtime visible-text hits: 0);
- Rust `cargo check --locked`: PASS in the working tree and exact re-extracted source archive;
- macOS Apple Silicon `.app` + DMG: built locally; DMG checksum and the app copied from the mounted DMG pass strict ad-hoc `codesign` verification;
- packaged desktop launch: PASS; current packaged sidecar health/token smoke is PASS;
- Web JS/MJS syntax: **20 files / 0 parse failures**;
- config parse: **6 JSON / 26 YAML / 2 TOML / 1 plist**, all PASS;
- fresh DB includes 2 Domain Packs, 1 default Psychology Area, scoped Personas and migrations 1–15;
- real desktop Core smoke: health 200, protected runtime without token 401, correct token 200;
- exact real v0.4.1→v0.5 migration: representative legacy rows preserved and bound to default Psychology Area; legacy plugin state copied to neutral ID.
- ClientRuntime contract tests (Node built-in runner): **59 PASS** (descriptors, compatibility, SemVer, URL normalization, connection state machine, storage namespace, credential store, retry safety, remote transport with connection-state guards, positive header allowlist, upload bounds, coded error-code classification, Offline recovery, machine subscribe, response-header passthrough, Gate E mobile capability vocabulary + desktop-only gate) + **7 PASS** runtime-connect-controller reducer tests;
- Rust runtime-mode + remote-transport + native broker integration tests: **44 PASS** (`cargo test --locked --lib`) — runtime-mode decisions (default/explicit desktop-local, desktop-remote never spawns sidecar, invalid profile never switches store, active/pending separation, provider admin gating, remote-command runtime gate) plus deterministic native broker tests against an in-memory server: redirects never followed (login/refresh/bootstrap secrets stay local), compatibility rejects (wrong product/API version/min-client/runtime mode/auth), strict metadata parsing fails closed (missing/empty/malformed fields → PROTOCOL_ERROR), identity before credentials (mismatched instance id blocks before any secret is sent; login identity-swap refused), 401-recovery (forced rotation of a locally-valid rejected token, exactly one refresh + one retry, 20 concurrent 401s share one rotation), two-slot keyring crash recovery (restart reads the durable pending slot; both-write failure stages in memory), restart lifecycle (`auth_expired` only after a server denial), HTTP method allowlist (CONNECT/TRACE rejected), truthful logout revoke results, header positive allowlist and bounded uploads;
- server instance identity: **6 PASS** (fresh single identity, restart unchanged, second server distinct, migration 15 upgrade once, singleton index, display-name env);
- Gate C desktop-local compatibility: existing install defaults to desktop-local; sidecar, App Data, DB, keyring and provider settings unchanged;
- Gate C CSP/capabilities audit: no relaxation to arbitrary HTTPS/`connect-src *` introduced;
- Gate D §D5–D7 source UX: `RuntimeConnect` compiles and lints (runtime mode selection, enrollment, login/logout, device management, connection status); System page provider settings gated to desktop-local; remote data location visually distinct in the desktop shell.
- SOURCE_MANIFEST integrity: `scripts/generate_source_manifest.py` deterministically renders the product manifest (376 tracked files, excluding the standalone Native Core subtree); `scripts/verify.py` checks it in CI, so tracked-source drift fails the Host gate. Regenerated 2026-08-14 after the native-broker/web runtime closure changes.

Release packaging follows a strict external verification process: generate the ZIP from a clean frozen commit, UTF-8-safe re-extract it, then rerun every available gate. The exact archive result is recorded outside the source package in the release verification report so the frozen package does not contain a self-referential archive-status claim.

## Native binary gate

The local Apple Silicon application and DMG are verified development/test artifacts. Developer ID signing, Apple notarization and real Windows Setup validation remain target-OS/toolchain/credential dependent and must never be inferred from the local ad-hoc signature.

## Compatibility identifiers intentionally retained

The following remain migration anchors, not current product branding:

- `app.psychologygrowth.desktop`
- `psychology_growth.db`
- `psychology-growth-core`
- Docker Compose legacy volume key `psychology_data`
