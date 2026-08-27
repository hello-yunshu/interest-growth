# Interest Growth Development Contract

**Status:** current, tool-neutral engineering contract

This document is the repository's authoritative development entry point. It
describes product and release invariants without depending on a particular
editor, coding assistant or agent.

## Product and architecture invariants

- Interest Growth is local-first, self-hosted capable, multi-interest,
  cross-device and native.
- `Interest Area` means what the user is cultivating; `Capability Plugin` means
  what the product can do; `Domain Pack` means how a subject-specific area
  behaves; `Capability Provider` means who executes model work.
- Psychology is the default Domain Pack, never the Core. General Areas must
  remain neutral for conceptual, procedural, creative and project interests.
- Direct reads and mutations of Area-owned records validate Area ownership;
  list filtering alone is not an authorization boundary.
- Capability lifecycle and provider lifecycle are global; Area overrides only
  apply to known `capability.*` plugins.

## Native runtime and data truth

- Tutor, Research, Learning, Practice, Knowledge, Memory, Writing, Living Book
  and related workflows run through Interest Growth's built-in Native Core.
- Native Tutor owns the canonical Host Session/Turn execution path, including
  start, replay, resume and cancel. The retired external tutor-runtime path is
  not a current runtime dependency.
- Host product models and the Host database are canonical. Checkpoints,
  public event traces, provider sessions, retrieval candidates, provider
  memory and generated proposals are derivative execution state.
- Retrieval candidates are not Evidence; Practice correctness and model output
  do not automatically promote Mastery; generated content requires Human
  Review before export/publication.
- Provider failures must remain visible and must not silently execute the same
  work twice. `wait_for_input` resumes the same turn.

## Psychology and provider boundaries

- Psychology evidence, diagnosis/treatment and publication rules belong to the
  Psychology Domain Pack and must not leak into General Areas.
- Provider secrets never reach Renderer JavaScript. DeepSeek-compatible model
  transport is optional and does not own product state.
- No external Tutor source is vendored, forked, submoduled or used as the
  canonical database/runtime. Historical DeepTutor decisions are retained as
  historical context only; current implementation facts are defined by the
  Native Tutor source and release criteria.

## Desktop, remote and Android contracts

- Desktop-local uses Tauri 2, static Next.js output, a Python/FastAPI sidecar,
  random loopback port, per-launch desktop token, OS App Data and OS-backed
  credential storage. Renderer CSP and external-link handling stay restricted.
- Desktop-remote and Android-remote use authenticated HTTPS/WSS device
  sessions. Android is online-first remote-only and does not bundle the Python
  sidecar or a canonical local database.
- The self-hosted deployment is single-owner, SQLite single-writer, persistent
  DB/Source/Artifact volumes, and must not be described as offline sync.
- Android release APKs use the project signing identity kept outside Git,
  preserve application ID and signing identity across upgrades, and publish
  checksums plus metadata. Debug and CI release-test APKs are never Stable
  release assets.

## Migration and security

- Migrations are real executed migrations, not ledger-only markers. Existing
  data must remain recoverable, Area-scoped and compatible with the retained
  technical identifiers `app.psychologygrowth.desktop`,
  `psychology_growth.db` and `psychology-growth-core`.
- PermissionBroker declarations are enforced at route boundaries. They are not
  a hostile third-party plugin sandbox.
- Remote authentication, device revocation, secure backup/restore, request
  bounds, TLS/proxy boundaries and provider-secret ownership remain fail-closed.

## Release and verification contract

Before a release, validate the exact source SHA, then run the required local
and remote gates. A green historical run cannot prove a new SHA.

```bash
python -m compileall -q apps packages adapters scripts tests
python -m pytest -q
python scripts/self_audit.py
```

The release order is: ordinary CI/Web/Build Artifacts on the exact `main`
SHA, exact-current-HEAD Stable Candidate, native Promotion/Stable tag, then
the exact-tag Release matrix and post-release asset/checksum/signature audit.
`NOT RUN` and external hardware boundaries are never reported as `PASS`.

## Definition of Done

A change has an owning capability, explicit Area scope, Domain policy owner,
canonical-data decision, provider degradation path, permission/risk
declarations, tests, migration impact, UI path and release/archive impact.
Target-OS signing, real Android hardware and public-TLS deployment remain
separate evidence categories when the current environment cannot execute them.
