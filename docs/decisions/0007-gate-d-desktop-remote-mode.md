# ADR 0007 · Gate D — Desktop remote mode

**Status:** Accepted · v0.7.0 (source + tests; not release-proven)

## Context

Gate C established a single ClientRuntime truth so the product UI is no longer
hard-wired to `Tauri == desktop-local`. Gate D adds the desktop remote mode:
the same Tauri shell switches between a local device (loopback Python Core)
and a self-hosted server (HTTPS + device-session auth). The frozen v0.7
contract (`docs/architecture/V0_7_RUNTIME_CONTRACT.md`) and threat model
(`docs/security/V0_7_REMOTE_THREAT_MODEL.md`) require:

- no silent fallback from a remote session to a local dataset;
- renewal credentials kept out of the renderer and `localStorage`;
- server identity verification separate from TLS certificate pinning;
- mutations disabled while disconnected; no implicit mutation retry;
- the Tauri CSP must not be relaxed to arbitrary HTTPS to make remote work.

## Decision

### 1. Native/Rust-owned remote transport, not WebView direct fetch

Remote HTTP traffic goes through a native credential broker and transport
(`apps/desktop/src-tauri/src/remote.rs`). The renderer submits only a relative
API path; the base origin always comes from the verified enrollment profile.
The renderer can never ask the transport to contact an arbitrary host, and it
never supplies an `Authorization` header. This keeps the Tauri CSP unchanged
(loopback/IPC only) and keeps the renewal credential in the OS keyring.

### 2. Explicit restart boundary, session immutable

A runtime-mode switch persists the NEXT profile and takes effect only after an
explicit application restart (`restart_app`). One process lifetime is exactly
one runtime (`desktop-local` or `desktop-remote`). This prevents mixing local
and remote datasets, half-started sidecars and cross-session credential
mixing. No silent local/server merge exists.

### 3. Remote mode never spawns the sidecar and never falls back locally

`RuntimeMode` is resolved from the persisted profile before startup; only
`desktop-local` spawns the sidecar. If a remote session loses the server,
expires or sees an identity change, the state machine maps it to
Offline/LoginExpired/IdentityChanged with mutations disabled rather than
silently starting a local Core.

### 4. Server identity, not certificate pinning

Identity is a stable non-secret `server_instance_id` (migration 15) verified
through TLS plus the server-info contract. Certificate renewal therefore never
triggers a false identity change; a changed instance id behind the same URL is
a blocking `IdentityChanged` requiring explicit re-enrollment.

### 5. Enrollment URL normalization

Enrollment origins accept only HTTPS (or explicit loopback HTTP for
development), reject embedded credentials/query/fragment/subpaths and never
disable TLS verification. Private/LAN hosts are allowed because self-hosted
servers commonly run on a LAN/VPN; this is distinct from the server-side
SafeWebFetcher SSRF rules.

### 6. Provider administration stays desktop-local

`canAdminLocalProviderSecret` is true only for `desktop-local`. In remote
mode the client shows provider availability only; server-side administration
belongs to a deliberate server-admin surface in a later milestone.

## Consequences

- Feature pages keep using the existing `api.js` facade; runtime selection,
  headers and transport are owned by the ClientRuntime, so Android reuses the
  same product surfaces.
- The desktop-local path, App Data, keyring, token and sidecar behavior are
  unchanged; existing installs default to `desktop-local`.
- Remote UX exists at source level (`RuntimeConnect`: mode selection,
  enrollment, login/logout, device management, connection status) but is NOT
  release-proven: no real public-TLS server session and no real packaged
  Windows/macOS regression have exercised it.
- `browser-remote` remains a planned adapter only; secure-cookie auth and CSRF
  are a separate implementation requirement and are not claimed.

## Verification

- ClientRuntime pure contract tests (Node built-in runner): 59 passed,
  including remote-transport connection-state guards, positive header
  allowlist, upload bounds, and Gate E mobile capability vocabulary +
  desktop-only gate.
- Rust runtime-mode + remote-transport + native broker integration tests: 39
  passed (`cargo test --locked --lib`) covering runtime-mode decisions
  (default/explicit desktop-local, desktop-remote never spawning the sidecar,
  invalid-profile store isolation, active/pending runtime separation,
  provider-admin gating), enrollment-origin normalization/validation,
  refresh-key namespace isolation, and deterministic native broker tests
  against an in-memory server: redirects never followed, compatibility
  rejects, identity before credentials, single-flight refresh with
  keyring-failure recovery, truthful logout revoke results, header positive
  allowlist and bounded uploads.
- Gate C/D desktop-local compatibility and CSP audits: PASS; no CSP relaxation
  to arbitrary HTTPS/`connect-src *`.
- SOURCE_MANIFEST integrity: deterministic generation + CI check PASS.
- Outstanding evidence (NOT RUN, not PASS): real public-TLS enrollment,
  packaged Windows/macOS local + remote regression, Android/APK, cross-device
  proof — tracked in `docs/roadmap/V0_7_SELF_HOSTED_CROSS_DEVICE_PLAN.md`.
