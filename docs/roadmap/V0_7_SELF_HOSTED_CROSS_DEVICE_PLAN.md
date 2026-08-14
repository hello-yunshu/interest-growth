# Interest Growth v0.7 — Self-hosted Cross-device Development Plan

## Goal

Add a secure single-owner Docker server mode and an Android remote client while preserving the current Windows/macOS local-sidecar product. Distribute Android directly as APK; do not make Google Play or AAB part of the release definition.

## Gate A — Contract and threat model

- [x] Freeze `desktop-local`, `desktop-remote`, `android-remote` and optional `browser-remote` semantics. → `docs/architecture/V0_7_RUNTIME_CONTRACT.md`
- [x] Define API/server compatibility metadata and minimum supported client version behavior. → `GET /api/system/capabilities` contract in `V0_7_RUNTIME_CONTRACT.md`
- [x] Define the single-owner/device-session threat model, credential storage and revocation. → `docs/security/V0_7_REMOTE_THREAT_MODEL.md`
- [x] Define LAN/VPN/public-Internet deployment profiles and TLS requirements. → `V0_7_REMOTE_THREAT_MODEL.md` §6 + remote Compose profile
- [x] Define consistent DB + Source + Artifact backup/restore. → `docs/operations/V0_7_BACKUP_RESTORE.md`
- [x] Record offline sync, multi-user SaaS and Google Play as non-goals.

## Gate B — Authenticated self-hosted Core

- [x] Add owner bootstrap/login without creating an open public-registration path.
- [x] Add named device sessions, short-lived access credentials, renewal rotation and per-device revocation.
- [x] Protect all non-health HTTP and WebSocket routes.
- [x] Keep authentication separate from Interest Area and PermissionBroker checks.
- [x] Move remote provider administration/secrets to server-owned surfaces.
- [x] Add request/upload limits, safe security events and brute-force/rate controls.
- [x] Add an authenticated remote Compose profile on loopback HTTP, plus external Nginx and optional Caddy TLS-edge examples.

### Gate B verification (2026-08-13)

- [x] Full suite 121 passed (baseline 95 + 26 new auth/backup tests); desktop runtime + contract tests 24 passed; native execution core 64 passed; self-audit PASS; compileall PASS.
- [x] Docker: remote profile boots with `PG_REMOTE_AUTH_ENABLED=true`; `/api/system/capabilities` public; protected routes 401; owner bootstrap → login → device session → authed dashboard 200; refresh rotation; refresh-token reuse rejected; per-device revoke; device listing.
- [x] Docker backup/restore: bundle created with DB+sources+artifacts manifest, verify-only PASS, fresh-dir restore with FK/schema checks.
- [x] TLS boundary: client-facing TLS terminates at the reverse proxy; trusted proxy-to-Docker HTTP is supported. Optional Caddy was exercised with an internal CA/HSTS; external Nginx is the documented default example.
- [ ] Real-device boundary not verified (no Android device/emulator, no real public hostname/TLS cert, no desktop packages).

### Gate B audit follow-ups (2026-08-13)

- [x] Make refresh-token consumption and replacement one atomic transaction and add a concurrent replay test.
- [x] Enforce the one-owner invariant in the database so concurrent bootstrap requests cannot create multiple owners.
- [x] Require a quiesced backup window now, then add an application maintenance/write lock before advertising online consistent backup.
- [x] Stage restore into temporary paths and retain rollback state until migrations and smoke checks pass.
- [ ] Integrate and test device authentication on each real WebSocket route when one is introduced; the current source has only an authentication helper and no active WebSocket endpoint.

Gate C starts after the security/data-consistency items above are closed or explicitly accepted as release blockers.

## Gate C — ClientRuntime refactor

- [x] Replace the every-Tauri-is-desktop assumption with an explicit runtime/platform adapter.
- [x] Centralize API base URL, auth headers, WebSocket auth/reconnect, export and external links.
- [x] Add enrolled-server identity and server-version state.
- [x] Replace local-only error copy in remote mode.
- [x] Add secure native credential storage; do not use `localStorage` for renewal credentials.
- [x] Give CSP/capabilities the minimum platform-specific remote origin and permissions.

### Gate C verification (2026-08-13, refreshed 2026-08-14)

