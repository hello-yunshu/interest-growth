# Interest Growth v0.7 — Android APK Release Verification Report

Verification date: 2026-08-15
Build path: `apps/desktop/src-tauri/gen/android/app/build/outputs/apk/universal/release/app-universal-release.apk`
Copy: `dist/android/interest-growth-0.7.0-universal-release.apk`

## 1. Artifact identity

| Field | Value |
| --- | --- |
| APK file | `interest-growth-0.7.0-universal-release.apk` |
| applicationId | `app.psychologygrowth.desktop` |
| versionName | `0.7.0` |
| versionCode | `7000` |
| minSdk | 24 |
| targetSdk | 36 |
| compileSdk | 36 |
| Supported ABIs (packed) | `arm64-v8a` (single canonical `.so`) |
| Size | 25 MB (26,136,169 bytes) |
| APK SHA-256 | `01ce82e4a2a03a6cca41a06fe15c3e1342bae0ee9f948afd02097c7499092024` |

## 2. Signing

Tool: Android SDK `apksigner verify --verbose --print-certs`

```
Verifies
Verified using v1 scheme (JAR signing): false
Verified using v2 scheme (APK Signature Scheme v2): true
Verified using v3 scheme: false
Number of signers: 1
Signer #1 certificate DN:      CN=Interest Growth, OU=Interest Growth, O=Interest Growth, C=CN
Signer #1 certificate SHA-256: 66871e8685d5bd7c3cc719e0b2ea2b8af2809a7648e333b0fe493a0cf41aa66f
Signer #1 key algorithm:       RSA, 2048 bits
```

- Signing key is project-owned, stored **outside the repository** (`~/Documents/GitHub/interest-growth-keystore`, mounted read-only into the build container at `/keystore`).
- Passwords are supplied via gitignored `keystore.properties` (and/or `PG_ANDROID_*` env vars); no `storePassword` / `keyPassword` / private key is committed to Gradle tracked source.
- Cert SHA-256 must remain stable for upgrade-in-place.

## 3. Build method

Built in a reproducible Docker environment (`scripts/android-docker.sh`, image `interest-growth-android`):

```bash
docker exec ig-build bash -c 'cd /work/apps/desktop && npx tauri android build --apk --target aarch64'
```

- CLI: `@tauri-apps/cli` 2.11.4; Rust `aarch64-linux-android` release build succeeded (no addr-file panic because the whole flow is driven through `tauri android build`, keeping the CLI WebSocket server alive).
- `jniLibs` packaging excludes numbered duplicates (`**/libinterest_growth_desktop_lib *.so`) so the APK contains exactly one canonical `.so`.

## 4. APK hygiene (Gate F §8.5)

Static inspection of APK entries (`unzip -l` + config dump):

- no Python / `.py` / `.pyc` sidecar: none;
- no provider secret, bootstrap token, release private key, `*.pem`/`*.jks`/key material: none (only standard META-INF license texts);
- no local canonical DB / `.db` / sqlite seed: none;
- no desktop updater payload; bundled `assets/tauri.conf.json` has `plugins.updater.pubkey` empty and no cleartext override;
- no `usesCleartextTraffic=true`; `network_security_config.xml` is fail-closed (`cleartextTrafficPermitted=false`, system trust anchors only);
- exactly one canonical `.so` per ABI (arm64-v8a).

## 5. What is verified / not verified

Verified in this environment:

- APK produced and **signature verified** (v2) with the project release key;
- APK hygiene (static) PASS;
- `aarch64-linux-android` release Rust build compiles; Android runtime/secure-store/network code compiled into the artifact.

NOT verified (explicit hardware/toolchain boundary — do not infer as PASS):

- emulator install / cold launch / runtime UX (no emulator image in this environment);
- physical-device install / lifecycle / enrollment / login / refresh / revoke / upload / download;
- upgrade-in-place (v0.7.0 build N → N+1 on the same key);
- cross-device proof (Client A desktop-remote + Client B android-remote on one server);
- real public-TLS server enrollment on Android.

## 6. Re-verification commands

```bash
shasum -a 256 dist/android/interest-growth-0.7.0-universal-release.apk
apksigner verify --verbose --print-certs dist/android/interest-growth-0.7.0-universal-release.apk
unzip -l dist/android/interest-growth-0.7.0-universal-release.apk | grep 'lib/arm64-v8a/'
```
