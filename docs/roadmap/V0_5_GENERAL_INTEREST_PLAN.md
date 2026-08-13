# v0.5 General Interest Core — Development Plan

## Goal

Turn the psychology-first v0.4.1 product into a reusable multi-interest system while preserving every v0.4.1 user's data and the Psychology pack's evidence-heavy behavior.

## Gate A — Scope and migration foundation

- [x] Add InterestArea, DomainPack, MasteryProfile, AreaCapabilitySetting, EntityAreaBinding, PersonaScope, LearningActivity and GroundingRef.
- [x] Implement executed migrations 8–10.
- [x] Backfill all legacy scoped entities into the default Psychology Area.
- [x] Migrate persisted `psychology.*` plugin states to neutral plugin IDs without deleting history.

## Gate B — Capability / Domain separation

- [x] Neutralize capability plugin IDs and dependencies.
- [x] Remove root bundled Skills; Domain Packs own Skills and Personas.
- [x] Add General and Psychology Domain Packs.
- [x] Move psychology Quick Explore/Research/Content/Mastery policy out of Core into Psychology pack.
- [x] Preserve compatibility aliases only where needed for v0.4.x clients/data.

## Gate C — End-to-end Area scope

- [x] HTTP `X-PG-Interest-Area` context.
- [x] Tutor WS Area context.
- [x] auto-binding of newly created legacy entities.
- [x] direct-ID area guards.
- [x] cross-Area Evidence/Claim, Source invalidation, Practice/Tutor and Tutor Turn protection.
- [x] Area-local Growth Memory and Persona/Skill selection.

## Gate D — General learning paths

- [x] General Quick Explore and Research no longer leak psychology policy.
- [x] adaptive mastery profile for non-psychology interests.
- [x] LearningActivity for creative/project/practical learning.
- [x] GroundingRef so General Content can use owned learning/practice records without pretending they are universal Evidence.
- [x] Psychology publication still requires verified Claim/Evidence chains.

## Gate E — Product UI and composition

- [x] Area switcher/create flow.
- [x] Domain Pack selection when creating an Area.
- [x] Area header on HTTP and query context on Tutor WS.
- [x] Tutor Persona/Skills loaded from active Domain Pack.
- [x] Content UI supports General GroundingRefs.
- [x] System UI exposes Area capability composition separately from global Plugin/Provider lifecycle.

## Gate F — Enforcement and release hardening

- [x] Route-level PermissionBroker resource/risk enforcement for capability routes.
- [x] Dynamic regression proving missing manifest permission/risk yields 403.
- [x] Area capability API rejects core/provider/unknown IDs.
- [x] DeepTutor optional-provider boundary preserved.
- [x] Final exact v0.4.1 → v0.5 database upgrade verification with representative sentinel rows.
- [x] Rewrite v0.5 self-audit and current documentation.
- [x] Full source validation.
- [x] Release-process contract defined: clean commit → exact tracked-file ZIP → archive revalidation → external verification report. Exact archive result is recorded outside the frozen source package.

## Deliberately deferred

- custom executable third-party Domain Packs/plugins;
- multi-user/cloud sync;
- automatic cross-Area sharing;
- removal of legacy OS-facing `app.psychologygrowth.desktop` / DB / keyring / sidecar compatibility identifiers;
- non-additive migration to make legacy globally unique Knowledge Base / Persona names area-local.
