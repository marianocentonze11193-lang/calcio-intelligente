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
