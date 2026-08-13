# v0.4.1 Beautiful AI Interface · UI + Code Audit

## Executive result

Psychology Growth v0.4.1 adopts the interaction concepts demonstrated by Beautiful UI as an **in-house AI-native desktop design system** and simultaneously hardens several v0.4.0 implementation details discovered during the audit.

The release does not vendor or fork the reference site and does not alter the independent-product / optional-provider boundary established in v0.3.1–v0.4.0.

## Audit scope

Reviewed:

- the Beautiful UI reference's interaction inventory and semantics;
- every current Web/Desktop product surface;
- Tauri renderer privileges and CSP;
- Python Core desktop token boundary;
- Provider secret/nonsecret configuration lifecycle;
- Human Review workflows;
- Tutor stream/activity rendering;
- external/source URL rendering;
- generated SVG preview;
- Next.js 16 tooling compatibility;
- v0.4 desktop runtime/provider regression suite.

## Source-derived design findings

The reference presents nineteen AI-native primitives: Loading State, Thinking, Streaming Text, Approval Card, Tool Chips, Task Rows, Chat, Prompt Bar, Recommendation Card, Context Cards, Diff Table, Records Table, Filter Table, Sidebar Nav, Search, Insight Cards, Code Block, Fine-tune Card and Selection Actions.

Psychology Growth maps all nineteen concepts to real product workflows. It intentionally changes one important semantic: the reference “Thinking” presentation becomes **Public Activity Trace** only. Hidden/private model chain-of-thought is not a product UI surface.

See `docs/design/BEAUTIFUL_UI_ADOPTION.md` for the complete mapping.

## Findings and fixes

### P1 · Obsolete Next.js 16 lint command

**Before:** `apps/web/package.json` used `next lint`.

**Problem:** Next.js 16 removed the `next lint` command. A future dependency-installed build/lint gate would fail or be misleading.

**Fix:**

- `lint` now calls ESLint directly;
- added flat `eslint.config.mjs` using Next core-web-vitals config;
- added explicit ESLint dependencies.

**Release gate:** when registry/dependencies are available, run the actual npm lint/build. The current sandbox must not claim that dependency-installed gate if packages cannot be installed.

### P1 · Browser-native modal workflows bypassed reviewable desktop UX

**Before:** Research, Learning and Career still used `window.prompt` / `window.confirm` for meaningful product decisions.

**Risk:** invisible/transient prompts are not composable with provenance, status or human-review semantics and feel like a Web fallback inside a desktop app.

**Fix:** replaced them with explicit `ApprovalCard` review surfaces with structured fields and cancel/confirm actions.

**Invariant:** renderer product code contains no `window.prompt`, `window.confirm` or `window.alert`.

### P1 · Raw SVG/HTML insertion in privileged renderer

**Before:** Content preview used `dangerouslySetInnerHTML` for generated SVG.

**Risk:** current backend SVG generation escapes its dynamic text, but raw HTML insertion remains an unnecessary privileged-renderer injection sink and creates a dangerous maintenance assumption if generation changes later.

**Fix:** `SafeSvgPreview` renders encoded SVG through an `<img>` data URL. `dangerouslySetInnerHTML` is forbidden by tests/self-audit.

### P1 · Activity UI could accidentally expose private reasoning categories

**Before:** the first UI adaptation separated answer deltas, but a future/raw provider event categorized as `thinking`/`reasoning` could be displayed when imitating the reference Thinking primitive.

**Fix:** `ActivityTrace` explicitly filters private categories including `thinking`, `reasoning`, `chain_of_thought`, `cot` and `internal_thought`. Answer deltas are rendered separately in `StreamingText`.

### P1 · Public Activity needed an allowlist, not only a private-category blocklist

**Before:** private reasoning names were blocked, but unknown event types could still be rendered and a `tool_result` could expose its raw result body inside the activity surface.

**Fix:** Activity Trace now uses an explicit public category allowlist. Tool calls/results expose tool identity/status only; raw tool-result content belongs in purpose-built Context/Artifact surfaces, not an activity log. Unknown categories are hidden by default.

### P2 · Prompt composer showed source/command glyphs without real actions

**Before:** the generic Prompt Bar visually rendered `@` and `/` buttons even when no product handler existed.

**Fix:** these controls are only interactive when real callbacks are provided. The default composer no longer advertises fake actions.

### P1 · Provider settings write had a crash-consistency window

**Before:** non-secret provider settings could remove the current JSON before replacing it with the new temporary file.

**Risk:** a process/OS failure in that interval could lose non-secret endpoint/model settings.

**Fix:**

1. write temporary file;
2. flush + `sync_all`;
3. rotate current file to `.json.bak`;
4. rename temporary file into current path;
5. restore backup if final promotion fails;
6. load path can recover from backup;
7. delete backup only after successful promotion.

Provider secrets remain outside this JSON in native credential storage.

### P2 · Home navigation nested interactive controls

**Before:** several Next `<Link>` elements wrapped `<button>` elements, producing invalid nested interactive markup.

