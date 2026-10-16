#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH=src
python_bin="${PYTHON_BIN:-python}"
exec 9>run/experiment012.lock
flock -n 9 || exit 73
"$python_bin" scripts/prepare_experiment012.py
"$python_bin" -m unittest discover -s tests -q
for protocol in order_control012 repeated_shift012; do
  "$python_bin" scripts/compare_policies.py --config "configs/$protocol.json" \
    --model-path "${MODEL_PATH:?Set MODEL_PATH}" \
    --vllm-bin "${VLLM_BIN:-vllm}" \
    --output-dir "results/$protocol" >"logs/$protocol.log" 2>&1
done
echo EXPERIMENT012_COMPLETE
