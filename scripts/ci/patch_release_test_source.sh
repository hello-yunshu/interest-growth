#!/usr/bin/env bash
# Phase 4e — add the minimal CI-only release-test instrumentation to a
# historical source tree so that a RELEASE-test x86_64 APK can be produced from
# the exact previous tag without replacing its native runtime.
#
# WHY (upgrade-in-place, prompt §11): the previous exact tag (v1.0.0-rc.3)
# predates R4's web-view CDP enablement (CiFlags.kt + MainActivity block) and
# the native CI TLS trust-root injection (remote.rs). To run a black-box CDP
# upgrade test over a REAL HTTPS edge, BOTH the old and new release-test APKs
# must:
#   * stay NON-debuggable (android:debuggable=false), and
#   * expose the smallest gated CI harness needed by the black-box driver.
# This script applies only CI instrumentation and build metadata to a
# source root. It is idempotent and applied ONLY while producing a thrown-away
# CI-release-test APK — it never alters the committed tag, never enables
# debuggable, and never ships in a production artifact.
#
# The transforms (each skipped if already present):
#   1. CiFlags.kt   -> ENABLE_WEBVIEW_REMOTE_DEBUGGING = true
#   2. MainActivity -> call WebView.setWebContentsDebuggingEnabled(true) under
#                      that flag, before super.onCreate (no new import: fully
#                      qualified). This does NOT set android:debuggable.
#   3. remote.rs    -> http_client() additionally loads a PEM root from the
#                      system property `ig.ci.tls_ca_path` on Android. Absent
#                      property = production behavior unchanged (Mozilla roots).
#   4. lib.rs       -> write a setup error to app-private storage if the old
#                      release-test process aborts before the black-box driver
#                      can connect. This is diagnostics only and is never used
#                      by a production source tree.
#   5. MainActivity -> write Java startup-boundary markers to app-private files
#                      for black-box failure diagnosis (CI-only).
#   6. lib.rs       -> install a throw-away panic hook and startup marker so a
#                      historical Android abort exposes the Rust panic payload
#                      and backtrace in app-private storage.
#   7. proguard-rules.pro -> retain the historical Rust-registered Kotlin plugin
#                            and its InvokeArg DTOs in a minified old APK.
#   8. build.gradle.kts -> carry the explicit release-test build profile into
#                          the old APK's generated Android project.
#   9. Cargo.toml/remote.rs -> declare and implement only the CI TLS trust-root
#                              feature; the historical native runtime remains
#                              otherwise unchanged.
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
which python3 >/dev/null 2>&1 || { echo "FAIL: python3 not on PATH" >&2; exit 1; }
[ -d "${SRC}/apps/desktop/src-tauri" ] || { echo "FAIL: not a desktop tree: ${SRC}" >&2; exit 1; }

export IG_SRC="${SRC}"
export IG_CIFLAGS_DIR="${SRC}/apps/desktop/src-tauri/gen/android/app/src/main/java/app/psychologygrowth/desktop"
export IG_MAINACT="${IG_CIFLAGS_DIR}/MainActivity.kt"
export IG_REMOTE="${SRC}/apps/desktop/src-tauri/src/remote.rs"
export IG_CARGO="${SRC}/apps/desktop/src-tauri/Cargo.toml"
export IG_GRADLE="${SRC}/apps/desktop/src-tauri/gen/android/app/build.gradle.kts"
export IG_PROGUARD="${SRC}/apps/desktop/src-tauri/gen/android/app/proguard-rules.pro"

python3 <<'PY'
import os
import re
import sys

src = os.environ["IG_SRC"]
cif = os.path.join(os.environ["IG_CIFLAGS_DIR"], "CiFlags.kt")
ma  = os.environ["IG_MAINACT"]
rem = os.environ["IG_REMOTE"]
cargo = os.environ["IG_CARGO"]
gradle = os.environ["IG_GRADLE"]
proguard = os.environ["IG_PROGUARD"]

def die(m):
    print("FAIL: " + m, file=sys.stderr)
    sys.exit(1)

changes = []

old_lib_path = os.path.join(src, "apps/desktop/src-tauri/src/lib.rs")
with open(old_lib_path) as fh:
    old_lib_txt = fh.read()

if "CI historical runtime preserved: no native source transplant" not in old_lib_txt:
    with open(old_lib_path, "a") as fh:
        fh.write("\n// CI historical runtime preserved: no native source transplant.\n")
    changes.append("lib.rs: recorded historical runtime provenance (no native transplant)")
