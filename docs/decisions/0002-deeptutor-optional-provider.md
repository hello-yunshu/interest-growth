# ADR 0002 · DeepTutor is an optional capability provider

**Status:** Superseded by ADR 0006 · retained as project history

## Context

Psychology Growth intentionally reuses useful DeepTutor capabilities, but the product is not a DeepTutor fork, distribution, downstream branch, or UI skin. The v0.3.0 audit confirmed source-level separation, but a second audit found two architectural signals that could blur that boundary:

1. several local Psychology plugins declared `integration.deeptutor` as a hard plugin dependency;
2. provider calls were gated primarily by `DEEPTUTOR_ENABLED`, so disabling the Integration plugin did not reliably disable the provider.

The product also used project-level wording such as `DeepTutor-Powered` and `DeepTutor Native Learning Runtime`, which was technically compatible with a no-fork architecture but unnecessarily centered the upstream product in Psychology Growth's identity.

## Decision

DeepTutor is treated as **one first-party external capability provider integration**.

- Upstream DeepTutor code is not vendored, forked, submoduled, patched, or imported directly.
- The DeepTutor runtime is installed separately in a sidecar from the pinned public package.
- Product code talks only to the local `pg_deeptutor` adapter over DeepTutor's public HTTP/WebSocket contracts.
- No Psychology product plugin may hard-depend on `integration.deeptutor`.
- Provider execution requires both deployment configuration and product-plugin state:

```text
DEEPTUTOR_ENABLED=true
        AND
integration.deeptutor is enabled
```

- Disabling DeepTutor may disable external execution/projection/indexing, but must not disable local canonical product capabilities such as Sources, Evidence, Claims, Practice, Notes, Personas, Tutor Session records, Writing Documents, Living Books, Growth Memory, or publication review.
- Product/domain IDs are always local. DeepTutor IDs are stored only in generic `upstream_*` / provider execution fields.
- Product-level branding is provider-neutral. DeepTutor is named only where users are configuring, diagnosing, or intentionally invoking that provider.

## Consequences

### Positive

- Psychology Growth remains independently understandable and deployable.
- Replacing or removing DeepTutor does not require re-identifying product data.
- Plugin lifecycle state now has real effect on provider calls.
- Local product features do not collapse when the provider is disabled.
- DeepTutor upgrades remain compatibility work, not product branch merges.

### Trade-offs

- Some advanced AI execution currently has only a DeepTutor implementation and therefore becomes unavailable when that provider is off.
- The `pg_deeptutor` adapter remains compiled with the application as first-party integration code; runtime DeepTutor itself remains external.
- Adding a second implementation for advanced Tutor/Book/Notebook behaviors may require additional provider factories/contracts, but it does not require changing the canonical data model.

## Verification

`tests/architecture/test_deeptutor_provider_boundary.py` and `scripts/self_audit.py` enforce:

- no upstream `deeptutor` source tree/submodule/direct Python imports;
- sidecar package install instead of source copying/cloning;
- no product plugin hard dependency on `integration.deeptutor`;
- disabling the provider leaves local product plugins and canonical local routes usable;
- the unified provider gate requires both deployment and plugin enablement.
