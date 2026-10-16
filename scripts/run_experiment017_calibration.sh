#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-python}"
VLLM="${VLLM_BIN:-vllm}"
MODEL="${MODEL_PATH:?Set MODEL_PATH to a local model directory}"
MODEL_NAME=qwen2.5-7b
LOCK="$ROOT/run/experiment017-calibration.lock"
SERVER_RUN_DIR="$ROOT/run/experiment017-server"
SERVER_LOG="$ROOT/logs/experiment017-7b-server.log"
RESULT_DIR="$ROOT/results/generalization_7b_low_load"

cd "$ROOT"
mkdir -p run logs "$RESULT_DIR"
exec 9>"$LOCK"
flock -n 9 || { echo "experiment 017 calibration is already running"; exit 1; }

test -s "$MODEL/config.json"
compgen -G "$MODEL/*.safetensors" >/dev/null

export PYTHONPATH=src
export MODEL_PATH="$MODEL"
export SERVED_MODEL_NAME="$MODEL_NAME"
export VLLM_BIN="$VLLM"
export ENABLE_PREFIX_CACHING=false
export ENABLE_CHUNKED_PREFILL=true
export MAX_NUM_BATCHED_TOKENS=2048
export MAX_NUM_SEQS=256
export SCHEDULING_POLICY=fcfs
export RUN_DIR="$SERVER_RUN_DIR"
export LOG_FILE="$SERVER_LOG"

cleanup() {
  bash scripts/server_ctl.sh stop || true
}
trap cleanup EXIT

bash scripts/server_ctl.sh start
ready=false
for _ in {1..180}; do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
    ready=true
    break
  fi
  if ! bash scripts/server_ctl.sh status >/dev/null 2>&1; then
    echo "7B server exited before becoming healthy" >&2
    tail -n 100 "$SERVER_LOG" >&2
    exit 1
  fi
  sleep 2
done
if [[ "$ready" != true ]]; then
  echo "7B server did not become healthy within 360 seconds" >&2
  tail -n 100 "$SERVER_LOG" >&2
  exit 1
fi

for seed in 101 102 103; do
  output="$RESULT_DIR/seed${seed}.json"
  if [[ -e "$output" ]]; then
    echo "seed${seed}: existing evidence preserved"
    continue
  fi
  "$PYTHON" scripts/run_mixed_workload.py \
    --config configs/generalization_7b_low_load.json \
    --base-url http://127.0.0.1:8000 \
    --model "$MODEL_NAME" \
    --tokenizer "$MODEL" \
    --request-rate 1 \
    --num-prompts 300 \
    --warmup-per-class 8 \
    --seed "$seed" \
    --request-timeout-s 120 \
    --server-prefix-caching false \
    --server-max-num-batched-tokens 2048 \
    --server-max-num-seqs 256 \
    --server-scheduling-policy fcfs \
    --output "$output"
done

cleanup
trap - EXIT

"$PYTHON" scripts/derive_generalization_slos.py \
  --inputs \
    "$RESULT_DIR/seed101.json" \
    "$RESULT_DIR/seed102.json" \
    "$RESULT_DIR/seed103.json" \
  --expected-seeds 101 102 103

echo EXPERIMENT017_LOW_LOAD_CALIBRATION_COMPLETE
