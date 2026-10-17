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
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCE = "https://www.football-data.co.uk"
# Solo massime divisioni nazionali con risultati storici disponibili nella fonte primaria.
LEAGUES = {
    "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga",
    "I1": "Serie A", "F1": "Ligue 1", "SC0": "Scottish Premiership",
    "N1": "Eredivisie", "P1": "Primeira Liga", "B1": "Belgian Pro League",
    "T1": "Super Lig turca", "AUT": "Bundesliga austriaca",
    "DNK": "Superliga danese", "G1": "Super League greca", "FIN": "Veikkausliiga finlandese",
    "IRL": "Premier Division irlandese", "NOK": "Eliteserien norvegese",
    "POL": "Ekstraklasa polacca", "RO": "Liga I rumena", "SWE": "Allsvenskan svedese",
    "SWZ": "Super League svizzera",
}
# Divisioni con CSV storici dedicati su football-data.co.uk. Le altre leghe
# usano il calendario/storico ESPN quando disponibili, senza chiamate CSV che
# restituiscono sistematicamente 404.
FOOTBALL_DATA_LEAGUES = frozenset({
    "E0", "SP1", "D1", "I1", "F1", "SC0", "N1", "P1", "B1", "T1", "G1",
})
# Football-data pubblica queste competizioni in CSV cumulativi /new/{CODICE}.csv.
# Si limita lo storico importato all'ultimo anno per evitare di mescolare stagioni
# troppo lontane, mantenendo copertura utile anche per i campionati a calendario solare.
EXTRA_FOOTBALL_DATA_LEAGUES = frozenset({
    "AUT", "DNK", "FIN", "IRL", "NOK", "POL", "RO", "SWE", "SWZ",
})
# Codici effettivi dei CSV cumulativi pubblicati dalla fonte (diversi dai codici interni ESPN).
EXTRA_SOURCE_CODES = {"NOK": "NOR", "RO": "ROU"}
EXTRA_HISTORY_DAYS = 365
LEAGUE_COUNTRIES = {
    "Premier League": "Inghilterra", "La Liga": "Spagna", "Bundesliga": "Germania",
    "Serie A": "Italia", "Ligue 1": "Francia", "Scottish Premiership": "Scozia",
    "Eredivisie": "Paesi Bassi", "Primeira Liga": "Portogallo",
    "Belgian Pro League": "Belgio", "Super Lig turca": "Turchia", "Bundesliga austriaca": "Austria",
    "Superliga danese": "Danimarca", "Super League greca": "Grecia",
    "Veikkausliiga finlandese": "Finlandia", "Premier Division irlandese": "Irlanda",
    "Eliteserien norvegese": "Norvegia", "Ekstraklasa polacca": "Polonia",
    "Liga I rumena": "Romania", "Allsvenskan svedese": "Svezia",
    "Super League svizzera": "Svizzera",
}
OUTPUT = Path("data/predictions.json")
COMPETITION_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "competition_data.json"
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
    "SC0": "sco.1", "N1": "ned.1", "P1": "por.1", "B1": "bel.1", "T1": "tur.1", "AUT": "aut.1", "DNK": "den.1", "G1": "gre.1",
    "FIN": "fin.1", "IRL": "irl.1", "NOK": "nor.1", "POL": "pol.1",
    "RO": "rou.1", "SWE": "swe.1", "SWZ": "sui.1",
}
ESPN_TIMEZONES = {
    "E0": "Europe/London", "SC0": "Europe/London", "SP1": "Europe/Madrid",
    "D1": "Europe/Berlin", "I1": "Europe/Rome", "F1": "Europe/Paris",
    "N1": "Europe/Amsterdam", "P1": "Europe/Lisbon", "B1": "Europe/Brussels",
    "T1": "Europe/Istanbul", "AUT": "Europe/Vienna", "DNK": "Europe/Copenhagen",
    "G1": "Europe/Athens", "FIN": "Europe/Helsinki", "IRL": "Europe/Dublin",
    "NOK": "Europe/Oslo", "POL": "Europe/Warsaw", "RO": "Europe/Bucharest",
    "SWE": "Europe/Stockholm", "SWZ": "Europe/Zurich",
}


def fetch_espn_fixtures(league_code, today, last_date):
    """Calendario ESPN per giorno: endpoint affidabile anche quando gli intervalli non funzionano."""
    sport_code = ESPN_LEAGUES.get(league_code)
    if not sport_code:
        return []
    fixtures = []
    cursor = today
    while cursor <= last_date:
        date_param = f"{cursor:%Y%m%d}"
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/soccer/"
            f"{sport_code}/scoreboard?dates={date_param}&limit=100"
        )
        try:
            request = urllib.request.Request(url)
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO: calendario ESPN {league_code} ({date_param}) non disponibile: {error}")
            cursor += timedelta(days=1)
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
        cursor += timedelta(days=1)
    return fixtures

def merge_fixture_sources(primary, secondary):
    """Unisce calendari diversi senza duplicare gare per data e squadre normalizzate."""
    merged = []
    positions = {}
    for item in list(primary or []) + list(secondary or []):
        if len(item) < 4:
            continue
        home, away, match_date, kickoff = item
        if not home or not away or not match_date:
            continue
        key = (match_date.isoformat(), team_key(home), team_key(away))
        if not key[1] or not key[2] or key[1] == key[2]:
            continue
        if key in positions:
            index = positions[key]
            old_item = merged[index]
            # Preferisce l'orario già disponibile; se manca, recupera quello dell'altra fonte.
            if not old_item[3] and kickoff:
                merged[index] = (old_item[0], old_item[1], old_item[2], kickoff)
            continue
        positions[key] = len(merged)
        merged.append((home.strip(), away.strip(), match_date, (kickoff or "").strip()))
    return merged


def fetch_espn_historical_results(league_code, start_date, end_date):
    """Recupera risultati ESPN verificati giorno per giorno per le ultime tre settimane."""
    sport_code = ESPN_LEAGUES.get(league_code)
    if not sport_code:
        return []
    # Il scoreboard ESPN accetta in modo affidabile una singola data, non sempre intervalli.
    # Limita il fallback a 21 giorni e usa concorrenza moderata per non rallentare il job.
    start_date = max(start_date, end_date - timedelta(days=20))
    days = []
    cursor = start_date
    while cursor <= end_date:
        days.append(cursor)
        cursor += timedelta(days=1)

    def fetch_day(day):
        url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{sport_code}/scoreboard"
               f"?dates={day:%Y%m%d}&limit=100")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO: storico ESPN {league_code} {day}: {error}")
            return []
        day_results = []
        for event in payload.get("events", []):
            competitions = event.get("competitions") or []
            if not competitions:
                continue
            competition = competitions[0]
            status = (competition.get("status") or {}).get("type") or {}
            if not status.get("completed"):
                continue
            raw_date = event.get("date", "")
            try:
                event_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                match_date = event_dt.astimezone(
                    ZoneInfo(ESPN_TIMEZONES.get(league_code, "Europe/Rome"))
                ).date()
            except (ValueError, TypeError):
                match_date = parse_date(raw_date)
            if not match_date or not (start_date <= match_date <= end_date):
                continue
            home = away = None
            for competitor in competition.get("competitors", []):
                team = (competitor.get("team") or {}).get("displayName", "").strip()
                score = number(competitor.get("score"))
                if competitor.get("homeAway") == "home":
                    home = (team, score)
                elif competitor.get("homeAway") == "away":
                    away = (team, score)
            if not home or not away or not home[0] or not away[0]:
                continue
            if home[1] is None or away[1] is None:
                continue
            if not (0 <= home[1] <= 15 and 0 <= away[1] <= 15):
                continue
            if team_key(home[0]) == team_key(away[0]):
                continue
            day_results.append((home[0], away[0], int(home[1]), int(away[1]), match_date))
        return day_results

    results, seen = [], set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_day, day) for day in days]
        for future in as_completed(futures):
            for home, away, hg, ag, match_date in future.result():
                key = (match_date.isoformat(), team_key(home), team_key(away))
                if key in seen:
                    continue
                seen.add(key)
                results.append((home, away, hg, ag, match_date))
    results.sort(key=lambda row: row[4])
    return results


