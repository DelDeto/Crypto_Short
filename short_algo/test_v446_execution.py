"""Focused tests for V4.4.6 retest-window selection."""
import unittest

import pandas as pd

from .v446_execution import _select_retest_entry


def _frame(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def _event(rows, level=100.0, atr=2.0):
    frame = _frame(rows)
    return {
        "frame": frame,
        "break_idx": 0,
        "break_time": frame.index[0],
        "level": level,
        "atr": atr,
    }


class TestV446Execution(unittest.TestCase):
    def test_ignores_early_retest_then_enters_in_1h_3h_window(self):
        rows = [
            {"open":100.0,"high":100.0,"low":99.2,"close":99.5},  # break
            {"open":99.5,"high":99.9,"low":99.2,"close":99.4},   # early touch
            {"open":99.4,"high":99.5,"low":99.0,"close":99.3},
            {"open":99.3,"high":99.4,"low":99.0,"close":99.2},
            {"open":99.7,"high":99.9,"low":99.1,"close":99.3},  # clear bearish retest
            {"open":99.45,"high":99.5,"low":99.0,"close":99.2},  # next open <=0.30ATR
            {"open":99.2,"high":99.4,"low":98.9,"close":99.1},
        ]
        sel = _select_retest_entry(_event(rows), "R1")
        self.assertEqual(sel["state"], "ENTRY")
        self.assertEqual(sel["trigger_idx"], 4)
        self.assertEqual(sel["entry_idx"], 5)
        self.assertEqual(sel["early_retest"], 1)

    def test_skips_event_if_extension_too_far_before_retest(self):
        rows = [
            {"open":100.0,"high":100.0,"low":99.2,"close":99.5},
            {"open":99.5,"high":99.6,"low":97.2,"close":98.0},   # 1.4 ATR extension
            {"open":98.0,"high":98.5,"low":97.5,"close":98.1},
            {"open":98.1,"high":98.8,"low":97.8,"close":98.4},
            {"open":98.4,"high":99.8,"low":98.2,"close":99.2},
            {"open":99.2,"high":99.4,"low":98.9,"close":99.0},
        ]
        sel = _select_retest_entry(_event(rows), "R1")
        self.assertEqual(sel["state"], "TOO_EXTENDED_BEFORE_RETEST")

    def test_hard_reclaim_invalidates(self):
        rows = [
            {"open":100.0,"high":100.0,"low":99.2,"close":99.5},
            {"open":99.5,"high":100.8,"low":99.4,"close":100.6}, # > +0.25ATR
            {"open":100.6,"high":100.7,"low":99.0,"close":99.2},
            {"open":99.2,"high":99.5,"low":98.9,"close":99.1},
            {"open":99.1,"high":99.8,"low":99.0,"close":99.3},
            {"open":99.3,"high":99.5,"low":99.0,"close":99.2},
            {"open":99.2,"high":99.4,"low":98.9,"close":99.1},
        ]
        sel = _select_retest_entry(_event(rows), "R1")
        self.assertEqual(sel["state"], "HARD_RECLAIM_INVALIDATED")

    def test_r2_requires_tighter_entry(self):
        rows = [
            {"open":100.0,"high":100.0,"low":99.2,"close":99.5},
            {"open":99.5,"high":99.6,"low":99.0,"close":99.4},
            {"open":99.4,"high":99.5,"low":99.0,"close":99.3},
            {"open":99.3,"high":99.4,"low":99.0,"close":99.2},
            {"open":99.7,"high":99.9,"low":99.0,"close":99.3},
            {"open":99.5,"high":99.6,"low":99.0,"close":99.3},
        ]
        r1 = _select_retest_entry(_event(rows), "R1")
        r2 = _select_retest_entry(_event(rows), "R2")
        self.assertEqual(r1["state"], "ENTRY")
        self.assertNotEqual(r2["state"], "ENTRY")


if __name__ == "__main__":
    unittest.main()
