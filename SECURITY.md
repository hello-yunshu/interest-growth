# Security Policy

## Supported version

Security fixes are currently evaluated for the `1.0.20` Interest Growth
release-closure line. Older RC and Native Execution Core notes below are
historical and do not expand the current release support claim.

## Reporting a vulnerability

Use GitHub private vulnerability reporting if it is enabled for this
repository. Do not publish sensitive vulnerability details in a public Issue,
Discussion, log, or test fixture. Never include API keys, tokens, cookies,
credentials, private user data, or production database content in a report.

Provide the affected version, the smallest safe reproduction, expected and
observed behavior, and the impact. Redact all secrets and personal data.

## Security boundaries

- Research and retrieval outputs are candidates, not accepted Evidence.
- AI answers, Practice results, writing revisions, Living Book updates, and
  visual plans require the appropriate Host review/acceptance workflow.
- Capability lifecycle, Area enablement, selected capability, PermissionBroker
  grants, and Tool grants are enforcement inputs, not merely prompt guidance.
- Network research Tools are permission-gated and explicitly enabled.
- DeepTutor is not a required runtime dependency.

The current PermissionBroker boundary covers reviewed first-party plugins. A
hostile-plugin sandbox is not claimed by this RC2 and should not be inferred
from first-party permission enforcement.

## Tracked security exception

### PYSEC-2026-113 — optional GraphRAG dependency

- **Advisory:** `PYSEC-2026-113`
- **Affected package/version:** `pyarrow 22.0.0` in the current lock when the
  optional `rag-graphrag` extra is installed.
- **Dependency origin:** `graphrag>=3.1,<3.2` resolves to GraphRAG 3.1.0,
  whose current dependency range requires `pyarrow~=22.0`; the project does
  not declare `pyarrow` directly.
- **Shipped/default status:** `rag-graphrag` is opt-in. It is not installed by
  the default server, desktop, Android or Stable release artifact paths.
- **Reachability assessment:** the project has not established that the
  advisory's affected path is reachable through the default product runtime.
  The optional RAG adapter remains subject to review whenever that extra is
  enabled.
- **Current mitigation:** the CI waiver is scoped only to the optional RAG
  audit step; default runtime dependencies remain fail-closed. NLTK is kept at
  `>=3.10.0` for the separate advisories observed in the same optional audit.
- **Why upgrade is currently blocked:** the reviewed GraphRAG 3.1 constraint
  requires the affected pyarrow major/minor line, and no compatible upstream
  fix has been validated without changing the reviewed adapter contract.
- **Upstream tracking:** re-check GraphRAG's dependency range and pip-audit
  output before enabling this extra in a shipped/default path.
- **Review condition:** remove this waiver immediately after a compatible
  GraphRAG/pyarrow resolution is verified; otherwise review by 2026-09-30 or
  before the next release that changes RAG packaging.
- **Owner:** Interest Growth maintainers.
