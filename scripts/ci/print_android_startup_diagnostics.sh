#!/usr/bin/env bash
# Print throw-away Android startup diagnostics after a CI-only app launch
# failure. The emulator action executes each line of its `script:` input as a
# separate shell command, so structured shell control flow belongs here rather
# than inline in the workflow.
set -u

APP_PACKAGE="${1:-app.psychologygrowth.desktop}"
FILES_DIR="/data/user/0/${APP_PACKAGE}/files"
LEGACY_FILES_DIR="/data/data/${APP_PACKAGE}/files"

echo "FAIL: ${APP_PACKAGE} did not remain running after launch" >&2
echo "--- ${APP_PACKAGE} crash buffer ---" >&2
adb logcat -d -b crash 2>/dev/null | tail -120 >&2 || true
echo "--- ${APP_PACKAGE} activity/process diagnostics ---" >&2
adb shell dumpsys activity activities 2>/dev/null \
  | grep -iE 'ResumedActivity|mResumedActivity|psychologygrowth' \
  | tail -40 >&2 || true
adb shell pidof "${APP_PACKAGE}" >&2 || true
echo "--- ${APP_PACKAGE} private startup diagnostics ---" >&2
for marker in \
  ci-old-java-oncreate.txt \
  ci-old-java-before-keyring.txt \
  ci-old-java-after-keyring.txt \
  ci-old-java-after-super.txt \
  ci-old-startup-entered.txt \
  ci-old-before-builder-run.txt \
  ci-old-setup-entered.txt \
  ci-old-before-trust-root.txt \
  ci-old-before-keystore-store.txt \
  ci-old-before-state-manage.txt \
  ci-old-startup-panic.txt \
  ci-old-startup-error.txt; do
  echo "marker=${marker}" >&2
  adb shell cat "${FILES_DIR}/${marker}" 2>/dev/null >&2 || true
  adb shell cat "${LEGACY_FILES_DIR}/${marker}" 2>/dev/null >&2 || true
done
