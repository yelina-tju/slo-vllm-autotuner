"""Paired, wall-clock workload traces and policy-independent scoring."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

from .mixed import RequestClass, percentile, summarize_records


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_model(path: Path, served_model_name: str) -> dict[str, Any]:
    """Record enough local model identity to keep benchmark evidence separable."""
    resolved = path.resolve()
    identity_files = {}
    for name in ("config.json", "generation_config.json", "tokenizer_config.json"):
        candidate = resolved / name
        if candidate.is_file():
            identity_files[name] = file_sha256(candidate)
    weight_files = sorted(resolved.glob("*.safetensors"))
    if not identity_files or not weight_files:
        raise ValueError(f"model directory is incomplete: {resolved}")
    return {
        "path": str(resolved),
        "served_model_name": served_model_name,
        "identity_file_sha256": identity_files,
        "weight_files": [
            {"name": item.name, "size_bytes": item.stat().st_size}
            for item in weight_files
        ],
        "weight_bytes": sum(item.stat().st_size for item in weight_files),
    }


def build_trace(config: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    """Generate arrivals independently of service and class assignment.

    Unlike a fixed-count run, a phase ends at a predetermined wall-clock time.
    Random class assignment avoids conditioning a Poisson trace on class counts.
    The same materialized trace is reused for every policy.
    """
    seed = int(config["seed"])
    arrivals = random.Random(seed)
    classes = random.Random(seed + 10000)
    trace, phases = [], []
    start = 0.0
    for phase in config["phases"]:
        duration = float(phase["duration_s"])
        rate = float(phase["request_rate"])
        fraction = float(phase["long_fraction"])
        if not all(math.isfinite(v) for v in (duration, rate, fraction)):
            raise ValueError("phase parameters must be finite")
        if duration <= 0 or rate <= 0 or not 0 <= fraction <= 1:
            raise ValueError("invalid phase duration, rate or long fraction")
        end = start + duration
        phases.append({**phase, "start_s": start, "end_s": end})
        offset = start + arrivals.expovariate(rate)
        while offset < end:
            is_long = classes.random() < fraction
            trace.append({
                "request_id": len(trace) + 1,
                "phase": phase["name"],
                "scheduled_offset_s": offset,
                "class_name": "document_long" if is_long else "interactive_short",
                "input_tokens": 2048 if is_long else 256,
                "requested_output_tokens": 64,
                "prompt_seed": seed * 1000000 + len(trace),
            })
            offset += arrivals.expovariate(rate)
        start = end
    if not trace:
        raise ValueError("trace contains no requests")
    return trace, phases


def score_records(
    records: Sequence[Mapping[str, Any]],
    classes: Sequence[RequestClass],
    duration_s: float,
) -> dict:
    active = [c for c in classes if any(r["class_name"] == c.name for r in records)]
    summary = summarize_records(records, active, duration_s)
    summary["status_counts"] = dict(Counter(str(r.get("status_code")) for r in records))
    summary["slo_compliant"] = sum(c["slo_compliant"] for c in summary["classes"].values())
    summary["p99_client_launch_delay_ms"] = percentile(
        (r["client_launch_delay_ms"] for r in records), 0.99,
    )
    summary["backend_or_transport_errors"] = sum(
        r.get("error") is not None and r.get("status_code") not in {429, 503}
        for r in records
    )
    return summary


def score_windows(records: Sequence[Mapping[str, Any]], classes: Sequence[RequestClass],
                  horizon_s: float, window_s: float) -> dict:
    """Nonoverlapping, arrival-cohort windows; rejections remain in goodput.

    Tail exceedance area is computed only for successful requests. Rejection
    counts and windows without successful samples are reported separately.
    This prevents a policy rejecting everything from looking SLO-compliant.
    """
    if window_s <= 0 or horizon_s <= 0:
        raise ValueError("window and horizon must be positive")
    windows = []
    area = 0.0
    unavailable = 0
    for index in range(math.ceil(horizon_s / window_s)):
        start, end = index * window_s, min((index + 1) * window_s, horizon_s)
        selected = [r for r in records if start <= r["scheduled_offset_s"] < end]
        summary = score_records(selected, classes, end - start)
        excess = 0.0
        for spec in summary["classes"].values():
            if spec["completed"] == 0:
                unavailable += 1
                continue
            excess += max(0.0, spec["p99_ttft_ms"] / spec["ttft_slo_ms"] - 1,
                          spec["p99_e2el_ms"] / spec["e2el_slo_ms"] - 1)
        area += excess * (end - start)
        windows.append({"start_s": start, "end_s": end, "tail_excess": excess, **summary})
    return {"windows": windows, "tail_violation_area_s": area,
            "class_windows_without_success": unavailable}
