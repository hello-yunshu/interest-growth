# 10 · Acceptance Tests

## Automated suite

v0.6 must preserve applicable historical contracts, add explicit General Interest / Area isolation contracts and enforce native-only execution. The exact test count is recorded only after the final frozen-tree run; do not hard-code a stale count here.

Required v0.5 contracts include:

1. Fresh install creates General + Psychology Domain Packs and one default Psychology Interest Area.
2. A General/Watercolor Area can Quick Explore/Research without Psychology prompt leakage.
3. Psychology retains evidence-heavy research, diagnosis/treatment boundary and Psychology Personas/Skills.
4. Question/Topic/Source/Evidence/Claim/Concept/Practice/Note/Tutor/Writing/Book data are Area-isolated in lists **and direct-ID mutations**.
5. Cross-Area Evidence→Claim, Practice→TutorSession and TutorTurn→Session operations are rejected.
6. Native Tutor start/reply/resume/cancel validates Turn belongs to current Area and active Session.
7. Source invalidation validates Area before mutating verification state.
8. Native Notebook and Practice proposals are Area-local and require explicit acceptance.
9. General Mastery uses the adaptive profile; Psychology preserves the conceptual-evidence profile.
10. General Content may use local GroundingRefs such as Note/Practice/LearningActivity without pretending they are scientific Evidence.
11. Psychology factual publishing still requires verified Claim/Evidence and Human Review.
12. Area capability overrides apply only to `capability.*`; Core lifecycle and model transport cannot be Area-overridden.
13. PermissionBroker dynamically blocks a route when its manifest loses a required resource permission or LLM/network risk declaration.
14. No current plugin manifest uses a `psychology.*` stable ID; legacy aliases remain migration compatibility only.
15. No product plugin depends on a model transport; product execution remains native when DeepSeek is absent.
16. Domain-specific Skills/Personas live under `domains/*`; no root generic Skills directory owns Psychology semantics.
17. v0.4.1 legacy rows upgrade without loss and receive primary bindings to the default Psychology Area.
18. Legacy `psychology.*` plugin states are preserved and copied to neutral capability IDs with state continuity.
19. Desktop random loopback/token, App Data, credential-store, single-instance, Save-dialog, updater and native URL-opener security contracts remain intact.
20. Beautiful AI Interface remains a public activity/review surface, never private chain-of-thought.
21. Renderer has no browser-native prompt/confirm/alert, no `dangerouslySetInnerHTML`, no direct Provider CSP access and no broad `fs:write-all`.
22. Curiosity Topic state uses `active_topic`; the old stale `promoted` UI state must not return.

## Required source-tree gates

```bash
python -m compileall -q apps packages scripts tests
python -m pytest -q
python scripts/self_audit.py
```

Also:
- parse every Web JS/JSX file with an available parser;
- parse all YAML, JSON, TOML and plist configuration;
- inspect tracked files for secrets, personal runtime data, caches/build output and accidental external workflow-runtime code;
- preserve the immutable historical Chinese baseline files byte-for-byte with their ASCII aliases.

## Fresh database gate

With a temporary empty SQLite URL, final verification must prove:

- **41 product tables**;
- **19 global plugin states**;
- expected Feature Flag count from the frozen build;
- **2 Domain Packs** (`general`, `psychology`);
- exactly one default Psychology Interest Area;
- **6 built-in Persona scopes** (2 General + 4 Psychology);
- schema ledger **1–12**;
- exact frozen OpenAPI path/operation counts.

## Exact v0.4.1 → v0.5 upgrade gate

Use the real v0.4.1 code to create an old database and representative sentinel rows (at minimum Question, Topic, Source, Evidence, Claim/ClaimVersion, LearningNote, Practice, WritingDocument and a legacy plugin state where feasible). Then initialize the same DB with frozen v0.5 code and prove:

- sentinel rows survive unchanged;
- migrations advance to 1–10;
- every representative legacy scoped entity receives a primary `EntityAreaBinding` to the default Psychology Area;
- General + Psychology Domain Packs exist;
- old `psychology.*` plugin-state rows remain compatibility history;
- corresponding neutral plugin IDs inherit prior enabled/disabled state.

Do not substitute ORM schema comparison for this runtime upgrade test.

## Desktop runtime gate

From frozen source/archive:

- launch `scripts/desktop_core.py` with a temporary App Data root, random loopback port and desktop token;
- `/api/health` → 200;
- protected runtime endpoint without token → 401;
- same endpoint with correct token → 200;
- service identity → `interest-growth-api` and version → frozen v0.5 version.

## Native build gates

On real macOS/Windows build runners:

1. install locked/reviewed dependencies;
2. build PyInstaller sidecar for exact target triple;
3. execute packaged sidecar and perform health/token smoke;
4. run Next static export;
5. compile Tauri app;
6. exercise credential storage, native Save, single instance, Core restart and URL opener;
7. create native bundles.

Signed public installers additionally require Apple Developer ID/notarization, Windows code signing and Tauri updater signing material. Missing native toolchain/credentials are **not executed**, never PASS.

## Archive gate

A release ZIP is accepted only after packaging `git ls-files` from a clean frozen commit, UTF-8-safe extraction into a new directory, and rerunning every gate available in the current environment from that exact archive.
