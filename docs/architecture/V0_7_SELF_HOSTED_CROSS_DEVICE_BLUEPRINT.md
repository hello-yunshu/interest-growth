# Interest Growth v0.7 — Self-hosted Cross-device Blueprint

## 1. Goal and product mode

v0.7 adds a user-owned server mode without deleting the existing local-first desktop mode. One Interest Growth Native Core can run in Docker on a Unix host and serve Windows, macOS, Android and an optional browser UI.

The first release is online-first and single-owner. The server is the canonical data location for remote mode; clients do not maintain independently writable database replicas.

## 2. Supported runtime matrix

| Client | Local sidecar | Self-hosted server | Initial distribution |
|---|---:|---:|---|
| Windows Tauri | yes | yes | existing desktop installer/package path |
| macOS Tauri | yes | yes | existing desktop app/DMG path |
| Android Tauri | no | yes | direct APK sideload |
| Browser | no | optional | served only through the controlled HTTPS deployment |

Google Play, Play App Signing, AAB publication and public multi-tenant SaaS are non-goals for v0.7.

## 3. Runtime architecture

```text
Windows/macOS Tauri                       Android Tauri
├── desktop-local runtime                 └── android-remote runtime
│    └── loopback Python sidecar                    │
└── desktop-remote runtime                          │
             │ HTTPS / WSS + device session         │
             └─────────────────┬─────────────────────┘
                               ▼
                 External reverse proxy / TLS edge
                               │ trusted loopback/container HTTP
                               ▼
                    Interest Growth API container
                    ├── Native Execution Core
                    ├── authentication/device sessions
                    ├── Capability + Domain policy
                    ├── SQLite (single writer)
                    ├── Source vault volume
                    └── Artifact vault volume
```

The browser renderer and native clients call Interest Growth only. Model-provider calls originate from the server Core or the existing desktop-local Core, never from client JavaScript.

## 4. Canonical data and cross-device meaning

In remote mode, the server's database, Source vault and Artifact vault are one canonical product state. Cross-device continuity means that two authenticated clients read and mutate this same state through versioned APIs.

It does not mean:

- peer-to-peer device replication;
- local SQLite copies synchronized in the background;
- offline mutation queues;
- automatic merging of a desktop-local database into a server database.

Client caches may preserve navigation, selected Area and safe presentation state. They may not become an undocumented second source of truth.

## 5. Ownership and authorization

v0.7 initially has one server owner and multiple registered devices. Authentication and Interest Area scoping are orthogonal:

- account/device identity answers **who may use this server**;
- Interest Area answers **where the owner's work belongs**;
- Capability/PermissionBroker answers **which product operation is allowed**;
- Domain Pack answers **which subject policy applies**.

Every protected HTTP and WebSocket path first authenticates the owner/device session, then applies existing Area and capability authorization. `X-PG-Interest-Area` must never be accepted as proof of account ownership.

## 6. Session design

- Enrollment creates a named, revocable device record.
- Access credentials are short-lived.
- Renewal credentials are rotated/revocable and stored only in native secure storage or a secure browser cookie.
- Server-side session records store hashes/identifiers rather than reusable plaintext secrets.
- Authentication events expose bounded operational metadata without logging credentials or sensitive request bodies.
- WebSocket reconnect reauthenticates and resumes only authorized Tutor state.

The existing per-launch desktop token remains local-mode process authentication and must not be presented as remote identity.

## 7. Storage and backup

The first server implementation may keep SQLite because the deployment is single-owner and single-writer. It must run one API writer process and must not advertise horizontal scaling.

The persistent unit is:

```text
server data
├── psychology_growth.db       compatibility filename
├── sources/                   canonical originals
├── artifacts/                 exported/generated product files
└── backup metadata            schema/app version + checksums
```

A backup is complete only when the database and both vaults come from a consistent backup operation. Restore verification must start the exact restored data, run migrations safely, check file references and exercise representative reads/downloads.

