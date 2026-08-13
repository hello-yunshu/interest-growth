# Interest Growth v0.7 — Implementation Audit

**Audit date:** 2026-08-14
**Scope:** authenticated self-hosted Core, Docker/proxy deployment, backup/restore, desktop/Android readiness and recorded verification.

## 1. Outcome

Gate A is documented. Gate B (B1–B4) is implemented and regression-tested as
of this audit, so Gate B is closed at the source-and-test gate level. Gate C
(ClientRuntime foundation) is implemented and regression-tested at the
source-and-test gate level. Gate D (desktop remote mode) is implemented at the
source-and-test gate level (§D5–D7 UX plus the native remote broker), but it
is NOT release-proven: no enrollment/login has been exercised against a real
public-TLS server and no real packaged Windows/macOS regression has run.
Android (Gate E), direct APK release (Gate F) and cross-device proof (Gate G)
remain not started at the hardware/toolchain level: no Android project or
mobile Rust entry point exists and no real remote server or second client has
been exercised. Gate E's source-level mobile capability contract is
implemented as vocabulary only (see §2).

The four concurrency/recovery boundaries that previously blocked Gate B are
now closed (see §4): atomic refresh-token rotation, database-enforced owner
singleton, cross-component backup consistency, and rollback-safe restore.

## 2. Implemented in source

- Single-owner bootstrap/login and named device records.
- Short-lived access credentials, rotated renewal credentials and per-device
  revocation.
- Atomic single-use refresh-token rotation (Gate B1).
- Database-enforced single-owner invariant (Gate B2).
- Maintenance/write lock coordinating DB + Source + Artifact mutations with
  online backup (Gate B3).
- Staged, rollback-safe restore that retains the previous live state until
  post-restore checks succeed (Gate B4).
- Remote-mode HTTP authentication middleware kept separate from Interest Area
  and PermissionBroker authorization.
- Public health/capability/server metadata endpoints.
- DB + Source + Artifact backup bundle, checksums, verification and restore
  smoke checks.
- Remote Docker API/Web profile on loopback HTTP.
- External Nginx TLS-edge example and optional bundled Caddy overlay.
- Static Next.js export packaged in an Nginx Web image.

### Gate C — ClientRuntime foundation

- `apps/web/lib/runtime/` ClientRuntime vocabulary: frozen `runtimeId`
  (`desktop-local`/`desktop-remote`/`android-remote`/`browser-remote`),
  orthogonal `platform` ids, `dataLocation`, runtime descriptors with
  platform capabilities, connection state machine, compatibility checker,
  SemVer, URL normalization, storage namespace and credential store.
- `api.js` remains the compatibility facade for feature pages; internal
  requests now route through `getClientRuntime()` → `runtime.transport`, so
  feature pages no longer branch on `isTauri()`.
- `isTauri()` is confined to the low-level `lib/runtime/platform.js`; feature
  and API logic consume the resolved runtime descriptor instead.
- Rust `runtime_mode.rs`: explicit runtime profile → `RuntimeMode` decision;
  `desktop-remote` never spawns the sidecar, existing installs default to
  `desktop-local`, invalid profiles never switch to another canonical store.
- Server instance identity: stable `server_instance_id` (migration 15,
  additive singleton row), `server_display_name`, exposed additively on
  capabilities/server-info/login responses, preserved across restart and
  backup/restore.
- Secure credential boundary: `CredentialStore` interface with an in-memory
  test adapter; renewal credentials never enter the renderer and no
  `localStorage` refresh-token path exists.
- Runtime-scoped UI cache: Area preference and disposable presentation cache
  are namespaced per runtime/server (`interest-growth.<namespace>.current-area`).
- Runtime-aware user copy: hardcoded “本机/本地” labels replaced by labels
  derived from the runtime descriptor, so a future remote mode never claims
  data is stored on this device.
- WebSocket abstraction with loopback-only query token; remote bearer tokens
  are never placed in a URL query and remote WebSocket transport is
  explicitly `not active`.
