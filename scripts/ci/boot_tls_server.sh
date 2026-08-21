#!/usr/bin/env bash
# Phase 4d — boot the self-hosted API behind a real HTTPS TLS edge for the
# upgrade-in-place / CDP tests.
#
# The product requires HTTPS for a non-loopback origin, and Phase 4c drives the
# REAL product path (Renderer -> ClientRuntime -> Tauri invoke -> Rust broker).
# Because the broker's reqwest uses the rustls default (compiled Mozilla roots),
# the ephemeral CI Caddy must present a cert issued by an ephemeral CI CA, and
# that CA is injected into the broker via the `ig.ci.tls_ca_path` system
# property (see remote::ci_tls_trust_root). On the DEVICE side, CI reads the CA
# PEM written to the well-known path below, pushes it to the device and sets the
# property + `adb reverse` to reach this host's TLS port over loopback.
#
# Fail-closed: any missing tool, failed generation, or unhealthy edge aborts.
#
# Usage:
#   scripts/ci/boot_tls_server.sh [tls_port] [compose_project]
#     tls_port        host/HTTPS port (default 18443)
#     compose_project compose project name (default ig-upgrade)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

TLS_PORT="${1:-18443}"
PROJECT="${2:-ig-upgrade}"
WORK="${RUNNER_TEMP:-/tmp}/ig_tls"

for tool in openssl docker curl; do
  command -v "${tool}" >/dev/null 2>&1 || { echo "FAIL: ${tool} not on PATH" >&2; exit 1; }
done

# ---- ephemeral CI CA + leaf cert (SAN IP:127.0.0.1, DNS:localhost) ----------
rm -rf "${WORK}"
mkdir -p "${WORK}"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "${WORK}/ca.key" -out "${WORK}/ca.pem" -days 2 \
  -subj "/CN=Interest Growth CI Root/O=Interest Growth CI" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes \
  -keyout "${WORK}/server.key" -out "${WORK}/server.csr" \
  -subj "/CN=127.0.0.1/O=Interest Growth CI" >/dev/null 2>&1
cat > "${WORK}/ext.cnf" <<EOF
subjectAltName = DNS:localhost, IP:127.0.0.1
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
basicConstraints = CA:FALSE
EOF
openssl x509 -req \
  -in "${WORK}/server.csr" -CA "${WORK}/ca.pem" -CAkey "${WORK}/ca.key" \
  -CAcreateserial -out "${WORK}/server.crt" -days 2 \
  -extfile "${WORK}/ext.cnf" >/dev/null 2>&1

cat > "${WORK}/Caddyfile" <<EOF
:443 {
	bind 0.0.0.0
	encode gzip
	tls /certs/server.crt /certs/server.key
	reverse_proxy /api/* api:8000
	reverse_proxy /api api:8000
	reverse_proxy /docs api:8000
	reverse_proxy /openapi.json api:8000
	reverse_proxy /healthz api:8000
}
EOF

echo "[tls-server] ephemeral CA written: ${WORK}/ca.pem"

# ---- boot the API (plain HTTP upstream for Caddy) ---------------------------
# Base compose declares env_file: [.env]; a clean checkout has no .env, so the
# remote-auth config MUST be written into .env (compose's env_file), or the
# server boots with PG_REMOTE_AUTH_ENABLED unset and fail-closed metadata
# checks refuse the broker's connection.
cat > .env <<'EOF'
PG_REMOTE_AUTH_ENABLED=true
PG_OWNER_BOOTSTRAP_TOKEN=ci-bootstrap-token-7a1f
APP_ENV=remote
EOF
docker compose -p "${PROJECT}" build api
docker compose -p "${PROJECT}" up -d api
API_TIMEOUT=$((SECONDS + 120))
until curl -sS -o /dev/null http://127.0.0.1:8000/api/health; do
  if [ "${SECONDS}" -gt "${API_TIMEOUT}" ]; then
    echo "FAIL: API did not become healthy" >&2
    docker compose -p "${PROJECT}" logs api >&2 || true
    exit 1
  fi
  sleep 2
done
echo "[tls-server] API healthy on 127.0.0.1:8000"

# ---- boot Caddy on the compose network, TLS on host ${TLS_PORT} -------------
NET="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$(docker compose -p "${PROJECT}" ps -q api | head -1)")"
if [ -z "${NET}" ]; then
  echo "FAIL: could not resolve API compose network" >&2
  exit 1
fi
# Remove a stale container of any prior run on the same runner cache.
docker rm -f ig-ci-caddy >/dev/null 2>&1 || true
docker run -d --rm --name ig-ci-caddy --network "${NET}" \
  -p "${TLS_PORT}:443" \
  -v "${WORK}:/certs:ro" \
  caddy:2.9-alpine caddy run --config /certs/Caddyfile >/dev/null
TLS_TIMEOUT=$((SECONDS + 120))
until curl -sk -o /dev/null "https://127.0.0.1:${TLS_PORT}/api/health"; do
  if [ "${SECONDS}" -gt "${TLS_TIMEOUT}" ]; then
    echo "FAIL: TLS edge did not become healthy" >&2
    docker logs ig-ci-caddy >&2 || true
    exit 1
  fi
  sleep 2
done
echo "[tls-server] HTTPS edge healthy on 127.0.0.1:${TLS_PORT}"
echo "CA_PEM=${WORK}/ca.pem"
echo "TLS_ORIGIN=https://127.0.0.1:${TLS_PORT}"