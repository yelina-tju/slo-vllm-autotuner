import asyncio
import time
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
import aiohttp
from aiohttp import web
from cohorts import ArrivalCohorts
from deadline_cohorts import DeadlineCohorts
from feedback import Feedback, Config
from hot_gate import HotAdmissionGate
from transport import StreamingPilot


class TransportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def backend(request):
            data = await request.json()
            if data.get('expect_tag') and request.headers.get('X-Request-Id') != data['expect_tag']:
                return web.Response(status=400)
            response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
            await response.prepare(request)
            if data.get('stall'):
                await asyncio.sleep(.2)
                return response
            await response.write(b'data: {"choices":[{"text":"hi"}]}\n\n')
            if not data.get('truncated'):
                await response.write(b'data: [DONE]\n\n')
            return response
        app = web.Application()
        app.router.add_post('/completions', backend)
        app.router.add_post('/v1/completions', backend)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f'http://127.0.0.1:{port}/completions'
        self.session = aiohttp.ClientSession()

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    def pilot(self, timeout=1):
        gate = HotAdmissionGate(3)
        f = Feedback(['short'], Config(settle_seconds=0))
        cohorts = ArrivalCohorts({'short': (1000, 1000)}, origin=time.monotonic(), width=.01, timeout=timeout)
        return StreamingPilot(SimpleNamespace(_lock=asyncio.Lock(), admission_gate=gate), f, cohorts)

    async def test_real_http_sse_success_and_release(self):
        p = self.pilot()
        r = await p.request(self.session, self.url, {}, 'short')
        self.assertTrue(r['success'])
        self.assertEqual(p.executor.admission_gate.in_flight, 0)
        self.assertEqual(p.cohorts.requests[1]['state'], 'success')

    async def test_request_tag_reaches_backend(self):
        p = self.pilot()
        r = await p.request(self.session, self.url, {'expect_tag': 'proof-1'}, 'short', request_tag='proof-1')
        self.assertTrue(r['success'])

    async def test_stall_closes_client_and_decreases_without_large_sample(self):
        p = self.pilot(timeout=.04)
        r = await p.request(self.session, self.url, {'stall': True}, 'short')
        self.assertEqual(r['error'], 'TimeoutError')
        self.assertEqual(p.executor.admission_gate.in_flight, 0)
        self.assertEqual(p.cohorts.requests[1]['state'], 'timeout')
        records = await p.tick()
        actions = [r for r in records if r['decision'].action == 'decrease']
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0]['applied'])
        self.assertAlmostEqual(p.feedback.rate, 2.1)

    async def test_truncated_and_paused_are_distinct(self):
        p = self.pilot()
        r = await p.request(self.session, self.url, {'truncated': True}, 'short')
        self.assertFalse(r['success'])
        self.assertEqual(p.cohorts.requests[1]['state'], 'failure')
        await p.executor.admission_gate.pause()
        r = await p.request(self.session, self.url, {}, 'short')
        self.assertEqual((r['status'], r['admitted']), (503, False))
        self.assertEqual(p.cohorts.requests[2]['state'], 'rejected')

    async def test_external_cancellation_releases_admission(self):
        p = self.pilot()
        task = asyncio.create_task(p.request(self.session, self.url, {'stall': True}, 'short'))
        await asyncio.sleep(.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(p.executor.admission_gate.in_flight, 0)
        self.assertEqual(p.cohorts.requests[1]['state'], 'failure')

    async def test_http_evidence_applies_growth_once(self):
        p = self.pilot()
        # Test-only thresholds: not proposed GPU calibration settings.
        p.feedback.config = Config(minimum_samples=1, confirmations=1,
                                   demand_fraction=.01, settle_seconds=0)
        await p.request(self.session, self.url, {}, 'short')
        await asyncio.sleep(.015)
        batches = await asyncio.gather(p.tick(), p.tick())
        growth = [r for batch in batches for r in batch if r['decision'].action == 'increase']
        self.assertEqual(len(growth), 1)
        self.assertTrue(growth[0]['applied'])
        self.assertEqual(p.executor.admission_gate.rate_limit_rps, 4)
        self.assertEqual(p.feedback.revision, 1)

    async def test_bounded_driver_writes_complete_request_accounting(self):
        from run_pilot import one_mode
        cfg = dict(model_name='fake', feedback={}, cohort_seconds=.04,
                   request_timeout_seconds=1, tick_seconds=.005,
                   max_pending_tasks=8, max_dispatch_lag_seconds=.5)
        profile = dict(name='short', input_tokens=8, output_tokens=1,
                       ttft_slo_ms=1000, e2el_slo_ms=1000)
        arrivals = [dict(at=.01, prompt_seed=1), dict(at=.05, prompt_seed=2)]
        with tempfile.TemporaryDirectory() as directory:
            # Driver uses /v1/completions; register that route in setup too.
            summary = await one_mode('fixed', cfg, profile, arrivals, .08,
                                     self.session, self.url.removesuffix('/completions'), Path(directory))
            self.assertTrue(summary['valid_plumbing'])
            self.assertGreater(summary['successes'], 0)
            self.assertEqual(summary['requests'], 2)
            self.assertEqual(len((Path(directory)/'fixed/requests.jsonl').read_text().splitlines()), 2)

    async def test_finalization_after_deadline_never_promotes(self):
        p = self.pilot()
        p.feedback.config = Config(minimum_samples=1, confirmations=1,
                                   demand_fraction=.01, settle_seconds=0)
        await p.request(self.session, self.url, {}, 'short')
        await asyncio.sleep(.015)
        records = await p.tick(actuation_deadline=time.monotonic())
        self.assertTrue(records)
        self.assertTrue(all(r['decision'].reason == 'drain_only' for r in records))
        self.assertEqual(p.feedback.rate, 3)
        self.assertEqual(p.feedback.revision, 0)

    async def test_http_ack_reanchors_without_losing_accounting(self):
        p = self.pilot()
        p.cohorts = DeadlineCohorts({'short': (1000, 1000)}, origin=time.monotonic(), width=.01, timeout=1)
        p.feedback.config = Config(minimum_samples=1, confirmations=1, demand_fraction=.01, settle_seconds=.02)
        response = await p.request(self.session, self.url, {}, 'short')
        await asyncio.sleep(.015)
        records = await p.tick()
        self.assertEqual(sum(bool(r['applied']) for r in records), 1)
        self.assertEqual(p.cohorts.epoch, 1)
        self.assertEqual(p.cohorts.evidence_ready, p.feedback.ready_at)
        self.assertEqual(p.cohorts.lane.origin, p.feedback.ready_at)
        self.assertEqual(p.cohorts.requests[response['request_id']]['state'], 'success')
        self.assertEqual(response['admission_revision'], 0)
        self.assertEqual(response['evidence_epoch'], 0)
        self.assertEqual(sum(r['audit']['offered'] for r in records if r['audit']['purpose'] == 'accounting'), 1)

    async def test_failed_update_reanchors_same_revision(self):
        p = self.pilot()
        p.cohorts = DeadlineCohorts({'short': (1000, 1000)}, origin=time.monotonic(), width=.01, timeout=1)
        p.feedback.config = Config(minimum_samples=1, confirmations=1, demand_fraction=.01, settle_seconds=.02)
        await p.request(self.session, self.url, {}, 'short')
        await p.executor.admission_gate.pause()
        await asyncio.sleep(.015)
        records = await p.tick()
        proposals = [r for r in records if r['applied'] is not None]
        self.assertEqual(len(proposals), 1)
        self.assertFalse(proposals[0]['applied'])
        self.assertEqual(p.cohorts.epoch, 1)
        self.assertEqual(p.cohorts.evidence_revision, 0)
        self.assertEqual(p.feedback.rate, 3)
        self.assertTrue(p.executor.admission_gate.paused)

    async def test_both_pair_modes_pass_per_request_membership_audit(self):
        from dataclasses import asdict
        from run_pilot import one_mode
        from audit_alignment_pairs import audit_mode
        cfg = dict(model_name='fake', feedback=asdict(Config(minimum_samples=1, confirmations=1,
                   demand_fraction=.01, settle_seconds=.02)), cohort_seconds=.02,
                   request_timeout_seconds=1, tick_seconds=.005,
                   max_pending_tasks=8, max_dispatch_lag_seconds=.5)
        profile = dict(name='short', input_tokens=8, output_tokens=1, ttft_slo_ms=1000, e2el_slo_ms=1000)
        arrivals = [dict(at=.01, prompt_seed=1), dict(at=.045, prompt_seed=2), dict(at=.07, prompt_seed=3)]
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('adaptive_fixed', 'adaptive_deadline'):
                # Leave several cohort widths after the last planned arrival.
                # The 80ms fixture ended too close to its final 70ms request
                # for Windows scheduling jitter; GPU protocols are unchanged.
                await one_mode(mode, cfg, profile, arrivals, .20, self.session,
                               self.url.removesuffix('/completions'), Path(directory))
                result = audit_mode(Path(directory)/mode, arrivals, mode)
                self.assertEqual(result['accounting_requests'], 3)

    async def test_static_rate_is_independent_and_never_observes_feedback(self):
        import json
        from dataclasses import asdict
        from unittest.mock import patch
        from run_pilot import one_mode
        from audit_alignment_pairs import audit_mode
        cfg = dict(model_name='fake', fixed_rate=6, cohort_alignment='deadline',
                   feedback=asdict(Config(initial=3, minimum_samples=1, confirmations=1,
                                          settle_seconds=0, demand_fraction=.01)),
                   cohort_seconds=.04, request_timeout_seconds=1, tick_seconds=.005,
                   max_pending_tasks=8, max_dispatch_lag_seconds=.5)
        profile = dict(name='short', input_tokens=8, output_tokens=1,
                       ttft_slo_ms=1000, e2el_slo_ms=1000)
        arrivals = [dict(at=.01, prompt_seed=1), dict(at=.05, prompt_seed=2)]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Feedback, 'observe', side_effect=AssertionError('static feedback observed')):
                summary = await one_mode('fixed', cfg, profile, arrivals, .08, self.session,
                                         self.url.removesuffix('/completions'), Path(directory))
            self.assertEqual((summary['final_rate'], summary['transitions']), (6, 0))
            folder = Path(directory)/'fixed'
            result = audit_mode(folder, arrivals, 'fixed')
            self.assertEqual(result['accounting_requests'], 2)
            controls = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
            controls[0]['rate'] = 3
            (folder/'control.jsonl').write_text('\n'.join(json.dumps(c) for c in controls))
            with self.assertRaisesRegex(ValueError, 'static rate/revision'):
                audit_mode(folder, arrivals, 'fixed')

    async def test_bad_static_rates_fail_before_creating_output(self):
        from run_pilot import one_mode
        for value in (0, -1, True, float('nan'), float('inf'), '6'):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, 'fixed_rate'):
                    await one_mode('fixed', dict(feedback={}, fixed_rate=value), {}, [], 1,
                                   self.session, self.url, Path(directory))
                self.assertFalse((Path(directory)/'fixed').exists())
