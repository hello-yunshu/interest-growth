# v0.5 General Interest Core — Implementation Audit

## Scope

This audit follows `V0_4_1_GENERAL_INTEREST_AUDIT.md` and evaluates whether the implementation is genuinely multi-interest rather than a psychology product with renamed UI.

## Resolved P0 findings

### First-class Area and Domain ownership

Resolved. `InterestArea`, `DomainPack`, `MasteryProfile`, `AreaCapabilitySetting`, `EntityAreaBinding`, `PersonaScope`, `LearningActivity` and `GroundingRef` now exist. Psychology is seeded as the default Area/Pack; General is a separate neutral pack.

### Psychology namespace as product skeleton

Resolved for current capability manifests. Product plugins use `core.interest-growth` / `capability.*`. Historical `psychology.*` IDs survive only in a compatibility alias map and persisted legacy rows.

### Psychology prompt leakage

Resolved in Quick Explore, Research, Tutor, Co-Writer, Living Book and Content paths. Domain behavior comes from active Domain Pack context. A General watercolor regression explicitly forbids psychology language and systematic-review/meta-analysis defaults.

### Cross-Area ownership

Resolved for tested primary flows. Lists filter by Area and direct-ID actions require ownership. Additional regressions cover cross-Area Evidence→Claim, Source invalidation, Note mutation, Practice↔Tutor Session, Persona/Skill context, Content card Topic and browser-supplied Tutor Turn IDs.

### Upgrade safety

Implemented migrations 8–10 replace the previous assumption that `create_all + ledger` alone is sufficient. Exact v0.4.1 migration verification is complete: representative legacy rows survived, received Psychology Area bindings, and legacy plugin state was copied to neutral IDs without deleting history.

## Resolved P1 findings

### Psychology-only mastery/practice/content path

Resolved by Domain Mastery Profiles, LearningActivity and GroundingRef. Psychology keeps its conceptual/evidence profile and factual Claim/Evidence publication gate; General may use practice/activity/note grounding without mislabeling it as universal Evidence.

### PermissionBroker only partially executed

Resolved for capability route surfaces by `require_plugin_access`, which combines plugin/Area availability with read/write/risk checks. A regression mutates the live Curiosity manifest and proves missing `question:write` or `llm` causes an HTTP 403.

### Area capability lifecycle confusion

Resolved. Area overrides accept only known `capability.*` IDs. Core and `integration.*` lifecycle remain global.

### Frontend `promoted` state mismatch

Resolved. Curiosity uses backend state `active_topic`.

## New issues discovered during v0.5 audit

### Tutor browser-supplied Turn IDs

Found and fixed. `submit_user_reply`, `resume_turn` and `cancel_turn` previously loaded a browser-provided Turn ID without re-checking Area and Tutor Session. A shared helper now requires both before exposing the upstream turn reference.

### Source invalidation direct-ID guard

Found and fixed earlier in v0.5. Revoking Source verification now requires Source ownership in the active Area before transitive invalidation.

### Practice Tutor Session and Question Notebook dedup

Found and fixed. Practice Attempt validates Tutor Session Area. DeepTutor Question Notebook import deduplicates per Area instead of globally.

### Tutor context Persona and Content card Topic

Found and fixed. Tutor context Patch validates Persona scope; SVG card Topic references cannot cross Area.

## Remaining limitations

1. `knowledge_bases.name` and Tutor Persona names retain legacy global uniqueness. This is a usability constraint, not an Area data leak; safe removal requires a non-additive migration.
2. PermissionBroker is trusted first-party enforcement, not an OS/process sandbox.
3. Domain Packs are bundled/trusted configuration in v0.5; arbitrary downloaded code/config is not enabled.
4. Native DMG/Windows installer compilation/signing remains a target-OS CI gate when the current environment lacks Rust/PyInstaller/signing credentials.
5. Legacy OS identifiers stay intentionally psychology-named for upgrade continuity; they are not current public brand identity.

## Validation status

Current source candidate validation: 104/104 tests PASS (complete bounded groups), compileall PASS, self-audit PASS, 20 Web JS/MJS parse with zero failures, 41-table fresh DB, migrations 1–10, 109 OpenAPI paths / 129 operations, real desktop Core 200/401/200 token smoke, and exact v0.4.1→v0.5 sentinel migration PASS.

## Release recommendation

Freeze only from a clean Git commit. Generate the source ZIP from tracked files, UTF-8-safe re-extract it, and rerun every available gate from the exact archive. Native signed installers remain a separate target-OS gate.
