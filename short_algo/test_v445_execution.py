"""Focused tests for V4.4.5 execution research."""
import unittest

import pandas as pd

from .v445_execution import _select_m2_entry, _study_24h


def _frame(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, index=idx)


class TestV445Execution(unittest.TestCase):
    def test_accept3_entry_is_causal(self):
        rows = [
            {"open": 100.0, "high": 100.1, "low": 99.4, "close": 99.6},
            {"open": 99.6, "high": 99.8, "low": 99.2, "close": 99.5},
            {"open": 99.5, "high": 99.7, "low": 99.1, "close": 99.4},
            {"open": 99.4, "high": 99.6, "low": 99.2, "close": 99.3},
            {"open": 99.3, "high": 99.5, "low": 99.0, "close": 99.2},
        ]
        frame = _frame(rows)
        sel = _select_m2_entry(frame, 0, 100.0, 2.0, "ACCEPT3")
        self.assertIsNotNone(sel)
        self.assertEqual(sel["trigger_idx"], 2)
        self.assertEqual(sel["entry_idx"], 3)
        self.assertGreaterEqual(sel["acceptance_closes"], 3)

    def test_near_entry_waits_for_price_near_support(self):
        rows = [
            {"open": 100.0, "high": 100.0, "low": 98.0, "close": 98.2},
            {"open": 98.2, "high": 98.5, "low": 97.8, "close": 98.0},
            {"open": 98.0, "high": 98.4, "low": 97.9, "close": 98.1},
            {"open": 98.1, "high": 99.7, "low": 98.0, "close": 99.5},
            {"open": 99.7, "high": 99.9, "low": 99.2, "close": 99.6},
            {"open": 99.6, "high": 99.8, "low": 99.1, "close": 99.4},
        ]
        frame = _frame(rows)
        sel = _select_m2_entry(frame, 0, 100.0, 2.0, "ACCEPT3_NEAR")
        self.assertIsNotNone(sel)
        self.assertGreaterEqual(sel["trigger_idx"], 3)
        self.assertLessEqual(sel["entry_below_support_atr"], 0.20)

    def test_24h_path_is_diagnostic(self):
        rows = []
        for i in range(96):
            close = 99.5 - 0.01 * i
            rows.append({
                "open": close + 0.1,
                "high": close + 0.2,
                "low": close - 0.3,
                "close": close,
            })
        frame = _frame(rows)
        event = {
            "frame": frame,
            "break_idx": 0,
            "break_time": frame.index[0],
            "level": 100.0,
            "atr": 2.0,
        }
        out = _study_24h(event)
        self.assertEqual(out["v445_m2_event_24h_max_consecutive_below"], 96)
        self.assertGreater(out["v445_m2_event_24h_max_extension_atr"], 0.5)
        self.assertGreater(out["v445_m2_event_24h_closes_below"], 90)

    def test_hard_reclaim_cancels_entry(self):
        rows = [
            {"open": 100.0, "high": 100.1, "low": 99.3, "close": 99.5},
            {"open": 99.5, "high": 100.8, "low": 99.4, "close": 100.7},
            {"open": 100.7, "high": 100.8, "low": 99.0, "close": 99.2},
            {"open": 99.2, "high": 99.5, "low": 98.8, "close": 99.0},
        ]
        frame = _frame(rows)
        self.assertIsNone(_select_m2_entry(frame, 0, 100.0, 2.0, "ACCEPT3"))


if __name__ == "__main__":
    unittest.main()