# Alias canonici espliciti per riconciliare i nomi restituiti da ESPN e football-data.
# La chiave canonica resta distinta tra club diversi (es. Milan e Inter).
TEAM_ALIAS_GROUPS = [
    {"inter", "intermilan", "fcinternazionale", "internazionale", "internazionalefc"},
    {"milan", "acmilan", "acmilan1899"},
    {"bologna", "bolognafc", "bolognafc1909"},
    {"atalanta", "atalantabc", "atalantabergamasca"},
    {"juventus", "juve", "juventusfc"},
    {"roma", "asroma", "associazionesportivaroma"},
    {"napoli", "sscnapoli", "societasportivacalcionapoli"},
    {"fiorentina", "acfiorentina"},
    {"lazio", "sslazio"},
    {"torino", "torinofc"},
    {"verona", "hellasverona"},
    {"psg", "parissaintgermain", "parissaintgermainfc"},
    {"parisfc", "parisfootballclub"},
    {"ajax", "ajaxamsterdam", "afcajax"},
    {"groningen", "fcgroningen"},
    {"twente", "fctwente"},
    {"utrecht", "fcutrecht"},
    {"psv", "psveindhoven"},
    {"feyenoord", "feyenoordrotterdam"},
    {"az", "azalkmaar"},
    {"manutd", "manchesterunited", "manchesterutd"},
    {"mancity", "manchestercity"},
    {"athleticclub", "athleticbilbao"},
    {"atleticodemadrid", "atleticomadrid"},
    {"fcbayern", "bayernmunich", "bayernmunchen"},
    {"sportingcp", "sportinglisbon"},
    {"salzburg", "redbullsalzburg"},
    {"tottenham", "tottenhamhotspur"},
    {"wolves", "wolverhamptonwanderers"},
    {"newcastle", "newcastleunited"},
    {"westham", "westhamunited"},
    {"leicester", "leicestercity"},
    {"brighton", "brightonandhovealbion"},
    {"eintrachtfrankfurt", "eintracht"},
    {"borussiadortmund", "dortmund"},
    {"borussiamonchengladbach", "monchengladbach", "gladbach"},
    {"rbleipzig", "rasenballsportleipzig", "rbleipzig"},
    {"olympiquedemarseille", "marseille"},
    {"olympiquelyonnais", "lyon"},
    {"realbetis", "betis"},
    {"realsociedad", "sociedad"},
    {"celta", "celtavigo"},
    {"cologne", "fccologne", "koln", "fckoln", "1fckoln", "1fccologne"},
    {"unionberlin", "fcunionberlin", "1fcunionberlin"},
    {"paderborn", "paderborn07", "scpaderborn", "scpaderborn07"},
    {"mainz", "mainz05", "fsvmainz05", "1fsvmainz05"},
    {"hamburgsv", "hamburgersv", "hsv"},
    {"stuttgart", "vfbstuttgart", "vfbstuttgart1893"},
    {"augsburg", "fcaugsburg"},
    {"leverkusen", "bayerleverkusen"},
    {"freiburg", "scfreiburg"},
    {"hoffenheim", "tsghoffenheim"},
    {"elversberg", "svelversberg"},
    {"schalke", "schalke04", "fcs04"},
    {"internacional", "internacionalportoalegre"}
]


def _raw_team_key(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value.lower())


_TEAM_CANONICAL = {
    alias: _raw_team_key(min(group, key=len))
    for group in TEAM_ALIAS_GROUPS
    for alias in group
}


def team_key(value):
    key = _raw_team_key(value)
    return _TEAM_CANONICAL.get(key, key)


def row_value(row, *names):
    """Legge colonne CSV senza dipendere da maiuscole, spazi o separatori."""
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(key).lower()): value
        for key, value in (row or {}).items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", str(name).lower())
        value = normalized.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def number(value):
    # Zero è un punteggio valido (0-0, 1-0, ecc.), non un valore mancante.
    value = str("" if value is None else value).strip()
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


def additional_odds_from_row(row):
    """Quote Over/Under 2,5 da football-data quando presenti nel CSV."""
    for keys in (("Avg>2.5", "Avg<2.5"), ("B365>2.5", "B365<2.5"),
                 ("Max>2.5", "Max<2.5"), ("BFE>2.5", "BFE<2.5")):
        values = [number(row.get(key)) for key in keys]
        if all(value is not None and value > 1 for value in values):
            return {"over_under_2_5": {"over": values[0], "under": values[1]}}
    return {}



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


def classify_no_bet(home_sample, away_sample, data_quality_ok=True):
    """Classifica in modo esplicito perché una partita non può essere stimata."""
    if not data_quality_ok:
        return "stima_non_affidabile", "Partita non adatta a una stima affidabile: qualità o comparabilità dei dati insufficiente."
    if home_sample + away_sample == 0:
        return "dati_mancanti", "Dati mancanti: nessuna osservazione storica pertinente per casa o trasferta."
    return "campione_insufficiente", "Campione insufficiente: servono almeno tre gare casalinghe per la squadra di casa e tre gare in trasferta per l’avversaria."


