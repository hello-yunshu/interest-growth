# Psychology Growth v0.4 Desktop Architecture (historical)

The v0.4 document records the earlier desktop design. Current runtime truth is
the Native Core plus optional DeepSeek-compatible transport; the old external
DeepTutor provider wording below is historical and does not describe a current
runtime dependency. See `docs/development/DEVELOPMENT_CONTRACT.md`.

## Product identity

Psychology Growth remains an independent, local-first product. Tauri is the desktop shell. Python Core is the product runtime. DeepSeek-compatible transport is optional. The historical external DeepTutor integration was never a fork parent, runtime parent, database owner, or required desktop dependency, and is not part of the current runtime.

## Runtime

```text
Tauri 2 desktop window
  -> static Next.js/React export
  -> Rust runtime authority
       -> random loopback port
       -> random per-launch desktop token
       -> Psychology Growth Python Core sidecar (PyInstaller)
            -> SQLite + source/artifact vault under OS app-data directory
            -> optional DeepSeek provider
            -> optional DeepTutor provider
```

The Rust shell starts and owns the Python process. The Python core never binds beyond loopback in desktop mode. HTTP routes require the per-launch token when `PG_DESKTOP_TOKEN` exists; the Tutor websocket validates the same token as a query parameter.

Desktop Provider credentials are not written to SQLite or JSON. The Rust shell stores DeepSeek API keys and optional DeepTutor auth tokens in the operating system credential store (macOS Keychain Services / Windows Credential Manager) through `keyring-rs`; only configured/not-configured state is exposed to the renderer. Non-secret provider settings are saved in `provider-settings.json` under OS App Data, validated as HTTPS or loopback HTTP, then injected into the Python Core at launch. Saving provider settings restarts only the local Core and rotates its port/token.

## Supported releases

macOS 桌面视觉保留透明窗口 + semantic sidebar material，因此平台配置显式启用 Tauri `macOSPrivateApi`。这是一项有意识的直发渠道取舍：v0.4 macOS 目标为 Developer ID signed/notarized DMG，不以 Mac App Store 为目标。

- Windows: Windows 11 24H2+ (build 26100+), **x64 release target**. Windows 10 and Windows-on-ARM are intentionally outside v0.4 release support; ARM64 can be added only after a native Python-sidecar build lane exists.
- macOS: macOS 13 Ventura+, Apple Silicon release target. Intel can be added only if a real need appears.
- Linux: development/test host only, not a v0.4 release target.

## UI architecture

The desktop client uses static Next.js output and behaves as an AI-native workspace rather than a browser dashboard: persistent compact sidebar, command palette, workspace-first content area, optional context inspector, provider status in the chrome, keyboard-first navigation, semantic surfaces and native-window materials.

## Updates

The desktop shell contains in-app update check/install commands backed by Tauri Updater. Validation builds keep the updater channel disabled. The release-config generator emits only a merge-patch delta, so it cannot overwrite platform-specific window/bundle settings. A production release that enables updates must provide `TAURI_UPDATER_ENDPOINT`, `TAURI_UPDATER_PUBLIC_KEY`, `TAURI_SIGNING_PRIVATE_KEY`, and build with `PG_UPDATER_CONFIGURED=1`. Update packages are signature-verified by Tauri before installation; the private updater key must never be committed.

## Distribution security

- macOS direct distribution requires Apple code signing and notarization.
- Windows public distribution should be code signed.
- Unsigned CI artifacts are for validation only, not end-user release.
- No updater private key, Apple certificate, or Windows signing key belongs in the repository.

## Desktop lifecycle hardening

v0.4 treats lifecycle as part of data safety, not visual shell behavior:

- the official Tauri single-instance plugin is registered before other plugins; a second launch focuses the existing `main` window;
- Core readiness is an HTTP `/api/health` probe rather than a TCP-open probe;
- runtime generation is identified by the per-launch token, so a delayed termination event from an old Core cannot overwrite a newer restarted Core;
- unexpected current-Core termination invalidates the stored endpoint/token and reports an error state to the renderer;
- the renderer listens for the termination event and refreshes runtime metadata;
- native CI launches the actual PyInstaller binary and checks health plus the protected desktop-runtime route before attempting the Tauri bundle.

## Renderer network / export boundary

The production renderer CSP cannot connect directly to external AI Provider hosts. It may use Tauri IPC and the random loopback Core only; DeepSeek/DeepTutor network calls stay in Python Core/provider adapters.

Publish-pack export in desktop mode uses Tauri's native Save dialog. The selected destination is added to the runtime filesystem scope for that session; only the file-write command needed for that selected path is exposed. Browser development keeps the ordinary download fallback.
