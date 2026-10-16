import asyncio
import unittest
import time
from types import SimpleNamespace
from hot_gate import HotAdmissionGate, apply_proposal
from feedback import Feedback, ClassEvidence, Window


class GateTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_free_tokens_and_pause_preserved(self):
        g = HotAdmissionGate(3)
        t = g._last_refill_s
        await g.acquire(t)
        self.assertTrue(await g.update_rate(12, t))
        self.assertEqual(g.snapshot()['available_tokens'], 0)
        self.assertEqual(g.in_flight, 1)
        await g.pause()
        self.assertFalse(await g.update_rate(6, t))
        self.assertTrue(g.paused)
        self.assertEqual(g.rate_limit_rps, 12)
        await g.release()
        self.assertTrue(await g.wait_for_drain(.1))

    async def test_lifecycle_lock_and_failed_ack(self):
        g = HotAdmissionGate(3)
        f = Feedback(['short'])
        evidence = {'short': ClassEvidence(40, 0, .5, .5)}
        f.observe(Window(0, 10, 0, 10, evidence))
        d = f.observe(Window(10, 20, 0, 10, evidence))
        executor = SimpleNamespace(_lock=asyncio.Lock(), admission_gate=g)
        await executor._lock.acquire()
        task = asyncio.create_task(apply_proposal(executor, f, d))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        await g.pause()
        executor._lock.release()
        self.assertFalse(await task)
        self.assertEqual((f.rate, f.revision), (3, 0))

    async def test_success_and_invalid_rate(self):
        g = HotAdmissionGate(3)
        for value in (float('nan'), float('inf'), 0):
            with self.assertRaises(ValueError):
                await g.update_rate(value)
        self.assertTrue(await g.update_rate(4))

    async def test_expired_proposal_waiting_for_lifecycle_lock_is_not_applied(self):
        g = HotAdmissionGate(3)
        f = Feedback(['short'])
        evidence = {'short': ClassEvidence(40, 0, .5, .5)}
        f.observe(Window(0, 10, 0, 10, evidence))
        d = f.observe(Window(10, 20, 0, 10, evidence))
        executor = SimpleNamespace(_lock=asyncio.Lock(), admission_gate=g)
        await executor._lock.acquire()
        task = asyncio.create_task(apply_proposal(executor, f, d, not_after=time.monotonic()+.01))
        await asyncio.sleep(.02)
        executor._lock.release()
        self.assertFalse(await task)
        self.assertEqual(g.rate_limit_rps, 3)
        self.assertEqual(f.revision, 0)
