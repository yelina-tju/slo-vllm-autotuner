#!/usr/bin/env python3
"""Verify paired evidence and export a comparison table and scientific plot.

The plot is optional; it needs matplotlib only in the analysis environment.
No dependency is added to the live serving environment.
"""

import argparse
from collections import Counter
import json
from pathlib import Path


def inspect_rollback_windows(audit, classes, rolling_seconds):
    """Reconstruct overlapping post-transition SLO windows from request audit."""
    limits = {"balanced": next(c for c in classes if c["name"] == "interactive_short"),
              "prefill_heavy": next(c for c in classes if c["name"] == "document_long")}
    requests = [item["payload"] for item in audit if item["kind"] == "request"]
    clear_at = float("-inf")
    findings = []
    previous_bad_ids = set()
    for item in audit:
        data = item["payload"]
        if item["kind"] == "execution":
            clear_at = data["completed_at_s"]
            previous_bad_ids = set()
        if item["kind"] != "decision" or "SLO violation" not in data.get("reason", ""):
            continue
        if data["active_profile"] != "mixed_80_20":
            continue
        now = data["timestamp_s"]
        selected = [r for r in requests if r["admitted"]
                    and max(clear_at, now - rolling_seconds) < r["completed_at_s"] <= now]
        bad = []
        for request in selected:
            spec = limits.get(request["shape"])
            if spec and (not request["success"] or request["ttft_ms"] > spec["ttft_slo_ms"]
                         or request["e2el_ms"] > spec["e2el_slo_ms"]):
                bad.append(request)
        bad_ids = {r["request_id"] for r in bad}
        findings.append({
            "action": data["action"], "timestamp_s": now, "reason": data["reason"],
            "samples_by_shape": dict(Counter(r["shape"] for r in selected)),
            "violating_request_ids": sorted(bad_ids),
            "overlap_with_previous_violation": sorted(bad_ids & previous_bad_ids),
            "violating_requests": bad,
        })
        previous_bad_ids = bad_ids
    return findings


def analyze(directory):
    manifest = json.loads((directory / "trace_manifest.json").read_text(encoding="utf-8"))
    expected_ids = [r["request_id"] for r in manifest["trace"]]
    expected_payloads = [r["payload_sha256"] for r in manifest["trace"]]
    results = []
    for mode in manifest["config"]["modes"]:
        path = directory / mode["name"] / "result.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["run_key"] != manifest["run_key"] or result["status"] != "complete":
            raise ValueError(f"unpaired or incomplete result: {path}")
        if [r["request_id"] for r in result["requests"]] != expected_ids:
            raise ValueError(f"missing or duplicate requests: {path}")
        if [r["payload_sha256"] for r in result["requests"]] != expected_payloads:
            raise ValueError(f"request payloads differ: {path}")
        observed = Counter(str(r["status_code"]) for r in result["requests"])
        if dict(observed) != result["summary"]["status_counts"]:
            raise ValueError(f"inconsistent status counts: {path}")
        # Cross-check the client against the independent gateway audit stream.
        with (path.parent / "gateway_audit.jsonl").open(encoding="utf-8") as stream:
            audit = [json.loads(raw) for raw in stream]
        events = [line["payload"] for line in audit if line["kind"] == "request"]
        gateway_counts = Counter(str(e["status_code"]) for e in events)
        if len(events) != len(expected_ids) or gateway_counts != observed:
            raise ValueError(f"client/gateway request-accounting mismatch: {path}")
        result["accounting_verified"] = True
        result["rollback_windows"] = inspect_rollback_windows(audit, manifest["classes"], 60)
        results.append(result)
    rows = []
    for result in results:
        summary = result["summary"]
        rows.append({
            "mode": result["mode"]["name"],
            "requests": summary["attempted"],
            "slo_compliant": summary["slo_compliant"],
            "goodput_rps": summary["request_goodput"],
            "completion_rate": summary["completed"] / summary["attempted"],
            "slo_compliance_rate": summary["request_compliance_rate"],
            "http_429": summary["status_counts"].get("429", 0),
            "http_503": summary["status_counts"].get("503", 0),
            "backend_or_transport_errors": summary["backend_or_transport_errors"],
            "tail_violations_among_completed": summary["completed"] - summary["slo_compliant"],
            "restarts": result["restart_count"],
            "transition_duration_s": result["transition_duration_s"],
            "tail_violation_area_s": result["tail_violation_area_s"],
            "class_windows_without_success": result["class_windows_without_success"],
            "p99_client_launch_delay_ms": summary["p99_client_launch_delay_ms"],
        })
    indexed = {r["mode"]: r for r in rows}
    adaptive = indexed["adaptive"]
    deltas = {}
    for name in ("static_aggressive", "static_conservative"):
        baseline = indexed[name]
        deltas[name] = {
            "goodput_delta_rps": adaptive["goodput_rps"] - baseline["goodput_rps"],
            "goodput_relative_change": adaptive["goodput_rps"] / baseline["goodput_rps"] - 1,
            "slo_compliant_delta": adaptive["slo_compliant"] - baseline["slo_compliant"],
        }
    return manifest, results, {"run_key": manifest["run_key"], "rows": rows,
                               "adaptive_vs_baseline": deltas,
                               "phase_summaries": {r["mode"]["name"]: r["by_phase"] for r in results},
                               "executions": {r["mode"]["name"]: r["executions"] for r in results},
                               "rollback_windows": {r["mode"]["name"]: r["rollback_windows"] for r in results}}


