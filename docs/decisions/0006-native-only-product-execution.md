# ADR 0006 · Native-only product execution

**Status:** Accepted · v0.6.0

## Context

Interest Growth now has an integrated Native Core that implements Tutor,
Research, Knowledge/RAG, Learning, Practice, Co-Writer, Living Book, Memory and
Visualize while preserving Host-owned product truth and human-review gates.
Keeping a second workflow runtime would duplicate orchestration, configuration,
failure modes and user-facing concepts without adding a product capability.

## Decision

- All product capabilities execute through Interest Growth Native Core.
- DeepSeek is an optional model transport, not a product workflow provider.
- The Host database remains the only canonical owner of product state.
- Native execution stores only checkpoints, public event sequences and
  auxiliary execution memory.
- No retired runtime adapter, sidecar, plugin, setting, secret, endpoint or UI
  entry ships in the product.
- Existing installations are migrated explicitly: retired plugin/feature state
  is removed and legacy external indexes require a native rebuild.
- Model-generated material remains a proposal or candidate until the relevant
  Host acceptance workflow promotes it.

## Consequences

- Installation, diagnostics and offline behavior have one execution model.
- Local deterministic features continue when no model transport is configured.
- Replacing the model transport does not change product capability contracts or
  canonical data.
- Historical architecture records remain available for audit, but they do not
  describe the current runtime.

## Verification

The Host test suite, Native Core suite, self-audit, production Web build and
desktop checks enforce the native-only execution boundary. Migration 12 covers
existing databases; current product UI and active runtime sources contain no
retired runtime surface.
