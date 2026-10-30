import unittest
import pandas as pd
from strategy.mtf_fvg_strategy import MTFFVGStrategy

class TestMTFFVGStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = MTFFVGStrategy()

    def test_missing_timeframe_returns_error(self):
        dfs = {"5m": pd.DataFrame(), "1h": pd.DataFrame()}
        decision = self.strategy.decide("ETH/USDT", dfs, as_of="2026-10-15T12:00:00Z")
        self.assertEqual(decision.status, "ERROR")
        self.assertEqual(decision.reason_code, "MISSING_TIMEFRAME")

if __name__ == "__main__":
    unittest.main()