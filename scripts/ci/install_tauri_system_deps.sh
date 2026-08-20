#!/usr/bin/env bash
# Install the Linux system libraries needed to `cargo check`/`cargo test` the
# Tauri desktop crate (used by the Rust source gate in ci.yml and by the
# release workflow's native harness jobs).
#
# Robustness: the default GitHub runner apt mirror (azure.archive.ubuntu.com)
# is intermittently flaky and can hang `apt-get update` for the whole job
# timeout. This helper pins the canonical archive.ubuntu.com mirror and runs
# `apt-get update` with a bounded timeout plus retries, so a transient mirror
# stall fails fast and retries instead of hanging until the job is cancelled.
# `apt-get install` itself is also bounded so the step never deadlocks.
set -euo pipefail

# 1. Pin the canonical Ubuntu mirror (bypass the flaky azure mirror). The
#    runner sources live in /etc/apt/sources.list.d/*.sources on modern images;
#    tolerate either layout. Never fail on a missing/unchanged file.
sudo sed -i 's|http://azure\.archive\.ubuntu\.com/ubuntu|http://archive.ubuntu.com/ubuntu|g' \
  /etc/apt/sources.list.d/*.sources 2>/dev/null || true
sudo sed -i 's|http://azure\.archive\.ubuntu\.com/ubuntu|http://archive.ubuntu.com/ubuntu|g' \
  /etc/apt/sources.list 2>/dev/null || true

# 2. Update with a bounded timeout and retries. `timeout` makes a hung mirror
#    return a real error instead of blocking the job; the loop retries it.
for attempt in 1 2 3; do
  if timeout 300 sudo apt-get update; then
    break
  fi
  if [ "${attempt}" -eq 3 ]; then
    echo "[system-deps] apt-get update failed after 3 attempts" >&2
    exit 1
  fi
  echo "[system-deps] apt-get update attempt ${attempt} failed; retrying..."
  sleep 5
done

# 3. Install the Tauri Linux build prerequisites (bounded, single retry).
if ! timeout 420 sudo apt-get install -y libwebkit2gtk-4.1-dev build-essential curl wget file \
  libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev; then
  echo "[system-deps] apt-get install failed; retrying once..." >&2
  timeout 420 sudo apt-get install -y libwebkit2gtk-4.1-dev build-essential curl wget file \
    libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
fi

echo "[system-deps] Tauri Linux system dependencies installed"
