#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-python}"
VLLM="${VLLM_BIN:-vllm}"
MODEL="${MODEL_PATH:?Set MODEL_PATH to a local model directory}"
LOCK="$ROOT/run/experiment014.lock"

cd "$ROOT"
mkdir -p run logs
exec 9>"$LOCK"
flock -n 9 || { echo "experiment 014 is already running"; exit 1; }

export PYTHONPATH=src
"$PYTHON" scripts/prepare_experiment014.py
"$PYTHON" -m unittest discover -s tests -v
"$PYTHON" scripts/run_live_canary_scenarios.py

for seed in 86 87; do
  "$PYTHON" scripts/compare_policies.py \
    --config "configs/canary_tradeoff_seed${seed}.json" \
    --model-path "$MODEL" \
    --vllm-bin "$VLLM" \
    --output-dir "results/canary_tradeoff_seed${seed}" \
    2>&1 | tee "logs/canary_tradeoff_seed${seed}.log"
done

"$PYTHON" scripts/summarize_canary_tradeoff.py
echo EXPERIMENT014_COMPLETE
