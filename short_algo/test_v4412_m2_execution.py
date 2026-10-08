"""Focused tests for V4.4.12 decoupled ATR execution."""
import unittest
import pandas as pd

from .v4412_m2_execution import _simulate_variant


class TestV4412M2Execution(unittest.TestCase):
    def _frame(self, rows):
        idx = pd.date_range("2026-01-01", periods=len(rows), freq="15min", tz="UTC")
        return pd.DataFrame(rows, index=idx)

    def test_target_is_independent_of_stop(self):
        rows = [{"open":100.0,"high":100.5,"low":96.5,"close":97.0}] + [
            {"open":97.0,"high":98.0,"low":96.0,"close":97.0}
        ] * 400
        frame = self._frame(rows)
        a = _simulate_variant(frame, 0, 100.0, 2.0, 1.25)
        b = _simulate_variant(frame, 0, 100.0, 2.0, 2.0)
        self.assertEqual(a["v4412_m2_s1_25_tp1"], b["v4412_m2_s2_0_tp1"])
        self.assertEqual(a["v4412_m2_s1_25_tp2"], b["v4412_m2_s2_0_tp2"])

    def test_stop_first_is_conservative(self):
        frame = self._frame([
            {"open":100.0,"high":103.0,"low":95.0,"close":99.0},
            {"open":99.0,"high":100.0,"low":98.0,"close":99.0},
        ])
        out = _simulate_variant(frame, 0, 100.0, 2.0, 1.25)
        self.assertEqual(out["v4412_m2_s1_25_state"], "SL_FIRST")
        self.assertLess(out["v4412_m2_s1_25_net_r"], 0)

    def test_tp2_full(self):
        rows = [{"open":100.0,"high":100.5,"low":93.5,"close":94.0}]
        rows += [{"open":94.0,"high":95.0,"low":93.0,"close":94.0}] * 400
        frame = self._frame(rows)
        out = _simulate_variant(frame, 0, 100.0, 2.0, 1.5)
        self.assertEqual(out["v4412_m2_s1_5_state"], "TP2_FULL")
        self.assertEqual(out["v4412_m2_s1_5_tp2_hit"], 1)
        self.assertGreater(out["v4412_m2_s1_5_net_r"], 1.0)


if __name__ == "__main__":
    unittest.main()
