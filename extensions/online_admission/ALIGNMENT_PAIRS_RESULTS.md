# Stage 8: real-GPU paired alignment results — 2026-09-14

## Outcome and scope

Four planned runs completed, with independent request-level audit passing.
Deadline-anchored evidence reduced the second growth action's delay by
19.771s and 19.554s versus fixed-grid adaptive evidence. Both pairs admitted 31
additional SLO-compliant requests. This supports removing avoidable evidence-grid
delay in this bounded single-class DEVELOPMENT scenario; it does not establish
optimal capacity, overload safety, or held-out generalization.

Both arms are adaptive. The comparison is NOT adaptive versus static 3 RPS.
The protocol in ALIGNMENT_PAIRS_PROTOCOL.md was frozen before launch. No trial
was dropped, retried, or added based on the observed effect.

## Results

Each run: 180 seconds, fresh Qwen2.5-1.5B backend, one 4090D, identical four-request
warmup, same per-seed traffic/prompts and fixed engine configuration. Balanced
256-input/64-output requests, TTFT <=100ms and end-to-end <=400ms. Goodput counts
requests meeting BOTH SLOs per second of offered-traffic duration.

| Seed / execution order | Mode | Offered | SLO-compliant | Rejected (429) | Goodput req/s | Growth times (s) |
|---|---|---:|---:|---:|---:|---|
| 202 / first | adaptive fixed grid | 1246 | 477 | 769 | 2.6500 | 40.115, 120.112 |
| 202 / second | adaptive deadline anchored | 1246 | 508 | 738 | 2.8222 | 40.145, 100.341, 160.548 |
| 203 / first | adaptive deadline anchored | 1308 | 505 | 803 | 2.8056 | 40.383, 100.581, 160.790 |
| 203 / second | adaptive fixed grid | 1308 | 474 | 834 | 2.6333 | 40.370, 120.135 |

All admitted requests succeeded and met the measured SLOs; backend failures,
completed SLO violations, final in-flight requests and pending primary cohorts
were zero in all four runs. Rejected demand is retained in offered totals, not
misreported as backend success or backend failure. Rejections remain substantial.

Fixed modes ended at rate 5; anchored modes reached the imposed upper bound 6.
No decrease was exercised by this workload. Across equal total run durations:

```text
fixed compliant total = 477 + 474 = 951
anchored compliant total = 508 + 505 = 1013
relative difference = (1013 - 951) / 951 = 6.5195%
mean paired goodput difference = +0.172222 requests/s
```

This descriptive percentage is not a resume-ready general performance claim.
Two development seeds, even in reverse order, cannot identify all order/cache
effects or establish a reliable confidence interval. There is no best-static
baseline, held-out evaluation, overload/decrease test, or mixed-class result here.

## Mechanism: why the difference occurs

Both modes require 20s settling after an applied change, then two valid 20s
evidence windows. The initial action occurs just after t=40s. Settling therefore
ends just after t=60s, rather than exactly on the fixed 20s grid.

The fixed-grid [60,80) window starts slightly before that deadline and must be
excluded. Its next two valid windows are [80,100) and [100,120), so growth waits
until approximately t=120s. Anchored evidence starts at the actual settling
deadline and collects two full windows, enabling growth around t=100s. The same
mechanism permits a third anchored growth around t=160s, before the 180s stop.

This preserves the sample floor, confirmation count and settling duration. It
does not achieve speed by accepting stale data or shortening the safety window.
Primary accounting remains on its original global grid; overlapping control
evidence is a separate view and is never added again to request totals.

## Verification and provenance

- Reconstructed 5,108 request memberships across the four runs, unique trace IDs,
  status counts, service/scheduled goodput, P99 evidence ratios, mixed revisions,
  timeout counts, evidence epochs, settling deadlines and bounded action steps.
- Checked no applied action at/after traffic termination; accounting conservation
  and all four owned-backend cleanup records passed.
- Supplementary scoring uses actual admission timestamps relative to intended
  arrival, including time after initial driver lag measurement. All four goodput
  values were unchanged. Maximum actual admission lag was about 3.285ms.
- Verified all 30 executed Python source hashes, configuration hash, four frozen
  v1 dependency hashes and SLO-source hash. The exact executed snapshot is retained.
- Frozen extension CPU/HTTP suite: 56 tests passed before launch and again after
  completion (post-run 1.342s). Six additional local independent audit tests passed,
  including deliberate corruption of counts, quantiles, revisions and timeouts.
- Independent CPU event stress: 100 deterministic scenarios, 25,000 requests,
  8,828 timeout outcomes; primary conservation and evidence membership passed.
  This is a correctness stress check, not a reliability probability estimate.
- Frozen v1 regression suite: 102 tests passed in the cloud environment after
  GPU completion. A local invocation could not import two test modules because
  local Python lacks aiohttp (83 discovered entries, two import errors); it is
  not counted as a passing full suite. No dependency/runtime changes were needed.

During the GPU batch, only local independent audit/stress/planning files changed.
The executed remote v10 source/config remained unchanged. The local auditor adds
the actual-admission-time diagnostic mentioned above to the archived auditor;
raw logs and original summary metrics were not rewritten.

Local evidence, relative to repository parent:

```text
work/alignment-pairs-sep14-evidence.tar.gz
work/alignment-pairs-sep14-evidence/online-admission-alignment-pairs-v10/
work/alignment-pairs-sep14-evidence/online-admission-pilot-results/
    alignment-pairs-dev202-203-attempt1/
work/alignment-pairs-sep14-audit.json
work/deadline-accounting-stress-sep14.json
```

Archive SHA256:
`59b1b2dd584801df843b75e11cab11b0ef8b2d8c6e6ebd793d23e394099f5945`

Archive bytes matched the remote hash; member paths/types were checked before
extraction into a new local directory. Remote originals were retained. GPU process
query was empty after batch cleanup; no additional GPU experiment was launched.

## Next work

See EVALUATION_NEXT_GATES.md: independently selectable static baselines and CPU
validation, bounded genuine SLO-pressure/decrease/recovery protocol, then frozen
held-out evaluation. Before mixed-class generalization, address the sample-budget
problem documented in SAMPLE_BUDGET_NOTES.md. Do not simply lower the evidence
floor to force growth. Keep v1 and career materials frozen until v2 coverage is
sufficiently clear.
