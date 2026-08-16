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
#   8b. vault data (source upload + artifact render)
#   9.  refresh
#   10. logout/revoke
#   11. revoked device refresh fails
#   12+ full disaster recovery (§9.4, NOT verify-only):
#       backup -> docker cp to host -> destroy (down -v) -> clean (fresh up)
#       -> inject bundle -> restore -> migrate -> integrity verify
#       -> restart -> product smoke (login + dashboard + restored data)
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
API_PORT="${CI_DOCKER_API_PORT:-8000}"
HOST_BIND="127.0.0.1"

# docker-compose.yml declares `env_file: [.env]`, which compose refuses to
# boot without AND passes into the api container. .env is gitignored, so back
# up any developer file and write the gate's remote-auth settings into it: a
# plain command-line prefix (e.g. `PG_REMOTE_AUTH_ENABLED=true docker compose`)
# only affects interpolation and never reaches the uvicorn process, which would
# leave every auth endpoint disabled. The original file is restored in cleanup.
ENV_BACKUP="$(mktemp -t ig-env-XXXX)"
if [ -f .env ]; then
  cp .env "${ENV_BACKUP}"
else
  : > "${ENV_BACKUP}"
fi
{
  echo "PG_REMOTE_AUTH_ENABLED=true"
  echo "PG_OWNER_BOOTSTRAP_TOKEN=${BOOTSTRAP_TOKEN}"
} > .env

