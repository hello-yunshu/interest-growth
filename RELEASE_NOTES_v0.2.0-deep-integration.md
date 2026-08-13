# v0.2.0 Deep Integration

This release corrects the earlier over-optimistic “complete Personal Alpha” claim by completing the audited product gaps and deeply integrating the high-value parts of DeepTutor.

## Added / completed

- DeepTutor baseline upgraded to v1.5.11.
- Unified-turn aware client with compatible SSE fallback.
- First-class local Engine Contracts for Knowledge/Parsing/Retrieval/Learning/Memory/Visualization/Skills.
- Own-Data-First Knowledge/RAG library with locally owned Source files and rebuildable DeepTutor index mappings.
- LlamaIndex / LightRAG / GraphRAG / PageIndex product ingestion choices.
- Direct RAG retrieval with `candidate_not_evidence` boundary.
- Psychology Skill synchronization into DeepTutor.
- Mastery Path + Deep Question learning assistance without auto-changing local Mastery.
- DeepTutor Memory v3 read-only bridge; Growth Memory remains authoritative.
- Visualize → reviewable Artifact.
- Complete Learning/Concept/Mastery Web workspace.
- Complete Content Human Review → ZIP Export Web workflow.
- Career Experiment core.
- Source verification revocation + Claim re-verification queue.
- Claim revision/re-verification automatically invalidates dependent approved content.
- Loopback-only Compose port binding by default.

## Kept intentionally out of the primary psychology UI

Voice, Partners, Multi-user admin, MCP management, `deep_solve` and `math_animator` are not blindly duplicated. Generic capability discovery remains available; additional surfaces should become product plugins only when real use justifies them.

## No change to safety boundaries

No automatic diagnosis/treatment decision, no AI-only Evidence approval, no automatic Claim approval, and no external social auto-publish.

## Verification

- 30 automated tests pass.
- Source self-audit, frontend syntax, YAML, clean DB/plugin/feature initialization and OpenAPI generation pass.
- A UTF-8 archive rehearsal extracted into a fresh directory passes the same gates and preserves the original Chinese baseline filenames byte-for-byte.
- Docker/real DeepTutor/real DeepSeek/Next production build remain deployment-host live gates and are not misreported as sandbox passes.