- CSP/capabilities audited: `tauri.conf.json` CSP and the Tauri capabilities
  manifest keep `connect-src` limited to loopback/IPC and were not relaxed to
  arbitrary HTTPS or `connect-src *`; remote traffic stays on the native
  broker transport (see §5).

### Gate D — Desktop remote mode (source + tests)

- `RuntimeConnect` on the System page: runtime-mode selection (This device /
  Self-hosted server), server enrollment with URL normalization, owner
  bootstrap, login/logout, device listing/revoke and connection status.
- Native remote credential broker (`remote.rs`): the renewal credential is
  stored in the OS keyring keyed by `server_instance_id` + `device_id`,
  rotated on refresh, and never exposed to the renderer; the HTTP transport
  accepts only relative API paths from the renderer and never an absolute URL
  or a renderer-supplied `Authorization` header.
- Explicit restart boundary: a mode switch persists the NEXT profile and
  applies only after an explicit `restart_app`; a remote session never
  silently falls back to a local store.
- Provider administration is gated to `desktop-local`; the desktop shell
  shows a data-location status dot so server data is visually distinct from
  local-device data and remote copy never claims data is stored on this
  device.
- The remote transport stays inert without the native broker; bearer/refresh
  credentials never enter the renderer and no `localStorage` refresh path
  exists.

### Gate E — Android mobile contract (source vocabulary only)

- Frozen `PLATFORM_CAPABILITIES` vocabulary and a `DESKTOP_ONLY_CAPABILITIES`
  gate in `apps/web/lib/runtime/contract.js`; descriptor tests assert every
  non-desktop runtime keeps every desktop-only capability false, so a mobile
  build cannot silently reach a desktop/local path.
- `android-remote` assigns the renewal credential to Android Keystore and
  declares document picker / share sheet / suspend-resume lifecycle / optional
  biometric unlock as planned adapters. These are contract vocabulary, not
  implemented surfaces; no Android project, emulator or device exists.

## 3. Verified in this audit

- Main Python suite: 244 passed (Host, includes the Gate B security and
  concurrency regression tests and the Gate C client-runtime/server-identity
  tests).
- Native Execution Core standalone package: 98 passed.
- ClientRuntime pure contract tests (Node built-in runner): 45 passed
  (descriptors, compatibility, SemVer, URL normalization, connection state
  machine, storage namespace, credential store, retry safety, remote
  transport, Gate E mobile capability vocabulary + desktop-only gate).
- Rust runtime-mode + remote-transport source tests: 12 passed
  (`cargo test --locked --lib`), covering default desktop-local, explicit
  desktop-local, desktop-remote never spawns sidecar, invalid profile never
  switches store, id validation, enrollment-origin normalization/validation
  and refresh-key namespace isolation.
- Server instance identity: 6 passed (fresh single identity, restart
  unchanged, second server distinct, migration 15 upgrade once, singleton
  index, display-name env).
- Gate B1 concurrent refresh rotation: two overlapping refreshes yield
  exactly one success and one failure; a single valid replacement chain remains.
- Gate B2 owner bootstrap race and singleton migration: tested on fresh and
  legacy databases.
- Gate B3 backup consistency and B4 rollback-safe restore: concurrent writes
  blocked during backup; torn/corrupt bundles fail before touching live state;
  every restore failure path retains the previous live state.
- Python compileall and self-audit: passed.
- Web ESLint and static production build: passed.
- Rust `cargo check --locked`: passed.
- API and Web Docker images: built successfully.
- Docker build context reduced from about 1.04 GB to 868 KB (API) and 407 KB
  (Web) after adding `.dockerignore`.
- Running loopback containers: health 200, capabilities 200, Web 200 and an
  unauthenticated protected route 401.
- Forwarded HTTPS scheme: `/api/auth/server-info` reported `tls: true` when
  reached through trusted proxy metadata.

The containers and temporary audit credential file were stopped/removed after
verification. The real external hostname/certificate path was not exercised.

### 2026-08-14 full regression and toolchain boundary (Gates C–E source, F/G)

- Web: `npm run lint` passed; ClientRuntime contract tests 45 passed; static
  production build passed.
