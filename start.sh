#!/usr/bin/env bash
# Start the API and the desk. If either is already running, stop it and start it again.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

API_HOST=127.0.0.1
API_PORT=8014
WEB_HOST=127.0.0.1
WEB_PORT=3000
RUN_DIR="$ROOT/var/run"
LOG_DIR="$ROOT/var/log"
mkdir -p "$RUN_DIR" "$LOG_DIR"

listener_pids() {
  local port="$1"
  ss -ltnp "sport = :${port}" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u
}

stop_tree() {
  local pid="$1"
  local child
  if [[ "$pid" -eq $$ || "$pid" -eq ${PPID:-0} ]]; then
    return
  fi
  for child in $(ps -o pid= --ppid "$pid" 2>/dev/null | tr -d ' '); do
    [[ -n "$child" ]] && stop_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

# Walk from the process listening on the port up through uvicorn / next / npm, then stop that tree.
stop_recorded() {
  local file="$1"
  local label="$2"
  [[ -f "$file" ]] || return 0
  local pid
  pid="$(tr -d '[:space:]' <"$file")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "Stopping recorded ${label} (pid ${pid})."
    kill -- "-${pid}" 2>/dev/null || stop_tree "$pid"
  fi
  rm -f "$file"
}

stop_port() {
  local port="$1"
  local label="$2"
  local pid parent args top found=0
  for pid in $(listener_pids "$port"); do
    found=1
    top="$pid"
    while true; do
      parent="$(ps -o ppid= -p "$top" 2>/dev/null | tr -d ' ')"
      [[ -z "$parent" || "$parent" == "1" || "$parent" == "$$" ]] && break
      args="$(ps -o args= -p "$parent" 2>/dev/null || true)"
      case "$args" in
        *uvicorn\ app.main*|*next\ dev*|*next-server*|*npm\ run\ dev*|*"sh -c next"*|*"sh -c \"next"*)
          top="$parent"
          ;;
        *)
          break
          ;;
      esac
    done
    echo "Stopping ${label} (pid ${top}) on port ${port}."
    stop_tree "$top"
  done
  if [[ "$found" -eq 0 ]]; then
    echo "Starting ${label} on port ${port}."
  else
    echo "Restarting ${label} on port ${port}."
  fi
  local wait
  for wait in 1 2 3 4 5 6 7 8 9 10; do
    [[ -z "$(listener_pids "$port")" ]] && return 0
    sleep 0.3
  done
  echo "${label} is still listening on port ${port}." >&2
  exit 1
}

database_port() {
  python3 - <<'PY'
from pathlib import Path
from urllib.parse import urlparse

url = ""
env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
if not url:
    url = "postgresql+psycopg://imm:imm@localhost:5432/imm"
if "://" in url:
    url = "postgresql://" + url.split("://", 1)[1]
parsed = urlparse(url)
print(parsed.port or 5432)
PY
}

ensure_database() {
  local port="$1"
  if ss -ltn | grep -q ":${port} "; then
    echo "Postgres is already accepting connections on port ${port}."
    return
  fi
  local container=""
  case "$port" in
    5432) container="stock_market_analysis-postgres-1" ;;
    54329) container="imm-m0-test-pg" ;;
  esac
  if [[ -z "$container" ]]; then
    echo "Nothing is listening on Postgres port ${port}. Start that database, then run this script again." >&2
    exit 1
  fi
  if ! docker start "$container" >/dev/null; then
    echo "Could not start Postgres container ${container} for port ${port}." >&2
    exit 1
  fi
  echo "Started Postgres container ${container}."
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if docker exec "$container" pg_isready -U imm -d imm >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "Postgres container ${container} did not become ready." >&2
  exit 1
}

wait_http() {
  local url="$1"
  local label="$2"
  local attempt
  for attempt in $(seq 1 40); do
    if curl -sf -o /dev/null --max-time 2 "$url"; then
      echo "${label} is up: ${url}"
      return 0
    fi
    sleep 0.5
  done
  echo "${label} did not answer at ${url}. See ${LOG_DIR}." >&2
  return 1
}

DB_PORT="$(database_port)"
ensure_database "$DB_PORT"

if [[ ! -x "$ROOT/.venv/bin/uvicorn" ]]; then
  echo "Missing $ROOT/.venv/bin/uvicorn. Create the virtualenv and install apps/api first." >&2
  exit 1
fi

set -m
stop_recorded "$RUN_DIR/api.pid" "API"
stop_port "$API_PORT" "API"
"$ROOT/.venv/bin/uvicorn" app.main:app --host "$API_HOST" --port "$API_PORT" \
  >"$LOG_DIR/api.log" 2>&1 < /dev/null &
echo $! >"$RUN_DIR/api.pid"

export API_URL="http://${API_HOST}:${API_PORT}"
stop_recorded "$RUN_DIR/web.pid" "desk"
stop_port "$WEB_PORT" "desk"
(
  cd "$ROOT/apps/web"
  npm run dev -- --hostname "$WEB_HOST" --port "$WEB_PORT"
) >"$LOG_DIR/web.log" 2>&1 < /dev/null &
echo $! >"$RUN_DIR/web.pid"

wait_http "http://${API_HOST}:${API_PORT}/health" "API"
wait_http "http://${WEB_HOST}:${WEB_PORT}/" "Desk"

echo "Logs: ${LOG_DIR}/api.log and ${LOG_DIR}/web.log"
echo "Desk: http://${WEB_HOST}:${WEB_PORT}"
echo "API:  http://${API_HOST}:${API_PORT}/health"
