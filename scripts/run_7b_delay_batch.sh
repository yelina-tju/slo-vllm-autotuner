#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH=src
PYTHON="${PYTHON_BIN:-python}"
mkdir -p run
exec 9>run/fault7b-delay-batch.lock
flock -n 9 || exit 1
for seed in 131 132; do
  "$PYTHON" scripts/run_7b_fault_pairs.py --seed "$seed" --fault
  "$PYTHON" scripts/audit_7b_fault_pair.py "results/fault7b_delay_seed${seed}"
done
echo FAULT7B_DELAY_BATCH_COMPLETE