- [x] ClientRuntime pure contract tests (Node built-in runner): 59 passed (descriptors, compatibility, SemVer, URL normalization, connection state machine, storage namespace, credential store, retry safety, remote transport with connection-state guards, positive header allowlist, upload bounds, coded error-code classification, Offline recovery, machine subscribe, response-header passthrough, Gate E mobile capability vocabulary + desktop-only gate); plus 7 runtime-connect-controller reducer tests.
- [x] Rust runtime-mode + remote-transport + native broker integration tests: 44 passed (`cargo test --locked --lib`), covering default desktop-local, explicit desktop-local, desktop-remote never spawns sidecar, invalid profile never switches store, active/pending runtime separation, provider-admin gating, remote-command runtime gate, id validation, enrollment-origin normalization/validation, refresh-key namespace isolation, plus deterministic broker tests (redirects never followed, compatibility rejects, strict fail-closed metadata parsing, identity before credentials with login identity-swap refusal, 401-recovery with forced rotation and generation-based single flight, two-slot keyring crash recovery, restart lifecycle, HTTP method allowlist, truthful logout revoke, header positive allowlist, bounded uploads).
- [x] Server instance identity: 6 tests passed (fresh single identity, restart unchanged, second server distinct, migration 15 upgrade once, singleton index, display-name env).
- [x] Main Python suite: 244 passed, including Gate B security/concurrency regressions; Native Execution Core standalone: 98 passed.
- [x] Web ESLint and static production build: passed; Host verify, Native Core mirror sync, self-audit and strict Host cutover audit: passed; SOURCE_MANIFEST integrity check: PASS.
- [x] Desktop-local compatibility: existing install defaults to desktop-local; sidecar behavior, App Data, DB, keyring and provider settings unchanged.
- [x] Desktop-remote decision: explicit runtime mode never spawns the sidecar; no silent fallback to a local store; remote failure maps to Offline/LoginExpired/IdentityChanged with mutations disabled.
- [x] Browser remote stays honest: cookie auth not implemented, so `browser-remote` remains a planned/not-release-proven adapter skeleton; no refresh token in `localStorage`.
- [x] Gate D §D5–D7 UX source: `RuntimeConnect` (mode selection, server enrollment, owner bootstrap, login/logout, device listing/revoke, connection status) integrated into the System page; provider settings gated to desktop-local; data-location visual distinction in the desktop shell; explicit restart boundary with no silent local/server merge.
- [x] Gate D final closure round (2026-08-14): business 401 forces a refresh (never reuses the rejected credential even when locally unexpired; generation-based coalescing, exactly one rotation + one retry under 20 concurrent 401s); restart with a stored refresh is NOT LoginExpired (`auth_expired` only after an explicit server denial; automatic native recovery attempt at startup); credentials are sent only after a FRESH native probe (stale-authorization cache closed; probe results are display cache only; TLS/PKI is the endpoint cryptographic identity and `server_instance_id` is application-instance continuity, §4.9); strict fail-closed metadata parsing; single connection-state source of truth via machine `subscribe()`; remote commands gated to active desktop-remote with a frozen HTTP method allowlist; two-slot keyring crash recovery; async session writes; response metadata header passthrough; Offline recoverable; stable error-code taxonomy both sides; refresh 429/5xx classified as transient (not LoginExpired); remote env fails closed unless remote auth enabled.
- [ ] Real desktop remote UX against a real public TLS host, real Windows/macOS package regression and real remote-server runtime: not done (Gate D finish).

## Gate D — Desktop remote mode

- [x] Add explicit local-device versus self-hosted-server selection (source UX in `RuntimeConnect`).
- [x] Add remote enrollment/login/logout/device revocation UX (source UX in `RuntimeConnect`).
- [x] Keep server data visually distinguishable from local-device data (data-location labels + status dot; provider settings hidden in remote mode).
- [x] Define explicit runtime switch boundary; mode changes persist the NEXT profile, require an explicit restart and never silently merge local and server stores.
- [ ] Preserve existing loopback sidecar startup, token rotation, App Data and provider keyring behavior under a real packaged Windows/macOS regression.
- [ ] Verify Windows/macOS local mode has no regression on real packages.
- [ ] Exercise enrollment/login against a real public TLS host and remote-server runtime.

### Gate C/D decision (2026-08-14)

