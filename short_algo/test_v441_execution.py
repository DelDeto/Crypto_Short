"""Focused unit tests for V4.4.1 dual-model execution mechanics."""
import unittest

import pandas as pd

from .v441_execution import (
    _m1_confirmation,
    _simulate_staged,
    _structural_support,
)


def _frame(rows, freq):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, index=idx)


class TestV441Execution(unittest.TestCase):
    def test_m1_confirmation_is_scored_not_all_or_nothing(self):
        seed = {"pool": 100.0, "micro_low": 99.5}
        bar = pd.Series({"open": 100.6, "high": 101.0, "low": 99.0, "close": 99.2})
        out = _m1_confirmation(bar, seed, 1.0, 100.5)
        self.assertGreaterEqual(out["score"], 3)
        self.assertEqual(out["failed_auction"], 1)
        self.assertEqual(out["rejection"], 1)
        self.assertEqual(out["bos"], 1)

    def test_structural_support_requires_repeated_4h_reactions(self):
        lows = [100, 99, 98, 95.0, 98, 99, 97, 95.1, 97, 98, 99, 100]
        rows = []
        for low in lows:
            rows.append({
                "open": low + 1.0,
                "high": low + 2.0,
                "low": low,
                "close": low + 1.2,
            })
        four = _frame(rows, "4h")
        support = _structural_support(four, 100.0, 2.0)
        self.assertIsNotNone(support)
        self.assertGreaterEqual(support["touches"], 2)
        self.assertAlmostEqual(support["level"], 95.05, delta=0.2)

    def test_followthrough_reclaim_exits_causally(self):
        rows = [
            {"open": 100.0, "high": 100.2, "low": 99.9, "close": 100.15},
            {"open": 100.15, "high": 100.3, "low": 99.95, "close": 100.2},
            {"open": 100.2, "high": 100.3, "low": 99.9, "close": 100.1},
            {"open": 100.1, "high": 100.2, "low": 99.85, "close": 100.05},
        ]
        fut = _frame(rows, "15min")
        prefix = "v441_m1"
        seed = {
            f"{prefix}_state": "PLANNED",
            f"{prefix}_context_ok": 1,
            f"{prefix}_ft_state": None,
            f"{prefix}_ft_pass": 0,
            f"{prefix}_ft_mfe_r": None,
            f"{prefix}_tp1_hit": 0,
            f"{prefix}_tp1_time": None,
        }
        out = _simulate_staged(
            prefix, fut, 0, 100.0, 102.0, 2.0, 96.0, 94.0, 3.0, 99.9, seed
        )
        self.assertEqual(out[f"{prefix}_state"], "FT_RECLAIM_EXIT")
        self.assertEqual(out[f"{prefix}_ft_pass"], 0)

    def test_tp1_then_demand_target(self):
        rows = [
            {"open": 100.0, "high": 100.2, "low": 99.0, "close": 99.2},
            {"open": 99.2, "high": 99.3, "low": 95.8, "close": 96.1},
            {"open": 96.1, "high": 96.2, "low": 93.8, "close": 94.0},
        ]
        fut = _frame(rows, "15min")
        prefix = "v441_m2"
        seed = {
            f"{prefix}_state": "PLANNED",
            f"{prefix}_context_ok": 1,
            f"{prefix}_ft_state": None,
            f"{prefix}_ft_pass": 0,
            f"{prefix}_ft_mfe_r": None,
            f"{prefix}_tp1_hit": 0,
            f"{prefix}_tp1_time": None,
        }
        out = _simulate_staged(
            prefix, fut, 0, 100.0, 102.0, 2.0, 96.0, 94.0, 3.0, 101.0, seed
        )
        self.assertEqual(out[f"{prefix}_state"], "TP2_DEMAND")
        self.assertEqual(out[f"{prefix}_tp1_hit"], 1)
        self.assertGreater(out[f"{prefix}_net_r"], 0)


if __name__ == "__main__":
    unittest.main()
