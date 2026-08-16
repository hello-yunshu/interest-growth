#!/usr/bin/env bash
# Run a command inside the Interest Growth Android build container.
#
# The image (docker/android/Dockerfile) already carries the full toolchain
# (JDK 17, Android SDK+NDK, Rust android targets, cargo-ndk, Node, Tauri CLI)
# so nothing is installed on the host. The repo is mounted at /work.
#
# Usage:
#   scripts/android-docker.sh <cmd...>
#   scripts/android-docker.sh bash
#   scripts/android-docker.sh tauri android init
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Release signing keystore lives OUTSIDE the repo (Gate F §8.2). The container
# expects it at /keystore (see gen/android/app/build.gradle.kts +
# keystore.properties). Only mount when the directory exists.
KEYSTORE_DIR="${PG_ANDROID_KEYSTORE_DIR:-${HOME}/Documents/GitHub/interest-growth-keystore}"
KEYSTORE_MOUNT=()
if [ -d "${KEYSTORE_DIR}" ]; then
  KEYSTORE_MOUNT=(-v "${KEYSTORE_DIR}:/keystore:ro")
fi

docker run --rm \
  --platform linux/amd64 \
  -v "${REPO_ROOT}":/work \
  -v ig-gradle-cache:/root/.gradle \
  -v ig-cargo-home:/usr/local/cargo \
  "${KEYSTORE_MOUNT[@]}" \
  -w /work \
  -e ANDROID_HOME=/opt/android-sdk \
  -e ANDROID_NDK_HOME=/opt/android-sdk/ndk/27.1.12297006 \
  interest-growth-android "$@"