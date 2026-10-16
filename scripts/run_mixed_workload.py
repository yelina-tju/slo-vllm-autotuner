#!/usr/bin/env python3
"""Run deterministic Poisson traffic with multiple request/SLO classes."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import time
from typing import Any

import aiohttp
from transformers import AutoTokenizer

from slo_autotuner.mixed import (
    RequestClass,
    allocate_request_classes,
    completion_event_has_token,
    load_request_classes,
    poisson_arrival_offsets,
    summarize_records,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_token_population(tokenizer: Any) -> tuple[int, ...]:
    """Use ordinary vocabulary IDs so prompt length is exact and reproducible."""
    special_ids = set(tokenizer.all_special_ids)
    population = tuple(
        token_id
        for token_id in range(tokenizer.vocab_size)
        if token_id not in special_ids
    )
    if not population:
        raise ValueError("tokenizer has no non-special token IDs")
    return population


def build_payload(
    model: str,
    request_class: RequestClass,
    population: tuple[int, ...],
    rng: random.Random,
    use_class_priority: bool,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": rng.choices(population, k=request_class.input_tokens),
        "max_tokens": request_class.output_tokens,
        "temperature": 0.0,
        "ignore_eos": True,
        "return_token_ids": True,
        "stream": True,
    }
    if use_class_priority:
        payload["priority"] = request_class.priority
    return payload


async def issue_request(
    session: aiohttp.ClientSession,
    endpoint: str,
    request_id: int,
    request_class: RequestClass,
    payload: dict[str, Any],
    benchmark_start: float,
    scheduled_offset_s: float,
) -> dict[str, Any]:
    scheduled_at = benchmark_start + scheduled_offset_s
    await asyncio.sleep(max(0.0, scheduled_at - time.perf_counter()))
    dispatched_at = time.perf_counter()
    first_token_at: float | None = None
    status_code: int | None = None
    error: str | None = None

    try:
        async with session.post(endpoint, json=payload) as response:
            status_code = response.status
            if response.status != 200:
                body = (await response.text())[:500]
                raise RuntimeError(f"HTTP {response.status}: {body}")
            async for raw_line in response.content:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if first_token_at is None and completion_event_has_token(event):
                    first_token_at = time.perf_counter()
            if first_token_at is None:
                raise RuntimeError("stream completed without a non-empty token")
    except Exception as exc:  # Keep the full benchmark alive after one failure.
        error = f"{type(exc).__name__}: {exc}"

    completed_at = time.perf_counter()
    return {
        "request_id": request_id,
        "class_name": request_class.name,
        "input_tokens": request_class.input_tokens,
        "requested_output_tokens": request_class.output_tokens,
        "scheduled_offset_s": scheduled_offset_s,
        "dispatch_offset_s": dispatched_at - benchmark_start,
        "client_launch_delay_ms": max(0.0, dispatched_at - scheduled_at) * 1000,
        "ttft_ms": (
            (first_token_at - dispatched_at) * 1000
            if first_token_at is not None
            else None
        ),
        "e2el_ms": (completed_at - dispatched_at) * 1000,
        "status_code": status_code,
        "error": error,
    }


async def warm_up(
    session: aiohttp.ClientSession,
    endpoint: str,
    model: str,
    request_classes: tuple[RequestClass, ...],
    population: tuple[int, ...],
    rng: random.Random,
    warmup_per_class: int,
    use_class_priority: bool,
) -> None:
    for request_class in request_classes:
        for warmup_index in range(warmup_per_class):
            started = time.perf_counter()
            record = await issue_request(
                session=session,
                endpoint=endpoint,
                request_id=-(warmup_index + 1),
                request_class=request_class,
                payload=build_payload(
                    model,
                    request_class,
                    population,
                    rng,
                    use_class_priority,
                ),
                benchmark_start=started,
                scheduled_offset_s=0.0,
            )
            if record["error"] is not None:
                raise RuntimeError(
                    f"warmup failed for {request_class.name}: {record['error']}"
                )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    request_classes = load_request_classes(args.config)
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer,
        local_files_only=True,
        trust_remote_code=False,
    )
    population = build_token_population(tokenizer)
    class_plan = allocate_request_classes(
        request_classes, args.num_prompts, args.seed
    )
    arrival_offsets = poisson_arrival_offsets(
        args.num_prompts, args.request_rate, args.seed + 1
    )
    prompt_rng = random.Random(args.seed + 2)
    payloads = [
        build_payload(
            args.model,
            request_class,
            population,
            prompt_rng,
            args.use_class_priority,
        )
        for request_class in class_plan
    ]

    timeout = aiohttp.ClientTimeout(total=args.request_timeout_s)
    connector = aiohttp.TCPConnector(limit=0)
    endpoint = f"{args.base_url.rstrip('/')}/v1/completions"
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        await warm_up(
            session,
            endpoint,
            args.model,
            request_classes,
            population,
            prompt_rng,
            args.warmup_per_class,
            args.use_class_priority,
        )
        benchmark_start = time.perf_counter()
        tasks = [
            asyncio.create_task(
                issue_request(
                    session=session,
                    endpoint=endpoint,
                    request_id=request_id,
                    request_class=request_class,
                    payload=payload,
                    benchmark_start=benchmark_start,
                    scheduled_offset_s=scheduled_offset,
                )
            )
            for request_id, (request_class, payload, scheduled_offset) in enumerate(
                zip(class_plan, payloads, arrival_offsets)
            )
        ]
        records = await asyncio.gather(*tasks)
        duration_s = time.perf_counter() - benchmark_start

    summary = summarize_records(records, request_classes, duration_s)
    return {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workload": "mixed_poisson",
        "config_file": str(args.config),
        "request_rate": args.request_rate,
        "num_prompts": args.num_prompts,
        "warmup_per_class": args.warmup_per_class,
        "seed": args.seed,
        "duration": duration_s,
        "model": args.model,
        "tokenizer": str(args.tokenizer),
        "server": {
            "prefix_caching": args.server_prefix_caching,
            "max_num_batched_tokens": args.server_max_num_batched_tokens,
            "max_num_seqs": args.server_max_num_seqs,
            "max_num_partial_prefills": args.server_max_num_partial_prefills,
            "max_long_partial_prefills": args.server_max_long_partial_prefills,
            "long_prefill_token_threshold": args.server_long_prefill_token_threshold,
            "scheduling_policy": args.server_scheduling_policy,
        },
        "class_priority_enabled": args.use_class_priority,
        "class_specs": [asdict(item) for item in request_classes],
        **summary,
        "requests": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "mixed_workload.json",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default="qwen2.5-1.5b")
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--request-rate", type=float, required=True)
    parser.add_argument("--num-prompts", type=int, default=200)
    parser.add_argument("--warmup-per-class", type=int, default=2)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--request-timeout-s", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--server-prefix-caching", default="false")
    parser.add_argument("--server-max-num-batched-tokens", default="unknown")
    parser.add_argument("--server-max-num-seqs", default="unknown")
    parser.add_argument("--server-max-num-partial-prefills", default="unknown")
    parser.add_argument("--server-max-long-partial-prefills", default="unknown")
    parser.add_argument("--server-long-prefill-token-threshold", default="unknown")
    parser.add_argument("--server-scheduling-policy", default="unknown")
    parser.add_argument(
        "--use-class-priority",
        action="store_true",
        help="Send the priority declared by each request class.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.num_prompts <= 0:
        raise SystemExit("--num-prompts must be positive")
    if args.warmup_per_class < 0:
        raise SystemExit("--warmup-per-class cannot be negative")
    payload = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"completed={payload['completed']}/{payload['attempted']} "
        f"throughput={payload['request_throughput']:.2f} req/s "
        f"goodput={payload['request_goodput']:.2f} req/s "
        f"all_classes_meet_slo={payload['all_classes_meet_slo']}"
    )
    for name, summary in payload["classes"].items():
        print(
            f"  {name}: n={summary['completed']} "
            f"P99 TTFT/E2E={summary['p99_ttft_ms']:.2f}/"
            f"{summary['p99_e2el_ms']:.2f} ms "
            f"compliance={summary['compliance_rate']:.1%} "
            f"window_meets_slo={summary['window_meets_slo']}"
        )
    print(f"wrote={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
