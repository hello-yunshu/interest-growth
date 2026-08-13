# 11 · Security & Privacy

## Trust model

Interest Growth can contain sensitive personal learning history, reflections, source files, unfinished writing, research notes and—because Psychology is the default Domain Pack—potentially sensitive psychology-related material. v0.5 is a **single-user local-first desktop product**, not a clinical system and not a public multi-tenant SaaS.

## Interest Area isolation

Interest Areas provide product-level data/context isolation inside the local user account.

- HTTP requests carry `X-PG-Interest-Area`.
- Native Tutor REST endpoints carry Area explicitly.
- Scoped list queries and direct-ID mutations validate Area ownership.
- Cross-Area Evidence/Claim, Practice/TutorSession and TutorTurn/session relationships are rejected.
- Native execution context (Persona/Skills/KB selection) is derived from the active Area/Domain.

Area isolation is **not an operating-system user sandbox**. A process that fully compromises the same OS account can access local application data.

## Domain Pack safety

Psychology safety policy belongs to `domains/psychology`, not the General Core.

The Psychology Domain Pack preserves:
- evidence-heavy factual publication;
- diagnosis/treatment language boundary;
- human verification before factual publication;
- Psychology-specific research/personas/skills/mastery profile.

General Areas do not inherit those prompts automatically. General GroundingRefs support honest personal/practice records but do not turn them into scientific Evidence.

## PermissionBroker

Trusted first-party Capability routes use `require_plugin_access(...)` to enforce manifest-declared resource reads/writes and risks such as network/LLM. Regression tests intentionally remove permissions and require real API 403 responses.

PermissionBroker is **not** a hostile-plugin OS/process sandbox. Untrusted arbitrary Python plugins remain unsupported.

## Desktop process/network boundary

- Tauri owns the Python Core lifecycle and enforces single instance.
- Core binds to a random `127.0.0.1` port.
- Each launch/restart receives a fresh high-entropy desktop token.
- HTTP requires `X-PG-Desktop-Token`; Native Tutor uses the same authenticated Host boundary.
- `/api/health` is intentionally non-sensitive and unauthenticated for readiness.
- Tauri performs a real health request before reporting Core ready.
- A failed/terminated Core is reflected as runtime error; stale process events cannot overwrite a newer Core generation.
- Browser-development/Compose mode stays loopback by default.

The desktop token protects against casual unrelated webpages/local callers; it does not defend against a malicious process under a compromised OS user.

## Sensitive storage

- SQLite, Sources and Artifacts live under OS App Data in desktop mode and are excluded from Git.
- Source paths are product-controlled and traversal is rejected.
- Native indexes/proposals are derivative and never the only source copy.
- The optional DeepSeek-compatible API key uses macOS Keychain / Windows Credential Manager.
- Renderer APIs expose secret set/delete/status only; saved secrets cannot be read back into JS.
- Non-secret Provider settings use temp + fsync + backup promotion/recovery.
- Updater private key and platform signing credentials are never repository files.

## Privileged Renderer boundary

- Beautiful AI Activity is a **public runtime trace**, not model chain-of-thought.
- Private/unknown reasoning event categories and raw tool-result bodies are not displayed.
- Consequential review actions use in-app Approval surfaces, not browser `prompt`/`confirm`/`alert`.
- `dangerouslySetInnerHTML` is forbidden in the desktop Renderer.
- Source identifiers become external links only for parsed `http:`/`https:` URLs.
- Desktop opens external URLs in the system browser via Tauri Opener instead of navigating the privileged main WebView.
- Renderer CSP is limited to Tauri IPC + loopback Core and must not directly connect to AI Provider HTTPS endpoints.
- Native export uses OS Save dialog plus runtime-scoped file write permission; no broad `fs:write-all`.

## Evidence / AI boundary

- LLM output is never automatically verified Evidence.
- Quick Explore is explicitly `not_evidence`.
- RAG output is a `candidate_not_evidence` until human/source verification.
- Practice/AI judgment does not automatically promote Mastery.
- Psychology factual content requires its Domain Pack's verified Claim/Evidence policy.
- General personal/practice Grounding remains labelled as such.
- No automatic social publication exists; final export remains Human Review gated.

## Native execution independence

Native Core implements product workflows and is independent of model transport. DeepSeek receives only the authorized request context and does not own Psychology policy or canonical product state.

Local Source/Note/Mastery/Writing/Book objects survive model transport deletion or replacement. Native checkpoints, indexes and proposals are execution/derivative state rather than product identity.

## Compatibility identifiers

`app.psychologygrowth.desktop`, `psychology_growth.db` and the `psychology-growth-core` sidecar basename remain intentional v0.5 migration anchors. They are not public product branding. Renaming them without an explicit data/credential/updater migration could make existing user data or credentials appear missing.

## Remote deployment

CORS is not authentication. The current unauthenticated development/Compose API must not be exposed to an untrusted LAN or the public Internet.

The planned v0.7 self-hosted mode is single-owner with multiple revocable devices, not public multi-tenant SaaS. Its minimum security contract is:

- HTTPS/WSS behind an explicit reverse-proxy boundary; Uvicorn is not directly public;
- authenticated owner/device sessions on every non-health HTTP and WebSocket route;
- short-lived access credentials and rotated/revocable per-device renewal credentials;
- native renewal credentials in OS-backed secure storage and browser credentials in secure cookie storage;
- no bearer/renewal credentials or provider secrets in `localStorage`, URLs, logs or public runtime traces;
- server-owned provider secrets, narrowly configured origins/hosts, bounded uploads/requests and rate controls;
- one SQLite writer process until a separately designed database migration exists;
- a consistent, tested backup/restore unit covering SQLite, Sources and Artifacts;
- explicit server compatibility and certificate/identity-change handling in clients.

The existing per-launch desktop token authenticates a local shell to its loopback sidecar only. It is not remote identity and must not be reused as Internet-facing authentication. Interest Area scoping is also not user/account authorization.

v0.7 remote clients are online-first. A presentation cache is not canonical data, and remote mutations stop when the server cannot be authenticated/reached. Offline operation logs, conflict resolution and replica encryption require a later explicit threat model.

### Android direct distribution

The Android channel is direct APK sideloading rather than Google Play. Every installable APK still requires cryptographic signing. Debug signing is limited to development; a controlled release uses a project-owned release keystore kept outside Git, and all upgrades retain the same application ID/signing identity with a higher version code.

Each release publishes a SHA-256 checksum and signing-certificate fingerprint. The actual handoff must recheck current Android developer-verification rules: direct sideload/ADB remain supported paths in this planning snapshot, while broader certified-device distribution may require developer/package registration or an advanced user installation flow as Android's rollout expands.

Release-time sources of truth are Android's [app-signing documentation](https://developer.android.com/studio/publish/app-signing), [developer-verification guide](https://developer.android.com/developer-verification/guides) and [verification FAQ](https://developer.android.com/developer-verification/guides/faq), plus Tauri's [Android signing guide](https://v2.tauri.app/distribute/sign/android/). External policy must be refreshed rather than copied forward as a permanent assumption.
