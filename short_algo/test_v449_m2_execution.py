"""Focused tests for V4.4.9 Confirmed Support Flip."""
import unittest

import pandas as pd

from .v441_execution import _empty
from .v449_m2_execution import _simulate, _watch_support_flip


def _frame(rows, freq="4h"):
    idx = pd.date_range(
        "2026-01-01", periods=len(rows), freq=freq, tz="UTC"
    )
    return pd.DataFrame(rows, index=idx)


def _event():
    return {
        "atr": 2.0,
        "level": 100.2,
        "lower": 100.0,
        "upper": 100.5,
        "break_h": 100.3,
        "break_time": pd.Timestamp("2026-01-01T00:00:00Z"),
    }


class TestV449M2Execution(unittest.TestCase):
    def test_first_failed_reclaim_does_not_arm_short(self):
        rows = [
            {"open":99.8,"high":100.2,"low":99.0,"close":99.2},
            {"open":99.2,"high":99.4,"low":98.8,"close":99.0},
        ]
        out = _watch_support_flip(_event(), _frame(rows))
        self.assertEqual(out["state"], "EXPIRED_NO_CONFIRMED_FLIP")
        self.assertEqual(out["failed_reclaim_attempts"], 1)
        self.assertIsNone(out["ready_time"])

    def test_repeated_failed_reclaim_with_lower_high_confirms_flip(self):
        rows = [
            {"open":99.9,"high":100.3,"low":99.0,"close":99.2},
            {"open":99.8,"high":100.1,"low":98.9,"close":99.1},
            {"open":99.1,"high":99.4,"low":98.6,"close":98.9},
        ]
        out = _watch_support_flip(_event(), _frame(rows))
        self.assertEqual(out["state"], "CONFIRMED_SUPPORT_FLIP")
        self.assertEqual(
            out["ready_reason"],
            "REPEATED_FAILED_RECLAIM_LOWER_HIGH",
        )
        self.assertGreaterEqual(out["watch_hours"], 8)
        self.assertGreaterEqual(out["failed_reclaim_attempts"], 2)
        self.assertLess(out["flip_anchor_high"], out["prior_flip_high"])

    def test_two_confirmed_closes_above_zone_cancel_event(self):
        rows = [
            {"open":100.6,"high":101.0,"low":100.4,"close":100.8},
            {"open":100.8,"high":101.1,"low":100.5,"close":100.9},
            {"open":100.9,"high":101.0,"low":99.8,"close":100.1},
        ]
        out = _watch_support_flip(_event(), _frame(rows))
        self.assertEqual(out["state"], "RECLAIMED")
        self.assertIsNone(out["ready_time"])

    def test_persistent_no_reclaim_with_lower_highs_confirms_flip(self):
        # Green/neutral bars avoid failed-reclaim rejection while still
        # creating two confirmed 4H lower swing highs below the lost support.
        rows = [
            {"open":99.0,"high":99.4,"low":98.6,"close":99.2},
            {"open":99.2,"high":99.9,"low":99.0,"close":99.5},
            {"open":99.0,"high":99.4,"low":98.7,"close":99.2},
            {"open":99.1,"high":99.7,"low":98.8,"close":99.4},
            {"open":98.9,"high":99.2,"low":98.5,"close":99.0},
            {"open":98.8,"high":99.1,"low":98.4,"close":98.9},
        ]
        out = _watch_support_flip(_event(), _frame(rows))
        self.assertEqual(out["state"], "CONFIRMED_SUPPORT_FLIP")
        self.assertEqual(
            out["ready_reason"],
            "PERSISTENT_NO_RECLAIM_LOWER_HIGHS",
        )
        self.assertGreaterEqual(out["pivot_high_count"], 2)

    def test_risk_ladder_banks_2r_and_4r(self):
        rows = [
            {"open":100.0,"high":100.4,"low":95.8,"close":96.2},
            {"open":96.2,"high":96.5,"low":91.5,"close":92.0},
            {"open":92.0,"high":95.0,"low":90.0,"close":91.0},
        ]
        future = _frame(rows, "15min")
        seed = _empty("v449_m2", "PLANNED")
        out = _simulate(
            "v449_m2",
            future,
            0,
            entry=100.0,
            stop=102.0,
            atr=2.0,
            runner_target=None,
            runner_room_r=None,
            seed=seed,
        )
        self.assertEqual(out["v449_m2_tp1_hit"], 1)
        self.assertEqual(out["v449_m2_tp2_hit"], 1)
        self.assertGreater(out["v449_m2_gross_r"], 2.0)


if __name__ == "__main__":
    unittest.main()
