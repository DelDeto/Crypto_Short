import unittest
from .v4414_m2_config import V4414_MIN_WATCH_HOURS,V4414_MAX_WATCH_HOURS,V4414_STOP_ATR,V4414_TP1_ATR,V4414_TP2_ATR
class TestV4414(unittest.TestCase):
    def test_frozen_rules(self):
        self.assertEqual((V4414_MIN_WATCH_HOURS,V4414_MAX_WATCH_HOURS),(24.0,48.0))
        self.assertEqual((V4414_STOP_ATR,V4414_TP1_ATR,V4414_TP2_ATR),(1.75,2.0,3.0))
if __name__=="__main__": unittest.main()
