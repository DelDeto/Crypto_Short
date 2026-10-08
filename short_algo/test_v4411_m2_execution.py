"""Focused tests for V4.4.11 M2 execution."""
import unittest
import pandas as pd

from .v4411_m2_execution import _simulate_variant


class TestV4411M2Execution(unittest.TestCase):
    def _frame(self, rows):
        idx = pd.date_range("2026-01-01", periods=len(rows), freq="15min", tz="UTC")
        return pd.DataFrame(rows, index=idx)

    def test_stop_first_is_conservative(self):
        frame = self._frame([
            {"open":100.0,"high":103.5,"low":95.0,"close":99.0},
            {"open":99.0,"high":100.0,"low":98.0,"close":99.0},
        ])
        out = _simulate_variant(frame,0,100.0,2.0,1.5)
        self.assertEqual(out["v4411_m2_s1_5_state"],"SL_FIRST")
        self.assertLess(out["v4411_m2_s1_5_net_r"],0)

    def test_tp1_then_be(self):
        rows=[
            {"open":100.0,"high":100.5,"low":93.5,"close":95.0},
            {"open":95.0,"high":100.2,"low":94.0,"close":99.0},
        ]
        rows += [{"open":99.0,"high":99.5,"low":98.0,"close":99.0}] * 400
        frame=self._frame(rows)
        out=_simulate_variant(frame,0,100.0,2.0,1.5)
        self.assertEqual(out["v4411_m2_s1_5_state"],"TP1_THEN_BE")
        self.assertEqual(out["v4411_m2_s1_5_tp1_hit"],1)
        self.assertGreater(out["v4411_m2_s1_5_net_r"],0)

    def test_tp2_full(self):
        rows=[{"open":100.0,"high":100.5,"low":90.5,"close":92.0}]
        rows += [{"open":92.0,"high":93.0,"low":91.0,"close":92.0}] * 400
        frame=self._frame(rows)
        out=_simulate_variant(frame,0,100.0,2.0,1.5)
        self.assertEqual(out["v4411_m2_s1_5_state"],"TP2_FULL")
        self.assertEqual(out["v4411_m2_s1_5_tp2_hit"],1)
        self.assertGreater(out["v4411_m2_s1_5_net_r"],2.0)


if __name__=="__main__":
    unittest.main()
