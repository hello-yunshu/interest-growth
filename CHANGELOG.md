# Changelog

All notable changes to the public package are recorded here. This file does
not invent commit history for unpublished work.

## 1.0.17 — v1.0.17 Stable target (2026-08-21)

**Status**: pending remote Actions verification (single unified Stable matrix).

`v1.0.16` was never published: its tag pointed to an incomplete commit whose
two lockfiles (`apps/desktop/package-lock.json`, `apps/desktop/src-tauri/
Cargo.lock`) were still pinned at `1.0.15`, so `cargo --locked` (and the
dependencies gate) could not resolve the product version. Per the
immutable-tag governance this ships as `1.0.17` — `1.0.16` is recorded below
as unpublished, and `1.0.17` contains no `4`/`11`.

**Fixes (Release pipeline only):**
- Fully synced every version source to `1.0.17`, including the two committed
  `Cargo.lock` / `package-lock.json` entries for the desktop package, so the
  Rust locked build and npm clean-install see a single consistent version.
- Android `versionCode` advanced to `1000018` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).

## 1.0.16 — v1.0.16 Stable target (unpublished)

**Status**: unpublished — the `v1.0.16` tag pointed at an incomplete commit:
the two desktop lockfiles were still `1.0.15`, breaking `cargo --locked`.
The intended fixes (recorded below) ship in `1.0.17`.

**Fixes (Release pipeline only):**
- `android-upgrade-in-place` TLS edge: the ephemeral Caddy in
  `boot_tls_server.sh` now sets `bind 0.0.0.0`, so Caddy listens on the
  container network interface and the `-p <tls_port>:443` host mapping is
  reachable (`FAIL: TLS edge did not become healthy` no longer fires).
  Without it Caddy only bound the container loopback, which the published
  port cannot reach.
- Windows packaged startup smoke: `verify_packaged_startup.sh` now polls for
  the `psychology-growth-core` sidecar (up to 40s) instead of a single
  `tasklist` snapshot, so a slow first launch under the runner's Defender scan
  is not a false negative; on failure it dumps the app stdout/stderr for
  diagnosis.
- Android `versionCode` advanced to `1000017` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).

## 1.0.15 — v1.0.15 Stable target (2026-08-21)

**Status**: unpublished — the Stable Release run failed two jobs: the
`android-upgrade-in-place` TLS edge (`FAIL: TLS edge did not become healthy`),
because the ephemeral Caddy only bound the container loopback, and the Windows
packaged startup smoke (`FAIL: desktop-local sidecar not found in tasklist`).
Addressing both ships in `1.0.16`.

`v1.0.13` was never published: its Release run failed the Stable-only
`android-upgrade-in-place` old-APK build at the npm stage. The previous tag
resolved was `v1.0.12` (healthy lockfile, so the cargo-regeneration guard
did not fire), but the guard's wrapper stepped out of `apps/desktop` to
`apps/` before `npm ci`, so the lockfile was not found and `npm ci` aborted.
Fixed by running the guard inside a `( ... )` subshell that stays in
`apps/desktop`. Per the immutable-tag governance this ships as `1.0.15` —
`1.0.14` is skipped because it contains `4`.

**Fixes (Release pipeline only):**
- The prior-tag lockfile regeneration guard in the old-APK build step now
  runs in a subshell, preserving `apps/desktop` as the cwd for the subsequent
  `npm ci` (the previous version jumped to `apps/` and failed clean install).
- Android `versionCode` advanced to `1000016` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).

## 1.0.13 — v1.0.13 Stable target (unpublished)

**Status**: unpublished — the Release run failed the Stable-only
`android-upgrade-in-place` old-APK build because the lockfile self-repair
guard's `cd ../..` left the cwd at `apps/` (not `apps/desktop`), so `npm ci`
could not find the package-lock.json. Guard reworked to a subshell in
`1.0.15`.

`v1.0.12` was never published: its Release run failed the Stable-only
`android-upgrade-in-place` N-side baseline build. The immediately-preceding
tag resolved was `v1.0.10`, whose committed `Cargo.lock` still pinned the
un-published `webpki-root-certs 1.0.10` (the corruption that `1.0.12` had
already fixed on its own source but that still lived in the earlier tag's
tree), so `cargo --locked` could not resolve it while the old same-cert
release-test APK was being rebuilt. Per the immutable-tag governance this
was to ship as `1.0.13`; that slot is now recorded as unpublished and the
hardened pipeline landed in `1.0.15`.

