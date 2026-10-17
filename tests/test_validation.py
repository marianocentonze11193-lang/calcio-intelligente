import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_published_data as validator


class PublishedDataValidationTests(unittest.TestCase):
    def test_competition_archive_accepts_valid_completed_and_scheduled_fixtures(self):
        archive = {
            "updated_at": "2026-10-17T10:00:00+00:00",
            "summary": {"competitions_configured": 32},
            "fixtures": [
                {"id": "ucl-1", "date": "2026-10-14", "competition_code": "uefa.champions",
                 "home_team": "Inter", "away_team": "Liverpool", "status": "completed",
                 "home_goals": 2, "away_goals": 1},
                {"id": "cup-1", "date": "2026-10-20", "competition": "Coppa Italia",
                 "home_team": "Roma", "away_team": "Milan", "status": "scheduled"},
            ],
        }
        self.assertEqual(validator.validate_competition_archive(archive), [])

    def test_competition_archive_rejects_duplicate_ids_bad_dates_and_invalid_scores(self):
        archive = {
            "updated_at": "not-a-date",
            "fixtures": [
                {"id": "same", "date": "2026-10-14", "competition": "Champions League",
                 "home_team": "Inter", "away_team": "Liverpool", "status": "completed",
                 "home_goals": 25, "away_goals": 1},
                {"id": "same", "date": "not-a-date", "competition": "Champions League",
                 "home_team": "Inter", "away_team": "Liverpool", "status": "completed",
                 "home_goals": 1, "away_goals": 0},
            ],
        }
        errors = validator.validate_competition_archive(archive)
        self.assertTrue(any("updated_at" in error for error in errors))
        self.assertTrue(any("id duplicato" in error for error in errors))
        self.assertTrue(any("data non valida" in error for error in errors))
        self.assertTrue(any("punteggio valido" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
