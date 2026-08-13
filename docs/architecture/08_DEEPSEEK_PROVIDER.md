# 08 · DeepSeek Provider

## Role

DeepSeek is an optional/default language-model capability provider for low-friction Quick Explore, structured assistance, optional prose enhancement and research fallback. It is **not a Domain Pack and not an evidence verifier**.

Domain-specific semantics are supplied by the current Domain Context. The adapter must not own a Psychology prompt just because Psychology is the default Area.

## Config

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL=https://api.deepseek.com`
- `DEEPSEEK_MODEL=deepseek-chat`
- `DEEPSEEK_TIMEOUT_SECONDS`

Desktop secrets are injected from native OS credential storage. Renderer JavaScript cannot read saved secrets back.

## Structured output rule

`LLM output → JSON parse/schema validation → one repair attempt → fail visibly`.

The provider accepts schemas and never silently drops invalid structured output.

## Quick Explore

Current Domain Pack supplies the Quick Explore system/template. Output remains `evidence_status=not_evidence` and never auto-creates Source, Evidence or Claim.

- General Domain gives neutral concepts/skills/observation + tiny next action.
- Psychology Domain keeps psychology-specific caution and diagnosis/treatment boundary.

Without a key or on failure, the Core returns a deterministic Domain-aware manual workspace.

## Research fallback

The current Domain Pack supplies research planning/source preferences. General Areas can prefer authoritative originals, demonstrations and contrasting perspectives; Psychology can prefer systematic reviews/meta-analysis/primary studies.

Generated citations are leads until grounded in locally reviewed Sources/Evidence. Provider model knowledge is never silently upgraded into verified Evidence.

## Content prose enhancement

The local product constructs deterministic factual/grounded content first. DeepSeek may improve wording only inside the current Area and Domain policy. Psychology factual claims remain subject to verified Claim/Evidence and Publish Guard after enhancement.

This preserves `LLM prose ≠ Evidence` while allowing non-Psychology Areas to express honest practice/learning records through GroundingRefs.
