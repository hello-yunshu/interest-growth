# Psychology Growth v0.4.0 — Desktop Runtime

## Added
- Tauri 2 Windows/macOS desktop shell.
- Static Next.js export; no production Node web server.
- PyInstaller Python Core sidecar owned by Tauri lifecycle.
- OS app-data database/source/artifact vault.
- Random loopback port and per-launch API token.
- Tauri window-state persistence and native material configuration.
- macOS native transparent sidebar explicitly enables Tauri `macOSPrivateApi`; v0.4 targets Developer ID signed/notarized DMG distribution rather than the Mac App Store.
- Desktop navigation shell, command palette and context inspector.
- Windows 11 24H2+ and macOS 13+ support policy; the Windows NSIS installer blocks builds below 26100 before installation.
- Updater-ready release config with mandatory external signing keys.
- Windows/macOS CI build matrix.
- Native OS credential storage for DeepSeek API key and optional DeepTutor auth token (macOS Keychain / Windows Credential Manager); secrets are write/delete/status-only from the renderer and never persisted in provider JSON.
- Desktop Provider settings UI for DeepSeek endpoint/model and optional DeepTutor endpoint/version/enable switch, with validated HTTPS-or-loopback URLs and immediate Core restart/port-token rotation.
- In-app signed updater check/install commands plus a merge-patch release-config generator; validation builds intentionally have no update channel.
- Native desktop export uses the OS Save dialog and a runtime-scoped file-write grant instead of browser-style download behavior.
- Single-instance desktop lifecycle prevents multiple shells from launching duplicate Python Cores against the same App Data.
- Core readiness now requires a successful `/api/health` response; failed restart records an explicit runtime error state.
- PyInstaller entrypoint statically imports the FastAPI application so the complete product import graph is discoverable in the packaged sidecar.
- Renderer CSP is limited to Tauri IPC and the random loopback Core; DeepSeek/DeepTutor are never called directly from renderer JavaScript.
- Unexpected Core termination invalidates only the matching runtime generation, so delayed events from an old process cannot overwrite a newly restarted Core.
- Native CI starts the packaged PyInstaller sidecar and verifies health plus the desktop token gate before Tauri bundling.

## Unchanged boundaries
DeepTutor remains an optional external capability provider. Disabling it does not remove local Psychology Growth data or core workflows. DeepSeek is also optional.

## Release gates
Source-level and Linux-host validation can verify Python/Web/config/build orchestration. Final `.dmg/.app/.exe` user releases require the corresponding macOS/Windows builders. Apple notarization and Windows signing additionally require owner credentials and therefore cannot be truthfully marked passed outside credentialed release infrastructure.
