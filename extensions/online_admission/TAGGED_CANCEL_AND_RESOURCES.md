# Tagged cancellation and resource measurements — 2026-09-14

## Outcome

New tagged-request protocol: **2/2 timeout cases passed**, independently audited
against raw metrics and exact request-ID log lines. The earlier counter-v1 run
remains FAILED under its original criteria; it was re-audited and not relabeled.

The new run enables --enable-log-requests and sends two unique X-Request-Id
values. The corresponding `Request cmpl-cancel-proof-case-N-0 aborted.` line is
required exactly once, in addition to resource-idle/token-plateau/recovery checks.
The protocol was saved before launch (CANCEL_TAGGED_PROTOCOL.md).

Full-length control: 2048 generated tokens, 8.5728 seconds, length finish +1.
Timeout cases: 1.5-second deadlines, 365 / 357 accounted generated tokens,
one exact tagged cancellation event each, no length completion, running/waiting
return to zero, >=2-second token plateau, timeout-triggered 3 -> 2.1 RPS decrease,
local gate release and successful recovery/health check. Aggregate abort counter
delta stayed zero in BOTH cases; retained as an explicit diagnostic, not hidden.

First post-client idle observation: 141.1ms / 17.5ms. Plateau confirmed after
2.246s / 2.137s. These are sampling observations, NOT exact cancellation latency.
This supports the tested installed-vLLM single-request path, not arbitrary
concurrency, model variants, engine failures or production reliability.

## Why CPU and RAM utilization look small

Observed cgroup limits: **16 CPU cores, 80 GiB RAM**. `free` showed roughly 1 TiB
host RAM; this host-wide view must not be mistaken for the container's quota.

Samples collected every approximately one second from /proc for the driver and
its exclusively owned backend group. CPU deltas are expressed as core equivalents:
100% on one core = 1 core, NOT 100% of the 16-core allocation. Memory is PSS
(proportional resident memory), avoiding double-counted shared RSS pages.

| Phase / component | Mean CPU core equivalents | Peak sampled PSS |
|---|---:|---:|
| Startup: driver | 0.062 | 26.0 MiB |
| Startup: model backend group | 3.657 | 4.33 GiB |
| Probe: driver | 0.139 | 26.6 MiB |
| Probe: model backend group | 1.085 | 2.88 GiB |

Probe driver CPU is about 0.87% of the 16-core quota; backend about 6.78%.
These are sampled means over slightly different process-presence intervals,
not a precise synchronized whole-container utilization figure. Peak RAM is
sampled, not a guaranteed maximum. Startup has higher loading/initialization cost.

The driver includes HTTP handling, metric polling, logs, resource sampling and
feedback. These numbers are NOT isolated control-loop overhead. The probe is
serial (one long request at a time), includes idle confirmation periods, and uses
synthetic token-ID inputs; it is neither a CPU-heavy tokenizer benchmark nor a
high-concurrency throughput test. vLLM uses GPU memory separately from system
RAM; low system-memory percentage says nothing about VRAM headroom. cgroup
memory.current additionally includes accounting such as cache and must not be
equated with process PSS. Do not use these small-probe numbers to size production.

## Validation and preservation

- Pre-GPU extension suite: 45 CPU/HTTP tests passed.
- Independent local cancellation-audit suite: 3 passed (includes old failed
  protocol preservation and exact-ID/prefix discrimination).
- Frozen v1 regression: 102 passed.
- Driver resources: 31 startup samples, 26 probe samples; backend present in 24
  probe samples. Recorded sampling errors: none.
- Process-group cleanup: stopped=true, exit_code=0; external GPU check 0 MiB/0%.
- Actual executed source snapshot: 25 manifest-listed Python files, all hashes
  verified locally. No old result or career material changed.

Local evidence archive:

```text
work/online-admission-tagged-sep14-evidence.tar.gz
SHA256 0a090127c7210dbff9188438a780a0aa3d2791c2474296801ee9cd71698d67a5
```

Validated/extracted under work/online-admission-tagged-sep14-evidence/, containing
online-admission-tagged-v8/ (executed source) and
online-admission-pilot-results/cancel-tagged-sep14-attempt1/ (raw evidence).
Independent audit: work/online-admission-tagged-sep14-audit.json.

Local Windows audit explicitly decodes backend.log as UTF-8 (replacement for
invalid bytes) instead of locale-dependent GBK. This post-run reader fix did not
change GPU code or evidence. Source manifests retain the exact executed version.

## Next

The tested cancellation-path evidence gap is closed. Next development focus is
deadline-anchored evidence cohorts to remove avoidable fixed-grid alignment delay,
with CPU tests retaining old-request accounting and strict revision isolation.
Only then consider controlled multi-load comparisons with calibrated static
baselines. No extra GPU trial is needed just to repeat this passed probe.
