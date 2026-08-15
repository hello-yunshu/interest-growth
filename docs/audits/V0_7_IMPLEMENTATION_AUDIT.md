# Interest Growth v0.7 — Implementation Audit

**Audit dates:** 2026-08-14 (Gate C/D closure rounds) / 2026-08-15 (Android Gate E/F round)
**Scope:** authenticated self-hosted Core, Docker/proxy deployment, backup/restore, desktop/Android readiness and recorded verification.

## 1. Outcome

Gate A is documented. Gate B (B1–B4) is implemented and regression-tested as
of this audit, so Gate B is closed at the source-and-test gate level. Gate C
(ClientRuntime foundation) is implemented and regression-tested at the
source-and-test gate level. Gate D (desktop remote mode) is implemented at the
source-and-test gate level (§D5–D7 UX plus the native remote broker), but it
is NOT release-proven: no enrollment/login has been exercised against a real
public-TLS server and no real packaged Windows/macOS regression has run.
Gate E (Android) is implemented at source and **compiled** for
`aarch64-linux-android`, and a v2-signed release APK exists (Gate F signing
half), but no emulator / physical-device run and no upgrade-in-place has been
executed; Gate G (cross-device proof) remains not started. The per-round
history below records what was true on each audit date (2026-08-14 and
2026-08-15).

The four concurrency/recovery boundaries that previously blocked Gate B are
now closed (see §4): atomic refresh-token rotation, database-enforced owner
singleton, cross-component backup consistency, and rollback-safe restore.

