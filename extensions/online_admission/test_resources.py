import unittest
from resources import summarize


class ResourceTest(unittest.TestCase):
    def test_cpu_units_and_pss_aggregation(self):
        rows = [dict(phase='probe', processes=[dict(role='backend', pss_kib=1024, cpu_one_core_pct=100),
                                              dict(role='backend', pss_kib=2048, cpu_one_core_pct=50)])]
        result = summarize(rows)['probe']['backend']
        self.assertEqual(result['max_pss_mib'], 3)
        self.assertEqual(result['mean_cpu_one_core_pct'], 150)

