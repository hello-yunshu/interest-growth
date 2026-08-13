# Psychology Growth v0.4.0 Desktop Runtime Audit

**Audit target:** v0.4.0 working tree derived from frozen v0.3.1 provider-boundary release.
**Product identity:** Psychology Growth remains independent; Tauri is the desktop shell and DeepSeek/DeepTutor remain optional external capability providers.
**Desktop targets:** Windows 11 24H2+ x64; macOS 13+ Apple Silicon.

## 1. Release verdict

**Source release candidate: PASS after corrective changes in this cycle.**

The desktop conversion is not a web wrapper around the previous API. Production architecture now has explicit desktop runtime ownership, local App Data, per-launch authorization, native credential storage, platform-specific window materials, native export, single-instance protection, signed-updater boundaries and a native build/smoke workflow.

**Native signed installer release: NOT EXECUTED in this Linux sandbox.** The sandbox has no Rust/Cargo toolchain, no PyInstaller installation, no resolved npm dependency cache/lockfiles, no Docker runtime and no Apple/Windows signing credentials. DNS resolution for npm/PyPI is unavailable. Those gates are represented by executable native CI/release scripts and must be run on the corresponding native hosts; they are not marked PASS here.

## 2. Architecture result

```text
Psychology Growth Desktop
  ├─ static Next.js/React renderer
  └─ Tauri 2 runtime authority
       ├─ native window / Mica or macOS material
       ├─ single instance / window state / signed updater
       ├─ OS credential store
       ├─ user-mediated native export
       └─ Psychology Growth Python Core sidecar
              ├─ random loopback endpoint
              ├─ random per-launch token
              ├─ SQLite + Sources + Artifacts in OS App Data
              └─ optional capability providers
                    ├─ DeepSeek
                    └─ DeepTutor v1.5.11
```

No Psychology Growth product plugin hard-depends on DeepTutor. The desktop shell does not own product domain semantics and does not move canonical data into Rust/Tauri.

## 3. Corrective findings discovered during desktop implementation

### D0-1 · PyInstaller import graph could have omitted the FastAPI product — FIXED

Initial desktop entrypoint called Uvicorn with the dynamic string `pg_api.main:app`. A PyInstaller analysis can miss modules reachable only through runtime string import. The entrypoint now statically imports `from pg_api.main import app` and passes the app object to Uvicorn. A regression test and self-audit rule prohibit returning to the import string.

### D0-2 · TCP-open was an insufficient Core readiness signal — FIXED

Initial Rust runtime considered the sidecar ready when the port accepted TCP. A process can bind before FastAPI startup is actually healthy. Tauri now performs an HTTP `GET /api/health` probe and requires the Psychology Growth service identity before reporting ready.

### D0-3 · Unexpected Core death could leave stale `ready` runtime metadata — FIXED

The shell emitted termination events but did not invalidate the cached endpoint/token. Termination now invalidates runtime state only when the event token still matches the current Core generation, preventing a delayed event from an old process from overwriting a newly restarted Core. The renderer listens for the termination event and refreshes runtime metadata.

### D0-4 · Duplicate desktop instances could share one App Data database — FIXED

Two shells could otherwise own two Core processes against the same SQLite/App Data. The official Tauri single-instance plugin is registered first; subsequent launches focus the existing main window.

### D1-1 · Renderer retained an unnecessary direct DeepSeek network allowance — FIXED

The renderer CSP initially allowed `https://api.deepseek.com`, contradicting the Core-side provider architecture. Production renderer `connect-src` is now limited to Tauri IPC and loopback Core WebSocket/HTTP paths. Provider traffic stays in Python adapters.

### D1-2 · Desktop export still behaved like browser download — FIXED

Publish-pack export now uses the native Save dialog. The dialog grants the chosen path to the runtime scope and the renderer has only the required file-write command. Browser development keeps the normal download fallback.

### D1-3 · Provider secrets needed desktop-native storage — FIXED

DeepSeek API key and optional DeepTutor auth token are stored by Rust through the OS credential facility (macOS Keychain / Windows Credential Manager). Renderer IPC exposes set/delete/status only; it has no read-secret command. Non-secret provider settings remain App Data JSON.

### D1-4 · Failed manual Core restart could retain an old runtime cache — FIXED

Rust records a failed restart as an explicit error runtime. The JS bridge clears its runtime promise on restart failure, and Settings includes a Core-only recovery action.

## 4. Platform policy

macOS transparency/sidebar material requires Tauri `macOSPrivateApi`; v0.4 enables it deliberately. The corresponding distribution target is Developer ID signed + notarized direct DMG, not the Mac App Store. This is treated as a documented channel trade-off rather than an accidental private-API dependency.

Intentional support floor:

- Windows 11 24H2+ (build 26100+), x64.
- macOS 13 Ventura+, Apple Silicon.
- Windows 10, 32-bit Windows, Windows-on-ARM and Intel Mac are not v0.4 release targets.
- Linux is a development/test host only.

This keeps the desktop surface focused on current WebView/native-window behavior instead of carrying legacy OS branches.

