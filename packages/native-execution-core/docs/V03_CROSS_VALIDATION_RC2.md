# v0.3 ↔ v0.6 RC2 Cross-Validation

Reference v0.3:
- commit `52e4687bc0be140e0f5e10e844ff3f2af88e342e`
- archive SHA-256 `b08772c3046f048e47afea8db506a63b90fbd9d9e92aa2412d8954cc928ae11a`

Target RC2:
- Interest Growth General Interest architecture
- execution-only Native Core
- no DeepTutor runtime dependency

## v0.3 independent audit A–K

| v0.3 closed finding | RC2 status | RC2 enforcement |
|---|---|---|
| A Stream pollution | CLOSED | Tool-round narration suppressed from `assistant_text`; semantic `answer_delta` only |
| B wait_for_input missing | CLOSED | same checkpoint + persisted execution snapshot + `ask_user` tool-result resume |
| C session continuity | CLOSED | Area/session, host Tutor IDs, KBs, selected Capability, grants, config and context fingerprints snapshotted |
| D unsafe semantic fallback | CLOSED | no silent rerun/fake provider success; failures terminalize explicitly |
| E fake per-Source RAG precision | PRESERVED AT HOST BOUNDARY | `WholeKbAsyncIndexAdapter` contract; host KnowledgeIngestionRun remains task truth |
| F same-name Source collision | CLOSED | exact adapter gets Source-ID-prefixed collision-safe filenames |
| G multi-file rebuild race | CLOSED BY CONTRACT | exact build receives one whole-KB snapshot, not one competing build per Source |
| H provenance missing | CLOSED | RetrievalCandidate includes KB/Source/fingerprint/filename/location/raw citation metadata |
| I Skill overclaim | CLOSED | package SHA covers all files; supporting files stay host-owned; requirements reported fail-closed |
| J Visualize raw-only | CLOSED | `interest-growth.visual.v1` reviewable manifest + fingerprint |
| K permission declarations only | IMPROVED | Tool discovery + execution both enforce current PermissionScope; still first-party, not hostile sandbox |

## v0.6 improvements retained

RC2 does not roll back:
- General Interest Core / Psychology as Domain Pack;
- Interest Area isolation;
- global + Area Capability composition;
- CAS cancellation/error state machine;
- explicit unavailable LLM state;
- honest RAG algorithm IDs;
- atomic migration 11;
- native execution package resource verification.

## Host-owned v0.3 product semantics not duplicated

RC2 intentionally does not recreate canonical:
- Knowledge Base / Source lifecycle;
- PracticeAttempt / MasteryEvidence;
- WritingDocument/Revision acceptance;
- LivingBook/Chapter staleness state;
- Growth Memory;
- Claim/Evidence verification.

The real v0.5 host merge must preserve those existing product models.
