# Contributing

Contributions must preserve the product and runtime boundaries below.

## Architecture laws

- The Host Core and canonical database own product truth.
- Native execution may own only `native_tutor_checkpoint`, `native_run_event`,
  and `native_aux_memory`.
- Do not create duplicate native Source, Evidence, Claim, Mastery, Practice,
  Note, Writing, Book, Skill, Persona, or Growth Memory stores.
- Domain-specific policy belongs in a Domain Pack, not the general runtime.
- Product capabilities execute through the Native Core. Do not add an external
  workflow runtime, compatibility bridge, or second product-state owner.
- Never silently map a third-party RAG engine ID to a different native
  algorithm. Add a reviewed exact adapter or return `requires_review`.
- Preserve the v0.3 answer/narration split, same-turn continuation, reconnect
  cursor, provenance, Skill SHA, stale-base, and memory-separation invariants.

## Development and tests

Create a Python 3.11 or 3.12 virtual environment and install:

```bash
python -m pip install -e ".[dev,api]"
```

Before submitting a change, run:

```bash
python scripts/audit_public_repo.py
python scripts/verify.py
python -m pip wheel . --no-deps -w dist
```

Every behavior change needs a focused regression test followed by the full
suite. Do not skip, weaken, delete, or blanket-catch a failing invariant.

## Public repository hygiene

Do not commit AI coding instructions, internal execution plans, local audit
scratch, environment files, credentials, personal data, caches, Wheels, ZIPs,
or build output. Do not add real secrets even temporarily: deleting them in a
later commit does not remove them from Git history.

No open-source license has been selected. Do not add a license or copy
third-party code without an explicit licensing decision and a review of all
applicable attribution obligations.
