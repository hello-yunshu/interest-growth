# Interest Growth v0.7 — Self-hosted Cross-device and Android Execution Prompt

You are evolving Interest Growth v0.6 into the v0.7 self-hosted, cross-device product. Read this file together with `12_CODING_AGENT_MASTER_PROMPT.md`, `V0_7_SELF_HOSTED_CROSS_DEVICE_BLUEPRINT.md`, `V0_7_SELF_HOSTED_CROSS_DEVICE_PLAN.md`, `V0_7_CROSS_DEVICE_CLIENT_DESIGN.md`, the latest audit and `11_SECURITY_AND_PRIVACY.md` before changing behavior.

## Mission

Deliver one user-owned Interest Growth service that runs in Docker on a Unix system and can be used from Windows, macOS, Android and an optional browser client.

The first v0.7 release is **server-authoritative and online-first**:

- FastAPI Native Core, canonical database, Sources and Artifacts run on the self-hosted server;
- Windows/macOS clients may use either the existing local sidecar mode or the new remote-server mode;
- the first Android client is remote-server-only and does not bundle or launch the Python sidecar;
- all remote clients see the same server state, which provides cross-device continuity without claiming offline database replication;
- Google Play, Play App Signing, AAB publication and store automation are outside this release.

## Non-negotiable product laws

- Preserve the four layers: Interest Area, Capability Plugin, Domain Pack and model transport. Do not reinterpret an Interest Area as a user, tenant or authorization boundary.
- Psychology remains the default Domain Pack, not Core.
- Host product models remain canonical. Model output, retrieval candidates and execution state remain non-authoritative until the existing review/evidence rules promote them.
- The Renderer never calls a model provider directly and never receives provider secrets.
- Remote mode must not weaken Area ownership, evidence verification, Human Review, pause/return or provider degradation.
- The existing desktop local mode and its App Data/keyring/updater compatibility identifiers must continue to work unless an explicit migration is implemented and tested.

## Remote deployment contract

- Never expose the current unauthenticated development API to an untrusted LAN or the Internet.
- Remote client-facing HTTP and WebSocket traffic require authenticated device sessions over HTTPS/WSS. The external proxy may forward to Docker over trusted loopback/private HTTP; CORS is not authentication.
- Start with a single-owner deployment. Do not silently generalize it into public multi-tenant SaaS.
- Use short-lived access credentials plus a revocable, per-device renewal mechanism. Never store long-lived credentials in browser `localStorage`.
- Android and desktop native clients store renewal credentials through an OS-backed secure-storage capability. Web login uses secure cookie semantics when a browser client is enabled.
- The server owns model-provider secrets. Ordinary remote clients can see configured/not-configured and health state but cannot read secret values.
- Server URL enrollment must reject embedded credentials, fragments, non-HTTPS public endpoints and unsafe redirect/downgrade behavior. Loopback HTTP remains valid for local Docker and reverse-proxy upstream traffic, not as an enrolled public endpoint.
- Rate limits, bounded request/file sizes, audit-safe security events and device-session revocation are required before public-network exposure.

## Data and continuity contract

- Initial self-hosted storage may remain SQLite only with one API writer process and no horizontal replicas.
- SQLite, Sources and Artifacts must live in declared persistent volumes. A real backup/restore workflow must cover all three as one consistency unit.
- Do not copy a live SQLite file as the only backup mechanism; use a consistent database backup/snapshot path and verify restore.
- A remote client cache is disposable UI state, not canonical product data.
- Do not label the first release “offline sync.” When the server is unreachable, remote mutations are unavailable unless a later version introduces an explicit operation log, idempotency keys, versions and conflict policy.
- Moving existing desktop-local data to a server requires an explicit export/import or migration workflow. Never merge two databases by file copy or silently upload App Data.

## Client runtime contract

Refactor the frontend around an explicit runtime adapter instead of assuming every Tauri WebView is desktop-local:

```text
ClientRuntime
├── desktop-local  -> Tauri command -> loopback sidecar + launch token
├── desktop-remote -> HTTPS/WSS server + device session
├── android-remote -> HTTPS/WSS server + device session
└── browser-remote -> same-origin/restricted HTTPS server
```

