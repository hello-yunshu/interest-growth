# Interest Growth v0.5 — General Interest Architecture

## Product identity

Interest Growth is a local-first, multi-interest learning, practice, research, reflection and expression system. Psychology is the default first Domain Pack, not the product core and not a parent namespace for other interests.

The architecture separates four concepts:

1. **Interest Area** — what the user is cultivating (Psychology, watercolor, programming, photography, etc.).
2. **Capability Plugin** — what the product can do (curiosity, research, knowledge/RAG, mastery, practice, notebook, tutor, writing, book, content...).
3. **Domain Pack** — how those capabilities should behave for a subject/interest family (prompts, evidence policy, mastery profile, skills, personas, capability defaults).
4. **Capability Provider** — optional external execution (DeepSeek, DeepTutor, future providers).

`Plugin = what`, `Domain Pack = how`, `Provider = who executes`, `Interest Area = what the user is cultivating`.

## Ownership layers

```text
Interest Growth Desktop
├── General Interest Core
│   ├── InterestArea
│   ├── EntityAreaBinding
│   ├── AreaCapabilitySetting
│   ├── LearningActivity
│   └── GroundingRef
├── Capability Plugins
│   ├── Curiosity
│   ├── Research & Evidence
│   ├── Knowledge & RAG
│   ├── Mastery / Concept Graph
│   ├── Practice / Notebook / Tutor
│   ├── Co-Writer / Living Book / Content
│   └── Growth / Reflection / Career
├── Domain Packs
│   ├── general
│   └── psychology (default)
└── Optional Capability Providers
    ├── DeepSeek
    └── DeepTutor
```

The user-owned database, Source vault, Artifact vault, Evidence/Claim ledger, Mastery, Practice, Notes, Writing and Books remain canonical local product data.

## Interest Area scoping

v0.5 intentionally avoids destructive `area_id` ALTER operations over every legacy v0.4.1 table. Existing domain objects are scoped through `EntityAreaBinding(entity_type, entity_id, area_id, sharing, is_primary)`.

New v0.5-native objects that need direct area ownership use `area_id` directly (for example `LearningActivity`, `GroundingRef`, `AreaCapabilitySetting`). A SQLAlchemy `before_flush` hook binds new legacy-model entities to the current Area. Direct-ID routes must also enforce current-Area membership; list filtering alone is not sufficient.

All v0.4.1 legacy rows are backfilled to the default Psychology Area during migration 9. Explicit `sharing=shared` is the only supported cross-Area sharing semantics; ordinary objects remain private to their Area.

## Domain Packs

### General Interest

The General pack is neutral and suitable for conceptual, procedural, creative and project-based interests. It:

- does not inject psychology language;
- treats practical demonstrations/worked examples as valid research inputs;
- uses an adaptive mastery profile: unfamiliar → familiar → understand → practice → apply → reflect → transfer → self_directed;
- permits content grounded in Notes, Activities, Practice, Sources, Artifacts and Book Chapters, while labeling personal/practice records as such rather than universal facts;
- provides neutral Personas and Skills.

### Psychology (default)

The Psychology pack preserves the stronger v0.4.1 discipline:

- psychology-specific research/evidence Skills and Personas;
- diagnosis/treatment boundary rules;
- systematic review / meta-analysis / primary study preferences where appropriate;
- conceptual + evidence mastery profile;
- psychology factual publication requires verified Claim/Evidence chains and Human Review.

Psychology is therefore a specialized policy pack layered on general capabilities, not a condition of using those capabilities.

## Capability composition

Every Interest Area receives Domain Pack capability defaults and may override individual `capability.*` plugins. Area overrides cannot change `core.*` or `integration.*` lifecycle. Core/provider enablement is global; Area capability composition is local.

Capability plugins depend on `core.interest-growth`, not on a psychology plugin or on `integration.deeptutor`.

## Permission boundary

The first-party `PermissionBroker` now participates in route execution. Sensitive reads, writes and network/LLM operations must be declared by the owning plugin manifest and checked at the route boundary. Tests remove permissions dynamically and require the API to return 403.

This is trusted first-party capability enforcement, **not** hostile-code sandboxing. Arbitrary executable third-party plugins remain unsupported.

## Provider boundary

DeepSeek and DeepTutor adapters receive Domain context but do not own Domain policy. DeepTutor remains a separately disableable provider plugin and sidecar. Disabling it leaves local Areas, Sources, Notes, Practice, Writing, Books and Growth Memory intact.

Retrieval remains `candidate_not_evidence`; provider memory remains auxiliary; provider Book/Notebook/Persona/Skill state is a projection.

## Desktop boundary

v0.4 desktop guarantees remain:

- Tauri 2 static desktop shell;
- Python/FastAPI Core sidecar;
- random loopback port and per-launch desktop token;
- OS App Data ownership;
- OS credential store for secrets;
- single instance;
- signed-updater architecture;
- macOS 13+ Apple Silicon / Windows 11 24H2+ x64 policy;
- renderer cannot directly call external AI providers.

The OS-facing identifier, keyring service, database filename and sidecar binary filename deliberately retain v0.4 compatibility identifiers in v0.5. They are technical migration anchors, not product branding. Renaming them requires a dedicated App Data/credential/update migration.

## Migration contract

v0.5 changes the schema migration contract from ledger-only additive assumptions to executed migrations after the v0.4.1 baseline:

- 1–7: legacy baseline;
- 8: create general-interest schema;
- 9: seed Domain Packs/default Psychology Area and backfill legacy entity bindings;
- 10: migrate persisted legacy `psychology.*` plugin states to neutral capability IDs while preserving old rows as compatibility history.

Fresh installs create the current schema and record 1–10. Existing databases must contain the complete 1–7 legacy ledger before migration proceeds.

## Known compatibility constraint

`knowledge_bases.name` and user Persona names retain legacy global uniqueness constraints. This does not leak data across Areas, but identical human-readable names cannot yet be duplicated in two Areas. Removing those constraints safely requires a dedicated non-additive migration and is intentionally not hidden inside v0.5's additive compatibility migration.
