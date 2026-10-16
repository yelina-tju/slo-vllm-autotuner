"""Preview/audit by default; --execute explicitly runs only four remaining cases."""
import argparse
import asyncio
import json
from pathlib import Path
from audit_alignment_pairs import require
from audit_recovery import read, sha
from recovery_continuation import prepare


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('prefix', 'prefix-snapshot', 'calibration'):
        parser.add_argument('--'+key, type=Path, required=True)
    for key in ('source', 'model', 'vllm', 'output'):
        parser.add_argument('--'+key, type=Path)
    parser.add_argument('--port', type=int, default=8031)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('invalid port')
    context, traces = prepare(args.prefix, args.prefix_snapshot, args.calibration, Path(__file__).parent)
    print(json.dumps(dict(link=context['link'], counts={s: len(t) for s, t in traces.items()}), indent=2), flush=True)
    if args.execute:
        if any(getattr(args, k) is None for k in ('source', 'model', 'vllm', 'output')):
            parser.error('execution requires all paths')
        previous = read(args.prefix/'manifest.json')
        require(sha(args.source/'configs/workload_profiles.json') == previous['profile_sha256'], 'SLO changed')
        require({name: sha(args.source/'src/slo_autotuner'/name) for name in previous['frozen_dependencies']}
                == previous['frozen_dependencies'], 'V1 dependencies changed')
        old_backend = read(args.prefix/'seed309-low/backend/manifest.json')
        require(sha(args.model/'config.json') == old_backend['model_config_sha256'], 'model changed')
        from run_recovery import entry
        asyncio.run(entry(args, traces, context))
