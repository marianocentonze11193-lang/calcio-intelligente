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
from zoneinfo import ZoneInfo

SOURCE = "https://www.football-data.co.uk"
# Solo massime divisioni nazionali con risultati storici disponibili nella fonte primaria.
LEAGUES = {
    "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga",
    "I1": "Serie A", "F1": "Ligue 1", "SC0": "Scottish Premiership",
    "N1": "Eredivisie", "P1": "Primeira Liga", "B1": "Belgian Pro League",
    "T1": "Super Lig turca",
}
LEAGUE_COUNTRIES = {
    "Premier League": "Inghilterra", "La Liga": "Spagna", "Bundesliga": "Germania",
    "Serie A": "Italia", "Ligue 1": "Francia", "Scottish Premiership": "Scozia",
    "Eredivisie": "Paesi Bassi", "Primeira Liga": "Portogallo",
    "Belgian Pro League": "Belgio", "Super Lig turca": "Turchia",
}
OUTPUT = Path("data/predictions.json")
USER_AGENT = "CalcioIntelligente/1.0"
MAX_DAYS_AHEAD = 5
MIN_TEAM_MATCHES = 3
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
    "E0": "eng.1", "SP1": "esp.1", "D1": "ger.1", "I1": "ita.1", "F1": "fra.1",
    "SC0": "sco.1", "N1": "ned.1", "P1": "por.1", "B1": "bel.1", "T1": "tur.1",
}
ESPN_TIMEZONES = {
    "E0": "Europe/London", "SC0": "Europe/London", "SP1": "Europe/Madrid",
    "D1": "Europe/Berlin", "I1": "Europe/Rome", "F1": "Europe/Paris",
    "N1": "Europe/Amsterdam", "P1": "Europe/Lisbon", "B1": "Europe/Brussels",
    "T1": "Europe/Istanbul",
}


