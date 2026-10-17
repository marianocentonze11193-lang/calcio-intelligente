import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backtest_walk_forward as backtest


class WalkForwardAuditTests(unittest.TestCase):
    def test_rows_to_results_normalizes_historical_market_odds(self):
        rows = [{
            "Date": "2025-08-01", "HomeTeam": "Home FC", "AwayTeam": "Away FC",
            "FTHG": "2", "FTAG": "1", "AvgH": "2.00", "AvgD": "3.50", "AvgA": "4.00",
        }]
        results = backtest.rows_to_results(rows, "E0", date(2025, 7, 1), date(2025, 8, 2))
        self.assertEqual(len(results), 1)
        market = results[0][5]
        self.assertAlmostEqual(sum(market.values()), 100.0)
        self.assertGreater(market["home_win"], market["draw"])
        self.assertGreater(market["draw"], market["away_win"])

    def test_rows_without_complete_odds_remain_valid_without_market_baseline(self):
        rows = [{
            "Date": "2025-08-01", "HomeTeam": "Home FC", "AwayTeam": "Away FC",
            "FTHG": "2", "FTAG": "1", "AvgH": "2.00", "AvgD": "", "AvgA": "4.00",
        }]
        results = backtest.rows_to_results(rows, "E0", date(2025, 7, 1), date(2025, 8, 2))
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0][5])

    def test_history_builder_ignores_optional_market_fields(self):
        rows = [
            (date(2025, 8, 1), "home", "away", 2, 0, {"home_win": 50, "draw": 30, "away_win": 20}),
        ]
        history, completed = backtest.history_for(rows)
        self.assertEqual(history["home"]["home_scored"], 2)
        self.assertEqual(completed, [("home", "away", 2, 0)])

    def test_blend_is_normalized_and_rejects_invalid_probabilities(self):
        model_probs = {"home_win": 50, "draw": 25, "away_win": 25}
        market_probs = {"home_win": 40, "draw": 30, "away_win": 30}
        blend = backtest.blend_probabilities(model_probs, market_probs)
        self.assertAlmostEqual(sum(blend.values()), 100.0)
        self.assertAlmostEqual(blend["home_win"], 45.0)
        self.assertIsNone(backtest.blend_probabilities(model_probs, {"home_win": 80, "draw": 30, "away_win": 10}))

    def test_metric_summary_includes_top_class_calibration(self):
        rows = [
            backtest.score_probabilities({"home_win": 70, "draw": 20, "away_win": 10}, "1"),
            backtest.score_probabilities({"home_win": 60, "draw": 30, "away_win": 10}, "X"),
        ]
        summary = backtest.metric_summary(rows)
        self.assertEqual(summary["matches"], 2)
        self.assertEqual(len(summary["top_class_calibration"]), 2)
        self.assertEqual(summary["top_class_calibration"][0]["observed_accuracy_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
