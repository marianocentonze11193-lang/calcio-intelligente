import importlib.util
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("backtest_walk_forward", ROOT / "scripts" / "backtest_walk_forward.py")
backtest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backtest)


class HistoricalXgBacktestTests(unittest.TestCase):
    def test_xg_history_uses_only_explicit_prior_matches(self):
        day1 = date(2025, 8, 1)
        day2 = date(2025, 8, 8)
        prior = [(day1, "alpha", "beta", 3, 0, None)]
        xg_lookup = {
            (day1.isoformat(), "alpha", "beta"): (1.1, 0.4),
            (day2.isoformat(), "alpha", "beta"): (2.8, 0.1),
        }
        history, home_avg, away_avg, count = backtest.history_for_xg(prior, xg_lookup)
        self.assertEqual(count, 1)
        self.assertAlmostEqual(home_avg, 1.1)
        self.assertAlmostEqual(away_avg, 0.4)
        self.assertEqual(history["alpha"]["home_games"], 1)
        self.assertAlmostEqual(history["alpha"]["home_scored"], 1.1)
        self.assertAlmostEqual(history["beta"]["away_scored"], 0.4)

    def test_missing_xg_is_not_replaced_with_goals(self):
        prior = [(date(2025, 8, 1), "alpha", "beta", 4, 0, None)]
        history, home_avg, away_avg, count = backtest.history_for_xg(prior, {})
        self.assertEqual(count, 0)
        self.assertIsNone(home_avg)
        self.assertIsNone(away_avg)
        self.assertEqual(history["alpha"]["home_games"], 0)
        self.assertEqual(history["alpha"]["home_scored"], 0.0)

    def test_xg_lookup_is_disabled_for_unsupported_competitions(self):
        self.assertEqual(backtest.load_league_xg("Unsupported League", date(2026, 10, 17)), {})


if __name__ == "__main__":
    unittest.main()
