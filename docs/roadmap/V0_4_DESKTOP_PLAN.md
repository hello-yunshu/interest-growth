# v0.4 Desktop Plan

Status: **source implementation complete; exact-archive verification and environment-specific native/signing gates remain.**

1. Desktop architecture and recent-OS support policy — complete.
2. Static Next.js export; no production Node server — complete.
3. Tauri 2 project + platform-specific native window materials — complete.
4. Python Core PyInstaller sidecar with static FastAPI import graph — complete in source.
5. OS App Data relocation for DB/Source/Artifact vaults — complete.
6. Random loopback port + per-launch desktop token — complete.
7. Real `/api/health` Core readiness probe — complete.
8. Sidecar lifecycle, termination-state invalidation and restart/token rotation — complete.
9. Single-instance protection for shared App Data — complete.
10. Native OS credential storage for provider secrets — complete.
11. Desktop Provider settings + explicit Core recovery/restart UX — complete.
12. Desktop workspace redesign + command palette + context inspector — complete.
13. Windows 11 Mica/custom controls and macOS overlay/semantic sidebar — complete.
14. Native Save-dialog publish-pack export with runtime-scoped filesystem write — complete.
15. Renderer CSP restricted to Tauri IPC + loopback Core; no direct AI-provider network path — complete.
16. Updater-safe merge-patch release configuration and in-app check/install — complete; production keys/endpoint deliberately external.
17. Native Windows/macOS CI build matrix — complete.
18. Native CI packaged-sidecar smoke before Tauri bundle — complete.
19. Automated Python tests/self-audit/config/Web syntax/DB/OpenAPI/upgrade/archive verification — release gate.
20. Actual Next dependency install, PyInstaller build and Cargo/Tauri compile — native build-host gate; executable in checked-in CI.
21. Apple notarization / Windows code signing / signed updater publication — credentialed release-infrastructure gate only.

No gate may be marked PASS merely because its configuration exists. Missing native toolchains or signing credentials are recorded as not executed.
