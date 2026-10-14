#!/usr/bin/env python3
"""Scarica risultati e partite future da football-data.co.uk e calcola stime Poisson."""
import csv
import io
import json
import math
import re
import unicodedata
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
    # football-data può pubblicare CSV con BOM UTF-8; se decodificato come
    # cp1252 diventa "ï»¿" e rompe il nome della prima colonna ("Div").
    text = raw.decode("cp1252", errors="replace").lstrip("\ufeffï»¿")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames:
        reader.fieldnames = [name.strip().lstrip("\ufeffï»¿") for name in reader.fieldnames]
    return list(reader)


ESPN_LEAGUES = {
    "E0": "eng.1",
    "SP1": "esp.1",
    "D1": "ger.1",
    "I1": "ita.1",
    "F1": "fra.1",
}


def fetch_espn_fixtures(league_code, today, last_date):
    """Calendario alternativo ESPN, richiesto in intervalli brevi per evitare HTTP 400."""
    sport_code = ESPN_LEAGUES[league_code]
    fixtures = []
    cursor = today
    while cursor <= last_date:
        chunk_end = min(cursor + timedelta(days=6), last_date)
        date_range = f"{cursor:%Y%m%d}-{chunk_end:%Y%m%d}"
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/soccer/"
            f"{sport_code}/scoreboard?dates={date_range}&limit=100"
        )
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO: calendario ESPN {league_code} ({date_range}) non disponibile: {error}")
            cursor = chunk_end + timedelta(days=1)
            continue

        for event in payload.get("events", []):
            competitions = event.get("competitions") or []
            if not competitions:
                continue
            competition = competitions[0]
            status = (competition.get("status") or {}).get("type") or {}
            if status.get("completed"):
                continue
            raw_date = event.get("date", "")
            match_date = parse_date(raw_date)
            if not match_date or not (today <= match_date <= last_date):
                continue
            home = away = ""
            for competitor in competition.get("competitors", []):
                team = (competitor.get("team") or {}).get("displayName", "").strip()
                if competitor.get("homeAway") == "home":
                    home = team
                elif competitor.get("homeAway") == "away":
                    away = team
            if home and away:
                kickoff = raw_date[11:16] if "T" in raw_date else ""
                item = (home, away, match_date, kickoff)
                if item not in fixtures:
                    fixtures.append(item)
        cursor = chunk_end + timedelta(days=1)
    return fixtures


def team_key(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value.lower())


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
    # Accetta anche date accompagnate da ora o timestamp ISO.
    candidates = [value, value[:10]]
    for candidate in candidates:
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
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

    def smooth(goals, games, prior):
        return (goals + PRIOR_MATCHES * prior) / (games + PRIOR_MATCHES)

    # Se una squadra è promossa o il nome cambia tra i CSV, usa la media
    # della lega come prior invece di scartare del tutto la partita.
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
        if all_fixtures:
            print("Colonne calendario:", ", ".join(all_fixtures[0].keys()))
            print("Esempio calendario:", repr(all_fixtures[0]))
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

        # All'inizio della stagione, se il file corrente non ha risultati,
        # usa la stagione precedente per costruire una base statistica iniziale.
        history_season = season
        if len(completed) < MIN_TEAM_MATCHES:
            previous_season = f"{(int(season[:2]) - 1) % 100:02d}{season[:2]}"
            try:
                previous_rows = fetch_csv(f"{SOURCE}/mmz4281/{previous_season}/{code}.csv")
                previous_completed = []
                for row in previous_rows:
                    home = (row.get("HomeTeam") or row.get("Home Team") or "").strip()
                    away = (row.get("AwayTeam") or row.get("Away Team") or "").strip()
                    hg = number(row.get("FTHG") or row.get("HG") or row.get("home_goals"))
                    ag = number(row.get("FTAG") or row.get("AG") or row.get("away_goals"))
                    if home and away and hg is not None and ag is not None:
                        previous_completed.append((home, away, int(hg), int(ag)))
                if len(previous_completed) > len(completed):
                    completed = previous_completed
                    history_season = previous_season
                    print(f"{league_name}: uso {previous_season} come storico iniziale.")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                print(f"AVVISO: storico precedente {code} non disponibile: {error}")

        # Aggiunge il calendario generale, che contiene le prossime partite.
        known_teams = {team for match in completed for team in match[:2]}
        known_team_keys = {team_key(team) for team in known_teams}
        fixture_rows_for_league = 0
        for row in all_fixtures:
            div = (row.get("Div") or row.get("div") or row.get("League") or row.get("league") or "").strip()
            home = (row.get("HomeTeam") or row.get("Home Team") or row.get("home_team") or "").strip()
            away = (row.get("AwayTeam") or row.get("Away Team") or row.get("away_team") or "").strip()
            match_date = parse_date(row.get("Date") or row.get("date"))
            if not home or not away or not match_date or not (today <= match_date <= last_date):
                continue
            # Se il CSV identifica chiaramente un altro campionato, non usarlo.
            if div in LEAGUES and div != code:
                continue
            # Se la colonna lega contiene un nome esteso, prova comunque ad associare
            # la partita alle squadre dello storico del campionato corrente.
            home_key, away_key = team_key(home), team_key(away)
            if div != code and (home_key not in known_team_keys or away_key not in known_team_keys):
                continue
            fixture_rows_for_league += 1
            kickoff = (row.get("Time") or row.get("time") or "").strip()
            item = (home, away, match_date, kickoff)
            if item not in fixtures:
                fixtures.append(item)

        # Se il CSV generale non ha partite future per questa lega, usa il calendario ESPN.
        if not fixtures:
            alternate_fixtures = fetch_espn_fixtures(code, today, last_date)
            for item in alternate_fixtures:
                if item not in fixtures:
                    fixtures.append(item)
            if alternate_fixtures:
                print(f"{league_name}: calendario alternativo ESPN, {len(alternate_fixtures)} partite.")
        print(f"{league_name}: {len(completed)} risultati storici, {fixture_rows_for_league} partite future abbinate, {len(fixtures)} candidate totali.")
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

        skipped = 0
        # Associa varianti di nomi squadra ai nomi storici più vicini.
        normalized_history = {team_key(team): team for team in history}
        for home, away, match_date, kickoff in fixtures:
            home = normalized_history.get(team_key(home), home)
            away = normalized_history.get(team_key(away), away)
            forecast = make_forecast(home, away, league_name, match_date, kickoff, history, league_home_avg, league_away_avg)
            if forecast:
                forecasts.append(forecast)
            else:
                skipped += 1
        print(f"{league_name}: pronostici creati {len(fixtures) - skipped}; scartate per storico insufficiente {skipped}.")

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
