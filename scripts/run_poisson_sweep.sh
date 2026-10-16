#!/usr/bin/env bash
set -euo pipefail

: "${TOKENIZER_PATH:?Set TOKENIZER_PATH to the local tokenizer/model directory}"

VLLM_BIN="${VLLM_BIN:-vllm}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
MODEL_NAME="${MODEL_NAME:-qwen2.5-1.5b}"
RESULT_DIR="${RESULT_DIR:-results/raw}"
REQUEST_RATES="${REQUEST_RATES:-5 20 50}"
NUM_PROMPTS="${NUM_PROMPTS:-100}"
RUN_TAG="${RUN_TAG:-}"
SEED="${SEED:-0}"
NUM_WARMUPS="${NUM_WARMUPS:-16}"
INPUT_TOKENS="${INPUT_TOKENS:-256}"
OUTPUT_TOKENS="${OUTPUT_TOKENS:-64}"
TTFT_SLO_MS="${TTFT_SLO_MS:-100}"
E2EL_SLO_MS="${E2EL_SLO_MS:-400}"
WORKLOAD_NAME="${WORKLOAD_NAME:-custom}"
SERVER_PREFIX_CACHING="${SERVER_PREFIX_CACHING:-unknown}"
SERVER_MAX_NUM_BATCHED_TOKENS="${SERVER_MAX_NUM_BATCHED_TOKENS:-unknown}"
SERVER_MAX_NUM_SEQS="${SERVER_MAX_NUM_SEQS:-unknown}"
TAG_SUFFIX="${RUN_TAG:+_${RUN_TAG}}"

mkdir -p "$RESULT_DIR"

for request_rate in $REQUEST_RATES; do
  echo "===== REQUEST_RATE=${request_rate} req/s ====="
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
    --request-rate "$request_rate" \
    --burstiness 1.0 \
    --temperature 0 \
    --extra-body '{"ignore_eos": true}' \
    --goodput ttft:"$TTFT_SLO_MS" e2el:"$E2EL_SLO_MS" \
    --metric-percentiles 50,90,95,99 \
    --percentile-metrics ttft,tpot,itl,e2el \
    --disable-tqdm \
    --save-result \
    --save-detailed \
    --metadata workload=poisson workload_name="$WORKLOAD_NAME" input_tokens="$INPUT_TOKENS" output_tokens="$OUTPUT_TOKENS" ttft_slo_ms="$TTFT_SLO_MS" e2el_slo_ms="$E2EL_SLO_MS" seed="$SEED" server_prefix_caching="$SERVER_PREFIX_CACHING" server_max_num_batched_tokens="$SERVER_MAX_NUM_BATCHED_TOKENS" server_max_num_seqs="$SERVER_MAX_NUM_SEQS" \
    --result-dir "$RESULT_DIR" \
    --result-filename "poisson_rps${request_rate}${TAG_SUFFIX}_i${INPUT_TOKENS}_o${OUTPUT_TOKENS}.json"
done
