#!/usr/bin/env bash
set -euo pipefail

: "${TOKENIZER_PATH:?Set TOKENIZER_PATH to the local tokenizer/model directory}"

VLLM_BIN="${VLLM_BIN:-vllm}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
MODEL_NAME="${MODEL_NAME:-qwen2.5-1.5b}"
RESULT_DIR="${RESULT_DIR:-results/raw}"
CONCURRENCIES="${CONCURRENCIES:-1 4 8 16 32}"
NUM_PROMPTS="${NUM_PROMPTS:-64}"
NUM_WARMUPS="${NUM_WARMUPS:-2}"
INPUT_TOKENS="${INPUT_TOKENS:-256}"
OUTPUT_TOKENS="${OUTPUT_TOKENS:-64}"
WORKLOAD_NAME="${WORKLOAD_NAME:-custom}"
RUN_TAG="${RUN_TAG:-}"
SEED="${SEED:-0}"
SERVER_PREFIX_CACHING="${SERVER_PREFIX_CACHING:-unknown}"
SERVER_MAX_NUM_BATCHED_TOKENS="${SERVER_MAX_NUM_BATCHED_TOKENS:-unknown}"
SERVER_MAX_NUM_SEQS="${SERVER_MAX_NUM_SEQS:-unknown}"
TAG_SUFFIX="${RUN_TAG:+_${RUN_TAG}}"

mkdir -p "$RESULT_DIR"

for concurrency in $CONCURRENCIES; do
  "$VLLM_BIN" bench serve \
    --backend openai \
    --base-url "$BASE_URL" \
    --endpoint /v1/completions \
    --model "$MODEL_NAME" \
    --tokenizer "$TOKENIZER_PATH" \
    --dataset-name random \
    --seed "$SEED" \
    --num-prompts "$NUM_PROMPTS" \
    --num-warmups "$NUM_WARMUPS" \
    --random-input-len "$INPUT_TOKENS" \
    --random-output-len "$OUTPUT_TOKENS" \
    --request-rate inf \
    --max-concurrency "$concurrency" \
    --temperature 0 \
    --extra-body '{"ignore_eos": true}' \
    --metric-percentiles 50,90,95,99 \
    --percentile-metrics ttft,tpot,itl,e2el \
    --disable-tqdm \
    --save-result \
    --save-detailed \
    --metadata workload=closed_loop_calibration workload_name="$WORKLOAD_NAME" input_tokens="$INPUT_TOKENS" output_tokens="$OUTPUT_TOKENS" seed="$SEED" server_prefix_caching="$SERVER_PREFIX_CACHING" server_max_num_batched_tokens="$SERVER_MAX_NUM_BATCHED_TOKENS" server_max_num_seqs="$SERVER_MAX_NUM_SEQS" \
    --result-dir "$RESULT_DIR" \
    --result-filename "calibration_c${concurrency}${TAG_SUFFIX}_i${INPUT_TOKENS}_o${OUTPUT_TOKENS}.json"
done