- Rust: `cargo test --locked --lib` 12 passed (compile of the lib doubles as
  `cargo check --locked --lib`).
- Main Python suite: 244 passed. Native Execution Core standalone verify: PASS.
- Host gates: `scripts/verify.py` PASS (version check synced from 0.6.0 to
  0.7.0, matching the v0.7 project version), `verify_native_core_sync.py`
  IN SYNC, `self_audit.py` PASS, `audit_public_repo.py` PASS (432 tracked
  paths), strict `audit_host_v050.py . --strict` PASS
  (`ready_for_native_cutover: true`).
- Android toolchain inventory checked 2026-08-14: no Java/JDK (`keytool`
  unavailable), no Android SDK (`ANDROID_HOME` unset), no Rust Android
  targets, no `cargo-ndk`, no `adb`, no emulator or physical device. Gates E
  (hardware), F and G remain not started at the toolchain level.

## 4. Gate B status (was "Open release blockers")

The four Gate B boundaries from the previous audit are now closed:

### B1 — Atomic renewal-token rotation — CLOSED

`device_refresh` consumes the old credential with a single conditional
`UPDATE ... WHERE revoked_at IS NULL AND expires_at > now` and only issues a
replacement when exactly one row is matched; consumption and replacement are
in the same transaction. A concurrent replay regression test asserts exactly
one success and one failure leave a single valid replacement chain.

### B2 — Database-enforced single owner — CLOSED

`auth_owners` carries a `singleton` marker guarded by a unique partial index
(migration 14, additive; existing owners preserved). Concurrent bootstrap
races surface as a unique-conflict `409 already configured` instead of `500`.

### B3 — Cross-component backup consistency — CLOSED

A maintenance/write lock (in-process reader/writer gate plus cross-process
advisory flock) coordinates an exclusive backup/restore span against shared
vault mutations on the DB, Source and Artifact paths. Backup also rejects any
snapshot that references a file missing from the bundle. A concurrent-write
regression test passes.

### B4 — Rollback-safe restore — CLOSED

Restore stages and fully verifies the bundle on temporary paths (migrations,
integrity, file-reference checks) before switching the live DB and vault
directories. The previous live state is retained as `*.pre-restore-<ts>` until
post-switch checks pass, then cleaned up; every simulated failure (corrupt
archive, checksum mismatch, migration failure, smoke failure, post-switch
failure) leaves the original live state recoverable.

## 5. Verified boundaries, not completion claims

- Gate D UX is implemented at source level and the native remote broker is
  covered by Rust unit tests, but no real public-TLS server session and no
  real packaged Windows/macOS regression has exercised it.
- No active application WebSocket route exists; `websocket_device_auth` is a
  helper with a unit test, not runtime WebSocket authentication proof.
- The desktop Rust source compiles, but the local DMG attempt failed in
  `bundle_dmg.sh`; no new desktop package is handed off by this audit.
- No `src-tauri/gen/android` project, `mobile_entry_point`, Android secure
  storage, emulator run, physical-device run or APK exists (Gates E–F not
  started).
- Cross-device continuity has not been exercised with two independent clients
  (Gate G not started).
- No real public hostname, valid public certificate or external Nginx runtime
  was exercised; only the loopback upstream contract and forwarded scheme were
  verified.

## 6. Required next order

1. Gate C `ClientRuntime` is implemented and regression-tested; the
   every-Tauri-is-desktop coupling is removed from feature pages.
2. Gate D desktop remote mode is implemented at source level (§D5–D7) with a
   native remote broker and explicit restart boundary; the next step is to
   exercise it against a real public-TLS server and run a real packaged
   Windows/macOS local + remote regression.
3. Initialize and target-gate Tauri Android (Gate E), reusing the mobile
   capability contract; gate sidecar, updater, single-instance, window-state
   and desktop-only credential code.
4. Verify emulator, physical device, signed APK upgrade and cross-device data
   (Gates F–G).

Release reporting must continue to separate source implementation, automated
tests, Docker runtime, desktop packages, emulator, physical Android hardware,
APK signing/checksum and real external TLS evidence.
