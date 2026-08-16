#!/usr/bin/env bash
#
# R0 §4 — packaged desktop-local startup smoke.
#
# Counter-part to the desktop-local startup BLOCKER that was fixed in R0: a
# clean default launch (no existing profile) resolves to `desktop-local` and
# MUST survive Tauri setup. The known regression caused setup to fail and the
# process to exit almost immediately. This smoke launches the PACKAGED app
# binary (not the raw sidecar) and asserts:
#
#   1. the packaged app process stays alive past the setup window (setup did
#      not crash) — this is the regression test for the startup BLOCKER;
#   2. a `psychology-growth-core` sidecar process is spawned, proving
#      desktop-local mode actually launched the local Core.
#
# It uses a scratch APP_DATA_ROOT so no real user profile is touched, and
# terminates the whole process tree on exit. GUI window rendering is not
# asserted (CI has no interactive display); process/runtime-health evidence is
# the accepted bar for this smoke and is labelled accordingly (§4).
#
# Usage:
#   verify_packaged_startup.sh <path-to-packaged-app-binary> [--win|--mac]
#
# Pass --win or --mac explicitly, or let it auto-detect from $(uname -s).

set -euo pipefail

APP_BIN="${1:?usage: verify_packaged_startup.sh <app-binary> [--win|--mac]}"
PLATFORM="${2:-}"
if [ -z "$PLATFORM" ]; then
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*|Windows*) PLATFORM="--win" ;;
    Darwin*) PLATFORM="--mac" ;;
    *) PLATFORM="--linux" ;;
  esac
fi

if [ ! -e "$APP_BIN" ]; then
  echo "FAIL: packaged app binary missing: $APP_BIN" >&2
  exit 1
fi

DATA_ROOT="$(mktemp -d -t "ig-packaged-startup-XXXXXX" 2>/dev/null || mktemp -d)"
export APP_DATA_ROOT="$DATA_ROOT"
export APP_ENV="desktop"
export DEEPSEEK_API_KEY=""
export PG_CORE_LOG_LEVEL="warning"

cleanup_tree() {
  local pid="$1"
  if [ "$PLATFORM" = "--win" ]; then
    taskkill //F //T //PID "$pid" >/dev/null 2>&1 || true
  else
    kill "$pid" >/dev/null 2>&1 || true
    pkill -f "psychology-growth-core" >/dev/null 2>&1 || true
  fi
}

launch_and_probe() {
  local pid
  "$APP_BIN" >"$DATA_ROOT/app.stdout.log" 2>"$DATA_ROOT/app.stderr.log" &
  pid=$!

  # Give the app a generous setup/first-launch window (a signed PyInstaller
  # sidecar can take a while to extract + boot).
  sleep 25

  if ! kill -0 "$pid" 2>/dev/null; then
    # The packaged app exited during/right after setup — this is exactly the
    # R0 startup BLOCKER regression.
    echo "FAIL: packaged app exited during startup (setup likely crashed)" >&2
    echo "--- app.stderr (tail) ---" >&2
    tail -60 "$DATA_ROOT/app.stderr.log" >&2 || true
    echo "--- app.stdout (tail) ---" >&2
    tail -20 "$DATA_ROOT/app.stdout.log" >&2 || true
    return 1
  fi
  echo "PASS: packaged app process alive after 25s (Tauri setup survived)"

  # desktop-local must spawn the local Core sidecar.
  if [ "$PLATFORM" = "--win" ]; then
    if tasklist 2>/dev/null | grep -qi "psychology-growth-core"; then
      echo "PASS: desktop-local sidecar process running"
    else
      echo "FAIL: desktop-local sidecar not found in tasklist" >&2
      cleanup_tree "$pid"
      return 1
    fi
  else
    if pgrep -f "psychology-growth-core" >/dev/null 2>&1; then
      echo "PASS: desktop-local sidecar process running"
    else
      echo "FAIL: desktop-local sidecar not found (pgrep psychology-growth-core)" >&2
      cleanup_tree "$pid"
      return 1
    fi
  fi

  cleanup_tree "$pid"
  return 0
}

rc=0
launch_and_probe || rc=$?
rm -rf "$DATA_ROOT"
exit "$rc"