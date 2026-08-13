# ADR-0001 · DeepTutor is an engine, not the product base

**Status:** Superseded by ADR 0006 · retained as project history

## Decision
Do not Fork or vendor DeepTutor. Run it separately and consume it through replaceable adapters.

## Consequences
We retain product/UI/data freedom and can remove DeepTutor without losing Question/Claim/Growth data. Cost: adapter and compatibility tests must be maintained.
