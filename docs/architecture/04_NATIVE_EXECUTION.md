# 04 · Native Execution

Interest Growth Native Core is the only product workflow execution layer.

## Contracts

- Host owns canonical Areas, Sources, Evidence, Claims, Mastery, Practice,
  Notes, Tutor Sessions/Turns, Writing, Books and Growth Memory.
- Native Core executes only capabilities granted by global lifecycle, current
  Area composition and PermissionBroker scope.
- Native execution persists checkpoints, monotonic public events and auxiliary
  execution memory only.
- Retrieval creates provenance-preserving candidates, never accepted Evidence.
- Practice, Notebook, Co-Writer, Living Book and Visualize outputs remain
  reviewable proposals until Host acceptance.
- DeepSeek is an optional model transport. When unavailable, deterministic
  local capabilities continue and model-dependent capabilities degrade
  explicitly.

## Product paths

Tutor, Research, Knowledge/RAG, Learning, Practice, Co-Writer, Living Book,
Memory and Visualize all call Native Core contracts through the authenticated
Host API. No compatibility sidecar, external workflow runtime, provider plugin
or alternate product database is part of the v0.6 product.

## Migration

Migration 12 removes retired runtime plugin/feature state and converts legacy
Knowledge Base mappings into an explicit native-rebuild state. No legacy index
is silently relabeled as a native algorithm.
