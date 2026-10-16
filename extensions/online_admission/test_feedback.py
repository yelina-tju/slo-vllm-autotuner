import unittest
from feedback import ClassEvidence as C, Config, Feedback, Window


class FeedbackTest(unittest.TestCase):
    def window(self, start, revision=0, pressure=0.5, demand=10, count=40):
        return Window(start, start+10, revision, demand, {'short': C(count, 0, pressure, pressure)})

    def grow(self, f, demand=10):
        self.assertEqual(f.observe(self.window(0, demand=demand)).reason, 'awaiting_confirmation')
        return f.observe(self.window(10, demand=demand))

    def test_ack_is_required_and_old_evidence_cannot_promote(self):
        f = Feedback(['short'])
        d = self.grow(f)
        self.assertEqual((d.action, d.rate, f.rate), ('increase', 4, 3))
        self.assertEqual(f.observe(self.window(20)).reason, 'actuation_pending')
        f.acknowledge(d.proposal_id, True, 20)
        self.assertEqual((f.rate, f.revision), (4, 1))
        self.assertEqual(f.observe(self.window(30, 1)).reason, 'settling_evidence')
        self.assertEqual(f.observe(self.window(40)).reason, 'wrong_revision')
        self.assertEqual(f.observe(self.window(40, 1)).reason, 'awaiting_confirmation')

    def test_failure_keeps_applied_state(self):
        f = Feedback(['short'])
        d = self.grow(f)
        f.acknowledge(d.proposal_id, False, 20)
        self.assertEqual((f.rate, f.revision), (3, 0))
        with self.assertRaises(ValueError):
            f.acknowledge(d.proposal_id, True, 21)

    def test_duplicate_window_does_not_confirm(self):
        f = Feedback(['short'])
        f.observe(self.window(0))
        self.assertEqual(f.observe(self.window(0)).reason, 'overlapping_or_old_window')
        self.assertEqual(f.observe(self.window(10)).action, 'increase')

    def test_no_growth_on_low_demand_missing_classes_or_samples(self):
        for demand, count in ((1,40),(10,1)):
            f = Feedback(['short'])
            for start in (0,10,20):
                self.assertEqual(f.observe(self.window(start,demand=demand,count=count)).action,'hold')
        f = Feedback(['short','long'])
        self.assertEqual(f.observe(self.window(0)).reason,'insufficient_class_evidence')

    def test_bad_class_can_decrease_when_other_class_missing(self):
        f = Feedback(['short','long'])
        d = f.observe(self.window(0,pressure=1.2))
        self.assertEqual(d.action,'decrease')
        self.assertAlmostEqual(d.rate,2.1)

    def test_all_failed_window_decreases_without_latency(self):
        f = Feedback(['short'])
        d = f.observe(Window(0,10,0,10,{'short': C(0,40,None,None)}))
        self.assertEqual(d.action,'decrease')

    def test_bounds(self):
        f = Feedback(['short'],Config(initial=1))
        self.assertEqual(f.observe(self.window(0,pressure=2)).reason,'rate_bound')
        f = Feedback(['short'],Config(initial=12))
        self.assertEqual(self.grow(f, demand=20).reason,'rate_bound')

    def test_gap_breaks_confirmation(self):
        f = Feedback(['short'])
        f.observe(self.window(0))
        self.assertEqual(f.observe(self.window(100)).reason, 'awaiting_confirmation')

    def test_invalid_numbers_and_ack_time(self):
        for value in (float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError):
                C(40,0,value,0.5)
        with self.assertRaises(ValueError):
            Config(confirmations=1.5)
        f = Feedback(['short'])
        d = self.grow(f)
        with self.assertRaises(ValueError):
            f.acknowledge(d.proposal_id,True,19)

    def test_deadband_breaks_confirmation(self):
        f = Feedback(['short'])
        f.observe(self.window(0))
        self.assertEqual(f.observe(self.window(10,pressure=.9)).action,'hold')
        self.assertEqual(f.observe(self.window(20)).reason,'awaiting_confirmation')


if __name__ == '__main__':
    unittest.main()
