# Psychology Growth v0.4.1 · Beautiful AI Interface

v0.4.1 is a UI/interaction and desktop-hardening release built on the independent v0.4.0 Tauri/Python desktop runtime. It does not change Psychology Growth into a DeepTutor-derived product and does not introduce a destructive database migration.

## AI-native design system

The desktop Web UI now implements an in-house design system inspired by the interaction primitives demonstrated by Beautiful UI:

- Loading / active work;
- Public Activity Trace;
- Streaming answers;
- Human Approval;
- Tool Chips;
- Task Rows;
- Chat;
- Prompt Bar;
- Recommendations;
- RAG Context;
- Diff review;
- Records + Filters;
- grouped Sidebar;
- Command Search;
- Insight cards;
- Code/artifact display;
- Provider Fine-tune/Inspector;
- Selection Actions.

The reference “Thinking” concept is intentionally narrowed to **public runtime activity**. Hidden/private model reasoning is never rendered.

## Product surfaces upgraded

- Home: calm insights + next-step recommendation + active tasks.
- Curiosity: AI-native prompt/filter/records with Quick Explore visibly non-evidence.
- Tutor: chat + streaming answer + tool chips + public activity trace + in-turn approval.
- Research: streamed candidate result, source workflow and explicit source invalidation review.
- Knowledge: RAG context/provenance and ingestion tasks.
- Learning: structured Practice review and explicit Mastery Evidence decision.
- Writing: selection actions + reviewable diff before canonical text changes.
- Career: reversible experiment review without browser prompts.
- Growth: low-pressure insight presentation.
- Living Book: source context + task state + proposal/spine confirmation.
- Content: Publish Guard + safe generated-card preview.
- System: provider/runtime/plugin/feature inspector surfaces.

## Audit fixes

- Replaced removed Next.js 16 `next lint` wrapper with explicit ESLint flat config/CLI.
- Removed product `window.prompt`, `window.confirm` and `window.alert` flows.
- Removed `dangerouslySetInnerHTML` generated-SVG preview from the privileged renderer.
- Added explicit private-reasoning category filtering to Public Activity Trace.
- Tightened Public Activity to an explicit event allowlist; tool-result raw bodies are not displayed in the activity surface.
- Removed nonfunctional `@`/`/` Prompt Bar controls unless a real product handler is supplied.
- Added recoverable/fsynced atomic-ish rotation for non-secret Provider settings JSON.
- Filtered clickable Source URLs to `http:` / `https:` protocols and route desktop opening through Tauri Opener/system browser.
- Removed nested Next Link + button interactive markup from Home navigation actions.
- Re-reviewed native Save dialog / runtime-scoped file-write boundary; no broad `fs:write-all` permission added.

## Compatibility

- Windows: Windows 11 24H2+ x64.
- macOS: macOS 13+ Apple Silicon.
- DeepTutor compatibility baseline remains v1.5.11 as an optional provider.
- DeepSeek remains optional.
- v0.4.1 contains no intended destructive Domain schema change.

## Release validation

Source-tree regression suite at freeze: **89/89 PASS**.

The release candidate must pass the full Python regression suite, compileall, self-audit, JS/JSX/config parsing, empty DB/OpenAPI validation, desktop Core token smoke, previous-release DB sentinel upgrade and exact archive revalidation.

Dependency-installed npm lint/build, Cargo/Tauri compilation, PyInstaller packaging, native signing/notarization and live external Provider behavior remain build-environment gates and must not be reported as PASS unless actually run.
