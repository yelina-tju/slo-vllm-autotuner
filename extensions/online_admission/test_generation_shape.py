import unittest
from audit_generation_shape import generation_counts


class GenerationShapeTest(unittest.TestCase):
    def raw(self, count='4', total='256'):
        return f'vllm:request_generation_tokens_count{{engine="0"}} {count}\nvllm:request_generation_tokens_sum{{engine="0"}} {total}\n'

    def test_parse(self):
        self.assertEqual(generation_counts(self.raw()), dict(count=4, tokens=256))

    def test_multiple_engines_aggregate(self):
        self.assertEqual(generation_counts(self.raw()+self.raw().replace('"0"', '"1"')), dict(count=8, tokens=512))

    def test_invalid_or_missing_metrics(self):
        for raw in ('', self.raw('NaN'), self.raw(total='-1')):
            with self.assertRaises(ValueError):
                generation_counts(raw)
