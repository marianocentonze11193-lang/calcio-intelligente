#!/usr/bin/env python3
"""Sincronizza calendari stagionali e classifiche da ESPN con cache, controlli e diagnostica."""
import csv
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "competition_data.json"
BASE = "https://site.api.espn.com/apis"
TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
FOOTBALL_DATA = "https://www.football-data.co.uk"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_FOOTBALL_LEAGUE_IDS = {
 "eng.1":39,"esp.1":140,"ger.1":78,"ita.1":135,"fra.1":61,"sco.1":179,
 "ned.1":88,"por.1":94,"bel.1":144,"tur.1":203,"aut.1":218,"den.1":119,
 "gre.1":197,"fin.1":244,"irl.1":357,"nor.1":103,"pol.1":106,"rou.1":283,
 "swe.1":113,"sui.1":207,"uefa.champions":2,"uefa.europa":3,"uefa.europa.conf":848,
 "ita.coppa_italia":137,"eng.fa":45,"esp.copa_del_rey":143,"ger.dfb_pokal":81,
 "fra.coupe_de_france":66,"ned.knvb_cup":90,"por.taca_de_portugal":96,
 "sco.fa_cup":181,"tur.turkiye_kupasi":206,
}
_API_CALL_LOCK = threading.Lock()
_API_NEXT_CALL = 0.0
API_CALL_INTERVAL_SECONDS = 6.2

FOOTBALL_CODES = {
 "eng.1":("E0","E0","season"),"esp.1":("SP1","SP1","season"),"ger.1":("D1","D1","season"),
 "ita.1":("I1","I1","season"),"fra.1":("F1","F1","season"),"sco.1":("SC0","SC0","season"),
 "ned.1":("N1","N1","season"),"por.1":("P1","P1","season"),"bel.1":("B1","B1","season"),
 "tur.1":("T1","T1","season"),"gre.1":("G1","G1","season"),"aut.1":("AUT","AUT","rolling"),
 "den.1":("DNK","DNK","rolling"),"fin.1":("FIN","FIN","rolling"),"irl.1":("IRL","IRL","rolling"),
 "nor.1":("NOK","NOR","rolling"),"pol.1":("POL","POL","rolling"),"rou.1":("RO","ROU","rolling"),
 "swe.1":("SWE","SWE","rolling"),"sui.1":("SWZ","SWZ","rolling"),
}
EUROPEAN = {
    "uefa.champions": "Champions League",
    "uefa.europa": "Europa League",
    "uefa.europa.conf": "Conference League",
}
CUPS = {
    "ita.coppa_italia": "Coppa Italia",
    "eng.fa": "FA Cup",
    "esp.copa_del_rey": "Copa del Rey",
    "ger.dfb_pokal": "DFB-Pokal",
    "fra.coupe_de_france": "Coupe de France",
    "ned.knvb_cup": "KNVB Beker",
    "por.taca_de_portugal": "Taça de Portugal",
    "sco.fa_cup": "Scottish Cup",
    "tur.turkiye_kupasi": "Coppa di Turchia",
}
LEAGUES = {
    "eng.1": ("Premier League", "Inghilterra", "summer"),
    "esp.1": ("La Liga", "Spagna", "summer"),
    "ger.1": ("Bundesliga", "Germania", "summer"),
    "ita.1": ("Serie A", "Italia", "summer"),
    "fra.1": ("Ligue 1", "Francia", "summer"),
    "sco.1": ("Scottish Premiership", "Scozia", "summer"),
    "ned.1": ("Eredivisie", "Paesi Bassi", "summer"),
    "por.1": ("Primeira Liga", "Portogallo", "summer"),
    "bel.1": ("Belgian Pro League", "Belgio", "summer"),
    "tur.1": ("Super Lig turca", "Turchia", "summer"),
    "aut.1": ("Bundesliga austriaca", "Austria", "summer"),
    "den.1": ("Superliga danese", "Danimarca", "summer"),
    "gre.1": ("Super League greca", "Grecia", "summer"),
    "fin.1": ("Veikkausliiga finlandese", "Finlandia", "calendar"),
    "irl.1": ("Premier Division irlandese", "Irlanda", "calendar"),
    "nor.1": ("Eliteserien norvegese", "Norvegia", "calendar"),
    "pol.1": ("Ekstraklasa polacca", "Polonia", "summer"),
    "rou.1": ("Liga I rumena", "Romania", "summer"),
    "swe.1": ("Allsvenskan svedese", "Svezia", "calendar"),
    "sui.1": ("Super League svizzera", "Svizzera", "summer"),
}
COMPETITIONS = {
    **{code: {"name": name, "country": "Europa", "kind": "Coppa europea"} for code, name in EUROPEAN.items()},
    **{code: {"name": name, "country": country, "kind": "Coppa nazionale"}
       for code, name, country in [
           ("ita.coppa_italia", "Coppa Italia", "Italia"),
           ("eng.fa", "FA Cup", "Inghilterra"),
           ("esp.copa_del_rey", "Copa del Rey", "Spagna"),
           ("ger.dfb_pokal", "DFB-Pokal", "Germania"),
           ("fra.coupe_de_france", "Coupe de France", "Francia"),
           ("ned.knvb_cup", "KNVB Beker", "Paesi Bassi"),
           ("por.taca_de_portugal", "Taça de Portugal", "Portogallo"),
           ("sco.fa_cup", "Scottish Cup", "Scozia"),
           ("tur.turkiye_kupasi", "Coppa di Turchia", "Turchia"),
       ]},
    **{code: {"name": name, "country": country, "kind": "Campionato"}
       for code, (name, country, _) in LEAGUES.items()},
}


