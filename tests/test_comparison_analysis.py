from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from summarize_policy_comparison import inspect_rollback_windows


class RollbackAuditTest(unittest.TestCase):
    def test_reused_slow_request_is_identified_and_reset_after_execution(self):
        classes = [
            {"name": "interactive_short", "ttft_slo_ms": 100, "e2el_slo_ms": 400},
            {"name": "document_long", "ttft_slo_ms": 295, "e2el_slo_ms": 500},
        ]

        def request(request_id, completed, ttft):
            return {"kind": "request", "payload": {
                "request_id": request_id, "admitted": True, "shape": "balanced",
                "completed_at_s": completed, "success": True, "ttft_ms": ttft,
                "e2el_ms": 300,
            }}

        def decision(timestamp):
            return {"kind": "decision", "payload": {
                "timestamp_s": timestamp, "reason": "confirmed SLO violation",
                "active_profile": "mixed_80_20", "action": "hold",
            }}

        audit = [
            {"kind": "execution", "payload": {"completed_at_s": 10}},
            request(1, 11, 160), decision(20),
            request(2, 21, 50), decision(30),
            {"kind": "execution", "payload": {"completed_at_s": 35}},
            request(3, 36, 160), decision(45),
        ]
        windows = inspect_rollback_windows(audit, classes, 60)
        self.assertEqual(windows[0]["violating_request_ids"], [1])
        self.assertEqual(windows[1]["violating_request_ids"], [1])
        self.assertEqual(windows[1]["overlap_with_previous_violation"], [1])
        self.assertEqual(windows[1]["samples_by_shape"], {"balanced": 2})
        self.assertEqual(windows[2]["violating_request_ids"], [3])
        self.assertEqual(windows[2]["overlap_with_previous_violation"], [])


if __name__ == "__main__":
    unittest.main()
