#!/usr/bin/env python3
"""Arricchisce le partite con indisponibilità e formazioni API-Football, senza cambiare le probabilità."""
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_FILE = Path("data/predictions.json")
CACHE_FILE = Path("data/availability_cache.json")
BASE_URL = "https://v3.football.api-sports.io"
REFRESH_SECONDS = 6 * 60 * 60
# Il piano rilevato consente oggi e domani: limita le richieste alle date accessibili.
API_DAYS_AHEAD = 1
MAX_LINEUP_CALLS_PER_RUN = 1
TIMEZONE = "Europe/Rome"


def now_utc():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def normalize_team(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", value.lower())


ALIASES = [
    {"inter", "intermilan", "fcinternazionale", "internazionale"},
    {"milan", "acmilan"},
    {"psg", "parissaintgermain", "parissaintgermainfc"},
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
]


def team_keys(value):
    key = normalize_team(value)
    for group in ALIASES:
        if key in group:
            return group
    return {key}


def same_team(first, second):
    return bool(team_keys(first) & team_keys(second))


def api_get(api_key, endpoint, params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{BASE_URL}/{endpoint}?{query}",
        headers={"x-apisports-key": api_key, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError(f"Risposta API-Football non valida su {endpoint}: {payload.get('errors') if isinstance(payload, dict) else 'JSON non valido'}")
    results = payload.get("response")
    if not isinstance(results, list):
        raise ValueError(f"Risposta API-Football senza elenco response su {endpoint}")
    return results


def load_cache():
    if not CACHE_FILE.exists():
        return {
            "last_full_refresh": None,
            "fixtures_by_date": {},
            "injuries_by_fixture": {},
            "injury_checked_dates": [],
            "lineups_by_fixture": {},
            "lineup_attempts": {},
            "unavailable_dates": {},
        }
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            raise ValueError("cache non valida")
        cache.setdefault("fixtures_by_date", {})
        cache.setdefault("injuries_by_fixture", {})
        cache.setdefault("injury_checked_dates", [])
        cache.setdefault("lineups_by_fixture", {})
        cache.setdefault("lineup_attempts", {})
        cache.setdefault("unavailable_dates", {})
        return cache
    except (OSError, ValueError):
        return {
            "last_full_refresh": None,
            "fixtures_by_date": {},
            "injuries_by_fixture": {},
            "injury_checked_dates": [],
            "lineups_by_fixture": {},
            "lineup_attempts": {},
        }


def add_unique_injury(cache, fixture_id, entry):
    entries = cache.setdefault("injuries_by_fixture", {}).setdefault(str(fixture_id), [])
    identity = (entry.get("team"), entry.get("player"), entry.get("type"), entry.get("reason"))
    if any((old.get("team"), old.get("player"), old.get("type"), old.get("reason")) == identity for old in entries):
        return False
    entries.append(entry)
    return True


def full_refresh(api_key, cache, today):
    dates = [(today + timedelta(days=offset)).isoformat() for offset in range(API_DAYS_AHEAD + 1)]
    for day in dates:
        try:
            fixtures = api_get(api_key, "fixtures", {"date": day, "timezone": TIMEZONE})
            normalized = []
            for item in fixtures:
                fixture = item.get("fixture") or {}
                teams = item.get("teams") or {}
                home = (teams.get("home") or {}).get("name")
                away = (teams.get("away") or {}).get("name")
                fixture_id = fixture.get("id")
                start = parse_datetime(fixture.get("date"))
                if not fixture_id or not home or not away or not start:
                    continue
                normalized.append({
                    "id": str(fixture_id),
                    "date": str(fixture.get("date", ""))[:10],
                    "kickoff_utc": start.isoformat(),
                    "home": home,
                    "away": away,
                    "status": ((fixture.get("status") or {}).get("short") or ""),
                    "league": (item.get("league") or {}).get("name", ""),
                })
            cache["fixtures_by_date"][day] = normalized
            cache.setdefault("unavailable_dates", {}).pop(day, None)
            injuries = api_get(api_key, "injuries", {"date": day, "timezone": TIMEZONE})
            # La richiesta è andata a buon fine: l'assenza di record non viene
            # interpretata come prova che tutti i giocatori siano disponibili.
            cache["injury_checked_dates"] = sorted(set(cache["injury_checked_dates"]) | {day})
            fixture_ids = {item["id"] for item in normalized}
            for fixture_id in fixture_ids:
                cache["injuries_by_fixture"].pop(fixture_id, None)
            for item in injuries:
                fixture_id = str(((item.get("fixture") or {}).get("id")) or "")
                if not fixture_id or fixture_id not in fixture_ids:
                    continue
                team = (item.get("team") or {}).get("name", "")
                player = item.get("player") or {}
                entry = {
                    "team": team,
                    "player": player.get("name", "Giocatore non specificato"),
                    "type": player.get("type") or "Indisponibilità",
                    "reason": player.get("reason") or "",
                }
                add_unique_injury(cache, fixture_id, entry)
            print(f"{day}: {len(normalized)} partite API-Football, {len(injuries)} segnalazioni indisponibilità.")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as error:
            # Mantieni l'ultimo dato valido per questa data, senza bloccare i pronostici.
            if "Free plans do not have access to this date" in str(error):
                cache.setdefault("unavailable_dates", {})[day] = "Data fuori copertura del piano API-Football configurato."
            print(f"AVVISO disponibilità {day}: {error}. Mantengo la cache precedente.")
    cache["last_full_refresh"] = now_utc().isoformat()


def refresh_one_lineup(api_key, cache):
    now = now_utc()
    candidates = []
    for fixtures in cache.get("fixtures_by_date", {}).values():
        for fixture in fixtures:
            start = parse_datetime(fixture.get("kickoff_utc"))
            if not start or start < now - timedelta(minutes=10) or start > now + timedelta(minutes=100):
                continue
            if fixture.get("status") not in ("NS", "TBD", ""):
                continue
            fixture_id = fixture["id"]
            lineup = cache.get("lineups_by_fixture", {}).get(fixture_id)
            if lineup and (lineup.get("home_starters") or lineup.get("away_starters")):
                continue
            attempted = parse_datetime(cache.get("lineup_attempts", {}).get(fixture_id))
            if attempted and now - attempted < timedelta(minutes=50):
                continue
            candidates.append((start, fixture))
    if not candidates:
        return
    candidates.sort(key=lambda entry: entry[0])
    _, fixture = candidates[0]
    fixture_id = fixture["id"]
    cache.setdefault("lineup_attempts", {})[fixture_id] = now.isoformat()
    try:
        response = api_get(api_key, "fixtures/lineups", {"fixture": fixture_id})
        by_team = {}
        for item in response:
            team_name = (item.get("team") or {}).get("name", "")
            starters = [p.get("player", {}).get("name", "") for p in item.get("startXI", []) if p.get("player", {}).get("name")]
            substitutes = [p.get("player", {}).get("name", "") for p in item.get("substitutes", []) if p.get("player", {}).get("name")]
            by_team[team_name] = {
                "formation": item.get("formation") or "",
                "starters": starters,
                "substitutes": substitutes,
                "coach": (item.get("coach") or {}).get("name") or "",
            }
        home = next((value for name, value in by_team.items() if same_team(name, fixture["home"])), {})
        away = next((value for name, value in by_team.items() if same_team(name, fixture["away"])), {})
        if home or away:
            cache.setdefault("lineups_by_fixture", {})[fixture_id] = {
                "updated_at": now.isoformat(),
                "home_starters": home.get("starters", []),
                "away_starters": away.get("starters", []),
                "home_substitutes": home.get("substitutes", []),
                "away_substitutes": away.get("substitutes", []),
                "home_formation": home.get("formation", ""),
                "away_formation": away.get("formation", ""),
                "home_coach": home.get("coach", ""),
                "away_coach": away.get("coach", ""),
            }
            print(f"Formazioni ricevute per {fixture['home']} - {fixture['away']}.")
        else:
            print(f"Formazioni non ancora pubblicate per {fixture['home']} - {fixture['away']}.")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as error:
        print(f"AVVISO formazioni {fixture['home']} - {fixture['away']}: {error}")


def match_fixture(match, cache):
    day = str(match.get("date") or "")[:10]
    candidates = cache.get("fixtures_by_date", {}).get(day, [])
    for fixture in candidates:
        if same_team(fixture.get("home"), match.get("home_team")) and same_team(fixture.get("away"), match.get("away_team")):
            return fixture
    return None


def availability_for(match, cache, configured):
    if not configured:
        return {
            "status": "non_configurata",
            "source": "API-Football",
            "note": "Fonte infortuni/formazioni non configurata: aggiungi il secret API_FOOTBALL_KEY su GitHub per attivare il controllo.",
            "injuries": [],
            "lineups": None,
        }
    fixture = match_fixture(match, cache)
    if not fixture:
        day = str(match.get("date") or "")[:10]
        unavailable = cache.get("unavailable_dates", {}).get(day)
        if unavailable:
            return {
                "status": "fuori_copertura_api",
                "source": "API-Football",
                "note": unavailable + " Le probabilità non vengono corrette con dati non verificati.",
                "injuries": [],
                "lineups": None,
            }
        return {
            "status": "non_trovata",
            "source": "API-Football",
            "note": "Partita non abbinata con certezza al calendario API-Football; nessun dato di disponibilità attribuito.",
            "injuries": [],
            "lineups": None,
        }
    fixture_id = fixture["id"]
    day = str(match.get("date") or "")[:10]
    injuries = cache.get("injuries_by_fixture", {}).get(fixture_id, [])
    checked = day in cache.get("injury_checked_dates", [])
    lineup = cache.get("lineups_by_fixture", {}).get(fixture_id)
    if injuries:
        status = "segnalazioni_trovate"
        note = f"La fonte segnala {len(injuries)} indisponibilità; elenco non necessariamente completo."
    elif checked:
        status = "nessuna_segnalazione"
        note = "La fonte non riporta indisponibilità per questa partita; non è una conferma che tutti i giocatori siano disponibili."
    else:
        status = "dati_non_disponibili"
        note = "La fonte non ha confermato la copertura delle indisponibilità per questa data."
    if lineup and (lineup.get("home_starters") or lineup.get("away_starters")):
        lineup_status = "formazioni_pubblicate"
    else:
        lineup_status = "non_pubblicate"
    return {
        "status": status,
        "source": "API-Football",
        "note": note,
        "fixture_id": fixture_id,
        "injuries": injuries,
        "lineups": lineup,
        "lineup_status": lineup_status,
    }


def main():
    if not DATA_FILE.exists():
        raise SystemExit("File data/predictions.json non trovato.")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        for match in data.get("matches", []) + data.get("no_bet_matches", []):
            match["availability_data"] = availability_for(match, {}, False)
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not CACHE_FILE.exists():
            CACHE_FILE.write_text(json.dumps(load_cache(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("API_FOOTBALL_KEY non configurata: pronostici mantenuti, dati disponibilità dichiarati non configurati.")
        return

    print("API_FOOTBALL_KEY presente: avvio verifica della connessione API-Football (la chiave non viene stampata).")
    cache = load_cache()
    today = now_utc().astimezone().date()
    last_refresh = parse_datetime(cache.get("last_full_refresh"))
    if not last_refresh or now_utc() - last_refresh >= timedelta(seconds=REFRESH_SECONDS):
        full_refresh(api_key, cache, today)
    # Le formazioni arrivano in prossimità del calcio d'inizio: massimo una chiamata per esecuzione.
    refresh_one_lineup(api_key, cache)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for match in data.get("matches", []) + data.get("no_bet_matches", []):
        match["availability_data"] = availability_for(match, cache, True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    configured_matches = sum(
        1 for match in data.get("matches", []) + data.get("no_bet_matches", [])
        if match.get("availability_data", {}).get("status") not in ("non_trovata", "non_configurata")
    )
    print(f"Dati disponibilità aggiornati: {configured_matches} partite abbinate. Le probabilità non sono state modificate.")


if __name__ == "__main__":
    main()