On 2026-08-14 the Gate C/D runtime loop was closed end-to-end (see §2 "Gate
C/D security closure"): identity/compatibility/credential/connection-state
now sit in the real credential-bearing native broker path, backed by 59
ClientRuntime JS tests and 39 Rust runtime-mode + deterministic broker
integration tests, with remote CI green. Gate C and Gate D remain HOLD only
for real-runtime evidence (public-TLS enrollment and packaged Windows/macOS
regression), not for missing source/test security closure. Gate E
(Android) remains NOT READY for engineering entry: the mobile capability
contract is vocabulary only and no Android toolchain/hardware exists on the
build machine.

On 2026-08-14 the final Gate C/D closure round (this audit's last recorded
round) closed the remaining HIGH/MEDIUM/P11 findings of the previous audit
(see §2 "Gate C/D final closure round"): the client now genuinely recovers
from a business 401 (forced rotation, never a locally-unexpired reuse), the
restart lifecycle no longer misreads "enrolled + refresh stored + not yet
connected" as LoginExpired, every credential send is preceded by a FRESH
native probe (no probe cache is ever reused as a credential-send
authorization), server metadata is parsed fail-closed, connection state has a
single source of truth, native remote commands are gated to the active
desktop-remote runtime with a frozen HTTP method allowlist, refresh rotation
survives keyring write failure and even a crash (two-slot durable pending +
active keyring slots), session writes are never `try_lock`, response
metadata headers reach the renderer through the safe allowlist, Offline is
recoverable, and every remote failure carries a stable error code the
renderer classifies instead of guessing from message text. Rust integration
tests grew to 44 and ClientRuntime JS tests to 59; the full regression
(244+ Python, 59 JS, 44 Rust, native-core verify, RAG upstream pin, web
lint/build, strict host audit, SOURCE_MANIFEST integrity) is green in the
same environment.

On 2026-08-14 the Gate C/D §5 acceptance list was executed end-to-end and
every item passed (see §2 "Gate C/D §5 release-safety acceptance"): refresh
429/5xx classified as transient (not LoginExpired), remote `APP_ENV`
fail-closed invariant, version overflow fail-closed parsing, honest secure
store total-failure reporting, keyring read backend-failure classification,
direct remote actions driving the unified ConnectionStateMachine, bootstrap
redirect test genuinely entering the target path, directed 401-recovery and
20-concurrent-401 single-flight regressions, plus no
identity-before-credential / header-allowlist / upload-bound / redirect
regressions. Final counts in this run: 248 Python, 66 ClientRuntime JS, 51
Rust, web lint/build, self-audit and SOURCE_MANIFEST all green. Per the
execution prompt, this closes Gate C and Gate D at the source-and-test gate
level: **Gate C = PASS (source/test)** and **Gate D = PASS (source/test)**.
They remain not release-proven only for real-runtime evidence (public-TLS
enrollment and packaged Windows/macOS regression), which is an execution
boundary, not a source/test gap.

On 2026-08-15 the Android round was executed (this audit's latest recorded
round): a persistent Docker Android build environment was established, the
Tauri Android project was initialized with the mobile Rust entry point, the
Android runtime was implemented at source and **compiled** for the
`aarch64-linux-android` target (always `android-remote`, no sidecar, no
desktop keyring/vaults/updater/window plugins, Android-Keystore-backed
credential store, fail-closed network security), and a **signed universal
release APK** was produced and signature-verified (v2) with a project-owned
keystore held outside the repository. Therefore **Gate E = source + compile
PASS**, and the APK/signing half of **Gate F (signing/checksum/fingerprint)
is PASS**. The following remain explicit NOT RUN hardware boundaries, not
inferred passes: Android emulator run, physical-device install/runtime,
upgrade-in-place, cross-device proof (Gate G) and real public-TLS enrollment
on Android (see §2 "2026-08-15 Android round" and §5).

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

### Gate C/D security closure (2026-08-14, this round)

The runtime loop was closed end-to-end so the security contracts actually sit
in the credential-bearing product path:

- **Active/pending runtime separation** (`runtime-connect-controller.js` pure
  reducer): the current runtime is immutable per session, a mode switch
  persists the NEXT profile, and the data-location label reflects only the
  active runtime. Tests cover persist-pending-keeps-active + restart-applies.
- **Connection state machine drives the transport** (`remote.js`): mutations
  fail closed in terminal states (Offline/LoginExpired/IdentityChanged/
  UpdateRequired/UnsupportedServer/LocalCoreError); identity-changed blocks
  mutations even while reads still work; a final 401 after single-flight
  refresh maps to LoginExpired. No silent fallback to a local store exists.
- **Native remote broker hardening** (`remote.rs`, deterministic integration
  tests against an in-memory server): `redirect::Policy::none()` so
  login/refresh/bootstrap secrets never reach a redirect target; a positive
  header allowlist strips renderer-supplied dangerous headers such as
  `Authorization`; uploads are bounded before and after base64 decode;
  refresh is single-flighted so concurrent callers share exactly one refresh,
  and a rotated token is staged in memory when keyring persistence fails so
  the only valid credential is not lost; identity is verified before any
  credential is sent (mismatched `server_instance_id` blocks); logout reports
  the truthful revoke result (local removed vs server revoke confirmed).
- **SOURCE_MANIFEST identity closure**: `scripts/generate_source_manifest.py`
  deterministically renders the product manifest (376 tracked files,
  excluding the standalone Native Core subtree) and `scripts/verify.py`
  fails the Host gate when the committed manifest drifts from the tracked
  tree, replacing the previous "existing but untrusted" manifest.
- **Truthful capability vocabulary** (Gate E contract only): capability
  descriptors distinguish `supportedByContract` from `implemented`; every
  non-desktop runtime keeps `canLaunchSidecar`/`canUseDesktopToken`/
  `canAdminLocalProviderSecret`/`canUseDesktopUpdater`/
  `supportsWindowControls` false so no UI can enable a non-existent mobile
  surface.
- **Honest boundaries retained**: `browser-remote` secure-cookie session is
  `NOT IMPLEMENTED` (no refresh/access token in `localStorage`); remote
  WebSocket transport remains contract-only/inactive (no active application
  WebSocket route exists); no CSP relaxation to arbitrary HTTPS was
  introduced.

### Gate C/D final closure round (2026-08-14, this audit's last round)

The findings below were recorded in the prior audit and are CLOSED in this
round, each with directed tests that uniquely trigger the fixed path:

- **HIGH — a 401 must genuinely force a refresh** (`remote.rs`): a business
  401 now goes through `refresh_after_401`, which compares the access
  GENERATION the request was sent with against the current one. If another
  caller already rotated, its newer access credential is reused (single
  flight); otherwise the rejected credential is FORCE-rotated even when it is
  still locally unexpired, then the original request is retried exactly once.
  A second 401 is LoginExpired. Directed tests: locally-valid token rejected
  → exactly 1 forced refresh + exactly 1 retry; 20 concurrent 401s →
  exactly 1 rotation shared by generation coalescing.
- **HIGH — restart with a stored refresh is NOT LoginExpired** (`remote.rs` +
  `client-runtime.js`): `auth_expired` is now set ONLY when the server
  explicitly denied the refresh credential (`refresh_denied` flag, cleared on
  login/logout/successful refresh). On startup, "enrolled + refresh stored +
  not connected" triggers an automatic native refresh attempt that maps to
  Connected / LoginExpired / IdentityChanged / offline honestly. Directed
  test: fresh broker over a stored credential reports `auth_expired: false`;
  a server denial flips it to true.
- **HIGH — credentials are only sent after a FRESH probe** (TOCTOU closure,
  `remote.rs`): the `PendingEnrollment` probe cache was removed; login and
  bootstrap call `fresh_verified_server()` inside the same call that sends
  the credential, so a server that was replaced while a stale probe result was
  cached is detected before the credential leaves the process. Directed test:
  probe answers instance-A, login endpoint answers instance-B → refused with
  IDENTITY_CHANGED and nothing persisted. Scope note (Gate C/D §4.9): this
  closes the stale-cache window; it does not claim to remove every theoretical
  TOCTOU between the fresh metadata GET and the login POST. Endpoint
  cryptographic identity is the TLS certificate/PKI; `server_instance_id` is
  an application-instance continuity identity, not a substitute for TLS.
- **HIGH — fail-closed protocol parsing** (`remote.rs`): `ParsedMetadata`
  with `unwrap_or_default` was replaced by strictly-typed parsers for the two
  frozen metadata endpoints. Every required field (including
  `auth.owner_configured` on both endpoints, `runtime_modes`, `tls`,
  `online_first`, `offline_sync`) must be present and correctly typed;
  versions must be numeric dotted; the two endpoints must agree on all shared
  fields or the probe fails with PROTOCOL_ERROR. No field ever defaults open.
- **HIGH — single connection-state source of truth** (`RuntimeConnect.js`):
  the component no longer derives its own verdict from status fields; it
  mirrors the `ConnectionStateMachine` through its new `subscribe()` API and
  only ever feeds it events from user actions (login/refresh/verify/logout).
  The transport also drives the machine from coded error verdicts instead of
  a blanket network-fail guess.
- **HIGH — native remote commands are runtime-gated** (`remote.rs`): every
  remote command except the public probe now requires the ACTIVE
  `desktop-remote` runtime mode (`ensure_remote_mode`, coded
  RUNTIME_MODE_DENIED), and `api_request` only accepts the frozen HTTP method
  allowlist (GET/HEAD/OPTIONS/POST/PUT/PATCH/DELETE) — CONNECT/TRACE/arbitrary
  strings never reach reqwest. The renderer is not treated as a security
  boundary.
- **MEDIUM — refresh rotation crash recovery** (`remote.rs`): the keyring
  store now has two slots per server/device — a durable PENDING slot and the
  ACTIVE slot (which keeps the legacy keyring key for exact migration
  compatibility). Rotation writes pending first, promotes, then clears; a
  crash between the two leaves the replacement readable from pending; only if
  BOTH slots fail is the replacement staged in memory for the session.
  Directed tests: active-write failure keeps pending readable by a restarted
  broker; both-write failure stages in memory and still rotates.
- **MEDIUM — session writes never `try_lock`** (`remote.rs`): `set_session`
  is now async and always awaits the session mutex; every write bumps a
  generation counter that powers the 401 coalescing above.
- **MEDIUM — response metadata headers reach the renderer**
  (`remote.rs` + `remote.js`): the native broker surfaces its safe response
  header allowlist (`etag`/`last-modified`) and `responseFromNative` copies
  them onto the fetch-compatible `Response`, so caching behaves like a normal
  HTTP client.
- **MEDIUM — Offline is recoverable** (`connection-state.js`): Offline left
  the terminal set; it is the bounded-retry resting state and a later
  `RECONNECT_OK`/`BOOTSTRAP_OK` recovers it. Mutations still fail closed
  outside Connected.
- **P11 — stable remote error codes** (`remote.rs` + `remote.js`): every
  native error is `{"code": ..., "message": ...}` with a frozen taxonomy
  (NETWORK_UNAVAILABLE, LOGIN_EXPIRED, IDENTITY_CHANGED, UPDATE_REQUIRED,
  UNSUPPORTED_SERVER, CREDENTIAL_PERSISTENCE_FAILURE, PROTOCOL_ERROR,
  RUNTIME_MODE_DENIED, INTERNAL_ERROR). The renderer classifies via
  `parseRemoteErrorCode`/`remoteErrorEvent`; server verdicts become their
  honest terminal states and ambiguous failures stay recoverable network
  failures. Errors never contain passwords or tokens.

### Gate C/D §5 release-safety acceptance (2026-08-14, executed end-to-end)

Every item on the execution prompt's §5 acceptance list was run and passed:

- **refresh 429/5xx not misclassified as LoginExpired** — directed Rust tests
  `refresh_429_is_not_login_expired_and_recovers` and
  `refresh_503_is_not_login_expired`; only 401/403 flip `auth_expired`.
- **remote `APP_ENV` fail-closed** — `packages/shared/pg_shared/settings.py`
  raises `ConfigError` when `APP_ENV=remote` but
  `PG_REMOTE_AUTH_ENABLED != true`; no unauthenticated remote API can start.
- **version overflow fail-closed** — `remote.rs` `ParsedVersion` rejects
  malformed and overflowing components instead of defaulting open; directed
  test `version_parser_accepts_valid_and_rejects_malformed_or_overflowing`.
- **secure store total failure not misclaimed crash-safe** — `rotate_refresh`
  returns `Result` and reports `CREDENTIAL_PERSISTENCE_FAILURE` when every
  keyring slot fails; tests `rotation_stages_in_memory_when_every_slot_fails`
  and `refresh_rotation_survives_keyring_write_failure`.
- **keyring read backend failure correctly classified** — `NoEntry` (no
  credential) is distinct from locked/unavailable backend failures, so a
  locked keychain never triggers a false login prompt.
- **direct remote actions drive the unified state** — `RuntimeConnect.js`
  routes every native remote action through `runRemoteAction` →
  `ConnectionStateMachine`; JS tests assert coded verdicts are the single
  source of truth.
- **bootstrap redirect test genuinely enters the target path** — the directed
  test asserts the login endpoint receives the credential-bearing request and
  the redirect target receives zero requests; `login_never_follows_307_redirect_and_secret_stays_local`.
- **401 successful-recovery directed test** — business 401 forces a rotation
  and exactly one retry, then reconnects; `refresh_401_retries_exactly_once_then_login_expired`.
- **20-concurrent-401 single-flight remains green** — generation-based
  coalescing produces exactly one rotation + one retry; regression unchanged.
- **no redirect / identity-before-credential / header-allowlist /
  upload-bound regressions** — all prior invariants re-verified:
  `login_never_follows_307_redirect_and_secret_stays_local`,
  `renderer_dangerous_headers_are_stripped_by_positive_allowlist`,
  `upload_is_bounded_before_and_after_base64_decode`, and the
  identity-before-credential login-swap refusal test.
- **stable error-code taxonomy both sides** — Remote error codes frozen and
  mirrored in Rust (`remote.rs`) and JS (`remote.js`); mismatch fails tests.
- **Full gate regression green** — 248 Python, 66 ClientRuntime JS, 51 Rust,
  web lint/build, self-audit and regenerated SOURCE_MANIFEST.

Result: **Gate C = PASS (source/test)**, **Gate D = PASS (source/test)**;
release-proven status remains pending only real public-TLS + packaged
Windows/macOS evidence.

### Gate E — Android mobile contract (source vocabulary)

- Frozen `PLATFORM_CAPABILITIES` vocabulary and a `DESKTOP_ONLY_CAPABILITIES`
  gate in `apps/web/lib/runtime/contract.js`; descriptor tests assert every
  non-desktop runtime keeps every desktop-only capability false, so a mobile
  build cannot silently reach a desktop/local path.
- `android-remote` assigns the renewal credential to Android Keystore and
  declares document picker / share sheet / suspend-resume lifecycle / optional
  biometric unlock as planned adapters.

### 2026-08-15 Android round (implemented at source + compiled)

This round moved Android from "vocabulary only" to implemented at source and
compiled for the Android target, using a Docker build environment (see §3).
Each Gate E §6 item:

- **Android toolchain (Docker)**: `docker/` image `interest-growth-android`
  (linux/amd64, JDK 17, Android SDK 36 / NDK 27.1, Rust `aarch64-linux-android`
  target, cargo-ndk, Node + `@tauri-apps/cli` 2.11.4), built against Tencent
  SDK / rsproxy Rust mirrors with persisted `ig-gradle-cache` and
  `ig-cargo-home` volumes; invoked via `scripts/android-docker.sh`. The whole
  release build is driven through `npx tauri android build --apk` (keeps the
  CLI WebSocket server alive) to avoid the addr-file panic that occurs when
  `android-studio-script` runs without the CLI server.
- **§6.2 Tauri Android project + mobile entry point**: `src-tauri/gen/android`
  initialized; `lib.rs` uses `#[cfg_attr(mobile, tauri::mobile_entry_point)]`;
  `tauri.conf.json`/capabilities apply to the mobile build. The generated
  project is **tracked in full** (ADR 0008, Option A — see below), so a clean
  checkout is directly buildable with no generator re-run and no local
  symlink/path. `SOURCE_MANIFEST` covers every `gen/android` file (no
  exclusion added for it).
- **§6.3 Android runtime is always `android-remote`**: `runtime_mode.rs`
  exposes `RUNTIME_ID_ANDROID_REMOTE` and `android_remote_mode()`
  (`cfg(target_os = "android")`); `AndroidRemote` never spawns a sidecar,
  desktop keyring/vaults/updater/single-instance/window-state are compiled out
  under `cfg(not(target_os="android"))`; no desktop-only credential path is
  reachable.
- **§6.4 Android secure credential store**: `AndroidKeystoreStore` in
  `remote.rs` wraps `android-native-keyring-store` (Android Keystore-backed,
  hardware/OS key, encrypted refresh credential persisted to app-private
  SharedPreferences). It keeps the two-slot active/pending rotation semantics
  and the honest NoEntry-vs-backend classification of the desktop store; the
  renderer never sees the refresh credential.
- **§6.5 Android native remote broker**: reuses the hardened native remote
  broker (`remote.rs`) — relative-API-path-only, positive header allowlist,
  bounded uploads, redirect policy `none`, single-flight refresh, identity
  verified before credentials, stable error-code taxonomy.
- **§6.6 Android lifecycle**: mobile entry point + suspend/resume path wired;
  the remote session is recovered from the secure store on resume.
- **§6.7 Android network security (fail-closed)**: `res/xml/network_security_config.xml`
  with `cleartextTrafficPermitted=false` and system trust anchors only; no
  trust-anchor override and no `usesCleartextTraffic=true` in the manifest.
- **§6.8–§6.11 Android UX / upload / download / external links**: the mobile
  surface shares the runtime-aware Web UI; upload bounds and download/export
  reuse the remote transport (not separately exercised on hardware).
- **§6.12 Provider admin**: no local provider admin surface on Android; the
  `DESKTOP_ONLY_CAPABILITIES` gate keeps provider-secret commands off the
  mobile runtime.

Compile evidence: `aarch64-linux-android` release build succeeds
(`tauri android build --apk --target aarch64`). Emulator and physical-device
execution were not available in this environment and are NOT RUN.

### 2026-08-15 GitHub Actions / unique-trusted-build closure round (source + tests)

This round implements the "GitHub Actions unique trusted build" prompt
(`Interest_Growth_v0.7_GitHub_Actions_...执行提示词.md`) at the source,
script and workflow level. It does **not** claim remote-Actions evidence:
nothing in this round is PASS beyond what the local source/tests prove. The
distinction is kept explicit below.

- **BLOCKER-1 closed (source)**: the non-self-contained tracked wrapper
  `apps/desktop/src-tauri/tauri.js` (a copy of the CLI's `node_modules`
  wrapper) was removed from Git tracking; Tauri CLI is invoked via the repo
  package manager (`npx tauri`) everywhere. `scripts/audit_public_repo.py`
  gained tracked-symlink/path integrity checks: broken symlink, absolute
  target, target under `node_modules`, target escaping the repository and
  target resolving under `$HOME` all fail. `git ls-files` in a clean checkout
  must be fully readable. **Remote-clean-runner evidence NOT RUN.**
- **ADR 0008 — Android generated source tracking policy (Option A)**: the
  `gen/android` project is tracked in full; `SOURCE_MANIFEST` covers every
  tracked `gen/android` file (no exclusion added); audit proves manifest entry
  set == git tracked file set within scope, so `gen/android` cannot silently
  drift in/out. **Source + local manifest check; remote Actions NOT RUN.**
- **BLOCKER-2 closed (source)**: `android-remote` now resolves through the
  shared `resolveNativeRemote(runtimeId, platform, runtime, adapter)` resolver
  (extracted from the desktop-remote path) and activates a genuine native
  `RemoteTransport` with the Android adapter broker — it no longer falls into
  `inactiveRemoteTransport()`. Android never falls back to desktop-local and
  never exposes a desktop token/local authHeader; its storage namespace is
  `android-remote:<server_instance_id>` scoped. Covered by a new
  `runtime-android.test.mjs` suite (15 cases: active transport, no local
  fallback, no desktop token, storage namespace, native broker GET, mutation
  blocked while disconnected, 401→native refresh→exactly one retry,
  LoginExpired/IdentityChanged/UpdateRequired/UnsupportedServer mappings).
  **Source + 15 local Node tests; remote Actions NOT RUN.**
- **Android platform adapter** (`apps/web/lib/runtime/platforms/tauri-android.js`):
  native remote broker invocation, `openExternal`, lifecycle/suspend-resume
  notification hooks, and honest NOT IMPLEMENTED stubs for document selection,
  upload-by-URI, share sheet, back handling and biometric unlock. Capabilities
  stay `false` where unimplemented; nothing is claimed PASS on Android UX.
- **FileProvider tightened (§4 / prompt §4)**: `file_paths.xml` exposes only
  app-owned `cache-path export/` and `files-path share/`; no `external-path`,
  no `path="."`, no storage root, no canonical/credential/DB paths.
  `audit_public_repo.py` statically rejects any broadening.
- **Unified CI scripts** (`scripts/ci/`): `verify_repo.sh` (audit +
  manifest-scope gate) and `verify_android_apk.sh` (APK static
  metadata/content verification) are the single verification entry points
  reused by PR CI, main artifact builds and tag releases — there is no second,
  laxer verification path.
- **ci.yml updated**: added `repo-integrity` as a required leading gate,
  added Android runtime tests to the Web job (`node --test
  lib/runtime/test/*.test.mjs`), and added an `actionlint` job so the
  workflows themselves are syntax/schema-checked. **Remote Actions NOT RUN.**

## 3. Verified in this audit

- Main Python suite: 244 passed (Host, includes the Gate B security and
  concurrency regression tests and the Gate C client-runtime/server-identity
  tests).
- Native Execution Core standalone package: 98 passed.
- ClientRuntime pure contract tests (Node built-in runner): 59 passed
  (descriptors, compatibility, SemVer, URL normalization, connection state
  machine, storage namespace, credential store, retry safety, remote
  transport with connection-state guards, positive header allowlist, upload
  bounds, Gate E mobile capability vocabulary + desktop-only gate).
- Rust runtime-mode + remote-transport + native broker integration tests: 44
  passed (`cargo test --locked --lib`) — runtime-mode decisions (default and
  explicit desktop-local, desktop-remote never spawns sidecar, invalid
  profile never switches store, active/pending separation, provider-admin
  gating, remote-command runtime gate) plus deterministic native broker tests
  against an in-memory server: redirects never followed (login/refresh/
  bootstrap secrets stay local), compatibility rejects (wrong product/API
  version/min-client/runtime mode/auth), strict metadata parsing fails
  closed (missing/empty/malformed fields → PROTOCOL_ERROR), identity before
  credentials (mismatched instance id blocks before any secret is sent;
  login identity-swap between fresh probe and login refused), 401-recovery
  (forced rotation of a locally-valid rejected token, exactly one refresh and
  one retry; 20 concurrent 401s share exactly one rotation), two-slot keyring
  crash recovery (restart reads the pending slot; both-write failure stages
  in memory), restart lifecycle (`auth_expired` only after a server denial),
  HTTP method allowlist, truthful logout revoke results, header positive
  allowlist and bounded uploads.
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

- Web: `npm run lint` passed; ClientRuntime contract tests 59 passed
  (including Offline-recovery, machine `subscribe`, coded error-taxonomy
  classification and response-header passthrough) plus the 7
  runtime-connect-controller tests; static production build passed.
- Rust: `cargo test --locked --lib` 44 passed, including the deterministic
  native remote-broker integration tests (compile of the lib doubles as
  `cargo check --locked --lib`).
- Main Python suite: 244 passed. Native Execution Core standalone verify: PASS.
- Host gates: `scripts/verify.py` PASS (version check synced from 0.6.0 to
  0.7.0, matching the v0.7 project version; SOURCE_MANIFEST integrity check
  PASS — manifest regenerated for the changed native-broker/web files),
  `verify_native_core_sync.py`
  IN SYNC, `self_audit.py` PASS, `audit_public_repo.py` PASS (460 tracked
  paths), strict `audit_host_v050.py . --strict` PASS
  (`ready_for_native_cutover: true`). Reviewed RAG upstream pin re-verified:
  graphrag 3.1.0, lightrag-hku 1.5.6, llama-index-core 0.14.23, pageindex
  0.1.3.
- Android toolchain inventory checked 2026-08-14: no Java/JDK (`keytool`
  unavailable), no Android SDK (`ANDROID_HOME` unset), no Rust Android
  targets, no `cargo-ndk`, no `adb`, no emulator or physical device. Gates E
  (hardware), F and G remain not started at the toolchain level.
- **Android toolchain inventory checked 2026-08-15 (now provisioned via
  Docker)**: the host still lacks a native JDK/Android SDK/emulator, but the
  Docker image `interest-growth-android` (linux/amd64) provides JDK 17,
  Android SDK 36 + NDK 27.1, `aarch64-linux-android` Rust target, cargo-ndk
  and Tauri CLI 2.11.4, so Android compile/sign works without host toolchain
  changes. There is still **no emulator image and no physical device** in
  this environment; emulator/device execution remains NOT RUN.

### 2026-08-15 Android verification round

- ClientRuntime contract tests: **66 passed** (`node --test
  lib/runtime/test/*.test.mjs`), including the Android capability vocabulary
  and the `android-remote` runtime-mode contract, plus the
  runtime-connect-controller reducer tests.
- Rust host tests: **52 passed** (`cargo test`), covering runtime-mode
  decisions (`android-remote` never spawns a sidecar, `AndroidRemote` is not
  a desktop id), the remote broker integration tests, credential-store
  NoEntry-vs-backend classification, version parser, connection state and the
  Android per-server/per-device credential namespace.
- `aarch64-linux-android` **release compile PASS** via
  `npx tauri android build --apk --target aarch64` (the CLI WebSocket server
  stays alive through the Gradle rust build, so no addr-file panic).
- **Signed release APK produced** (Gate F §8.3): universal release APK,
  arm64-v8a single canonical `.so`, v2-signed with the project keystore
  (external to the repo); `apksigner verify --verbose --print-certs` PASS.
  Full identity/signing/hygiene in `docs/audits/V0_7_ANDROID_APK_RELEASE_VERIFICATION.md`.
- **APK hygiene (Gate F §8.5) PASS** (static): no Python sidecar, no provider
  secret / bootstrap token / release private key, no local DB seed, no
  desktop updater payload, no cleartext config; network security is
  fail-closed.
- **NOT RUN (hardware boundaries)**: emulator install/run, physical-device
  install/runtime, upgrade-in-place, cross-device proof, real public-TLS
  enrollment on Android.

### 2026-08-15 Phase 6 — manifest regeneration + local verification + workflow closure

Local verification re-run on the assembled branch (source-level only; remote
Actions evidence still NOT RUN — nothing here claims a remote run).

- **SOURCE_MANIFEST regenerated and verified**: `generate_source_manifest.py`
  wrote **435 entries**; `--check` PASS. Regenerated *after* staging the new
  workflow/script/ADR files so the manifest covers the full tracked set
  (`git ls-files` scope).
- **`verify_repo.sh` PASS**: `audit_public_repo.py` hygiene PASS (519 tracked
  paths, symlink/path/credential/FileProvider/manifest-scope checks) and
  `generate_source_manifest.py --check` PASS. The audit proves manifest entry
  set == git tracked file set within scope.
- **Web gate PASS**: `npm run lint` (0 warnings), ClientRuntime
  `node --test lib/runtime/test/*.test.mjs` → **81 passed / 0 failed**
  (includes the 15 `android-remote` native-transport tests), static
  production `npm run build` PASS.
- **Rust gate PASS**: `cargo test --locked --lib` → **52 passed / 0 failed**
  (runtime-mode, native broker, credential store, refresh/rotation, error
  taxonomy).
- **Python host suite**: not runnable on this host (missing `fastapi`/dev
  deps — no local venv); CI installs `.[dev]` in a clean runner. Local NOT
  RUN, not claimed PASS.
- **Docker integration gate**: script verified syntactically and structurally
  against the auth contract; a local run was attempted but the base-image
  pull failed on the configured mirror (`docker.mirrors.ustc.edu.cn` Bad
  Gateway — host network, not a script defect). Local NOT VERIFIED; must be
  exercised in Actions.
- **Workflow YAML parse PASS**: all four `workflows/*.yml` parse cleanly.
  Fixed two unquoted-colon YAML errors in `release.yml` (step names/runs
  containing `: `) that would have broken the workflow.
- **`release.yml` closure fixes**:
  - `release-gate` now also `needs: android-emulator` (emulator is a required
    release gate, prompt §31).
  - `android-signed-build` now generates `SHA256SUMS.txt` from the actual
    APKs and uploads it with the artifacts.
  - `publish-release` downloads the artifacts, regenerates `SHA256SUMS.txt`,
    and auto-generates `V0_7_RELEASE_VERIFICATION.md` via
    `generate_release_report.py` from this run's real data (run identity,
    toolchain, asset sizes/SHA-256, gate results, explicit NOT RUN items),
    then uploads both as release assets — the release body no longer points
    at checksums/report files that were never produced.
  - Release assets now = signed arm64 APK + x86_64 debug emulator APK +
    SHA256SUMS.txt + V0_7_RELEASE_VERIFICATION.md.

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
  covered by deterministic Rust integration tests (redirect, compatibility,
  identity, single-flight refresh, logout truthfulness, header allowlist,
  upload bounds), but no real public-TLS server session and no real packaged
  Windows/macOS regression has exercised it.
