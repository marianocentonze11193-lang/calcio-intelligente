import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_competitions as sync


class CompetitionSyncTests(unittest.TestCase):
    def test_month_chunks_cover_range_without_gaps(self):
        chunks = list(sync.month_chunks(date(2026, 8, 15), date(2026, 10, 3)))
        self.assertEqual(chunks, [
            (date(2026, 8, 15), date(2026, 8, 31)),
            (date(2026, 9, 1), date(2026, 9, 30)),
            (date(2026, 10, 1), date(2026, 10, 3)),
        ])

    def test_season_ranges(self):
        self.assertEqual(sync.season_range(date(2026, 10, 17), "summer"),
                         (date(2026, 7, 1), date(2027, 6, 30)))
        self.assertEqual(sync.season_range(date(2026, 3, 10), "summer"),
                         (date(2025, 7, 1), date(2026, 6, 30)))
        self.assertEqual(sync.season_range(date(2026, 3, 10), "calendar"),
                         (date(2026, 1, 1), date(2026, 12, 31)))

    def test_cup_calendar_uses_daily_scoreboard_requests(self):
        from unittest.mock import patch
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        from datetime import timezone

        today = sync.datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome")).date()
        start, end = today - timedelta(days=7), today + timedelta(days=14)
        with patch.object(sync, "fetch_json", return_value={"events": []}) as mocked:
            code, events, diagnostics = sync.fetch_calendar_competition(
                "uefa.champions",
                {"name": "Champions League", "country": "Europa", "kind": "Coppa europea"},
                start, end,
            )
        self.assertEqual(code, "uefa.champions")
        self.assertEqual(events, [])
        self.assertEqual(diagnostics["chunks_ok"], 22)
        requested_dates = [call.args[0].split("dates=")[1].split("&")[0] for call in mocked.call_args_list]
        self.assertEqual(len(requested_dates), 22)
        self.assertTrue(all(len(value) == 8 and "-" not in value for value in requested_dates))


    def test_parse_event_valid_finished_match(self):
        event = {
            "id": "123",
            "date": "2026-10-17T18:00:00Z",
            "competitions": [{
                "status": {"type": {"completed": True}},
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Inter Milan"}, "score": "2"},
                    {"homeAway": "away", "team": {"displayName": "AC Milan"}, "score": "1"},
                ],
            }],
        }
        meta = {"name": "Serie A", "country": "Italia", "kind": "Campionato"}
        row = sync.parse_event(event, "ita.1", meta)
        self.assertEqual(row["status"], "completed")
        self.assertEqual((row["home_goals"], row["away_goals"]), (2, 1))
        self.assertEqual(row["competition_code"], "ita.1")

    def test_parse_event_rejects_invalid_score(self):
        event = {
            "id": "124", "date": "2026-10-17T18:00:00Z",
            "competitions": [{
                "status": {"type": {"completed": True}},
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Inter"}, "score": "30"},
                    {"homeAway": "away", "team": {"displayName": "Roma"}, "score": "1"},
                ],
            }],
        }
        self.assertIsNone(sync.parse_event(event, "ita.1", {"name": "Serie A", "country": "Italia", "kind": "Campionato"}))

    def test_api_football_fixture_parser(self):
        payload = [{
            "fixture": {"id": 9001, "date": "2026-10-17T18:00:00+00:00", "status": {"short": "FT"}},
            "teams": {"home": {"name": "Inter"}, "away": {"name": "Roma"}},
            "goals": {"home": 2, "away": 1},
        }]
        from unittest.mock import patch
        meta = {"name": "Serie A", "country": "Italia", "kind": "Campionato"}
        with patch.object(sync, "api_football_get", return_value=payload):
            events, diag = sync.fetch_api_football_fixtures("test-key", "ita.1", meta, 2026)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "completed")
        self.assertEqual((events[0]["home_goals"], events[0]["away_goals"]), (2, 1))
        self.assertEqual(diag["source"], "API-Football")

    def test_api_football_standings_parser(self):
        payload = [{"league": {"name": "Serie A", "standings": [[
            {"rank": 1, "team": {"id": 1, "name": "Inter"}, "points": 19, "goalsDiff": 12,
             "group": "Regular Season", "all": {"played": 8, "win": 6, "draw": 1, "lose": 1, "goals": {"for": 17, "against": 5}}, "form": "WWDWW"},
            {"rank": 2, "team": {"id": 2, "name": "Roma"}, "points": 17, "goalsDiff": 7,
             "group": "Regular Season", "all": {"played": 8, "win": 5, "draw": 2, "lose": 1, "goals": {"for": 14, "against": 7}}, "form": "WWDWL"},
            {"rank": 3, "team": {"id": 3, "name": "Milan"}, "points": 15, "goalsDiff": 5,
             "group": "Regular Season", "all": {"played": 8, "win": 4, "draw": 3, "lose": 1, "goals": {"for": 12, "against": 7}}, "form": "WDDWW"},
            {"rank": 4, "team": {"id": 4, "name": "Lazio"}, "points": 13, "goalsDiff": 2,
             "group": "Regular Season", "all": {"played": 8, "win": 4, "draw": 1, "lose": 3, "goals": {"for": 11, "against": 9}}, "form": "WLWWL"},
        ]]}}]
        from unittest.mock import patch
        meta = {"name": "Serie A", "country": "Italia", "kind": "Campionato"}
        with patch.object(sync, "api_football_get", return_value=payload):
            table = sync.fetch_api_football_standings("test-key", "ita.1", meta, 2026)
        self.assertEqual(table["rows"][0]["team"], "Inter")
        self.assertEqual(table["rows"][0]["points"], 19)
        self.assertEqual(table["diagnostics"]["status"], "available")

    def test_standings_parsed_by_stat_name(self):
        payload = {"children": [{"name": "Serie A", "standings": {"entries": [{
            "team": {"id": "1", "displayName": "Inter"},
            "stats": [
                {"name": "gamesPlayed", "value": 8},
                {"name": "wins", "value": 6},
                {"name": "ties", "value": 1},
                {"name": "losses", "value": 1},
                {"name": "pointsFor", "value": 17},
                {"name": "pointsAgainst", "value": 5},
                {"name": "pointDifferential", "value": 12},
                {"name": "points", "value": 19},
                {"name": "rank", "value": 1},
            ],
        }]}}]}
        rows = sync.parse_standings(payload, "ita.1", {"name": "Serie A", "country": "Italia", "kind": "Campionato"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["played"], 8)
        self.assertEqual(rows[0]["goals_for"], 17)
        self.assertEqual(rows[0]["points"], 19)
        self.assertEqual(rows[0]["position"], 1)


if __name__ == "__main__":
    unittest.main()
