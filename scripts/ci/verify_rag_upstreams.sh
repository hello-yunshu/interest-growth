#!/usr/bin/env bash
# Shared exact-RAG upstreams install + verify (prompt §9).
#
# Single source of truth for PR CI and the Stable exact-tag release matrix so
# the two can never drift on RAG extras again. Installs ALL four reviewed RAG
# extras (LlamaIndex / LightRAG / GraphRAG / PageIndex) and then runs the
# fail-closed upstream-API verifier. Weaker installs are forbidden.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "[verify_rag_upstreams] install all four reviewed RAG extras"
python3 -m pip install -e ".[rag-llamaindex,rag-lightrag,rag-graphrag,rag-pageindex]"

echo "[verify_rag_upstreams] verify exact RAG upstream APIs"
python3 "${ROOT}/scripts/verify_exact_rag_upstreams.py"

echo "[verify_rag_upstreams] PASS"
