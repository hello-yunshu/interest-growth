# 06 · Database Schema

SQLite + SQLAlchemy remain the local default. v0.5 introduces a **real explicit migration runner** for schema generations 8–10 while preserving the v0.4.1 baseline generations 1–7.

## Migration contract

- 1–7: v0.4.1 legacy baseline.
- 8: create General Interest schema objects.
- 9: seed Domain Packs/default Psychology Area and backfill all legacy scoped entities into it.
- 10: copy saved legacy `psychology.*` plugin state into neutral plugin IDs while preserving old rows as compatibility history.

`CURRENT_SCHEMA_VERSION = 10`.

`Base.metadata.create_all()` remains useful for fresh databases, but existing databases advance through explicit migration implementations. Future non-additive changes still require an explicit migration; adding a ledger number without transformation code is forbidden.

## Current 41 tables

1. `schema_migrations`
2. `plugin_states`
3. `feature_flags`
4. `domain_packs`
5. `mastery_profiles`
6. `interest_areas`
7. `area_capability_settings`
8. `entity_area_bindings`
9. `persona_scopes`
10. `learning_activities`
11. `grounding_refs`
12. `questions`
13. `topics`
14. `sources`
15. `evidence`
16. `claims`
17. `claim_versions`
18. `concepts`
19. `mastery_records`
20. `domain_events`
21. `growth_events`
22. `growth_memory`
23. `reflections`
24. `artifacts`
25. `practice_items`
26. `practice_attempts`
27. `mastery_evidence`
28. `learning_notes`
29. `tutor_personas`
30. `writing_documents`
31. `writing_revisions`
32. `living_books`
33. `living_book_chapters`
34. `tutor_sessions`
35. `tutor_turns`
36. `capability_runs`
37. `knowledge_bases`
38. `knowledge_source_indexes`
39. `knowledge_ingestion_runs`
40. `retrieval_candidates`
41. `career_experiments`

The final release verification script is the source of truth for actual initialized counts.

## Scope ownership

Legacy canonical tables intentionally do not receive destructive `area_id` ALTERs in v0.5. `EntityAreaBinding` provides explicit Area ownership. SQLAlchemy new-object hooks bind new legacy-model instances to the current Area.

Area-native tables (`learning_activities`, `grounding_refs`, `area_capability_settings`) carry direct Area identity.

All v0.4.1 legacy data must receive a primary binding to the default Psychology Area during migration 9.

## Integrity rules

- A Claim cannot reference Evidence from another Area.
- A Practice Attempt cannot attach to a Tutor Session from another Area.
- Tutor browser-supplied Turn IDs must belong to both current Area and active Tutor Session.
- Source invalidation must validate current Area before mutation.
- Native Notebook and Practice proposal identity is Area-local.
- Provider projection IDs are never canonical ownership.

## Known v0.5 compatibility limitation

Some legacy names remain globally unique, notably Knowledge Base names and Tutor Persona names. This is a usability constraint, not permission to cross Areas. Removing those uniqueness constraints requires a future non-additive migration and is intentionally not mixed into v0.5.
