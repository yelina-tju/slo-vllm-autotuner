# Reviewer handoff: online-admission recovery extension

Updated2026-09-22. This supplements, not replaces, the original vLLM project and
its earlier controller/restart/7B experiments. Career materials are unchanged.

## What this extension demonstrates

SLO feedback can hot-update admission rate without restarting vLLM. Request
arrival cohorts, outcome finalization, acknowledged policy revisions, settling
and fresh evidence prevent stale/mixed-policy evidence from driving decisions.
Frozen paired controls and raw evidence audit test behavior rather than just
presenting a favorable console summary. Check README for earlier implementation
and cancellation/transport tests; this handoff focuses on the recovery evidence.

## Evidence ladder: preserve all three conclusions

| Stage | Design | Conclusion | Report |
|---|---|---|---|
|Development309/310|240s, fixed24/fixed48/adaptive48|Recovery replicated; one interrupted batch linked to continuation|RECOVERY_RESULTS.md|
|Unseen401/402|Same240s distribution|Inconclusive initial baseline due to boundary-straddling requests; NOT discarded|HELDOUT_RESULTS.md|
|Guarded403/404|New frozen260s design,20s guard|Both baseline/recovery gates pass; full-high evidence observed|GUARDED_RESULTS.md|

Do not average or merge these into six equivalent independent seeds. The last
design was informed by a failed validation and uses new traces. Two final seeds
support descriptive replication only, not a universal guarantee.

## Strong technical discussion points

- Arrival-time cohort membership is not completion-time phase isolation.
  A request arriving just before a workload transition may legitimately violate
  afterward. The original gate caught this rather than silently excluding it.
- Action time is not evidence provenance. A decrease after the step can be based
  on pre-step arrivals. The new report labels both, and both final adaptive runs
  actually use[60,80) fully high-load evidence.
- Recovery is not episode-wide compliance: the final adaptive high phases still
  have about17% service violations because initial overload costs remain counted.
- Against conservative fixed24, whole-trace scheduled goodput rises about19%,
  but978/986 extra service violations are incurred. Against aggressive fixed48,
  violations fall by6594/6531. Explain the tradeoff, not “all metrics improved”.
- Evidence reproducibility: frozen source/config/trace identities, exclusive
  output paths, bounded runs, owned-backend cleanup, linked partial provenance,
  independent reconstruction from raw request and telemetry logs.

## Do not claim

Optimal admission rate; best-static superiority; continuous SLO guarantee;
significance from two seeds; controller overhead inferred from5ms acknowledgement;
7B/multi-model/mixed-workload validation for THIS extension;401/402 success;
causal proof that the guard alone improved recovery; production readiness.

## Where to inspect

- Code: feedback.py, cohorts.py, deadline_cohorts.py, transport.py, run_pilot.py.
- Final protocol: guarded_protocol.py, guarded_recovery_plan.py.
- Measurement: guarded_recovery_analysis.py; independent audit_guarded_recovery.py.
- CPU-only full evidence recheck: recheck_guarded_evidence.py.
- Sibling work folder: guarded-sep22-evidence.tar.gz and extracted directory,
  guarded-sep22-audit.json, guarded-sep22-diagnostics.json,
  guarded-sep22-chain-recheck.json; predecessor bundles must also be kept.

Final stage: completed and locally backed up. No GPU process remains from it.
Further model/workload expansion is optional new scope, not needed to finish
this registered experiment. Documentation can be used for future résumé/interview
drafting, but this file is a factual handoff, not a rewritten résumé claim.
