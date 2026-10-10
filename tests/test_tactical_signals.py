import unittest

import numpy as np
import pandas as pd

from tactical_signals import early_rrg_signals, participation_metrics


class TacticalSignalsTests(unittest.TestCase):
    def test_participation_and_anchor(self):
        index = pd.bdate_range("2026-01-01", periods=30)
        volume = np.full(30, 100.0)
        volume[-1] = 300.0
        frame = pd.DataFrame({"High": 11.0, "Low": 9.0, "Close": 10.0,
                              "Volume": volume}, index=index)
        result = participation_metrics(frame)
        self.assertAlmostEqual(result["rvol"], 3.0)
        self.assertAlmostEqual(result["dollar_volume_m"], 0.003)
        self.assertGreater(result["volume_trend_pct"], 0)
        self.assertAlmostEqual(result["avwap"], 10.0)
        self.assertAlmostEqual(result["avwap_distance_pct"], 0)

    def test_ambush_needs_participation(self):
        index = pd.bdate_range("2026-01-01", periods=30)
        rrg = pd.DataFrame({"rs_ratio": np.full(4, 98.0),
                            "rs_momentum": [99.0, 100.0, 100.5, 101.0]}, index=index[-4:])
        close = pd.Series(np.linspace(10, 12, 30), index=index)
        bench = pd.Series(np.full(30, 10.0), index=index)
        self.assertEqual(early_rrg_signals(rrg, close, bench), (False, False))
        self.assertEqual(early_rrg_signals(rrg, close, bench, volume_trend_pct=8.0), (True, False))

    def test_climax(self):
        index = pd.bdate_range("2026-01-01", periods=30)
        rrg = pd.DataFrame({"rs_ratio": [103., 104., 105., 106.],
                            "rs_momentum": [105., 104., 103., 102.]}, index=index[-4:])
        close = pd.Series(np.linspace(10, 12, 30), index=index)
        bench = pd.Series(np.full(30, 10.0), index=index)
        self.assertEqual(early_rrg_signals(rrg, close, bench), (False, True))


if __name__ == "__main__":
    unittest.main()
