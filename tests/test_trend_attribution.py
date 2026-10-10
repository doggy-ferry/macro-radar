import unittest

import numpy as np
import pandas as pd

from trend_attribution import beta_return_decomposition, slope_regime, slope_statistics, sma_slope_panel


class TrendAttributionTests(unittest.TestCase):
    def test_sma_slope_uses_five_prior_ma_observations(self):
        index = pd.bdate_range("2024-01-01", periods=260)
        close = pd.Series(np.arange(1, 261, dtype=float), index=index)
        panel = sma_slope_panel(close)
        self.assertTrue(np.isnan(panel["SMA200 Slope"].iloc[203]))
        expected = (panel["SMA20"].iloc[-1] - panel["SMA20"].iloc[-6]) / (5 * panel["SMA20"].iloc[-6]) * 100
        self.assertAlmostEqual(panel["SMA20 Slope"].iloc[-1], expected)
        stats = slope_statistics(panel)
        self.assertEqual(len(stats), 3)
        self.assertEqual(stats.loc[stats["Moving Average"].eq("200DMA"), "Observations"].iloc[0], 56)

    def test_regime_rules(self):
        bullish = pd.DataFrame({"SMA20 Slope": [-.1], "SMA50 Slope": [.02], "SMA200 Slope": [.01]})
        self.assertEqual(slope_regime(bullish), "BULLISH_DIP")
        self.assertEqual(slope_regime(pd.DataFrame({"SMA20 Slope": [.1], "SMA50 Slope": [-.1],
                                                    "SMA200 Slope": [-.1]})), "MIXED")
        self.assertEqual(slope_regime(pd.DataFrame({"SMA20 Slope": [-.1], "SMA50 Slope": [-.1],
                                                    "SMA200 Slope": [-.1]})), "SYSTEMIC_BREAK")

    def test_beta_attribution_reconciles_exactly(self):
        index = pd.bdate_range("2025-01-01", periods=253)
        market_returns = np.sin(np.arange(252) / 8) * .01 + .0002
        market = pd.Series(100 * np.r_[1, np.cumprod(1 + market_returns)], index=index)
        target_returns = market_returns * 1.7
        target = pd.Series(50 * np.r_[1, np.cumprod(1 + target_returns)], index=index)
        result = beta_return_decomposition(target, market)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["beta"], 1.7, places=9)
        self.assertAlmostEqual(result["specific_pp"], 0, places=9)
        self.assertAlmostEqual(result["explained_pp"] + result["specific_pp"], result["target_1d"])
        self.assertIsNone(beta_return_decomposition(target.iloc[10:], market))

    def test_missing_quote_does_not_turn_two_days_into_one(self):
        index = pd.bdate_range("2025-01-01", periods=255)
        daily = np.sin(np.arange(254) / 8) * .01 + .0002
        market = pd.Series(100 * np.r_[1, np.cumprod(1 + daily)], index=index)
        target = market.mul(1.2).copy()
        target.iloc[-2] = np.nan
        result = beta_return_decomposition(target, market)
        self.assertIsNotNone(result)
        self.assertEqual(result["asof"], index[-3])


if __name__ == "__main__":
    unittest.main()
