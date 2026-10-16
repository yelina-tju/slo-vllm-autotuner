#!/usr/bin/env python3
"""Run the live adaptive gateway in front of one local vLLM server."""

from __future__ import annotations

import argparse
from pathlib import Path

from aiohttp import web
from transformers import AutoTokenizer

from slo_autotuner.controller import (
    AdaptiveServingController,
    ControllerConfig,
    RollingWorkloadDetector,
    load_policy_catalog,
)
from slo_autotuner.executor import AdmissionGate, PolicyExecutor, ShellServerLifecycle
from slo_autotuner.gateway import GatewayRuntime, create_gateway_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_runtime(args: argparse.Namespace) -> GatewayRuntime:
    config = ControllerConfig.from_json(args.controller_config)
    catalog = load_policy_catalog(
        args.workload_policy,
        args.workload_profiles,
        args.mixed_policy,
        config.mixed_profile_name,
        config.default_max_num_seqs,
    )
    detector = RollingWorkloadDetector(
        config.rolling_window_seconds,
        config.minimum_samples,
        config.shape_prototypes,
        config.profile_distributions,
    )
    controller = AdaptiveServingController(config, catalog, detector)
    if args.initial_policy is not None:
        controller.force_active_policy(args.initial_policy, 0.0, 0.0)
    gate = AdmissionGate(
        controller.active_policy.admission_limit_rps,
        burst_seconds=args.admission_burst_seconds,
    )
    lifecycle = ShellServerLifecycle(
        project_root=args.project_root,
        model_path=args.model_path,
        vllm_bin=args.vllm_bin,
        health_url=f"{args.backend_url.rstrip('/')}/health",
        poll_interval_s=args.health_poll_interval_s,
        warmup_requests_per_shape=args.warmup_requests_per_shape,
        served_model_name=args.served_model_name,
    )
    executor = PolicyExecutor(
        controller,
        controller.catalog,
        gate,
        lifecycle,
        drain_timeout_s=args.drain_timeout_s,
        startup_timeout_s=args.startup_timeout_s,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer_path,
        local_files_only=True,
        trust_remote_code=False,
    )
    return GatewayRuntime(
        controller,
        gate,
        executor,
        tokenizer,
        backend_base_url=args.backend_url,
        backend_request_timeout_s=args.backend_request_timeout_s,
        startup_timeout_s=args.startup_timeout_s,
        ensure_backend=args.ensure_backend,
        adopt_existing_backend=args.adopt_existing_backend,
        audit_path=args.audit_path,
        adaptive_enabled=args.adaptive,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--initial-policy", default=None)
    parser.add_argument("--adaptive", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--controller-config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "controller.json",
    )
    parser.add_argument(
        "--workload-policy",
        type=Path,
        default=PROJECT_ROOT / "results" / "workload_policy.json",
    )
    parser.add_argument(
        "--workload-profiles",
        type=Path,
        default=PROJECT_ROOT / "configs" / "workload_profiles.json",
    )
    parser.add_argument(
        "--mixed-policy",
        type=Path,
        default=PROJECT_ROOT / "results" / "mixed_policy.json",
    )
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--tokenizer-path", type=Path, required=True)
    parser.add_argument("--served-model-name", default="qwen2.5-1.5b")
    parser.add_argument("--vllm-bin", type=Path, required=True)
    parser.add_argument("--admission-burst-seconds", type=float, default=1.0)
    parser.add_argument("--drain-timeout-s", type=float, default=120.0)
    parser.add_argument("--startup-timeout-s", type=float, default=180.0)
    parser.add_argument("--backend-request-timeout-s", type=float, default=180.0)
    parser.add_argument("--health-poll-interval-s", type=float, default=1.0)
    parser.add_argument("--warmup-requests-per-shape", type=int, default=4)
    parser.add_argument(
        "--ensure-backend",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--adopt-existing-backend",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Trust an already-healthy backend as the default policy.",
    )
    parser.add_argument(
        "--audit-path",
        type=Path,
        default=PROJECT_ROOT / "results" / "gateway_audit.jsonl",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    runtime = build_runtime(args)
    web.run_app(
        create_gateway_app(runtime),
        host=args.host,
        port=args.port,
        print=lambda message: print(message, flush=True),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
