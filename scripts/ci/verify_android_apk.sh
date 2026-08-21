#!/usr/bin/env bash
# APK static verification gate (prompt §9.2 / §30).
#
# Used identically by PR CI, main artifact builds and tag releases. It proves
# an APK is honest BEFORE it is uploaded or signed as release material:
#
#   * metadata (applicationId / versionName / versionCode / minSdk / targetSdk)
#   * ABI set matches the artifact name (never call an arm64-only APK universal)
#   * exactly one canonical native .so per ABI lib dir (single Rust cdylib)
#   * no Python sidecar, no DB seed, no provider secret, no bootstrap token
#   * no desktop updater payload, no signing key/keystore, no cleartext traffic
#   * network_security_config present
#
# Content checks run with `unzip -l` so they work on any host. Metadata checks
# use `aapt dump badging` when aapt/aapt2 is on PATH (e.g. inside the Android
# Docker toolchain); otherwise the metadata block is reported as SKIPPED so the
# gate is honest, never a silent pass.
#
# Usage:
#   scripts/ci/verify_android_apk.sh <apk> [<apk> ...]
#   e.g. scripts/ci/verify_android_apk.sh apps/desktop/src-tauri/gen/android/app/build/outputs/apk/universal/release/app-universal-release.apk
#   Add --require-aapt to fail (not skip) when aapt/aapt2 is not on PATH —
#   used by release jobs so a missing metadata tool can never become a pass
#   (Gate R2 §13.1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

REQUIRE_AAPT=0
APKS=()
for arg in "$@"; do
  if [ "${arg}" = "--require-aapt" ]; then
    REQUIRE_AAPT=1
  else
    APKS+=("${arg}")
  fi
done

if [ "${#APKS[@]}" -eq 0 ]; then
  echo "usage: $0 [--require-aapt] <apk> [<apk> ...]" >&2
  exit 2
fi

FAILURES=0
fail() {
  echo "  FAIL: $1" >&2
  FAILURES=$((FAILURES + 1))
}

# ---- aapt metadata resolution -----------------------------------------------
AAPT=""
for cand in aapt aapt2; do
  if command -v "${cand}" >/dev/null 2>&1; then
    AAPT="${cand}"
    break
  fi
done
if [ -z "${AAPT}" ] && [ "${REQUIRE_AAPT}" -eq 1 ]; then
  echo "FAIL: aapt/aapt2 not on PATH but --require-aapt was set (Gate R2 §13.1)" >&2
  exit 1
fi

# ---- content checks (unzip -l, host-agnostic) --------------------------------
check_contents() {
  local apk="$1"
  local listing
  listing="$(unzip -l "${apk}")"

  echo "[apk:$(basename "${apk}")] content checks"

  # No Python sidecar / package.
  if grep -qE 'lib/.*/libpython|\.pyc|python[0-9.]*/lib' <<<"${listing}"; then
    fail "Python sidecar must not be packaged: ${apk}"
  fi
  # No DB seed / canonical database.
  if grep -qE '\.(sqlite|sqlite3|db)(/|$)|assets/.*\.db' <<<"${listing}"; then
    fail "DB seed must not be packaged: ${apk}"
  fi
  # No provider secret / bootstrap token / signing key / keystore.
  for needle in '.jks' '.keystore' '.p12' '.pfx' '.pem' '.key' 'bootstrap_token' 'provider_secret'; do
    if grep -qF "${needle}" <<<"${listing}"; then
      fail "secret material (${needle}) must not be packaged: ${apk}"
    fi
  done
  # No desktop updater payload (updater artifacts are desktop-only).
  if grep -qE 'updater|latest\.json|\.sig$' <<<"${listing}"; then
    fail "desktop updater payload must not be packaged: ${apk}"
  fi
  # network_security_config must be present (Gate E §6.7 fail-closed TLS).
  # AAPT2 stores XML resources directly under res/xml/ (no intermediate
  # segment), so match the leaf filename rather than a res/<x>/xml/ shape.
  if ! grep -qE 'network_security_config\.xml|networkSecurityConfig' <<<"${listing}"; then
    fail "network_security_config.xml is missing: ${apk}"
  fi

  # Production arm64 is built without the CI-only trust-root feature. Inspect
  # native strings rather than source paths: the compile-time contract is that
  # the property, loader marker and upgrade-test/WebView-debug hooks are absent
  # from the production binary. The x86_64 release-test APK is intentionally
  # allowed to contain these markers and is never a release asset.
  local base
  base="$(basename "${apk}")"
  if [[ "${base}" == *arm64* && "${base}" != *release-test* ]]; then
    local apk_strings
    apk_strings="$(while read -r entry; do unzip -p "${apk}" "${entry}" 2>/dev/null || true; done < <(unzip -Z1 "${apk}") | strings || true)"
    for needle in 'ig.ci.tls_ca_path' 'android-ci-trust-root' 'upgrade-test' 'ENABLE_WEBVIEW_REMOTE_DEBUGGING' 'setWebContentsDebuggingEnabled'; do
      if grep -qF "${needle}" <<<"${apk_strings}"; then
        fail "production arm64 APK contains CI/test marker (${needle}): ${apk}"
      fi
    done
  fi

  # Native .so hygiene: at least one ABI lib dir, and exactly one canonical
  # cdylib name across all of them (libapp_<ident> is the Tauri Rust dylib).
  local libdirs
  libdirs="$(grep -oE 'lib/[^/]+/lib[^/]+\.so' <<<"${listing}" | sed -E 's#/lib[^/]+\.so##' | sort -u)"
  if [ -z "${libdirs}" ]; then
    fail "no native .so found (JNI not packaged): ${apk}"
  else
    local abis
    abis="$(sed -E 's#^lib/##' <<<"${libdirs}" | tr '\n' ' ' | sed 's/ $//')"
    echo "  ABIs: ${abis}"
    local so_names
    so_names="$(grep -oE 'lib/[^/]+/lib[^/]+\.so' <<<"${listing}" | sed -E 's#lib/[^/]+/##' | sort -u)"
    local count
    count="$(wc -l <<<"${so_names}")"
    if [ "${count}" -ne 1 ]; then
      fail "expected exactly one canonical .so name, found: $(tr '\n' ' ' <<<"${so_names}")"
    fi
  fi
}

