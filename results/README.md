# Result summaries

This directory versions small aggregate results and measured policy inputs.
Per-request traces, generated payloads, process logs and raw run directories
remain local and are excluded by `.gitignore`. No raw evidence was deleted.

| File | Experiment |
|---|---|
| `final_benchmark_analysis.json`, `final_benchmark_rows.csv` | V1 1.5B, five seeds and five policies |
| `generalization_7b_final_analysis.json`, `generalization_7b_final_rows.csv` | V1 7B, four seeds and four policies |
| `generalization_7b_capacity_audit.json` | Held-out capacity-selection checks |
| `*_policy.json` | Measured inputs used by controllers and CPU contracts |
| Other `*_analysis.json` and CSV summaries | Earlier experiments; see the result index for their scope |

The independent online-admission extension is reported in
[GUARDED_RESULTS.md](../extensions/online_admission/GUARDED_RESULTS.md).
The [result index](../docs/RESULTS_INDEX.md) distinguishes development,
final comparison, fault injection and inconclusive experiments.

Some JSON fields name raw local runs that are not in a public clone. These are
provenance references, not downloadable paths. A summary is not a substitute
for raw-data reanalysis. The archive requirements and offline checks are in
[REPRODUCIBILITY.md](../docs/REPRODUCIBILITY.md).
