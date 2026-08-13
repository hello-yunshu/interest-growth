# 09 · Roadmap / Completion Map

The original phase contract remains preserved in `00_DEVELOPMENT_PHASE_PLAN.md`. This file records what is now implemented after the independent audit and DeepTutor deep-integration pass.

## P0 · Architecture Foundation — implemented

Independent repo structure, Domain, Engine Contracts, Plugin Runtime, Event Bus, Feature Flags, Artifact abstraction, DB/migrations, DeepSeek/DeepTutor adapters, Compose, CI/self-audit and Core independence.

## P1 · Curiosity & Interest — implemented

Curiosity Inbox, Energy Mode, Quick Explore=`not_evidence`, Pause/Return/Close, Topic promotion and quiet Dashboard.

## P2 · Research & Evidence — implemented

Deep Research, Research Plan, Source/Evidence/Claim/ClaimVersion, Skeptic Pass, evidence boundary, source/claim re-verification propagation, knowledge-aware research and fallback.

## P3 · Learning & Growth — implemented

Concept Card, Flexible Mastery, real Learning UI, Concept Graph, Growth Event, G1/G2/G3 Growth Memory, Weekly Reflection, DeepTutor Mastery Path/Deep Question assistance.

## P4 · Content & Publish Pack — implemented

Content Studio, XHS Pack, image/video prompt packs, local card, per-Claim Publish Guard, Human Review and downloadable ZIP export. No auto-publication.

## P5 · High-value DeepTutor use — implemented core

- Knowledge/RAG and Source ↔ index mapping;
- rebuild from product-owned files;
- direct selected-KB retrieval with `candidate_not_evidence` boundary;
- parsing text preview;
- Skills sync;
- Memory read-only Agent bridge;
- Guided Learning/Mastery assistance;
- Visualize Artifact;
- Unified turn transport / capability discovery;
- Claim/content re-verification invalidation.

Not every DeepTutor platform surface is copied. Low-product-value platform/admin surfaces remain need-driven integration candidates.

## P6 · Career & ecosystem — career core implemented

Career Experiment is implemented as reversible evidence-gathering. Optional ecosystem adapters remain demand-driven:

Zotero / PubMed / Crossref / Semantic Scholar / Obsidian / external storage / additional LLM-image-video providers / optional social publishing / DeepTutor Watcher / Plugin Hub.

These are extensions rather than prerequisites for the current product loop.

## P7 · Self-hosted cross-device + Android — planned

- optional single-owner FastAPI Docker server on Unix;
- authenticated HTTPS/WSS and revocable device sessions;
- explicit desktop-local, desktop-remote and Android-remote runtime modes;
- Windows/macOS remote access without regressing the local sidecar;
- Android Tauri client with mobile lifecycle/file/navigation behavior;
- direct APK sideloading with debug builds for development and a project-self-signed release APK for controlled distribution;
- complete SQLite + Source + Artifact backup/restore;
- real two-client continuity, device revocation and same-key APK upgrade proof.

Google Play/AAB, public multi-tenancy and offline bidirectional sync are not part of P7. The executable plan is `V0_7_SELF_HOSTED_CROSS_DEVICE_PLAN.md`.

## Next iteration policy

Do not add another integration because it exists. Require a concrete user friction or repeated workflow. Prioritize the approved P7 server/client boundary, real-use feedback, live model-transport smoke, browser E2E, data backup/export hardening and upstream compatibility before ecosystem breadth.
