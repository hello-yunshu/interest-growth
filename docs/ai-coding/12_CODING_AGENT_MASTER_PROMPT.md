# Interest Growth v0.6 / v0.7 — Coding Agent Contract

You are continuing the verified **Interest Growth v0.6 Native Execution Product** while implementing the additive **v0.7 self-hosted cross-device mode**. Do not redesign the product from scratch and do not re-center the Core on Psychology or any external Provider.

## Current product facts

- Interest Growth is an independent local-first multi-interest desktop product.
- Psychology is the default first Domain Pack, not the parent product.
- The product has four distinct layers: Interest Area, Capability Plugin, Domain Pack, Capability Provider.
- Desktop: Tauri 2 + static Next.js/React + local Python/FastAPI sidecar.
- DeepSeek and DeepTutor are optional providers; DeepTutor baseline is pinned/audited to v1.5.11.
- Windows target: Windows 11 24H2+ x64. macOS target: macOS 13+ Apple Silicon.

## Forward v0.7 work

The approved next direction is an optional single-owner, self-hosted Docker server used by Windows, macOS and Android clients. This is an additive product mode, not permission to weaken or silently replace the current local-first desktop contract.

Before any remote deployment, client-runtime or Android change, read and follow:

- `13_SELF_HOSTED_CROSS_DEVICE_ANDROID_PROMPT.md`;
- `../architecture/V0_7_SELF_HOSTED_CROSS_DEVICE_BLUEPRINT.md`;
- `../roadmap/V0_7_SELF_HOSTED_CROSS_DEVICE_PLAN.md`;
- `../design/V0_7_CROSS_DEVICE_CLIENT_DESIGN.md`;
- `../audits/V0_7_IMPLEMENTATION_AUDIT.md`;
- `../security/11_SECURITY_AND_PRIVACY.md`.

v0.7 Android distribution is direct APK sideloading, not Google Play. APKs still require cryptographic signing: debug signing is for development, while controlled release APKs use a project-owned private key kept outside Git. The first remote release is server-authoritative/online-first and must not be described as offline sync.

The remote Docker profile intentionally serves HTTP on loopback. Client-facing HTTPS/WSS terminates at an external Nginx/Caddy edge (or the optional Caddy overlay), which forwards over trusted loopback/private HTTP. Never bind the trusted-proxy API profile directly to an untrusted LAN or the Internet.

## Non-negotiable general-interest laws

- `Interest Area = what`, `Capability Plugin = what the system can do`, `Domain Pack = how`, `Provider = who executes`.
- Core code must not inject Psychology prompts/policies into General Areas.
- Psychology-specific Skills/Personas/policies belong under `domains/psychology`.
- General Area behavior must stay neutral and usable for conceptual, procedural, creative and project-based interests.
- all direct-ID mutations/reads of Area-owned data require Area ownership; list filtering alone is insufficient.
- Tutor WS browser-supplied Turn IDs must also belong to the current Tutor Session.
- cross-Area Evidence/Claim, Practice/Tutor and other domain references must be rejected unless an explicit shared-binding design says otherwise.
- Area overrides apply only to known `capability.*` plugins; Core and Provider lifecycle are global.
- PermissionBroker read/write/risk declarations must be executable route boundaries, not decorative manifest metadata.

## Psychology default-pack laws

- verified Claim/Evidence chain remains required for psychology factual publication readiness;
- no automatic individual diagnosis/treatment decision or treatment guarantee;
- Source invalidation/Claim revision invalidates downstream review as before;
- Psychology Mastery Profile and evidence-aware Research policy remain available only through the Psychology pack.

## Provider / evidence laws

- no DeepTutor fork, vendored source, submodule or upstream domain types in canonical DB contracts;
- no product capability plugin hard-depends on `integration.deeptutor`;
- retrieval remains `candidate_not_evidence`;
- provider memory is auxiliary; local Growth Memory is authoritative;
- provider Book/Notebook/Persona/Skill/RAG state is projection/derivative;
- semantic provider failure must not silently double-execute work;
- wait-for-input resumes the same turn;
- Practice correctness never auto-promotes Mastery;
- Human Review is required before Export; Export is not external publication.

## Desktop laws

Preserve the v0.4/v0.4.1 desktop security contract: static export, Tauri-owned sidecar, random loopback/token, single instance, App Data ownership, OS credential storage with no JS secret readback, user-mediated Save dialog, restricted renderer CSP, system-browser external URLs, updater private keys outside repository and target-OS support policy.

`app.psychologygrowth.desktop`, `psychology_growth.db`, and `psychology-growth-core` are intentional v0.5 compatibility identifiers. Do not rename them casually; doing so requires an explicit App Data/credential/updater migration.

## Beautiful AI Interface laws

- Public Activity Trace is an allowlist of public stage/progress/tool/source/wait/error/done events; never display private chain-of-thought, unknown categories or raw tool-result bodies.
- no browser-native prompt/confirm/alert for consequential review;
- no `dangerouslySetInnerHTML` in privileged renderer;
- Context/RAG UI does not imply verified Evidence;
- Diff requires explicit accept/reject;
- external Source links open through scoped Tauri Opener/system browser in desktop mode.

## Migration laws

- v0.4.1 legacy schema baseline is 1–7;
- migrations 8–10 are real executed migrations, not ledger-only markers;
- all v0.4.1 entities backfill into default Psychology Area;
- legacy `psychology.*` plugin state is copied to neutral capability IDs while old rows remain compatibility history;
- future non-additive schema changes require an explicit migration and exact prior-release upgrade test.

## Definition of Done

A feature needs owner capability, Area scope, Domain policy ownership, canonical-data decision, provider degradation path, permission/risk declarations, tests, migration impact, UI path and exact-archive validation.

Source gates:

```bash
python -m compileall -q apps packages adapters scripts tests
python -m pytest -q
python scripts/self_audit.py
```

Native DMG/Setup signing/build remains a separate target-OS gate and must be reported as not executed when the required toolchain or credentials are unavailable.
