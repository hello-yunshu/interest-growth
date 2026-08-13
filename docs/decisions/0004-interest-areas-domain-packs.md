# ADR 0004 — Interest Areas and Domain Packs

**Status:** Accepted for v0.5

## Decision

The product is renamed publicly to **Interest Growth** and becomes a general-interest system. Psychology remains the default Domain Pack.

We separate Interest Area, Capability Plugin, Domain Pack and Capability Provider instead of creating one plugin type that tries to represent all four.

## Why

The v0.4.1 core models were broadly reusable, but psychology-specific plugin IDs, prompts, Personas, Skills and dependency assumptions leaked into other interests. A simple topic selector would have allowed psychology policy to contaminate watercolor, programming and other domains.

## Data-scoping decision

Use an additive `EntityAreaBinding` layer for v0.4.1 models instead of adding `area_id` columns to every historical table in one release. This minimizes upgrade risk and enables a later explicit shared-binding model.

## Compatibility decision

Public branding changes in v0.5, but these OS-facing identifiers remain unchanged:

- Tauri bundle/keyring identifier: `app.psychologygrowth.desktop`
- database filename: `psychology_growth.db`
- Python sidecar binary basename: `psychology-growth-core`

They are migration anchors. A later rename must migrate App Data, secrets, updater identity and installed-app continuity explicitly.

## Consequences

Positive:
- Psychology behavior remains specialized and rigorous.
- General interests can use different mastery/research/content paths.
- Capability plugins and Providers can evolve independently.
- Existing v0.4.1 data has a deterministic default destination.

Costs:
- Area membership is an additional authorization/scoping layer every direct-ID route must respect.
- legacy global uniqueness constraints remain on some models until a dedicated non-additive migration.
- Domain Pack editing/import is intentionally trusted/bundled-only in v0.5.
