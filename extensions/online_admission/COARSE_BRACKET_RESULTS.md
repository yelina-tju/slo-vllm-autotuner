# Stage 12 bounded coarse bracket — 2026-09-20

## Outcome

Six runs completed, independently audited and backed up locally. The frozen
sequential rule selected **LOW=24 RPS, HIGH=48 RPS**, with both classifications
replicated in development seeds307 and308. Seed307 rate36 was AMBIGUOUS and
therefore ineligible as a LOW anchor. This closes the pressure-calibration gate,
not controller recovery or held-out evaluation.

No seventh run, retry, altered threshold or extra seed was used. The first HIGH
occurred at the cap48, so this batch used all six allowed cases; early stopping
was implemented/tested but did not save cases relative to that maximum here.
No recovery GPU experiment was started. The adaptive default maximum6 and
growth margin0.8, frozen V1, resume and interview material remain unchanged.

## Fixed conditions and actual execution order

Qwen2.5-1.5B FP16 on one4090D; balanced256-input/64-output requests;
TTFT100ms and E2E400ms SLO. Each case120s, fresh engine, four identical warmups.
Offered Poisson72 RPS; seed307 has8,663 arrivals, seed308 has8,655. Each seed's
exact arrival/prompt trace was reused across its static rates. Classification
uses six20s windows; see COARSE_BRACKET_PROTOCOL.md for the frozen rules.

| Seed | Admission RPS | Successful200 | Service-compliant | Rejected429 | Scheduled goodput req/s | P99 TTFT ms | P99 E2E ms | Breached windows | Label |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 307 | 18 | 2163 | 2163 | 6500 | 18.0250 | 36.65 | 344.05 | 0/6 | LOW |
| 307 | 24 | 2885 | 2885 | 5778 | 24.0417 | 36.50 | 358.06 | 0/6 | LOW |
| 307 | 36 | 4327 | 4308 | 4336 | 35.9000 | 48.29 | 392.01 | 1/6 | AMBIGUOUS |
| 307 | 48 | 5769 | 158 | 2894 | 1.1917 | 62.03 | 478.36 | 6/6 | HIGH |
| 308 | 48 | 5770 | 159 | 2885 | 1.2167 | 62.36 | 475.73 | 6/6 | HIGH |
| 308 | 24 | 2885 | 2885 | 5770 | 24.0417 | 38.26 | 358.24 | 0/6 | LOW |

51,962 offered records =23,799 admitted successes +28,163 deliberate rejections.
No backend failures, request loss, static actuation, outstanding requests or
unfinished cohorts. There were11,241 completed-request SLO violations, including
19 at36 and5,611 in each48 run. HTTP200 means successful completion, not SLO compliance.

Service-compliant measures latency from service dispatch. Scheduled goodput also
includes the driver's recorded dispatch lag: high-rate compliant counts are143
and146 rather than158/159. A stricter reconstruction using actual admission
timestamps gives141 and140 (goodput1.1750 and1.1667); all other rows retain the
same compliant counts. These definitions must not be mixed when comparing arms.

## Interpretation and limitations

- Rate36's whole-run P99 E2E392.01ms and violation fraction0.439% hide one window
  with pressure1.0164 (E2E P99 about406.56ms). Under the preregistered rule it is
  neither consistently LOW nor repeatedly HIGH. It was not retested or relabeled.
- Rate48's two runs have about97.26% and97.24% service violations. TTFT remains
  within SLO; E2E is the limiting metric. High successful throughput is not high
  compliant goodput.
- Rate24 is a replicated compliant anchor under these conditions, **not the
  optimal throughput setting or a universally safe capacity**. Rate36 actually
  has higher measured goodput in its single run, but fails the stricter window
  criterion. The interval24–48 does not resolve a precise boundary or prove
  monotonic latency behavior.
- These are two development traces of one synthetic model/shape, with sequential
  selection and one confirmation trace, not independent held-out performance or
  confidence bounds. This does not establish multi-model generalization.

## Telemetry and generation diagnostic

694 valid within-traffic samples. Maximum sampled running counts across the six
cases:7/9/16/29/28/9; client in-flight peaks10/14/22/34/34/14. Sampled waiting was
zero throughout, despite HIGH latency. A1s sampler cannot exclude brief queueing,
and this is not a causal decomposition of scheduling versus decode latency.
Maximum actual admission lag45.622ms and metrics scrape61.992ms are below the
frozen250ms/500ms bounds. Sampling overhead was not separately ablated.

