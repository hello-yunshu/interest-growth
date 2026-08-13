# Optional Roadmap after v0.4.1 Beautiful AI Interface

v0.4 completes the current desktop product architecture in source. Future work should follow observed use, not a desire to copy every provider/platform feature.

## UI evolution rule

Do not add more visual primitives merely to chase a design trend. Extend the v0.4.1 AI-native design system only when a real workflow needs a new state or interaction. Preserve Public Activity Trace (not private CoT), Human Approval, Context-not-Evidence, reviewable Diff, keyboard navigation and the existing renderer security boundary.

## First: native release infrastructure

1. Run the checked-in macOS Apple-Silicon and Windows x64 build matrix.
2. Exercise packaged sidecar launch, `/api/health`, restart/token rotation, single-instance behavior, native credential store and native export Save dialog.
3. Add owner signing/notarization credentials outside the repository and produce trusted installers.
4. Publish a signed Tauri updater channel only after installer validation and rollback policy are defined.
5. Back up App Data, reinstall/upgrade the desktop application and prove local DB/Source/Artifact continuity.

## Then: real-model verification

1. Real Native Tutor turn including `ask_user` pause/resume and reconnect.
2. Real local multi-file Knowledge ingestion and citation-backed retrieval.
3. Real Persona/Notebook/Practice/Co-Writer/Book proposal acceptance flows.
4. Optional real DeepSeek call using the OS credential store.
5. Delete/rebuild derivative native indexes while preserving local canonical data.

## Need-driven integrations

- literature metadata/full text: PubMed, Crossref, Semantic Scholar;
- reference manager: Zotero;
- note/export bridge: Obsidian;
- backup/storage: encrypted local archive, NAS/S3 only when requested;
- media providers: image/video/speech;
- carefully allowlisted MCP adapters for specific trusted services;
- model-transport health diagnostics and explicit compatibility checks;
- social-platform adapter only as a separate default-off plugin with immediate human confirmation.

## Before any third-party executable plugin ecosystem

PermissionBroker is insufficient for hostile code. Require signed packages, provenance, static review, process isolation, filesystem/network mediation and explicit install trust UX first.

## Do not regress

Local-first ownership, native-only execution, model-transport isolation, evidence separation, Mastery separation, Growth Memory authority, review-gated writing/book/publishing, desktop token/credential/file boundaries, explicit degradation and no clinical automation remain release invariants.
