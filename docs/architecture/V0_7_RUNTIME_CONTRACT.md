# Interest Growth v0.7 — Runtime Contract (Gate A, frozen)

This document freezes the runtime semantics that every v0.7 client and the
self-hosted server must implement. It is normative for Gate B–G. Behavior
changes require a new version of this contract and an explicit client/server
compatibility check.

## 1. Runtime matrix (frozen)

| Runtime id | Client shell | Data owner | Sidecar | Canonical store | Distribution |
|---|---|---|---|---|---|
| `desktop-local` | Tauri 2 (Windows/macOS) | local device | Python Core on loopback | OS App Data (`psychology_growth.db` + Sources + Artifacts) | existing desktop installer/DMG path |
| `desktop-remote` | Tauri 2 (Windows/macOS) | self-hosted server | none (remote only) | server DB + server vaults | same desktop package |
| `android-remote` | Tauri 2 (Android) | self-hosted server | never bundles Python | server DB + server vaults | direct APK sideload |
| `browser-remote` | static Next.js export in a WebView-free browser | self-hosted server | none | server DB + server vaults | served only by the controlled HTTPS deployment |

Frozen semantics:

1. The v0.7 release is **server-authoritative and online-first**. Remote
   clients never hold a writable replica of canonical product data.
2. A remote client cache is disposable UI presentation state, never canonical
   product data, and must not be described as offline storage.
3. When the server is unreachable, remote mutations are disabled. "Offline
   sync" is a non-goal and must not be claimed.
4. The existing desktop-local mode and its App Data, keyring, token and
   updater behavior remain unchanged and fully supported.
5. Android does not bundle or launch the Python sidecar and does not create a
   local canonical database.
6. The browser renderer never calls a model provider directly and never
   receives provider secrets.
7. The server (or the desktop-local Core) originates model-provider calls.

## 2. Runtime identifier and capability contract

Each client declares its runtime explicitly:

```text
runtimeId: desktop-local | desktop-remote | android-remote | browser-remote
```

API consumers must not infer the runtime from `isTauri()` alone: the same
Tauri shell can be `desktop-local` or `desktop-remote`, and Android must be
treated as a distinct mobile runtime, not a desktop fallback.

Per-runtime capability table (frozen):

| Capability | desktop-local | desktop-remote | android-remote | browser-remote |
|---|---|---|---|---|
| Launch local sidecar | yes | no | no | no |
| Loopback desktop token | yes | no | no | no |
| Device session auth | no (local token) | yes | yes | yes (cookie) |
| OS secure storage for renewal credential | yes (desktop keyring) | yes (desktop keyring) | yes (Android Keystore) | secure cookie |
| Local Source/Artifact vaults | yes | no | no | no |
| Server Source/Artifact upload/download | no | yes | yes | yes |
| Provider-secret editing | desktop keyring surface | server-admin surface only | not in v0.7 | server-admin surface only |
| System-browser external links | yes | yes | yes | yes (scoped) |
| Export via OS Save/picker | yes | yes | Android picker/share | server download |

Mobile adaptation contract (additive, Gate E — source vocabulary, adapters
planned): every runtime descriptor exposes the frozen capability vocabulary
from `apps/web/lib/runtime/contract.js` (`PLATFORM_CAPABILITIES`). The
desktop-only gate (`DESKTOP_ONLY_CAPABILITIES`) — launch sidecar, loopback
token, OS save dialog, local vaults, desktop updater, window controls and
local provider-secret administration — MUST be false on every non-desktop
runtime, so a mobile build can never silently reach a desktop/local path.
`android-remote` assigns the renewal credential to Android Keystore
(`canUseNativeSecureStore` true) and declares document picker / share sheet /
suspend-resume lifecycle / optional biometric unlock as planned adapters; they
are contract vocabulary, not implemented surfaces.

## 3. Authentication contract (frozen)

1. Every non-health HTTP route authenticates the owner/device session first;
   Interest Area scoping and PermissionBroker checks run afterwards and remain
   orthogonal. Every WebSocket route must enforce the same ordering when one
   is introduced; the current implementation contains no active WebSocket
   endpoint and a helper alone is not completion evidence.
2. `desktop-local` uses the existing per-launch loopback desktop token. That
   token is process authentication only and is never presented as remote
   identity.