EUROPEAN_ESPN_COMPETITIONS = {
    "uefa.champions": "Champions League",
    "uefa.europa": "Europa League",
    "uefa.europa.conf": "Conference League",
}
NATIONAL_CUP_ESPN_COMPETITIONS = {
    "ita.coppa_italia": "Coppa Italia",
    "eng.fa": "FA Cup",
    "eng.league_cup": "EFL Cup",
    "eng.charity": "Community Shield",
    "esp.copa_del_rey": "Copa del Rey",
    "esp.super_cup": "Supercoppa di Spagna",
    "ger.dfb_pokal": "DFB-Pokal",
    "ger.super_cup": "Supercoppa di Germania",
    "fra.coupe_de_france": "Coupe de France",
    "fra.super_cup": "Trophée des Champions",
    "ita.super_cup": "Supercoppa Italiana",
    "ned.cup": "KNVB Beker",
    "ned.supercup": "Supercoppa olandese",
    "por.taca.portugal": "Taça de Portugal",
    "sco.tennents": "Scottish Cup",
    "sco.cis": "Scottish League Cup",
    "tur.turkiye_kupasi": "Coppa di Turchia",
}
COMPETITION_ESPN_CODES = {**EUROPEAN_ESPN_COMPETITIONS, **NATIONAL_CUP_ESPN_COMPETITIONS}
COMPETITION_COUNTRIES = {
    "Champions League": "Europa", "Europa League": "Europa", "Conference League": "Europa",
    "Coppa Italia": "Italia", "FA Cup": "Inghilterra", "EFL Cup": "Inghilterra",
    "Community Shield": "Inghilterra", "Copa del Rey": "Spagna", "Supercoppa di Spagna": "Spagna",
    "DFB-Pokal": "Germania", "Supercoppa di Germania": "Germania",
    "Coupe de France": "Francia", "Trophée des Champions": "Francia",
    "Supercoppa Italiana": "Italia", "KNVB Beker": "Paesi Bassi",
    "Supercoppa olandese": "Paesi Bassi", "Taça de Portugal": "Portogallo",
    "Scottish Cup": "Scozia", "Scottish League Cup": "Scozia", "Coppa di Turchia": "Turchia",
}


def fetch_competition_calendar(start_date, end_date):
    """Recupera calendario e risultati di coppe UEFA/nazionali; nessun punteggio viene inventato."""
    if end_date < start_date:
        return []
    competitions = COMPETITION_ESPN_CODES
    results = []

    def parse_payload(payload, competition_name, requested_start, requested_end):
        found = []
        for event in payload.get("events", []):
            competitions_data = event.get("competitions") or []
            if not competitions_data:
                continue
            competition = competitions_data[0]
            status_obj = (competition.get("status") or {}).get("type") or {}
            completed = bool(status_obj.get("completed"))
            raw_date = event.get("date", "")
            try:
                event_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                local_dt = event_dt.astimezone(ZoneInfo("Europe/Rome"))
                event_date = local_dt.date()
                kickoff = local_dt.strftime("%H:%M")
            except (ValueError, TypeError):
                event_date = parse_date(raw_date)
                kickoff = raw_date[11:16] if "T" in raw_date else ""
            if not event_date or not (requested_start <= event_date <= requested_end):
                continue
            home = away = None
            for competitor in competition.get("competitors", []):
                team = (competitor.get("team") or {}).get("displayName", "").strip()
                score = number(competitor.get("score"))
                if competitor.get("homeAway") == "home":
                    home = (team, score)
                elif competitor.get("homeAway") == "away":
                    away = (team, score)
            if not home or not away or not home[0] or not away[0]:
                continue
            if team_key(home[0]) == team_key(away[0]):
                continue
            item = {
                "date": event_date.isoformat(), "kickoff": kickoff,
                "home_team": home[0], "away_team": away[0],
                "competition": competition_name,
                "status": "completed" if completed and home[1] is not None and away[1] is not None else "scheduled",
                "source": "ESPN",
            }
            if item["status"] == "completed":
                if not (0 <= home[1] <= 15 and 0 <= away[1] <= 15):
                    continue
                item["home_goals"], item["away_goals"] = int(home[1]), int(away[1])
            found.append(item)
        return found

    def fetch_range(sport_code, competition_name):
        base = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
        params = f"?dates={start_date:%Y%m%d}-{end_date:%Y%m%d}&limit=100"
        try:
            request = urllib.request.Request(base + sport_code + "/scoreboard" + params, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            found = parse_payload(payload, competition_name, start_date, end_date)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO: calendario {competition_name} non disponibile: {error}")
            found = []
        # Alcuni scoreboard ESPN non rispettano sempre l'intervallo: usa il fallback
        # giornaliero soltanto quando la richiesta compatta non ha restituito eventi.
        if found:
            return found
        fallback = []
        cursor = start_date
        while cursor <= end_date:
            url = base + sport_code + f"/scoreboard?dates={cursor:%Y%m%d}&limit=100"
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=8) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                fallback.extend(parse_payload(payload, competition_name, cursor, cursor))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                print(f"AVVISO: calendario {competition_name} {cursor}: {error}")
            cursor += timedelta(days=1)
        return fallback

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_range, code, name) for code, name in competitions.items()]
        for future in as_completed(futures):
            results.extend(future.result())
    unique = {}
    for item in results:
        key = (item["date"], item["competition"], team_key(item["home_team"]), team_key(item["away_team"]))
        unique[key] = item
    ordered = sorted(unique.values(), key=lambda item: (item["date"], item["kickoff"], item["competition"]))
    completed = sum(1 for item in ordered if item["status"] == "completed")
    scheduled = sum(1 for item in ordered if item["status"] == "scheduled")
    print(f"Calendari coppe ESPN: {len(ordered)} gare ({completed} concluse, {scheduled} future) su {len(competitions)} competizioni configurate.")
    return ordered



def load_competition_calendar(start_date, end_date, now=None):
    """Usa il calendario stagionale già sincronizzato; ricorre a ESPN solo se la cache manca o è obsoleta."""
    current = now or datetime.now(timezone.utc)
    try:
        with COMPETITION_DATA_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        updated_at = datetime.fromisoformat(str(payload.get("updated_at", "")).replace("Z", "+00:00"))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = current.astimezone(timezone.utc) - updated_at.astimezone(timezone.utc)
        fixtures = payload.get("fixtures")
        if age < timedelta(0) or age > timedelta(hours=36) or not isinstance(fixtures, list):
            raise ValueError("cache calendario obsoleta o non valida")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"Calendario stagionale non utilizzabile ({error}); attivo il fallback ESPN.")
        return fetch_competition_calendar(start_date, end_date)

    allowed_competitions = set(COMPETITION_COUNTRIES)
    selected = []
    for item in fixtures:
        if not isinstance(item, dict) or item.get("competition") not in allowed_competitions:
            continue
        if item.get("status") not in ("completed", "scheduled"):
            continue
        try:
            fixture_date = date.fromisoformat(str(item.get("date", "")))
        except (TypeError, ValueError):
            continue
        if not start_date <= fixture_date <= end_date:
            continue
        home = str(item.get("home_team", "")).strip()
        away = str(item.get("away_team", "")).strip()
        if not home or not away or team_key(home) == team_key(away):
            continue
        normalized = dict(item)
        normalized["date"] = fixture_date.isoformat()
        normalized["home_team"] = home
        normalized["away_team"] = away
        normalized["kickoff"] = str(item.get("kickoff") or "")
        if normalized["status"] == "completed":
            hg, ag = number(item.get("home_goals")), number(item.get("away_goals"))
            if hg is None or ag is None or not (0 <= hg <= 15 and 0 <= ag <= 15):
                continue
            normalized["home_goals"], normalized["away_goals"] = int(hg), int(ag)
        selected.append(normalized)

    # Se il file è valido ma non contiene partite nella finestra, l'elenco vuoto è
    # un risultato legittimo: evitare di interrogare 12 scoreboard ogni ora.
    selected.sort(key=lambda item: (item["date"], item["kickoff"], item["competition"]))
    print(
        f"Calendario da cache: {len(selected)} gare coppe nella finestra "
        f"{start_date.isoformat()}–{end_date.isoformat()}."
    )
    return selected