def fetch_json(url, retries=1):
    last_error = None
    candidates = [url]
    alternate = url.replace("https://site.api.espn.com", "https://site.web.api.espn.com")
    if alternate != url:
        candidates.append(alternate)
    for attempt in range(retries + 1):
        for candidate in candidates:
            try:
                request = urllib.request.Request(candidate, headers={
                    "User-Agent": USER_AGENT, "Accept": "application/json",
                    "Referer": "https://www.espn.com/soccer/",
                    "Origin": "https://www.espn.com",
                })
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Risposta JSON non è un oggetto")
                return payload
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                last_error = error
        if attempt < retries:
            time.sleep(0.5)
    raise RuntimeError(str(last_error))


def season_range(today, mode="summer"):
    if mode == "calendar":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    start_year = today.year if today.month >= 7 else today.year - 1
    return date(start_year, 7, 1), date(start_year + 1, 6, 30)


def month_chunks(start, end):
    cursor = start
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        chunk_end = min(end, next_month - timedelta(days=1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def quarter_chunks(start, end):
    cursor = start
    while cursor <= end:
        quarter_end_month = ((cursor.month - 1) // 3 + 1) * 3
        next_period = date(cursor.year + 1, 1, 1) if quarter_end_month == 12 else date(cursor.year, quarter_end_month + 1, 1)
        chunk_end = min(end, next_period - timedelta(days=1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def csv_field(row, *names):
    normalized = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in row.items()}
    for name in names:
        value = normalized.get(re.sub(r"[^a-z0-9]", "", name.lower()))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def csv_date(value):
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def fetch_domestic_csv(code, meta, start, end):
    internal, source_code, source_type = FOOTBALL_CODES[code]
    if source_type == "season":
        season = f"{start.year % 100:02d}{(start.year + 1) % 100:02d}"
        url = f"https://www.football-data.co.uk/mmz4281/{season}/{source_code}.csv"
    else:
        url = f"https://www.football-data.co.uk/new/{source_code}.csv"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": "https://www.football-data.co.uk/"})
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode("cp1252", errors="replace").lstrip("\\ufeffï»¿")
    reader = csv.DictReader(io.StringIO(text))
    events = []
    for row in reader:
        d = csv_date(csv_field(row, "Date"))
        home, away = csv_field(row, "HomeTeam"), csv_field(row, "AwayTeam")
        if not d or not start <= d <= end or not home or not away or home.casefold() == away.casefold():
            continue
        try:
            hg, ag = int(float(csv_field(row, "FTHG"))), int(float(csv_field(row, "FTAG")))
            done = 0 <= hg <= 15 and 0 <= ag <= 15
        except (ValueError, TypeError):
            hg = ag = None
            done = False
        events.append({
            "id": f"fd-{code}-{d.isoformat()}-{home.casefold()}-{away.casefold()}",
            "date": d.isoformat(), "kickoff": csv_field(row, "Time"),
            "timezone": "fuso orario non specificato dalla fonte", "home_team": home, "away_team": away,
            "status": "completed" if done else "scheduled", "home_goals": hg if done else None,
            "away_goals": ag if done else None, "competition_code": code, "competition": meta["name"],
            "country": meta["country"], "kind": meta["kind"], "source": "football-data.co.uk"
        })
    if not events:
        raise ValueError("nessuna partita valida nel CSV stagionale")
    return events, {"status": "loaded", "events": len(events),
                    "completed": sum(x["status"] == "completed" for x in events),
                    "source": "football-data.co.uk", "range_start": start.isoformat(), "range_end": end.isoformat()}


def calculate_domestic_table(fixtures, code, meta, season, updated_at):
    teams = {}
    games = [x for x in fixtures if x.get("competition_code") == code and x.get("status") == "completed"]
    def team(name):
        return teams.setdefault(name.casefold(), {"team_id":"", "team":name, "group":meta["name"], "played":0,
            "wins":0,"draws":0,"losses":0,"goals_for":0,"goals_against":0,"goal_difference":0,
            "points":0,"position":None,"record":"","source":"football-data.co.uk"})
    for game in games:
        h, a = team(game["home_team"]), team(game["away_team"])
        hg, ag = game["home_goals"], game["away_goals"]
        h["played"] += 1; a["played"] += 1
        h["goals_for"] += hg; h["goals_against"] += ag
        a["goals_for"] += ag; a["goals_against"] += hg
        if hg > ag:
            h["wins"] += 1; h["points"] += 3; a["losses"] += 1
        elif hg < ag:
            a["wins"] += 1; a["points"] += 3; h["losses"] += 1
        else:
            h["draws"] += 1; a["draws"] += 1; h["points"] += 1; a["points"] += 1
    rows = list(teams.values())
    for row in rows:
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
    rows.sort(key=lambda r:(r["points"],r["goal_difference"],r["goals_for"],r["wins"]),reverse=True)
    for i,row in enumerate(rows,1): row["position"] = i
    return {"competition":meta["name"],"country":meta["country"],"kind":meta["kind"],"season":season,
            "updated_at":updated_at,"rows":rows,
            "diagnostics":{"status":"computed_from_results" if len(rows)>=8 and games else "partial",
             "teams":len(rows),"results_used":len(games),"source":"football-data.co.uk",
             "note":"Classifica calcolata dai risultati acquisiti; può differire dalla classifica ufficiale per penalizzazioni o regole particolari."}}


def api_football_get(api_key, endpoint, params):
    global _API_NEXT_CALL
    query = urllib.parse.urlencode(params)
    url = f"{API_FOOTBALL_BASE}/{endpoint}?{query}"
    # API-Football free tiers have a per-minute limit. Pace requests to avoid
    # burst failures and keep the daily sync below the published quota.
    with _API_CALL_LOCK:
        wait = max(0.0, _API_NEXT_CALL - time.monotonic())
        if wait:
            time.sleep(wait)
        _API_NEXT_CALL = time.monotonic() + API_CALL_INTERVAL_SECONDS
    request = urllib.request.Request(url, headers={
        "x-apisports-key": api_key, "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError(f"API-Football error: {str(payload.get('errors') if isinstance(payload,dict) else 'JSON non valido')[:180]}")
    rows = payload.get("response")
    if not isinstance(rows, list):
        raise ValueError("API-Football: campo response non valido")
    return rows


def fetch_api_football_fixtures(api_key, code, meta, season):
    league_id = API_FOOTBALL_LEAGUE_IDS[code]
    response = api_football_get(api_key, "fixtures", {
        "league": league_id, "season": season, "timezone": "Europe/Rome"
    })
    events = []
    for item in response:
        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        home_obj, away_obj = teams.get("home") or {}, teams.get("away") or {}
        home, away = str(home_obj.get("name") or "").strip(), str(away_obj.get("name") or "").strip()
        raw_date = fixture.get("date")
        if not home or not away or home.casefold() == away.casefold() or not raw_date:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            local = parsed.astimezone(ZoneInfo("Europe/Rome"))
        except (ValueError, TypeError):
            continue
        status_obj = fixture.get("status") or {}
        short = str(status_obj.get("short") or "").upper()
        goals = item.get("goals") or {}
        try:
            hg = int(goals["home"]) if goals.get("home") is not None else None
            ag = int(goals["away"]) if goals.get("away") is not None else None
        except (TypeError, ValueError):
            hg = ag = None
        completed = short in {"FT", "AET", "PEN"} and hg is not None and ag is not None and 0 <= hg <= 15 and 0 <= ag <= 15
        live = short in {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"}
        state = "completed" if completed else "in_progress" if live else "scheduled"
        events.append({
            "id": str(fixture.get("id") or ""),
            "date": local.date().isoformat(), "kickoff": local.strftime("%H:%M"),
            "timezone": "Europe/Rome", "home_team": home, "away_team": away,
            "status": state, "home_goals": hg if completed else None, "away_goals": ag if completed else None,
            "competition_code": code, "competition": meta["name"], "country": meta["country"],
            "kind": meta["kind"], "source": "API-Football",
        })
    if not events:
        raise ValueError("API-Football non ha restituito partite per questa competizione/stagione")
    return events, {
        "status": "loaded", "events": len(events),
        "completed": sum(x["status"] == "completed" for x in events),
        "scheduled": sum(x["status"] == "scheduled" for x in events),
        "source": "API-Football", "season": season,
        "range_start": min(x["date"] for x in events), "range_end": max(x["date"] for x in events),
    }


def fetch_api_football_standings(api_key, code, meta, season):
    response = api_football_get(api_key, "standings", {"league": API_FOOTBALL_LEAGUE_IDS[code], "season": season})
    rows = []
    for league in response:
        league_data = league.get("league") or {}
        groups = league_data.get("standings") or []
        for group_rows in groups:
            for item in group_rows or []:
                team = item.get("team") or {}
                overall = item.get("all") or {}
                goals = overall.get("goals") or {}
                name = str(team.get("name") or "").strip()
                if not name:
                    continue
                rows.append({
                    "team_id": str(team.get("id") or ""), "team": name,
                    "group": str(item.get("group") or league_data.get("name") or meta["name"]),
                    "played": overall.get("played"), "wins": overall.get("win"),
                    "draws": overall.get("draw"), "losses": overall.get("lose"),
                    "goals_for": goals.get("for"), "goals_against": goals.get("against"),
                    "goal_difference": item.get("goalsDiff"), "points": item.get("points"),
                    "position": item.get("rank"), "record": item.get("form") or "",
                    "source": "API-Football",
                })
    if len(rows) < 4:
        raise ValueError(f"API-Football non ha restituito una classifica valida ({len(rows)} squadre)")
    return {
        "competition": meta["name"], "country": meta["country"], "kind": meta["kind"],
        "season": season, "updated_at": datetime.now(timezone.utc).isoformat(), "rows": rows,
        "diagnostics": {"status": "available", "teams": len(rows), "source": "API-Football",
                        "note": "Classifica fornita dal provider API-Football."},
    }


def fetch_global_fixtures(today, jobs):
    url = "https://www.football-data.co.uk/fixtures.csv"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": "https://www.football-data.co.uk/"})
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode("cp1252", errors="replace").lstrip("\\ufeffï»¿")
    reader = csv.DictReader(io.StringIO(text))
    source_to_code = {values[1]: code for code, values in FOOTBALL_CODES.items()}
    found = {code: [] for code in LEAGUES}
    for row in reader:
        code = source_to_code.get(csv_field(row, "Div", "Division"))
        if code not in LEAGUES:
            continue
        match_date = csv_date(csv_field(row, "Date"))
        meta, start, end, _ = jobs[code]
        if not match_date or match_date < today or match_date > end:
            continue
        home, away = csv_field(row, "HomeTeam"), csv_field(row, "AwayTeam")
        if not home or not away or home.casefold() == away.casefold():
            continue
        found[code].append({
            "id": f"fd-{code}-{match_date.isoformat()}-{home.casefold()}-{away.casefold()}",
            "date": match_date.isoformat(), "kickoff": csv_field(row, "Time"),
            "timezone": "fuso orario non specificato dalla fonte", "home_team": home, "away_team": away,
            "status": "scheduled", "home_goals": None, "away_goals": None,
            "competition_code": code, "competition": meta["name"], "country": meta["country"],
            "kind": meta["kind"], "source": "football-data.co.uk fixtures.csv",
        })
    return found


def parse_event(event, code, meta):
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    status_obj = ((comp.get("status") or {}).get("type") or {})
    raw_date = event.get("date") or ""
    try:
        parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        local = parsed.astimezone(ZoneInfo("Europe/Rome"))
        event_date = local.date()
        kickoff = local.strftime("%H:%M")
    except (ValueError, TypeError):
        return None
    # Use the event's official ISO date as a stable calendar key; timezone is explicitly identified.
    home = away = None
    for competitor in comp.get("competitors", []):
        team = (competitor.get("team") or {})
        name = str(team.get("displayName") or "").strip()
        if not name:
            continue
        score_raw = competitor.get("score")
        try:
            score = int(float(score_raw)) if score_raw not in (None, "") else None
        except (TypeError, ValueError):
            score = None
        if competitor.get("homeAway") == "home":
            home = (name, score)
        elif competitor.get("homeAway") == "away":
            away = (name, score)
    if not home or not away or home[0].casefold() == away[0].casefold():
        return None
    completed = bool(status_obj.get("completed")) and home[1] is not None and away[1] is not None
    if completed and not (0 <= home[1] <= 15 and 0 <= away[1] <= 15):
        return None
    return {
        "id": str(event.get("id") or ""),
        "date": event_date.isoformat(),
        "kickoff": kickoff,
        "timezone": "Europe/Rome",
        "home_team": home[0],
        "away_team": away[0],
        "status": "completed" if completed else ("in_progress" if status_obj.get("inProgress") else "scheduled"),
        "home_goals": home[1] if completed else None,
        "away_goals": away[1] if completed else None,
        "competition_code": code,
        "competition": meta["name"],
        "country": meta["country"],
        "kind": meta["kind"],
        "source": "ESPN",
    }


def fetch_calendar_competition(code, meta, start, end):
    matches = {}
    successful_chunks = 0
    failed_chunks = []
    base = f"{BASE}/site/v2/sports/soccer/{code}/scoreboard"
    # ESPN rifiuta gli intervalli di date per queste coppe: il suo scoreboard
    # funziona con una singola data. Per limitare il carico, sincronizziamo per
    # le coppe solo i risultati recenti e il calendario utile alle previsioni.
    # Il modello consulta i 4 giorni precedenti e pubblica le prossime 5 giornate.
    if code in EUROPEAN or code in CUPS:
        today = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome")).date()
        query_start = max(start, today - timedelta(days=7))
        query_end = min(end, today + timedelta(days=14))
        chunks = ((query_start + timedelta(days=offset), query_start + timedelta(days=offset))
                  for offset in range((query_end - query_start).days + 1))
    else:
        query_start, query_end = start, end
        chunks = quarter_chunks(start, end)
    for chunk_start, chunk_end in chunks:
        date_param = (
            f"{chunk_start:%Y%m%d}" if chunk_start == chunk_end
            else f"{chunk_start:%Y%m%d}-{chunk_end:%Y%m%d}"
        )
        url = f"{base}?dates={date_param}&limit=100"
        try:
            payload = fetch_json(url)
            events = payload.get("events")
            if not isinstance(events, list):
                raise ValueError("campo events mancante")
            successful_chunks += 1
            for event in events:
                item = parse_event(event, code, meta)
                if not item or not (chunk_start.isoformat() <= item["date"] <= chunk_end.isoformat()):
                    continue
                # ESPN event id is preferred; date+teams protects against duplicate source ids.
                key = item["id"] or "|".join((item["date"], item["home_team"].casefold(), item["away_team"].casefold()))
                matches[key] = item
        except Exception as error:
            failed_chunks.append({"from": chunk_start.isoformat(), "to": chunk_end.isoformat(), "error": str(error)[:180]})
    return code, list(matches.values()), {
        "status": "complete_window" if not failed_chunks else ("partial" if successful_chunks else "unavailable"),
        "chunks_ok": successful_chunks, "chunks_failed": failed_chunks,
        "range_start": query_start.isoformat(), "range_end": query_end.isoformat(),
        "events": len(matches), "source": "ESPN",
    }


def extract_stat(stats, aliases):
    for stat in stats or []:
        key = str(stat.get("name") or stat.get("type") or "").replace("_", "").replace(" ", "").lower()
        if key in aliases:
            value = stat.get("value")
            if value is None:
                value = stat.get("displayValue")
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def parse_standings(payload, code, meta):
    rows = []
    groups = payload.get("children") or []
    # Some league responses expose a single standings object without children.
    if not groups and payload.get("standings"):
        groups = [{"name": meta["name"], "standings": payload["standings"]}]
    for group in groups:
        standings = group.get("standings") or {}
        entries = standings.get("entries") or []
        group_name = group.get("name") or group.get("abbreviation") or meta["name"]
        for entry in entries:
            team = entry.get("team") or {}
            name = str(team.get("displayName") or "").strip()
            if not name:
                continue
            stats = entry.get("stats") or []
            row = {
                "team_id": str(team.get("id") or ""),
                "team": name,
                "group": group_name,
                "played": extract_stat(stats, {"gamesplayed", "played", "gp"}),
                "wins": extract_stat(stats, {"wins", "won", "w"}),
                "draws": extract_stat(stats, {"ties", "draws", "drawn", "d"}),
                "losses": extract_stat(stats, {"losses", "lost", "l"}),
                "goals_for": extract_stat(stats, {"pointsfor", "goalsfor", "gf", "for"}),
                "goals_against": extract_stat(stats, {"pointsagainst", "goalsagainst", "ga", "against"}),
                "goal_difference": extract_stat(stats, {"pointdifferential", "goaldifference", "gd"}),
                "points": extract_stat(stats, {"points", "pts"}),
                "position": extract_stat(stats, {"playoffseed", "rank", "position", "standing"}),
                "record": entry.get("statsSummary") or entry.get("note") or "",
                "source": "ESPN",
            }
            rows.append(row)
    rows.sort(key=lambda row: (row["group"], row["position"] if row["position"] is not None else 999, row["team"].casefold()))
    # If ESPN omits rank/position, derive it only when points and GD exist, with deterministic tie-breakers.
    by_group = {}
    for row in rows:
        by_group.setdefault(row["group"], []).append(row)
    for group_rows in by_group.values():
        if any(row["position"] is not None for row in group_rows):
            continue
        if all(row["points"] is not None and row["goal_difference"] is not None for row in group_rows):
            ordered = sorted(group_rows, key=lambda row: (row["points"], row["goal_difference"], row["goals_for"] or 0), reverse=True)
            for pos, row in enumerate(ordered, 1):
                row["position"] = pos
    return rows


def fetch_standings(code, meta, season_year):
    url = f"{BASE}/v2/sports/soccer/{code}/standings?season={season_year}"
    payload = fetch_json(url)
    rows = parse_standings(payload, code, meta)
    # Reject empty or implausibly small tables rather than publishing them as complete.
    if len(rows) < 4:
        raise ValueError(f"classifica incompleta: solo {len(rows)} squadre")
    groups = {}
    for row in rows:
        groups[row["group"]] = groups.get(row["group"], 0) + 1
    return rows, {"status": "available", "teams": len(rows), "groups": groups, "source": "ESPN", "season": season_year}


def main():
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Europe/Rome")).date()
    old = {}
    if OUTPUT.exists():
        try: old = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except (OSError, ValueError): old = {}
    old_fixtures = old.get("fixtures", []) if isinstance(old.get("fixtures"), list) else []
    old_tables = old.get("standings", {}) if isinstance(old.get("standings"), dict) else {}
    old_coverage = old.get("coverage", {}) if isinstance(old.get("coverage"), dict) else {}
    try:
        old_stamp = datetime.fromisoformat(str(old.get("updated_at", "")).replace("Z", "+00:00"))
        if old_stamp.tzinfo is None: old_stamp = old_stamp.replace(tzinfo=timezone.utc)
        cache_age = now - old_stamp.astimezone(timezone.utc)
        cache_fresh = timedelta(0) <= cache_age <= timedelta(hours=20)
        cache_recent = timedelta(0) <= cache_age <= timedelta(hours=6)
    except (ValueError, TypeError):
        cache_fresh = False
        cache_recent = False
    if cache_recent and os.environ.get("FORCE_COMPETITION_SYNC", "").strip() != "1":
        print(f"Calendario coppe/campionati aggiornato da meno di 6 ore ({old.get('updated_at')}); sincronizzazione saltata.")
        return
    jobs = {}
    for code, meta in COMPETITIONS.items():
        start, end = season_range(today, LEAGUES[code][2]) if code in LEAGUES else season_range(today, "summer")
        jobs[code] = (meta, start, end, start.year)

    fresh, coverage, success, failed = {}, {}, set(), set(jobs)
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    cached_api_codes = set()
    cached_tables = set()
    if api_key and cache_fresh:
        for code in jobs:
            diag = old_coverage.get(code, {})
            cached_rows = [item for item in old_fixtures if item.get("competition_code") == code]
            if diag.get("source") == "API-Football" and diag.get("status") == "loaded" and cached_rows:
                fresh[code] = cached_rows
                coverage[code] = diag
                success.add(code); failed.discard(code); cached_api_codes.add(code)
            table = old_tables.get(code)
            if isinstance(table, dict) and table.get("diagnostics", {}).get("source") == "API-Football" and table.get("updated_at"):
                try:
                    table_stamp = datetime.fromisoformat(str(table["updated_at"]).replace("Z", "+00:00"))
                    if table_stamp.tzinfo is None: table_stamp = table_stamp.replace(tzinfo=timezone.utc)
                    if timedelta(0) <= now - table_stamp.astimezone(timezone.utc) <= timedelta(hours=20):
                        cached_tables.add(code)
                except (ValueError, TypeError):
                    pass
        print(f"Cache API-Football riutilizzata per {len(cached_api_codes)} competizioni.")
    if api_key:
        # Un'unica richiesta fixtures per competizione recupera tutta la stagione.
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch_api_football_fixtures, api_key, code, jobs[code][0], jobs[code][3]): code for code in jobs if code not in cached_api_codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    events, diag = future.result()
                    fresh[code] = events; coverage[code] = diag
                    success.add(code); failed.discard(code)
                    print(f"API-Football {code}: {len(events)} partite")
                except Exception as error:
                    coverage[code] = {"status":"unavailable","source":"API-Football","error":str(error)[:180]}
                    print(f"AVVISO API-Football {code}: {error}")

    # Fonte di riserva per i campionati: risultati storici e calendario eventualmente incluso nei CSV.
    domestic_fallback = set(LEAGUES) - success
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_domestic_csv, code, jobs[code][0], jobs[code][1], jobs[code][2]): code for code in domestic_fallback}
        for future in as_completed(futures):
            code = futures[future]
            try:
                events, diag = future.result()
                fresh[code] = events; coverage[code] = {**coverage.get(code, {}), **diag}
                success.add(code); failed.discard(code)
                print(f"football-data {code}: {len(events)} gare, {diag['completed']} risultati")
            except Exception as error:
                coverage.setdefault(code, {}).update({"status":"unavailable","source":"football-data.co.uk","error":str(error)[:160]})
                print(f"AVVISO football-data {code}: {error}")

    # Integra le partite future presenti nel feed generale di football-data.
    try:
        global_fixtures = fetch_global_fixtures(today, jobs)
        for code, events in global_fixtures.items():
            if not events:
                continue
            existing = {(x["date"], x["home_team"].casefold(), x["away_team"].casefold()) for x in fresh.get(code, [])}
            additions = [x for x in events if (x["date"], x["home_team"].casefold(), x["away_team"].casefold()) not in existing]
            if additions:
                fresh.setdefault(code, []).extend(additions)
                success.add(code); failed.discard(code)
                diag = coverage.setdefault(code, {"source":"football-data.co.uk"})
                diag["future_fixtures"] = len(additions)
                diag["future_source"] = "football-data.co.uk fixtures.csv"
                diag["events"] = len(fresh[code])
        print("Feed generale football-data: integrazione completata.")
    except Exception as error:
        coverage["global_fixtures"] = {"status":"unavailable","source":"football-data.co.uk","error":str(error)[:160]}
        print(f"AVVISO fixtures.csv: {error}")

    # ESPN rimane un fallback per coppe quando API-Football non è disponibile.
    espn_codes = (set(EUROPEAN) | set(CUPS)) - success
    espn_codes.update((set(LEAGUES) - success))
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_calendar_competition, code, jobs[code][0], jobs[code][1], jobs[code][2]): code for code in espn_codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                _, events, diag = future.result()
                coverage[code] = {**coverage.get(code, {}), **diag}
                if events:
                    fresh[code] = events; success.add(code); failed.discard(code)
                else:
                    failed.add(code)
                print(f"ESPN {code}: {len(events)} eventi ({diag['status']})")
            except Exception as error:
                failed.add(code)
                coverage.setdefault(code, {}).update({"status":"unavailable","source":"ESPN","error":str(error)[:160]})
                print(f"ERRORE ESPN {code}: {error}")

    fixture_map = {}
    for item in old_fixtures:
        if isinstance(item, dict) and item.get("competition_code") in failed:
            key=(item.get("competition_code"),item.get("id") or "|".join((item.get("date",""),item.get("home_team",""),item.get("away_team",""))))
            fixture_map[key]=item
    for code in success:
        for item in fresh.get(code,[]):
            key=(code,item.get("id") or "|".join((item.get("date",""),item.get("home_team",""),item.get("away_team",""))))
            fixture_map[key]=item
    fixtures=sorted(fixture_map.values(),key=lambda x:(x.get("date",""),x.get("kickoff",""),x.get("competition","")))

    tables={}
    if api_key:
        # Riserva le chiamate alle classifiche ufficiali alle cinque leghe principali e alle tre coppe UEFA.
        # Per gli altri campionati la tabella è calcolata dai risultati completi già scaricati.
        official_table_codes = {"eng.1", "esp.1", "ita.1", "uefa.champions"}
        eligible_tables = (official_table_codes & success) - cached_tables
        tables.update({code: old_tables[code] for code in cached_tables if code in old_tables})
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch_api_football_standings, api_key, code, jobs[code][0], jobs[code][3]): code for code in eligible_tables}
            for future in as_completed(futures):
                code=futures[future]
                try:
                    tables[code]=future.result()
                    coverage.setdefault(code,{})["standings"]={"status":"available","source":"API-Football","teams":len(tables[code]["rows"])}
                except Exception as error:
                    coverage.setdefault(code,{})["standings"]={"status":"unavailable","source":"API-Football","error":str(error)[:160]}
    for code,(meta,start,end,season) in jobs.items():
        if code in tables:
            continue
        if code in LEAGUES and code in success:
            tables[code]=calculate_domestic_table(fixtures,code,meta,season,now.isoformat())
        elif code in old_tables:
            tables[code]=old_tables[code]
            if code in failed:
                tables[code].setdefault("diagnostics",{})["status"]="stale"
                tables[code]["diagnostics"]["refresh_error"]=coverage.get(code,{}).get("error","fonte non disponibile")

    errors=[]; seen=set(); valid=[]
    for item in fixtures:
        try: date.fromisoformat(item["date"])
        except (ValueError,TypeError,KeyError):
            errors.append("data non valida"); continue
        if not item.get("home_team") or not item.get("away_team") or item["home_team"].casefold()==item["away_team"].casefold():
            errors.append("nomi squadre non validi"); continue
        if item.get("status")=="completed":
            hg,ag=item.get("home_goals"),item.get("away_goals")
            if not isinstance(hg,int) or not isinstance(ag,int) or not (0<=hg<=15 and 0<=ag<=15):
                errors.append("punteggio finale non valido"); continue
        key=(item.get("competition_code"),item.get("id") or item["date"]+item["home_team"]+item["away_team"])
        if key in seen: continue
        seen.add(key); valid.append(item)

    result={"schema_version":3,"updated_at":now.isoformat(),
      "source_policy":"Fonte prioritaria: API-Football se la chiave è configurata; fallback football-data.co.uk per i campionati ed ESPN per le coppe. Classifiche ufficiali API-Football per Premier League, La Liga, Serie A e Champions League; altre classifiche ricalcolate dai risultati, con possibili differenze per penalizzazioni o regole speciali. Date, squadre e punteggi sono controllati.",
      "fixtures":valid,"standings":tables,"coverage":coverage,
      "summary":{"competitions_configured":len(jobs),
        "competitions_with_fixtures":sum(1 for code in jobs if coverage.get(code,{}).get("events",0)>0),
        "fixtures_total":len(valid),"fixtures_completed":sum(1 for x in valid if x.get("status")=="completed"),
        "fixtures_scheduled":sum(1 for x in valid if x.get("status")=="scheduled"),
        "standings_available":sum(1 for x in tables.values() if x.get("diagnostics",{}).get("status") in ("available","computed_from_results","partial")),
        "validation_errors":errors[:20]}}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Riepilogo:",json.dumps(result["summary"],ensure_ascii=False))
    if errors: raise SystemExit("Controllo integrità fallito: "+"; ".join(errors[:5]))


if __name__ == "__main__":
    main()
