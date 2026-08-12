# Security Policy

## Supported version

Security fixes are currently evaluated for the `0.6.0-rc2` Native Execution
Core. The full merged v0.6 Host is not yet claimed or supported by this RC2
repository.

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
