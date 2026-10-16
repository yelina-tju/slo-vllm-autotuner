#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${RUN_DIR:-$PROJECT_ROOT/run}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
PID_FILE="$RUN_DIR/gateway.pid"
LOG_FILE="${GATEWAY_LOG_FILE:-$LOG_DIR/gateway.log}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
STOP_BACKEND_ON_STOP="${STOP_BACKEND_ON_STOP:-true}"

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o args= | grep -q "run_gateway.py"
}

status() {
  if ! is_running; then
    echo "gateway=stopped"
    return 1
  fi
  local pid health
  pid="$(cat "$PID_FILE")"
  if curl -fsS "$GATEWAY_URL/health" >/dev/null; then
    health="ready"
  else
    health="starting_or_unhealthy"
  fi
  echo "gateway=running pid=$pid health=$health log=$LOG_FILE"
  ps -o pid,ppid,stat,etime,cmd -p "$pid"
}

start() {
  : "${MODEL_PATH:?Set MODEL_PATH to the downloaded model directory}"
  : "${TOKENIZER_PATH:?Set TOKENIZER_PATH to the tokenizer/model directory}"
  : "${VLLM_BIN:?Set VLLM_BIN to the vllm executable}"
  if is_running; then
    status
    return 0
  fi
  mkdir -p "$RUN_DIR" "$LOG_DIR"
  PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    PYTHONUNBUFFERED=1 \
    nohup "$PYTHON_BIN" "$PROJECT_ROOT/scripts/run_gateway.py" \
      --project-root "$PROJECT_ROOT" \
      --model-path "$MODEL_PATH" \
      --tokenizer-path "$TOKENIZER_PATH" \
      --vllm-bin "$VLLM_BIN" \
      >"$LOG_FILE" 2>&1 </dev/null &
  local pid
  pid=$!
  printf "%s\n" "$pid" >"$PID_FILE"
  echo "gateway=starting pid=$pid log=$LOG_FILE"
}

stop_gateway() {
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "gateway=already_stopped"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill -TERM "$pid"
  for _ in {1..30}; do
    if ! is_running; then
      rm -f "$PID_FILE"
      echo "gateway=stopped"
      return 0
    fi
    sleep 1
  done
  echo "gateway=still_stopping pid=$pid" >&2
  return 1
}

stop() {
  local gateway_status=0 backend_status=0
  stop_gateway || gateway_status=$?
  if [[ "$STOP_BACKEND_ON_STOP" == "true" ]]; then
    bash "$PROJECT_ROOT/scripts/server_ctl.sh" stop || backend_status=$?
  fi
  if (( gateway_status != 0 || backend_status != 0 )); then
    return 1
  fi
}

case "${1:-status}" in
  start) start ;;
  status) status ;;
  stop) stop ;;
  logs) tail -n "${LOG_LINES:-80}" "$LOG_FILE" ;;
  *) echo "usage: $0 {start|status|stop|logs}" >&2; exit 2 ;;
esac
