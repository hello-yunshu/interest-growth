# 03 · Plugin API v0.1

## Purpose

Plugins isolate first-party product capabilities so they can be enabled, upgraded, audited and composed per Interest Area. They are **not Domain Packs** and they are not a public hostile-code plugin marketplace.

## Layer separation

- `core.interest-growth` owns the product core runtime.
- `capability.*` plugins provide reusable product capabilities.
- `domains/*` define subject/interest policies, default capability composition, Personas, Skills and mastery profile.
- model transport configuration is infrastructure, not a product plugin.

No `capability.*` plugin may hard-depend on a Psychology plugin or model transport.

## Manifest example

```yaml
id: capability.growth-feedback
name: Growth Feedback
version: 0.5.0
level: 3
requires:
  core: ">=0.5,<0.6"
  plugins: [core.interest-growth]
provides:
  pages: [/growth]
  capabilities: [growth-feedback]
  widgets: [weekly-growth]
subscribes: [question.returned, claim.revised, mastery.updated]
permissions:
  read: [mastery, research, claim, growth_event, reflection]
  write: [growth_event, growth_memory]
risk:
  network: false
  shell: false
  llm: false
  destructive_data: false
```

## Area capability overrides

Only `capability.*` plugin IDs can be overridden per Interest Area. Core lifecycle remains global.

Legacy `psychology.*` plugin IDs are compatibility aliases during v0.4.1→v0.5 migration; new manifests must use neutral IDs.

## PermissionBroker

Route execution for first-party Capability Plugins uses `require_plugin_access(...)` to enforce manifest-declared:

- resource reads;
- resource writes;
- network/LLM/shell/destructive risk declarations.

The broker is a product policy boundary, **not an OS/process sandbox**. Arbitrary untrusted Python plugins remain out of scope.

## Lifecycle

```text
Installed
Enabled
Disabled
Update Available
Updating
Rollback Available
Uninstalled
```

Rollback metadata does not magically roll back code. A trusted previous plugin/app bundle must be deployed for code rollback.

## Domain Pack composition

A Domain Pack lists default capability enablement but does not become a plugin dependency. Example:

```yaml
id: psychology
capabilities:
  capability.curiosity: true
  capability.research-evidence: true
  capability.practice: true
  capability.content-studio: true
```

A General/Watercolor Area can override capability choices independently without changing Psychology.

## Native execution rule

Product plugins invoke Host-owned Native Core contracts. Optional model transport availability may degrade model-dependent execution, but it cannot disable or take ownership of canonical Knowledge, Practice, Notes, Persona, Tutor Session, Writing or Living Book data.