## 1.0.12 — v1.0.12 Stable target (unpublished)

**Status**: unpublished — the Release run failed the Stable-only
`android-upgrade-in-place` old-side build because the immediately-preceding
tag (`v1.0.10`) still committed the corrupted `webpki-root-certs 1.0.10` lock
entry, which `cargo --locked` could not resolve. The pipeline hardening that
makes prior-tag lockfiles self-repairing ships in `1.0.15`.

`v1.0.10` was never published: its Release run failed the Rust / Android /
macOS cargo gates because a dependency version was corrupted during the version
sync — `webpki-root-certs` (a real crates.io package at `1.0.9`) was wrongly
rewritten to `1.0.10`, so `cargo --locked` could not resolve it. The lockfile is
restored so the genuine dependency versions are unchanged (only the product
`interest-growth-desktop` entry advances). Per the immutable-tag governance this
ships as `1.0.12` — `1.0.11` is skipped because it contains `11`.

**Fixes (Release pipeline only):**
- `apps/desktop/src-tauri/Cargo.lock` restores the genuine `webpki-root-certs`
  version (`1.0.9`) and bumps only the `interest-growth-desktop` product entry
  to `1.0.12`; macOS / Android / Rust cargo gates resolve again.
- Android `versionCode` advanced to `1000013` (monotonic; contains no `4` or
  `11` — `1000011` is skipped because it contains `11`); `MIN_CLIENT_VERSION`
  stays `1.0.0` (patch release, no protocol change).

## 1.0.10 — v1.0.10 Stable target (unpublished)

**Status**: unpublished — the Release run failed the Rust / Android / macOS
cargo gates because the version sync corrupted the `webpki-root-certs` lock
entry (`1.0.9` → `1.0.10`). Restored in `1.0.12`.

The pipeline fix first proposed for `1.0.10` over the `v1.0.9` tag SHA:
- `android-upgrade-in-place` now fetches repository tags before resolving the
  previous formal stable tag, so the old APK build baseline is available even
  with the shallow, tag-less checkout (`fetch-depth: 1` + `fetch-tags: false`)
  used by that job.
- Android `versionCode` advanced to `1000012` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).

## 1.0.9 — v1.0.9 Stable target (unpublished)

**Status**: unpublished — the Release run failed at the Stable-only
`android-upgrade-in-place` N-side baseline resolution because the job's
shallow checkout (`fetch-tags: false`) exposed no tags to `git tag`. Fixed in
`1.0.10`.

`v1.0.8` was never published: its Release run surfaced two bugs at the
Stable-only gates. (1) `android-upgrade-in-place` resolved its N-side
upgrade baseline from previously *published* non-prerelease GitHub releases —
for a first Stable this is empty, so the old APK build had no tag to build
from and failed. The fix (also carried into `1.0.10`) resolves the previous
version from descending release *git tags* (`git tag --sort=-v:refname` minus
the current tag), so a tag without a published release is a valid, honest
upgrade baseline (its old APK is rebuilt and re-signed with the current
keystore, prompt §11). (2) The web lockfile regeneration during the version
bump pulled two transitive deps (`available-typed-arrays`, `path-parse`) to a
non-existent `1.0.8`, failing npm resolution; both were pinned back to `1.0.7`.
Per the immutable-tag governance these fixes ship as the next patch `1.0.9`
(contains no `4` or `11`).

**Fixes first proposed for `1.0.9` over the v1.0.8 tag SHA**:
- `android-upgrade-in-place` N-side baseline now resolves the immediately
  preceding version **tag** instead of requiring a published Stable release,
  so a first-ever Stable has a valid upgrade baseline.
- web `package-lock.json` restores the resolvable transitive dep versions
  (`available-typed-arrays` / `path-parse` 1.0.7, neither of which exists at
  1.0.8 on the npm registry).
- Android `versionCode` advanced to `1000010` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).

## 1.0.8 — v1.0.8 Stable target (unpublished)

