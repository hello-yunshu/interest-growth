# Interest Growth v0.7 — Implementation Audit

**Audit date:** 2026-08-13
**Scope:** authenticated self-hosted Core, Docker/proxy deployment, backup/restore, desktop/Android readiness and recorded verification.

## 1. Outcome

Gate A is documented. Gate B (B1–B4) is implemented and regression-tested as
of this audit, so Gate B is closed at the source-and-test gate level. Gate C
must not be represented as started: the frontend still treats Tauri as
desktop-local, and no Android project or mobile Rust entry point exists.

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

## 3. Verified in this audit

- Main Python suite: 234 passed (Host, includes the Gate B security and
  concurrency regression tests).
- Native Execution Core standalone package: 97 passed.
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

1. Implement Gate C `ClientRuntime` and remove every-Tauri-is-desktop coupling.
2. Implement and regression-test desktop remote mode while preserving local
   sidecar mode.
3. Initialize and target-gate Tauri Android.
4. Verify emulator, physical device, signed APK upgrade and cross-device data.

Release reporting must continue to separate source implementation, automated
tests, Docker runtime, desktop packages, emulator, physical Android hardware,
APK signing/checksum and real external TLS evidence.
