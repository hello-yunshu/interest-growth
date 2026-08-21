#!/usr/bin/env bash
# Stable Candidate gate: extract and deploy only the self-hosted server bundle.
# No path from the original checkout is used as a Compose build context.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <server-bundle.tar.gz>" >&2
  exit 2
fi

ARCHIVE="$1"
[ -f "${ARCHIVE}" ] || { echo "FAIL: bundle not found: ${ARCHIVE}" >&2; exit 1; }
WORK="$(mktemp -d -t ig-clean-bundle-XXXXXX)"
PROJECT="ig-clean-bundle-${RANDOM}"
cleanup() {
  docker compose -p "${PROJECT}" -f "${WORK}/bundle/docker-compose.yml" \
    -f "${WORK}/bundle/docker-compose.remote.yml" --env-file "${WORK}/bundle/.env.remote" \
    down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${WORK}"
}
trap cleanup EXIT

mkdir -p "${WORK}/bundle"
tar -xzf "${ARCHIVE}" -C "${WORK}/bundle" --strip-components=1
cd "${WORK}/bundle"
[ -s VERSION ] && [ -s SOURCE_SHA ]
[ -f docker-compose.yml ] && [ -f docker-compose.remote.yml ] && [ -f .env.remote.example ]
[ -f apps/api/Dockerfile ] && [ -f apps/web/Dockerfile ]
cp .env.remote.example .env.remote
sed -i.bak 's/^PG_OWNER_BOOTSTRAP_TOKEN=.*/PG_OWNER_BOOTSTRAP_TOKEN=clean-bundle-bootstrap-token/' .env.remote
rm -f .env.remote.bak

docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote up -d --build
BASE="http://127.0.0.1:8000/api"
for _ in $(seq 1 90); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/health" 2>/dev/null || true)"
  [ "${code}" = 200 ] && break
  sleep 1
done
[ "${code:-000}" = 200 ] || { docker compose -p "${PROJECT}" logs >&2 || true; exit 1; }
curl -sS -f "${BASE}/system/capabilities" >/dev/null
nobody_code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/dashboard")"
[ "${nobody_code}" = 401 ]

curl -sS -f -X POST "${BASE}/auth/owner/bootstrap" \
  -H 'Content-Type: application/json' \
  -H 'X-PG-Owner-Bootstrap-Token: clean-bundle-bootstrap-token' \
  -d '{"owner_password":"Clean-Bundle-Owner-Password-2026!"}' >/dev/null
LOGIN="$(curl -sS -f -X POST "${BASE}/auth/owner/login" \
  -H 'Content-Type: application/json' \
  -d '{"owner_password":"Clean-Bundle-Owner-Password-2026!","device_name":"clean-bundle","platform":"desktop","app_version":"1.0.20"}')"
ACCESS="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tokens"]["access_token"])' <<<"${LOGIN}")"
AUTH="Authorization: Bearer ${ACCESS}"
curl -sS -f -H "${AUTH}" -X POST "${BASE}/questions" \
  -H 'Content-Type: application/json' -d '{"question":"clean extract canonical data"}' >/dev/null

docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote exec -T api python - <<'PY'
from pg_api.backup_restore import create_backup, verify_bundle
bundle = create_backup(destination_dir="/app/backups")
assert verify_bundle(bundle_dir=str(bundle))
print(f"clean-bundle backup verified: {bundle}")
PY

docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote restart api
for _ in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/health" 2>/dev/null || true)"
  [ "${code}" = 200 ] && break
  sleep 1
done
[ "${code:-000}" = 200 ]
echo "SERVER BUNDLE CLEAN DEPLOYMENT: PASS"
