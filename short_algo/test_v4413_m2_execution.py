"""Tests for V4.4.13 persistent-route diagnostic execution."""
import unittest
import pandas as pd
from .v4413_m2_execution import evaluate_v4413_m2
from .v4412_m2_execution import _simulate_variant

class TestV4413M2Execution(unittest.TestCase):
    def test_frozen_variant_matches_v12_175_prefix_values(self):
        idx=pd.date_range("2026-01-01",periods=400,freq="15min",tz="UTC")
        rows=[{"open":100.0,"high":100.5,"low":95.5,"close":96.0}]
        rows += [{"open":96.0,"high":97.0,"low":93.5,"close":94.0}] + [{"open":94.0,"high":95.0,"low":93.0,"close":94.0}]*398
        frame=pd.DataFrame(rows,index=idx)
        out=_simulate_variant(frame,0,100.0,2.0,1.75)
        self.assertEqual(out["v4412_m2_s1_75_stop_atr"],1.75)
        self.assertEqual(out["v4412_m2_s1_75_tp1_atr"],2.0)
        self.assertEqual(out["v4412_m2_s1_75_tp2_atr"],3.0)
        self.assertEqual(out["v4412_m2_s1_75_tp2_hit"],1)

if __name__=="__main__": unittest.main()