cleanup() {
  echo "[docker-integration] tearing down compose project ${COMPOSE_PROJECT}"
  HOST_BIND="${HOST_BIND}" docker compose -p "${COMPOSE_PROJECT}" down -v --remove-orphans 2>/dev/null || true
  if [ -s "${ENV_BACKUP}" ]; then
    mv "${ENV_BACKUP}" .env
  else
    rm -f .env "${ENV_BACKUP}"
  fi
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

# JSON helpers (avoid depending on jq). Every `http` response body is stored
# in /tmp/ig_resp.json, so parse that file — reading stdin here would be empty
# under a CI runner and silently yield no token.
json_get() {
  python3 -c "import sys,json;d=json.load(open('/tmp/ig_resp.json'));print(d$1)" 2>/dev/null || true
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
code="$(http POST /auth/owner/login -H "Content-Type: application/json" -d "{\"owner_password\":\"${OWNER_PASSWORD}\",\"device_name\":\"ci-b\",\"platform\":\"android\",\"app_version\":\"1.0.0\"}")"
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

# 8b. vault data (source upload + artifact render) so the bundle has Sources+Artifacts
step "vault data (source upload + artifact render)"
if [ -n "${ACCESS_TOKEN}" ]; then
  TMP_SRC="$(mktemp -t ig-src-XXXX.md)"
  printf '# backup round-trip\n' > "${TMP_SRC}"
  code="$(curl -sS -o /tmp/ig_resp.json -w '%{http_code}' -X POST "${BASE}/knowledge/sources/upload" \
    -H "${AUTH}" -F "title=backup-notes" -F "source_type=document" \
    -F "file=@${TMP_SRC};filename=backup-notes.md;type=text/markdown")"
  rm -f "${TMP_SRC}"
  if [ "${code}" = "200" ]; then PASS=$((PASS + 1)); else fail "source upload (got ${code})"; fi
  code="$(http POST /content/cards/render -H "${AUTH}" -H "Content-Type: application/json" \
    -d '{"title":"continuity-card","points":["backup"],"footer":"smoke","layout":"three_points","topic_id":null}')"
  if [ "${code}" = "200" ]; then PASS=$((PASS + 1)); else fail "artifact render (got ${code})"; fi
else
  fail "vault data skipped (no token)"
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

# 12+. Full disaster recovery: create data -> backup -> destroy -> clean ->
#      restore -> migrate -> integrity verify -> product smoke. This is NOT a
#      verify-only check: the data volume is destroyed and rebuilt from the
#      bundle, and the restored deployment must pass auth + data smoke tests.
step "backup bundle to /app/backups (outside the data volume)"
BACKUP_OUT="$(docker compose -p "${COMPOSE_PROJECT}" exec -T api python - <<'PY' 2>&1 || true
from pg_api.backup_restore import create_backup, verify_bundle
import pathlib
dest = pathlib.Path('/app/backups')
dest.mkdir(parents=True, exist_ok=True)
bundle = create_backup(destination_dir=str(dest))
ok = verify_bundle(bundle_dir=str(bundle))
print("BUNDLE=" + str(bundle))
print("bundle_verified_ok=" + str(bool(ok)))
PY
)"
echo "${BACKUP_OUT}"
BUNDLE_PATH="$(grep -oE 'BUNDLE=/[^ ]+' <<<"${BACKUP_OUT}" | head -1 | cut -d= -f2- || true)"
if [ -n "${BUNDLE_PATH}" ] && grep -q "bundle_verified_ok=True" <<<"${BACKUP_OUT}"; then
  PASS=$((PASS + 1))
else
  fail "backup bundle create/verify"; BUNDLE_PATH=""
fi

if [ -n "${BUNDLE_PATH}" ]; then
  BUNDLE_NAME="$(basename "${BUNDLE_PATH}")"
  HOST_BUNDLE_DIR="$(mktemp -d -t ig-bundle-XXXX)"
  APICID="$(docker compose -p "${COMPOSE_PROJECT}" ps -q api)"
  if docker cp "${APICID}:${BUNDLE_PATH}" "${HOST_BUNDLE_DIR}/"; then
    PASS=$((PASS + 1)); step "bundle staged on host (docker cp, survives destroy)"
  else
    fail "docker cp bundle to host"
  fi

  step "destroy deployment (down -v wipes the data volume)"
  HOST_BIND="${HOST_BIND}" docker compose -p "${COMPOSE_PROJECT}" down -v --remove-orphans 2>&1 || true

  step "clean deployment (fresh up with an empty volume)"
  HOST_BIND="${HOST_BIND}" \
    PG_REMOTE_AUTH_ENABLED=true \
    PG_OWNER_BOOTSTRAP_TOKEN="${BOOTSTRAP_TOKEN}" \
    docker compose -p "${COMPOSE_PROJECT}" up -d api web 2>&1 || true
  code=000
  for _ in $(seq 1 90); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/health" 2>/dev/null || true)"
    [ "${code}" = "200" ] && break
    sleep 1
  done
  if [ "${code}" = "200" ]; then PASS=$((PASS + 1)); else fail "clean deployment health (got ${code})"; fi

  step "inject bundle into fresh container"
  docker compose -p "${COMPOSE_PROJECT}" exec -T api mkdir -p /app/restore 2>&1 || true
  APICID="$(docker compose -p "${COMPOSE_PROJECT}" ps -q api)"
  if docker cp "${HOST_BUNDLE_DIR}/${BUNDLE_NAME}" "${APICID}:/app/restore/"; then
    PASS=$((PASS + 1))
  else
    fail "docker cp bundle into fresh container"
  fi

  step "restore from bundle into the fresh deployment (full, not verify-only)"
  RESTORE_OUT="$(docker compose -p "${COMPOSE_PROJECT}" exec -T api python - <<'PY' 2>&1 || true
from pg_api.backup_restore import restore_backup
import pathlib
cands = sorted(pathlib.Path('/app/restore').glob('backup-*'))
assert cands, 'no bundle found in /app/restore'
result = restore_backup(bundle_dir=str(cands[-1]))
print("restored=" + str(result.get("restored")))
print("integrity=" + str(result.get("integrity")))
print("fk_violations=" + str(result.get("foreign_key_violations")))
print("missing_sources=" + str(len(result.get("missing_source_files", []))))
print("missing_artifacts=" + str(len(result.get("missing_artifact_files", []))))
PY
)"
  echo "${RESTORE_OUT}"
  if grep -q "restored=True" <<<"${RESTORE_OUT}" \
     && grep -q "integrity=ok" <<<"${RESTORE_OUT}" \
     && grep -q "fk_violations=0" <<<"${RESTORE_OUT}" \
     && grep -q "missing_sources=0" <<<"${RESTORE_OUT}" \
     && grep -q "missing_artifacts=0" <<<"${RESTORE_OUT}"; then
    PASS=$((PASS + 1))
  else
    fail "restore round trip"
  fi

  step "migrate (schema version after restore equals current)"
  MIGRATE_OUT="$(docker compose -p "${COMPOSE_PROJECT}" exec -T api python - <<'PY' 2>&1 || true