def fetch_espn_fixtures(league_code, today, last_date):
    """Calendario ESPN: usa una richiesta per intervallo e ripiega sulle singole date se necessario."""
    sport_code = ESPN_LEAGUES.get(league_code)
    if not sport_code:
        return []

    def request_payload(date_param):
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/soccer/"
            f"{sport_code}/scoreboard?dates={date_param}&limit=100"
        )
        request = urllib.request.Request(url)
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        payload = request_payload(f"{today:%Y%m%d}-{last_date:%Y%m%d}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        print(f"AVVISO: intervallo ESPN {league_code} non disponibile; provo le date singole: {error}")
        payload = {"events": []}
        cursor = today
        while cursor <= last_date:
            try:
                daily = request_payload(f"{cursor:%Y%m%d}")
                payload["events"].extend(daily.get("events", []))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as daily_error:
                print(f"AVVISO: calendario ESPN {league_code} ({cursor:%Y%m%d}) non disponibile: {daily_error}")
            cursor += timedelta(days=1)

    fixtures = []
    for event in payload.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        competition = competitions[0]
        status = (competition.get("status") or {}).get("type") or {}
        if status.get("completed"):
            continue
        raw_date = event.get("date", "")
        try:
            event_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            local_dt = event_dt.astimezone(ZoneInfo(ESPN_TIMEZONES.get(league_code, "Europe/Rome")))
            match_date = local_dt.date()
        except (ValueError, TypeError):
            match_date = parse_date(raw_date)
            local_dt = None
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
            kickoff = local_dt.strftime("%H:%M") if local_dt else (raw_date[11:16] if "T" in raw_date else "")
            item = (home, away, match_date, kickoff)
            if item not in fixtures:
                fixtures.append(item)
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

def odds_from_row(row):
    """Quote 1X2 da football-data: preferisce le medie disponibili, poi il bookmaker B365."""
    for keys in (("AvgH", "AvgD", "AvgA"), ("B365H", "B365D", "B365A"),
                 ("MaxH", "MaxD", "MaxA")):
        values = [number(row.get(key)) for key in keys]
        if all(value is not None and value > 1 for value in values):
            return {"home": values[0], "draw": values[1], "away": values[2]}
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


def calculate_elo(completed, initial=1500.0, k_factor=22.0, home_advantage=55.0):
    """Stima Elo sequenziale usando i risultati disponibili, senza usare dati futuri."""
    ratings = defaultdict(lambda: initial)
    for home, away, home_goals, away_goals in completed:
        home_rating = ratings[home] + home_advantage
        away_rating = ratings[away]
        expected_home = 1 / (1 + 10 ** ((away_rating - home_rating) / 400))
        actual_home = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
        delta = k_factor * (actual_home - expected_home)
        ratings[home] += delta
        ratings[away] -= delta
    return dict(ratings)


def calculate_recent_form(completed, limit=5):
    """Ultime gare disponibili per squadra; i CSV sorgente sono letti in ordine temporale."""
    recent = defaultdict(list)
    for home, away, home_goals, away_goals in completed:
        home_points = 3 if home_goals > away_goals else 1 if home_goals == away_goals else 0
        away_points = 3 if away_goals > home_goals else 1 if home_goals == away_goals else 0
        recent[home].append({"gf": home_goals, "ga": away_goals, "points": home_points})
        recent[away].append({"gf": away_goals, "ga": home_goals, "points": away_points})
    return {
        team: {
            "games": len(items[-limit:]),
            "goals_for": sum(x["gf"] for x in items[-limit:]) / len(items[-limit:]),
            "goals_against": sum(x["ga"] for x in items[-limit:]) / len(items[-limit:]),
            "points_per_match": sum(x["points"] for x in items[-limit:]) / len(items[-limit:]),
        }
        for team, items in recent.items() if items
    }


def make_forecast(home, away, league, match_date, kickoff, history, league_home_avg, league_away_avg, elo_ratings=None, recent_form=None):
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
    # Correzione Elo moderata: informa la forza relativa senza sostituire le statistiche gol.
    if elo_ratings:
        rating_gap = elo_ratings.get(home, 1500.0) - elo_ratings.get(away, 1500.0) + 50.0
        elo_factor = math.exp(max(-250.0, min(250.0, rating_gap)) * math.log(1.15) / 400.0)
        expected_home = max(0.15, min(4.5, expected_home * elo_factor))
        expected_away = max(0.15, min(4.5, expected_away / elo_factor))
    # Forma delle ultime cinque gare, con correzione volutamente moderata.
    home_form = (recent_form or {}).get(home, {})
    away_form = (recent_form or {}).get(away, {})
    if home_form and away_form:
        league_goal_avg = max(0.5, (league_home_avg + league_away_avg) / 2)
        home_attack_form = home_form["goals_for"] / league_goal_avg
        home_defence_form = away_form["goals_against"] / max(0.5, league_home_avg)
        away_attack_form = away_form["goals_for"] / league_goal_avg
        away_defence_form = home_form["goals_against"] / max(0.5, league_away_avg)
        home_form_factor = max(0.82, min(1.18, math.sqrt(home_attack_form * home_defence_form)))
        away_form_factor = max(0.82, min(1.18, math.sqrt(away_attack_form * away_defence_form)))
        expected_home = max(0.15, min(4.5, expected_home * home_form_factor))
        expected_away = max(0.15, min(4.5, expected_away * away_form_factor))
    hp, ap = poisson_probs(expected_home), poisson_probs(expected_away)

    home_win = draw = away_win = over15 = over25 = over35 = btts = 0.0
    home_scores = away_scores = 0.0
    scorelines = []
    for h, ph in enumerate(hp):
        for a, pa in enumerate(ap):
            p = ph * pa
            scorelines.append((p, h, a))
            if h > a:
                home_win += p
            elif h == a:
                draw += p
            else:
                away_win += p
            if h + a >= 2:
                over15 += p
            if h + a >= 3:
                over25 += p
            if h + a >= 4:
                over35 += p
            if h >= 1 and a >= 1:
                btts += p
            if h >= 1:
                home_scores += p
            if a >= 1:
                away_scores += p
    total = home_win + draw + away_win
    # Il prior di lega consente una stima preliminare anche con pochi dati specifici.
    # NO BET resta per casi senza campione pertinente, non solo perché il campione è piccolo.
    home_sample = hs["home_games"]
    away_sample = aws["away_games"]
    sample = min(home_sample, away_sample)
    valid = (home_sample + away_sample) >= 2
    scorelines.sort(reverse=True)
    probabilities = {
        "home_win": percent(home_win / total), "draw": percent(draw / total),
        "away_win": percent(away_win / total),
        "double_chance_1x": percent((home_win + draw) / total),
        "double_chance_x2": percent((draw + away_win) / total),
        "double_chance_12": percent((home_win + away_win) / total),
        "over_1_5": percent(over15), "over_2_5": percent(over25),
        "over_3_5": percent(over35), "under_1_5": percent(1 - over15),
        "under_2_5": percent(1 - over25), "under_3_5": percent(1 - over35),
        "btts_yes": percent(btts), "btts_no": percent(1 - btts),
        "home_scores": percent(home_scores), "away_scores": percent(away_scores),
    } if valid else {}
    summary = ""
    suggested = []
    if valid:
        probs_1x2 = [(home_win / total, "1"), (draw / total, "X"), (away_win / total, "2")]
        best_probability, best_outcome = max(probs_1x2)
        outcome_text = {"1": f"{home} leggermente favorito", "X": "pareggio da considerare", "2": f"{away} leggermente favorita"}[best_outcome]
        goal_text = "scenario da almeno 2 gol" if over15 >= 0.70 else "totale gol incerto"
        btts_text = "entrambe a segno plausibile" if btts >= 0.60 else "Goal/No Goal non netto"
        summary = f"{outcome_text}; {goal_text}; {btts_text}. Commento automatico basato solo sul modello statistico, non su notizie o quote."
        if over15 >= 0.70: suggested.append("Over 1,5")
        if btts >= 0.70: suggested.append("Goal")
        if best_probability >= 0.70: suggested.append(best_outcome)
    return {
        "id": f"{match_date.isoformat()}-{league}-{home}-{away}",
        "date": match_date.isoformat(), "kickoff": kickoff or "", "league": league,
        "country": LEAGUE_COUNTRIES.get(league, "Competizioni UEFA" if league in ("Champions League", "Europa League", "Conference League") else "Altro"),
        "home_team": home, "away_team": away,
        "expected_home_goals": round(expected_home, 2),
        "expected_away_goals": round(expected_away, 2),
        "probabilities": probabilities,
        "analysis": summary,
        "suggested_markets": suggested,
        "top_scorelines": [
            {"score": f"{h}-{a}", "probability": percent(p)}
            for p, h, a in scorelines[:3]
        ] if valid else [],
        "sample_matches": sample,
        "home_matches_sample": home_sample,
        "away_matches_sample": away_sample,
        "status": ("Pronostico valutabile" if sample >= 3 else "Stima preliminare") if valid else "NO BET",
        "reason": "" if valid else "Storico insufficiente: non risultano almeno due osservazioni pertinenti per le squadre.",
        "confidence": "più solida" if sample >= 8 else "intermedia" if sample >= 5 else "bassa (campione ridotto)",
        "elo_home": round((elo_ratings or {}).get(home, 1500.0), 1),
        "elo_away": round((elo_ratings or {}).get(away, 1500.0), 1),
        "home_recent_form": (recent_form or {}).get(home),
        "away_recent_form": (recent_form or {}).get(away),
        "method": "Poisson casa/trasferta + prior di lega + Elo + forma ultime 5 gare; sperimentale non ancora validato",
    }


def main():
    today = datetime.now(timezone.utc).date()
    season = current_season_code(today)
    last_date = today + timedelta(days=MAX_DAYS_AHEAD)
    forecasts, downloaded, failed = [], 0, []
    fixture_odds = {}

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
                quote = odds_from_row(row)
                if quote:
                    fixture_odds[(match_date.isoformat(), team_key(home), team_key(away))] = quote

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
            quote = odds_from_row(row)
            if quote:
                fixture_odds[(match_date.isoformat(), team_key(home), team_key(away))] = quote

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

        elo_ratings = calculate_elo(completed)
        recent_form = calculate_recent_form(completed)
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
            forecast = make_forecast(home, away, league_name, match_date, kickoff, history, league_home_avg, league_away_avg, elo_ratings, recent_form)
            if forecast:
                quote = fixture_odds.get((match_date.isoformat(), team_key(home), team_key(away)))
                if quote and forecast.get("probabilities"):
                    probs = forecast["probabilities"]
                    ev = {
                        "home": round(probs["home_win"] / 100 * quote["home"] - 1, 4),
                        "draw": round(probs["draw"] / 100 * quote["draw"] - 1, 4),
                        "away": round(probs["away_win"] / 100 * quote["away"] - 1, 4),
                    }
                    forecast["odds_1x2"] = quote
                    forecast["odds_source"] = "football-data.co.uk"
                    forecast["expected_value_1x2"] = ev
                    forecast["value_bets"] = [
                        {"market": label, "model_probability": probs[prob_key],
                         "best_odds": quote[price_key], "expected_value": ev[price_key]}
                        for price_key, prob_key, label in (
                            ("home", "home_win", "1"), ("draw", "draw", "X"), ("away", "away_win", "2")
                        )
                        if ev[price_key] >= 0.03 and forecast.get("status") == "Pronostico valutabile"
                    ]
                forecasts.append(forecast)
            else:
                skipped += 1
        print(f"{league_name}: pronostici creati {len(fixtures) - skipped}; scartate per storico insufficiente {skipped}.")

    # Il calendario si concentra sulle massime divisioni nazionali selezionate.
    # Le coppe UEFA restano escluse finché non è disponibile uno storico inter-lega verificato.

    if downloaded == 0:
        raise SystemExit("Nessuna fonte dati raggiungibile: il file precedente è stato mantenuto.")

    forecasts.sort(key=lambda item: (
        item.get("country", "Altro"),
        item["league"],
        item["date"],
        item["kickoff"] or "99:99",
        item["home_team"],
        item["away_team"],
    ))
    result = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": SOURCE, "season": season,
        "model": "Poisson casa/trasferta con prior di lega e correzione Elo; stime sperimentali, non garanzie",
        "leagues_checked": downloaded,
        "no_bet_notice": "Le partite NO BET sono mostrate perché i dati non bastano o non sono comparabili. Nessun esito consigliato.",
        "matches": [item for item in forecasts if item.get("status") in ("Pronostico valutabile", "Stima preliminare")][:120],
        "no_bet_matches": [item for item in forecasts if item.get("status") == "NO BET"][:80],
        "notice": "Le probabilità sono stime statistiche e non garantiscono risultati.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Stagione {season}; campionati scaricati: {downloaded}; stime generate: {len(result['matches'])}")
    if failed:
        print("Fonti non raggiungibili:", "; ".join(failed))


if __name__ == "__main__":
    main()
