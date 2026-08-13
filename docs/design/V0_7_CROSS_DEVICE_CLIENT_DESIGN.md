# Interest Growth v0.7 — Cross-device Client Design

## 1. Design objective

Make the same Interest Growth workspace feel native and trustworthy on desktop and Android while always showing where canonical data lives. Reuse the shared Next.js/React product surfaces; adapt navigation, runtime actions and density by capability rather than duplicating the product.

## 2. First-run choice

Desktop first run offers two explicit modes:

1. **This device** — existing local Core and App Data.
2. **Self-hosted server** — connect to an owner-controlled HTTPS server.

Android starts with **Self-hosted server** because v0.7 does not bundle the Python Core. The enrollment flow asks for:

- server address;
- verified server identity/name and TLS state;
- owner login;
- a human-readable device name;
- final confirmation of where data will be stored.

The app must not persist credentials until server identity, protocol compatibility and authentication succeed.

## 3. Global shell

Desktop keeps the persistent navigation and optional inspector. Android uses:

- compact top bar with active Interest Area and connection state;
- drawer or bottom navigation for primary destinations;
- overflow navigation for lower-frequency settings/administration;
- one-column content at phone widths;
- safe-area padding and keyboard-aware editors;
- platform Back that closes transient UI before navigating away.

Touch targets must remain comfortably operable. Hover-only disclosure is not allowed for required actions.

## 4. Data-location language

The shell always has a quiet but discoverable runtime label:

- `This device · Online` for desktop local mode;
- `<server name> · Connected` for remote mode;
- `Reconnecting`, `Offline`, `Login expired`, `Server unavailable` or `Update required` when applicable.

Remote copy must say “saved on your self-hosted server,” not “safe on this device.” Local mode must not imply that data is already available on Android.

## 5. Connection states

| State | User experience | Mutations |
|---|---|---|
| Connected | normal workspace | enabled |
| Reconnecting | preserve current view, bounded retry indicator | temporarily disabled or explicitly queued only if a future queue contract exists |
| Offline/server unavailable | show last safe presentation state where available | disabled in v0.7 |
| Login expired | focused re-authentication flow | disabled until renewed |
| Certificate/identity changed | blocking security explanation | disabled; require explicit re-enrollment |
| Client/server incompatible | explain required update | disabled where contract safety is unknown |

Do not show indefinite spinners or silently retry consequential mutations.

## 6. Authentication and devices

System settings exposes:

- current account/server;
- this device name and last active state;
- other registered devices and last-seen metadata;
- revoke action with in-app confirmation;
- logout/remove-server action;
- server backup status for an administrator.

Secret values, raw tokens and provider API keys are never rendered. Android biometric unlock may protect local access to the stored renewal credential, but biometrics do not replace server authentication.

## 7. Provider settings

In remote mode, ordinary clients display provider availability and health only. Provider URL/model/secret administration belongs to a deliberate server-admin view and may be unavailable on Android in the first release.

Desktop local mode retains its OS credential-store workflow.

## 8. Files and exports

- Upload uses the Android document picker; the UI explains file size/type limits before transfer.
- Download/export uses the Android system picker or share sheet and reports the final destination honestly.
- Cancelled or backgrounded transfers return to a recoverable state.
- Source links open through the system browser.
- Files selected on Android become server-owned Sources only after the server accepts and records them.

## 9. Tutor and long-running work

Tutor, Research and other streamed activity must tolerate Android suspend/resume:

- reconnect using the authenticated session;
- resume from the server-owned turn/checkpoint/event sequence;
- never fabricate completion from a disconnected stream;
- show whether a task is running on the server and safe to leave;
- keep ask-user and approval states actionable after reconnection.

## 10. Direct APK installation and updates

The initial distribution experience is intentionally modest:

- internal users receive a debug APK or install through ADB;
- controlled users receive a project-self-signed release APK plus SHA-256 checksum and signing fingerprint;
- installation instructions explain Android's unknown-source confirmation and current developer-verification behavior;
- update instructions require the same application ID/signing key and a higher version code;
- the first release may use manual update download/install instead of an in-app silent updater.

Never describe the release APK as unsigned. Never place the keystore or passwords in the app, repository, documentation examples or downloadable release directory.

## 11. Accessibility and privacy

- Support text scaling without clipped primary actions.
- Maintain keyboard/focus behavior for desktop and TalkBack labels for Android controls.
- Respect reduced motion.
- Avoid sensitive learning/reflection content in notifications, logs and task-switcher previews by default.
- Explain server logging and backup ownership without pretending self-hosting is automatically secure.

## 12. Design acceptance

Acceptance requires real screenshots and interaction checks at representative phone and desktop sizes, plus real Android verification of Back, keyboard, rotation policy, document picker, external links, suspend/resume, login expiry and connection loss. Responsive CSS alone is not sufficient proof.
