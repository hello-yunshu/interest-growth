# ADR 0008 · Android generated project tracking policy

**Status:** Accepted · v0.7.0 (source + tests; not release-proven)

## Context

`tauri android init` generates a Gradle/Android project under
`apps/desktop/src-tauri/gen/android/`. The v0.7 Android closure requires this
project to be part of the auditable source of truth (Gate E §6.2 and the
GitHub Actions "unique trusted build" closure). The prompt
(`Interest_Growth_v0.7_GitHub_Actions_...执行提示词.md` §27) forbids the
"partially tracked + local link + incomplete manifest" intermediate state and
offers two valid end states:

- **A. Track the Android project**: required source/config fully tracked, root
  `SOURCE_MANIFEST` covers it, a clean checkout is directly buildable, no local
  symlink/path, CI verifies drift.
- **B. Generated + deterministic overlay**: only custom content is tracked as
  template/patch; CI runs `init` + deterministic patch and verifies the diff.

## Decision

**Adopt Option A — track the Android generated project in full.**

Rationale:

1. The Android project already carries custom, review-critical content
   (`app/build.gradle.kts`, `buildSrc` Rust plugin, `MainActivity.kt`,
   `network_security_config.xml`, `file_paths.xml`, release-signing wiring). It
   is small enough to track wholesale and would be the slowest/highest-drift
   part of a B-style `init + patch` overlay.
2. A clean checkout is directly buildable: `npx tauri android build --apk`
   from `apps/desktop/src-tauri` needs no generator re-run, which removes a
   whole class of "CI builds different source than the developer" failures.
3. Auditability is enforced, not assumed:
   - `git ls-files` includes every `gen/android/` file;
   - `scripts/generate_source_manifest.py` hashes every tracked file including
     `gen/android/` (no exclusion is added for it — the only exclusions remain
     the manifest itself and `packages/native-execution-core/`, which owns its
     own package-scoped manifest);
   - `scripts/audit_public_repo.py` proves
     `manifest entry set == git tracked file set (within scope)` in clean
     checkout, so a `gen/android` file can never be silently added or dropped.

## Consequences

- No `tauri.js`/local symlink or absolute/`node_modules` link is allowed; the
  audit's tracked-symlink integrity check fails any such file (BLOCKER-1).
- Regenerating `gen/android` (e.g. a Tauri CLI upgrade) is a normal tracked
  change: regenerate `SOURCE_MANIFEST` in the same commit.
- `file_paths.xml` is static-checked by the audit (only `cache-path export/`
  and `files-path share/` are valid) so the FileProvider surface cannot widen
  without a gate failure.
- CI must run `audit_public_repo.py` + `generate_source_manifest.py --check`
  on every clean checkout before any build is trusted.
