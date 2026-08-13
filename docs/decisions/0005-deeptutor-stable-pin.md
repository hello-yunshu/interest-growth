# ADR 0005 · DeepTutor stable version pin

**Status:** Superseded by ADR 0006 · retained as project history

## Decision

Pin the optional sidecar to an audited stable DeepTutor release; never use `latest` as the product contract.

Current active baseline: **v1.5.11**. The prior v1.5.4 baseline is historical and was superseded after upstream v1.5.11 became a stable release and the project added Knowledge/RAG, Skills, Learning, Memory and Visualize integration.

## Consequence

Any future upgrade requires release/diff review, affected contract tests and a compatibility report before the deployment default changes. Optional RAG extras may be selected by the deployment package build arg without changing product data ownership.
