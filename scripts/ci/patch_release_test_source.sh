#!/usr/bin/env bash
# Phase 4e — build-time transplant of the R4 CI-only release-test harness into a
# source tree, so that a RELEASE-test x86_64 APK can be produced from a tag
# whose runtime predates the R4 CI hooks (e.g. building the "previous" N side
# of the upgrade-in-place proof from the exact previous tag).
#
# WHY (upgrade-in-place, prompt §11): the previous exact tag (v1.0.0-rc.3)
# predates R4's web-view CDP enablement (CiFlags.kt + MainActivity block) and
# the native CI TLS trust-root injection (remote.rs). To run a black-box CDP
# upgrade test over a REAL HTTPS edge, BOTH the old and new release-test APKs
# must:
#   * stay NON-debuggable (android:debuggable=false), and
#   * expose the same gated CI harness (self-contained, production-off).
# This script applies exactly those three, committed, gated enablers to a
# source root. It is idempotent and applied ONLY while producing a thrown-away
# CI-release-test APK — it never alters the committed tag, never enables
# debuggable, and never ships in a production artifact.
#
# The seven transforms (each skipped if already present):
#   1. CiFlags.kt   -> ENABLE_WEBVIEW_REMOTE_DEBUGGING = true
#   2. MainActivity -> call WebView.setWebContentsDebuggingEnabled(true) under
#                      that flag, after super.onCreate (no new import: fully
#                      qualified). This does NOT set android:debuggable.
#   3. remote.rs    -> http_client() additionally loads a PEM root from the
#                      system property `ig.ci.tls_ca_path` on Android. Absent
#                      property = production behavior unchanged (Mozilla roots).
#   4. lib.rs       -> write a setup error to app-private storage if the old
#                      release-test process aborts before the black-box driver
#                      can connect. This is diagnostics only and is never used
#                      by a production source tree.
#   5. lib.rs       -> keep historical Android plugins out of the old APK, so a
#                      historical Android release-test source does not abort
#                      during native plugin initialization. This is the same
#                      minimal Android surface as the current production source.
#   6. MainActivity -> write Java startup-boundary markers to app-private files
#                      for black-box failure diagnosis (CI-only).
#   7. lib.rs       -> install a throw-away panic hook and startup marker so a
#                      historical Android abort exposes the Rust panic payload
#                      and backtrace in app-private storage.
#
# Usage:
#   scripts/ci/patch_release_test_source.sh <src_root>
#
# Fail-closed: any transform that cannot be applied cleanly aborts (exit 1) so
# a silently-unpatched APK can never be mistaken for a valid test artifact.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <src_root>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

which python3 >/dev/null 2>&1 || { echo "FAIL: python3 not on PATH" >&2; exit 1; }
[ -d "${SRC}/apps/desktop/src-tauri" ] || { echo "FAIL: not a desktop tree: ${SRC}" >&2; exit 1; }

export IG_SRC="${SRC}"
export IG_REPO_ROOT="${REPO_ROOT}"
export IG_CIFLAGS_DIR="${SRC}/apps/desktop/src-tauri/gen/android/app/src/main/java/app/psychologygrowth/desktop"
export IG_MAINACT="${IG_CIFLAGS_DIR}/MainActivity.kt"
export IG_REMOTE="${SRC}/apps/desktop/src-tauri/src/remote.rs"

python3 <<'PY'
import os
import re
import sys

src = os.environ["IG_SRC"]
repo_root = os.environ["IG_REPO_ROOT"]
cif = os.path.join(os.environ["IG_CIFLAGS_DIR"], "CiFlags.kt")
ma  = os.environ["IG_MAINACT"]
rem = os.environ["IG_REMOTE"]

def die(m):
    print("FAIL: " + m, file=sys.stderr)
    sys.exit(1)

changes = []