PostgreSQL, object storage and multi-tenant ownership require a later explicit migration design; `APP_DATABASE_URL` alone does not prove the current SQLite-specific migrations are portable.

## 8. Client runtime abstraction

The shared Next.js/React UI obtains a `ClientRuntime` with:

- mode and platform;
- API and WebSocket endpoints;
- authentication/header provider;
- secure credential operations;
- export/download implementation;
- external-link implementation;
- connection/server-version state;
- platform capabilities.

No feature page may branch directly on a vague `isTauri()` assumption when the behavior differs between desktop-local, desktop-remote and Android.

## 9. Android boundary

Android packages the static UI and a mobile Tauri/Rust shell only. It does not package Python, SQLite product data or the desktop sidecar.

Desktop-only dependencies and commands are target-gated. Android provides mobile-specific implementations for secure credential storage, document selection/export, external links, Back handling, lifecycle/resume and network-state recovery.

The initial supported artifact is a directly distributed APK:

- debug-signed APK for development/ADB;
- project-self-signed release APK for controlled distribution;
- no Google Play/AAB requirement;
- stable application ID, monotonically increasing version code and the same private signing key for updates;
- SHA-256 checksum and signing-certificate fingerprint published with each release.

## 10. Network deployment

Compose continues to bind to loopback by default. The authenticated remote profile itself may use plain HTTP on `127.0.0.1`; an operator-managed external Nginx/Caddy (or the optional Caddy overlay) supplies the public hostname and TLS edge. Directly binding Uvicorn to an untrusted LAN or the Internet is not a supported deployment.

The remote profile requires:

- client-facing HTTPS/WSS with a valid certificate and no insecure downgrade;
- trusted loopback/private-network HTTP is allowed between the reverse proxy and Docker;
- narrowly configured origins/hosts;
- authentication on every non-health data route;
- upload/request limits and bounded timeouts;
- secret injection outside images/source;
- restart policy, health checks and consistent backup jobs;
- clear LAN-only/VPN/public-Internet deployment modes.

For a personal deployment, a private network/VPN path may be recommended before public Internet exposure, but it does not replace application authentication.

## 11. Local-to-server migration

Desktop local mode remains valid. A user may explicitly export a migration bundle containing a schema/app version, manifest, database records and referenced Source/Artifact files. The server validates and imports the bundle transactionally or provides a dry-run/conflict report.

Direct database-file replacement, automatic startup upload and undocumented record merging are forbidden.

## 12. APK sideload policy horizon

Android still requires every installable APK to be cryptographically signed, even when it is not distributed through Google Play. The project manages its own key.

Android developer-verification policy is an external, evolving constraint. In the 2026-08-13 planning snapshot, direct sideload/ADB remain possible; the initial September 2026 participating-store enforcement does not yet cover direct sideload, while broader certified-device enforcement is planned to expand during 2027. Verified package registration or an advanced installation flow may therefore affect later distribution. Release work must recheck current Android documentation and describe the actual user installation path rather than promise friction-free unsigned installation.

Official references for release-time revalidation:

- Android app signing: <https://developer.android.com/studio/publish/app-signing>
- Android developer verification: <https://developer.android.com/developer-verification/guides>
- Verification FAQ and sideload/advanced-flow status: <https://developer.android.com/developer-verification/guides/faq>
- Tauri Android signing: <https://v2.tauri.app/distribute/sign/android/>

## 13. Non-goals

- Google Play or another store submission;
- AAB as a required artifact;
- public signup or multi-tenant SaaS;
- offline bidirectional sync;
- bundling the Python Core inside Android;
- automatic merge of independent local and server databases;
- renaming legacy desktop identifiers without a migration;
- exposing model-provider secrets to clients.

## 14. Completion definition

v0.7 is complete only when authenticated Docker deployment, desktop remote mode, Android remote mode, cross-device data continuity, session revocation, consistent backup/restore and same-key APK upgrade are all independently verified. Source-only compilation is not Android delivery proof.
