#!/usr/bin/env bash
# Unified repository-integrity gate (prompt §7.1 / §30).
#
# Every clean checkout must pass this before any build is trusted. It is the
# SAME script used by PR CI, main artifact builds and tag releases, so there
# is never a second, laxer verification path.
#
# Fails closed on:
#   * tracked symlink / path-escape / credential-file / Java-keystore hygiene
#   * SOURCE_MANIFEST drift (manifest scope == git tracked scope, no Android
#     exclusion) — BLOCKER-1 / ADR 0008
#   * Android FileProvider surface widening beyond cache/export/ + files/share/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

PY=python3

echo "[verify_repo] auditing public repository (symlink/path/credential/FileProvider/manifest scope)"
"${PY}" scripts/audit_public_repo.py

echo "[verify_repo] checking SOURCE_MANIFEST against tracked scope"
"${PY}" scripts/generate_source_manifest.py --check

echo "[verify_repo] repository integrity: PASS"
