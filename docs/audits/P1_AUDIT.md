# P1 Audit · Curiosity & Interest Loop

**Decision:** PASS

Verified legal product journeys:

- `Question capture → END`;
- `Question capture → Quick Explore (not evidence) → Close`;
- `Question capture → Quick Explore → pause → return → returned_count + GrowthEvent → promote Topic`.

The Web Curiosity Inbox exposes all of these directly. Quick Explore never auto-creates Source/Evidence/Claim and explicitly labels its result `not_evidence`; without DeepSeek it degrades to a deterministic manual micro-workspace. It does not auto-start Deep Research.

Dashboard limits itself to recent questions, up to three Active Topics and micro-progress; no streak/publish KPI exists. Energy modes Light/Normal/Deep are persisted as neutral modes. Pause/Close are valid endings. Return is a positive growth signal.