from pg_api.db import CURRENT_SCHEMA_VERSION
from sqlalchemy import create_engine, text
e = create_engine('sqlite:////app/data/psychology_growth.db')
with e.connect() as c:
    v = c.execute(text("SELECT COALESCE(MAX(version),0) FROM schema_migrations")).scalar()
print("schema_version=" + str(v))
print("current_schema_version=" + str(CURRENT_SCHEMA_VERSION))
PY
)"
  echo "${MIGRATE_OUT}"
  MIGRATED_VERSION="$(grep -oE 'schema_version=[0-9]+' <<<"${MIGRATE_OUT}" | head -1 | cut -d= -f2 || true)"
  CURRENT_VERSION="$(grep -oE 'current_schema_version=[0-9]+' <<<"${MIGRATE_OUT}" | head -1 | cut -d= -f2 || true)"
  if [ -n "${MIGRATED_VERSION}" ] && [ "${MIGRATED_VERSION}" = "${CURRENT_VERSION}" ]; then
    PASS=$((PASS + 1)); step "schema ${MIGRATED_VERSION} == current ${CURRENT_VERSION}"
  else
    fail "migrate schema version (got ${MIGRATED_VERSION:-?} vs current ${CURRENT_VERSION:-?})"
  fi

  step "restart api so it reopens the restored DB fresh"
  docker compose -p "${COMPOSE_PROJECT}" restart api 2>&1 || true
  code=000
  for _ in $(seq 1 90); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/health" 2>/dev/null || true)"
    [ "${code}" = "200" ] && break
    sleep 1
  done
  if [ "${code}" = "200" ]; then PASS=$((PASS + 1)); else fail "post-restore health (got ${code})"; fi

  step "product smoke (owner login + dashboard + restored data)"
  code="$(http POST /auth/owner/login -H "Content-Type: application/json" -d "{\"owner_password\":\"${OWNER_PASSWORD}\",\"device_name\":\"ci-recover\",\"platform\":\"android\",\"app_version\":\"1.0.0\"}")"
  if [ "${code}" = "201" ]; then
    PASS=$((PASS + 1))
    ACCESS_TOKEN="$(json_get "['tokens']['access_token']")"
    code="$(http GET /dashboard -H "Authorization: Bearer ${ACCESS_TOKEN}")"
    if [ "${code}" = "200" ]; then PASS=$((PASS + 1)); else fail "smoke dashboard (got ${code})"; fi
    code="$(http GET /questions -H "Authorization: Bearer ${ACCESS_TOKEN}")"
    if [ "${code}" = "200" ] && grep -q "docker integration question" /tmp/ig_resp.json; then
      PASS=$((PASS + 1)); step "restored question present"
    else
      fail "restored question missing (got ${code})"
    fi
    SRCF="$(docker compose -p "${COMPOSE_PROJECT}" exec -T api sh -c 'find /app/data/source_files -name backup-notes.md 2>/dev/null | wc -l | tr -d " "' 2>/dev/null)"
    if [ "${SRCF:-0}" -ge 1 ] 2>/dev/null; then PASS=$((PASS + 1)); step "restored source file present"; else fail "restored source file missing"; fi
  else
    fail "smoke login (got ${code})"
  fi
  rm -rf "${HOST_BUNDLE_DIR}" 2>/dev/null || true
fi

echo "----------------------------------------"
echo "[docker-integration] PASS=${PASS} FAILURES=${FAILURES}"
if [ "${FAILURES}" -ne 0 ]; then
  echo "[docker-integration] DOCKER INTEGRATION: FAIL" >&2
  exit 1
fi
echo "[docker-integration] DOCKER INTEGRATION: PASS"
