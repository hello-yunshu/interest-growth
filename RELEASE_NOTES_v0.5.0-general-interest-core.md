# Interest Growth v0.5.0 — General Interest Core

v0.5 separates the product from its original Psychology-first domain without weakening the Psychology learning/research safeguards.

## Highlights

- public product identity becomes **Interest Growth**;
- Psychology remains the default Domain Pack instead of the product Core;
- users can create multiple Interest Areas using General or Psychology behavior;
- Area-scoped Question/Topic/Source/Evidence/Claim/Practice/Note/Tutor/Writing/Book/Growth flows;
- General Areas support practical/creative/project LearningActivity and flexible GroundingRef expression;
- Psychology keeps verified Claim/Evidence factual publication, diagnosis/treatment boundary and evidence-heavy research policy;
- Capability Plugin IDs are neutral and legacy `psychology.*` plugin state is migrated;
- Domain Packs own Personas, Skills, mastery profiles and capability defaults;
- System UI can enable/disable `capability.*` per Interest Area without changing Core/Provider lifecycle;
- PermissionBroker now participates in route execution and is verified by dynamic 403 regressions;
- cross-Area direct-ID issues found during the refactor were fixed and regression-tested.

## Migration

v0.5 introduces explicit migration implementations after the v0.4.1 baseline:

- 1–7: legacy v0.4.1 ledger;
- 8: General Interest schema;
- 9: General/Psychology Domain seeds + default Psychology Area + legacy entity scope backfill;
- 10: legacy `psychology.*` plugin-state copy to neutral IDs.

A real v0.4.1 database containing representative Question, Topic, Source, Evidence, Claim/ClaimVersion, LearningNote, PracticeItem, WritingDocument and `psychology.curiosity=disabled` state was upgraded during release validation. All sentinel rows survived, all representative entities received primary Psychology Area bindings, the old plugin row remained, and `capability.curiosity` inherited the disabled state.

## Validation snapshot

The source candidate validation established:

- **104/104 tests PASS** (collected once, executed in bounded complete groups);
- **41 tables**;
- **19 plugin states**;
- **20 feature flags**;
- **2 Domain Packs**;
- **1 default Psychology Area**;
- **6 Persona scopes**;
- schema ledger **1–10**;
- OpenAPI **109 paths / 129 operations**;
- real desktop Core token smoke **200 / 401 / 200**.

The final source ZIP is separately re-extracted and revalidated; its SHA-256 and exact-archive results live in the external release verification report.

## Compatibility

The following technical identifiers intentionally remain unchanged to preserve installed-app/App Data/credential/sidecar continuity:

- `app.psychologygrowth.desktop`
- `psychology_growth.db`
- `psychology-growth-core`
- Docker Compose legacy volume key `psychology_data`

They are migration anchors, not the public product name.

## Provider boundary

DeepSeek and DeepTutor remain optional execution providers. DeepTutor is not a fork parent, product namespace, required Capability dependency or canonical data owner.

## Known compatibility limitation

Legacy Knowledge Base names and Tutor Persona names remain globally unique in v0.5. This can prevent identical names in two Areas but does not authorize cross-Area access. Removing these constraints safely requires a future explicit non-additive migration.

## Native release note

Source validation and native signed installer validation are separate gates. A DMG/Setup.exe must not be claimed as validated unless actually built and smoke-tested on the target OS with the required toolchain and signing credentials.
