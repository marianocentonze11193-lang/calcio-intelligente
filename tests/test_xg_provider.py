import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "xg_provider_understat.py"
SPEC = importlib.util.spec_from_file_location("xg_provider_understat", SCRIPT)
xg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(xg)


class UnderstatXgTests(unittest.TestCase):
    def test_parses_real_xg_without_substituting_goals(self):
        payload = [{
            "datetime": "1792195200",
            "team_h_xg": "1.42",
            "team_a_xg": "0.63",
            "h": {"title": "Home FC"},
            "a": {"title": "Away FC"},
        }]
        encoded = json.dumps(payload).replace("\\", "\\\\").replace("'", "\\'")
        html = "var datesData = JSON.parse('" + encoded + "');"
        rows = xg.parse_match_rows(html, "Premier League")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_xg"], 1.42)
        self.assertEqual(rows[0]["away_xg"], 0.63)
        self.assertEqual(rows[0]["source"], "Understat")

    def test_missing_or_invalid_xg_is_not_fabricated(self):
        self.assertEqual(xg.parse_match_rows("var datesData = JSON.parse('[]');", "Premier League"), [])
        summary = xg.xg_feature_summary([])
        self.assertEqual(summary["status"], "unavailable")
        self.assertIsNone(summary["home_xg_mean"])
        self.assertFalse(summary["probabilities_adjusted"])

    def test_rejects_implausible_xg(self):
        payload = [{
            "datetime": "1792195200", "team_h_xg": "99", "team_a_xg": "0.5",
            "h": {"title": "Home FC"}, "a": {"title": "Away FC"},
        }]
        encoded = json.dumps(payload).replace("\\", "\\\\").replace("'", "\\'")
        self.assertEqual(xg.parse_match_rows("var datesData = JSON.parse('" + encoded + "');", "Premier League"), [])

    def test_unsupported_competition_fails_closed(self):
        self.assertEqual(xg.fetch_league_xg("Unsupported League", 2026), [])


if __name__ == "__main__":
    unittest.main()
