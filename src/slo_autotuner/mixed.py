"""Utilities for deterministic mixed-class serving experiments."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class RequestClass:
    """One traffic class with a request shape and independent latency SLO."""

    name: str
    weight: float
    input_tokens: int
    output_tokens: int
    ttft_slo_ms: float
    e2el_slo_ms: float
    priority: int = 0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RequestClass":
        request_class = cls(
            name=str(payload["name"]),
            weight=float(payload["weight"]),
            input_tokens=int(payload["input_tokens"]),
            output_tokens=int(payload["output_tokens"]),
            ttft_slo_ms=float(payload["ttft_slo_ms"]),
            e2el_slo_ms=float(payload["e2el_slo_ms"]),
            priority=int(payload.get("priority", 0)),
        )
        request_class.validate()
        return request_class

    def validate(self) -> None:
        if not self.name:
            raise ValueError("request class name cannot be empty")
        if self.weight <= 0:
            raise ValueError(f"{self.name}: weight must be positive")
        if self.input_tokens <= 0 or self.output_tokens <= 0:
            raise ValueError(f"{self.name}: token counts must be positive")
        if self.ttft_slo_ms <= 0 or self.e2el_slo_ms <= 0:
            raise ValueError(f"{self.name}: SLOs must be positive")


def load_request_classes(path: Path) -> tuple[RequestClass, ...]:
    """Load and validate the class list in a mixed-workload manifest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    request_classes = tuple(
        RequestClass.from_mapping(item) for item in payload["classes"]
    )
    if not request_classes:
        raise ValueError("mixed workload must contain at least one class")
    names = [item.name for item in request_classes]
    if len(names) != len(set(names)):
        raise ValueError("request class names must be unique")
    return request_classes


def allocate_request_classes(
    request_classes: Sequence[RequestClass],
    num_requests: int,
    seed: int,
) -> list[RequestClass]:
    """Allocate exact weighted counts, then deterministically shuffle them.

    Exact allocation avoids class-count drift between paired scheduler trials.
    The largest-remainder method also guarantees the total is num_requests.
    """
    if num_requests <= 0:
        raise ValueError("num_requests must be positive")
    if not request_classes:
        raise ValueError("request_classes cannot be empty")

    total_weight = sum(item.weight for item in request_classes)
    quotas = [num_requests * item.weight / total_weight for item in request_classes]
    counts = [math.floor(quota) for quota in quotas]
    remaining = num_requests - sum(counts)
    remainder_order = sorted(
        range(len(request_classes)),
        key=lambda index: (quotas[index] - counts[index], -index),
        reverse=True,
    )
    for index in remainder_order[:remaining]:
        counts[index] += 1

    plan = [
        request_class
        for request_class, count in zip(request_classes, counts)
        for _ in range(count)
    ]
    random.Random(seed).shuffle(plan)
    return plan


def poisson_arrival_offsets(
    num_requests: int,
    request_rate: float,
    seed: int,
) -> list[float]:
    """Return deterministic open-loop arrival offsets in seconds."""
    if num_requests <= 0:
        raise ValueError("num_requests must be positive")
    if request_rate <= 0 or not math.isfinite(request_rate):
        raise ValueError("request_rate must be a finite positive number")

    rng = random.Random(seed)
    offsets = [0.0]
    for _ in range(1, num_requests):
        offsets.append(offsets[-1] + rng.expovariate(request_rate))
    return offsets


def percentile(values: Iterable[float], quantile: float) -> float | None:
    """Compute a linearly interpolated percentile without NumPy."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def completion_event_has_token(event: Mapping[str, Any]) -> bool:
    """Detect generation even when a special token has no visible text."""
    choices = event.get("choices", [])
    if not choices:
        return False
    first_choice = choices[0]
    return bool(first_choice.get("token_ids")) or bool(first_choice.get("text"))


def summarize_records(
    records: Sequence[Mapping[str, Any]],
    request_classes: Sequence[RequestClass],
    duration_s: float,
) -> dict[str, Any]:
    """Summarize latency and compliance globally and independently by class."""
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")

    class_summaries: dict[str, dict[str, Any]] = {}
    total_compliant = 0
    for request_class in request_classes:
        class_records = [
            record
            for record in records
            if record["class_name"] == request_class.name
        ]
        completed = [
            record for record in class_records if record.get("error") is None
        ]
        compliant = [
            record
            for record in completed
            if float(record["ttft_ms"]) <= request_class.ttft_slo_ms
            and float(record["e2el_ms"]) <= request_class.e2el_slo_ms
        ]
        total_compliant += len(compliant)
        ttfts = [float(record["ttft_ms"]) for record in completed]
        e2els = [float(record["e2el_ms"]) for record in completed]
        p99_ttft = percentile(ttfts, 0.99)
        p99_e2el = percentile(e2els, 0.99)
        failed = len(class_records) - len(completed)
        meets_slo = (
            bool(completed)
            and failed == 0
            and p99_ttft is not None
            and p99_e2el is not None
            and p99_ttft <= request_class.ttft_slo_ms
            and p99_e2el <= request_class.e2el_slo_ms
        )
        class_summaries[request_class.name] = {
            "weight": request_class.weight,
            "input_tokens": request_class.input_tokens,
            "output_tokens": request_class.output_tokens,
            "ttft_slo_ms": request_class.ttft_slo_ms,
            "e2el_slo_ms": request_class.e2el_slo_ms,
            "attempted": len(class_records),
            "completed": len(completed),
            "failed": failed,
            "slo_compliant": len(compliant),
            "slo_violations": len(class_records) - len(compliant),
            "compliance_rate": (
                len(compliant) / len(class_records) if class_records else 0.0
            ),
            "goodput_rps": len(compliant) / duration_s,
            "p50_ttft_ms": percentile(ttfts, 0.50),
            "p95_ttft_ms": percentile(ttfts, 0.95),
            "p99_ttft_ms": p99_ttft,
            "p50_e2el_ms": percentile(e2els, 0.50),
            "p95_e2el_ms": percentile(e2els, 0.95),
            "p99_e2el_ms": p99_e2el,
            "window_meets_slo": meets_slo,
        }

    completed_count = sum(record.get("error") is None for record in records)
    return {
        "attempted": len(records),
        "completed": completed_count,
        "failed": len(records) - completed_count,
        "request_throughput": completed_count / duration_s,
        "request_goodput": total_compliant / duration_s,
        "request_compliance_rate": (
            total_compliant / len(records) if records else 0.0
        ),
        "all_classes_meet_slo": all(
            summary["window_meets_slo"] for summary in class_summaries.values()
        ),
        "classes": class_summaries,
    }
