"""Focused tests for V4.4.4 support-pressure context."""
import unittest

import pandas as pd

from .v444_execution import _plan_reason, _pressure_profile


class TestV444Execution(unittest.TestCase):
    def test_pressure_profile_detects_compression_without_trend_label(self):
        rows = []
        for i in range(24):
            # Earlier bars have wider rebounds; recent bars compress toward 100.
            if i < 16:
                high = 106.0 - 0.05 * i
                close = 104.0 - 0.05 * i
            else:
                high = 103.0 - 0.20 * (i - 16)
                close = 102.0 - 0.18 * (i - 16)
            open_ = close + (0.3 if i % 2 == 0 else -0.1)
            rows.append({
                "open": open_,
                "high": max(high, open_, close),
                "low": min(99.8, open_, close),
                "close": close,
            })
        idx = pd.date_range("2026-01-01", periods=24, freq="1h", tz="UTC")
        one = pd.DataFrame(rows, index=idx)
        out = _pressure_profile(
            one,
            support_level=100.0,
            atr=2.0,
            features={"relative_4h_pct": -1.0},
        )
        self.assertGreaterEqual(out["score"], 2)
        self.assertEqual(out["lower_highs"], 1)
        self.assertEqual(out["close_compression"], 1)
        self.assertEqual(out["relative_weakness"], 1)

    def test_pressure_does_not_require_v428_trend_phase(self):
        rows = []
        for i in range(24):
            rows.append({
                "open": 102.5 - 0.04 * i,
                "high": 103.0 - 0.05 * i,
                "low": 100.0,
                "close": 102.3 - 0.05 * i,
            })
        idx = pd.date_range("2026-01-01", periods=24, freq="1h", tz="UTC")
        one = pd.DataFrame(rows, index=idx)
        out = _pressure_profile(
            one,
            support_level=100.0,
            atr=2.0,
            features={"v428_trend_phase": "RECOVERY_RECLAIM"},
        )
        self.assertIn("score", out)
        self.assertGreaterEqual(out["score"], 1)

    def test_plan_rejects_excessive_cost_r(self):
        # Tiny price risk makes fixed 14 bps round-trip cost too large in R.
        self.assertEqual(_plan_reason(100.0, 100.1, 2.0), "SKIP_COST_R")

    def test_plan_accepts_structural_risk(self):
        self.assertIsNone(_plan_reason(100.0, 101.2, 2.0))


if __name__ == "__main__":
    unittest.main()
