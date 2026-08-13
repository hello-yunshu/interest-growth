# 07 · Event Contract

## Product Domain Event envelope

```json
{"id":"uuid","type":"claim.revised","payload":{},"occurred_at":"UTC datetime","schema_version":1}
```

Product domain events are persisted in `domain_events`; subscriber exceptions are isolated and recorded in `subscriber_errors`.

Domain Events remain local product facts. Their owning objects are Interest-Area scoped through the product scope layer.

Important events include question return/close, research completion, source invalidation, claim revision/verification/reverification, mastery/reflection and content/artifact lifecycle.

## Critical subscriptions

- Growth Feedback converts return/revision/mastery/research/reflection changes into non-gamified progress feedback inside the owning Interest Area.
- Content invalidation listens to `claim.revised` / `claim.reverification_required`, clears approval and marks linked factual content review-needed.
- Living Book invalidation marks dependent chapters stale instead of silently rewriting them.

## Provider stream events are adapter protocols

Native Tutor public events are **not** persisted as product DomainEvents automatically. The Host maps accepted public execution events into TutorTurn categories such as:

- `answer_delta`
- public `activity`
- `sources`
- `wait_for_input`
- `result`
- `done`
- `error`
- `session`

Only `answer_delta` contributes to final Tutor answer text. Tool results/progress/sources must not masquerade as final assistant content.

The desktop Beautiful AI Interface exposes only a public activity allowlist. Private categories such as `thinking`, `reasoning`, `chain_of_thought` and `internal_thought`, unknown event types and raw tool-result bodies are not rendered as activity.

## Area boundary

Tutor WebSocket carries current Area explicitly. Browser-supplied `local_turn_id` for reply/resume/cancel must resolve to both the active Tutor Session and current Area before any provider action is attempted.
