"""CPU-only lifecycle contract tests; fake transport, no HTTP/GPU or model outcomes."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from guarded_protocol import CONFIG, plan
from run_guarded_recovery import execute


class Session:
    def __init__(self, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


def save(path, value):
    with path.open('x') as stream: json.dump(value, stream)


class GuardedRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, fail=False, exists=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, calibration, output = root/'source', root/'calibration', root/'output'
            (source/'configs').mkdir(parents=True)
            (source/'src/slo_autotuner').mkdir(parents=True)
            calibration.mkdir()
            for name in ('executor.py', 'gateway.py', 'controller.py', 'mixed.py'):
                (source/'src/slo_autotuner'/name).write_text('# synthetic')
            save(source/CONFIG['slo_source'], dict(profiles=[dict(name='balanced', input_tokens=256,
                 output_tokens=64, ttft_slo_ms=100, e2el_slo_ms=400)]))
            save(calibration/'report.json', dict(status='passed', selection=dict(status='candidate_found', low_rate=24, high_rate=48)))
            if exists: output.mkdir()
            calls = []

            class Backend:
                def __init__(self, args): self.args, self.url = args, 'fake://no-network'
                async def __aenter__(self):
                    calls.append(self.args.output.parent.name)
                    if fail: raise RuntimeError('synthetic startup failure')
                    self.args.output.mkdir()
                    return self
                async def __aexit__(self, *args): save(self.args.output/'cleanup.json', dict(stopped=True))

            async def warmup(*args): return [dict(token=True, done=True, status=200)]*4
            async def sample(session, url, path, stop): await stop.wait()
            async def mode(mode, cfg, profile, arrivals, duration, *args):
                self.assertEqual(duration, 260)
                self.assertIn(cfg['seed'], (403, 404))
                return dict(valid_plumbing=True)
            def analyze(folder, trace, seed, arm):
                return dict(seed=seed, arm=arm, before_healthy=True, low_anchor_reproduced=True,
                            high_anchor_reproduced=True, recovery=dict(recovered=True),
                            actions=[], goodput=0, rejections=0, completed_slo_violations=0)
            modules = dict(aiohttp=SimpleNamespace(ClientSession=Session, ClientTimeout=lambda **k: None,
                                                   TCPConnector=lambda **k: None),
                           owned_backend=SimpleNamespace(OwnedBackend=Backend, save=save),
                           run_alignment_pairs=SimpleNamespace(warmup=warmup),
                           run_pilot=SimpleNamespace(one_mode=mode),
                           run_pressure_calibration=SimpleNamespace(collect_queue=sample))
            args = SimpleNamespace(source=source, calibration=calibration, output=output,
                                   model=root/'model', vllm=root/'vllm', port=8031)
            with patch.dict('sys.modules', modules), patch('run_guarded_recovery.analyze_case', side_effect=analyze):
                if exists:
                    with self.assertRaises(FileExistsError): await execute(args, {403: [], 404: []}, {})
                    self.assertEqual(calls, [])
                    return
                if fail:
                    with self.assertRaisesRegex(RuntimeError, 'synthetic'): await execute(args, {403: [], 404: []}, {})
                else:
                    await execute(args, {403: [], 404: []}, {})
            report = json.loads((output/'report.json').read_text())
            self.assertEqual(report['status'], 'failed' if fail else 'passed')
            self.assertEqual(len(report['completed']), 0 if fail else 6)
            self.assertEqual(calls, ['seed403-low'] if fail else [f'seed{x["seed"]}-{x["arm"]}' for x in plan()])
            self.assertEqual(len(list(output.glob('checkpoint-*.json'))), 0 if fail else 6)

    async def test_complete_order_and_260_seconds(self): await self.exercise()
    async def test_failure_is_preserved_without_retry(self): await self.exercise(fail=True)
    async def test_existing_output_refused_before_backend(self): await self.exercise(exists=True)


if __name__ == '__main__': unittest.main()
