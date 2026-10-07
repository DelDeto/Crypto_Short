"""Focused unit tests for V4.4 causal structural mechanics."""
import unittest

import pandas as pd

from .v440_execution import _liquidity_pool, _nearest_demand, _simulate_staged


def _frame(rows, freq):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, index=idx)


class TestV440Execution(unittest.TestCase):
    def test_liquidity_pool_requires_repeated_separated_highs(self):
        records = []
        highs = [99.2, 100.0, 99.5, 100.05, 99.4, 100.02]
        for h in highs:
            records.append({"open": 99.0, "high": h, "low": 98.5, "close": 99.1})
        pool = _liquidity_pool(records, 1.0, 99.5, 100.5)
        self.assertIsNotNone(pool)
        self.assertGreaterEqual(pool["touches"], 2)
        self.assertAlmostEqual(pool["level"], 100.0, delta=0.08)

    def test_nearest_demand_prefers_nearest_meaningful_zone(self):
        rows4 = []
        lows4 = [95, 94, 93, 90, 93, 94, 95, 96, 97, 98]
        for i, low in enumerate(lows4):
            rows4.append({
                "open": low + 1.0,
                "high": low + 2.0,
                "low": low,
                "close": low + 1.2,
            })
        four = _frame(rows4, "4h")

        rows1 = []
        lows1 = [97, 96, 95, 94, 95, 94.1, 95, 96, 97, 98, 97, 96]
        for low in lows1:
            rows1.append({
                "open": low + 0.6,
                "high": low + 1.2,
                "low": low,
                "close": low + 0.7,
            })
        one = _frame(rows1, "1h")
        demand = _nearest_demand(one, four, 100.0, 2.0)
        self.assertIsNotNone(demand)
        self.assertLess(demand["upper"], 100.0)

    def test_bos_reclaim_exits_causally(self):
        rows = [
            {"open": 100.0, "high": 100.2, "low": 99.9, "close": 100.05},
            {"open": 100.05, "high": 100.2, "low": 99.85, "close": 100.0},
            {"open": 100.0, "high": 100.15, "low": 99.82, "close": 99.98},
            {"open": 99.98, "high": 100.10, "low": 99.80, "close": 99.95},
            {"open": 99.95, "high": 100.0, "low": 99.0, "close": 99.2},
        ]
        fut = _frame(rows, "15min")
        seed = {
            "v440_state": "PLANNED",
            "v440_trigger": "TEST",
            "v440_ft_state": None,
            "v440_ft_pass": 0,
            "v440_ft_mfe_r": None,
            "v440_tp1_hit": 0,
            "v440_tp1_time": None,
        }
        out = _simulate_staged(
            fut, 0, 100.0, 102.0, 2.0, 96.0, 94.0, 3.0, 99.0, seed
        )
        self.assertEqual(out["v440_state"], "FT_RECLAIM_EXIT")
        self.assertEqual(out["v440_ft_state"], "FAIL_BOS_RECLAIM")
        self.assertEqual(out["v440_ft_pass"], 0)

    def test_tp1_then_demand_target(self):
        rows = [
            {"open": 100.0, "high": 100.2, "low": 99.0, "close": 99.2},
            {"open": 99.2, "high": 99.3, "low": 95.8, "close": 96.1},
            {"open": 96.1, "high": 96.2, "low": 93.8, "close": 94.0},
        ]
        fut = _frame(rows, "15min")
        seed = {
            "v440_state": "PLANNED",
            "v440_trigger": "TEST",
            "v440_ft_state": None,
            "v440_ft_pass": 0,
            "v440_ft_mfe_r": None,
            "v440_tp1_hit": 0,
            "v440_tp1_time": None,
        }
        out = _simulate_staged(
            fut, 0, 100.0, 102.0, 2.0, 96.0, 94.0, 3.0, 98.0, seed
        )
        self.assertEqual(out["v440_state"], "TP2_DEMAND")
        self.assertEqual(out["v440_tp1_hit"], 1)
        self.assertGreater(out["v440_net_r"], 0)


if __name__ == "__main__":
    unittest.main()
