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

- [ ] Make refresh-token consumption and replacement one atomic transaction and add a concurrent replay test.
- [ ] Enforce the one-owner invariant in the database so concurrent bootstrap requests cannot create multiple owners.
- [ ] Require a quiesced backup window now, then add an application maintenance/write lock before advertising online consistent backup.
- [ ] Stage restore into temporary paths and retain rollback state until migrations and smoke checks pass.
- [ ] Integrate and test device authentication on each real WebSocket route when one is introduced; the current source has only an authentication helper and no active WebSocket endpoint.

Gate C starts after the security/data-consistency items above are closed or explicitly accepted as release blockers.

## Gate C — ClientRuntime refactor

- [ ] Replace the every-Tauri-is-desktop assumption with an explicit runtime/platform adapter.
- [ ] Centralize API base URL, auth headers, WebSocket auth/reconnect, export and external links.
- [ ] Add enrolled-server identity and server-version state.
- [ ] Replace local-only error copy in remote mode.
- [ ] Add secure native credential storage; do not use `localStorage` for renewal credentials.
- [ ] Give CSP/capabilities the minimum platform-specific remote origin and permissions.

## Gate D — Desktop remote mode

- [ ] Add explicit local-device versus self-hosted-server selection.
- [ ] Preserve existing loopback sidecar startup, token rotation, App Data and provider keyring behavior.
- [ ] Add remote enrollment/login/logout/device revocation UX.
- [ ] Keep server data visually distinguishable from local-device data.
- [ ] Define explicit local export/server import; do not silently merge stores.
- [ ] Verify Windows/macOS local mode has no regression.

## Gate E — Android application

- [ ] Initialize the Tauri Android project and mobile entry point.
- [ ] Gate sidecar, updater, single-instance, window-state and desktop-only credential code.
- [ ] Select mobile-supported secure storage, opener, dialog/document and lifecycle implementations.
- [ ] Implement remote server enrollment and authentication.
- [ ] Complete narrow-screen navigation, system Back, keyboard/insets, touch and suspend/resume behavior.
- [ ] Verify uploads, downloads/exports, Tutor WebSocket reconnect and external links.
- [ ] Test emulator plus at least one physical Android device.

## Gate F — Direct APK release

- [ ] Produce a debug-signed APK for internal/ADB testing.
- [ ] Generate and securely back up a project-owned release keystore outside Git.
- [ ] Build a release APK signed with that key; no Google Play/AAB dependency.
- [ ] Record application ID, version name, version code and signing-certificate fingerprint.
- [ ] Publish SHA-256 checksum and a concise installation/update guide.
- [ ] Install the first release on hardware, then prove a higher-version APK signed by the same key upgrades in place.
- [ ] Recheck current Android developer-verification/sideload rules before broad handoff and choose an explicit path: ADB/internal use, current limited-device distribution, verified broad distribution or documented advanced user flow.

## Gate G — Cross-device and recovery proof

- [ ] Mutate representative canonical data on one client and verify it on desktop and Android.
- [ ] Exercise Area isolation, Evidence/Claim review, Tutor resume and Artifact download across clients.
- [ ] Revoke one device without breaking other sessions.
- [ ] Verify authentication expiry/recovery and incompatible-server behavior.
- [ ] Back up the complete server data unit, restore it into a clean deployment and run integrity smoke tests.
- [ ] Run existing compile/test/self-audit gates and add remote/Android contract tests.

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
