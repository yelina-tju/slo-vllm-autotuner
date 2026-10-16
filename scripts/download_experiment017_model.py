#!/usr/bin/env python3
"""Resumably download and validate the preregistered Experiment 017 model."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil


DEFAULT_REPO = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_DESTINATION = Path(os.environ.get('MODEL_PATH', 'models/Qwen2.5-7B-Instruct'))
MINIMUM_FREE_BYTES = 20 * 1024**3


def validate_model(directory: Path) -> dict:
    config_path = directory / "config.json"
    if not config_path.is_file():
        raise ValueError(f"missing model config: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    weights = sorted(directory.glob("*.safetensors"))
    if not weights or any(path.stat().st_size == 0 for path in weights):
        raise ValueError(f"missing or empty safetensors weights in {directory}")
    index = directory / "model.safetensors.index.json"
    if len(weights) > 1 and not index.is_file():
        raise ValueError("sharded model is missing model.safetensors.index.json")
    return {
        "model_type": config.get("model_type"),
        "architectures": config.get("architectures"),
        "num_hidden_layers": config.get("num_hidden_layers"),
        "weight_files": [path.name for path in weights],
        "weight_bytes": sum(path.stat().st_size for path in weights),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    args = parser.parse_args()

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(args.destination.parent).free
    if free_bytes < MINIMUM_FREE_BYTES:
        raise RuntimeError(
            f"refusing download with only {free_bytes / 1024**3:.2f} GiB free; "
            f"at least {MINIMUM_FREE_BYTES / 1024**3:.0f} GiB is required"
        )

    # huggingface_hub reads HF_ENDPOINT during import.
    os.environ["HF_ENDPOINT"] = args.endpoint
    # Public weights on some mirrors advertise Xet CAS objects whose anonymous
    # reconstruction endpoint returns 401. Plain HTTP is slower but portable
    # and retains huggingface_hub's resumable cache semantics.
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    from huggingface_hub import snapshot_download

    print(
        f"downloading repo={args.repo_id} destination={args.destination} "
        f"free_before_gib={free_bytes / 1024**3:.2f}",
        flush=True,
    )
    snapshot_download(
        repo_id=args.repo_id,
        local_dir=args.destination,
        ignore_patterns=["*.bin", "*.h5", "*.msgpack", "*.ot"],
        max_workers=4,
    )
    identity = validate_model(args.destination)
    free_after = shutil.disk_usage(args.destination.parent).free
    print(json.dumps(identity, indent=2, ensure_ascii=False), flush=True)
    print(f"free_after_gib={free_after / 1024**3:.2f}", flush=True)
    print("EXPERIMENT017_MODEL_DOWNLOAD_COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
