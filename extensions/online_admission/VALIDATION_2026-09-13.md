# Stage 2 integration-contract validation

## Server preflight

Authenticated existing SSH key without replacement. RTX 4090D, 24564 MiB,
0 MiB allocated, no GPU process. No active experiment driver was present.
Original result directories and driver logs were retained. The last restart-fail
driver log reports healthy recovery, successful post-recovery completion, and
backend cleanup stopped. No old experiment was rerun.

## Changes

Only independent extensions/online_admission files changed locally. Uploaded
the extension to /root/autodl-tmp/online-admission-v2, outside both existing
experiment source and frozen release source. No model/backend was launched.

events.py accepts ordered request-start/completion events with admission
revision. It requires a trustworthy monotonic watermark. Unknown/duplicate/late
events fail explicitly; it does not silently infer missing data from polling.
Mixed revisions and pending streams block evidence. Rejections contribute
demand, not backend failures. Pending age is reported but does not yet trigger
an emergency decrease or cancellation. Class set stays explicit and fixed.

hot_gate.py subclasses the unchanged v1 admission gate. update_rate does not
resume a pause or refill a fresh burst. apply_proposal serializes with executor
lifecycle operations; mismatched applied rates and paused gates reject updates.
The current wrapper requires one feedback owner and feedback reset on lifecycle
changes. It uses private gate/executor fields and needs a stable interface before
production use; it is not yet wired into the live gateway.

## Executed CPU checks

- Existing cloud working source: 99 tests passed (older source copy).
- Frozen /root/autodl-tmp/release-final: 102 tests passed.
- Extension against frozen release src: 18 tests passed, Python unittest.
- Extension also passed against older working source: 18 tests.

Extension command on cloud:

```sh
cd /root/autodl-tmp/online-admission-v2
PYTHONPATH=/root/autodl-tmp/release-final/src /root/autodl-tmp/envs/vllm-autotuner/bin/python -m unittest discover -s . -p 'test_*.py' -q
```

## Explicit non-results / next gate

No real streaming HTTP integration, historical event replay, GPU pilot, capacity
estimate, throughput comparison, or stability claim in this stage. Any-pending
blocking is deliberately conservative and will stall adaptation under continuous
traffic. Next: bounded arrival cohorts with delayed finalization, timeout safety,
and an opt-in live gateway hook; test continuous traffic before spending GPU
time. Keep v1 results and career materials unchanged.
