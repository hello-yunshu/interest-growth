#!/usr/bin/env bash
# Unified Web / ClientRuntime gate (prompt §7.5 / §30).
#
# Same script used by PR CI, main artifact builds and tag releases:
#   * npm ci
#   * lint (zero warnings)
#   * ALL ClientRuntime tests, including the Android runtime suite
#   * static production build
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}/apps/web"

echo "[verify_web] npm ci"
npm ci

echo "[verify_web] npm run lint"
npm run lint

echo "[verify_web] ClientRuntime tests (contract + runtime modes + connect-controller + Android)"
node --test lib/runtime/test/*.test.mjs

echo "[verify_web] static production build"
NEXT_PUBLIC_API_BASE="${NEXT_PUBLIC_API_BASE:-http://localhost:8000/api}" npm run build

echo "[verify_web] Web / ClientRuntime gate: PASS"
