#!/usr/bin/env bash
# Docker remote-server integration gate (prompt §7.7 / §30).
#
# Same script used by PR CI, main artifact builds and tag releases. Builds the
# CURRENT commit's API/Web images from a clean checkout, boots them with a
# CLEAN data volume and exercises the remote auth + data contract over real
# HTTP:
#
#   1.  API/Web boot
#   2.  /api/health
#   3.  /api/system/capabilities
#   4.  unauthenticated protected route -> 401
#   5.  owner bootstrap
#   6.  login
#   7.  authenticated GET
#   8.  mutation
#   9.  refresh
#   10. logout/revoke
#   11. revoked device refresh fails
#   12. backup
#   13. restore
#   14. restored data/identity behavior matches the contract
#
# All images are built from the current commit; nothing is pulled from a
# registry or a developer machine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

# Remote auth must be ON for this gate. Never disable it here.
BOOTSTRAP_TOKEN="ci-bootstrap-token-7a1f"
OWNER_PASSWORD="Ci-Owner-Password-2026!"
COMPOSE_PROJECT="ig-ci-$$"
API_PORT="${CI_DOCKER_API_PORT:-18080}"
HOST_BIND="127.0.0.1"

cleanup() {
  echo "[docker-integration] tearing down compose project ${COMPOSE_PROJECT}"
  HOST_BIND="${HOST_BIND}" docker compose -p "${COMPOSE_PROJECT}" down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

echo "[docker-integration] building API/Web images from current commit"
HOST_BIND="${HOST_BIND}" docker compose -p "${COMPOSE_PROJECT}" build api web

echo "[docker-integration] booting API/Web with clean data volume"
HOST_BIND="${HOST_BIND}" \
PG_REMOTE_AUTH_ENABLED=true \
PG_OWNER_BOOTSTRAP_TOKEN="${BOOTSTRAP_TOKEN}" \
docker compose -p "${COMPOSE_PROJECT}" up -d api web

BASE="http://${HOST_BIND}:${API_PORT}/api"
PASS=0
FAILURES=0
step() { echo "  - $1"; }

# JSON helpers (avoid depending on jq)
json_get() {
  python3 -c "import sys,json;d=json.load(sys.stdin);print(d$1)" 2>/dev/null || true
}

http() { # http <METHOD> <path> [curl-args...]
  local method="$1" path="$2"; shift 2
  curl -sS -o /tmp/ig_resp.json -w '%{http_code}' -X "${method}" "${BASE}${path}" "$@"
}

fail() { echo "  FAIL: $1" >&2; FAILURES=$((FAILURES + 1)); }

# 1-2. boot + health (retry up to 60s)
step "waiting for /api/health"
code=000
for _ in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/health" 2>/dev/null || true)"
  [ "${code}" = "200" ] && break
  sleep 1
done
if [ "${code}" = "200" ]; then PASS=$((PASS + 1)); step "health 200"; else fail "health not 200 (got ${code})"; fi

# 3. capabilities
step "capabilities"
code="$(http GET /system/capabilities)"
if [ "${code}" = "200" ] && grep -q "device" /tmp/ig_resp.json; then PASS=$((PASS + 1)); else fail "capabilities (got ${code})"; fi

# 4. unauthenticated protected route -> 401
step "unauthenticated protected route -> 401"
code="$(http GET /dashboard)"
if [ "${code}" = "401" ]; then PASS=$((PASS + 1)); else fail "protected route not 401 (got ${code})"; fi

# 5. owner bootstrap
step "owner bootstrap"
code="$(http POST /auth/owner/bootstrap -H "Content-Type: application/json" -H "X-PG-Owner-Bootstrap-Token: ${BOOTSTRAP_TOKEN}" -d "{\"owner_password\":\"${OWNER_PASSWORD}\"}")"
if [ "${code}" = "201" ]; then PASS=$((PASS + 1)); else fail "bootstrap (got ${code})"; fi

# 6. login
step "owner login"
code="$(http POST /auth/owner/login -H "Content-Type: application/json" -d "{\"owner_password\":\"${OWNER_PASSWORD}\",\"device_name\":\"ci-b\",\"platform\":\"android\",\"app_version\":\"0.7.0\"}")"
if [ "${code}" = "201" ]; then
  PASS=$((PASS + 1))
  DEVICE_ID="$(json_get "['device']['id']")"
  ACCESS_TOKEN="$(json_get "['tokens']['access_token']")"
  REFRESH_TOKEN="$(json_get "['tokens']['refresh_token']")"
  AUTH="Authorization: Bearer ${ACCESS_TOKEN}"
else
  fail "login (got ${code})"
  DEVICE_ID=""; ACCESS_TOKEN=""; REFRESH_TOKEN=""
fi

# 7. authenticated GET
step "authenticated GET /dashboard"
if [ -n "${ACCESS_TOKEN}" ]; then
  code="$(http GET /dashboard -H "${AUTH}")"
  if [ "${code}" = "200" ]; then PASS=$((PASS + 1)); else fail "auth GET (got ${code})"; fi
fi

# 8. mutation (create a question)
step "mutation POST /questions"
if [ -n "${ACCESS_TOKEN}" ]; then
  code="$(http POST /questions -H "${AUTH}" -H "Content-Type: application/json" -d '{"question":"docker integration question"}')"
  if [ "${code}" = "200" ] || [ "${code}" = "201" ]; then PASS=$((PASS + 1)); else fail "mutation (got ${code})"; fi
fi

# 9. refresh
step "refresh (rotates renewal credential)"
if [ -n "${REFRESH_TOKEN}" ] && [ -n "${DEVICE_ID}" ]; then
  code="$(http POST /auth/device/refresh -H "Content-Type: application/json" -d "{\"device_id\":\"${DEVICE_ID}\",\"refresh_token\":\"${REFRESH_TOKEN}\"}")"
  if [ "${code}" = "200" ]; then
    PASS=$((PASS + 1))
    NEW_REFRESH="$(json_get "['tokens']['refresh_token']")"
  else
    fail "refresh (got ${code})"; NEW_REFRESH=""
  fi
  # old refresh must be consumed
  code2="$(http POST /auth/device/refresh -H "Content-Type: application/json" -d "{\"device_id\":\"${DEVICE_ID}\",\"refresh_token\":\"${REFRESH_TOKEN}\"}")"
  if [ "${code2}" = "401" ]; then PASS=$((PASS + 1)); else fail "reused refresh not rejected (got ${code2})"; fi
fi

# 10-11. logout/revoke + revoked refresh fails
step "revoke device"
if [ -n "${DEVICE_ID}" ] && [ -n "${ACCESS_TOKEN}" ]; then
  code="$(http POST /auth/device/revoke -H "${AUTH}" -H "Content-Type: application/json" -d "{\"device_id\":\"${DEVICE_ID}\",\"owner_password\":\"${OWNER_PASSWORD}\"}")"
  if [ "${code}" = "200" ]; then PASS=$((PASS + 1)); else fail "revoke (got ${code})"; fi
  if [ -n "${NEW_REFRESH:-}" ]; then
    code2="$(http POST /auth/device/refresh -H "Content-Type: application/json" -d "{\"device_id\":\"${DEVICE_ID}\",\"refresh_token\":\"${NEW_REFRESH}\"}")"
    if [ "${code2}" = "401" ]; then PASS=$((PASS + 1)); else fail "revoked refresh not rejected (got ${code2})"; fi
  fi
fi

# 12-14. backup / restore / identity preserved
step "backup + restore (engine-level, in-container)"
BACKUP_OUT="$(docker compose -p "${COMPOSE_PROJECT}" exec -T api python - <<'PY' 2>&1 || true
from pg_api.backup_restore import create_backup, verify_bundle, restore_backup
import tempfile, pathlib
base = tempfile.mkdtemp(prefix="ig-ci-backup-")
bundle = create_backup(destination_dir=str(pathlib.Path(base) / "backups"))
ok = verify_bundle(bundle_dir=str(bundle))
print("bundle_verified=" + str(ok))
result = restore_backup(bundle_dir=str(bundle))
print("restored=" + str(result.get("restored")))
PY
)"
echo "${BACKUP_OUT}"
if grep -q "bundle_verified=True" <<<"${BACKUP_OUT}" && grep -q "restored=True" <<<"${BACKUP_OUT}"; then
  PASS=$((PASS + 1))
else
  fail "backup/restore round trip"
fi

# identity preserved across restart is covered by the Host test suite
# (tests/security/test_backup_restore.py::test_restore_preserves_server_identity);
# the container round trip above proves the bundle path on the real image.

echo "----------------------------------------"
echo "[docker-integration] PASS=${PASS} FAILURES=${FAILURES}"
if [ "${FAILURES}" -ne 0 ]; then
  echo "[docker-integration] DOCKER INTEGRATION: FAIL" >&2
  exit 1
fi
echo "[docker-integration] DOCKER INTEGRATION: PASS"
