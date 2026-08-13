# Interest Growth v0.7 — Implementation Audit

**Audit date:** 2026-08-13
**Scope:** authenticated self-hosted Core, Docker/proxy deployment, backup/restore, desktop/Android readiness and recorded verification.

## 1. Outcome

Gate A is documented. Most Gate B source work exists and the corrected Docker
profile runs, but Gate B is not release-complete because four concurrency and
recovery boundaries remain open. Gate C must not be represented as started:
the frontend still treats Tauri as desktop-local, and no Android project or
mobile Rust entry point exists.

## 2. Implemented in source

- Single-owner bootstrap/login and named device records.
- Short-lived access credentials, rotated renewal credentials and per-device
  revocation.
- Remote-mode HTTP authentication middleware kept separate from Interest Area
  and PermissionBroker authorization.
- Public health/capability/server metadata endpoints.
- DB + Source + Artifact backup bundle, checksums, verification and restore
  smoke checks.
- Remote Docker API/Web profile on loopback HTTP.
- External Nginx TLS-edge example and optional bundled Caddy overlay.
- Static Next.js export packaged in an Nginx Web image.

## 3. Verified in this audit

- Main Python suite: 121 passed.
- Native Execution Core: 64 passed.
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

## 4. Open release blockers

### B1 — Atomic renewal-token rotation

`device_refresh` reads the old token, marks it revoked and calls a token issuer
that commits internally. Two concurrent requests can observe the old token as
usable before either transaction consumes it. Consumption and replacement
must be one atomic conditional transaction with a concurrent replay test.

### B2 — Database-enforced single owner

The bootstrap route checks `owner_configured()` before insert, but the database
does not enforce a singleton row. Concurrent first bootstrap requests can
create multiple owners. Add a database-level invariant and treat the unique
conflict as an already-configured response.

### B3 — Cross-component backup consistency

The SQLite online snapshot is consistent by itself, but Sources and Artifacts
are copied afterwards. The current workflow therefore requires writes to be
stopped/drained for the entire operation. Online backup may be advertised only
after a maintenance/write lock coordinates DB and vault mutations and a
concurrent-write regression test passes.

### B4 — Rollback-safe restore

Restore overwrites the live DB and removes live vault directories before
migrations and smoke checks finish. Restore must stage and verify temporary
paths, switch atomically where possible and retain the previous state until
post-restore checks succeed.

## 5. Verified boundaries, not completion claims

- No active application WebSocket route exists; `websocket_device_auth` is a
  helper with a unit test, not runtime WebSocket authentication proof.
- The desktop Rust source compiles, but the local DMG attempt failed in
  `bundle_dmg.sh`; no new desktop package is handed off by this audit.
- No `src-tauri/gen/android` project, `mobile_entry_point`, Android secure
  storage, emulator run, physical-device run or APK exists.
- Cross-device continuity has not been exercised with two independent clients.
- No real public hostname, valid public certificate or external Nginx runtime
  was exercised; only the loopback upstream contract and forwarded scheme were
  verified.

## 6. Required next order

1. Close B1–B4 and add their regression tests.
2. Implement Gate C `ClientRuntime` and remove every-Tauri-is-desktop coupling.
3. Implement and regression-test desktop remote mode while preserving local
   sidecar mode.
4. Initialize and target-gate Tauri Android.
5. Verify emulator, physical device, signed APK upgrade and cross-device data.

Release reporting must continue to separate source implementation, automated
tests, Docker runtime, desktop packages, emulator, physical Android hardware,
APK signing/checksum and real external TLS evidence.