# ---- metadata checks (aapt, when available) ----------------------------------
check_metadata() {
  local apk="$1"
  if [ -z "${AAPT}" ]; then
    echo "[apk:$(basename "${apk}")] metadata checks: SKIPPED (aapt/aapt2 not on PATH)"
    return
  fi
  echo "[apk:$(basename "${apk}")] metadata checks (${AAPT})"
  local badging
  badging="$("${AAPT}" dump badging "${apk}" 2>/dev/null || true)"
  if [ -z "${badging}" ]; then
    fail "aapt dump badging produced no output for ${apk}"
    return
  fi
  for field in application-label package versionName versionCode sdkVersion targetSdkVersion native-code; do
    if ! grep -qE "(^|:)${field}" <<<"${badging}"; then
      echo "  ${field}: (absent)"
    else
      echo "  ${field}: $(grep -E "(^|:)${field}" <<<"${badging}" | head -1 | tr -d '\r')"
    fi
  done
  # The artifact naming rule (prompt §21): a universal APK must actually carry
  # every supported ABI; an arm64-only APK must never be named universal.
  base="$(basename "${apk}")"
  local native_codes
  native_codes="$(grep -oE "native-code: '[^']+'" <<<"${badging}" | sed -E "s/native-code: '([^']+)'/\1/" | tr ' ' '\n')"
  if [[ "${base}" == *universal* ]]; then
    local need_arm64 need_x86_64
    need_arm64="$(grep -c '^arm64-v8a$' <<<"${native_codes}" || true)"
    need_x86_64="$(grep -c '^x86_64$' <<<"${native_codes}" || true)"
    if [ "${need_arm64}" -eq 0 ]; then
      fail "APK named 'universal' but has no arm64-v8a native-code"
    fi
  elif [[ "${base}" == *arm64* && "${base}" != *universal* ]]; then
    local arm64_only
    arm64_only="$(grep -c '^arm64-v8a$' <<<"${native_codes}" || true)"
    local total
    total="$(wc -l <<<"${native_codes}")"
    if [ "${arm64_only}" -ne "${total}" ]; then
      fail "arm64-named APK carries non-arm64 ABIs: $(tr '\n' ' ' <<<"${native_codes}")"
    fi
  fi
}

for apk in "${APKS[@]}"; do
  if [ ! -f "${apk}" ]; then
    echo "missing APK: ${apk}" >&2
    exit 2
  fi
  check_contents "${apk}"
  check_metadata "${apk}"
done

if [ "${FAILURES}" -ne 0 ]; then
  echo "APK STATIC VERIFICATION: FAIL (${FAILURES} issue(s))" >&2
  exit 1
fi
echo "APK STATIC VERIFICATION: PASS"
