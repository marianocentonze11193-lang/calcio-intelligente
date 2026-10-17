import importlib.util
import unittest
import tempfile
from unittest.mock import MagicMock, patch
from collections import defaultdict
from datetime import date, datetime, timezone
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
VALIDATOR_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_published_data.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location("validate_published_data", VALIDATOR_SCRIPT)
validator_module = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(validator_module)
API_ODDS_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enrich_with_api_football_odds.py"
API_ODDS_SPEC = importlib.util.spec_from_file_location("enrich_with_api_football_odds", API_ODDS_SCRIPT)
api_odds_module = importlib.util.module_from_spec(API_ODDS_SPEC)
API_ODDS_SPEC.loader.exec_module(api_odds_module)
MARKET_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_market_odds.py"
MARKET_SPEC = importlib.util.spec_from_file_location("analyze_market_odds", MARKET_SCRIPT)
market_module = importlib.util.module_from_spec(MARKET_SPEC)
MARKET_SPEC.loader.exec_module(market_module)


class PredictionModelTests(unittest.TestCase):
    def test_motivation_context_uses_table_signals_without_claiming_final_outcomes(self):
        completed = [
            ("Team A", "Team C", 2, 0), ("Team A", "Team D", 1, 0),
            ("Team A", "Team E", 3, 1), ("Team A", "Team F", 2, 1),
            ("Team A", "Team G", 1, 0),
            ("Team B", "Team C", 1, 0), ("Team B", "Team D", 2, 0),
            ("Team B", "Team E", 1, 1), ("Team B", "Team F", 0, 1),
            ("Team B", "Team G", 1, 0),
        ]
        table = module.build_motivation_table(completed)
        context = module.motivation_for_match("Team A", "Team B", table)
        self.assertEqual(context["status"], "indizi_classifica")
        self.assertEqual(context["home"]["position"], 1)
        self.assertEqual(context["home"]["played"], 5)
        self.assertIn("possibile corsa al titolo", context["home"]["signals"][0])
        self.assertIn("non vengono dichiarati", context["note"])

    def test_motivation_context_is_cautious_when_table_is_missing(self):
        context = module.motivation_for_match("Team A", "Team B", {})
        self.assertEqual(context["status"], "non_verificabile")
        self.assertIn("non dedotte", context["note"])

    def test_load_competition_calendar_uses_fresh_cache_for_european_and_national_cups(self):
        now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        payload = {
            "updated_at": "2026-10-17T10:00:00+00:00",
            "fixtures": [
                {"id": "ucl-1", "date": "2026-10-14", "kickoff": "21:00",
                 "home_team": "Inter Milan", "away_team": "Liverpool",
                 "status": "completed", "home_goals": 2, "away_goals": 1,
                 "competition": "Champions League", "kind": "Coppa europea", "source": "API-Football"},
                {"id": "cup-1", "date": "2026-10-15", "kickoff": "20:45",
                 "home_team": "Roma", "away_team": "Milan", "status": "completed",
                 "home_goals": 1, "away_goals": 0, "competition": "Coppa Italia",
                 "kind": "Coppa nazionale", "source": "ESPN"},
                {"id": "league-1", "date": "2026-10-16", "kickoff": "20:45",
                 "home_team": "Inter", "away_team": "Milan", "status": "completed",
                 "home_goals": 1, "away_goals": 0, "competition": "Serie A",
                 "kind": "Campionato", "source": "ESPN"},
                {"id": "bad-score", "date": "2026-10-16", "home_team": "Roma", "away_team": "Lazio",
                 "status": "completed", "home_goals": None, "away_goals": 0,
                 "competition": "Coppa Italia"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "competition_data.json"
            cache.write_text(__import__("json").dumps(payload), encoding="utf-8")
            with (
                patch.object(module, "COMPETITION_DATA_FILE", cache),
                patch.object(module, "fetch_competition_calendar", side_effect=AssertionError("fallback non atteso")),
            ):
                matches = module.load_competition_calendar(
                    date(2026, 10, 13), date(2026, 10, 22), now=now
                )
        self.assertEqual([item["competition"] for item in matches], ["Champions League", "Coppa Italia"])
        self.assertEqual(matches[0]["home_goals"], 2)
        self.assertEqual(matches[0]["source"], "API-Football")

    def test_load_competition_calendar_falls_back_when_cache_is_stale(self):
        now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        fallback = [{"date": "2026-10-16", "home_team": "Inter", "away_team": "Roma",
                     "competition": "Champions League", "status": "completed", "source": "ESPN"}]
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "competition_data.json"
            cache.write_text(
                __import__("json").dumps({
                    "updated_at": "2026-10-15T00:00:00+00:00",
                    "fixtures": [],
                }),
                encoding="utf-8",
            )
            with (
                patch.object(module, "COMPETITION_DATA_FILE", cache),
                patch.object(module, "fetch_competition_calendar", return_value=fallback) as fetch,
            ):
                matches = module.load_competition_calendar(
                    date(2026, 10, 13), date(2026, 10, 22), now=now
                )
        fetch.assert_called_once()
        self.assertEqual(matches, fallback)

    def test_european_fatigue_context_flags_short_rest_and_away_trip(self):
        match = {
            "date": "2026-10-14", "home_team": "Inter Milan", "away_team": "Arsenal",
            "competition": "Champions League", "status": "completed",
            "source": "ESPN", "home_goals": 1, "away_goals": 0,
        }
        context = module.european_fatigue_context(
            "Inter", "Arsenal", date(2026, 10, 16), [match]
        )
        self.assertEqual(len(context), 2)
        by_team = {item["team"]: item for item in context}
        self.assertEqual(by_team["Inter"]["days_before"], 2)
        self.assertEqual(by_team["Inter"]["venue"], "casa")
        self.assertEqual(by_team["Inter"]["attack_factor"], 0.95)
        self.assertEqual(by_team["Arsenal"]["venue"], "trasferta")
        self.assertEqual(by_team["Arsenal"]["attack_factor"], 0.92)

    def test_european_fatigue_context_ignores_same_day_old_and_unrelated_matches(self):
        matches = [
            {"date": "2026-10-16", "home_team": "Inter", "away_team": "Arsenal", "competition": "UCL"},
            {"date": "2026-10-10", "home_team": "Inter", "away_team": "Arsenal", "competition": "UCL"},
            {"date": "2026-10-14", "home_team": "Roma", "away_team": "Ajax", "competition": "UEL"},
        ]
        self.assertEqual(
            module.european_fatigue_context("Inter", "Arsenal", date(2026, 10, 16), matches),
            [],
        )

    def test_api_football_odds_parser_extracts_best_1x2_prices(self):
        payload = {"response": [{
            "bookmakers": [
                {"name": "Book A", "bets": [{"id": 1, "name": "Match Winner", "values": [
                    {"value": "Home", "odd": "2.10"},
                    {"value": "Draw", "odd": "3.20"},
                    {"value": "Away", "odd": "3.80"},
                ]}]},
                {"name": "Book B", "bets": [{"id": 1, "name": "Match Winner", "values": [
                    {"value": "Milan", "odd": "2.25"},
                    {"value": "Draw", "odd": "3.10"},
                    {"value": "Roma", "odd": "3.95"},
                ]}]},
            ]
        }]}
        prices = api_odds_module.parse_odds_payload(payload, "Milan", "Roma")
        self.assertEqual(prices, {"home": 2.25, "draw": 3.2, "away": 3.95})

    def test_api_football_parser_extracts_goal_markets(self):
        payload = {"response": [{"bookmakers": [{"bets": [
            {"id": 5, "name": "Goals Over/Under", "values": [
                {"value": "Over 2.5", "odd": "1.90"}, {"value": "Under 2.5", "odd": "1.95"},
                {"value": "Over 1.5", "odd": "1.30"}, {"value": "Under 1.5", "odd": "3.50"},
            ]},
            {"id": 8, "name": "Both Teams Score", "values": [
                {"value": "Yes", "odd": "1.80"}, {"value": "No", "odd": "2.00"},
            ]},
            {"id": 12, "name": "Double Chance", "values": [
                {"value": "Home/Draw", "odd": "1.25"}, {"value": "Draw/Away", "odd": "1.60"},
                {"value": "Home/Away", "odd": "1.35"},
            ]},
        ]}]}]}
        parsed = api_odds_module.parse_all_odds_payload(payload, "Milan", "Roma")
        self.assertEqual(parsed["markets"]["over_under_2_5"], {"over": 1.9, "under": 1.95})
        self.assertEqual(parsed["markets"]["btts"], {"yes": 1.8, "no": 2.0})
        self.assertEqual(parsed["markets"]["double_chance"], {"1x": 1.25, "x2": 1.6, "12": 1.35})

    def test_api_football_odds_request_supports_date_and_pagination(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"errors": [], "response": []}'
        with patch.object(api_odds_module.urllib.request, "urlopen", return_value=response) as mocked:
            payload = api_odds_module.api_get_odds("test-key", date="2026-10-17", page=2)
        self.assertEqual(payload["response"], [])
        request = mocked.call_args.args[0]
        self.assertIn("date=2026-10-17", request.full_url)
        self.assertIn("page=2", request.full_url)
        self.assertNotIn("test-key", request.full_url)

    def test_api_football_quote_cache_expires_after_24_hours(self):
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        fresh = {"fetched_at": (now - timedelta(hours=23)).isoformat()}
        stale = {"fetched_at": (now - timedelta(hours=25)).isoformat()}
        self.assertTrue(api_odds_module.quote_is_fresh(fresh, now))
        self.assertFalse(api_odds_module.quote_is_fresh(stale, now))
        self.assertFalse(api_odds_module.quote_is_fresh({}, now))

    def test_football_data_additional_odds_extracts_over_under_25(self):
        row = {"Avg>2.5": "1.87", "Avg<2.5": "1.91"}
        self.assertEqual(module.additional_odds_from_row(row), {"over_under_2_5": {"over": 1.87, "under": 1.91}})
        self.assertEqual(module.additional_odds_from_row({"Avg>2.5": "", "Avg<2.5": "1.9"}), {})

    def test_api_football_odds_parser_ignores_incomplete_prices(self):
        payload = {"response": [{"bookmakers": [{"bets": [{"id": 1, "name": "Match Winner", "values": [
            {"value": "Home", "odd": "1.75"},
            {"value": "Draw", "odd": "3.40"},
        ]}]}]}]}
        prices = api_odds_module.parse_odds_payload(payload, "Milan", "Roma")
        self.assertEqual(prices, {"home": 1.75, "draw": 3.4, "away": None})

    def test_api_football_odds_value_is_calculated_from_model_probability(self):
        match = {
            "status": "Pronostico valutabile",
            "home_matches_sample": 10,
            "away_matches_sample": 10,
            "probabilities": {"home_win": 55, "draw": 25, "away_win": 20},
        }
        api_odds_module.calculate_value(match, {"home": 2.0, "draw": 4.0, "away": 5.5})
        self.assertEqual(match["odds_source"], "API-Football")
        self.assertEqual(match["expected_value_1x2"], {"home": 0.1, "draw": 0.0, "away": 0.1})
        self.assertEqual({item["market"] for item in match["value_bets"]}, {"1", "2"})

    def test_additional_market_analysis_calculates_probabilities_and_ev(self):
        match = {
            "odds_markets_fetched_at": datetime.now(timezone.utc).isoformat(),
            "odds_markets": {
                "over_under_2_5": {"over": 2.0, "under": 2.0},
                "btts": {"yes": 1.8, "no": 2.2},
                "double_chance": {"1x": 1.3},
            },
            "probabilities": {
                "over_2_5": 60, "under_2_5": 40,
                "btts_yes": 55, "btts_no": 45,
                "double_chance_1x": 80,
            },
        }
        self.assertTrue(market_module.market_analysis_additional(match))
        totals = match["market_analysis_markets"]["over_under_2_5"]
        self.assertEqual(totals["market_implied_probability"], {"over": 50.0, "under": 50.0})
        self.assertAlmostEqual(totals["expected_value"]["over"], 0.2, places=4)
        self.assertEqual(match["market_analysis_markets"]["double_chance"]["1x"]["expected_value"], 0.04)

    def test_value_assessment_rejects_positive_ev_with_small_sample_or_stale_quotes(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        match = {
            "status": "Stima preliminare", "data_quality": "controllata",
            "home_matches_sample": 4, "away_matches_sample": 4,
            "odds_fetched_at": now.isoformat(), "value_bets": [{"market": "1"}],
        }
        self.assertFalse(market_module.value_assessment(match, now))
        self.assertEqual(match["value_bets"], [])
        self.assertFalse(match["value_assessment"]["eligible_for_candidate"])
        match.update({
            "status": "Pronostico valutabile", "home_matches_sample": 10,
            "away_matches_sample": 10, "odds_fetched_at": "2026-10-15T10:00:00+00:00",
        })
        self.assertFalse(market_module.value_assessment(match, now))
        self.assertIn("data di aggiornamento quote assente o oltre 24 ore", match["value_assessment"]["reasons"])

    def test_market_analysis_removes_margin_and_calculates_ev(self):
        match = {
            "odds_1x2": {"home": 2.0, "draw": 3.5, "away": 4.0},
            "odds_fetched_at": datetime.now(timezone.utc).isoformat(),
            "probabilities": {"home_win": 50, "draw": 30, "away_win": 20},
        }
        self.assertTrue(market_module.market_analysis(match))
        self.assertAlmostEqual(sum(match["market_implied_probability_1x2"].values()), 100, delta=0.1)
        self.assertAlmostEqual(match["expected_value_1x2"]["home"], 0.0, delta=0.0001)
        self.assertIn("market_overround_1x2", match)
        self.assertIn("model_vs_market_delta_1x2", match)

    def test_historical_model_market_comparison_uses_same_settled_matches(self):
        records = []
        for i in range(30):
            outcome = ("1", "X", "2")[i % 3]
            model = {"home_win": 70, "draw": 20, "away_win": 10} if outcome == "1" else {"home_win": 20, "draw": 70, "away_win": 10} if outcome == "X" else {"home_win": 20, "draw": 20, "away_win": 60}
            records.append({
                "outcome": outcome,
                "probabilities": model,
                "market_implied_probability_1x2": {"home": 33.3, "draw": 33.3, "away": 33.4},
            })
        metrics = archive_module.calculate_model_market_metrics(records)
        self.assertEqual(metrics["settled_matches_with_model_and_odds"], 30)
        self.assertEqual(metrics["model"]["accuracy_1x2"], 100.0)
        self.assertLess(metrics["model"]["brier_score_1x2"], metrics["market"]["brier_score_1x2"])
        self.assertIsNotNone(metrics["comparison"])

    def test_extra_european_leagues_have_free_csv_fallback_configured(self):
        expected = {"AUT", "DNK", "FIN", "IRL", "NOK", "POL", "RO", "SWE", "SWZ"}
        self.assertEqual(module.EXTRA_FOOTBALL_DATA_LEAGUES, expected)
        self.assertTrue(expected.issubset(module.LEAGUES))
        self.assertTrue(expected.isdisjoint(module.FOOTBALL_DATA_LEAGUES))
        self.assertEqual(module.EXTRA_HISTORY_DAYS, 365)
        self.assertEqual(archive_module.EXTRA_FOOTBALL_DATA_LEAGUES, expected)

    def test_extra_csv_source_codes_match_published_files(self):
        self.assertEqual(module.EXTRA_SOURCE_CODES, {"NOK": "NOR", "RO": "ROU"})
        self.assertEqual(archive_module.EXTRA_SOURCE_CODES, {"NOK": "NOR", "RO": "ROU"})

    def test_archive_result_index_accepts_lowercase_extra_csv_columns(self):
        index = archive_module.result_index([{
            "date": "15/10/26", "home_team": "Milan", "away_team": "Roma",
            "fthg": "0", "ftag": "2",
        }])
        key = ("2026-10-15", archive_module.team_key("Milan"), archive_module.team_key("Roma"))
        self.assertEqual(index[key], (0, 2))

    def test_published_data_timestamp_rejects_stale_future_and_invalid_values(self):
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc)
        self.assertTrue(validator_module.is_recent_timestamp("2026-10-15T17:00:00+00:00", now=now))
        self.assertFalse(validator_module.is_recent_timestamp("2026-10-13T00:00:00+00:00", now=now))
        self.assertFalse(validator_module.is_recent_timestamp("2026-10-15T19:00:00+00:00", now=now))
        self.assertFalse(validator_module.is_recent_timestamp("not-a-date", now=now))


    def test_german_team_aliases_reconcile_common_source_variants(self):
        pairs = [
            ("FC Cologne", "1. FC Köln"),
            ("Cologne", "FC Köln"),
            ("1. FC Union Berlin", "Union Berlin"),
            ("SC Paderborn 07", "Paderborn"),
            ("Mainz 05", "1. FSV Mainz 05"),
            ("Hamburg SV", "Hamburger SV"),
            ("VfB Stuttgart", "Stuttgart"),
            ("Bayer Leverkusen", "Leverkusen"),
            ("SC Freiburg", "Freiburg"),
            ("TSG Hoffenheim", "Hoffenheim"),
        ]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                self.assertEqual(module.team_key(first), module.team_key(second))
                self.assertEqual(archive_module.team_key(first), archive_module.team_key(second))
                self.assertTrue(availability_module.same_team(first, second))
                self.assertTrue(odds_module.same_team(first, second))

    def test_extra_csv_row_parser_handles_schema_variants_and_zero_scores(self):
        row = {
            " Match Date ": "15/10/26",
            "Home Team": "FC Cologne",
            "away_team": "1. FC Union Berlin",
            "home_score": "0",
            "Away Score": "2",
        }
        self.assertEqual(module.parse_date(module.row_value(row, "date", "match_date")), date(2026, 10, 15))
        self.assertEqual(module.row_value(row, "home_team"), "FC Cologne")
        self.assertEqual(module.number(module.row_value(row, "FTHG", "home_goals", "home_score")), 0)
        self.assertEqual(module.number(module.row_value(row, "FTAG", "away_goals", "away_score")), 2)

    def test_team_aliases_reconcile_espn_and_football_data_names(self):
        pairs = [
            ("Bologna", "Bologna FC 1909"),
            ("Internazionale", "Inter Milan"),
            ("AC Milan", "Milan"),
            ("Atalanta BC", "Atalanta"),
            ("Juventus FC", "Juventus"),
            ("Paris Saint-Germain", "PSG"),
            ("Ajax Amsterdam", "Ajax"),
            ("FC Groningen", "Groningen"),
            ("FC Twente", "Twente"),
            ("FC Utrecht", "Utrecht"),
            ("PSV Eindhoven", "PSV"),
            ("Feyenoord Rotterdam", "Feyenoord"),
            ("AZ Alkmaar", "AZ"),
            ("Athletic Bilbao", "Athletic Club"),
            ("Bayern Munich", "FC Bayern"),
            ("Manchester United", "Man Utd"),
        ]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                self.assertEqual(module.team_key(first), module.team_key(second))
                self.assertEqual(archive_module.team_key(first), archive_module.team_key(second))
        self.assertNotEqual(module.team_key("Milan"), module.team_key("Inter"))
        self.assertNotEqual(module.team_key("Roma"), module.team_key("Lazio"))
        self.assertEqual(module.team_key("Paris FC"), module.team_key("Paris Football Club"))
        self.assertEqual(archive_module.team_key("Paris FC"), archive_module.team_key("Paris Football Club"))
        self.assertEqual(module.team_key("Paris FC"), archive_module.team_key("Paris FC"))
        self.assertNotEqual(module.team_key("Paris FC"), module.team_key("Paris Saint-Germain"))
        self.assertNotEqual(module.team_key("Inter"), module.team_key("Internacional"))

    def test_every_configured_team_alias_is_consistent_across_all_pipelines(self):
        # Testa ogni alias dichiarato, non solo una selezione manuale di squadre.
        all_aliases = []
        seen = {}
        for group in module.TEAM_ALIAS_GROUPS:
            normalized_group = {module._raw_team_key(alias) for alias in group}
            self.assertGreaterEqual(len(normalized_group), 2)
            for alias in normalized_group:
                if alias in seen:
                    self.fail(f"Alias ambiguo {alias!r}: presente in {seen[alias]!r} e {group!r}")
                seen[alias] = group
                all_aliases.append((alias, normalized_group))

        self.assertEqual(
            {frozenset(module._raw_team_key(x) for x in g) for g in module.TEAM_ALIAS_GROUPS},
            {frozenset(archive_module._raw_team_key(x) for x in g) for g in archive_module.TEAM_ALIAS_GROUPS},
        )
        self.assertEqual(
            {frozenset(module._raw_team_key(x) for x in g) for g in module.TEAM_ALIAS_GROUPS},
            {frozenset(availability_module.normalize_team(x) for x in g) for g in availability_module.ALIASES},
        )

        for alias, group in all_aliases:
            for equivalent in group:
                with self.subTest(alias=alias, equivalent=equivalent):
                    self.assertEqual(module.team_key(alias), module.team_key(equivalent))
                    self.assertEqual(archive_module.team_key(alias), archive_module.team_key(equivalent))
                    self.assertTrue(availability_module.same_team(alias, equivalent))
                    self.assertTrue(odds_module.same_team(alias, equivalent))

    def test_team_aliases_do_not_merge_distinct_clubs(self):
        distinct_pairs = [
            ("Milan", "Inter"),
            ("Roma", "Lazio"),
            ("Paris FC", "Paris Saint-Germain"),
            ("Manchester City", "Manchester United"),
            ("Ajax", "AZ Alkmaar"),
            ("Inter", "Internacional"),
        ]
        for first, second in distinct_pairs:
            with self.subTest(first=first, second=second):
                self.assertNotEqual(module.team_key(first), module.team_key(second))
                self.assertNotEqual(archive_module.team_key(first), archive_module.team_key(second))
                self.assertFalse(availability_module.same_team(first, second))
                self.assertFalse(odds_module.same_team(first, second))

    def test_fixture_name_variant_matches_existing_history_key(self):
        history = defaultdict(lambda: {
            "played": 12, "home_games": 3, "away_games": 3,
            "home_scored": 9, "home_conceded": 6,
            "away_scored": 7, "away_conceded": 8,
        })
        history["Inter"].update({"home_games": 0, "away_games": 3, "away_scored": 8, "away_conceded": 3})
        normalized_history = {module.team_key(team): team for team in history}
        self.assertEqual(normalized_history.get(module.team_key("Internazionale")), "Inter")

    def test_availability_team_matching_uses_safe_aliases(self):
        self.assertTrue(availability_module.same_team("Paris Saint-Germain", "PSG"))
        self.assertTrue(availability_module.same_team("Inter Milan", "Internazionale"))
        self.assertFalse(availability_module.same_team("Milan", "Inter"))
        self.assertFalse(availability_module.same_team("Roma", "Lazio"))
        self.assertTrue(availability_module.same_team("Ajax Amsterdam", "Ajax"))
        self.assertTrue(availability_module.same_team("FC Groningen", "Groningen"))
        self.assertTrue(odds_module.same_team("Feyenoord Rotterdam", "Feyenoord"))
        self.assertTrue(odds_module.same_team("AZ Alkmaar", "AZ"))

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

    def test_archive_selects_season_from_match_date(self):
        self.assertEqual(archive_module.season_code_for_match("2026-10-15"), "2627")
        self.assertEqual(archive_module.season_code_for_match("2026-05-15"), "2526")

    def test_archive_supports_same_leagues_as_forecast_calendar(self):
        for league in module.LEAGUES.values():
            self.assertIn(league, archive_module.ESPN_LEAGUES)

    def test_backtest_metrics_calculate_accuracy_and_brier_score(self):
        records = [{
            "outcome": "1",
            "probabilities": {"home_win": 70, "draw": 20, "away_win": 10},
        } for _ in range(30)]
        metrics = archive_module.calculate_metrics(records)
        self.assertEqual(metrics["settled_matches"], 30)
        self.assertEqual(metrics["accuracy_1x2"], 100.0)
        self.assertAlmostEqual(metrics["brier_score_1x2"], 0.14, places=4)
        self.assertIsInstance(metrics["log_loss_1x2"], float)

    def test_supported_leagues_have_country_and_calendar_mappings(self):
        for code in ("AUT", "DNK", "G1", "FIN", "IRL", "NOK", "POL", "RO", "SWE", "SWZ"):
            self.assertIn(code, module.LEAGUES)
            self.assertIn(module.LEAGUES[code], module.LEAGUE_COUNTRIES)
            self.assertIn(code, module.ESPN_LEAGUES)

    def test_only_real_football_data_csv_divisions_use_primary_history(self):
        self.assertEqual(
            module.FOOTBALL_DATA_LEAGUES,
            frozenset({"E0", "SP1", "D1", "I1", "F1", "SC0", "N1", "P1", "B1", "T1", "G1"}),
        )
        self.assertTrue(module.FOOTBALL_DATA_LEAGUES.issubset(module.LEAGUES))

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

    def test_archive_reports_past_matches_without_verified_results(self):
        records = [
            {"date": "2026-10-15", "outcome": None, "league": "Test", "home_team": "Casa", "away_team": "Ospite"},
            {"date": "2026-10-16", "outcome": None},
            {"date": "2026-10-17", "outcome": None},
            {"date": "2026-10-14", "outcome": "1"},
        ]
        unresolved = archive_module.unresolved_past_matches(records, date(2026, 10, 16))
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["home_team"], "Casa")

    def test_value_bet_metrics_settle_archived_1x2_candidates(self):
        records = []
        for i in range(30):
            records.append({
                "outcome": "1" if i < 15 else "X",
                "value_bets": [{"market": "1", "best_odds": 2.0}],
            })
        metrics = archive_module.calculate_value_bet_metrics(records)
        self.assertEqual(metrics["settled_bets"], 30)
        self.assertEqual(metrics["wins"], 15)
        self.assertEqual(metrics["losses"], 15)
        self.assertEqual(metrics["net_units_per_one_unit_stake"], 0.0)
        self.assertEqual(metrics["roi_percent"], 0.0)

    def test_metrics_can_be_split_by_european_context(self):
        records = []
        for i in range(30):
            records.append({
                "outcome": "1", "probabilities": {"home_win": 60, "draw": 25, "away_win": 15},
                "european_context": [{"team": "Inter"}] if i % 2 == 0 else [],
            })
        result = archive_module.calculate_metrics_by_european_context(records)
        self.assertEqual(result["groups"]["recent_european_match"]["context_matches_archived"], 15)
        self.assertIsNone(result["groups"]["recent_european_match"]["accuracy_1x2"])
        self.assertIsNone(result["groups"]["no_recent_european_match"]["accuracy_1x2"])

    def test_metrics_are_hidden_until_minimum_sample(self):
        records = [{
            "outcome": "1",
            "probabilities": {"home_win": 70, "draw": 20, "away_win": 10},
        } for _ in range(29)]
        metrics = archive_module.calculate_metrics(records)
        self.assertEqual(metrics["settled_matches"], 29)
        self.assertIsNone(metrics["accuracy_1x2"])
        self.assertIsNone(metrics["brier_score_1x2"])
        self.assertEqual(metrics["minimum_matches_required"], 30)

    def test_invalid_probabilities_do_not_unlock_league_metrics(self):
        records = [
            {"league": "Serie A", "outcome": "1",
             "probabilities": {"home_win": 80, "draw": 30, "away_win": 10}}
            for _ in range(40)
        ]
        metrics = archive_module.calculate_metrics_by_league(records)
        self.assertNotIn("Serie A", metrics)

    def test_metrics_are_separated_by_league(self):
        records = (
            [{"league": "Serie A", "outcome": "1",
              "probabilities": {"home_win": 70, "draw": 20, "away_win": 10}} for _ in range(30)] +
            [{"league": "Premier League", "outcome": "2",
              "probabilities": {"home_win": 20, "draw": 20, "away_win": 60}} for _ in range(30)]
        )
        metrics = archive_module.calculate_metrics_by_league(records)
        self.assertEqual(metrics["Serie A"]["settled_matches"], 30)
        self.assertEqual(metrics["Premier League"]["settled_matches"], 30)
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

    def test_odds_parser_supports_additional_markets(self):
        event = {"bookmakers": [{"markets": [
            {"key": "totals", "outcomes": [
                {"name": "Over", "point": 2.5, "price": 1.91},
                {"name": "Under", "point": 2.5, "price": 1.95},
            ]},
            {"key": "btts", "outcomes": [
                {"name": "Yes", "price": 1.8}, {"name": "No", "price": 2.0},
            ]},
            {"key": "double_chance", "outcomes": [
                {"name": "Home/Draw", "price": 1.35},
                {"name": "Draw/Away", "price": 1.55},
                {"name": "Home/Away", "price": 1.4},
            ]},
        ]}]}
        parsed = odds_module.best_additional_markets(event)
        self.assertEqual(parsed["over_under_2_5"], {"over": 1.91, "under": 1.95})
        self.assertEqual(parsed["btts"], {"yes": 1.8, "no": 2.0})
        self.assertEqual(parsed["double_chance"], {"1x": 1.35, "x2": 1.55, "12": 1.4})

    def test_api_football_does_not_overwrite_other_provider_prices(self):
        match = {
            "status": "Pronostico valutabile", "home_matches_sample": 10, "away_matches_sample": 10,
            "probabilities": {"home_win": 50, "draw": 25, "away_win": 25},
            "odds_1x2": {"home": 2.2, "draw": 3.4, "away": 3.1},
            "odds_source": "The Odds API",
        }
        api_odds_module.calculate_value(
            match, {"home": 2.0, "draw": 3.0, "away": 3.5},
            {"over_under_2_5": {"over": 1.9, "under": 1.9}},
        )
        self.assertEqual(match["odds_source"], "The Odds API")
        self.assertEqual(match["odds_1x2"], {"home": 2.2, "draw": 3.4, "away": 3.1})
        self.assertIn("over_under_2_5", match["odds_markets"])

    def test_value_assessment_requires_complete_fresh_1x2_quotes(self):
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        match = {
            "status": "Pronostico valutabile", "home_matches_sample": 10, "away_matches_sample": 10,
            "data_quality": "controllata", "odds_fetched_at": "2026-10-16T11:30:00+00:00",
        }
        self.assertFalse(market_module.value_assessment(match, now))
        self.assertIn("quote 1X2 complete non disponibili", match["value_assessment"]["reasons"])
        match["odds_1x2"] = {"home": 2.0, "draw": 3.4, "away": 3.8}
        self.assertTrue(market_module.value_assessment(match, now))

    def test_additional_market_analysis_rejects_stale_quotes(self):
        match = {
            "odds_markets": {"over_under_2_5": {"over": 1.9, "under": 1.9}},
            "odds_markets_fetched_at": "2026-10-13T10:00:00+00:00",
            "probabilities": {"over_2_5": 50, "under_2_5": 50},
        }
        self.assertFalse(market_module.market_analysis_additional(match))
        self.assertNotIn("market_analysis_markets", match)

    def test_fixture_sources_merge_without_duplicates_and_fill_missing_kickoff(self):
        primary = [
            ("Sporting CP", "Benfica", date(2026, 10, 18), ""),
            ("Porto", "Braga", date(2026, 10, 19), "20:00"),
        ]
        secondary = [
            ("Sporting Lisbon", "Benfica", date(2026, 10, 18), "18:00"),
            ("Gil Vicente", "Portimonense", date(2026, 10, 20), "19:00"),
        ]
        merged = module.merge_fixture_sources(primary, secondary)
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0][3], "18:00")
        self.assertEqual(merged[1][0], "Porto")
        self.assertEqual(merged[2][0], "Gil Vicente")

    def test_fixture_merge_rejects_same_team_and_empty_names(self):
        merged = module.merge_fixture_sources([
            ("", "Benfica", date(2026, 10, 18), "18:00"),
            ("Porto", "Porto", date(2026, 10, 18), "20:00"),
        ], [])
        self.assertEqual(merged, [])

    def test_poisson_probabilities_sum_to_one(self):
        probabilities = module.poisson_probs(1.7)
        self.assertAlmostEqual(sum(probabilities), 1.0, places=9)
        self.assertTrue(all(value >= 0 for value in probabilities))

    def test_preliminary_estimates_do_not_auto_select_markets(self):
        history = defaultdict(lambda: {
            "played": 20, "home_games": 0, "away_games": 0,
            "home_scored": 0, "home_conceded": 0,
            "away_scored": 0, "away_conceded": 0,
        })
        history["Casa"].update({
            "played": 20, "home_games": 3, "home_scored": 9,
            "home_conceded": 4,
        })
        forecast = module.make_forecast(
            "Casa", "Trasferta", "Test League", date(2026, 10, 16), "18:00",
            history, 1.4, 1.1,
        )
        self.assertEqual(forecast["status"], "NO BET")
        self.assertEqual(forecast["no_bet_type"], "campione_insufficiente")
        self.assertEqual(forecast["away_matches_sample"], 0)
        self.assertEqual(forecast["probabilities"], {})
        self.assertEqual(forecast["suggested_markets"], [])

    def test_two_or_fewer_relevant_matches_per_side_are_no_bet(self):
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
        self.assertEqual(forecast["no_bet_type"], "dati_mancanti")

    def test_no_bet_distinguishes_missing_data_from_small_sample(self):
        history = defaultdict(lambda: {
            "played": 0, "home_games": 0, "away_games": 0,
            "home_scored": 0, "home_conceded": 0,
            "away_scored": 0, "away_conceded": 0,
        })
        history["Casa"].update({"played": 1, "home_games": 1, "home_scored": 1, "home_conceded": 0})
        forecast = module.make_forecast(
            "Casa", "Trasferta", "Test League", date(2026, 10, 16), "18:00",
            history, 1.4, 1.1,
        )
        self.assertEqual(forecast["status"], "NO BET")
        self.assertEqual(forecast["no_bet_type"], "campione_insufficiente")
        self.assertIn("Campione insufficiente", forecast["reason"])

    def test_no_bet_flags_unreliable_context_when_both_sides_have_tiny_samples(self):
        history = defaultdict(lambda: {
            "played": 0, "home_games": 0, "away_games": 0,
            "home_scored": 0, "home_conceded": 0,
            "away_scored": 0, "away_conceded": 0,
        })
        history["Casa"].update({"played": 1, "home_games": 1, "home_scored": 1, "home_conceded": 1})
        history["Trasferta"].update({"played": 1, "away_games": 1, "away_scored": 1, "away_conceded": 1})
        forecast = module.make_forecast(
            "Casa", "Trasferta", "Test League", date(2026, 10, 16), "18:00",
            history, 1.4, 1.1,
        )
        self.assertEqual(forecast["status"], "NO BET")
        self.assertEqual(forecast["no_bet_type"], "campione_insufficiente")
        self.assertIn("Campione insufficiente", forecast["reason"])
        category, reason = module.classify_no_bet(5, 5, data_quality_ok=False)
        self.assertEqual(category, "stima_non_affidabile")
        self.assertIn("non adatta a una stima affidabile", reason)

    def test_no_bet_categories_are_explicit(self):
        self.assertEqual(module.classify_no_bet(0, 0)[0], "dati_mancanti")
        self.assertEqual(module.classify_no_bet(1, 3)[0], "campione_insufficiente")
        self.assertEqual(module.classify_no_bet(5, 5, data_quality_ok=False)[0], "stima_non_affidabile")

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
        self.assertEqual(forecast["status"], "Stima preliminare")
        self.assertTrue(forecast["probabilities"])
        self.assertTrue(all(0 <= p <= 100 for p in forecast["probabilities"].values()))
        self.assertFalse(any("Champions League" in name or "Europa League" in name or "Conference League" in name
                             for name in module.LEAGUES.values()))


    def test_cup_competitions_cover_uefa_and_major_national_cups(self):
        self.assertEqual(
            module.EUROPEAN_ESPN_COMPETITIONS,
            {
                "uefa.champions": "Champions League",
                "uefa.europa": "Europa League",
                "uefa.europa.conf": "Conference League",
            },
        )
        self.assertIn("Coppa Italia", module.COMPETITION_ESPN_CODES.values())
        self.assertIn("FA Cup", module.COMPETITION_ESPN_CODES.values())
        self.assertIn("Copa del Rey", module.COMPETITION_ESPN_CODES.values())
        self.assertIn("DFB-Pokal", module.COMPETITION_ESPN_CODES.values())
        self.assertEqual(
            set(module.COMPETITION_ESPN_CODES.values()),
            set(archive_module.ESPN_LEAGUES).intersection(module.COMPETITION_ESPN_CODES.values()),
        )

    def test_cup_forecasts_are_always_preliminary_and_never_auto_recommend_markets(self):
        for competition, expected_type in (
            ("Champions League", "europea"),
            ("Coppa Italia", "coppa_nazionale"),
        ):
            forecast = {
                "status": "Pronostico valutabile",
                "probabilities": {"home_win": 50.0, "draw": 25.0, "away_win": 25.0},
                "suggested_markets": [{"market": "1"}],
                "value_bets": [{"market": "1"}],
                "expected_value_1x2": {"home": 0.1},
                "confidence": "alta",
                "data_quality": "buona",
            }
            result = module.declassify_cup_forecast(forecast, competition)
            self.assertEqual(result["status"], "Stima preliminare")
            self.assertEqual(result["competition_type"], expected_type)
            self.assertEqual(result["suggested_markets"], [])
            self.assertEqual(result["value_bets"], [])
            self.assertEqual(result["expected_value_1x2"], {})
            self.assertEqual(result["data_quality"], "coppa_non_validata")
            self.assertIn("non validato", result["cup_model_note"])

    def test_market_analysis_suppresses_ev_for_unvalidated_cup_competitions(self):
        for competition_type in ("europea", "coppa_nazionale"):
            match = {
                "competition_type": competition_type,
                "status": "Stima preliminare",
                "probabilities": {"home_win": 55, "draw": 25, "away_win": 20},
                "odds_1x2": {"home": 2.0, "draw": 3.5, "away": 4.0},
                "suggested_markets": [{"market": "1"}],
                "value_bets": [{"market": "1"}],
                "expected_value_1x2": {"home": 0.1},
            }
            self.assertFalse(market_module.market_analysis(match))
            self.assertEqual(match["suggested_markets"], [])
            self.assertEqual(match["value_bets"], [])
            self.assertNotIn("expected_value_1x2", match)
            self.assertFalse(match["value_assessment"]["eligible_for_candidate"])

    def test_cup_no_bet_stays_without_probabilities(self):
        forecast = {
            "status": "NO BET", "probabilities": {},
            "suggested_markets": [], "value_bets": [],
            "reason": "Storico non disponibile",
        }
        result = module.declassify_cup_forecast(forecast, "Conference League")
        self.assertEqual(result["status"], "NO BET")
        self.assertEqual(result["probabilities"], {})
        self.assertEqual(result["competition_type"], "europea")

    def test_recent_national_cup_match_declassifies_league_forecast(self):
        history = defaultdict(lambda: {
            "played": 10, "home_games": 0, "away_games": 0,
            "home_scored": 0, "home_conceded": 0,
            "away_scored": 0, "away_conceded": 0,
        })
        history["Casa"].update({
            "played": 10, "home_games": 10, "home_scored": 18, "home_conceded": 9,
        })
        history["Ospite"].update({
            "played": 10, "away_games": 10, "away_scored": 13, "away_conceded": 12,
        })
        cup_match = {
            "date": "2026-10-14", "home_team": "Casa", "away_team": "Ospite",
            "competition": "Coppa Italia", "status": "completed",
            "home_goals": 1, "away_goals": 0, "source": "ESPN",
        }
        forecast = module.make_forecast(
            "Casa", "Ospite", "Serie A", date(2026, 10, 16), "20:45",
            history, 1.5, 1.2, european_matches=[cup_match],
        )
        self.assertEqual(forecast["status"], "Stima preliminare")
        self.assertEqual(len(forecast["recent_competition_context"]), 2)
        self.assertEqual(forecast["european_context"], [])
        self.assertEqual(forecast["recent_competition_context"][0]["competition"], "Coppa Italia")
        self.assertEqual(forecast["competition_type"], "campionato")
        self.assertEqual(forecast["suggested_markets"], [])


if __name__ == "__main__":
    unittest.main()
