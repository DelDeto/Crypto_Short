import unittest

from .live_m2 import classify_tier


class TestLiveM2Tier(unittest.TestCase):
    def test_tiers(self):
        base = {"market_risk_off": 1, "s4_macro_bear": 1}
        self.assertEqual(classify_tier({**base, "ema20_distance_atr": 1.50, "anti_bottom_total": 18})["tier"], "A+")
        self.assertEqual(classify_tier({**base, "ema20_distance_atr": 1.00, "anti_bottom_total": 18})["tier"], "A")
        self.assertEqual(classify_tier({**base, "ema20_distance_atr": 1.50, "anti_bottom_total": 10})["tier"], "B")
        self.assertEqual(classify_tier({**base, "ema20_distance_atr": 1.00, "anti_bottom_total": 10})["tier"], "C")
        self.assertIsNone(classify_tier({"market_risk_off": 0, "s4_macro_bear": 1})["tier"])


if __name__ == "__main__":
    unittest.main()