## 5. Desktop security boundary

Verified in source/tests:

- random free loopback port;
- per-launch random desktop token;
- HTTP token middleware and Tutor WebSocket token gate;
- CORS preflight does not bypass data authorization;
- sensitive runtime endpoint requires the token;
- renderer cannot directly connect to external AI provider domains;
- OS App Data owns mutable database/source/artifact state;
- secrets remain in native credential storage;
- no secret read-back renderer command;
- updater private key/signing credentials are excluded from source;
- native export is user-mediated;
- single-instance protects shared App Data process ownership.

Threat-model limit: a malicious process already executing as the same compromised OS user is outside the protection offered by the desktop token/credential boundary.

## 6. UI / desktop product result

The renderer was changed from a browser-dashboard layout into a desktop workspace:

- persistent compact navigation;
- `Cmd/Ctrl+K` command palette;
- workspace-centered content area;
- optional Context Inspector;
- provider/runtime status in desktop chrome;
- Windows 11 borderless Mica + custom window controls;
- macOS overlay title bar + semantic sidebar material;
- system light/dark semantic surfaces;
- explicit Core recovery and Provider settings;
- native update UI when a signed update channel is compiled in.

Existing v0.3 product journeys remain available within the new desktop chrome rather than being rewritten into a different domain model.

## 7. Build and distribution architecture

Checked in:

- PyInstaller sidecar builder with exact Tauri target-triple naming;
- static Next.js export configuration;
- Tauri external binary configuration;
- platform-specific Tauri config merge files;
- unsigned native GitHub Actions matrix for macOS Apple Silicon and Windows x64;
- packaged-sidecar health/token smoke before Tauri bundling;
- updater release-config merge-patch generator;
- signed-updater release orchestrator that refuses to run without updater endpoint/public/private signing inputs.

Production Apple/Windows code signing identities remain owner-controlled external release infrastructure.

## 8. Current automated evidence

Source tree at the final pre-freeze gate:

- Python tests: **77/77 PASS**.
- Desktop-specific tests: **21/21 PASS**.
- Python compileall: PASS.
- `scripts/self_audit.py`: PASS.
- Web JS/JSX parser: **18 files / 0 parse failures**.
- configuration parser: JSON **6**, YAML **22**, TOML **2**, plist **1** — PASS.
- clean DB: **33 tables**.
- plugin states: **19**.
- Feature Flags: **20**.
- built-in Personas: **4**.
- schema ledger: **1–7**.
- OpenAPI: **102 paths / 120 operations**.
- v0.3.1-created DB → v0.4 initialization: sentinel row preserved; 33 tables; ledger 1–7.
- original Chinese blueprint vs ASCII baseline: byte-identical.
- original Chinese phase plan vs ASCII baseline: byte-identical.
- source Uvicorn desktop Core smoke: health PASS; protected runtime returns 401 without token and 200 with token.
- product-code TODO/FIXME/NotImplemented scan: no unresolved marker found.
- credential/private-key scan: no release credential material found.

The ignored `data/psychology_growth.db` generated during local validation is not a tracked release file and must be removed before packaging.

## 9. Environment-specific gates not executed here

Not marked PASS:

1. actual npm dependency resolution + Next static production build;
2. actual PyInstaller one-file binary build;
3. actual Cargo/Tauri compile;
4. packaged sidecar smoke on native macOS/Windows binary;
5. actual `.app/.dmg/.exe` build;
6. Apple signing/notarization;
7. Windows code signing;
8. signed updater publication/install from a real endpoint;
9. live DeepTutor/DeepSeek provider calls.

Reason: current sandbox lacks Cargo/Rust, PyInstaller, native signing credentials and outbound DNS/package resolution. The native CI workflow executes gates 1–5 on the correct platforms once run in a connected repository.

## 10. Remaining limitations / follow-up, not release blockers for source v0.4

### L1 · JavaScript/Rust lockfiles are not present

The sandbox cannot resolve npm/crates to generate trustworthy lockfiles. Do not fabricate them. The first connected native build should generate reviewed lockfiles and commit them before treating binary builds as fully dependency-reproducible.

### L2 · Public multi-user web authentication is still outside this product mode

Desktop uses a local runtime token, not a public identity/login system. Do not reinterpret that token as SaaS authentication.

### L3 · No hostile third-party plugin sandbox

PermissionBroker remains trusted first-party policy enforcement. Executable third-party plugins require separate process isolation/signing/provenance work.

### L4 · Backup UX is not yet a dedicated desktop workflow

Canonical data is local and clearly located under App Data, but a polished encrypted backup/restore UI should be added before cloud sync or broader nontechnical distribution.

## 11. Final architectural judgment

v0.4 is a coherent independent desktop architecture, not a DeepTutor branch and not an Electron-style bundled web server. The chosen Tauri/static-renderer/Python-sidecar split preserves the mature Python domain while moving OS lifecycle, credentials, updates, file selection and native window behavior into the appropriate desktop authority.

The source can be frozen and distributed after exact-archive verification. Native public installers must wait for the native build/signing gates rather than being falsely labeled complete in this environment.
