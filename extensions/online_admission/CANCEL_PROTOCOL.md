# Cancellation probe — development acceptance, 2026-09-14

Independent 4090D / Qwen2.5-1.5B run, never reusing an already running backend.
No changes to the frozen v1 or dev201 results. No performance comparison.

Minimum experiment: four 64-token warmups, one complete 2048-token control,
two sequential 1.5-second client-timeout requests each requesting 2048 tokens,
and one 64-token recovery request after each timeout. All prompts use 256 token
IDs, temperature 0, ignore_eos, prefix caching disabled. Source/config command
hashes and all raw metric scrapes are preserved in a new output directory.

Control must finish by length, generate 2048 tokens, and take over 3 seconds;
otherwise it does not establish a useful contrast to the 1.5-second deadline.

For EACH timeout case require:

- client TimeoutError and cohort timeout outcome, at least one token observed;
- running >=1 observed during the request;
- abort finish counter increases exactly one, length finish counter unchanged;
- generated token delta is positive and less than 2048;
- running=waiting=0 and generated-token counter unchanged for at least 2 seconds,
  observed within a 10-second post-client deadline;
- one timeout-triggered admission decrease applied and local in-flight count zero;
- subsequent normal request succeeds and backend health returns HTTP 200.

Metric names/abort label were checked against the installed vLLM source before
launch. Missing required metrics FAIL the probe, not silently count as zero.
Idle alone is insufficient: a request that naturally finished at full length is
not evidence of cancellation. No API request is sent through an artificial delay
proxy in this probe; it directly tests the StreamingPilot client timeout path.

Only one request is intentionally outstanding at a time, so aggregate metric
deltas have a clear attribution. This does NOT cover many-client contention,
different engines/models, restart rollback, non-cooperative backends or universal
cancellation guarantees. Sampling resolution (~100 ms plus HTTP time) limits
latency claims. Record first observed idle and plateau confirmation separately.

Startup timeout 240s, whole probe timeout 360s, owned-process-group cleanup.
Preserve partial failures; no automatic repeated GPU attempts. Inspect exit and
GPU state afterwards, then copy evidence locally.
