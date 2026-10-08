"""Focused tests for V4.4.3 quality cohorts and M2 funnel helpers."""
import unittest

from .v443_merge import _m1a, _m1bplus, _m2_balanced, _m2_strict_funnel


class TestV443Filters(unittest.TestCase):
    def test_m1a_requires_same_m1_context(self):
        row = {
            "v441_m1_context_ok": 1,
            "v440_state": "TP2_DEMAND",
            "v440_net_r": 2.0,
        }
        self.assertTrue(_m1a(row))
        row["v441_m1_context_ok"] = 0
        self.assertFalse(_m1a(row))

    def test_m1_b_plus_requires_bos_and_rejection(self):
        row = {
            "v441_m1_state": "TP1_THEN_BE",
            "v441_m1_net_r": 0.8,
            "v428_trend_phase": "MATURE_DOWNTREND",
            "v441_m1_confirm_score": 4,
            "v441_m1_failed_auction": 1,
            "v441_m1_micro_bos": 1,
            "v441_m1_rejection": 1,
            "v441_m1_cost_r": 0.15,
            "v441_m1_room_r": 3.5,
        }
        self.assertTrue(_m1bplus(row))
        row["v441_m1_rejection"] = 0
        self.assertFalse(_m1bplus(row))

    def test_m2_balanced_accepts_multi_bar_acceptance(self):
        row = {
            "v441_m2_state": "TP2_DEMAND",
            "v441_m2_net_r": 2.0,
            "v428_trend_phase": "MATURE_DOWNTREND",
            "v441_m2_confirm_score": 3,
            "v441_m2_controlled_break": 1,
            "v441_m2_retest_rejection": 0,
            "v441_m2_acceptance_bars": 3,
            "v441_m2_entry": 98.4,
            "v441_m2_support_level": 100.0,
            "atr_1h": 2.0,
            "v441_m2_break_body_atr": 0.9,
            "v441_m2_cost_r": 0.18,
            "v441_m2_room_r": 3.5,
        }
        self.assertTrue(_m2_balanced(row))
        self.assertAlmostEqual(row["v443_m2_entry_below_support_atr"], 0.8, places=4)

    def test_strict_funnel_never_increases(self):
        rows = [{
            "v441_m2_state": "TP2_DEMAND",
            "v441_m2_net_r": 2.0,
            "v428_trend_phase": "MATURE_DOWNTREND",
            "v441_m2_confirm_score": 4,
            "v441_m2_controlled_break": 1,
            "v441_m2_retest_touched": 1,
            "v441_m2_retest_rejection": 1,
            "v441_m2_entry": 99.0,
            "v441_m2_support_level": 100.0,
            "atr_1h": 2.0,
            "v441_m2_break_body_atr": 0.8,
            "v441_m2_cost_r": 0.15,
            "v441_m2_room_r": 3.5,
        }]
        funnel = _m2_strict_funnel(rows)
        counts = [x["count"] for x in funnel]
        self.assertTrue(all(a >= b for a, b in zip(counts, counts[1:])))


if __name__ == "__main__":
    unittest.main()
