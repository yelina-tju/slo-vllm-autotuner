#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-python}"
VLLM="${VLLM_BIN:-vllm}"
MODEL="${MODEL_PATH:?Set MODEL_PATH to a local model directory}"
LOCK="$ROOT/run/experiment015.lock"

cd "$ROOT"
mkdir -p run logs
exec 9>"$LOCK"
flock -n 9 || { echo "experiment 015 is already running"; exit 1; }

export PYTHONPATH=src
"$PYTHON" scripts/prepare_experiment015.py
"$PYTHON" -m unittest discover -s tests -v

for seed in 88 89 90 91 92; do
  "$PYTHON" scripts/compare_policies.py \
    --config "configs/final_benchmark_seed${seed}.json" \
    --model-path "$MODEL" \
    --vllm-bin "$VLLM" \
    --output-dir "results/final_benchmark_seed${seed}" \
    2>&1 | tee "logs/final_benchmark_seed${seed}.log"
done

"$PYTHON" scripts/summarize_final_benchmark.py
echo EXPERIMENT015_COMPLETE