Supplementary raw generation histograms have monotone completion counts and
cumulative mean output64 in every sample. Final counters lag request logs plus
four warmups by0–19 completions. This is aggregate consistency evidence, not
per-request token proof or a new inclusion rule. Request logs remain authoritative.

## Verification and operations

1. Checked the existing cloud GPU/process state and absence of the new result
   directory. No completed calibration was rerun.
2. Implemented sequential planning, exclusive checkpoints and capped execution.
   Local20 planning/analysis/metric tests passed. Source v14 was archived/uploaded
   independently of prior snapshots; local/remote source archive SHA256 matched.
3. Frozen v14 cloud CPU/HTTP suite:106 tests passed in1.879s before GPU launch.
   Plan tests enumerate all3^6 label sequences, confirming termination by six
   cases; error and checkpoint failures prevent another launch.
4. Ran the six cases in the order above. Each owned backend was warmed and cleaned
   independently. The cloud snapshot remained unchanged throughout execution.
5. Built the separate local read-only auditor while the GPU ran. A selected local
   suite of45 tests passed in1.659s, including eight new provenance/checkpoint
   tamper tests. These test counts overlap; do not add them as distinct tests.
6. Original frozen V1 regression after GPU completion:102 tests passed in0.158s.
7. Downloaded the archive, verified SHA256, checked178 member paths/types and
   extracted to a new directory. Reconstructed all requests/windows/metrics,
   sequential choices and six checkpoints. All49 executed Python source hashes,
   config, profile, V1 dependencies, model config and engine commands were checked
   against the snapshot/prior baseline. Only the private engine port differs.
   Every warmup and owned cleanup passed. Independent audit status:passed.
8. GPU query showed0MiB/0% and no compute process; no experiment runner remained.
   Instance is safe to shut down now. No shutdown or deletion was performed.

## Evidence and reproduction

Paths relative to the repository parent:

```text
work/coarse-bracket-v14-source.tar.gz
work/coarse-bracket-sep20-evidence.tar.gz
work/coarse-bracket-sep20-evidence/coarse-bracket-v14/online_admission/
work/coarse-bracket-sep20-evidence/online-admission-pilot-results/
    coarse-dev307-308-attempt1/
work/coarse-bracket-sep20-audit.json
work/coarse-bracket-sep20-generation.json
```

Source archive SHA256:
`754dbaa1f45db093df833e4c87665f159614cb04df97c542c6dacf797ca144bc`.

Evidence archive SHA256, matching cloud and local:
`86ca4f2f0aac4dcec1a4b2b36bf89f7b51713d8078d74a769c366232e26ab777`.

The independent local auditor was added after launch and is intentionally not in
the executed snapshot. Its SHA256 at verification is
`932abdd7dc3ed0dba1be8fdababc3fd5fbe0b28dfb7136628dbbbf0b613057cd`.
Remote raw results and source snapshot remain intact.

Read-only audit from repository root, with Python3.11+ (no GPU/aiohttp needed):

```sh
python extensions/online_admission/audit_coarse_bracket.py \
  ../work/coarse-bracket-sep20-evidence/online-admission-pilot-results/coarse-dev307-308-attempt1 \
  --snapshot ../work/coarse-bracket-sep20-evidence/coarse-bracket-v14/online_admission \
  --static-reference ../work/static-endpoints-sep15-evidence/online-admission-pilot-results/static-endpoints-dev202-203-attempt1
```

## Next gate — not executed

Freeze a matched staticLOW24/staticHIGH48/adaptive-from48 recovery evaluation.
Use an explicitly adverse initial rate only in that evaluation configuration,
not the prototype defaults. Compare full-trace costs and require recovered full
windows **while high offered load is still present**. Recovery after traffic
falls must be reported separately and cannot establish controller benefit.

At decrease factor0.7, the illustrative path48 -> 33.6 -> 23.52 takes two actions
to pass the LOW anchor. Review evidence/settling/finalization timing before
freezing the high-phase duration; the earlier80s draft may be too short.
See RECOVERY_DESIGN_DRAFT.md. Seeds, duration, order, bounds and acceptance tests
still need freezing and CPU tests before any new GPU run. Even a successful
development recovery test would not by itself finish held-out evaluation.
