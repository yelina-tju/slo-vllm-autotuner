#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${RUN_DIR:-$PROJECT_ROOT/run}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
PID_FILE="$RUN_DIR/server.pid"
LOG_FILE="${LOG_FILE:-$LOG_DIR/server.log}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o args= | grep -q "vllm serve"
}

status() {
  if ! is_running; then
    echo "server=stopped"
    return 1
  fi
  local pid health
  pid="$(cat "$PID_FILE")"
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    health="ready"
  else
    health="starting_or_unhealthy"
  fi
  echo "server=running pid=$pid health=$health log=$LOG_FILE"
  ps -o pid,ppid,stat,etime,cmd -p "$pid"
}

start() {
  : "${MODEL_PATH:?Set MODEL_PATH to the downloaded model directory}"
  if is_running; then
    status
    return 0
  fi
  mkdir -p "$RUN_DIR" "$LOG_DIR"
  nohup bash "$PROJECT_ROOT/scripts/serve.sh" \
    >"$LOG_FILE" 2>&1 </dev/null &
  local pid
  pid=$!
  printf "%s\n" "$pid" >"$PID_FILE"
  echo "server=starting pid=$pid log=$LOG_FILE"
}

stop() {
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "server=already_stopped"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill -INT "$pid"
  for _ in {1..30}; do
    if ! is_running; then
      rm -f "$PID_FILE"
      echo "server=stopped"
      return 0
    fi
    sleep 1
  done
  echo "server=still_stopping pid=$pid" >&2
  return 1
}

case "${1:-status}" in
  start) start ;;
  status) status ;;
  stop) stop ;;
  logs) tail -n "${LOG_LINES:-50}" "$LOG_FILE" ;;
  *) echo "usage: $0 {start|status|stop|logs}" >&2; exit 2 ;;
esac
