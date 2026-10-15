import importlib.util
import unittest
from collections import defaultdict
from datetime import date
from pathlib import Path

GEMINI_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enrich_with_gemini.py"
GEMINI_SPEC = importlib.util.spec_from_file_location("enrich_with_gemini", GEMINI_SCRIPT)
gemini_module = importlib.util.module_from_spec(GEMINI_SPEC)
GEMINI_SPEC.loader.exec_module(gemini_module)
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_predictions.py"
SPEC = importlib.util.spec_from_file_location("update_predictions", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
ODDS_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enrich_with_odds.py"
ODDS_SPEC = importlib.util.spec_from_file_location("enrich_with_odds", ODDS_SCRIPT)
odds_module = importlib.util.module_from_spec(ODDS_SPEC)
ODDS_SPEC.loader.exec_module(odds_module)
ARCHIVE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_predictions.py"
ARCHIVE_SPEC = importlib.util.spec_from_file_location("archive_predictions", ARCHIVE_SCRIPT)
archive_module = importlib.util.module_from_spec(ARCHIVE_SPEC)
ARCHIVE_SPEC.loader.exec_module(archive_module)
AVAILABILITY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enrich_with_availability.py"
AVAILABILITY_SPEC = importlib.util.spec_from_file_location("enrich_with_availability", AVAILABILITY_SCRIPT)
availability_module = importlib.util.module_from_spec(AVAILABILITY_SPEC)
AVAILABILITY_SPEC.loader.exec_module(availability_module)


class PredictionModelTests(unittest.TestCase):
    def test_availability_team_matching_uses_safe_aliases(self):
        self.assertTrue(availability_module.same_team("Paris Saint-Germain", "PSG"))
        self.assertTrue(availability_module.same_team("Inter Milan", "Internazionale"))
        self.assertFalse(availability_module.same_team("Milan", "Inter"))
        self.assertFalse(availability_module.same_team("Roma", "Lazio"))

    def test_duplicate_injury_reports_are_deduplicated(self):
        cache = {}
        injury = {"team": "Milan", "player": "Player A", "type": "Injury", "reason": "Ankle"}
        self.assertTrue(availability_module.add_unique_injury(cache, "123", injury))
        self.assertFalse(availability_module.add_unique_injury(cache, "123", injury.copy()))
        self.assertEqual(len(cache["injuries_by_fixture"]["123"]), 1)

    def test_availability_without_key_is_explicitly_unconfigured(self):
        result = availability_module.availability_for({"home_team": "A", "away_team": "B"}, {}, False)
        self.assertEqual(result["status"], "non_configurata")
        self.assertEqual(result["injuries"], [])
        self.assertIsNone(result["lineups"])

    def test_gemini_json_parser_accepts_plain_and_markdown_json(self):
        self.assertEqual(gemini_module.extract_json('{"analyses": []}'), {"analyses": []})
        self.assertEqual(gemini_module.extract_json('```json\n{"analyses": []}\n```'), {"analyses": []})


    def test_archive_result_index_parses_final_scores(self):
        index = archive_module.result_index([{
            "Date": "15/10/2026", "HomeTeam": "Milan", "AwayTeam": "Roma",
            "FTHG": "2", "FTAG": "1",
        }])
        key = ("2026-10-15", archive_module.team_key("Milan"), archive_module.team_key("Roma"))
        self.assertEqual(index[key], (2, 1))

    def test_backtest_metrics_calculate_accuracy_and_brier_score(self):
        records = [{
            "outcome": "1",
            "probabilities": {"home_win": 70, "draw": 20, "away_win": 10},
        }]
        metrics = archive_module.calculate_metrics(records)
        self.assertEqual(metrics["settled_matches"], 1)
        self.assertEqual(metrics["accuracy_1x2"], 100.0)
        self.assertAlmostEqual(metrics["brier_score_1x2"], 0.14, places=4)

    def test_supported_leagues_have_country_and_calendar_mappings(self):
        for code in ("AUT", "DNK", "G1", "FIN", "IRL", "NOK", "POL", "RO", "SWE", "SWZ"):
            self.assertIn(code, module.LEAGUES)
            self.assertIn(module.LEAGUES[code], module.LEAGUE_COUNTRIES)
            self.assertIn(code, module.ESPN_LEAGUES)

    def test_forecast_initializes_value_bets_list(self):
        history = defaultdict(lambda: {
            "played": 12, "home_games": 3, "away_games": 3,
            "home_scored": 9, "home_conceded": 6,
            "away_scored": 7, "away_conceded": 8,
        })
        forecast = module.make_forecast(
            "Casa", "Trasferta", "Test League", date(2026, 10, 16), "18:00",
            history, 1.4, 1.1,
        )
        self.assertEqual(forecast["value_bets"], [])
        self.assertEqual(forecast["availability_data"]["status"], "non_integrata")

    def test_odds_team_aliases_are_explicit_and_ordered(self):
        self.assertTrue(odds_module.same_team("Inter Milan", "Internazionale"))
        self.assertTrue(odds_module.same_team("Paris Saint-Germain", "PSG"))
        self.assertFalse(odds_module.same_team("Milan", "Inter"))
        self.assertFalse(odds_module.same_team("Roma", "Milan"))

    def test_metrics_are_separated_by_league(self):
        records = [
            {"league": "Serie A", "outcome": "1",
             "probabilities": {"home_win": 70, "draw": 20, "away_win": 10}},
            {"league": "Premier League", "outcome": "2",
             "probabilities": {"home_win": 20, "draw": 20, "away_win": 60}},
        ]
        metrics = archive_module.calculate_metrics_by_league(records)
        self.assertEqual(metrics["Serie A"]["settled_matches"], 1)
        self.assertEqual(metrics["Premier League"]["accuracy_1x2"], 100.0)

    def test_odds_parser_selects_best_1x2_prices(self):
        event = {
            "home_team": "Milan", "away_team": "Roma",
            "bookmakers": [
                {"markets": [{"key": "h2h", "outcomes": [
                    {"name": "Milan", "price": 2.1},
                    {"name": "Draw", "price": 3.2},
                    {"name": "Roma", "price": 3.5},
                ]}]},
                {"markets": [{"key": "h2h", "outcomes": [
                    {"name": "Milan", "price": 2.2},
                    {"name": "Draw", "price": 3.1},
                    {"name": "Roma", "price": 3.7},
                ]}]},
            ],
        }
        self.assertEqual(odds_module.best_prices(event), {"home": 2.2, "draw": 3.2, "away": 3.7})

    def test_poisson_probabilities_sum_to_one(self):
        probabilities = module.poisson_probs(1.7)
        self.assertAlmostEqual(sum(probabilities), 1.0, places=9)
        self.assertTrue(all(value >= 0 for value in probabilities))

    def test_small_samples_get_preliminary_estimate_instead_of_false_no_bet(self):
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
        self.assertEqual(forecast["status"], "Stima preliminare")
        self.assertTrue(forecast["probabilities"])
        self.assertEqual(forecast["home_matches_sample"], 3)
        self.assertEqual(forecast["away_matches_sample"], 2)

    def test_recent_form_uses_latest_five_matches(self):
        form = module.calculate_recent_form([
            ("Casa", "Avversaria1", 1, 0),
            ("Casa", "Avversaria2", 2, 0),
            ("Casa", "Avversaria3", 0, 1),
        ])
        self.assertEqual(form["Casa"]["games"], 3)
        self.assertAlmostEqual(form["Casa"]["goals_for"], 1.0)
        self.assertAlmostEqual(form["Casa"]["points_per_match"], 2.0)

    def test_elo_ratings_update_after_results(self):
        ratings = module.calculate_elo([
            ("Casa", "Trasferta", 2, 0),
            ("Casa", "Trasferta", 1, 0),
        ])
        self.assertGreater(ratings["Casa"], 1500)
        self.assertLess(ratings["Trasferta"], 1500)

    def test_no_bet_when_no_relevant_sample_exists(self):
        history = defaultdict(lambda: {
            "played": 0, "home_games": 0, "away_games": 0,
            "home_scored": 0, "home_conceded": 0,
            "away_scored": 0, "away_conceded": 0,
        })
        forecast = module.make_forecast(
            "Casa", "Trasferta", "Test League", date(2026, 10, 16), "18:00",
            history, 1.4, 1.1,
        )
        self.assertEqual(forecast["status"], "NO BET")
        self.assertEqual(forecast["probabilities"], {})

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
        self.assertFalse(any("Champions League" in name or "Europa League" in name or "Conference League" in name
                             for name in module.LEAGUES.values()))


if __name__ == "__main__":
    unittest.main()