**Status**: unpublished — the Release run failed at the Stable-only
`android-upgrade-in-place` gate (previous-version baseline resolution) and at
npm dependency resolution. Both fixed in `1.0.9`.

The fixes first proposed for `1.0.8` over the `v1.0.7` tag SHA were:
- `android-upgrade-in-place` sets up Docker Buildx (docker-container driver)
  before building the toolchain image, so the gha layer cache works — mirrors
  the `android-signed-build` job.
- Server multi-device device-list assertion corrected to `len(devs["devices"])
  >= 2`.
- Android `versionCode` advanced to `1000009` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).

## 1.0.7 — v1.0.7 Stable target (unpublished)

**Status**: unpublished — the Release run reached the stable-only gates
(upgrade-in-place, cross-device) for the first time; the toolchain image build
lacked a docker-container builder and the device-list assertion read a dict.
Both fixed in `1.0.8`.

`v1.0.6` was never published: its Release run failed at the Android shared-cert
step because `apksigner verify --print-certs` emits one `certificate SHA-256
digest` line per merged signer (V2+V3), so BOTH release APKs produced two
fingerprints — the old global "2 lines / 1 unique" assertion was wrong for a
multi-signature APK and exited with `certs=4, unique=2` even though both APKs
were signed with the same keystore. Per the immutable-tag governance the fixes
ship as the next patch `1.0.7` (contains no `4` or `11`).

**Fixes over the v1.0.6 tag SHA** (Release workflow hardening only):
- Android shared-cert check now captures each APK's **per-signer** SHA-256
  fingerprint set into a separate file and asserts the two sets are identical,
  instead of demanding a single global fingerprint line (V2+V3 merged signing
  legitimately yields multiple entries per APK).
- Android `versionCode` advanced to `1000008` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).

## 1.0.6 — v1.0.6 Stable target (unpublished)

**Status**: unpublished — the Release matrix failed at the Android shared-cert
step (`certs=4, unique=2`, see `1.0.7` below for the fix). The fix ships as
`1.0.7`.

`v1.0.5` was never published: its Release run failed at the Android shared-cert
step, because `apksigner verify` was handed BOTH release APKs in one invocation
(that tool accepts exactly ONE APK per call) and exited with
`Unexpected parameter(s) after APK`. Per the immutable-tag governance the fixes
ship as the next patch `1.0.6` (contains no `4` or `11`).

**Fixes over the v1.0.5 tag SHA** (Release workflow hardening only):
- Android static verification now loops over each release APK (`arm64` +
  `x86_64`) and runs `apksigner verify --print-certs` separately, so the shared
  same-signing-cert check actually completes and both certificate fingerprints
  are captured.
- Android `versionCode` advanced to `1000007` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).
- The apksigner shared-cert loop replaces the previous single-command call that
  produced `Unexpected parameter(s) after APK` and failed the Android gate.

**Fixes over the v1.0.3 tag SHA** (carried forward from the failed `1.0.5`):
- Android static verification loop (see above) plus the macOS `--bundles app`
  packaging change; Android `x86_64` Rust compile fix, deterministic macOS
  binary resolver, `CiFlags.kt` WebView remote-debug leak fix.

## 1.0.5 — v1.0.5 Stable target (unpublished)

**Status**: unpublished — the Release matrix failed at Android shared-cert
verification (`apksigner verify` received multiple APKs in one call). The fix
ships as `1.0.6`.

`v1.0.2` and `v1.0.3` were never published (no GitHub Release was created), so
per the immutable-tag governance the fixes below ship as the next patch `1.0.5`
(`1.0.4` is skipped — the version must not contain the digit `4`).

**Fixes over the v1.0.3 tag SHA** (Release workflow hardening only):
- Android static verification — `apksigner verify --print-certs` accepts ONE
  APK per invocation; the shared-cert check now loops over each release APK
  separately so both arm64 + x86_64 certificates are captured and compared.
- macOS packaging — the DMG is not a release asset and its bundling is flaky
  on headless CI; the arm64 package gate now builds `--bundles app` and still
  runs the packaged `.app` startup smoke.
- Android `versionCode` advanced to `1000006` (monotonic; contains no `4` or
  `11`); `MIN_CLIENT_VERSION` stays `1.0.0` (patch release, no protocol change).

