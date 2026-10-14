#!/usr/bin/env python3
"""Scarica risultati e partite future da football-data.co.uk e calcola stime Poisson."""
import csv
import io
import json
import math
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SOURCE = "https://www.football-data.co.uk"
LEAGUES = {"E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga", "I1": "Serie A", "F1": "Ligue 1"}
OUTPUT = Path("data/predictions.json")
USER_AGENT = "CalcioIntelligente/1.0"
MAX_DAYS_AHEAD = 30
MIN_TEAM_MATCHES = 4
PRIOR_MATCHES = 3


def current_season_code(today):
    start_year = today.year if today.month >= 7 else today.year - 1
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def fetch_csv(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read()
    return list(csv.DictReader(io.StringIO(raw.decode("cp1252", errors="replace"))))


def number(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_date(value):
    value = (value or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def poisson_probs(lam, maximum=9):
    lam = max(0.05, min(float(lam), 6.0))
    values = [math.exp(-lam)]
    for goals in range(1, maximum + 1):
        values.append(values[-1] * lam / goals)
    total = sum(values)
    return [value / total for value in values]


def percent(value):
    return round(max(0.0, min(1.0, value)) * 100, 1)


def make_forecast(home, away, league, match_date, kickoff, history, league_home_avg, league_away_avg):
    hs, aws = history[home], history[away]
    if hs["played"] < MIN_TEAM_MATCHES or aws["played"] < MIN_TEAM_MATCHES:
        return None

    def smooth(goals, games, prior):
        return (goals + PRIOR_MATCHES * prior) / (games + PRIOR_MATCHES)

    home_attack = smooth(hs["home_scored"], hs["home_games"], league_home_avg)
    home_defence = smooth(hs["home_conceded"], hs["home_games"], league_away_avg)
    away_attack = smooth(aws["away_scored"], aws["away_games"], league_away_avg)
    away_defence = smooth(aws["away_conceded"], aws["away_games"], league_home_avg)
    expected_home = max(0.15, min(4.5, home_attack * away_defence / max(0.2, league_home_avg)))
    expected_away = max(0.15, min(4.5, away_attack * home_defence / max(0.2, league_away_avg)))
    hp, ap = poisson_probs(expected_home), poisson_probs(expected_away)

    home_win = draw = away_win = over25 = btts = 0.0
    for h, ph in enumerate(hp):
        for a, pa in enumerate(ap):
            p = ph * pa
            if h > a:
                home_win += p
            elif h == a:
                draw += p
            else:
                away_win += p
            if h + a >= 3:
                over25 += p
            if h >= 1 and a >= 1:
                btts += p
    total = home_win + draw + away_win
    sample = min(hs["played"], aws["played"])
    return {
        "id": f"{match_date.isoformat()}-{league}-{home}-{away}",
        "date": match_date.isoformat(), "kickoff": kickoff or "", "league": league,
        "home_team": home, "away_team": away,
        "expected_home_goals": round(expected_home, 2),
        "expected_away_goals": round(expected_away, 2),
        "probabilities": {
            "home_win": percent(home_win / total), "draw": percent(draw / total),
            "away_win": percent(away_win / total), "over_2_5": percent(over25),
            "btts_yes": percent(btts),
        },
        "sample_matches": sample,
        "confidence": "media" if sample >= 8 else "iniziale",
        "method": "Modello Poisson con medie casa/trasferta e correzione per media di lega",
    }


def main():
    today = datetime.now(timezone.utc).date()
    season = current_season_code(today)
    last_date = today + timedelta(days=MAX_DAYS_AHEAD)
    forecasts, downloaded, failed = [], 0, []

    # Football-data pubblica le prossime partite in un CSV separato.
    try:
        all_fixtures = fetch_csv(f"{SOURCE}/fixtures.csv")
        print(f"Calendario futuro scaricato: {len(all_fixtures)} righe.")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        all_fixtures = []
        print(f"AVVISO: calendario futuro non disponibile: {error}")

    for code, league_name in LEAGUES.items():
        try:
            rows = fetch_csv(f"{SOURCE}/mmz4281/{season}/{code}.csv")
            downloaded += 1
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            failed.append(f"{code}: {error}")
            print(f"AVVISO: impossibile scaricare {code}: {error}")
            continue

        completed, fixtures = [], []
        # Conserva eventuali fixture presenti nel file del campionato.
        for row in rows:
            home = (row.get("HomeTeam") or row.get("Home Team") or "").strip()
            away = (row.get("AwayTeam") or row.get("Away Team") or "").strip()
            match_date = parse_date(row.get("Date") or row.get("date"))
            if not home or not away or not match_date:
                continue
            hg = number(row.get("FTHG") or row.get("HG") or row.get("home_goals"))
            ag = number(row.get("FTAG") or row.get("AG") or row.get("away_goals"))
            if hg is not None and ag is not None:
                completed.append((home, away, int(hg), int(ag)))
            elif today <= match_date <= last_date:
                fixtures.append((home, away, match_date, (row.get("Time") or row.get("time") or "").strip()))

        # Aggiunge il calendario generale, che contiene le prossime partite.
        known_teams = {team for match in completed for team in match[:2]}
        for row in all_fixtures:
            div = (row.get("Div") or row.get("div") or "").strip()
            if div != code:
                continue
            home = (row.get("HomeTeam") or row.get("Home Team") or row.get("home_team") or "").strip()
            away = (row.get("AwayTeam") or row.get("Away Team") or row.get("away_team") or "").strip()
            match_date = parse_date(row.get("Date") or row.get("date"))
            if home and away and match_date and today <= match_date <= last_date:
                kickoff = (row.get("Time") or row.get("time") or "").strip()
                item = (home, away, match_date, kickoff)
                if item not in fixtures:
                    fixtures.append(item)

        if not completed:
            print(f"AVVISO: {league_name}: nessun risultato concluso disponibile.")
            continue
        league_home_avg = sum(item[2] for item in completed) / len(completed)
        league_away_avg = sum(item[3] for item in completed) / len(completed)
        if league_home_avg <= 0 or league_away_avg <= 0:
            continue

        history = defaultdict(lambda: {
            "played": 0, "home_games": 0, "away_games": 0,
            "home_scored": 0, "home_conceded": 0, "away_scored": 0, "away_conceded": 0,
        })
        for home, away, hg, ag in completed:
            hs, aws = history[home], history[away]
            hs["played"] += 1
            hs["home_games"] += 1
            hs["home_scored"] += hg
            hs["home_conceded"] += ag
            aws["played"] += 1
            aws["away_games"] += 1
            aws["away_scored"] += ag
            aws["away_conceded"] += hg

        for home, away, match_date, kickoff in fixtures:
            forecast = make_forecast(home, away, league_name, match_date, kickoff, history, league_home_avg, league_away_avg)
            if forecast:
                forecasts.append(forecast)

    if downloaded == 0:
        raise SystemExit("Nessuna fonte dati raggiungibile: il file precedente è stato mantenuto.")

    forecasts.sort(key=lambda item: (item["date"], item["league"], item["home_team"]))
    result = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": SOURCE, "season": season, "model": "Poisson semplice; stime indicative, non garanzie",
        "leagues_checked": downloaded, "matches": forecasts[:80],
        "notice": "Le probabilità sono stime statistiche e non garantiscono risultati.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Stagione {season}; campionati scaricati: {downloaded}; stime generate: {len(result['matches'])}")
    if failed:
        print("Fonti non raggiungibili:", "; ".join(failed))


if __name__ == "__main__":
    main()
