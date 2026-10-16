import unittest
from audit_static_endpoints import normalized_command
from static_gate_replay import replay


class StaticOfflineTest(unittest.TestCase):
    def test_only_private_port_is_normalized(self):
        base = ['vllm', 'serve', 'model', '--port', '8023', '--dtype', 'float16']
        other = base.copy()
        other[4] = '8025'
        self.assertEqual(normalized_command(base), normalized_command(other))
        other[-1] = 'bfloat16'
        self.assertNotEqual(normalized_command(base), normalized_command(other))
        self.assertEqual(base[4], '8023')

    def test_invalid_command_fails(self):
        with self.assertRaises(ValueError):
            normalized_command(['vllm', '--port'])

    def test_one_token_refill_and_rejections(self):
        result = replay([0, .125, .25, .5, .625], 4)
        self.assertEqual(result['accepted_ids'], [0, 2, 3])
        self.assertEqual(result['accepted']+result['rejected'], result['offered'])

    def test_fractional_capacity_is_retained(self):
        result = replay([0, 0, .125, .25], 6)
        self.assertEqual(result['capacity'], 1.5)
        self.assertEqual(result['accepted_ids'], [0, 2, 3])

    def test_empty_and_invalid_inputs(self):
        self.assertEqual(replay([], 3)['accepted'], 0)
        for times, rate in (([.5, .1], 3), ([-1], 3), ([float('nan')], 3), ([0], 0)):
            with self.assertRaises(ValueError):
                replay(times, rate)


if __name__ == '__main__':
    unittest.main()
