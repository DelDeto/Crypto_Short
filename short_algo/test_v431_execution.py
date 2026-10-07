"""Network-free tests for V4.3.1 causal micro-entry timing."""
import unittest

import pandas as pd

from .v431_execution import evaluate_v431_entries, _simulate_trade


def frame(rows, start="2026-06-01 00:00:00+00:00"):
    index = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, index=index)


def tail_rows(count=120, value=100.8):
    return [
        (value, value + 0.2, value - 0.2, value)
        for _ in range(count)
    ]


def hist():
    rows = tail_rows(40, 100.9)
    rows[-1] = (101.0, 101.2, 100.4, 101.1)
    return frame(rows, start="2026-05-31 14:00:00+00:00")


def features(confirmed=0, stop=103.0):
    return {
        "v428_entry_confirmed": confirmed,
        "v428_confirm_entry_reference": 100.8,
        "v428_confirm_stop_reference": stop,
        "v428_confirm_risk": stop - 100.8,
        "preferred_zone_lower": 100.5,
        "preferred_zone_upper": 101.5,
        "atr_1h": 2.0,
        "support_distance_atr": 1.0,
    }


SUPPORT = {"v430_support_structural": 95.0}


class TestV431Execution(unittest.TestCase):
    def test_same_bar_collision_is_stop(self):
        f = frame(tail_rows())
        f.iloc[0] = [100.0, 101.2, 97.5, 100.0]
        out = _simulate_trade(
            f, 0, 100.0, 101.0, 2.0, "A1", 0,
            "TEST", f.index[0], enforce_micro=False,
        )
        self.assertEqual(out["v431_A1_state"], "SL_SAME_BAR")
        self.assertLess(out["v431_A1_net_r"], -1.0)

    def test_a1_rejection_fills_next_open(self):
        rows = tail_rows()
        rows[0] = (101.2, 101.4, 100.4, 100.6)
        rows[1] = (100.7, 100.9, 98.3, 98.7)
        f = frame(rows)
        out = evaluate_v431_entries(features(), hist(), f, SUPPORT)
        self.assertEqual(out["v431_A1_entry_time"], f.index[1].isoformat())
        self.assertEqual(out["v431_A1_entry"], 100.7)
        self.assertEqual(out["v431_A1_state"], "TP2R_FIRST")

    def test_a2_sweep_fills_next_open(self):
        rows = tail_rows()
        rows[0] = (101.3, 101.8, 100.5, 100.8)
        rows[1] = (100.9, 101.0, 98.0, 98.5)
        f = frame(rows)
        out = evaluate_v431_entries(features(), hist(), f, SUPPORT)
        self.assertEqual(out["v431_A2_entry_time"], f.index[1].isoformat())
        self.assertEqual(out["v431_A2_state"], "TP2R_FIRST")

    def test_a3_waits_for_micro_low_break_then_next_open(self):
        rows = tail_rows()
        rows[0] = (101.2, 101.4, 100.5, 100.7)
        rows[1] = (100.7, 100.8, 99.8, 100.0)
        rows[2] = (100.1, 100.3, 96.5, 97.0)
        f = frame(rows)
        out = evaluate_v431_entries(features(), hist(), f, SUPPORT)
        self.assertEqual(out["v431_A3_entry_time"], f.index[2].isoformat())
        self.assertEqual(out["v431_A3_state"], "TP2R_FIRST")

    def test_no_chase_rejects_low_next_open(self):
        rows = tail_rows()
        rows[0] = (101.2, 101.4, 100.4, 100.6)
        rows[1] = (98.9, 99.0, 98.0, 98.4)
        f = frame(rows)
        out = evaluate_v431_entries(features(), hist(), f, SUPPORT)
        self.assertEqual(out["v431_A1_state"], "SKIP_CHASE")

    def test_c_requires_real_stop_and_reclaims_invalidation(self):
        rows = tail_rows()
        rows[0] = (100.0, 101.3, 99.8, 101.2)
        rows[1] = (101.2, 101.3, 100.3, 100.5)
        rows[2] = (100.6, 100.8, 98.4, 98.8)
        f = frame(rows)
        ft = features(confirmed=1, stop=101.0)
        out = evaluate_v431_entries(ft, hist(), f, SUPPORT)
        self.assertIn(out["v431_A0_state"], ("SL_FIRST", "SL_SAME_BAR"))
        self.assertEqual(out["v431_A0C_entry_time"], f.index[2].isoformat())
        self.assertEqual(out["v431_A0C_state"], "TP2R_FIRST")
        self.assertEqual(out["v431_A0_plus_C_trades"], 2)

    def test_no_c_without_primary_stop(self):
        rows = tail_rows()
        rows[0] = (100.0, 100.2, 93.0, 94.5)
        f = frame(rows)
        out = evaluate_v431_entries(
            features(confirmed=1, stop=103.0), hist(), f, SUPPORT
        )
        self.assertEqual(out["v431_A0_state"], "TP2R_FIRST")
        self.assertEqual(out["v431_A0C_state"], "PRIMARY_NOT_STOPPED")

    def test_missing_bar_censors_trade(self):
        f = frame(tail_rows())
        f = f.drop(f.index[8])
        out = _simulate_trade(
            f, 0, 100.0, 103.0, 2.0, "A1", 0,
            "TEST", f.index[0], enforce_micro=False,
        )
        self.assertEqual(out["v431_A1_state"], "CENSORED_15M_GAP")


if __name__ == "__main__":
    unittest.main()