**Fixes over the v1.0.1 tag SHA** (carried forward):
- Android `x86_64` Rust compile fix, deterministic macOS binary resolver,
  `CiFlags.kt` WebView remote-debug leak fix — see the `1.0.3` entry below.

## 1.0.3 — v1.0.3 Stable target (2026-08-21)

**Status**: unpublished — the Release matrix failed at Android shared-cert
verification and macOS DMG bundling (both fixed in `1.0.5`).

`v1.0.1` and `v1.0.2` were never published (no GitHub Release was created), so
per the immutable-tag governance the fixes below ship as the next patch `1.0.3`.

**Fixes over the v1.0.1 tag SHA**:
- Android `x86_64` Rust compile fix — `__system_property_get` buffer must be
  typed `[c_char; 92]` (matches the `*mut c_char` signature on every Android
  target; `c_char` is `u8` on `aarch64` but `i8` on `x86_64`).
- Deterministic packaged-binary resolver — the macOS main app is resolved from
  `bundle/macos/<App>.app/Contents/MacOS/<CFBundleExecutable>` and hidden Cargo
  metadata is excluded, so startup smoke can no longer launch the Python
  sidecar or a build helper quasicom.
- **Production security fix** — `CiFlags.kt` no longer leaks WebView remote
  debugging: `ENABLE_WEBVIEW_REMOTE_DEBUGGING` is `false`, so the published
  production APK and normal builds always disable it (the `true` default was
  an internal test artifact flag and is confined to the throwaway x86_64
  emulator APK).
- Version bump `1.0.2 → 1.0.3` with `MIN_CLIENT_VERSION` kept at `1.0.0`
  (patch release, no protocol/API break); Android `versionCode` advanced to
  `1000005` (monotonic; `1000004` is skipped — versionCode must not contain
  the digit `4`).

## 1.0.2 — (unpublished)

Never published. Android `versionCode` was advanced to `1000003` but a
production security defect (CiFlags.kt `ENABLE_WEBVIEW_REMOTE_DEBUGGING=true`)
was found before any release created; all fixes ship in `1.0.3`.

## 1.0.1 — v1.0.1 Stable (2026-08-20)

**Status**: Stable closure merged into `main` at `422c0f1` (PR #14). Version
bump `1.0.0 → 1.0.1`; `MIN_CLIENT_VERSION` remains `1.0.0` (patch release, no
protocol/API break). All remote Actions gates green on the merged main.

**Android hardening (§6)**:
- fail-closed byte upload on Android (`byteUploadAllowed=false`; the upload
  throws before `file.arrayBuffer()`);
- immutable `getDesktopRuntimeMode()` on Android; `setDesktopRuntimeMode()`
  rejects;
- fresh-install resume resolves to `RESET` (sessionStatus-first pure
  `resumeSessionDecision()`);
- plugin surface cfg-gated per `target_os`; updater / runtime-mode commands
  reject on Android; capability-surface audit test added.

**Release pipeline**:
- `gh release create --verify-tag` + explicit tag→SHA fail-closed binding;
- `server-bundle` job (`interest-growth-server-<version>.tar.gz`);
- Windows/macOS/server assets attached to the release; single `SHA256SUMS.txt`
  over exactly the attached assets (debug APK never included);
- actionlint pinned to an immutable image digest.

**Android**: `versionCode` `1000001 → 1000002` (monotonic, gate-checked).

## 1.0.0 — v1.0.0-rc.1 (2026-08-17)

**Published**: v1.0.0 release candidate 1, prerelease, at
https://github.com/hello-yunshu/interest-growth/releases with a signed
Android arm64 APK, SPDX SBOM, SHA256SUMS and a verification report.

**Release evidence**: GitHub Actions run `32000632965` — all gates PASS on
the tag commit (`877734d`, tag SHA == build SHA): repository integrity,
Python host, Web/ClientRuntime, Rust, Docker integration, dependency
security, **Android signed release APK + static verification** (signing
keystore secrets now configured; APK Signature Scheme v2), and the **Android
emulator real remote vertical slice** (login → … → logout_revoke, all
`ok=true`, `result=PASS`), then publish.

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
