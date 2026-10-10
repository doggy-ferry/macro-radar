import unittest
from datetime import date

import pandas as pd

from sector_options import sector_option_signal


class SectorOptionTests(unittest.TestCase):
    def test_call_ambush_and_deep_otm_exclusion(self):
        frame = pd.DataFrame({"Expiration": ["2026-10-23"] * 3,
            "Type": ["Call", "Put", "Put"], "strike": [105, 95, 50],
            "volume": [3000, 1000, 100000], "openInterest": [1000, 500, 1000]})
        result = sector_option_signal(frame, 100, date(2026, 10, 10))
        self.assertEqual(result["label"], "🔥 Call 抢筹伏兵")
        self.assertEqual(result["contracts"], 2)

    def test_unavailable_is_not_balance(self):
        result = sector_option_signal(pd.DataFrame(), 100, date(2026, 10, 10))
        self.assertTrue(str(result["label"]).startswith("N/A"))

    def test_put_defense(self):
        frame = pd.DataFrame({"Expiration": ["2026-10-23"], "Type": ["Put"],
            "strike": [95], "volume": [5000], "openInterest": [1000]})
        self.assertEqual(sector_option_signal(frame, 100, date(2026, 10, 10))["label"], "🛡️ Put 巨量避险")


if __name__ == "__main__":
    unittest.main()