The execution prompt's §5 release-safety acceptance list was run end-to-end
and every item passed (see `docs/audits/V0_7_IMPLEMENTATION_AUDIT.md` §2 "Gate
C/D §5 release-safety acceptance"): 248 Python, 66 ClientRuntime JS, 51 Rust,
web lint/build, self-audit and SOURCE_MANIFEST all green. Therefore:

```text
Gate C = PASS (source/test)
Gate D = PASS (source/test)
```

Still NOT release-proven (blocks Gate D release-proven status only): real
public-TLS enrollment/login and real packaged Windows/macOS regression, which
require hardware/package execution not present on this build machine.

## Gate E — Android application

### Source-level contract (2026-08-14)

- [x] Define the mobile adaptation contract: `android-remote` runtime
      descriptor with a frozen mobile capability vocabulary (no sidecar, no
      desktop token, no local vaults, no desktop updater, no window controls;
      Android Keystore for the renewal credential; document picker / share
      sheet / system browser / suspend-resume lifecycle as planned adapters).
- [x] Add a desktop-only gate inventory: the Rust surface that must be gated
      when the Android target is initialized — sidecar spawn, updater,
      single-instance, window-state and the OS-keyring provider/credential
      commands — is recorded in the runtime contract so a mobile build cannot
      silently pull in a desktop/local path.

### Toolchain work (2026-08-15, provisioned via Docker)

The host machine still has no native JDK/Android SDK/emulator, but a
persistent Docker build environment now provides the full Android toolchain:
image `interest-growth-android` (linux/amd64) with JDK 17, Android SDK 36 +
NDK 27.1, the Rust `aarch64-linux-android` target, cargo-ndk and
`@tauri-apps/cli` 2.11.4, built against Tencent/rsproxy mirrors with persisted
`ig-gradle-cache` / `ig-cargo-home` volumes and invoked through
`scripts/android-docker.sh`. There is still **no emulator image and no
physical device** in this environment; emulator/device execution is an
explicit boundary, not an inferred pass.

- [x] Initialize the Tauri Android project and mobile entry point.
- [x] Gate sidecar, updater, single-instance, window-state and desktop-only
      credential code behind the Android target; the Android shell is always
      `android-remote` (`runtime_mode::android_remote_mode()`) and desktop-only
      plugins are compiled out under `cfg(not(target_os="android"))`.
- [x] Select mobile-supported secure storage (Android Keystore via
      `android-native-keyring-store`) and lifecycle implementations; document
      picker / share sheet / biometric unlock remain planned adapters.
- [x] Implement remote server enrollment and authentication on Android
      (reuses the hardened native remote broker; refresh credential encrypted
      in the Android Keystore store, never in the renderer).
- [~] Narrow-screen navigation, system Back, keyboard/insets, touch and
      suspend/resume behavior: source wired (mobile entry point +
      suspend/resume recovery); NOT verified on a running device.
- [~] Uploads / downloads-exports / Tutor WebSocket reconnect / external
      links: reuse the runtime-aware remote transport; NOT exercised on a
      running device.
- [ ] Test emulator plus at least one physical Android device (no emulator
      image / device available in this environment; Gate E source/compile is
      PASS, hardware execution is NOT RUN).

## Gate F — Direct APK release

Status (2026-08-15): a **signed universal release APK** is produced and
signature-verified; the release keystore and installation guide exist.
Upgrade-in-place and hardware installation remain NOT RUN (no device/emulator
in this environment).

- [x] Produce a debug APK for internal/ADB testing (`app-universal-debug.apk`).
- [x] Generate and securely back up a project-owned release keystore outside Git
      (`~/Documents/GitHub/interest-growth-keystore`, mounted read-only into the
      build container; passwords via gitignored `keystore.properties` /
      `PG_ANDROID_*` env vars — nothing in Gradle tracked source).
- [x] Build a release APK signed with that key; no Google Play/AAB dependency.
- [x] Record application ID (`app.psychologygrowth.desktop`), version name
      `0.7.0`, version code `7000` and signing-certificate fingerprint
      (`66871e86…aa66f`) — see `docs/audits/V0_7_ANDROID_APK_RELEASE_VERIFICATION.md`.
- [x] Publish SHA-256 checksum and a concise installation/update guide —
      `docs/android/ANDROID_INSTALL_GUIDE.md` (checksum
      `01ce82e4…92024`).
- [ ] Install the first release on hardware, then prove a higher-version APK
      signed by the same key upgrades in place (NOT RUN — no device/emulator).
- [ ] Recheck current Android developer-verification/sideload rules before broad
      handoff and choose an explicit path (documented in the install guide;
      decision still pending hardware validation).

## Gate G — Cross-device and recovery proof

No cross-device or recovery evidence exists: no second client has run on
hardware and no clean-deployment restore has been exercised on hardware. The
Android `android-remote` runtime is implemented and compiled (see Gate E), so
a Client A = desktop-remote + Client B = android-remote matrix is ready to be
exercised once an Android device/emulator and a real server are available.

- [ ] Mutate representative canonical data on one client and verify it on desktop and Android.
- [ ] Exercise Area isolation, Evidence/Claim review, Tutor resume and Artifact download across clients.
- [ ] Revoke one device without breaking other sessions.
- [ ] Verify authentication expiry/recovery and incompatible-server behavior.
- [ ] Back up the complete server data unit, restore it into a clean deployment and run integrity smoke tests.
- [x] Run existing compile/test/self-audit gates and add remote/Android contract tests (66 ClientRuntime JS + controller tests and 52 Rust host tests, including the Android `android-remote` runtime-mode and per-server/per-device credential-namespace coverage).

## Deferred

- offline mutation/sync and conflict resolution;
- public registration, organizations and multi-tenancy;
- PostgreSQL/object-storage migration;
- Android Python sidecar/local canonical database;
- Play Store/AAB publication and store-managed updates;
- automatic desktop-local to server merge;
- broad third-party executable plugins.

## Release evidence

The final handoff must separately state source implementation, automated tests, Docker verification, desktop package verification, emulator verification, real-device verification, APK signing/checksum and backup/restore proof. Missing hardware or signing evidence remains an explicit boundary, not an inferred pass.