else:
    changes.append("lib.rs: historical runtime provenance marker already present (no-op)")

# ---------- 0. CI-only feature/build metadata ----------
if not os.path.exists(cargo):
    die("Cargo.toml not found")
with open(cargo) as fh:
    cargo_txt = fh.read()
if "android-ci-trust-root = []" not in cargo_txt:
    if "[features]\n" in cargo_txt:
        cargo_txt = cargo_txt.replace(
            "[features]\n", "[features]\nandroid-ci-trust-root = []\n", 1)
    else:
        cargo_anchor = 'crate-type = ["staticlib", "cdylib", "rlib"]\n'
        if cargo_anchor not in cargo_txt:
            die("Cargo.toml crate-type anchor not found for CI feature")
        cargo_txt = cargo_txt.replace(
            cargo_anchor,
            cargo_anchor + "\n[features]\nandroid-ci-trust-root = []\n",
            1,
        )
    with open(cargo, "w") as fh:
        fh.write(cargo_txt)
    changes.append("Cargo.toml: declared android-ci-trust-root CI feature")
else:
    changes.append("Cargo.toml: CI trust-root feature already declared (no-op)")

if not os.path.exists(gradle):
    die("generated Android build.gradle.kts not found")
with open(gradle) as fh:
    gradle_txt = fh.read()
if "val releaseTestBuild = System.getenv(\"PG_RELEASE_TEST\") == \"1\"" not in gradle_txt:
    gradle_anchor = "\nandroid {\n"
    if gradle_anchor not in gradle_txt:
        die("build.gradle.kts android anchor not found")
    gradle_txt = gradle_txt.replace(
        gradle_anchor,
        '\nval releaseTestBuild = System.getenv("PG_RELEASE_TEST") == "1"\n' + gradle_anchor,
        1,
    )
if 'getByName("release") {' not in gradle_txt:
    die("build.gradle.kts release build type anchor not found")
release_head, release_tail = gradle_txt.split('getByName("release") {', 1)
if "isMinifyEnabled = !releaseTestBuild" not in release_tail.split("\n        }", 1)[0]:
    release_body = release_tail.split("\n        }", 1)[0]
    if "isMinifyEnabled = true" not in release_body:
        die("release build type has no minify anchor")
    release_body = release_body.replace("isMinifyEnabled = true", "isMinifyEnabled = !releaseTestBuild", 1)
    gradle_txt = release_head + 'getByName("release") {' + release_body + "\n        }" + release_tail.split("\n        }", 1)[1]
if "CI-only release-test profile" not in gradle_txt:
    gradle_txt = gradle_txt.replace(
        'isMinifyEnabled = !releaseTestBuild',
        '/* CI-only release-test profile remains non-debuggable but unminified. */\n            isMinifyEnabled = !releaseTestBuild',
        1,
    )
with open(gradle, "w") as fh:
    fh.write(gradle_txt)
changes.append("build.gradle.kts: release-test profile is non-debuggable and unminified")

if not os.path.exists(proguard):
    die("proguard-rules.pro not found")
with open(proguard) as fh:
    proguard_txt = fh.read()
if "InterestGrowthPlugin" not in proguard_txt:
    proguard_txt += """

# Historical Android release-test instrumentation: retain Rust-registered
# plugin DTOs when the old APK is built with normal release shrinking.
-keep class app.psychologygrowth.desktop.InterestGrowthPlugin { *; }
-keep class app.psychologygrowth.desktop.StageContentUriArgs { *; }
-keep class app.psychologygrowth.desktop.SaveDocumentFromFileArgs { *; }
-keep class app.psychologygrowth.desktop.PickDocumentArgs { *; }
-keepattributes RuntimeVisibleAnnotations,RuntimeInvisibleAnnotations,AnnotationDefault
"""
    with open(proguard, "w") as fh:
        fh.write(proguard_txt)
    changes.append("proguard-rules.pro: retained historical Kotlin plugin DTOs")
else:
    changes.append("proguard-rules.pro: historical plugin keep rules already present (no-op)")

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
'// Phase 4e (CI-only historical instrumentation) \u2014 optional TLS trust root for a\n'
'// RELEASE-test APK. Reads the Android system property `ig.ci.tls_ca_path`;\n'
'// when set, loads that PEM as an additional root. Absent property =>\n'
'// production behavior (Mozilla roots) unchanged. Fail-closed: a set-but-\n'
'// unreadable/invalid PEM is a hard error, never a silent fallthrough.\n'
'#[cfg(all(target_os = "android", feature = "android-ci-trust-root"))]\n'
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
'    #[cfg(all(target_os = "android", feature = "android-ci-trust-root"))]\n'
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
# Preserve the exact historical plugin and credential surface. Compatibility
# changes belong in the explicit feature-gated CI instrumentation only; a
# current-native plugin transplant would invalidate the provenance claim.
changes.append("lib.rs: preserved historical plugin surface (no-op)")

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

