# Experiment 007: Live event gateway and transactional single-GPU executor

## Objective

Connect the replay-tested controller to real OpenAI-compatible completion
traffic and make every policy transition safe enough to execute on one GPU.
The transition contract is:

```text
pause admission -> drain in-flight requests -> stop old vLLM
-> start target policy -> wait for /health -> resume at target rate
```

If the target does not become healthy, the executor stops it and starts the
last working policy. Admission resumes only after that rollback passes its own
health check. If neither target nor rollback is healthy, admission remains
paused; sending traffic to a known-bad process would be the less safe outcome.

## Implementation

### Live request/event path

`src/slo_autotuner/gateway.py` provides a localhost gateway with four routes:

- `POST /v1/completions`: proxies streaming requests to vLLM;
- `GET /health`: reports readiness only when the backend is healthy and
  admission is open;
- `GET /controller/state`: exposes controller, admission and transition state;
- `GET /events`: exposes a bounded request-event audit view.

The gateway accepts either one text prompt or one token-ID prompt. Text is
counted with the model tokenizer; a token-ID list has an exact length. Batched
prompts and non-streaming responses are deliberately rejected in this MVP so
their different latency semantics cannot silently corrupt TTFT measurements.

The SSE parser is incremental: it handles UTF-8 and JSON lines split across
arbitrary network chunks. The backend request forces `return_token_ids=true`,
so a generated special token with empty visible text still counts as a real
first token. Offered request shapes feed the workload detector before
admission; only admitted backend outcomes feed the SLO collector. This keeps
workload detection visible under overload without treating an intentional
rate-limit rejection as backend latency.

The 60-second SLO collector maps detector shapes to each policy's actual SLO
classes through `configs/controller.json`. For example, under `mixed_80_20`,
`balanced` maps to `interactive_short` and `prefill_heavy` maps to
`document_long`. Failures are violations even when the window has fewer than
the normal minimum number of successful samples.

### Transactional executor

`src/slo_autotuner/executor.py` contains:

- a pauseable token-bucket `AdmissionGate` with an in-flight counter;
- `PolicyExecutor`, which serializes transitions with an async lock;
- `ShellServerLifecycle`, which controls the detached vLLM process and polls
  the backend health endpoint;
- structured `ExecutionResult.steps`, status and diagnostic detail.

The important failure branches are:

| Failure | Result |
|---|---|
| drain timeout | preserve the untouched source server and reopen source admission |
| old-server stop fails but source is healthy | restore controller state and reopen source admission |
| old-server stop fails and source is unhealthy | keep admission paused |
| target startup/health fails | stop target, restart and health-check source |
| target and source both fail | keep admission paused for manual recovery |

When only the admission limit changes and the vLLM environment is identical,
the executor drains and updates admission without restarting the model.

At gateway startup, the default behavior establishes ownership of the backend:
it stops any unknown existing process and starts the configured default policy.
An operator must explicitly pass `--adopt-existing-backend` to trust an already
healthy process. Future runs append request, decision and execution records to
`results/gateway_audit.jsonl`.

## Automated verification

The full suite has 40 passing tests. New coverage includes:

- split SSE chunks and invisible token IDs;
- real aiohttp proxy streaming and event measurement;
- paused admission returning HTTP 503 without backend dispatch;
- per-class rolling SLO aggregation;
- waiting for an in-flight request before stopping vLLM;
- drain timeout preserving the current process;
- target startup failure recovering the last working policy;
- target and rollback failure keeping admission closed;
- no-restart admission-only changes;
- explicit versus implicit ownership of an existing backend.

```bash
PYTHONPATH=src /root/autodl-tmp/envs/vllm-autotuner/bin/python \
  -m unittest discover -s tests -v
```

## Live 4090D validation

The test started with no vLLM or gateway process. The gateway launched the
measured default policy:

```text
balanced:mbt2048-seq256, admission=24 req/s
```

A five-request preflight completed 5/5 through the gateway. Then 80 Poisson
arrivals at 2 req/s used the measured 80% 256/64 and 20% 2048/64 mix. At the
third confirmation window, the detector reported:

| Field | Observed |
|---|---:|
| rolling samples | 79 |
| balanced share | 0.797468 |
| prefill-heavy share | 0.202532 |
| distance to `mixed_80_20` | 0.002532 |

The live executor applied this transition:

```text
balanced:mbt2048-seq256
  -> mixed_80_20:selected:mbt1024_fcfs
```

Its recorded steps were:

```text
admission_paused
in_flight_drained
source_stopped
target_start_command_succeeded
target_health_passed
target_admission_resumed
```

The new process command line contained
`--max-num-batched-tokens 1024 --max-num-seqs 256 --scheduling-policy fcfs`.
Health returned 200 and the admission limit became 3 req/s.

Across the preflight, switching workload and post-switch smoke test, the
gateway captured 90 events: 89 HTTP 200 responses and exactly one HTTP 503.
That rejection was request 85, returned in 0.39 ms with `admission paused`
during the single-replica restart. The switch workload itself completed 79/80;
the post-switch smoke test completed 5/5.

These runs validate control-plane behavior, not a new latency-capacity result:
the switching run intentionally includes planned downtime and the post-switch
sample is too small for an SLO claim.

Artifacts:

- `results/live_gateway_smoke.json`
- `results/live_gateway_switch_80req.json`
- `results/live_gateway_post_switch_smoke.json`
- `results/live_gateway_state_after_switch.json`
- `results/live_gateway_events_after_switch.json`

## Reproduction and shutdown

```bash
export MODEL_PATH=/root/autodl-tmp/models/Qwen2.5-1.5B-Instruct
export TOKENIZER_PATH="$MODEL_PATH"
export VLLM_BIN=/root/autodl-tmp/envs/vllm-autotuner/bin/vllm
export PYTHON_BIN=/root/autodl-tmp/envs/vllm-autotuner/bin/python

bash scripts/gateway_ctl.sh start
bash scripts/gateway_ctl.sh status
curl http://127.0.0.1:8080/controller/state
```

By default this command stops both the gateway and its vLLM backend:

```bash
bash scripts/gateway_ctl.sh stop
```

Verify that no GPU process remains before shutting down the cloud instance:

```bash
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
```

## Limitations exposed by the experiment

- One replica cannot provide zero-downtime changes that require model reload.
  Clients need bounded retries for 503, or the design needs a second replica.
- Rolling controller state is currently in memory; JSONL is an audit log, not
  crash recovery for pending/cooldown state.
- This MVP covers streaming `/v1/completions`, not chat or batch requests.
- The token bucket enforces a measured average with a one-second burst budget;
  it is not a distributed global rate limiter.
- Startup-failure rollback is deterministically fault-injected in tests rather
  than deliberately crashing the paid live GPU process.
