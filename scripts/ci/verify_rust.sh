#!/usr/bin/env bash
# Unified Rust host gate (prompt §7.6 / §30).
#
# Same script used by PR CI, main artifact builds and tag releases. Runs from
# apps/desktop/src-tauri and exercises:
#   * cargo check --locked --lib
#   * cargo test --locked --lib (runtime-mode, remote broker, credential
#     store, 401 force-refresh, single-flight, identity, strict metadata,
#     method allowlist, restart recovery, logout/revoke, error taxonomy)
#
# Tauri's Linux system libraries and the frontend static export are installed
# by the caller (the web gate produces the frontendDist). A sidecar placeholder
# is created only if missing so `tauri-build`'s externalBin check passes for a
# pure source gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}/apps/desktop/src-tauri"

# tauri-build validates that every externalBin file exists. The real
# PyInstaller sidecar is built per target and git-ignored; a temporary
# placeholder satisfies the source gate. This matches docs/FINAL_RC2_AUDIT.md.
mkdir -p binaries
: > binaries/psychology-growth-core-x86_64-unknown-linux-gnu

echo "[verify_rust] cargo check --locked --lib"
cargo check --locked --lib

# Gate R2 §10.3 / R4 §10 layer-2 — Desktop A native broker harness compile
# regression. The `desktop-native-harness` feature is never in the default
# build, so a plain `cargo check` cannot catch breakage in the harness. This
# explicit feature-gated check keeps the CI cross-device job buildable.
echo "[verify_rust] cargo check --locked --bin desktop_native_harness --features desktop-native-harness"
cargo check --locked --bin desktop_native_harness --features desktop-native-harness

echo "[verify_rust] cargo test --locked --lib"
cargo test --locked --lib

echo "[verify_rust] Rust host gate: PASS"
