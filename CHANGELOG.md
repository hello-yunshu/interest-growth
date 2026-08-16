# Changelog

All notable changes to the public package are recorded here. This file does
not invent commit history for unpublished work.

## 1.0.0 — v1.0.0-rc.1 (in progress)

### 1.0 highlights

- **Native-only product execution** — Interest Growth Native Core is the sole
  workflow runtime; Host DB remains the only canonical product truth; DeepSeek
  / OpenAI-compatible providers are model transport only.
- **General Interest Core** — curiosity → research/evidence/claim → learning →
  growth → optional expression journeys work without Psychology entities.
- **Research / Evidence / Claim** — human-review gate, claim version history,
  citation provenance, invalidated-evidence downgrade.
- **Learning / Practice / Mastery** — accepted-progression only; AI never
  auto-promotes Mastery.
- **Content Studio** — human-review gate before export; no auto-publish.
- **Self-hosted server** — single-owner bootstrap, named device sessions,
  atomic single-use refresh rotation, per-device revocation, consistent
  DB+Source+Artifact backup/restore with fail-closed corruption handling.
- **Cross-device ClientRuntime** — desktop-local / desktop-remote /
  android-remote with a frozen runtime vocabulary, secure credential
  boundaries and a stable remote error taxonomy.
- **Android remote client** — streaming/SAF upload, artifact export/download,
  minimal capability scope, Keystore-backed renewal credential, fail-closed
  network security.
- **Release pipeline** — remote Actions as the only release evidence:
  migration fixtures, clean backup/restore, provider-contract mock server,
  version/schema freeze, reliability soak, Windows/macOS packages, Android
  emulator + signed APK gates.

### 0.7 development

- Optional self-hosted single-owner Docker server used by Windows, macOS and
  Android clients (additive mode; local-first desktop contract preserved).
- Gates B1–B4: atomic refresh rotation, DB-enforced owner singleton,
  maintenance/write-locked consistent backup, staged rollback-safe restore.
- Gate C ClientRuntime: frozen `runtimeId` vocabulary, orthogonal platform
  adapters, connection state machine, SemVer/compatibility checks, secure
  credential boundary.
- Gate D: desktop remote UX + native broker security closure.
- Gate E: Android runtime, Keystore store, lifecycle, minimal capability scope.
- Server instance identity and schema migrations 13–15.

## 0.6.0-rc2 — 2026-08-12

- Restored the reviewed v0.3 Tutor, RAG, Skill, writing, and reconnect
  invariants in the General Interest architecture.
- Added the native execution architecture while preserving Host canonical data
  ownership.
- Removed DeepTutor as a runtime requirement and retained it only as a reviewed
  compatibility reference.
- Enforced exact-adapter semantics for legacy third-party RAG engine IDs.
- Added public repository hygiene, security, contribution, and reproducible CI
  gates for Python 3.11 and 3.12.
