# 01 · Architecture

**Status:** v0.6.0 Native-only product architecture contract with planned v0.7 self-hosted extension
**Desktop shell:** Tauri 2
**Python Core:** Interest Growth FastAPI/SQLAlchemy
**Default Domain Pack:** Psychology
**Optional model transport:** DeepSeek-compatible API

## Product boundary

Interest Growth is an independent, local-first desktop product for cultivating one or more interests. Psychology is the first and default specialized Domain Pack, not the owner of the product Core.

```text
Interest Growth Desktop
  ├─ static Next.js / React UI
  └─ Tauri 2 runtime authority
       ├─ native window / single instance / updater / secure credentials
       └─ owns Interest Growth Python Core sidecar
              ├─ random 127.0.0.1 port + per-launch token
              ├─ SQLite / Source vault / Artifact vault in OS App Data
              ├─ Interest Areas + Domain Packs + Scope Binding
              ├─ Capability Plugins + PermissionBroker
              ├─ Curiosity / Research / Knowledge / Mastery / Practice
              ├─ Notes / Tutor / Writing / Living Book / Content / Growth
              ├─ Native Execution Core
              └─ optional DeepSeek-compatible model transport
```

The browser-development mode remains available. Production desktop does not require a Node.js server.

## Planned self-hosted cross-device extension

v0.7 adds an optional, single-owner server-authoritative mode:

```text
Windows/macOS remote client ─┐
Android remote client ───────┼─ HTTPS/WSS ─ TLS proxy ─ Docker FastAPI Core
Optional browser client ─────┘                         ├─ SQLite single writer
                                                       ├─ Source volume
                                                       └─ Artifact volume
```

The existing Windows/macOS local-sidecar mode remains supported. Android is remote-only initially and does not package the Python Core. Remote clients share the server's canonical data; v0.7 does not claim independently writable offline replicas or automatic local-database merging.

The Android release channel is direct APK sideloading. Google Play/AAB are not required, but Android still requires every installable APK to be cryptographically signed. Controlled releases use a project-owned private key outside Git and retain the same signing identity across upgrades.

The normative successor blueprint is `V0_7_SELF_HOSTED_CROSS_DEVICE_BLUEPRINT.md`.

## Four-layer law

The following layers must remain separate:

1. **Interest Area** — what the user is cultivating, e.g. Psychology, Watercolor, Programming.
2. **Capability Plugin** — what the product can do, e.g. research, practice, tutor, writing.
3. **Domain Pack** — subject-specific defaults/policies/personas/skills/mastery profile.
4. **Native Execution** — built-in execution of authorized product capabilities.

`Plugin = what`, `Domain Pack = how for this interest`, `Native Core = execution`, `Interest Area = where the user's work belongs`.

A Capability Plugin must not depend on a Domain Pack or model transport. A Domain Pack composes capabilities; it does not own product infrastructure.

## Psychology default-pack law

The default Area is Psychology and uses the `psychology` Domain Pack. Psychology keeps its evidence-heavy research policy, diagnosis/treatment boundary, Psychology Personas/Skills and conceptual-evidence mastery profile.

General or future Domain Packs must not inherit Psychology prompts merely because Psychology is the default Area. The `general` Domain Pack is neutral and provides the fallback behavior for interests without a specialized pack.

## Area isolation

Legacy v0.4.1 entities are scoped through `EntityAreaBinding(entity_type, entity_id, area_id)`. New Area-native models such as `LearningActivity` and `GroundingRef` carry `area_id` directly.

- HTTP uses `X-PG-Interest-Area`.
- Native Tutor REST endpoints explicitly carry the Area selector.
- List queries, direct-ID mutations, cross-entity relations and Tutor turns must validate current Area.
- Cross-Area Claim/Evidence, Practice/Tutor and TutorTurn/session relationships are rejected.
- Area capability overrides apply only to `capability.*` plugins; Core lifecycle is global.

The default Psychology Area is the migration target for all v0.4.1 legacy data.

## Canonical vs derivative data

**Canonical local:** Interest Area, Question, Topic, Source file, Evidence, Claim/version, Concept/Mastery, Practice/Attempt/Evidence, LearningActivity, LearningNote, Tutor Persona definition/scope, Tutor Session/Turn, Growth Memory, Reflection, WritingDocument/Revision decision, LivingBook/Chapter, GroundingRef, publication approval and Career Experiment.

**Derivative/execution state:** native indexes, ingestion task ids, Tutor checkpoints/events, reviewable Notebook/Practice/Writing/Book proposals, auxiliary execution Memory and Visualize plans.

Index rebuild or model-transport changes must never destroy canonical local work.

## Evidence and grounding law

Evidence and Grounding are related but not equivalent.

- `Source → Evidence → ClaimVersion → Claim` is the verified factual evidence chain.
- `GroundingRef` can point to Source, Note, Practice, LearningActivity, Book Chapter, Artifact or Project context for general-interest expression.
- Psychology factual publishing still requires verified Claim/Evidence under the Psychology Domain Pack.
- General Areas may publish learning/practice records grounded in local records, but those records must not be represented as universal factual Evidence.

## Desktop runtime law

- Tauri owns exactly one Python Core process per desktop app instance.
- Core binds only to a random `127.0.0.1` port.
- Each launch/restart receives a fresh high-entropy token.
- Desktop HTTP calls use `X-PG-Desktop-Token`; Native Tutor uses the same authenticated Host API.
- Core readiness means a successful `/api/health` response, not an open TCP port.
- Mutable data lives in OS App Data.
- Optional model secrets live in macOS Keychain / Windows Credential Manager and are not readable back by Renderer JavaScript.
- Renderer CSP permits Tauri IPC + loopback Core, not direct AI-provider HTTPS.
- External Source URLs open in the system browser through Tauri Opener.

These laws remain authoritative for `desktop-local`. `desktop-remote` and `android-remote` use authenticated HTTPS/WSS device sessions instead of the per-launch loopback token. A desktop token must never be repurposed as remote account authentication.

## Compatibility identifiers

v0.5 changes the public product identity to Interest Growth but intentionally preserves these technical migration anchors:

- `app.psychologygrowth.desktop`
- `psychology_growth.db`
- sidecar binary basename `psychology-growth-core`
- Docker Compose legacy volume key `psychology_data`

Renaming them requires a dedicated App Data / credential / updater migration and must not be mixed into the Domain refactor.

## Native execution boundary

All product workflows execute through Native Core. DeepSeek is only an optional model transport and is never a source of verified Evidence, a product-state owner or a plugin lifecycle dependency. Native execution may store checkpoints, public event sequences and auxiliary memory only; Host product models remain canonical.

## Security posture

The shipped v0.6 product is a trusted single-user local-first application. PermissionBroker enforces declared first-party plugin resource/risk boundaries, but it is not an OS/process sandbox for hostile third-party Python code.

The planned v0.7 remote mode remains single-owner but adds a hostile-network boundary: application authentication, per-device revocation, HTTPS/WSS, origin/host controls, request limits and complete backup/restore are required before remote exposure. Interest Areas are not users or tenants. Multi-tenant/public signup remains a separate future architecture.
