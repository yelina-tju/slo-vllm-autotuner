#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-python}"
VLLM="${VLLM_BIN:-vllm}"
MODEL="${MODEL_PATH:?Set MODEL_PATH to a local model directory}"
LOCK="$ROOT/run/experiment017-final.lock"

cd "$ROOT"
mkdir -p run logs
exec 9>"$LOCK"
flock -n 9 || { echo "experiment 017 final benchmark is already running"; exit 1; }

test -s results/generalization_7b_balanced_capacity_final_policy.json
test -s results/generalization_7b_mixed_capacity_final_policy.json

export PYTHONPATH=src
"$PYTHON" scripts/prepare_experiment017_final.py
"$PYTHON" -m unittest discover -s tests -v

for seed in 121 122 123 124; do
  "$PYTHON" scripts/compare_policies.py \
    --config "configs/generalization_7b_final_seed${seed}.json" \
    --model-path "$MODEL" \
    --served-model-name qwen2.5-7b \
    --vllm-bin "$VLLM" \
    --controller-config configs/generalization_7b_controller.json \
    --workload-policy results/generalization_7b_workload_policy.json \
    --workload-profiles configs/generalization_7b_workload_profiles.json \
    --mixed-policy results/generalization_7b_mixed_capacity_final_policy.json \
    --mixed-workload-config configs/generalization_7b_mixed.json \
    --output-dir "results/generalization_7b_final_seed${seed}" \
    2>&1 | tee "logs/generalization_7b_final_seed${seed}.log"
done

"$PYTHON" scripts/summarize_experiment017_final.py
echo EXPERIMENT017_FINAL_COMPLETE