def fetch_european_matches(start_date, end_date):
    """Compatibilità: restituisce soltanto risultati UEFA conclusi nella finestra richiesta."""
    return [
        item for item in fetch_competition_calendar(start_date, end_date)
        if item.get("status") == "completed" and item.get("competition") in EUROPEAN_ESPN_COMPETITIONS.values()
    ]


def european_fatigue_context(home, away, match_date, european_matches):
    """Contesto riposo UEFA: correzione prudente e sperimentale, limitata ai risultati verificati."""
    try:
        target_date = match_date if isinstance(match_date, date) else date.fromisoformat(str(match_date))
    except (TypeError, ValueError):
        return []
    context = []
    for team in (home, away):
        recent = []
        for item in european_matches or []:
            if item.get("status") not in (None, "completed"):
                continue
            try:
                played_date = date.fromisoformat(item.get("date", ""))
            except (TypeError, ValueError):
                continue
            days_before = (target_date - played_date).days
            if not 1 <= days_before <= 4:
                continue
            if team_key(team) == team_key(item.get("home_team")):
                venue = "casa"
            elif team_key(team) == team_key(item.get("away_team")):
                venue = "trasferta"
            else:
                continue
            recent.append((played_date, days_before, venue, item))
        if not recent:
            continue
        played_date, days_before, venue, item = max(recent, key=lambda row: row[0])
        # Penalità minima e dichiaratamente sperimentale. Le partite UEFA non
        # forniscono sempre minuti giocati/tempi supplementari: non si inventano.
        if days_before <= 2:
            factor = 0.92 if venue == "trasferta" else 0.95
        elif days_before == 3:
            factor = 0.95 if venue == "trasferta" else 0.97
        else:
            factor = 0.98 if venue == "trasferta" else 0.99
        context.append({
            "team": team, "competition": item.get("competition", "Coppa europea"),
            "match_date": item.get("date"), "days_before": days_before,
            "venue": venue, "home_goals": item.get("home_goals"),
            "away_goals": item.get("away_goals"), "attack_factor": factor,
            "adjustment_pct": round((1 - factor) * 100, 1),
            "source": item.get("source", "ESPN"),
            "note": "Stima sperimentale: minuti effettivi, viaggio e supplementari non verificati.",
        })
    return context



def declassify_cup_forecast(forecast, competition_name):
    """Impedisce di presentare come validato un modello basato sul campionato per una coppa."""
    if not isinstance(forecast, dict):
        return forecast
    is_european = competition_name in EUROPEAN_ESPN_COMPETITIONS.values()
    forecast["competition_type"] = "europea" if is_european else "coppa_nazionale"
    forecast["status"] = "Stima preliminare" if forecast.get("probabilities") else "NO BET"
    forecast["suggested_markets"] = []
    forecast["suggested_market_details"] = []
    forecast["betting_advice"] = (
        "Per le coppe non fornisco una giocata automatica: il modello non è ancora validato "
        "su uno storico specifico della competizione. Meglio attendere dati più solidi."
    )
    forecast["value_bets"] = []
    forecast["expected_value_1x2"] = {}
    if isinstance(forecast.get("value_assessment"), dict):
        forecast["value_assessment"]["eligible_for_candidate"] = False
    forecast["confidence"] = "limitata: modello non validato per coppe"
    forecast["data_quality"] = "coppa_non_validata"
    forecast["cup_model_note"] = (
        "Stima orientativa basata sui dati dei campionati nazionali disponibili, "
        "non su uno storico specifico della coppa. Pronostico non validato: nessun "
        "mercato o value bet automatico viene consigliato."
    )
    if forecast.get("status") == "NO BET":
        forecast["reason"] = (
            "Dati insufficienti o squadre non riconciliate: nessuna probabilità pubblicata. "
            + forecast.get("reason", "")
        ).strip()
    else:
        forecast["reason"] = forecast["cup_model_note"]
    return forecast


def build_motivation_table(completed):
    """Classifica le pressioni di classifica senza fingere di conoscere verdetti matematici."""
    table = defaultdict(lambda: {"played": 0, "points": 0, "gf": 0, "ga": 0, "wins": 0})
    for home, away, hg, ag in completed:
        if team_key(home) == team_key(away):
            continue
        h, a = table[team_key(home)], table[team_key(away)]
        h["played"] += 1; a["played"] += 1
        h["gf"] += hg; h["ga"] += ag
        a["gf"] += ag; a["ga"] += hg
        if hg > ag:
            h["points"] += 3; h["wins"] += 1
        elif hg < ag:
            a["points"] += 3; a["wins"] += 1
        else:
            h["points"] += 1; a["points"] += 1
    ordered = sorted(
        table.items(),
        key=lambda item: (item[1]["points"], item[1]["gf"] - item[1]["ga"], item[1]["gf"], item[1]["wins"]),
        reverse=True,
    )
    total = len(ordered)
    result = {}
    for position, (key, stats) in enumerate(ordered, 1):
        result[key] = {**stats, "position": position, "teams_count": total}
    return result