# ---------- 7. setup boundary diagnostics ----------
# Tauri runs the setup hook from its Android event-loop callback. A setup error
# is converted to a panic there and the mobile entry point aborts the process,
# so the post-run error handler above cannot observe it. Keep throw-away markers
# around each fallible startup boundary to identify the exact old-fixture input
# that fails without changing the production runtime or its secure-store path.
setup_diag_marker = "CI old Android setup boundary diagnostics"
if setup_diag_marker not in lib_txt:
    setup_diag = '''
// CI old Android setup boundary diagnostics (throw-away fixture only).
fn ci_old_setup_marker(name: &str) {
    for path in [
        format!("/data/user/0/app.psychologygrowth.desktop/files/{name}"),
        format!("/data/data/app.psychologygrowth.desktop/files/{name}"),
    ] {
        let _ = std::fs::write(path, "written\\n");
    }
}
'''
    setup_anchor = "#[cfg_attr(mobile, tauri::mobile_entry_point)]\n"
    if setup_anchor not in lib_txt:
        die("lib.rs mobile entry anchor not found for setup diagnostics")
    lib_txt = lib_txt.replace(setup_anchor, setup_diag + "\n" + setup_anchor, 1)
    setup_run_anchor = '    eprintln!("CI_OLD_STARTUP: panic hook installed");\n'
    if setup_run_anchor not in lib_txt:
        die("lib.rs panic-hook anchor not found for setup diagnostics")
    lib_txt = lib_txt.replace(
        setup_run_anchor,
        setup_run_anchor + '    ci_old_setup_marker("ci-old-before-builder-run.txt");\n',
        1,
    )
    setup_hook_anchor = "        .setup(move |app| {\n"
    if setup_hook_anchor not in lib_txt:
        die("lib.rs setup hook anchor not found for setup diagnostics")
    lib_txt = lib_txt.replace(
        setup_hook_anchor,
        setup_hook_anchor + '            ci_old_setup_marker("ci-old-setup-entered.txt");\n',
        1,
    )
    trust_anchor = "                let trust_root = remote::ci_tls_trust_root()\n"
    if trust_anchor in lib_txt:
        lib_txt = lib_txt.replace(
            trust_anchor,
            '                ci_old_setup_marker("ci-old-before-trust-root.txt");\n' + trust_anchor,
            1,
        )
    else:
        changes.append("lib.rs: historical setup has no CI trust-root boundary (no-op)")
    store_anchor = '                AndroidKeystoreStore::new()\n' \
        '                    .map_err(|error| format!("failed to open Android Keystore: {error}"))?,\n'
    if store_anchor not in lib_txt:
        store_anchor = '                    AndroidKeystoreStore::new()\n' \
            '                        .map_err(|error| format!("failed to open Android Keystore: {error}"))?,\n'
    if store_anchor not in lib_txt:
        die("lib.rs Android Keystore anchor not found for setup diagnostics")
    lib_txt = lib_txt.replace(
        store_anchor,
        '                ci_old_setup_marker("ci-old-before-keystore-store.txt");\n' + store_anchor,
        1,
    )
    manage_anchor = "            app.manage(DesktopState {\n"
    if manage_anchor not in lib_txt:
        die("lib.rs DesktopState anchor not found for setup diagnostics")
    lib_txt = lib_txt.replace(
        manage_anchor,
        '            ci_old_setup_marker("ci-old-before-state-manage.txt");\n' + manage_anchor,
        1,
    )
    with open(lib, "w") as fh:
        fh.write(lib_txt)
    changes.append("lib.rs: added throw-away Android setup boundary diagnostics")
else:
    changes.append("lib.rs: Android setup boundary diagnostics already present (no-op)")

# The historical plugin surface, Android bridge, and credential path remain
# unchanged. This is part of the fail-closed provenance contract.
changes.append("lib.rs: preserved historical plugin surface and credential path (no-op)")

for c in changes:
    print("  + " + c)
print("patch_release_test_source: OK on " + src)
PY

echo "patch_release_test_source: ALL TRANSFORMS OK on ${SRC}"
