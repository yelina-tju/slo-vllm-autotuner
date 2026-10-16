#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-python}"
VLLM="${VLLM_BIN:-vllm}"
MODEL="${MODEL_PATH:?Set MODEL_PATH to a local model directory}"
MODEL_NAME=qwen2.5-7b
LOCK="$ROOT/run/experiment017-capacity-extension.lock"
RESULT_DIR="$ROOT/results/generalization_7b_capacity"
SERVER_RUN_DIR="$ROOT/run/experiment017-capacity-extension-server"

cd "$ROOT"
mkdir -p run logs "$RESULT_DIR"
exec 9>"$LOCK"
flock -n 9 || { echo "experiment 017 capacity extension is already running"; exit 1; }

export PYTHONPATH=src

# Recompute the base-only policies. The evaluator filters by the seeds declared
# in each manifest, so a resumed extension can never leak extension outcomes
# into the trigger decision.
for workload in balanced mixed; do
  "$PYTHON" scripts/evaluate_mixed_search.py \
    --manifest "configs/generalization_7b_${workload}_search.json" \
    --workload-config "configs/generalization_7b_${workload}.json" \
    --result-dir "$RESULT_DIR" \
    --output-csv "results/generalization_7b_${workload}_search.csv" \
    --output-policy "results/generalization_7b_${workload}_policy.json" \
    --workload-name "qwen2.5-7b_${workload}"
done
"$PYTHON" scripts/prepare_experiment017_capacity_extension.py

export MODEL_PATH="$MODEL"
export SERVED_MODEL_NAME="$MODEL_NAME"
export VLLM_BIN="$VLLM"
export ENABLE_PREFIX_CACHING=false
export ENABLE_CHUNKED_PREFILL=true
export MAX_NUM_SEQS=256
export SCHEDULING_POLICY=fcfs
export RUN_DIR="$SERVER_RUN_DIR"

cleanup() {
  bash scripts/server_ctl.sh stop || true
}
trap cleanup EXIT

is_triggered() {
  local workload="$1"
  local candidate="$2"
  "$PYTHON" -c \
    'import json,sys; p=json.load(open(sys.argv[1])); raise SystemExit(0 if sys.argv[2] in p["extension_candidates"] else 1)' \
    "configs/generalization_7b_${workload}_capacity_final_search.json" \
    "$candidate"
}

run_candidate() {
  local workload="$1"
  local mbt="$2"
  local num_prompts="$3"
  shift 3
  local rates=("$@")
  local candidate="mbt${mbt}_fcfs"
  local config="configs/generalization_7b_${workload}.json"

  if ! is_triggered "$workload" "$candidate"; then
    echo "$workload $candidate: base search was bounded; extension skipped"
    return
  fi

  export MAX_NUM_BATCHED_TOKENS="$mbt"
  export LOG_FILE="$ROOT/logs/experiment017-extension-${workload}-mbt${mbt}-server.log"
  bash scripts/server_ctl.sh start
  local ready=false
  for _ in {1..180}; do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
      ready=true
      break
    fi
    if ! bash scripts/server_ctl.sh status >/dev/null 2>&1; then
      echo "server exited before healthy: workload=$workload mbt=$mbt" >&2
      tail -n 100 "$LOG_FILE" >&2
      exit 1
    fi
    sleep 2
  done
  [[ "$ready" == true ]] || { echo "server health timeout" >&2; exit 1; }

  for rate in "${rates[@]}"; do
    local all_pass=true
    for seed in 114 115 116; do
      local output="$RESULT_DIR/generalization7b_${workload}_rps${rate}_mbt${mbt}_fcfs_seed${seed}.json"
      if [[ ! -e "$output" ]]; then
        "$PYTHON" scripts/run_mixed_workload.py \
          --config "$config" \
          --base-url http://127.0.0.1:8000 \
          --model "$MODEL_NAME" \
          --tokenizer "$MODEL" \
          --request-rate "$rate" \
          --num-prompts "$num_prompts" \
          --warmup-per-class 8 \
          --seed "$seed" \
          --request-timeout-s 120 \
          --server-prefix-caching false \
          --server-max-num-batched-tokens "$mbt" \
          --server-max-num-seqs 256 \
          --server-scheduling-policy fcfs \
          --output "$output"
      fi

      set +e
      "$PYTHON" scripts/check_capacity_result.py \
        --path "$output" --model "$MODEL_NAME" --seed "$seed" \
        --rate "$rate" --mbt "$mbt" --num-prompts "$num_prompts"
      local status=$?
      set -e
      if [[ "$status" -eq 2 ]]; then
        echo "invalid preserved capacity-extension result: $output" >&2
        exit 1
      elif [[ "$status" -eq 1 ]]; then
        all_pass=false
      fi
    done
    if [[ "$all_pass" != true ]]; then
      echo "$workload mbt=$mbt: extension stopped after non-robust rate=$rate"
      break
    fi
  done
  cleanup
}

run_candidate balanced 1024 160 14 16 18 20 24
run_candidate balanced 2048 160 14 16 18 20 24
run_candidate mixed 1024 240 5 6 8 10
run_candidate mixed 2048 240 5 6 8 10

trap - EXIT

for workload in balanced mixed; do
  "$PYTHON" scripts/evaluate_mixed_search.py \
    --manifest "configs/generalization_7b_${workload}_capacity_final_search.json" \
    --workload-config "configs/generalization_7b_${workload}.json" \
    --result-dir "$RESULT_DIR" \
    --output-csv "results/generalization_7b_${workload}_capacity_final_search.csv" \
    --output-policy "results/generalization_7b_${workload}_capacity_final_policy.json" \
    --workload-name "qwen2.5-7b_${workload}"
done

"$PYTHON" scripts/audit_experiment017_capacity.py

echo EXPERIMENT017_CAPACITY_EXTENSION_COMPLETE