def motivation_for_match(home, away, table):
    """Restituisce indizi prudenti di classifica; non dichiara titoli o retrocessioni matematiche."""
    if not table:
        return {"status": "non_verificabile", "note": "Classifica aggiornata non disponibile: motivazioni non dedotte."}
    h, a = table.get(team_key(home)), table.get(team_key(away))
    if not h or not a or min(h["played"], a["played"]) < 5:
        return {"status": "dati_insufficienti", "note": "Poche partite concluse per valutare con prudenza gli obiettivi di classifica."}
    total = max(h["teams_count"], a["teams_count"])
    def labels(stats, opponent):
        labels = []
        position = stats["position"]
        points_gap = stats["points"] - opponent["points"]
        if position <= min(2, max(1, total // 8)) and abs(points_gap) <= 6:
            labels.append("zona alta / possibile corsa al titolo")
        if position <= max(4, round(total * 0.30)) and position > 1:
            labels.append("zona obiettivi europei o alta classifica")
        if position >= max(1, total - max(3, round(total * 0.20)) + 1):
            labels.append("zona bassa / possibile lotta salvezza")
        if not labels:
            labels.append("motivazione competitiva ordinaria; obiettivo specifico non deducibile")
        return labels
    return {
        "status": "indizi_classifica",
        "home": {"position": h["position"], "points": h["points"], "played": h["played"], "signals": labels(h, a)},
        "away": {"position": a["position"], "points": a["points"], "played": a["played"], "signals": labels(a, h)},
        "note": "Indizi calcolati dai risultati di campionato disponibili, non verdetti ufficiali. Titolo già vinto/retrocessione matematica non vengono dichiarati senza una classifica e un calendario completi verificati.",
    }




def apply_motivation_adjustment(expected_home, expected_away, motivation_context):
    """Espone il contesto motivazionale senza alterare probabilità non validate."""
    result = {
        "home_factor": 1.0,
        "away_factor": 1.0,
        "applied": False,
        "adjustment_pct": 0.0,
        "status": "solo_informativa",
        "note": (
            "Motivazioni di classifica mostrate solo come contesto informativo: "
            "non modificano gol attesi o probabilità finché l'effetto non è calibrato "
            "e verificato con backtest fuori campione."
        ),
    }
    if not isinstance(motivation_context, dict) or motivation_context.get("status") != "indizi_classifica":
        result["status"] = "non_verificabile"
        result["note"] = (
            "Motivazioni non verificabili con i dati disponibili; nessuna modifica "
            "a gol attesi o probabilità."
        )
    return expected_home, expected_away, result


def build_betting_recommendations(probabilities, home_sample, away_sample, recent_context=None):
    """Seleziona pochi mercati da valutare e indica una quota-obiettivo prudente."""
    if not probabilities or home_sample < 8 or away_sample < 8:
        return [], [], (
            "Qui non forzerei una giocata: lo storico specifico è ancora troppo corto. "
            "Meglio aspettare dati più solidi che riempire la schedina per forza."
        )
    if recent_context:
        teams = ", ".join(dict.fromkeys(
            str(item.get("team", "")).strip() for item in recent_context if item.get("team")
        ))
        detail = f" ({teams} hanno un impegno ravvicinato)" if teams else ""
        return [], [], (
            "Partita da prendere con le pinze" + detail +
            ": il calendario può pesare e il modello non lo misura abbastanza bene. "
            "Per ora passerei, senza inventare una giocata."
        )

    candidates = [
        ("1", probabilities.get("home_win"), "esito"),
        ("X", probabilities.get("draw"), "esito"),
        ("2", probabilities.get("away_win"), "esito"),
        ("1X", probabilities.get("double_chance_1x"), "esito"),
        ("X2", probabilities.get("double_chance_x2"), "esito"),
        ("12", probabilities.get("double_chance_12"), "esito"),
        ("Over 1,5", probabilities.get("over_1_5"), "gol"),
        ("Over 2,5", probabilities.get("over_2_5"), "gol"),
        ("Under 2,5", probabilities.get("under_2_5"), "gol"),
        ("Under 3,5", probabilities.get("under_3_5"), "gol"),
        ("Goal", probabilities.get("btts_yes"), "entrambe"),
        ("No Goal", probabilities.get("btts_no"), "entrambe"),
    ]
    thresholds = {"esito": 70.0, "gol": 70.0, "entrambe": 70.0}
    # Una sola scelta per famiglia: evita di proporre mercati ridondanti sulla stessa partita.
    ranked = sorted(
        ({"market": name, "probability": float(prob), "family": family}
         for name, prob, family in candidates
         if isinstance(prob, (int, float)) and prob >= thresholds[family]),
        key=lambda item: item["probability"], reverse=True,
    )
    chosen, families = [], set()
    for item in ranked:
        if item["family"] in families:
            continue
        p = item["probability"] / 100.0
        fair_odds = 1.0 / p if p > 0 else None
        item["fair_odds"] = round(fair_odds, 2) if fair_odds else None
        item["target_odds"] = round(fair_odds * 1.05, 2) if fair_odds else None
        chosen.append(item)
        families.add(item["family"])
        if len(chosen) == 2:
            break

    if not chosen:
        return [], [], (
            "Non vedo un esito abbastanza netto da meritare una giocata automatica. "
            "Meglio lasciarla stare e conservare il budget per una partita più leggibile."
        )
    labels = [item["market"] for item in chosen]
    first = chosen[0]
    advice = (
        f"Prima scelta da valutare: {first['market']} "
        f"(stima {first['probability']:.1f}%). Cercherei una quota almeno "
        f"{first['target_odds']:.2f}: è una soglia orientativa con un piccolo margine, "
        "non una garanzia. Se il prezzo è più basso, meglio non inseguirla."
    )
    if len(chosen) > 1:
        second = chosen[1]
        advice += (
            f" In alternativa: {second['market']} (stima {second['probability']:.1f}%), "
            f"da considerare solo intorno a quota {second['target_odds']:.2f} o superiore."
        )
    return labels, chosen, advice

def make_forecast(home, away, league, match_date, kickoff, history, league_home_avg, league_away_avg, elo_ratings=None, recent_form=None, european_matches=None, motivation_table=None, apply_form_adjustment=True, apply_competition_adjustment=True):
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
    if home_form and away_form and apply_form_adjustment:
        league_goal_avg = max(0.5, (league_home_avg + league_away_avg) / 2)
        home_attack_form = home_form["goals_for"] / league_goal_avg
        home_defence_form = away_form["goals_against"] / max(0.5, league_home_avg)
        away_attack_form = away_form["goals_for"] / league_goal_avg
        away_defence_form = home_form["goals_against"] / max(0.5, league_away_avg)
        home_form_factor = max(0.82, min(1.18, math.sqrt(home_attack_form * home_defence_form)))
        away_form_factor = max(0.82, min(1.18, math.sqrt(away_attack_form * away_defence_form)))
        expected_home = max(0.15, min(4.5, expected_home * home_form_factor))
        expected_away = max(0.15, min(4.5, expected_away * away_form_factor))
    recent_competition_context = european_fatigue_context(home, away, match_date, european_matches)
    european_context = [item for item in recent_competition_context if item.get("competition") in EUROPEAN_ESPN_COMPETITIONS.values()]
    if apply_competition_adjustment:
        for item in recent_competition_context:
            if team_key(item["team"]) == team_key(home):
                expected_home = max(0.15, expected_home * item["attack_factor"])
            elif team_key(item["team"]) == team_key(away):
                expected_away = max(0.15, expected_away * item["attack_factor"])
    motivation_context = motivation_for_match(home, away, motivation_table or {})
    expected_home, expected_away, motivation_adjustment = apply_motivation_adjustment(
        expected_home, expected_away, motivation_context
    )
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
    # Sotto tre gare pertinenti per lato il campione è troppo fragile: niente probabilità pubblicate.
    # Da 3 a 7 gare la stima resta preliminare; la soglia per un candidato EV è 8 per lato.
    valid = home_sample >= MIN_TEAM_MATCHES and away_sample >= MIN_TEAM_MATCHES
    no_bet_type, no_bet_reason = classify_no_bet(home_sample, away_sample)
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
    suggested, suggested_details, betting_advice = build_betting_recommendations(
        probabilities, home_sample, away_sample, recent_competition_context
    ) if valid else ([], [], "Qui mancano basi sufficienti per consigliare una giocata: meglio passare.")
    summary = betting_advice
    return {
        "id": f"{match_date.isoformat()}-{league}-{home}-{away}",
        "date": match_date.isoformat(), "kickoff": kickoff or "", "league": league,
        "country": LEAGUE_COUNTRIES.get(league, COMPETITION_COUNTRIES.get(league, "Altro")),
        "home_team": home, "away_team": away,
        "expected_home_goals": round(expected_home, 2),
        "expected_away_goals": round(expected_away, 2),
        "probabilities": probabilities,
        "analysis": summary,
        "suggested_markets": suggested,
        "suggested_market_details": suggested_details,
        "betting_advice": betting_advice,
        "value_bets": [],
        "top_scorelines": [
            {"score": f"{h}-{a}", "probability": percent(p)}
            for p, h, a in scorelines[:3]
        ] if valid else [],
        "sample_matches": sample,
        "home_matches_sample": home_sample,
        "away_matches_sample": away_sample,
        "status": ("Pronostico valutabile" if home_sample >= 8 and away_sample >= 8 and not recent_competition_context else "Stima preliminare") if valid else "NO BET",
        "no_bet_type": "" if valid else no_bet_type,
        "reason": "" if valid else no_bet_reason,
        "confidence": "alta quantità di dati (non sinonimo di accuratezza verificata)" if sample >= 8 else "media quantità di dati" if sample >= 5 else "bassa quantità di dati",
        "data_quality": "controllata",
        "elo_home": round((elo_ratings or {}).get(home, 1500.0), 1),
        "elo_away": round((elo_ratings or {}).get(away, 1500.0), 1),
        "home_recent_form": (recent_form or {}).get(home),
        "away_recent_form": (recent_form or {}).get(away),
        "european_context": european_context,
        "recent_competition_context": recent_competition_context,
        "motivation_context": {
            **motivation_context,
            "model_adjustment": motivation_adjustment,
        },
        "motivation_adjustment": motivation_adjustment,
        "european_fatigue_status": "rilevato" if european_context else "nessuna gara europea recente verificata",
        "recent_competition_status": "impegno ravvicinato rilevato" if recent_competition_context else "nessun impegno recente verificato",
        "competition_type": "europea" if league in EUROPEAN_ESPN_COMPETITIONS.values() else "nazionale" if league in NATIONAL_CUP_ESPN_COMPETITIONS.values() else "campionato",
        "method": "Poisson casa/trasferta + prior di lega + Elo; forma recente e impegni UEFA/coppe nazionali solo informativi, non applicati agli expected goals finché non validati",
        "availability_data": {
            "status": "non_integrata",
            "note": "Infortuni, squalifiche e formazioni ufficiali non sono inclusi: nessuna fonte verificata disponibile nel calcolo."
        },
    }


def published_forecast_lists(forecasts):
    """Pubblica tutte le partite NO BET e fino a 120 stime, senza nascondere record conteggiati."""
    return {
        "matches": [item for item in forecasts if item.get("status") in ("Pronostico valutabile", "Stima preliminare")][:120],
        "no_bet_matches": [item for item in forecasts if item.get("status") == "NO BET"],
    }


def main():
    today = datetime.now(timezone.utc).date()
    season = current_season_code(today)
    last_date = today + timedelta(days=MAX_DAYS_AHEAD)
    forecasts, downloaded, failed = [], 0, []
    historical_available = []
    league_models = []
    fixture_odds = {}
    fixture_markets = {}
    competition_calendar = load_competition_calendar(today - timedelta(days=4), last_date)
    recent_competition_matches = [
        item for item in competition_calendar
        if item.get("status") == "completed"
        and item.get("competition") in set(EUROPEAN_ESPN_COMPETITIONS.values()) | set(NATIONAL_CUP_ESPN_COMPETITIONS.values())
    ]

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
        rows = []
        if code in FOOTBALL_DATA_LEAGUES:
            try:
                rows = fetch_csv(f"{SOURCE}/mmz4281/{season}/{code}.csv")
                downloaded += 1
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                failed.append(f"{code}: {error}")
                print(f"AVVISO: storico principale {code} non disponibile: {error}; provo calendario alternativo.")
        elif code in EXTRA_FOOTBALL_DATA_LEAGUES:
            try:
                rows = fetch_csv(f"{SOURCE}/new/{EXTRA_SOURCE_CODES.get(code, code)}.csv")
                downloaded += 1
                print(f"{league_name}: CSV cumulativo gratuito scaricato ({code}).")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                failed.append(f"{code}: {error}")
                print(f"AVVISO: CSV cumulativo {code} non disponibile: {error}; provo il fallback ESPN.")
        else:
            print(f"{league_name}: nessun CSV dedicato configurato; provo il fallback ESPN.")

        completed, fixtures = [], []
        # Conserva eventuali fixture presenti nel file del campionato.
        for row in rows:
            home = str(row_value(row, "HomeTeam", "Home Team", "home_team", "home", "hometeamname") or "").strip()
            away = str(row_value(row, "AwayTeam", "Away Team", "away_team", "away", "awayteamname") or "").strip()
            match_date = parse_date(row_value(row, "Date", "date", "match_date", "matchdate"))
            if not home or not away or not match_date:
                continue
            # I CSV /new/ contengono più stagioni: limita i risultati usati dal
            # modello all'ultimo anno, evitando che dati vecchi dominino la forma.
            if code in EXTRA_FOOTBALL_DATA_LEAGUES and match_date < today - timedelta(days=EXTRA_HISTORY_DAYS):
                continue
            hg = number(row_value(row, "FTHG", "HG", "fthg", "home_goals", "home_score", "home_score_ft", "score_home"))
            ag = number(row_value(row, "FTAG", "AG", "ftag", "away_goals", "away_score", "away_score_ft", "score_away"))
            if (hg is not None and ag is not None and match_date < today and
                    0 <= hg <= 15 and 0 <= ag <= 15 and team_key(home) != team_key(away)):
                completed.append((home, away, int(hg), int(ag)))
            elif today <= match_date <= last_date and team_key(home) != team_key(away):
                fixtures.append((home, away, match_date, str(row_value(row, "Time", "time", "kickoff") or "").strip()))
                fixture_key = (match_date.isoformat(), team_key(home), team_key(away))
                quote = odds_from_row(row)
                if quote:
                    fixture_odds[fixture_key] = quote
                extra_quotes = additional_odds_from_row(row)
                if extra_quotes:
                    fixture_markets.setdefault(fixture_key, {}).update(extra_quotes)

        # All'inizio della stagione prova prima la stagione precedente della fonte primaria.
        history_season = season
        if len(completed) < MIN_TEAM_MATCHES and code in FOOTBALL_DATA_LEAGUES:
            previous_season = f"{(int(season[:2]) - 1) % 100:02d}{season[:2]}"
            try:
                previous_rows = fetch_csv(f"{SOURCE}/mmz4281/{previous_season}/{code}.csv")
                previous_completed = []
                for row in previous_rows:
                    home = (row.get("HomeTeam") or row.get("Home Team") or "").strip()
                    away = (row.get("AwayTeam") or row.get("Away Team") or "").strip()
                    match_date = parse_date(row_value(row, "Date", "date", "match_date", "matchdate"))
                    hg = number(row.get("FTHG") or row.get("HG") or row.get("home_goals"))
                    ag = number(row.get("FTAG") or row.get("AG") or row.get("away_goals"))
                    if (home and away and match_date and match_date < today and
                            hg is not None and ag is not None and 0 <= hg <= 15 and 0 <= ag <= 15 and
                            team_key(home) != team_key(away)):
                        previous_completed.append((home, away, int(hg), int(ag)))
                if len(previous_completed) > len(completed):
                    completed = previous_completed
                    history_season = previous_season
                    print(f"{league_name}: uso {previous_season} come storico iniziale.")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                print(f"AVVISO: storico precedente {code} non disponibile: {error}")

        # Fallback storico ESPN in una singola richiesta per intervallo, se supportato.
        if len(completed) < MIN_TEAM_MATCHES:
            espn_rows = fetch_espn_historical_results(code, today - timedelta(days=120), today - timedelta(days=1))
            if len(espn_rows) > len(completed):
                completed = [(h, a, hg, ag) for h, a, hg, ag, _ in espn_rows]
                history_season = "ESPN-120-giorni"
                print(f"{league_name}: recuperati {len(completed)} risultati ESPN per lo storico recente.")

        if completed:
            historical_available.append(league_name)

        # Aggiunge il calendario generale, che contiene le prossime partite.
        known_teams = {team for match in completed for team in match[:2]}
        known_team_keys = {team_key(team) for team in known_teams}
        fixture_rows_for_league = 0
        for row in all_fixtures:
            div = str(row_value(row, "Div", "div", "League", "league", "division", "country") or "").strip()
            div = {"NOR": "NOK", "ROU": "RO"}.get(div, div)
            home = str(row_value(row, "HomeTeam", "Home Team", "home_team", "home", "hometeamname") or "").strip()
            away = str(row_value(row, "AwayTeam", "Away Team", "away_team", "away", "awayteamname") or "").strip()
            match_date = parse_date(row_value(row, "Date", "date", "match_date", "matchdate"))
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
            kickoff = str(row_value(row, "Time", "time", "kickoff") or "").strip()
            item = (home, away, match_date, kickoff)
            if item not in fixtures:
                fixtures.append(item)
            fixture_key = (match_date.isoformat(), team_key(home), team_key(away))
            quote = odds_from_row(row)
            if quote:
                fixture_odds[fixture_key] = quote
            extra_quotes = additional_odds_from_row(row)
            if extra_quotes:
                fixture_markets.setdefault(fixture_key, {}).update(extra_quotes)

        # ESPN integra anche calendari parziali: una sola partita CSV non significa
        # che la copertura sia completa. Evita richieste aggiuntive quando il CSV ha
        # già almeno due candidate; unisce le fonti usando data + nomi normalizzati.
        if len(fixtures) < 2:
            alternate_fixtures = fetch_espn_fixtures(code, today, last_date)
            before_merge = len(fixtures)
            fixtures = merge_fixture_sources(fixtures, alternate_fixtures)
            added = len(fixtures) - before_merge
            if alternate_fixtures:
                print(
                    f"{league_name}: calendario ESPN consultato ({len(alternate_fixtures)} gare); "
                    f"{added} nuove candidate aggiunte, {len(fixtures)} totali."
                )
        else:
            fixtures = merge_fixture_sources(fixtures, [])
        print(f"{league_name}: {len(completed)} risultati storici, {fixture_rows_for_league} partite future abbinate, {len(fixtures)} candidate totali.")
        if not completed:
            print(f"AVVISO: {league_name}: nessun risultato concluso disponibile; le partite alternative saranno mostrate come NO BET.")
            for home, away, match_date, kickoff in fixtures:
                forecasts.append({
                    "id": f"{match_date.isoformat()}-{league_name}-{home}-{away}",
                    "date": match_date.isoformat(), "kickoff": kickoff or "", "league": league_name,
                    "country": LEAGUE_COUNTRIES.get(league_name, "Altro"),
                    "home_team": home, "away_team": away, "expected_home_goals": None,
                    "expected_away_goals": None, "probabilities": {}, "analysis": "",
                    "suggested_markets": [], "value_bets": [], "top_scorelines": [],
                    "sample_matches": 0, "home_matches_sample": 0, "away_matches_sample": 0,
                    "status": "NO BET", "no_bet_type": "dati_mancanti",
                    "reason": "Dati mancanti: calendario trovato, ma non ci sono risultati storici verificabili per questa competizione.",
                    "confidence": "non stimabile", "data_quality": "storico_assente", "method": "Nessuna stima: storico non disponibile",
                    "availability_data": {"status": "non_integrata", "note": "Disponibilità non verificata."}
                })
            continue
        league_home_avg = sum(item[2] for item in completed) / len(completed)
        league_away_avg = sum(item[3] for item in completed) / len(completed)
        if league_home_avg <= 0 or league_away_avg <= 0:
            print(f"AVVISO: {league_name}: medie gol non valide; nessuna probabilità sarà pubblicata.")
            for home, away, match_date, kickoff in fixtures:
                no_type, no_reason = classify_no_bet(0, 0, data_quality_ok=False)
                forecasts.append({
                    "id": f"{match_date.isoformat()}-{league_name}-{home}-{away}",
                    "date": match_date.isoformat(), "kickoff": kickoff or "", "league": league_name,
                    "country": LEAGUE_COUNTRIES.get(league_name, "Altro"),
                    "home_team": home, "away_team": away, "expected_home_goals": None,
                    "expected_away_goals": None, "probabilities": {}, "analysis": "",
                    "suggested_markets": [], "value_bets": [], "top_scorelines": [],
                    "sample_matches": 0, "home_matches_sample": 0, "away_matches_sample": 0,
                    "status": "NO BET", "no_bet_type": no_type, "reason": no_reason,
                    "confidence": "non stimabile", "data_quality": "dati_non_validi", "method": "Nessuna stima: dati statistici non validi",
                    "availability_data": {"status": "non_integrata", "note": "Disponibilità non verificata."}
                })
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

        motivation_table = build_motivation_table(completed) if history_season == season else {}

        # Conserva i modelli nazionali per usare lo storico di campionato anche nelle coppe.
        normalized_history = {team_key(team): team for team in history}
        league_models.append({
            "league": league_name, "history": history, "home_avg": league_home_avg,
            "away_avg": league_away_avg, "elo": elo_ratings, "recent": recent_form,
            "normalized_history": normalized_history, "motivation_table": motivation_table,
        })
        skipped = 0
        for home, away, match_date, kickoff in fixtures:
            home = normalized_history.get(team_key(home), home)
            away = normalized_history.get(team_key(away), away)
            forecast = make_forecast(home, away, league_name, match_date, kickoff, history, league_home_avg, league_away_avg, elo_ratings, recent_form, recent_competition_matches, motivation_table, apply_form_adjustment=False, apply_competition_adjustment=False)
            if forecast:
                fixture_key = (match_date.isoformat(), team_key(home), team_key(away))
                quote = fixture_odds.get(fixture_key)
                extra_quotes = fixture_markets.get(fixture_key, {})
                if extra_quotes:
                    forecast["odds_markets"] = extra_quotes
                    forecast["odds_markets_source"] = "football-data.co.uk"
                    forecast["odds_fetched_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                if quote and forecast.get("probabilities"):
                    forecast["odds_fetched_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
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
                        if ev[price_key] >= 0.05 and forecast.get("status") == "Pronostico valutabile" and forecast.get("home_matches_sample", 0) >= 8 and forecast.get("away_matches_sample", 0) >= 8
                    ]
                forecasts.append(forecast)
            else:
                skipped += 1
        print(f"{league_name}: pronostici creati {len(fixtures) - skipped}; scartate per storico insufficiente {skipped}.")

    # Aggiunge le partite future delle coppe. Per ogni club usa il suo storico nazionale;
    # se uno dei due club non è abbinabile, la partita resta visibile come NO BET.
    future_cup_fixtures = [
        item for item in competition_calendar
        if item.get("status") == "scheduled"
        and today <= date.fromisoformat(item["date"]) <= last_date
    ]
    team_records = {}
    for model in league_models:
        for team, stats in model["history"].items():
            key = team_key(team)
            if key and key not in team_records:
                team_records[key] = {"team": team, "stats": stats, "model": model}
    existing_fixture_keys = {
        (item.get("date"), item.get("league"), team_key(item.get("home_team")), team_key(item.get("away_team")))
        for item in forecasts
    }
    cup_added = 0
    for fixture in future_cup_fixtures:
        competition_name = fixture["competition"]
        home_key, away_key = team_key(fixture["home_team"]), team_key(fixture["away_team"])
        unique_key = (fixture["date"], competition_name, home_key, away_key)
        if unique_key in existing_fixture_keys:
            continue
        home_record, away_record = team_records.get(home_key), team_records.get(away_key)
        match_date = date.fromisoformat(fixture["date"])
        if home_record and away_record:
            home_team, away_team = home_record["team"], away_record["team"]
            combined_history = defaultdict(lambda: {
                "played": 0, "home_games": 0, "away_games": 0,
                "home_scored": 0, "home_conceded": 0, "away_scored": 0, "away_conceded": 0,
            })
            combined_history[home_team] = home_record["stats"]
            combined_history[away_team] = away_record["stats"]
            home_model, away_model = home_record["model"], away_record["model"]
            combined_elo = {home_team: home_model["elo"].get(home_team, 1500.0), away_team: away_model["elo"].get(away_team, 1500.0)}
            combined_recent = {}
            if home_team in home_model["recent"]: combined_recent[home_team] = home_model["recent"][home_team]
            if away_team in away_model["recent"]: combined_recent[away_team] = away_model["recent"][away_team]
            home_avg = (home_model["home_avg"] + away_model["home_avg"]) / 2
            away_avg = (home_model["away_avg"] + away_model["away_avg"]) / 2
            forecast = make_forecast(
                home_team, away_team, competition_name, match_date, fixture.get("kickoff", ""),
                combined_history, home_avg, away_avg, combined_elo, combined_recent, competition_calendar, {},
                apply_form_adjustment=False, apply_competition_adjustment=False,
            )
            forecast = declassify_cup_forecast(forecast, competition_name)
            forecast["source_calendar"] = fixture.get("source", "ESPN")
            forecast["historical_sources"] = [home_model["league"], away_model["league"]]
        else:
            forecast = {
                "id": f"{fixture['date']}-{competition_name}-{fixture['home_team']}-{fixture['away_team']}",
                "date": fixture["date"], "kickoff": fixture.get("kickoff", ""), "league": competition_name,
                "country": COMPETITION_COUNTRIES.get(competition_name, "Europa"),
                "home_team": fixture["home_team"], "away_team": fixture["away_team"],
                "expected_home_goals": None, "expected_away_goals": None, "probabilities": {},
                "analysis": "", "suggested_markets": [], "value_bets": [], "top_scorelines": [],
                "sample_matches": 0, "home_matches_sample": 0, "away_matches_sample": 0,
                "status": "NO BET", "no_bet_type": "dati_mancanti",
                "reason": "Storico nazionale non abbinabile a entrambe le squadre: la partita è mostrata ma non viene stimata.",
                "confidence": "non stimabile", "data_quality": "storico_assente",
                "method": "Nessuna stima: storico club non disponibile o nome squadra non riconciliato",
                "availability_data": {"status": "non_integrata", "note": "Disponibilità non verificata."},
                "competition_type": "europea" if competition_name in EUROPEAN_ESPN_COMPETITIONS.values() else "coppa_nazionale",
                "cup_model_note": "Nessuna stima affidabile: lo storico nazionale non è abbinabile a entrambe le squadre.",
                "source_calendar": fixture.get("source", "ESPN"),
            }
        forecasts.append(forecast)
        existing_fixture_keys.add(unique_key)
        cup_added += 1
    print(f"Coppe: {cup_added} partite future aggiunte al dataset (stima solo con storico nazionale abbinabile).")

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
        "model": "Poisson con statistiche casa/trasferta, prior di lega ed Elo; forma recente e contesto coppe UEFA/nazionali solo informativi finché non validati",
        "competition_calendar": {
            "source": "ESPN", "range_start": (today - timedelta(days=4)).isoformat(),
            "range_end": last_date.isoformat(), "events_loaded": len(competition_calendar),
            "completed_results": sum(1 for item in competition_calendar if item.get("status") == "completed"),
            "upcoming_fixtures": len(future_cup_fixtures),
            "competitions_configured": list(COMPETITION_ESPN_CODES.values()),
        },
        "leagues_checked": downloaded,
        "coverage": {
            "leagues_configured": len(LEAGUES),
            "csv_downloaded": downloaded,
            "cup_competitions_configured": len(COMPETITION_ESPN_CODES),
            "cup_fixtures_found": len(future_cup_fixtures),
            "cup_fixtures_added": cup_added,
            "cup_competitions_with_fixtures": sorted({item.get("competition") for item in future_cup_fixtures}),
            "leagues_with_history": sorted(set(historical_available)),
            "leagues_without_history": sorted(set(LEAGUES.values()) - set(historical_available)),
            "matches_with_estimates": sum(1 for item in forecasts if item.get("status") in ("Pronostico valutabile", "Stima preliminare")),
            "matches_no_bet": sum(1 for item in forecasts if item.get("status") == "NO BET"),
            "failed_sources": failed,
        },
        "no_bet_notice": "Le partite NO BET sono mostrate perché i dati non bastano o non sono comparabili. Nessun esito consigliato.",
        **published_forecast_lists(forecasts),
        "notice": "Le probabilità sono stime statistiche e non garantiscono risultati.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Stagione {season}; campionati scaricati: {downloaded}; stime generate: {len(result['matches'])}")
    if failed:
        print("Fonti non raggiungibili:", "; ".join(failed))


if __name__ == "__main__":
    main()
