"""Focused tests for V4.4.8 M2 target/execution engine."""
import unittest

import pandas as pd

from .v441_execution import _empty
from .v448_m2_execution import _major_4h_demand, _simulate


def _frame(rows, freq="4h"):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, index=idx)


class TestV448M2Execution(unittest.TestCase):
    def test_major_4h_demand_accepts_strong_departure_pivot(self):
        rows = [
            {"open":101,"high":102,"low":100,"close":101},
            {"open":100,"high":101,"low":99,"close":100},
            {"open":99,"high":100,"low":98,"close":99},
            {"open":97,"high":98,"low":95,"close":96},
            {"open":97,"high":100,"low":97,"close":99},
            {"open":99,"high":103,"low":98,"close":102},
            {"open":102,"high":106,"low":101,"close":105},
            {"open":104,"high":107,"low":103,"close":106},
            {"open":105,"high":108,"low":104,"close":107},
            {"open":106,"high":109,"low":105,"close":108},
        ]
        out = _major_4h_demand(_frame(rows), entry=110.0, atr=2.0)
        self.assertIsNotNone(out)
        self.assertEqual(out["source"], "MAJOR_4H_DEPARTURE")
        self.assertLess(out["upper"], 110.0)
        self.assertGreaterEqual(out["departure_atr"], 2.0)

    def test_minor_single_pivot_without_departure_is_ignored(self):
        rows = [
            {"open":101,"high":102,"low":100,"close":101},
            {"open":100,"high":101,"low":99,"close":100},
            {"open":99,"high":100,"low":98,"close":99},
            {"open":97,"high":98,"low":95,"close":96},
            {"open":96,"high":97,"low":96,"close":96.5},
            {"open":96.5,"high":97.5,"low":96,"close":97},
            {"open":97,"high":98,"low":96.5,"close":97.5},
            {"open":97.5,"high":98,"low":97,"close":97.5},
            {"open":98,"high":99,"low":97.5,"close":98.5},
        ]
        out = _major_4h_demand(_frame(rows), entry=110.0, atr=2.0)
        self.assertIsNone(out)

    def test_open_space_ladder_banks_2r_and_4r(self):
        rows = [
            {"open":100.0,"high":100.5,"low":97.5,"close":98.0},
            {"open":98.0,"high":98.5,"low":95.5,"close":96.0},
            {"open":96.0,"high":96.5,"low":91.5,"close":92.0},
            {"open":92.0,"high":95.0,"low":90.0,"close":91.0},
        ]
        future = _frame(rows, "15min")
        seed = _empty("v448_m2", "PLANNED")
        out = _simulate(
            "v448_m2",
            future,
            0,
            entry=100.0,
            stop=102.0,
            atr=2.0,
            mode="OPEN_SPACE",
            major_target=None,
            room_r=None,
            seed=seed,
        )
        self.assertEqual(out["v448_m2_tp1_hit"], 1)
        self.assertEqual(out["v448_m2_tp2_hit"], 1)
        self.assertEqual(out["v448_m2_state"], "OPEN_TIME_EXIT")
        self.assertGreater(out["v448_m2_gross_r"], 2.0)


if __name__ == "__main__":
    unittest.main()