3. `desktop-remote` / `android-remote` use a short-lived access credential
   (`Authorization: Bearer`) plus a rotated, per-device renewal credential.
4. Renewal credentials are stored only in OS-backed secure storage
   (native clients) or a secure cookie (browser-remote). `localStorage` is
   forbidden for renewal credentials.
5. The server stores only salted password hashes and token hashes, never
   reusable plaintext secrets.
6. Device revocation invalidates only the revoked device's renewal path.
7. CORS is not authentication. Narrowly configured origins only define where
   the same-origin browser UI may run; they never grant API access.

## 4. API compatibility metadata (frozen)

The server exposes a public, non-sensitive capability endpoint:

```text
GET /api/system/capabilities
```

Response shape (normative):

```json
{
  "product": "interest-growth",
  "server_version": "0.7.0",
  "api_version": "1",
  "min_client_version": "0.7.0",
  "runtime_modes": ["desktop-local", "desktop-remote", "android-remote", "browser-remote"],
  "auth": {
    "mode": "single_owner_devices",
    "enabled": true
  },
  "online_first": true,
  "offline_sync": false,
  "public_health": true
}
```

Client behavior (frozen):

- Before writing any credential, the client reads this endpoint over HTTPS,
  verifies the server identity/TLS state, and checks `api_version` and
  `min_client_version`.
- If the client version is below `min_client_version`, the client enters the
  incompatible-server state and disables mutations.
- If a server requires auth (`auth.enabled`) but the client has no device
  session, the client starts enrollment; it never guesses data location.
- `api_version` increments only on breaking API changes. `server_version`
  follows product releases.

## 5. Remote enrollment flow (frozen)

1. User enters the server URL; the client rejects URLs with embedded
   credentials, fragments, non-HTTPS public endpoints and unsafe redirects.
   Loopback HTTP remains allowed for explicit development and as the trusted
   external-proxy-to-Docker upstream. It is never an enrolled public endpoint.
2. Client fetches `/api/system/capabilities` and `/api/auth/server-info`
   and shows server identity, TLS state, product/version and auth mode.
3. Client asks for the owner password and a human-readable device name.
4. `POST /api/auth/owner/login` returns a device id plus a short-lived access
   credential and a renewal credential. `POST /api/auth/device/refresh`
   rotates the renewal credential.
5. Only after successful authentication may the client persist the renewal
   credential in native secure storage, and it must label the session with
   the enrolled server identity and the device name.

## 6. Server identity and connection states (frozen)

The global connection state must distinguish:

- `Connected` — authenticated, server reachable;
- `Reconnecting` — bounded retry, current view preserved;
- `Offline` / `Server unavailable` — mutations disabled;
- `Login expired` — focused re-authentication flow required;
- `Certificate/identity changed` — blocking security explanation, explicit
  re-enrollment required;
- `Update required` — server/client incompatible.

Remote error text must never claim that canonical data is stored on the
current device.

## 7. Backup/restore unit (frozen)

The server persistent unit is one consistency unit:

```text
server data
├── psychology_growth.db
├── sources/            canonical originals
├── artifacts/          exported/generated product files
└── backup metadata     schema/app version + per-file checksums
```

- A backup is complete only when DB + both vaults come from one consistent
  backup operation; copying a live SQLite file alone is not a backup.
- Restore must re-run migrations, check database integrity and file
  references, and verify representative reads/downloads.
- Online backup and restore coordinate DB + Source + Artifact mutations under
  one maintenance/write lock (an in-process reader/writer gate plus a
  cross-process advisory flock), so a bundle never references a file that was
  not copied. Restore stages and verifies the bundle on temporary paths and
  retains the previous live state until post-restore checks pass. (This bullet
  is a post-Gate-B fact sync of §7 wording — no change to other frozen Gate A
  contract semantics.)

## 8. Non-goals (frozen for v0.7)

- Google Play, Play App Signing, AAB and store automation;
- public registration, organizations and multi-tenancy;
- offline bidirectional sync and conflict resolution;
- bundling the Python Core inside Android;
- automatic merge of a desktop-local database into a server database;
- renaming legacy compatibility identifiers without a migration;
- exposing model-provider secrets to clients;
- directly exposing Uvicorn or the trusted-proxy remote profile to an
  untrusted LAN/public network.
