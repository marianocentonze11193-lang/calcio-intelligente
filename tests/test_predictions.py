import importlib.util
import unittest
from collections import defaultdict
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_predictions.py"
SPEC = importlib.util.spec_from_file_location("update_predictions", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PredictionModelTests(unittest.TestCase):
    def test_poisson_probabilities_sum_to_one(self):
        probabilities = module.poisson_probs(1.7)
        self.assertAlmostEqual(sum(probabilities), 1.0, places=9)
        self.assertTrue(all(value >= 0 for value in probabilities))

    def test_forecast_requires_home_and_away_samples_in_correct_context(self):
        history = defaultdict(lambda: {
            "played": 20, "home_games": 0, "away_games": 0,
            "home_scored": 0, "home_conceded": 0,
            "away_scored": 0, "away_conceded": 0,
        })
        history["Casa"].update({
            "played": 20, "home_games": 3, "home_scored": 5,
            "home_conceded": 7,
        })
        history["Trasferta"].update({
            "played": 20, "away_games": 2, "away_scored": 3,
            "away_conceded": 9,
        })
        forecast = module.make_forecast(
            "Casa", "Trasferta", "Test League", date(2026, 10, 16), "18:00",
            history, 1.4, 1.1,
        )
        self.assertEqual(forecast["status"], "NO BET")
        self.assertEqual(forecast["probabilities"], {})
        self.assertEqual(forecast["home_matches_sample"], 3)
        self.assertEqual(forecast["away_matches_sample"], 2)

    def test_forecast_probabilities_are_bounded(self):
        history = defaultdict(lambda: {
            "played": 12, "home_games": 3, "away_games": 3,
            "home_scored": 9, "home_conceded": 6,
            "away_scored": 7, "away_conceded": 8,
        })
        forecast = module.make_forecast(
            "Casa", "Trasferta", "Test League", date(2026, 10, 16), "18:00",
            history, 1.4, 1.1,
        )
        self.assertEqual(forecast["status"], "Pronostico valutabile")
        self.assertTrue(forecast["probabilities"])
        self.assertTrue(all(0 <= p <= 100 for p in forecast["probabilities"].values()))


if __name__ == "__main__":
    unittest.main()
