"""Network-free validation of causal V4.3 execution mechanics."""
import unittest

import pandas as pd

from .v430_execution import (
    _simulate_exit,
    classify_support,
    evaluate_execution_policies,
)


def bars(prices, start="2026-05-01 00:00:00+00:00"):
    rows = []
    for o, h, l, c in prices:
        rows.append({"open": o, "high": h, "low": l, "close": c})
    index = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, index=index)


def flat(count=420, value=100.0):
    return bars([(value, value + 0.02, value - 0.02, value)] * count)


def features(stop=101.0, lower=100.6, upper=101.0, entry=100.0):
    return {
        "v428_entry_confirmed": 1,
        "v428_confirm_entry_reference": entry,
        "v428_confirm_stop_reference": stop,
        "v428_confirm_risk": stop - entry,
        "preferred_zone_lower": lower,
        "preferred_zone_upper": upper,
        "atr_1h": 1.0,
        "support_distance_atr": 0.35,
    }


class TestCausalExecution(unittest.TestCase):
    def test_stop_before_tp_on_same_bar(self):
        frame = flat(100)
        frame.iloc[0] = [100, 101.3, 97.8, 100]
        out = _simulate_exit(frame, 0, 100, 101, "A")
        self.assertEqual(out["v430_A_state"], "SL_SAME_BAR")
        self.assertLess(out["v430_A_net_r"], -1)

    def test_entry_after_closed_rejection_not_before(self):
        data = [(100, 100.3, 99.7, 100.0)] * 105
        data[1] = (100.1, 101.4, 100.1, 101.3)
        data[2] = (101.3, 101.6, 100.6, 100.75)
        data[3] = (100.9, 101.0, 100.0, 100.4)
        data[4] = (100.3, 100.5, 98.0, 98.5)
        frame = bars(data)
        out = evaluate_execution_policies(features(stop=102, lower=101.0, upper=101.6), frame)
        self.assertEqual(out["v430_B_entry_time"], frame.index[3].isoformat())
        self.assertEqual(out["v430_B_entry"], 100.9)
        self.assertEqual(out["v430_B_state"], "TP2R_FIRST")

    def test_reentry_only_after_realized_stop_and_reclaim(self):
        data = [(100, 100.2, 99.6, 100)] * 105
        data[0] = (100, 100.4, 99.7, 100.2)
        data[1] = (100.2, 101.5, 100.0, 101.2)  # old short stops
        data[2] = (101.1, 101.1, 100.5, 100.65)  # bearish invalidation reclaim
        data[3] = (100.75, 100.9, 100.2, 100.5)  # reentry next open
        data[4] = (100.5, 100.7, 98.4, 98.7)  # reaches new 2R
        frame = bars(data)
        out = evaluate_execution_policies(features(), frame)
        self.assertIn(out["v430_A_state"], ("SL_FIRST", "SL_SAME_BAR"))
        self.assertEqual(out["v430_C_entry_time"], frame.index[3].isoformat())
        self.assertEqual(out["v430_C_state"], "TP2R_FIRST")
        self.assertEqual(out["v430_AplusC_trades"], 2)

    def test_no_reentry_without_stop(self):
        data = [(100, 100.2, 99.6, 100)] * 110
        data[1] = (100, 100.1, 97.5, 97.8)
        frame = bars(data)
        out = evaluate_execution_policies(features(), frame)
        self.assertEqual(out["v430_A_state"], "TP2R_FIRST")
        self.assertEqual(out["v430_C_state"], "A_NOT_STOPPED")

    def test_structural_support_unknown_is_not_infinite_room(self):
        one = pd.DataFrame(
            [{"low": 100.0, "close": 100.1}] * 100
        )
        four = pd.DataFrame(
            [{"low": 100.0, "close": 100.1}] * 90
        )
        out = classify_support(one, four, features())
        self.assertEqual(out["v430_support_class"], "MINOR")
        self.assertIsNone(out["v430_structural_room_r"])
        self.assertEqual(out["v430_support_pass"], 0)

    def test_future_gap_is_not_a_valid_24h_time_exit(self):
        frame = flat(100)
        frame = frame.drop(frame.index[8])
        out = _simulate_exit(frame, 0, 100, 101, "A")
        self.assertEqual(out["v430_A_state"], "CENSORED_15M_GAP")


if __name__ == "__main__":
    unittest.main()
