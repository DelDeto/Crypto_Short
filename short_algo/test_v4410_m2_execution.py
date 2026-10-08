"""Focused tests for V4.4.10 no-stop path research."""
import unittest

import pandas as pd

from .v4410_m2_execution import (
    _path_for_horizon,
    _reclaim_after_entry,
    _threshold_path,
)


def _frame(rows, freq):
    idx = pd.date_range(
        "2026-01-01", periods=len(rows), freq=freq, tz="UTC"
    )
    return pd.DataFrame(rows, index=idx)


class TestV4410M2PathStudy(unittest.TestCase):
    def test_path_records_mae_mfe_without_exit(self):
        future = _frame([
            {"open":100.0,"high":101.0,"low":99.5,"close":99.8},
            {"open":99.8,"high":103.0,"low":98.5,"close":99.0},
            {"open":99.0,"high":102.0,"low":96.0,"close":97.0},
            {"open":97.0,"high":101.0,"low":95.0,"close":95.5},
        ], "15min")
        out = _path_for_horizon(
            future, 0, entry=100.0, atr=2.0, hours=1
        )
        self.assertEqual(out["complete"], 1)
        self.assertAlmostEqual(out["mae_atr"], 1.5)
        self.assertAlmostEqual(out["mfe_atr"], 2.5)
        self.assertAlmostEqual(out["time_to_mae_h"], 0.5)
        self.assertAlmostEqual(out["time_to_mfe_h"], 1.0)
        self.assertAlmostEqual(out["forward_close_atr"], 2.25)

    def test_mae_before_2atr_is_measured_before_hit(self):
        future = _frame([
            {"open":100.0,"high":101.0,"low":99.5,"close":99.8},
            {"open":99.8,"high":103.0,"low":98.5,"close":99.0},
            {"open":99.0,"high":102.0,"low":96.0,"close":97.0},
            {"open":97.0,"high":101.0,"low":95.0,"close":95.5},
        ], "15min")
        out = _threshold_path(
            future,
            0,
            entry=100.0,
            atr=2.0,
            threshold_atr=2.0,
            max_hours=1,
        )
        self.assertEqual(out["hit"], 1)
        self.assertAlmostEqual(out["time_to_hit_h"], 0.75)
        self.assertAlmostEqual(out["mae_before_hit_atr"], 1.5)

    def test_reclaim_after_entry_is_diagnostic_only(self):
        event = {
            "atr": 2.0,
            "upper": 100.5,
        }
        future4h = _frame([
            {"open":100.0,"high":101.0,"low":99.5,"close":100.8},
            {"open":100.8,"high":101.2,"low":100.4,"close":100.9},
            {"open":100.9,"high":101.0,"low":99.8,"close":100.0},
        ], "4h")
        out = _reclaim_after_entry(
            event,
            future4h,
            pd.Timestamp("2026-01-01T00:00:00Z"),
        )
        self.assertEqual(out["reclaimed"], 1)
        self.assertAlmostEqual(out["time_to_reclaim_h"], 8.0)

    def test_incomplete_horizon_is_marked_censored(self):
        future = _frame([
            {"open":100.0,"high":101.0,"low":99.0,"close":100.0},
            {"open":100.0,"high":101.0,"low":99.0,"close":100.0},
        ], "15min")
        out = _path_for_horizon(
            future, 0, entry=100.0, atr=2.0, hours=1
        )
        self.assertEqual(out["complete"], 0)


if __name__ == "__main__":
    unittest.main()
