#!/usr/bin/env bash
# Gate R2 §10.3 / R4 §10 layer-2 — Android B slices for the true Native
# cross-device gate.
#
# Runs on the HOST of the ubuntu runner, invoked as a single line from the
# reactivecircus/android-emulator-runner `script:` (which has the emulator
# booted and `adb` on PATH). It drives the REAL Android native broker
# (emulator_e2e.rs, compiled into the x86_64 DEBUG APK) through TWO app
# launches against the SAME Docker server the Desktop A harness used, plus
# Desktop A's revoke phase in between:
#
#   B slice 1 (enroll + keepDevice):  Android B login/enroll; EXACT A->B
#       cross-read of Desktop A's marker (expectAQuestion); B creates its own
#       marker (createMarker); keeps the device ACTIVE (keepDevice, no
#       self-revoke) so A's later revoke is what denies B.
#   Desktop A b_revoke (host binary): B->A exact cross-read (expectBQuestion);
#       device list has A+B; A revokes B; A unaffected; server records B
#       revoked.
#   B slice 2 (expectRevoked):        B's next authenticated mutation is
#       DENIED (A revoked it — no re-login); B re-enrolls (recovery) and
#       re-reads A's marker (expectAQuestion after recovery).
#
# The desktop_native_harness binary is built earlier in the job
# (desktop-native-harness feature) and is NOT a raw HTTP client — it is the
# real `RemoteBroker` running as Desktop A. Combined with the emulator's real
# android-remote broker, this is the true Native cross-device evidence
# (prompt §10 layer-2): never two raw HTTP clients.
#
# Required env:
#   IG_HARNESS_BIN   absolute path to the built desktop_native_harness binary
#   IG_B_REVOKE_CFG  absolute path to Desktop A `b_revoke` HarnessConfig JSON
#   IG_B_SLICE1_CFG  absolute path to Android B slice-1 EmulatorE2EConfig JSON
#   IG_B_SLICE2_CFG  absolute path to Android B slice-2 EmulatorE2EConfig JSON
#   IG_APK           absolute path to the x86_64 DEBUG APK (has emulator_e2e)
#   IG_PKG           Android package name (debug APK: app.psychologygrowth.desktop)
set -euo pipefail

for var in IG_HARNESS_BIN IG_B_REVOKE_CFG IG_B_SLICE1_CFG IG_B_SLICE2_CFG IG_APK IG_PKG; do
  if [ -z "${!var:-}" ]; then echo "missing required env ${var}" >&2; exit 2; fi
done

# Push a JSON config into the app-private files/ dir (the emulator_e2e trigger
# contract). Reuses a fixed on-device temp path then `run-as` copies it.
push_cfg() { # $1 = host file, $2 = device file name
  adb push "$1" /data/local/tmp/ig_aux.json >/dev/null
  adb shell run-as "${IG_PKG}" mkdir -p files
  adb shell run-as "${IG_PKG}" cp /data/local/tmp/ig_aux.json "files/$2"
  adb shell run-as "${IG_PKG}" chmod 600 "files/$2"
}

# Poll files/ig_e2e_result.json for a terminal PASS/FAIL; exits the script on
# FAIL/timeout. $1 = human-readable slice label.
poll_result() { # $1 = label
  local label="$1" i r
  for i in $(seq 1 90); do
    r="$(adb shell run-as "${IG_PKG}" cat files/ig_e2e_result.json 2>/dev/null || true)"
    if printf '%s' "$r" | grep -q '"result": "PASS"'; then
      echo "[ig-cross] ${label}: PASS"
      printf '%s\n' "$r"
      return 0
    fi
    if printf '%s' "$r" | grep -q '"result": "FAIL"'; then
      echo "[ig-cross] ${label}: FAIL" >&2
      printf '%s\n' "$r" >&2
      exit 1
    fi
    sleep 2
  done
  echo "[ig-cross] ${label}: did not complete in time" >&2
  echo "--- app pid ---"; adb shell pidof "${IG_PKG}" || echo "process NOT running"
  echo "--- app-private files dir ---"; adb shell run-as "${IG_PKG}" ls -la files 2>&1 || true
  echo "--- crash logcat ---"; adb logcat -d -b crash 2>/dev/null | tail -40 || true
  exit 1
}

echo "=== [ig-cross] install APK + adb reverse (emulator 18080 -> host 8000) ==="
adb install "${IG_APK}"
adb reverse tcp:18080 tcp:8000

echo "=== [ig-cross] Android B slice 1 (enroll + A->B exact read + keepDevice) ==="
push_cfg "${IG_B_SLICE1_CFG}" ig_e2e_config.json
adb shell am start -n "${IG_PKG}/.MainActivity"
sleep 8
poll_result "B slice 1 (A->B exact read)"

echo "=== [ig-cross] Desktop A b_revoke (native desktop-remote broker, same server) ==="
"${IG_HARNESS_BIN}" --config "${IG_B_REVOKE_CFG}"
echo "[ig-cross] Desktop A b_revoke: PASS"

echo "=== [ig-cross] Android B slice 2 (expectRevoked + recovery cross-read) ==="
push_cfg "${IG_B_SLICE2_CFG}" ig_e2e_config.json
adb shell am force-stop "${IG_PKG}"
adb shell am start -n "${IG_PKG}/.MainActivity"
sleep 8
poll_result "B slice 2 (revoke-isolation + recovery)"

echo "=== [ig-cross] Native cross-device gate (layer 2): ALL SLICES PASS ==="
