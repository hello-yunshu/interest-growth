# Project Status

**Product:** Interest Growth
**Release candidate:** v0.6.0 — Native Execution Product
**Next development target:** v0.7 — Self-hosted Cross-device + direct Android APK
**Default Domain Pack:** Psychology
**Runtime:** Tauri 2 desktop shell + static Next.js/React + local Python/FastAPI Core

## Source candidate status

v0.6 Host integration is implemented. Product packaging/runtime verification is tracked separately:

- General Interest Core + Interest Areas: implemented;
- General + Psychology Domain Packs: implemented;
- Domain-scoped Skills/Personas/Mastery policy: implemented;
- neutral `core.interest-growth` / `capability.*` plugin namespace: implemented;
- migrations 8–12 and v0.4.1 legacy backfill: implemented;
- Area HTTP scoping and direct-ID guards: implemented;
- General LearningActivity/GroundingRef: implemented;
- Area capability composition: implemented;
- route-level PermissionBroker enforcement: implemented;
- Native-only product execution: implemented;
- v0.4/v0.4.1 desktop + Beautiful AI Interface boundaries: preserved.
- migration 11 native execution state: implemented;
- Host-owned native Knowledge Source parse/sync/rebuild/retrieve: implemented;
- native Tutor start/replay/resume/cancel with canonical Host Session/Turn: implemented;
- retired external tutor-runtime paths: removed with explicit schema migration;
- native DomainPolicy, Area capability and PermissionScope compilation: implemented.

## v0.7 implementation status (2026-08-13)

- Runtime/auth/version, threat, deployment, client and APK contracts: documented.
- Single-owner bootstrap/login, named device sessions, access/refresh tokens and per-device revocation: implemented with automated coverage.
- Atomic single-use refresh-token rotation (Gate B1): implemented and concurrency-tested.
- Database-enforced owner singleton (Gate B2): implemented via migration 14 and concurrency-tested.
- Maintenance/write lock for consistent DB + Source + Artifact backup (Gate B3): implemented and regression-tested.
- Staged rollback-safe restore (Gate B4): implemented and regression-tested across failure paths.
- Authenticated remote Compose profile: implemented as loopback HTTP; external Nginx and optional Caddy terminate client-facing TLS.
- DB + Source + Artifact backup/restore bundle tooling: implemented.
- Docker API/Web images: build and boot; health/capability/Web return 200 and an unauthenticated protected route returns 401.
- Gate B (B1–B4) is closed at the source-and-test gate level.
- ClientRuntime, desktop remote UX, Android target, emulator/device proof and signed APK delivery: not implemented.

Normative execution status and next order live in `docs/audits/V0_7_IMPLEMENTATION_AUDIT.md` and `docs/roadmap/V0_7_SELF_HOSTED_CROSS_DEVICE_PLAN.md`.

## Verified source/runtime facts

- frozen v0.5 Host archive: exact SHA-256 verified, **246 files**, original **104 tests PASS**;
- merged Host/native regression suite: **234 tests PASS**;
- standalone Native Execution Core verification: **97 tests PASS**;
- reviewed exact RAG API smoke: LlamaIndex 0.14, LightRAG 1.5, GraphRAG 3.1 and PageIndex 0.1.3 PASS;
- compileall: PASS;
- self-audit: PASS;
- Web ESLint and production static build: PASS (**15 static pages**);
- browser product flow: PASS (Home, System, Tutor and Research expose Native Core + optional DeepSeek only; retired runtime visible-text hits: 0);
- Rust `cargo check --locked`: PASS in the working tree and exact re-extracted source archive;
- macOS Apple Silicon `.app` + DMG: built locally; DMG checksum and the app copied from the mounted DMG pass strict ad-hoc `codesign` verification;
- packaged desktop launch: PASS; current packaged sidecar health/token smoke is PASS;
- Web JS/MJS syntax: **20 files / 0 parse failures**;
- config parse: **6 JSON / 26 YAML / 2 TOML / 1 plist**, all PASS;
- fresh DB includes 2 Domain Packs, 1 default Psychology Area, scoped Personas and migrations 1–14;
- real desktop Core smoke: health 200, protected runtime without token 401, correct token 200;
- exact real v0.4.1→v0.5 migration: representative legacy rows preserved and bound to default Psychology Area; legacy plugin state copied to neutral ID.

Release packaging follows a strict external verification process: generate the ZIP from a clean frozen commit, UTF-8-safe re-extract it, then rerun every available gate. The exact archive result is recorded outside the source package in the release verification report so the frozen package does not contain a self-referential archive-status claim.

## Native binary gate

The local Apple Silicon application and DMG are verified development/test artifacts. Developer ID signing, Apple notarization and real Windows Setup validation remain target-OS/toolchain/credential dependent and must never be inferred from the local ad-hoc signature.

## Compatibility identifiers intentionally retained

The following remain migration anchors, not current product branding:

- `app.psychologygrowth.desktop`
- `psychology_growth.db`
- `psychology-growth-core`
- Docker Compose legacy volume key `psychology_data`
