"""Resolve user-supplied GPU paths before creating any experiment output."""
import os
from pathlib import Path
import shutil


def gpu_paths():
    model = os.environ.get('MODEL_PATH')
    if not model or not Path(model).is_dir():
        raise ValueError('Set MODEL_PATH to an existing local model directory')
    executable = shutil.which(os.environ.get('VLLM_BIN', 'vllm'))
    if executable is None:
        raise ValueError('Set VLLM_BIN to an executable vllm installation')
    return Path(model).resolve(), Path(executable).resolve()
