#!/usr/bin/env bash
#
# Gate R1 "Web/UX closure" e2e fixture booter.
#
# Boots the Python host Core (FastAPI/uvicorn) against a throwaway SQLite DB
# and the Next.js web app (dev server) so Playwright can exercise the real
# pages in a plain Chromium browser. It is deliberately self-contained: it
# owns its own temp workspace, environment, and process lifecycle.
#
# Usage:
#   bash scripts/ci/web_e2e_server.sh start   # boot API + web, seed content (default)
#   bash scripts/ci/web_e2e_server.sh stop    # tear down whatever this script started
#   bash scripts/ci/web_e2e_server.sh status  # print PID files + readiness
#
# Overridable env:
#   E2E_WORKSPACE   temp dir (default: /tmp/interest-growth-web-e2e)
#   E2E_API_PORT    Core loopback port      (default: 8000)
#   E2E_WEB_PORT    Next dev port           (default: 3000)
#   PYTHON_BIN      python interpreter      (default: python3)
#   E2E_KEEP_WORKSPACE  set to 1 to keep the seeded DB between runs
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE="${E2E_WORKSPACE:-/tmp/interest-growth-web-e2e}"
API_PORT="${E2E_API_PORT:-8000}"
WEB_PORT="${E2E_WEB_PORT:-3000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
API_HOST="127.0.0.1"
WEB_HOST="127.0.0.1"
API_URL="http://${API_HOST}:${API_PORT}"
WEB_URL="http://${WEB_HOST}:${WEB_PORT}"
API_PID_FILE="$WORKSPACE/api.pid"
WEB_PID_FILE="$WORKSPACE/web.pid"
API_LOG="$WORKSPACE/api.log"
WEB_LOG="$WORKSPACE/web.log"

# Same package layout the pytest runner uses (see root pyproject.toml).
PYTHONPATH="$REPO_ROOT:$REPO_ROOT/apps/api:$REPO_ROOT/packages/domain:$REPO_ROOT/packages/plugin-runtime:$REPO_ROOT/packages/engine-contracts:$REPO_ROOT/packages/event-bus:$REPO_ROOT/packages/artifacts:$REPO_ROOT/packages/shared:$REPO_ROOT/packages/native-execution-core:$REPO_ROOT/adapters/deepseek"

export APP_ENV=test
export APP_DATA_ROOT="$WORKSPACE/data"
export APP_DATABASE_URL="sqlite:///$WORKSPACE/data/e2e.db"
export DEEPSEEK_API_KEY=""
export SOURCE_STORAGE_ROOT="$WORKSPACE/data/sources"
export ARTIFACT_STORAGE_ROOT="$WORKSPACE/data/artifacts"
export PG_RESOURCE_ROOT="$REPO_ROOT"
export PYTHONPATH

seed_content() {
  # Seed a second Interest Area plus some content bound to the default area so
  # the feature pages have something to render. Runs in its own process but
  # shares the same SQLite file with the running Core.
  "$PYTHON_BIN" - "$WORKSPACE" <<'PY'
import sys
from sqlalchemy import select
from pg_api.db import init_db, get_session_factory, QuestionModel, TopicModel, LearningNoteModel, SourceModel, KnowledgeBaseModel
from pg_api.domains import create_interest_area, get_default_area, bind_entity

init_db()
with get_session_factory()() as db:
    db.info["skip_area_scope"] = True
    default = get_default_area()
    area = create_interest_area(name="城市摄影", slug="city-photography",
                                description="城市、街头与光影。", domain_pack_id="general",
                                icon="camera", accent="amber")
    q = QuestionModel(question="为什么阴天更适合城市街头摄影？", state="active_topic", interest_level=4)
    db.add(q); db.flush(); bind_entity(db, "question", q.id, area_id=default.id)
    t = TopicModel(question_id=q.id, title="阴天城市街头摄影的光线", description="低反差、柔和阴影")
    db.add(t); db.flush(); bind_entity(db, "topic", t.id, area_id=default.id)
    n = LearningNoteModel(title="光线如何塑造情绪", body_markdown="阴天的柔和光让阴影更少、色彩更均匀。", note_type="learning_note")
    db.add(n); db.flush(); bind_entity(db, "learning_note", n.id, area_id=default.id)
    s = SourceModel(title="Mastering Street Photography", source_type="book", year=2019)
    db.add(s); db.flush(); bind_entity(db, "source", s.id, area_id=default.id)
    kb = KnowledgeBaseModel(name="街头摄影资料库", description="城市摄影相关原文", rag_provider="native-lexical", upstream_name="street-photo-kb")
    db.add(kb); db.flush(); bind_entity(db, "knowledge_base", kb.id, area_id=default.id)
    db.commit()
print("SEEDED area=%s question=%s topic=%s note=%s source=%s kb=%s" % (area.slug, q.id, t.id, n.id, s.id, kb.id))
PY
}

