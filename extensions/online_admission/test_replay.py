import unittest
from replay import demonstrate


class ReplayTest(unittest.TestCase):
    def test_scripted_lifecycle(self):
        records = demonstrate()
        changes = [r for r in records if r['applied'] is not None]
        self.assertEqual([r['decision']['action'] for r in changes],
                         ['increase', 'decrease', 'increase', 'increase'])
        self.assertEqual([r['applied'] for r in changes], [True, True, False, True])
        self.assertAlmostEqual(changes[1]['after'], 2.8)
        self.assertEqual(changes[2]['before'], changes[2]['after'])
        self.assertEqual(changes[2]['revision'], changes[2]['evidence_revision'])
        self.assertAlmostEqual(records[-1]['after'], 3.8)
        self.assertEqual(records[-1]['revision'], 3)

    def test_deterministic(self):
        self.assertEqual(demonstrate(), demonstrate())
