#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON_BIN:-python}"
BASE_PID="${1:?pass the active base-capacity shell PID}"
PACKAGE="$ROOT/run/experiment017-next/experiment017-next-code-v2.tar.gz"
PACKAGE_SHA256=c0a895ecaa76f8197853610f97e3e79a557f12165ce21174e1edaa750ed677b8
BASE_LOG="$ROOT/logs/experiment017-capacity.log"
BACKUP="$ROOT/run/pre017-extension-base-evidence.tar.gz"

cd "$ROOT"
echo "supervisor=waiting base_pid=$BASE_PID"
while kill -0 "$BASE_PID" 2>/dev/null; do
  sleep 30
done

if ! tail -n 200 "$BASE_LOG" | grep -q EXPERIMENT017_CAPACITY_SEARCH_COMPLETE; then
  echo "supervisor=stopped reason=base_capacity_missing_success_marker" >&2
  exit 1
fi
echo "supervisor=base_capacity_complete"

if [[ ! -e "$BACKUP" ]]; then
  tar -czf "$BACKUP" \
    README.md scripts tests src configs docs \
    results/generalization_7b_capacity \
    results/generalization_7b_slo_evidence.json \
    results/generalization_7b_balanced_search.csv \
    results/generalization_7b_balanced_policy.json \
    results/generalization_7b_mixed_search.csv \
    results/generalization_7b_mixed_policy.json \
    logs/experiment017-capacity.log \
    logs/experiment017-balanced-mbt1024-server.log \
    logs/experiment017-balanced-mbt2048-server.log \
    logs/experiment017-mixed-mbt1024-server.log \
    logs/experiment017-mixed-mbt2048-server.log
fi
sha256sum "$BACKUP"

actual_sha256="$(sha256sum "$PACKAGE" | awk '{print $1}')"
if [[ "$actual_sha256" != "$PACKAGE_SHA256" ]]; then
  echo "supervisor=stopped reason=staged_package_hash_mismatch actual=$actual_sha256" >&2
  exit 1
fi
echo "supervisor=package_verified sha256=$actual_sha256"
tar -xzf "$PACKAGE" -C "$ROOT"

export PYTHONPATH=src
"$PYTHON" -m unittest discover -s tests -v
echo "supervisor=cloud_tests_passed"

bash scripts/run_experiment017_capacity_extension.sh

EVIDENCE="$ROOT/run/experiment017-capacity-final-evidence.tar.gz"
if [[ ! -e "$EVIDENCE" ]]; then
  tar -czf "$EVIDENCE" \
    configs/generalization_7b_balanced_search.json \
    configs/generalization_7b_mixed_search.json \
    configs/generalization_7b_balanced_capacity_final_search.json \
    configs/generalization_7b_mixed_capacity_final_search.json \
    results/generalization_7b_capacity \
    results/generalization_7b_capacity_extension_amendment.json \
    results/generalization_7b_balanced_capacity_final_search.csv \
    results/generalization_7b_balanced_capacity_final_policy.json \
    results/generalization_7b_mixed_capacity_final_search.csv \
    results/generalization_7b_mixed_capacity_final_policy.json \
    results/generalization_7b_capacity_audit.json \
    logs/experiment017-capacity.log \
    logs/experiment017-extension-*-server.log
fi
sha256sum "$EVIDENCE"
echo "supervisor=complete next=human_review_before_final_benchmark"
