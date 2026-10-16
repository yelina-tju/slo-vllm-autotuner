#!/usr/bin/env python3
"""Validate one resumable capacity result and exit 0=pass, 1=valid fail, 2=invalid."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def validate(args: argparse.Namespace) -> bool:
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    server = payload["server"]
    if (
        payload["model"] != args.model
        or int(payload["seed"]) != args.seed
        or not math.isclose(float(payload["request_rate"]), args.rate)
        or str(server["max_num_batched_tokens"]) != str(args.mbt)
        or str(server["max_num_seqs"]) != "256"
        or server["scheduling_policy"] != "fcfs"
        or server["prefix_caching"] != "false"
        or int(payload["attempted"]) != args.num_prompts
        or int(payload["completed"]) + int(payload["failed"]) != args.num_prompts
    ):
        raise ValueError("capacity result metadata does not match the frozen run")
    return bool(payload["all_classes_meet_slo"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--mbt", type=int, required=True)
    parser.add_argument("--num-prompts", type=int, required=True)
    args = parser.parse_args()
    try:
        passed = validate(args)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"invalid: {exc}")
        return 2
    print("pass" if passed else "slo_fail")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