- API base URL, authentication headers, WebSocket authentication, download/export and external-link behavior must be runtime-owned.
- `isTauri()` is not sufficient to distinguish desktop from Android.
- Remote error text must not claim that canonical data is stored on the current device.
- CSP and capability files must use the narrowest platform-specific permissions and allow only the enrolled remote origin where technically possible.
- Desktop-only sidecar, updater, window-state, single-instance and desktop keyring code must be gated behind desktop targets.
- Android must use a mobile entry point and mobile-supported plugins or platform implementations.

## Android APK distribution contract

- The release channel is direct APK sideloading, not Google Play.
- Internal development may use a debug-signed APK or `adb install`.
- A distributable release APK must be signed with the project's own private Android signing key. “No official/store signature” never means “unsigned APK.”
- Keep the keystore, passwords and generated signing properties outside Git. CI receives them only through protected secrets or a controlled local release environment.
- Every update for the same Android application ID must use the same signing identity and a valid higher version code. Losing the key is a release-blocking incident.
- Produce SHA-256 checksums next to direct-download APKs and publish the expected application ID, version name, version code and signing-certificate fingerprint.
- Do not add Google Play assets, Play Console automation or AAB as a release requirement.
- Recheck the current Android developer-verification rules before broad distribution. Direct sideloading and `adb` testing are allowed paths, but future certified-device verification or advanced-install flows must not be hidden from users.

## UX laws

- First launch clearly selects or reports `This device` versus `Self-hosted server`; never make users guess where their data lives.
- Remote enrollment shows server identity, TLS/security state, account and device name before writing credentials.
- The global connection state distinguishes online, reconnecting, offline, authentication expired, incompatible server and server unavailable.
- Android navigation, system Back, keyboard/insets, touch targets, document picker/share sheet and process resume must be intentional rather than accidental desktop fallbacks.
- Provider-secret editing is a server-administration surface, not an ordinary Android client setting.
- Remote destructive actions retain the existing in-app approval and Human Review rules.

## Required implementation order

1. Preserve the frozen remote API/auth/version contract and threat model.
2. Close the Gate B audit findings before client expansion: atomic refresh rotation, database-enforced owner singleton, quiesced/locked backup consistency and rollback-safe restore.
3. Keep Docker HTTP loopback-bound and verify the external proxy overwrites forwarded headers and supplies client-facing HTTPS/WSS.
4. Introduce the platform-neutral ClientRuntime adapter and update HTTP, WebSocket, export and error paths.
5. Add desktop remote mode without regressing desktop local mode.
6. Add the Tauri Android target with desktop-only Rust/plugins/config correctly gated.
7. Complete responsive/mobile interaction QA on an emulator and at least one real Android device.
8. Produce a debug APK for internal testing, then a project-self-signed release APK plus checksum and fingerprint metadata.
9. Prove cross-device continuity, session revocation, server backup/restore and same-key APK upgrade.

## Required verification

- Existing compile, unit, self-audit and desktop contract tests remain green.
- Unauthenticated HTTP and WebSocket access to protected data return 401; unauthorized resource access returns 403/404 according to the disclosure policy.
- Revoking one device invalidates only that device's renewal path.
- Windows/macOS remote mode and Android observe the same server-side change after refresh/reconnect.
- Local desktop mode still launches its loopback Core and retains existing local data.
- Remote clients cannot invoke desktop-local commands or obtain server/provider secrets.
- Source upload/download, Tutor reconnect, export, app suspend/resume and token refresh are tested on Android.
- A release APK installs on a real device and a later APK signed by the same key upgrades it without uninstalling.
- Backup restoration recreates the database plus Source/Artifact files and passes referential/integrity smoke tests.

## Completion and reporting

Report these states separately:

1. documented;
2. implemented in source;
3. covered by automated tests;
4. verified in Docker;
5. verified on desktop packages;
6. verified on Android emulator;
7. verified on real Android hardware;
8. release APK signed/checksummed and handed off.

Do not claim Android publication merely because the web build or Rust cross-compile succeeds. Do not claim cross-device continuity until two independent clients have exercised the same server data. Do not claim offline sync in v0.7.
