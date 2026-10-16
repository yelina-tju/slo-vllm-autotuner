#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-python}"
DOWNLOAD_LOG="$ROOT/logs/experiment017-download-retry1.log"
CALIBRATION_LOG="$ROOT/logs/experiment017-calibration.log"
LOCK="$ROOT/run/experiment017-continuation.lock"

cd "$ROOT"
mkdir -p run logs
exec 9>"$LOCK"
flock -n 9 || { echo "experiment 017 continuation is already running"; exit 1; }

echo "waiting for the resumable 7B download"
while pgrep -f '[d]ownload_experiment017_model.py' >/dev/null; do
  sleep 15
done

if ! grep -q '^EXPERIMENT017_MODEL_DOWNLOAD_COMPLETE$' "$DOWNLOAD_LOG"; then
  echo "download did not finish successfully; calibration will not start" >&2
  tail -n 80 "$DOWNLOAD_LOG" >&2
  exit 1
fi

export PYTHONPATH=src
"$PYTHON" -m unittest discover -s tests -v
bash scripts/run_experiment017_calibration.sh 2>&1 | tee "$CALIBRATION_LOG"