def plot(directory, manifest, results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    colors = {"static_aggressive": "#d97706", "adaptive": "#2563eb", "static_conservative": "#059669"}
    labels = {"static_aggressive": "Static: mbt2048 / 24 rps",
              "adaptive": "Adaptive controller", "static_conservative": "Static: mbt1024 / 3 rps"}
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True,
                             gridspec_kw={"height_ratios": [1.1, 1, 1]}, layout="constrained")
    for phase in manifest["phases"]:
        for ax in axes:
            ax.axvspan(phase["start_s"], phase["end_s"],
                       color="#e2e8f0" if phase["long_fraction"] else "#f8fafc", zorder=-5)
            ax.axvline(phase["start_s"], color="#94a3b8", lw=0.7)
        axes[0].text((phase["start_s"] + phase["end_s"]) / 2, 1.03,
                     f"{'80/20 mixed' if phase['long_fraction'] else 'Short only'} / {phase['request_rate']:g} rps",
                     ha="center", transform=axes[0].get_xaxis_transform(), fontsize=10)
    for result in results:
        mode = result["mode"]["name"]
        windows = result["windows"]
        edges = [w["start_s"] for w in windows] + [windows[-1]["end_s"]]
        axes[0].stairs([w["request_goodput"] for w in windows], edges,
                       label=labels[mode], color=colors[mode], lw=2, baseline=None)
        axes[1].stairs([1 - w["request_compliance_rate"] for w in windows], edges,
                       color=colors[mode], lw=2, baseline=None)
    adaptive = next(r for r in results if r["mode"]["name"] == "adaptive")
    with (directory / "adaptive" / "state_samples.jsonl").open(encoding="utf-8") as stream:
        states = [json.loads(line) for line in stream]
    axes[2].step([s["offset_s"] for s in states], [s["admission"]["rate_limit_rps"] for s in states],
                 where="post", color=colors["adaptive"], lw=2, label="Adaptive admission limit")
    for phase in manifest["phases"]:
        axes[2].plot([phase["start_s"], phase["end_s"]], [phase["request_rate"]] * 2,
                     color="#475569", ls="--", lw=1.3,
                     label="Planned offered rate" if phase == manifest["phases"][0] else None)
    for event in adaptive["executions"]:
        axes[2].axvspan(event["started_offset_s"], event["completed_offset_s"],
                       color="#ef4444", alpha=0.24)
        axes[2].text((event["started_offset_s"] + event["completed_offset_s"]) / 2,
                     12, f"{event['action']}\n{event['duration_s']:.1f}s",
                     fontsize=9, ha="center", color="#991b1b")
    axes[0].set_ylabel("SLO-compliant requests / s")
    axes[0].legend(loc="upper right", fontsize=9, framealpha=0.95)
    axes[1].set_ylabel("Fraction not meeting SLO\n(including 429 / 503)")
    axes[1].set_ylim(-0.02, 1.02)
    axes[2].set_ylabel("Requests / s")
    axes[2].set_xlabel("Seconds since trace start; fixed 30-second arrival-cohort windows")
    handles, legend_labels = axes[2].get_legend_handles_labels()
    axes[2].legend(handles + [Patch(facecolor="#ef4444", alpha=0.24)],
                    legend_labels + ["Admission paused during transition"], fontsize=9, loc="upper right")
    for ax in axes:
        ax.set_xlim(0, manifest["phases"][-1]["end_s"])
        ax.grid(axis="y", alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Experiment 008: identical planned workload, different serving policies\n"
                 f"RTX 4090 D | Qwen2.5-1.5B | seed {manifest['config']['seed']} | single-run pilot", fontsize=14)
    fig.savefig(directory / "comparison.png", dpi=170)
    fig.savefig(directory / "comparison.svg")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--inspect-rollback", action="store_true")
    args = parser.parse_args()
    if args.inspect_rollback:
        manifest = json.loads((args.directory / "trace_manifest.json").read_text(encoding="utf-8"))
        with (args.directory / "adaptive" / "gateway_audit.jsonl").open(encoding="utf-8") as stream:
            audit = [json.loads(line) for line in stream]
        print(json.dumps(inspect_rollback_windows(audit, manifest["classes"], 60), indent=2))
        raise SystemExit(0)
    manifest, results, summary = analyze(args.directory)
    (args.directory / "analysis.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"phase_summaries", "executions", "rollback_windows"}}, indent=2))
    if args.plot:
        plot(args.directory, manifest, results)
