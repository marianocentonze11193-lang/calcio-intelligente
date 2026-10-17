#!/usr/bin/env python3
"""Sincronizza calendari stagionali e classifiche da ESPN con cache, controlli e diagnostica."""
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "competition_data.json"
BASE = "https://site.api.espn.com/apis"
TIMEOUT = 12
USER_AGENT = "CalcioIntelligente/1.0 (+public schedule sync)"
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


def fetch_json(url, retries=2):
    last_error = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Risposta JSON non è un oggetto")
            return payload
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(0.4 * (attempt + 1))
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


def parse_event(event, code, meta):
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    status_obj = ((comp.get("status") or {}).get("type") or {})
    raw_date = event.get("date") or ""
    try:
        parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        local = parsed.astimezone(timezone(timedelta(hours=2)))  # canonical display fallback; date is replaced below for UTC-safe parsing
        event_date = parsed.date()
        kickoff = parsed.strftime("%H:%M")
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
        "timezone": "UTC source timestamp",
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
    for chunk_start, chunk_end in month_chunks(start, end):
        url = f"{base}?dates={chunk_start:%Y%m%d}-{chunk_end:%Y%m%d}&limit=100"
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
        "range_start": start.isoformat(), "range_end": end.isoformat(),
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
    today = now.date()
    previous = {}
    if OUTPUT.exists():
        try:
            previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
    old_fixtures = previous.get("fixtures", []) if isinstance(previous.get("fixtures"), list) else []
    old_standings = previous.get("standings", {}) if isinstance(previous.get("standings"), dict) else {}
    old_coverage = previous.get("coverage", {}) if isinstance(previous.get("coverage"), dict) else {}

    meta_by_code = dict(COMPETITIONS)
    jobs = {}
    for code, meta in meta_by_code.items():
        if code in LEAGUES:
            start, end = season_range(today, LEAGUES[code][2])
            season_year = start.year
        else:
            start, end = season_range(today, "summer")
            season_year = start.year
        jobs[code] = (meta, start, end, season_year)

    fresh_by_code = {}
    coverage = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_calendar_competition, code, meta, start, end): code
                   for code, (meta, start, end, _) in jobs.items()}
        for future in as_completed(futures):
            code = futures[future]
            try:
                _, events, diag = future.result()
                fresh_by_code[code] = events
                coverage[code] = diag
                print(f"Calendario {code}: {len(events)} eventi, stato {diag['status']}")
            except Exception as error:
                coverage[code] = {"status": "unavailable", "error": str(error)[:200], "source": "ESPN"}
                print(f"ERRORE calendario {code}: {error}")

    # Preserve last known fixtures for failed date ranges; successful windows replace only matching competition dates.
    fixture_map = {}
    for item in old_fixtures:
        if isinstance(item, dict) and item.get("competition_code") in jobs:
            key = (item.get("competition_code"), item.get("id") or "|".join((item.get("date", ""), item.get("home_team", ""), item.get("away_team", ""))))
            fixture_map[key] = item
    for code, events in fresh_by_code.items():
        diag = coverage.get(code, {})
        if diag.get("status") == "unavailable":
            continue
        for item in events:
            key = (code, item.get("id") or "|".join((item.get("date", ""), item.get("home_team", ""), item.get("away_team", ""))))
            fixture_map[key] = item
    fixtures = sorted(fixture_map.values(), key=lambda item: (item.get("date", ""), item.get("kickoff", ""), item.get("competition", "")))

    standings = dict(old_standings)
    def get_table(code, meta, season_year):
        try:
            rows, diag = fetch_standings(code, meta, season_year)
            standings[code] = {
                "competition": meta["name"], "country": meta["country"], "kind": meta["kind"],
                "season": season_year, "updated_at": now.isoformat(), "rows": rows, "diagnostics": diag,
            }
            return code, diag
        except Exception as error:
            old = standings.get(code)
            if old:
                old.setdefault("diagnostics", {})["refresh_error"] = str(error)[:180]
                old["diagnostics"]["status"] = "stale"
            return code, {"status": "stale" if old else "unavailable", "error": str(error)[:180]}

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(get_table, code, meta, season_year)
                   for code, (meta, _, _, season_year) in jobs.items()]
        for future in as_completed(futures):
            code, diag = future.result()
            coverage.setdefault(code, {})["standings"] = diag
            print(f"Classifica {code}: {diag.get('status')}")

    # Consistency checks: valid dates, distinct teams, valid scores and no duplicate event keys.
    errors = []
    seen = set()
    valid_fixtures = []
    for item in fixtures:
        try:
            date.fromisoformat(item["date"])
        except (ValueError, TypeError, KeyError):
            errors.append("data non valida")
            continue
        if not item.get("home_team") or not item.get("away_team") or item["home_team"].casefold() == item["away_team"].casefold():
            errors.append("nomi squadre non validi")
            continue
        if item.get("status") == "completed":
            hg, ag = item.get("home_goals"), item.get("away_goals")
            if not isinstance(hg, int) or not isinstance(ag, int) or not (0 <= hg <= 15 and 0 <= ag <= 15):
                errors.append("punteggio finale non valido")
                continue
        key = (item.get("competition_code"), item.get("id") or item["date"] + item["home_team"] + item["away_team"])
        if key in seen:
            continue
        seen.add(key)
        valid_fixtures.append(item)

    result = {
        "schema_version": 1,
        "updated_at": now.isoformat(),
        "source_policy": "ESPN public endpoints; schema and internal consistency validated. Coverage depends on upstream availability; see per-competition diagnostics.",
        "fixtures": valid_fixtures,
        "standings": standings,
        "coverage": coverage,
        "summary": {
            "competitions_configured": len(jobs),
            "competitions_with_fixtures": sum(1 for code in jobs if coverage.get(code, {}).get("events", 0) > 0),
            "fixtures_total": len(valid_fixtures),
            "fixtures_completed": sum(1 for item in valid_fixtures if item.get("status") == "completed"),
            "fixtures_scheduled": sum(1 for item in valid_fixtures if item.get("status") == "scheduled"),
            "standings_available": sum(1 for item in standings.values() if item.get("diagnostics", {}).get("status") == "available"),
            "validation_errors": errors[:20],
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Riepilogo calendario/classifiche:", json.dumps(result["summary"], ensure_ascii=False))
    if errors:
        raise SystemExit("Controllo integrità fallito: " + "; ".join(errors[:5]))


if __name__ == "__main__":
    main()
