import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import aiohttp
from aiohttp import web
from pressure_analysis import make_trace
from run_pilot import trace
from run_pressure_calibration import collect_queue


class PressureHttpTest(unittest.IsolatedAsyncioTestCase):
    def test_trace_generator_matches_existing_driver(self):
        for seed, offered in ((303, 18), (304, 18), (305, 36), (306, 36)):
            expected, duration = trace(dict(seed=seed, phases=[dict(seconds=120, rps=offered)]))
            self.assertEqual(make_trace(seed, offered), expected)
            self.assertEqual(duration, 120)

    async def test_sampler_keeps_raw_and_stops_without_gpu(self):
        stop = asyncio.Event()
        async def handler(request):
            stop.set()
            return web.Response(text='vllm:num_requests_running 1\nvllm:num_requests_waiting 0\n')
        app = web.Application()
        app.router.add_get('/metrics', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'queue.jsonl'
                async with aiohttp.ClientSession() as session:
                    await collect_queue(session, f'http://127.0.0.1:{port}', path, stop)
                records = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]['metrics'], dict(running=1, waiting=0))
                self.assertIn('vllm:num_requests_running', records[0]['raw'])
                self.assertGreaterEqual(records[0]['finished_at'], records[0]['at'])
        finally:
            await runner.cleanup()
