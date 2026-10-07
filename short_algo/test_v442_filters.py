"""Focused tests for V4.4.2 signal-time quality filters."""
import unittest

from .v442_merge import _m1b_quality, _m2_quality


class TestV442Filters(unittest.TestCase):
    def test_m1b_quality_requires_grade_b_context(self):
        row={
            "v441_m1_state":"TP1_THEN_BE","v441_m1_net_r":0.8,
            "v428_trend_phase":"MATURE_DOWNTREND","v441_m1_confirm_score":4,
            "v441_m1_failed_auction":1,"v441_m1_micro_bos":1,
            "v441_m1_rejection":1,"v441_m1_cost_r":0.15,"v441_m1_room_r":3.0,
        }
        self.assertTrue(_m1b_quality(row))

    def test_m2_quality_requires_real_retest_and_location(self):
        row={
            "v441_m2_state":"TP2_DEMAND","v441_m2_net_r":2.0,
            "v428_trend_phase":"MATURE_DOWNTREND","v441_m2_confirm_score":4,
            "v441_m2_controlled_break":1,"v441_m2_retest_touched":1,
            "v441_m2_retest_rejection":1,"v441_m2_entry":98.8,
            "v441_m2_support_level":100.0,"atr_1h":2.0,
            "v441_m2_cost_r":0.15,"v441_m2_room_r":4.0,
            "v441_m2_break_body_atr":0.8,
        }
        self.assertTrue(_m2_quality(row))
        self.assertAlmostEqual(row["v442_m2_entry_below_support_atr"],0.6,places=4)


if __name__=="__main__":
    unittest.main()
