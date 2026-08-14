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
  the credential, so a server replaced behind the same URL is detected
  right before the password/refresh leaves the process. Directed test: probe
  answers instance-A, login endpoint answers instance-B → refused with
  IDENTITY_CHANGED and nothing persisted.
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
