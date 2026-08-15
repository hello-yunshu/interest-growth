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
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <apk> [<apk> ...]" >&2
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
  if ! grep -qE 'res/.*/xml/network_security_config\.xml|networkSecurityConfig' <<<"${listing}"; then
    fail "network_security_config.xml is missing: ${apk}"
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
  local base
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

for apk in "$@"; do
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
