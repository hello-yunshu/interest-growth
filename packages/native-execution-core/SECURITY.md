# Security Policy

## Supported version

Security fixes are evaluated across the merged Host repository and the
independently verifiable `0.6.0-rc2` Native Execution Core package. The Host is
the only canonical product-data owner; the standalone package does not create
a second supported Host surface.

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
- Product execution is provided by the built-in Native Core; external model
  transports receive only explicitly authorized requests.

The current PermissionBroker boundary covers reviewed first-party plugins. A
hostile-plugin sandbox is not claimed by this RC2 and should not be inferred
from first-party permission enforcement.
