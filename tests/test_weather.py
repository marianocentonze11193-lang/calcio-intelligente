import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enrich_with_weather.py"
SPEC = importlib.util.spec_from_file_location("enrich_with_weather", SCRIPT)
weather = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(weather)


class WeatherEnrichmentTests(unittest.TestCase):
    def test_weather_code_is_translated_without_affecting_probabilities(self):
        self.assertEqual(weather.WEATHER_CODES[0], "sereno")
        self.assertEqual(weather.WEATHER_CODES[61], "pioggia debole")

    def test_forecast_uses_local_kickoff_hour_and_reports_informational_only(self):
        location = {
            "latitude": 45.46, "longitude": 9.19, "timezone": "Europe/Rome",
            "resolved_name": "Milano",
        }
        now = datetime(2026, 10, 17, 10, tzinfo=timezone.utc)
        with patch.object(weather, "fetch_json", return_value={
            "timezone": "Europe/Rome",
            "hourly": {
                "time": ["2026-10-18T20:00"],
                "temperature_2m": [14.0],
                "precipitation_probability": [70],
                "precipitation": [1.2],
                "wind_speed_10m": [18.0],
                "weather_code": [61],
            },
        }):
            result = weather.get_weather(location, "2026-10-18T18:00:00+00:00", now, {"forecasts": {}})
        self.assertEqual(result["temperature_c"], 14.0)
        self.assertEqual(result["precipitation_probability_pct"], 70)
        self.assertIn("non modifica", result["note"])
        self.assertEqual(result["kickoff_local"], "2026-10-18T20:00")

    def test_team_key_matches_common_source_name_variants(self):
        self.assertEqual(weather.team_key("Atlético Madrid"), weather.team_key("Ath Madrid"))
        self.assertEqual(weather.team_key("AC Milan"), weather.team_key("Milan"))

    def test_ambiguous_geocoding_does_not_guess_a_city(self):
        now = datetime(2026, 10, 17, 10, tzinfo=timezone.utc)
        with patch.object(weather, "fetch_json", return_value={
            "results": [
                {"name": "San Jose", "country": "United States", "latitude": 37.3, "longitude": -121.9, "timezone": "America/Los_Angeles"},
                {"name": "San José", "country": "Costa Rica", "latitude": 9.9, "longitude": -84.1, "timezone": "America/Costa_Rica"},
            ],
        }):
            self.assertIsNone(weather.get_location("San Jose", "Paese sconosciuto", {"locations": {}}, now))

    def test_missing_weather_reason_is_explicit(self):
        self.assertIn("Città dello stadio", weather.weather_unavailable_reason({"venue_city": "", "kickoff_utc": "2026-10-18T18:00:00Z"}))

    def test_missing_kickoff_timezone_returns_no_weather(self):
        location = {"latitude": 45.46, "longitude": 9.19, "timezone": "Europe/Rome"}
        self.assertIsNone(weather.get_weather(location, "2026-10-18T20:00", datetime.now(timezone.utc), {}))


if __name__ == "__main__":
    unittest.main()
