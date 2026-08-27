# 02 · Domain Model

**Current runtime note:** Native Tutor is the product-owned canonical Tutor
runtime. Any DeepTutor wording in this historical model catalog refers only to
derivative or historical provider projections; it must not be read as a current
runtime dependency. See `docs/development/DEVELOPMENT_CONTRACT.md`.

## Product composition entities

| Entity | Meaning |
|---|---|
| DomainPack | Built-in or future subject-specific policy/persona/skill/mastery configuration |
| MasteryProfile | Ordered learning/mastery state model selected by a Domain Pack or Area |
| InterestArea | One user-owned interest workspace such as Psychology or Watercolor |
| AreaCapabilitySetting | Area-local enable/disable override for `capability.*` plugins |
| EntityAreaBinding | Area scope for legacy canonical entities without destructive column changes |
| PersonaScope | Maps a local Persona to a Domain Pack |
| LearningActivity | Area-native practice/observation/project activity |
| GroundingRef | Area-native reference from expression/content to local source/note/practice/activity/book/artifact/project context |

## Stable owned learning/research entities

| Entity | Meaning |
|---|---|
| Question | A real curiosity question; can be explored, paused, closed or promoted |
| Topic | A sustained topic promoted from a Question or created intentionally |
| Source | Identifiable source plus locally owned original file when available |
| Evidence | Source-bound evidence unit with location, limitation and verification status |
| Claim / ClaimVersion | Claim identity plus append-only revision history |
| Concept / MasteryRecord | Concept and user-owned mastery state using the Area mastery profile |
| PracticeItem / PracticeAttempt | Practice prompt/task and user attempt; not automatic Mastery |
| MasteryEvidence | Explicitly retained mastery evidence |
| LearningActivity | General conceptual/procedural/creative/project learning record |
| LearningNote | Intermediate learning note that does not need to become a Claim |
| TutorPersona / PersonaScope | Local Persona plus Domain Pack ownership |
| TutorSession / TutorTurn | Persistent tutoring context and normalized turn execution |
| GrowthEvent / GrowthMemory | Traceable progress/return/effort/understanding memory |
| Reflection | Periodic reflection on interest, energy, understanding and direction |
| WritingDocument / WritingRevision | Canonical local text plus AI revision proposal/human decision |
| LivingBook / LivingBookChapter | Long-lived compiled learning artifact with source fingerprints |
| Artifact | Reviewable research/content/visual/export artifact |
| CapabilityRun | Local/external engine run and explicit limitations |
| KnowledgeBase | Product-owned KB intent/configuration |
| KnowledgeSourceIndex | Source↔KB mapping, not fake per-file indexing truth |
| KnowledgeIngestionRun | Async whole-KB ingestion task truth |
| RetrievalCandidate | RAG answer/provenance candidate; `candidate_not_evidence` by default |
| CareerExperiment | Reversible career/expression experiment and observation |
| PluginState / FeatureFlag | Global plugin lifecycle and feature isolation |

## Interest Area scope

All user-owned learning/research/expression objects must resolve to an Interest Area.

Legacy v0.4.1 models are scoped through `EntityAreaBinding`; v0.5 Area-native models carry `area_id`. Direct-ID routes must validate that the referenced object belongs to the current Area, not just filter list endpoints.

A user may create a General Area such as Watercolor without receiving Psychology prompts, Personas, Skills or mastery states.

## Domain Pack semantics

`general` supplies neutral defaults. `psychology` is the default specialized pack.

Psychology adds, without redefining Core entities:
- psychology-specific research source preferences;
- diagnosis/treatment boundary;
- evidence-heavy factual publication rules;
- psychology Personas and Skills;
- conceptual/evidence mastery states.

A future Drawing/Music/Programming Domain Pack may choose different capability defaults and mastery profile without forking the Core.

## Verification chain

```text
Source created/uploaded = unverified
→ user reads original → Source verified
→ Evidence may become human_verified
→ current ClaimVersion has current verified Evidence
→ Claim may become human_verified/publishable
```

Source verification revoked → dependent Evidence downgraded → dependent current Claim unverified / re-verification queue → approved factual content invalidated → dependent Living Book chapters stale. Historical ClaimVersion remains.

## General grounding chain

```text
Note / Practice / LearningActivity / Source / BookChapter / Artifact / Project
        ↓
    GroundingRef
        ↓
Writing / Content / Living Book context
```

This chain supports honest “what I learned / tried / observed / made” expression. It does **not** upgrade personal/practice records into scientific Evidence.

## Mastery profiles

Psychology default profile:

`unfamiliar → familiar → explain → example → distinguish → transfer → evidence_boundary → stable_expression`

General adaptive profile:

`unfamiliar → familiar → understand → practice → apply → reflect → transfer → self_directed`

Practice results, model output and AI judgment never automatically promote Mastery; promotion remains user/product-owned and evidence-aware.

## Provider ownership

Provider projections are derivative. External session IDs, KB IDs, Persona projections, Notebook records, Question Notebook records, Book IDs and auxiliary Memory never become canonical product identity.