wait_ready() {
  local url="$1" name="$2" tries=60
  for _ in $(seq 1 "$tries"); do
    if curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null; then
      echo "[web-e2e] $name ready at $url"
      return 0
    fi
    sleep 1
  done
  echo "[web-e2e] ERROR: $name did not become ready at $url" >&2
  return 1
}

start() {
  if [[ "${E2E_KEEP_WORKSPACE:-0}" != "1" ]]; then
    rm -rf "$WORKSPACE"
  fi
  mkdir -p "$WORKSPACE/data" "$WORKSPACE/logs"

  # --- Host Core -----------------------------------------------------------
  if [[ -f "$API_PID_FILE" ]] && kill -0 "$(cat "$API_PID_FILE")" 2>/dev/null; then
    echo "[web-e2e] API already running (pid $(cat "$API_PID_FILE"))"
  else
    "$PYTHON_BIN" -m uvicorn pg_api.main:app --host "$API_HOST" --port "$API_PORT" --log-level warning \
      >>"$API_LOG" 2>&1 &
    echo $! > "$API_PID_FILE"
    wait_ready "$API_URL/" "Core API"
  fi

  # --- Seed content --------------------------------------------------------
  seed_content

  # --- Next.js web app -----------------------------------------------------
  if [[ -f "$WEB_PID_FILE" ]] && kill -0 "$(cat "$WEB_PID_FILE")" 2>/dev/null; then
    echo "[web-e2e] Web already running (pid $(cat "$WEB_PID_FILE"))"
  else
    (cd "$REPO_ROOT/apps/web" \
      && NEXT_PUBLIC_API_BASE="$API_URL/api" \
         npm run dev -- -p "$WEB_PORT" -H "$WEB_HOST" >>"$WEB_LOG" 2>&1) &
    echo $! > "$WEB_PID_FILE"
    wait_ready "$WEB_URL/" "Web app"
  fi

  echo "[web-e2e] READY api=$API_URL web=$WEB_URL workspace=$WORKSPACE"
  echo "[web-e2e] API pid=$(cat "$API_PID_FILE") web pid=$(cat "$WEB_PID_FILE")"
  echo "[web-e2e] logs: $API_LOG $WEB_LOG"
}

stop() {
  for f in "$WEB_PID_FILE" "$API_PID_FILE"; do
    if [[ -f "$f" ]]; then
      local pid
      pid="$(cat "$f")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "[web-e2e] stopped pid $pid"
      fi
      rm -f "$f"
    fi
  done
}

status() {
  for f in "$API_PID_FILE" "$WEB_PID_FILE"; do
    if [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null; then
      echo "$f -> $(cat "$f") (running)"
    elif [[ -f "$f" ]]; then
      echo "$f -> $(cat "$f") (stale)"
    else
      echo "$f -> (none)"
    fi
  done
}

case "${1:-start}" in
  start) start ;;
  stop)  stop ;;
  status) status ;;
  *) echo "unknown command: $1" >&2; exit 1 ;;
esac