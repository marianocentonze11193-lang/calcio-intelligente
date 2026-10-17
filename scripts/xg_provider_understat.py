#!/usr/bin/env python3
"""Fetch verified match xG from Understat without fabricating missing values.

This module is deliberately observational: it does not change published
probabilities. The model may consume these features only after walk-forward
validation demonstrates an improvement.
"""
import json
import re
import urllib.error
import urllib.request
from datetime import date

LEAGUES = {
    "Premier League": "EPL",
    "La Liga": "La_liga",
    "Bundesliga": "Bundesliga",
    "Serie A": "Serie_A",
    "Ligue 1": "Ligue_1",
}
USER_AGENT = "CalcioIntelligente/1.0 (+https://github.com/marianocentonze11193-lang/calcio-intelligente)"


def _decode_understat_json(html, variable):
    """Extract a JSON value from an Understat script assignment."""
    match = re.search(
        rf"var\s+{re.escape(variable)}\s*=\s*JSON\.parse\('(.*?)'\);",
        html,
        re.DOTALL,
    )
    if not match:
        return None
    # Understat escapes JSON for embedding in a single-quoted JS string.
    raw = match.group(1)
    # Decode JSON directly first to preserve UTF-8 team names. Some embedded
    # scripts use JavaScript-only escapes; handle those conservatively as fallback.
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        try:
            return json.loads(raw.replace("\\'", "'").replace("\\/", "/"))
        except (json.JSONDecodeError, TypeError):
            return None


def parse_match_rows(html, league_name):
    """Return normalized, verified xG observations keyed by date and team names."""
    matches = _decode_understat_json(html, "datesData")
    if not isinstance(matches, list):
        return []
    rows = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        try:
            match_date = date.fromtimestamp(int(match["datetime"])).isoformat()
            home_xg = float(match["team_h_xg"])
            away_xg = float(match["team_a_xg"])
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        home = str(match.get("h", {}).get("title", "")).strip()
        away = str(match.get("a", {}).get("title", "")).strip()
        if not home or not away or home.casefold() == away.casefold():
            continue
        if not (0 <= home_xg <= 10 and 0 <= away_xg <= 10):
            continue
        rows.append({
            "date": match_date,
            "home_team": home,
            "away_team": away,
            "home_xg": home_xg,
            "away_xg": away_xg,
            "competition": league_name,
            "source": "Understat",
        })
    return rows


def fetch_league_xg(league_name, season, timeout=15):
    """Fetch one league-season. Returns [] on unsupported league/provider outage."""
    code = LEAGUES.get(league_name)
    if not code:
        return []
    url = f"https://understat.com/league/{code}/{int(season)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []
    return parse_match_rows(html, league_name)


def xg_feature_summary(rows):
    """Coverage diagnostics; absent xG stays absent and is never replaced by goals."""
    valid = [
        row for row in rows if isinstance(row, dict)
        and isinstance(row.get("home_xg"), (int, float))
        and isinstance(row.get("away_xg"), (int, float))
        and 0 <= row["home_xg"] <= 10 and 0 <= row["away_xg"] <= 10
    ]
    return {
        "source": "Understat",
        "matches_with_xg": len(valid),
        "home_xg_mean": round(sum(r["home_xg"] for r in valid) / len(valid), 3) if valid else None,
        "away_xg_mean": round(sum(r["away_xg"] for r in valid) / len(valid), 3) if valid else None,
        "probabilities_adjusted": False,
        "status": "available" if valid else "unavailable",
    }
