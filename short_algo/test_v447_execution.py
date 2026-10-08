"""Focused tests for V4.4.7 persistent broken-support state machine."""
import unittest

import pandas as pd

from .v447_execution import _find_1h_entry, _watch_reclaim


def _frame(rows, freq):
    idx = pd.date_range(
        "2026-01-01",
        periods=len(rows),
        freq=freq,
        tz="UTC",
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


class TestV447Execution(unittest.TestCase):
    def test_two_4h_closes_above_zone_confirm_reclaim(self):
        rows = [
            {"open":100.4,"high":101.0,"low":100.2,"close":100.8},
            {"open":100.8,"high":101.1,"low":100.5,"close":100.9},
            {"open":100.9,"high":101.0,"low":100.0,"close":100.2},
        ]
        out = _watch_reclaim(_event(), _frame(rows, "4h"))
        self.assertEqual(out["state"], "RECLAIMED")
        self.assertIsNone(out["ready_reason"])

    def test_failed_reclaim_touch_becomes_short_ready(self):
        rows = [
            {"open":99.7,"high":100.2,"low":98.9,"close":99.1},
            {"open":99.1,"high":99.5,"low":98.6,"close":98.9},
        ]
        out = _watch_reclaim(_event(), _frame(rows, "4h"))
        self.assertEqual(out["state"], "SHORT_READY")
        self.assertEqual(out["ready_reason"], "FAILED_RECLAIM_TOUCH")
        self.assertEqual(out["retest_attempts"], 1)

    def test_persistent_no_reclaim_lower_high_becomes_short_ready(self):
        rows = [
            {"open":99.3,"high":99.5,"low":98.8,"close":99.1},
            {"open":99.1,"high":99.4,"low":98.7,"close":99.0},
            {"open":99.0,"high":99.3,"low":98.5,"close":98.8},
            {"open":98.8,"high":99.0,"low":98.2,"close":98.6},
            {"open":98.6,"high":98.9,"low":98.0,"close":98.4},
            {"open":98.4,"high":98.8,"low":97.9,"close":98.2},
        ]
        out = _watch_reclaim(_event(), _frame(rows, "4h"))
        self.assertEqual(out["state"], "SHORT_READY")
        self.assertEqual(
            out["ready_reason"],
            "PERSISTENT_NO_RECLAIM_LOWER_HIGH",
        )
        self.assertEqual(out["lower_high_confirmed"], 1)

    def test_short_ready_waits_for_causal_1h_confirmation(self):
        ready = {
            "ready_time": pd.Timestamp("2026-01-01T00:00:00Z"),
            "ready_reclaim_high": 100.4,
        }
        one = _frame([
            {"open":99.8,"high":100.2,"low":99.0,"close":99.2},
            {"open":99.2,"high":99.5,"low":98.8,"close":99.0},
        ], "1h")
        fifteen = _frame([
            {"open":99.7,"high":99.8,"low":99.5,"close":99.6},
            {"open":99.6,"high":99.7,"low":99.4,"close":99.5},
            {"open":99.5,"high":99.6,"low":99.3,"close":99.4},
            {"open":99.4,"high":99.5,"low":99.1,"close":99.2},
            {"open":99.2,"high":99.3,"low":99.0,"close":99.1},
            {"open":99.1,"high":99.2,"low":98.9,"close":99.0},
            {"open":99.0,"high":99.1,"low":98.8,"close":98.9},
            {"open":98.9,"high":99.0,"low":98.7,"close":98.8},
        ], "15min")
        out = _find_1h_entry(ready, _event(), one, fifteen)
        self.assertEqual(out["state"], "ENTRY")
        self.assertEqual(
            out["confirm_time"],
            pd.Timestamp("2026-01-01T01:00:00Z"),
        )
        self.assertGreaterEqual(out["entry_idx"], 4)


if __name__ == "__main__":
    unittest.main()
