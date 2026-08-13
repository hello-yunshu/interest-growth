# P4 Audit · Content Studio & Publish Pack

**Decision:** PASS FOR PERSONAL ALPHA

## Implemented

- user selects Topic and Claims in the browser;
- generated Publish Pack contains title candidates, body, tags, Claim/evidence bundle, card outline, image prompts, video pack and risk review;
- persisted files include `01-title-candidates.md` through `10-video-prompts.md` plus `publish.json`;
- Publish Guard checks absolute/causal/diagnostic/treatment-promise language **and each selected Claim** for human verification, complete support Source+Evidence verification, AI-summary-only dependency, publishability and counter/boundary evidence;
- a safe Claim cannot mask an unsafe selected Claim: any high-severity Claim issue forces `ready_for_publication=false`;
- optional DeepSeek enhancement may alter title/body/tags only from selected local Claim statements + limitations; guard reruns after enhancement and failure falls back to deterministic template;
- disabling `psychology.media-prompt` / `FEATURE_MEDIA_PROMPT` degrades Content Studio to a valid text-only pack instead of breaking the feature;
- local information card renderer produces an editable SVG Artifact and is independently gated by its plugin/feature;
- Artifact approval records human review only;
- API explicitly returns `external_publish_performed=false`;
- there is no social publishing endpoint in v0.1.

The local renderer is intentionally information-card-first rather than an AI art generator. Complex images/videos use Prompt Packs and manual generation, matching the Personal Alpha scope.