# The published baseline predates the current Android startup/runtime contract.
# Its historical native entry aborts inside Tauri's mobile start thread before
# `run()` can execute, so the upgrade proof cannot reach the black-box driver.
# Build the thrown-away old-version APK with the current, already-qualified
# native runtime while retaining the baseline version metadata and Web source.
# This is a CI-only source transplant: the current product tree is never
# modified, and the resulting APK is never used as a production artifact.
native_transplanted = False
old_manifest = os.path.join(src, "apps/desktop/src-tauri/Cargo.toml")
old_lock = os.path.join(src, "apps/desktop/src-tauri/Cargo.lock")
with open(old_manifest) as fh:
    old_manifest_txt = fh.read()
old_version_match = re.search(r'^version\s*=\s*"([^"]+)"', old_manifest_txt, re.MULTILINE)
if not old_version_match:
    die("old Cargo.toml package version not found")
old_version = old_version_match.group(1)
native_marker = "CI throw-away baseline build uses current qualified native runtime"
old_lib_path = os.path.join(src, "apps/desktop/src-tauri/src/lib.rs")
with open(old_lib_path) as fh:
    old_lib_txt = fh.read()
if native_marker not in old_lib_txt:
    native_paths = [
        "apps/desktop/src-tauri/src/lib.rs",
        "apps/desktop/src-tauri/src/remote.rs",
        "apps/desktop/src-tauri/src/runtime_mode.rs",
        "apps/desktop/src-tauri/src/android_bridge.rs",
        "apps/desktop/src-tauri/src/ui_ipc_e2e.rs",
        "apps/desktop/src-tauri/Cargo.toml",
        "apps/desktop/src-tauri/Cargo.lock",
    ]
    for relative in native_paths:
        source = os.path.join(repo_root, relative)
        target = os.path.join(src, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(source, "rb") as source_fh, open(target, "wb") as target_fh:
            target_fh.write(source_fh.read())
    with open(os.path.join(src, "apps/desktop/src-tauri/Cargo.toml")) as fh:
        manifest_txt = fh.read()
    manifest_txt = re.sub(
        r'^(version\s*=\s*)"[^"]+"',
        r'\g<1>"' + old_version + '"',
        manifest_txt,
        count=1,
        flags=re.MULTILINE,
    )
    with open(os.path.join(src, "apps/desktop/src-tauri/Cargo.toml"), "w") as fh:
        fh.write(manifest_txt)
    with open(os.path.join(src, "apps/desktop/src-tauri/Cargo.lock")) as fh:
        lock_txt = fh.read()
    lock_txt = lock_txt.replace(
        'name = "interest-growth-desktop"\nversion = "1.0.20"',
        'name = "interest-growth-desktop"\nversion = "' + old_version + '"',
        1,
    )
    with open(os.path.join(src, "apps/desktop/src-tauri/Cargo.lock"), "w") as fh:
        fh.write(lock_txt)
    with open(old_lib_path, "a") as fh:
        fh.write("\n// " + native_marker + ".\n")
    native_transplanted = True
    changes.append("old baseline: transplanted current qualified native runtime; restored baseline Cargo version " + old_version)
else:
    native_transplanted = True
    changes.append("old baseline: current qualified native runtime already transplanted (no-op)")

CIFLAGS = (
'// Phase 4c/e \u2014 build-time CI capability flag for a RELEASE-test APK.\n'
'//\n'
'// This is a SOURCE flag, read by MainActivity and compiled into the APK. The\n'
'// committed default is `false`; CI builds the x86_64 release-test APK (used by\n'
'// the upgrade-in-place emulator job) with `true`. Enablement does NOT set\n'
'// android:debuggable, so the APK stays non-debuggable (verified by\n'
'// verify_upgrade_apk_pair.sh) and the flag is inert in every production build.\n'
'object CiFlags {\n'
'  const val ENABLE_WEBVIEW_REMOTE_DEBUGGING: Boolean = true\n'
'}\n'
)

# ---------- 1. CiFlags.kt ----------
if not os.path.exists(cif):
    os.makedirs(os.path.dirname(cif), exist_ok=True)
    with open(cif, "w") as fh:
        fh.write(CIFLAGS)
    changes.append("CiFlags.kt: created with ENABLE_WEBVIEW_REMOTE_DEBUGGING=true")
else:
    with open(cif) as fh:
        txt = fh.read()
    if "ENABLE_WEBVIEW_REMOTE_DEBUGGING: Boolean = true" not in txt:
        if re.search(r"ENABLE_WEBVIEW_REMOTE_DEBUGGING:\s*Boolean\s*=\s*false", txt):
            txt = txt.replace(
                "ENABLE_WEBVIEW_REMOTE_DEBUGGING: Boolean = false",
                "ENABLE_WEBVIEW_REMOTE_DEBUGGING: Boolean = true")
        else:
            die("CiFlags.kt exists but has no ENABLE_WEBVIEW_REMOTE_DEBUGGING Boolean to enable")
        with open(cif, "w") as fh:
            fh.write(txt)
        changes.append("CiFlags.kt: flipped ENABLE_WEBVIEW_REMOTE_DEBUGGING to true")
    else:
        changes.append("CiFlags.kt: already enabled (no-op)")

# ---------- 2. MainActivity.kt ----------
if not os.path.exists(ma):
    die("MainActivity.kt not found under " + os.path.dirname(ma))
with open(ma) as fh:
    ma_txt = fh.read()
if "CiFlags.ENABLE_WEBVIEW_REMOTE_DEBUGGING" not in ma_txt:
    if "override fun onCreate(savedInstanceState: Bundle?) {" not in ma_txt:
        die("MainActivity.kt has no onCreate anchor to patch")
    block = (
"    // Phase 4c/e \u2014 CI-only release-test APK enables WebView CDP.\n"
"    // Run before super.onCreate(): Tauri creates the WebView during super, so\n"
"    // the process-wide debugging flag must be set before that boundary.\n"
"    // WebView debugging applies\n"
"    // to the WebView created by Tauri. It does NOT set android:debuggable; the\n"
"    // flag is inert in production (CiFlags default false).\n"
"    if (CiFlags.ENABLE_WEBVIEW_REMOTE_DEBUGGING) {\n"
"      android.webkit.WebView.setWebContentsDebuggingEnabled(true)\n"
"    }\n"
    )
    super_anchor = "    super.onCreate(savedInstanceState)\n"
    if super_anchor in ma_txt:
        ma_txt = ma_txt.replace(super_anchor, block + super_anchor, 1)
    else:
        ma_txt = ma_txt.replace(
            "override fun onCreate(savedInstanceState: Bundle?) {",
            "override fun onCreate(savedInstanceState: Bundle?) {\n" + block, 1)
    with open(ma, "w") as fh:
        fh.write(ma_txt)
    changes.append("MainActivity.kt: inserted WebView CDP enablement block")
else:
    changes.append("MainActivity.kt: CDP block already present (no-op)")

# ---------- 2b. MainActivity startup boundary diagnostics ----------
# The Rust mobile entry point runs from TauriActivity.super.onCreate(). If a
# historical APK aborts before the Rust `run()` body can emit diagnostics, use
# Android's own log buffer to distinguish the Java/Keystore boundary from the
# JNI/native entry boundary. This is throw-away CI instrumentation only.
activity_marker = "CI_OLD_STARTUP: MainActivity onCreate"
if "ci-old-java-oncreate.txt" not in ma_txt:
    on_create_anchor = "  override fun onCreate(savedInstanceState: Bundle?) {\n"
    if on_create_anchor not in ma_txt:
        die("MainActivity.kt onCreate anchor not found for startup diagnostics")
    marker_helper = (
        "  private fun ciMarker(name: String) {\n"
        "    runCatching { java.io.File(applicationContext.filesDir, name).writeText(\"written\\n\") }\n"
        "  }\n"
    )
    ma_txt = ma_txt.replace(
        on_create_anchor,
        marker_helper
        + on_create_anchor
        + '    ciMarker("ci-old-java-oncreate.txt")\n'
        + '    android.util.Log.e("CI_OLD_STARTUP", "MainActivity onCreate entered")\n',
        1,
    )
    keyring_anchor = "    Keyring.initializeNdkContext(applicationContext)\n"
    if keyring_anchor not in ma_txt:
        die("MainActivity.kt Keyring initialization anchor not found")
    ma_txt = ma_txt.replace(
        keyring_anchor,
        '    ciMarker("ci-old-java-before-keyring.txt")\n'
        '    android.util.Log.e("CI_OLD_STARTUP", "before Keyring.initializeNdkContext")\n'
        + keyring_anchor
        + '    ciMarker("ci-old-java-after-keyring.txt")\n'
        + '    android.util.Log.e("CI_OLD_STARTUP", "after Keyring.initializeNdkContext")\n',
        1,
    )
    super_anchor = "    super.onCreate(savedInstanceState)\n"
    if super_anchor not in ma_txt:
        die("MainActivity.kt super.onCreate anchor not found for startup diagnostics")
    ma_txt = ma_txt.replace(
        super_anchor,
        super_anchor
        + '    ciMarker("ci-old-java-after-super.txt")\n'
        + '    android.util.Log.e("CI_OLD_STARTUP", "after super.onCreate")\n',
        1,
    )
    with open(ma, "w") as fh:
        fh.write(ma_txt)
    changes.append("MainActivity.kt: added Java startup boundary diagnostics")
else:
    changes.append("MainActivity.kt: startup boundary diagnostics already present (no-op)")

# ---------- 3. remote.rs ----------
if not os.path.exists(rem):
    die("remote.rs not found")
with open(rem) as fh:
    rem_txt = fh.read()

HELPER = (
'// Phase 4e (transplanted, CI-only) \u2014 optional TLS trust root for a\n'
'// RELEASE-test APK. Reads the Android system property `ig.ci.tls_ca_path`;\n'
'// when set, loads that PEM as an additional root. Absent property =>\n'
'// production behavior (Mozilla roots) unchanged. Fail-closed: a set-but-\n'
'// unreadable/invalid PEM is a hard error, never a silent fallthrough.\n'
'#[cfg(target_os = "android")]\n'
'fn ci_ci_tls_trust_root_pem_path() -> Option<String> {\n'
'    use std::ffi::CStr;\n'
'    let mut value = [0i8; 92];\n'
'    extern "C" { fn __system_property_get(name: *const i8, value: *mut i8) -> i32; }\n'
'    // SAFETY: NAME is a NUL-terminated string; value is a 92-byte buffer that\n'
'    // __system_property_get fills with a NUL-terminated string.\n'
'    let n = unsafe {\n'
'        __system_property_get(b"ig.ci.tls_ca_path\\0".as_ptr() as *const i8, value.as_mut_ptr())\n'
'    };\n'
'    if n <= 0 { return None; }\n'
'    let text = unsafe { CStr::from_ptr(value.as_ptr()) }.to_string_lossy().into_owned();\n'
'    if text.trim().is_empty() { None } else { Some(text.trim().to_owned()) }\n'
'}\n\n'
)

NEW_CLIENT = (
'fn http_client() -> Result<reqwest::Client, String> {\n'
'    let mut builder = reqwest::Client::builder()\n'
'        .timeout(REQUEST_TIMEOUT)\n'
'        .connect_timeout(CONNECT_TIMEOUT)\n'
'        .user_agent(format!("interest-growth-desktop/{CLIENT_APP_VERSION}"))\n'
'        .redirect(reqwest::redirect::Policy::none());\n'
'    #[cfg(target_os = "android")]\n'
'    if let Some(pem) = ci_ci_tls_trust_root_pem_path() {\n'
'        let bytes = std::fs::read(&pem)\n'
'            .map_err(|e| format!("cannot read CI TLS trust root {pem}: {e}"))?;\n'
'        let cert = reqwest::Certificate::from_pem(&bytes)\n'
'            .map_err(|e| format!("invalid CI TLS trust root {pem}: {e}"))?;\n'
'        builder = builder.add_root_certificate(cert);\n'
'    }\n'
'    builder.build().map_err(|error| error.to_string())\n'
'}\n'
)

# Sentinel for the R4 NATIVE trust-root implementation (the "new"/N+1 side of the
# upgrade test is built from the R4 source directly; it must NOT be patched).
NATIVE_SENTINELS = ("http_client_with_trust_root", "load_pem_trust_root",
                    "android_system_property")
has_patch_symbol = "ci_ci_tls_trust_root_pem_path" in rem_txt
has_native_sentinel = any(s in rem_txt for s in NATIVE_SENTINELS)
if not has_patch_symbol and not has_native_sentinel:
    # Match the whole R3/R4 http_client() function (no nested braces inside).
    pat = re.compile(r"fn http_client\(\) -> Result<reqwest::Client, String> \{\n.*?\n\}", re.DOTALL)
    if not pat.search(rem_txt):
        die("remote.rs http_client() body does not match the expected R3/R4 layout; refusing a blind patch")
    rem_txt = pat.sub(NEW_CLIENT, rem_txt, count=1)
    rem_txt = rem_txt.replace(
        "fn http_client() -> Result<reqwest::Client, String> {\n",
        HELPER + "fn http_client() -> Result<reqwest::Client, String> {\n", 1)
    with open(rem, "w") as fh:
        fh.write(rem_txt)
    changes.append("remote.rs: added ci_ci_tls_trust_root_pem_path + trust-root in http_client()")
elif has_patch_symbol:
    changes.append("remote.rs: patch trust-root support already present (no-op)")
else:
    changes.append("remote.rs: native R4 trust-root support present (no-op)")

# ---------- 4. lib.rs startup diagnostics ----------
# The old release-test APK is built from a historical tag. If its native
# setup returns an error, Tauri aborts the process and the CDP driver can only
# report that the app disappeared. Keep the exact setup error in app-private
# storage so the emulator step can expose it without changing product code.
lib = os.path.join(src, "apps/desktop/src-tauri/src/lib.rs")
if not os.path.exists(lib):
    die("lib.rs not found")
with open(lib) as fh:
    lib_txt = fh.read()
diagnostic_marker = "ci-old-startup-error.txt"
if diagnostic_marker not in lib_txt:
    old_run = '''    builder
        .run(tauri::generate_context!())
        .expect("error while running Interest Growth desktop");'''
    new_run = '''    if let Err(error) = builder.run(tauri::generate_context!()) {
        let detail = format!("CI old Android startup error: {error:?}\\n{error}");
        for path in [
            "/data/user/0/app.psychologygrowth.desktop/files/ci-old-startup-error.txt",
            "/data/data/app.psychologygrowth.desktop/files/ci-old-startup-error.txt",
        ] {
            let _ = std::fs::write(path, &detail);
        }
        panic!("{detail}");
    }'''
    if old_run not in lib_txt:
        die("lib.rs run error anchor not found")
    lib_txt = lib_txt.replace(old_run, new_run, 1)
    with open(lib, "w") as fh:
        fh.write(lib_txt)
    changes.append("lib.rs: added throw-away startup error diagnostic")
else:
    changes.append("lib.rs: startup error diagnostic already present (no-op)")

# ---------- 5. historical Android plugin surface ----------
# v1.0.0-rc.3 registers desktop shell/updater/dialog/fs/opener and SAF bridge plugins on Android.
# That old native plugin surface aborts before setup can return a Result on the
# API 35 release-test emulator. Transplant the later, committed target_os split
# into the throw-away old APK source. The Android behavior then matches the
# current production plugin surface; desktop builds of the historical source
# retain the original plugins. This is deliberately exact-anchor and fail-closed.
android_plugin_marker = "CI historical Android plugin surface: desktop-only plugins"
if android_plugin_marker not in lib_txt:
    old_plugins = '''    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_opener::init())
        // Gate R0.5/R0.6 — registers the Kotlin InterestGrowthPlugin on
        // Android (no-op plugin on desktop). The SAF bridge lets the native
        // layer read/write file bytes without a renderer base64 copy.
        .plugin(android_bridge::init());'''
    new_plugins = '''    // CI historical Android plugin surface: desktop-only plugins
    // are excluded from the old release-test APK, matching the current
    // production broker + WebView surface and preventing native plugin-init
    // aborts in the historical generated Android host.
    let mut builder = tauri::Builder::default();
    #[cfg(not(target_os = "android"))]
    {
        builder = builder
            .plugin(tauri_plugin_shell::init())
            .plugin(tauri_plugin_updater::Builder::new().build())
            .plugin(tauri_plugin_dialog::init())
            .plugin(tauri_plugin_fs::init())
            .plugin(tauri_plugin_opener::init());
    }
    // The old upgrade fixture does not exercise the SAF bridge. Keep it out
    // of the historical Android host; it remains registered in production.
    #[cfg(not(target_os = "android"))]
    {
        builder = builder.plugin(android_bridge::init());
    }'''
    if old_plugins not in lib_txt:
        if native_transplanted and "Gate R2 §6.4 — desktop vs Android plugin surface is structurally split." in lib_txt:
            changes.append("lib.rs: current qualified Android plugin surface already present (no-op)")
        else:
            die("historical Android plugin registration anchor not found")
    else:
        lib_txt = lib_txt.replace(old_plugins, new_plugins, 1)
        with open(lib, "w") as fh:
            fh.write(lib_txt)
        changes.append("lib.rs: transplanted minimal historical Android plugin surface")
else:
    changes.append("lib.rs: historical Android plugin surface already present (no-op)")

# ---------- 6. historical Android startup panic diagnostics ----------
# Tauri's Android JNI entry aborts the process when the start thread panics;
# the native crash backtrace otherwise stops at __start_app and hides the
# payload. This hook is only installed in the throw-away historical source.
panic_marker = "CI old Android panic diagnostic hook"
if panic_marker not in lib_txt:
    old_run_start = "pub fn run() {\n"
    new_run_start = '''pub fn run() {
    // CI old Android panic diagnostic hook (throw-away historical source).
    eprintln!("CI_OLD_STARTUP: run entered");
    for directory in [
        "/data/user/0/app.psychologygrowth.desktop/files",
        "/data/data/app.psychologygrowth.desktop/files",
    ] {
        let _ = std::fs::create_dir_all(directory);
    }
    for path in [
        "/data/user/0/app.psychologygrowth.desktop/files/ci-old-startup-entered.txt",
        "/data/data/app.psychologygrowth.desktop/files/ci-old-startup-entered.txt",
    ] {
        let _ = std::fs::write(path, "run entered\\n");
    }
    std::panic::set_hook(Box::new(|info| {
        let payload = info
            .payload()
            .downcast_ref::<&str>()
            .copied()
            .or_else(|| info.payload().downcast_ref::<String>().map(String::as_str))
            .unwrap_or("non-string panic payload");
        let detail = format!(
            "CI old Android panic: {info}\\npayload={payload}\\nbacktrace={:?}\\n",
            std::backtrace::Backtrace::force_capture(),
        );
        for path in [
            "/data/user/0/app.psychologygrowth.desktop/files/ci-old-startup-panic.txt",
            "/data/data/app.psychologygrowth.desktop/files/ci-old-startup-panic.txt",
        ] {
            let _ = std::fs::write(path, &detail);
        }
    }));
    eprintln!("CI_OLD_STARTUP: panic hook installed");
'''
    if old_run_start not in lib_txt:
        die("lib.rs run start anchor not found")
    lib_txt = lib_txt.replace(old_run_start, new_run_start, 1)
    with open(lib, "w") as fh:
        fh.write(lib_txt)
    changes.append("lib.rs: added throw-away startup panic diagnostic hook")
else:
    changes.append("lib.rs: startup panic diagnostic hook already present (no-op)")

for c in changes:
    print("  + " + c)
print("patch_release_test_source: OK on " + src)
PY

echo "patch_release_test_source: ALL TRANSFORMS OK on ${SRC}"