- No active application WebSocket route exists; `websocket_device_auth` is a
  helper with a unit test, not runtime WebSocket authentication proof.
- The desktop Rust source compiles, but the local DMG attempt failed in
  `bundle_dmg.sh`; no new desktop package is handed off by this audit.
- No `src-tauri/gen/android` project, `mobile_entry_point`, Android secure
  storage, emulator run, physical-device run or APK exists (Gates E–F not
  started). **Updated 2026-08-15**: the Android project, mobile entry point,
  Android secure store and a signed release APK now exist; only emulator /
  physical-device / upgrade-in-place execution remains not started.
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
3. Gate E Android is implemented at source and **compiled** for
   `aarch64-linux-android` with an always-`android-remote` runtime, Android
   Keystore credential store, fail-closed network security and a v2-signed
   release APK (Gate F signing/checksum/fingerprint); the next step is
   hardware execution — run the APK on an Android emulator and a physical
   device (enrollment/login/refresh/revoke/upload/download/lifecycle).
4. Verify emulator, physical device, signed APK upgrade-in-place and
   cross-device data (Gates F–G); upgrade-in-place must be proven on hardware
   with the same signing key before Gate F can be fully closed.

Release reporting must continue to separate source implementation, automated
tests, Docker runtime, desktop packages, emulator, physical Android hardware,
APK signing/checksum and real external TLS evidence.
