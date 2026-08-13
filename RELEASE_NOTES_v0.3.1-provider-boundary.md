# Psychology Growth v0.3.1 — Provider Boundary Correction

v0.3.1 does not add a new product identity around DeepTutor. It does the opposite: it makes the existing architecture accurately reflect that Psychology Growth is the product and DeepTutor is an optional external capability provider.

## Why this release exists

The v0.3.0 codebase did **not** vendor or fork DeepTutor source, but a new audit found three misleading couplings:

- product-level wording such as `DeepTutor-Powered` and `DeepTutor Native Learning Runtime` over-centered the upstream provider;
- several local Psychology Growth plugins had a hard manifest dependency on `integration.deeptutor`;
- provider calls mostly obeyed `DEEPTUTOR_ENABLED` but did not consistently obey the integration plugin lifecycle state.

That combination could make a technically independent product behave and read like a DeepTutor-derived edition. v0.3.1 corrects the boundary.

## Changed

- Renamed current product/runtime documentation to **Independent Learning Runtime**.
- Added ADR `0002-deeptutor-optional-provider.md`.
- Added `THIRD_PARTY_NOTICES.md` describing DeepTutor as an optional third-party capability provider.
- Removed every hard `integration.deeptutor` dependency from Psychology Growth product plugins.
- Renamed the integration manifest to **DeepTutor Capability Provider** and clarified that it never owns product data or identity.
- Added `apps/api/pg_api/capability_providers.py` as the single provider execution gate.
- DeepTutor execution now requires both deployment configuration and the integration plugin to be enabled.
- Disabling the provider no longer disables Knowledge, Practice, Learning Note, Persona, Memory Graph, Tutor Session, Living Book, or other local canonical capabilities.
- System UI now presents external integrations as **Capability Providers** and can enable/disable the provider plugin.
- Local development `make run` now binds to `127.0.0.1` by default.
- Added architecture regression tests for no vendoring, no direct upstream imports, no product hard-dependencies, and local behavior after provider disable.
- Expanded self-audit to enforce the provider boundary and provider-neutral current product identity.

## Preserved

All v0.3 product data and workflows remain Psychology Growth-owned:

- Source / Evidence / Claim and verification state;
- Concept / Mastery / Practice evidence;
- Growth Memory;
- Learning Notes and Personas;
- Writing Documents and accepted revisions;
- Living Books and chapter fingerprints;
- Content approval/export state.

DeepTutor IDs, knowledge indexes, sessions, notebooks, personas, memory and book projections remain rebuildable/auxiliary upstream references.

## Compatibility

The audited optional provider baseline remains **DeepTutor v1.5.11**. The sidecar installs the published Python package; no upstream source tree or submodule is included in Psychology Growth.

## Verification

Working-tree verification after the boundary correction:

- 56/56 pytest tests PASS;
- provider-boundary architecture tests PASS;
- Python compileall PASS;
- no direct `import deeptutor` in application/package/adapter source;
- no product plugin hard-dependency on `integration.deeptutor`.

Exact release-ZIP verification is recorded separately during packaging.
