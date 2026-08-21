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
QUESTION_TEXT='clean extract canonical question marker'
QUESTION_JSON="$(curl -sS -f -H "${AUTH}" -X POST "${BASE}/questions" \
  -H 'Content-Type: application/json' -d "{\"question\":\"${QUESTION_TEXT}\"}")"
QUESTION_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"${QUESTION_JSON}")"

SOURCE_FILE="${WORK}/canonical-source.txt"
printf 'clean extract canonical source marker\n' > "${SOURCE_FILE}"
SOURCE_JSON="$(curl -sS -f -X POST "${BASE}/knowledge/sources/upload" \
  -H "${AUTH}" -F 'title=clean-extract-source' -F 'source_type=document' \
  -F "file=@${SOURCE_FILE};filename=clean-extract-source.txt;type=text/plain")"
SOURCE_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"${SOURCE_JSON}")"

ARTIFACT_TITLE='clean-extract-artifact-marker'
ARTIFACT_JSON="$(curl -sS -f -X POST "${BASE}/content/cards/render" \
  -H "${AUTH}" -H 'Content-Type: application/json' \
  -d "{\"title\":\"${ARTIFACT_TITLE}\",\"points\":[\"canonical\"],\"footer\":\"restore\",\"layout\":\"three_points\",\"topic_id\":null}")"
ARTIFACT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["artifact"]["id"])' <<<"${ARTIFACT_JSON}")"

docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote exec -T api python - <<'PY'
from pg_api.backup_restore import create_backup, verify_bundle
bundle = create_backup(destination_dir="/app/backups")
assert verify_bundle(bundle_dir=str(bundle))
print(f"clean-bundle backup verified: {bundle}")
PY

BACKUP_PATH="$(docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote exec -T api sh -c 'find /app/backups -maxdepth 1 -type d -name "backup-*" -print | sort | tail -1' | tr -d '\r')"
test -n "${BACKUP_PATH}" || { echo "FAIL: clean-bundle backup path missing" >&2; exit 1; }
BACKUP_NAME="$(basename "${BACKUP_PATH}")"
HOST_BACKUP="$(mktemp -d -t ig-clean-restore-XXXXXX)"
API_CONTAINER="$(docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml ps -q api)"
docker cp "${API_CONTAINER}:${BACKUP_PATH}" "${HOST_BACKUP}/"

echo "destroying clean-bundle deployment and data volume before restore"
docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote down -v --remove-orphans
docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote up -d --build
for _ in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/health" 2>/dev/null || true)"
  [ "${code}" = 200 ] && break
  sleep 1
done
[ "${code:-000}" = 200 ]

API_CONTAINER="$(docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml ps -q api)"
docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote exec -T api mkdir -p /app/restore
docker cp "${HOST_BACKUP}/${BACKUP_NAME}" "${API_CONTAINER}:/app/restore/"
RESTORE_OUT="$(docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote exec -T api python - <<'PY'
from pg_api.backup_restore import restore_backup
import pathlib
bundle = sorted(pathlib.Path('/app/restore').glob('backup-*'))[-1]
result = restore_backup(bundle_dir=str(bundle))
print('restored=' + str(result.get('restored')))
print('integrity=' + str(result.get('integrity')))
print('fk_violations=' + str(result.get('foreign_key_violations')))
print('missing_sources=' + str(len(result.get('missing_source_files', []))))
print('missing_artifacts=' + str(len(result.get('missing_artifact_files', []))))
PY
  )"
echo "${RESTORE_OUT}"
grep -q 'restored=True' <<<"${RESTORE_OUT}"
grep -q 'integrity=ok' <<<"${RESTORE_OUT}"
grep -q 'fk_violations=0' <<<"${RESTORE_OUT}"
grep -q 'missing_sources=0' <<<"${RESTORE_OUT}"
grep -q 'missing_artifacts=0' <<<"${RESTORE_OUT}"

docker compose -p "${PROJECT}" -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote restart api
for _ in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE}/health" 2>/dev/null || true)"
  [ "${code}" = 200 ] && break
  sleep 1
done
[ "${code:-000}" = 200 ]

RESTORED_LOGIN="$(curl -sS -f -X POST "${BASE}/auth/owner/login" \
  -H 'Content-Type: application/json' \
  -d '{"owner_password":"Clean-Bundle-Owner-Password-2026!","device_name":"clean-bundle-restored","platform":"desktop","app_version":"1.0.20"}')"
RESTORED_ACCESS="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tokens"]["access_token"])' <<<"${RESTORED_LOGIN}")"
RESTORED_AUTH="Authorization: Bearer ${RESTORED_ACCESS}"
RESTORED_QUESTION="$(curl -sS -f -H "${RESTORED_AUTH}" "${BASE}/questions/${QUESTION_ID}")"
python3 - "${QUESTION_TEXT}" "${RESTORED_QUESTION}" <<'PY'
import json
import sys
expected, raw = sys.argv[1:]
actual = json.loads(raw)
assert actual['question'] == expected, actual
PY
curl -sS -f -H "${RESTORED_AUTH}" "${BASE}/knowledge/sources/${SOURCE_ID}/file" -o "${WORK}/restored-source.txt"
cmp -s "${SOURCE_FILE}" "${WORK}/restored-source.txt"
RESTORED_ARTIFACTS="$(curl -sS -f -H "${RESTORED_AUTH}" "${BASE}/artifacts")"
python3 - "${ARTIFACT_ID}" "${ARTIFACT_TITLE}" "${RESTORED_ARTIFACTS}" <<'PY'
import json
import sys
artifact_id, title, raw = sys.argv[1:]
items = json.loads(raw)['artifacts']
assert any(item.get('id') == artifact_id and item.get('title') == title for item in items), items
PY
rm -rf "${HOST_BACKUP}"
echo "SERVER BUNDLE CLEAN DEPLOYMENT: PASS"
