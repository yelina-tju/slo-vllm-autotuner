#!/usr/bin/env bash
set -euo pipefail

: "${MODEL_PATH:?Set MODEL_PATH to the downloaded model directory}"

VLLM_BIN="${VLLM_BIN:-vllm}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen2.5-1.5b}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
ENABLE_PREFIX_CACHING="${ENABLE_PREFIX_CACHING:-false}"
ENABLE_CHUNKED_PREFILL="${ENABLE_CHUNKED_PREFILL:-true}"
MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-auto}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-auto}"
MAX_NUM_PARTIAL_PREFILLS="${MAX_NUM_PARTIAL_PREFILLS:-auto}"
MAX_LONG_PARTIAL_PREFILLS="${MAX_LONG_PARTIAL_PREFILLS:-auto}"
LONG_PREFILL_TOKEN_THRESHOLD="${LONG_PREFILL_TOKEN_THRESHOLD:-auto}"
SCHEDULING_POLICY="${SCHEDULING_POLICY:-fcfs}"

case "$ENABLE_PREFIX_CACHING" in
  true) prefix_cache_flag="--enable-prefix-caching" ;;
  false) prefix_cache_flag="--no-enable-prefix-caching" ;;
  *) echo "ENABLE_PREFIX_CACHING must be true or false" >&2; exit 2 ;;
esac

case "$ENABLE_CHUNKED_PREFILL" in
  true) chunked_prefill_flag="--enable-chunked-prefill" ;;
  false) chunked_prefill_flag="--no-enable-chunked-prefill" ;;
  *) echo "ENABLE_CHUNKED_PREFILL must be true or false" >&2; exit 2 ;;
esac

case "$SCHEDULING_POLICY" in
  fcfs|priority) ;;
  *) echo "SCHEDULING_POLICY must be fcfs or priority" >&2; exit 2 ;;
esac

scheduler_args=()
if [[ "$MAX_NUM_BATCHED_TOKENS" != "auto" ]]; then
  scheduler_args+=(--max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS")
fi
if [[ "$MAX_NUM_SEQS" != "auto" ]]; then
  scheduler_args+=(--max-num-seqs "$MAX_NUM_SEQS")
fi
if [[ "$MAX_NUM_PARTIAL_PREFILLS" != "auto" ]]; then
  scheduler_args+=(--max-num-partial-prefills "$MAX_NUM_PARTIAL_PREFILLS")
fi
if [[ "$MAX_LONG_PARTIAL_PREFILLS" != "auto" ]]; then
  scheduler_args+=(--max-long-partial-prefills "$MAX_LONG_PARTIAL_PREFILLS")
fi
if [[ "$LONG_PREFILL_TOKEN_THRESHOLD" != "auto" ]]; then
  scheduler_args+=(--long-prefill-token-threshold "$LONG_PREFILL_TOKEN_THRESHOLD")
fi
scheduler_args+=(--scheduling-policy "$SCHEDULING_POLICY")

exec "$VLLM_BIN" serve "$MODEL_PATH" \
  --host "$HOST" \
  --port "$PORT" \
  --served-model-name "$SERVED_MODEL_NAME" \
  --dtype float16 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.75 \
  --disable-uvicorn-access-log \
  "$prefix_cache_flag" \
  "$chunked_prefill_flag" \
  "${scheduler_args[@]}"
