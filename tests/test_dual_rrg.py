import unittest

import numpy as np
import pandas as pd

from dual_rrg import build_flow_rrg, convergence_label, flow_quadrant


class DualRRGTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.bdate_range("2026-01-01", periods=45)
        self.prices = pd.DataFrame({
            "XLK": np.linspace(100, 120, len(self.dates)),
            "XLE": np.linspace(50, 56, len(self.dates)),
        }, index=self.dates)
        self.records = {
            ticker: pd.DataFrame({"date": self.dates,
                "shares_outstanding": 10_000_000 + np.arange(len(self.dates)) ** power * 100_000})
            for ticker, power in (("XLK", 1), ("XLE", 1.2))
        }

    def test_verified_trails_and_lagged_quote(self):
        quotes = pd.concat([self.prices, pd.DataFrame({"XLK": [121], "XLE": [57]},
            index=[self.dates[-1] + pd.offsets.BDay(1)])])
        trails, flows = build_flow_rrg(quotes, self.records)
        self.assertEqual(set(trails), {"XLK", "XLE"})
        self.assertEqual(len(trails["XLK"]), 5)
        self.assertEqual(trails["XLK"].index[-1], self.dates[-1])
        self.assertGreater(flows["XLK"], 0)

    def test_missing_share_day_does_not_become_zero_flow(self):
        records = {key: value.copy() for key, value in self.records.items()}
        records["XLK"] = records["XLK"].iloc[:-3]
        trails, _ = build_flow_rrg(self.prices, records)
        self.assertNotIn("XLK", trails)

    def test_non_us_union_dates_do_not_stale_official_flow(self):
        quotes = self.prices.copy()
        quotes["SPY"] = np.linspace(400, 410, len(quotes))
        quotes["EXTRA"] = 1.0
        weekend = self.dates[-1] + pd.Timedelta(days=2)
        quotes = pd.concat([quotes, pd.DataFrame({"SPY": [np.nan], "EXTRA": [2.0]}, index=[weekend])])
        trails, _ = build_flow_rrg(quotes, self.records)
        self.assertIn("XLK", trails)

    def test_convergence_rules(self):
        self.assertEqual(flow_quadrant(99, 101), "Improving")
        self.assertEqual(convergence_label("Lagging", "Improving", 1), "🔥 机构抢跑起爆")
        self.assertEqual(convergence_label("Leading", "Lagging", -1), "⚠️ 缩量虚火诱多")
        self.assertIn("待核实", convergence_label("Leading", "N/A", float("nan")))


if __name__ == "__main__":
    unittest.main()