**Fix:** navigation actions are now styled links using the shared button visual classes. This preserves keyboard/semantic navigation without nested interactive elements.

### P2 · Source canonical URL was rendered without protocol filtering

**Before:** stored `canonical_url` could be used directly as an anchor.

**Risk:** the Domain permits arbitrary strings (DOI/identifier/URL). A malformed or unsafe scheme should not become a privileged renderer navigation target.

**Fix:** `SourceLink` only permits parsed `http:` / `https:` URLs; other values remain plain text. In desktop mode the URL is handed to Tauri Opener and the OS default browser instead of navigating the privileged main WebView.

### P2 · Native Save flow reviewed against Tauri scope semantics

Current desktop export uses the native Save dialog and then `fs.writeFile` for the selected destination. The capability exposes the write-file command, not a broad write-all permission; the selected path is runtime-scoped by the native dialog flow.

**Decision:** retain this implementation in v0.4.1. A dedicated Rust “save artifact” command could reduce renderer filesystem authority further in a later hardening release, but current behavior follows the deliberate user-selected-path boundary and is not a release blocker.

## Beautiful UI adoption completeness

Implemented primitives in `apps/web/components/BeautifulUI.js`:

- `PixelLoader`
- `ActivityTrace`
- `StreamingText`
- `ApprovalCard`
- `ToolChips`
- `TaskRows`
- `ChatPanel`
- `PromptBar`
- `RecommendationCard`
- `ContextCards`
- `DiffTable`
- `RecordsTable`
- `FilterTabs`
- `InsightCards`
- `CodeBlock`
- `FineTunePanel`
- `SelectionActions`
- `SafeSvgPreview` (Psychology Growth-specific hardening primitive)

The remaining source concepts, Sidebar Nav and Search, are implemented as grouped DesktopShell navigation and the keyboard Command Palette.

## Product-level integration reviewed

- Home: insights/recommendation/tasks.
- Curiosity: prompt/filter/records/recommendation.
- Tutor: chat/stream/public activity/tools/wait-for-input approval.
- Research: streamed result/source workflow/invalidation review.
- Knowledge: ingestion tasks/RAG context/provenance records.
- Learning: practice review/mastery-evidence decision.
- Writing: selection actions/diff/accept-reject.
- Career: reversible experiment review.
- Growth: low-pressure insight surfaces.
- Living Book: context/tasks/proposal/spine approvals.
- Content: Publish Guard/review/safe SVG preview.
- System: provider inspector/runtime/plugin/feature records.

## Boundaries that remain PASS

The audit found no reason to redesign these v0.4 boundaries:

- Psychology Growth remains the canonical product; DeepTutor is optional provider only.
- no product plugin hard-depends on `integration.deeptutor`;
- no direct `import deeptutor` in product Domain/runtime;
- renderer cannot directly connect to AI Provider HTTPS endpoints;
- desktop Core remains random loopback + per-launch token protected;
- Provider secrets remain native credential-store data and cannot be read back to JS;
- Source/Evidence/Claim, Practice/Mastery and Co-Writer review semantics remain human gated;
- no automatic social publication;
- no raw private chain-of-thought surface added.

## Validation strategy

Required source gates:

```bash
python -m pytest -q
python -m compileall -q apps packages adapters plugins scripts tests
python scripts/self_audit.py
```

Plus:

- parse every Web JS/JSX source;
- parse JSON/YAML/TOML/plist configuration;
- scan renderer for native browser modals/raw HTML/private-reasoning display paths;
- scan source for secrets/private paths/provider-source vendoring;
- empty DB initialization + OpenAPI count;
- previous-release DB upgrade sentinel;
- real source `desktop_core.py` HTTP token smoke;
- exact tracked-file ZIP extraction and re-run all gates.

## Source-tree validation result

Before release freeze, the v0.4.1 candidate passed:

- Python regression suite: **89/89 PASS**;
- compileall: PASS;
- self-audit: PASS;
- Web JS/JSX syntax parse: **19 files / 0 failures**;
- config parse: 6 JSON / 22 YAML / 2 TOML / 1 plist;
- clean DB: 33 tables / 19 plugins / 20 feature flags / 4 personas / migration ledger 1–7;
- OpenAPI: 102 paths / 120 operations;
- real source desktop Core smoke: health 200 / protected-no-token 401 / protected-correct-token 200;
- real v0.4.0-created DB → v0.4.1 initialization: sentinel preserved;
- immutable Chinese baseline files remain byte-identical to their ASCII aliases;
- no live API key/private key/private absolute path found in the release candidate.

The exact tracked-file archive must repeat these gates after extraction before it is called verified.

## Environment-specific gates

This audit must not claim native package compilation/signing unless executed on the appropriate build infrastructure with dependencies and credentials:

- dependency-installed Next.js ESLint/build;
- Cargo/Tauri native compile;
- PyInstaller packaged sidecar build;
- Windows NSIS package and code signing;
- macOS app/DMG signing + notarization;
- signed updater publication;
- live DeepSeek/DeepTutor provider calls.

The repository's native CI is the intended handoff for unsigned native validation builds; secrets remain external.
