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
# The three transforms (each skipped if already present):
#   1. CiFlags.kt   -> ENABLE_WEBVIEW_REMOTE_DEBUGGING = true
#   2. MainActivity -> call WebView.setWebContentsDebuggingEnabled(true) under
#                      that flag, before super.onCreate (no new import: fully
#                      qualified). This does NOT set android:debuggable.
#   3. remote.rs    -> http_client() additionally loads a PEM root from the
#                      system property `ig.ci.tls_ca_path` on Android. Absent
#                      property = production behavior unchanged (Mozilla roots).
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

python3 <<'PY'
import os
import re
import sys

src = os.environ["IG_SRC"]
cif = os.path.join(os.environ["IG_CIFLAGS_DIR"], "CiFlags.kt")
ma  = os.environ["IG_MAINACT"]
rem = os.environ["IG_REMOTE"]

def die(m):
    print("FAIL: " + m, file=sys.stderr)
    sys.exit(1)

changes = []

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
"    // Run after super.onCreate(): Tauri starts the native Rust setup thread\n"
"    // during super, so enabling CDP must not race Android Keystore/broker\n"
"    // initialization. WebView debugging is a process-wide setting and applies\n"
"    // to the WebView created by Tauri. It does NOT set android:debuggable; the\n"
"    // flag is inert in production (CiFlags default false).\n"
"    if (CiFlags.ENABLE_WEBVIEW_REMOTE_DEBUGGING) {\n"
"      android.webkit.WebView.setWebContentsDebuggingEnabled(true)\n"
"    }\n"
    )
    super_anchor = "    super.onCreate(savedInstanceState)\n"
    if super_anchor in ma_txt:
        ma_txt = ma_txt.replace(super_anchor, super_anchor + block, 1)
    else:
        ma_txt = ma_txt.replace(
            "override fun onCreate(savedInstanceState: Bundle?) {",
            "override fun onCreate(savedInstanceState: Bundle?) {\n" + block, 1)
    with open(ma, "w") as fh:
        fh.write(ma_txt)
    changes.append("MainActivity.kt: inserted WebView CDP enablement block")
else:
    changes.append("MainActivity.kt: CDP block already present (no-op)")

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

for c in changes:
    print("  + " + c)
print("patch_release_test_source: OK on " + src)
PY

echo "patch_release_test_source: ALL TRANSFORMS OK on ${SRC}"
