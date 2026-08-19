#!/usr/bin/env bash
# Android upgrade-in-place static preflight (Phase 4 / prompt §11).
#
# Proves, BEFORE any emulator boots, that an APK pair is a valid same-cert
# N -> N+1 upgrade on the x86_64 emulator. Fail-closed: any violation aborts.
#
#   * applicationId old == new
#   * cert SHA-256 old == new            (same signing identity)
#   * ABI old/new == x86_64              (must run on the emulator arch)
#   * old versionCode < new versionCode  (monotonic N -> N+1)
#   * both are RELEASE / non-debuggable  (never weaken the product for a test)
#
# Requires aapt/aapt2 and apksigner on PATH (e.g. inside the Android Docker
# toolchain, or on a host with build-tools). Missing tools are a hard FAIL so
# a missing tool can never silently become a pass.
#
# Usage:
#   scripts/ci/verify_upgrade_apk_pair.sh <old.apk> <new.apk>
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <old.apk> <new.apk>" >&2
  exit 2
fi
OLD_APK="$1"
NEW_APK="$2"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

# ---- tool availability (fail-closed) ----------------------------------------
AAPT=""
for cand in aapt aapt2; do
  if command -v "${cand}" >/dev/null 2>&1; then
    AAPT="${cand}"
    break
  fi
done
if [ -z "${AAPT}" ]; then
  echo "FAIL: aapt/aapt2 not on PATH (run inside the Android toolchain or install build-tools)" >&2
  exit 1
fi
if ! command -v apksigner >/dev/null 2>&1; then
  echo "FAIL: apksigner not on PATH (run inside the Android toolchain or install build-tools)" >&2
  exit 1
fi

FAILURES=0
fail() { echo "  FAIL: $1" >&2; FAILURES=$((FAILURES + 1)); }
pass() { echo "  PASS: $1"; }

echo "[upgrade-pair] static preflight: old=$(basename "${OLD_APK}") new=$(basename "${NEW_APK}")"

# ---- per-APK metadata --------------------------------------------------------
badging() { "${AAPT}" dump badging "$1" 2>/dev/null || true; }

OLD_PKG="$(badging "${OLD_APK}" | grep -E '^package: ' | head -1 || true)"
NEW_PKG="$(badging "${NEW_APK}" | grep -E '^package: ' | head -1 || true)"

OLD_APPID="$(sed -E "s/^package: name='([^']*)'.*/\1/" <<<"${OLD_PKG}")"
NEW_APPID="$(sed -E "s/^package: name='([^']*)'.*/\1/" <<<"${NEW_PKG}")"
OLD_VCODE="$(sed -E "s/.*versionCode='([0-9]+)'.*/\1/" <<<"${OLD_PKG}")"
NEW_VCODE="$(sed -E "s/.*versionCode='([0-9]+)'.*/\1/" <<<"${NEW_PKG}")"
OLD_VNAME="$(sed -E "s/.*versionName='([^']*)'.*/\1/" <<<"${OLD_PKG}")"
NEW_VNAME="$(sed -E "s/.*versionName='([^']*)'.*/\1/" <<<"${NEW_PKG}")"

OLD_NATIVE="$(badging "${OLD_APK}" | grep -oE "native-code: '[^']+'" | sed -E "s/native-code: '([^']+)'/\1/" | sort -u | tr '\n' ' ' | sed 's/ $//')"
NEW_NATIVE="$(badging "${NEW_APK}" | grep -oE "native-code: '[^']+'" | sed -E "s/native-code: '([^']+)'/\1/" | sort -u | tr '\n' ' ' | sed 's/ $//')"

# debuggable flag from the binary AndroidManifest (aapt dump badging has no
# reliable debuggable marker; the manifest attribute is authoritative).
# `aapt dump xmltree` prints `android:debuggable(0x0101000f)=(type 0x12)0xffffffff`
# for true; for a non-debuggable release the attribute is simply absent.
OLD_DBG=no; NEW_DBG=no
if "${AAPT}" dump xmltree "${OLD_APK}" AndroidManifest.xml 2>/dev/null | grep -q 'android:debuggable(0x0101000f).*0xffffffff'; then OLD_DBG=yes; fi
if "${AAPT}" dump xmltree "${NEW_APK}" AndroidManifest.xml 2>/dev/null | grep -q 'android:debuggable(0x0101000f).*0xffffffff'; then NEW_DBG=yes; fi

# ---- assertions --------------------------------------------------------------
echo "[upgrade-pair] old: appId=${OLD_APPID} versionName=${OLD_VNAME} versionCode=${OLD_VCODE} ABI=${OLD_NATIVE} debuggable=${OLD_DBG}"
echo "[upgrade-pair] new: appId=${NEW_APPID} versionName=${NEW_VNAME} versionCode=${NEW_VCODE} ABI=${NEW_NATIVE} debuggable=${NEW_DBG}"

if [ -z "${OLD_PKG}" ] || [ -z "${NEW_PKG}" ]; then
  fail "aapt could not read package metadata from one or both APKs"
else
  # 1. applicationId old == new
  if [ -n "${OLD_APPID}" ] && [ "${OLD_APPID}" = "${NEW_APPID}" ]; then
    pass "applicationId old == new ('${OLD_APPID}')"
  else
    fail "applicationId mismatch: old='${OLD_APPID}' new='${NEW_APPID}'"
  fi

  # 2. ABI old/new == x86_64
  for side_abi in "OLD:${OLD_NATIVE}" "NEW:${NEW_NATIVE}"; do
    side="${side_abi%%:*}"
    abi="${side_abi#*:}"
    if [ "${abi}" = "x86_64" ]; then
      pass "${side} ABI == x86_64"
    else
      fail "${side} ABI must be exactly x86_64, got: '${abi}'"
    fi
  done

  # 3. monotonic versionCode (old < new)
  if [ -n "${OLD_VCODE}" ] && [ -n "${NEW_VCODE}" ]; then
    if [ "${OLD_VCODE}" -lt "${NEW_VCODE}" ]; then
      pass "versionCode monotonic (${OLD_VCODE} < ${NEW_VCODE})"
    else
      fail "versionCode must increase: old=${OLD_VCODE} new=${NEW_VCODE}"
    fi
  else
    fail "versionCode missing: old='${OLD_VCODE}' new='${NEW_VCODE}'"
  fi

  # 4. both non-debuggable (RELEASE)
  for side_dbg in "OLD:${OLD_DBG}" "NEW:${NEW_DBG}"; do
    side="${side_dbg%%:*}"
    dbg="${side_dbg#*:}"
    if [ "${dbg}" = "no" ]; then
      pass "${side} is non-debuggable (RELEASE)"
    else
      fail "${side} must be non-debuggable (RELEASE) — do not weaken the product for a test"
    fi
  done
fi

# ---- signing identity --------------------------------------------------------
# apksigner verify --print-certs -> "Signer #1 certificate SHA-256: <hex>"
cert_sha() { apksigner verify --verbose --print-certs "$1" 2>/dev/null | grep -E 'SHA-256' | head -1 | sed -E 's/.*SHA-256: //'; }
OLD_CERT="$(cert_sha "${OLD_APK}")"
NEW_CERT="$(cert_sha "${NEW_APK}")"
if [ -z "${OLD_CERT}" ] || [ -z "${NEW_CERT}" ]; then
  fail "apksigner could not extract a signing cert (old='${OLD_CERT}' new='${NEW_CERT}')"
elif [ "${OLD_CERT}" = "${NEW_CERT}" ]; then
  pass "signing cert identical (SHA-256 ${NEW_CERT})"
else
  fail "signing cert mismatch: old=${OLD_CERT} new=${NEW_CERT} (same-cert upgrade impossible)"
fi

if [ "${FAILURES}" -ne 0 ]; then
  echo "UPGRADE APK PAIR PREFLIGHT: FAIL (${FAILURES} issue(s))" >&2
  exit 1
fi
echo "UPGRADE APK PAIR PREFLIGHT: PASS"
