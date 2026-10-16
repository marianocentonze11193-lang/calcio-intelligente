#!/usr/bin/env python3
"""Aggiunge quote 1X2 da API-Football usando la chiave già prevista per disponibilità.

La chiave è opzionale. Il limite prudenziale di richieste quote protegge la quota
gratuita condivisa con gli altri endpoint API-Football. Le risposte sono salvate
in cache e non vengono richieste più volte nello stesso giorno per lo stesso match.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = Path("data/predictions.json")
AVAILABILITY_CACHE_FILE = Path("data/availability_cache.json")
CACHE_FILE = Path("data/odds_cache.json")
BASE_URL = "https://v3.football.api-sports.io/odds"
MAX_NEW_REQUESTS_PER_DAY = 15
USER_AGENT = "CalcioIntelligente/1.0"


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def team_key(value):
    import re
    import unicodedata
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def outcome_key(value, home, away):
    key = team_key(value)
    if key in {"1", "home", "hometeam", "local", "casa"} or key == team_key(home):
        return "home"
    if key in {"x", "draw", "tie", "empate", "pareggio"}:
        return "draw"
    if key in {"2", "away", "awayteam", "visitor", "trasferta"} or key == team_key(away):
        return "away"
    # Alcuni bookmaker includono suffissi o nomi estesi della squadra.
    home_key, away_key = team_key(home), team_key(away)
    if home_key and (key.startswith(home_key) or home_key.startswith(key)):
        return "home"
    if away_key and (key.startswith(away_key) or away_key.startswith(key)):
        return "away"
    return None


def parse_odds_payload(payload, home, away):
    """Restituisce la quota massima 1/X/2 tra i bookmaker per il mercato vincente."""
    prices = {"home": None, "draw": None, "away": None}
    for event in payload.get("response", []) or []:
        for bookmaker in event.get("bookmakers", []) or []:
            for bet in bookmaker.get("bets", []) or []:
                bet_name = team_key(bet.get("name"))
                if bet_name not in {"matchwinner", "1x2", "fulltimeresult", "matchresult"} and str(bet.get("id", "")) != "1":
                    continue
                for value in bet.get("values", []) or []:
                    key = outcome_key(value.get("value"), home, away)
                    try:
                        price = float(str(value.get("odd", "")).replace(",", "."))
                    except (TypeError, ValueError):
                        continue
                    if key and price > 1 and (prices[key] is None or price > prices[key]):
                        prices[key] = price
    return prices


def api_get_odds(api_key, fixture_id):
    query = urllib.parse.urlencode({"fixture": fixture_id})
    request = urllib.request.Request(
        f"{BASE_URL}?{query}",
        headers={"x-apisports-key": api_key, "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=18) as response:
        payload = json.loads(response.read().decode("utf-8"))
    errors = payload.get("errors")
    if errors:
        raise ValueError(f"API-Football ha segnalato un errore: {errors}")
    return payload


def calculate_value(match, prices):
    probs = match.get("probabilities") or {}
    model = {"home": probs.get("home_win"), "draw": probs.get("draw"), "away": probs.get("away_win")}
    if not all(isinstance(prices.get(k), (int, float)) and isinstance(model.get(k), (int, float)) for k in prices):
        return
    match["odds_1x2"] = prices
    match["odds_source"] = "API-Football"
    match["expected_value_1x2"] = {k: round((model[k] / 100) * prices[k] - 1, 4) for k in prices}
    match["value_bets"] = []
    if match.get("status") == "Pronostico valutabile" and match.get("home_matches_sample", 0) >= 8 and match.get("away_matches_sample", 0) >= 8:
        for key, label in (("home", "1"), ("draw", "X"), ("away", "2")):
            ev = match["expected_value_1x2"][key]
            if ev >= 0.05:
                match["value_bets"].append({
                    "market": label,
                    "model_probability": model[key],
                    "best_odds": prices[key],
                    "expected_value": ev,
                })


def main():
    data = read_json(DATA_FILE, None)
    if not isinstance(data, dict):
        raise SystemExit("File data/predictions.json non trovato o non valido.")
    cache = read_json(CACHE_FILE, {"version": 1, "entries": {}, "daily_usage": {}})
    cache.setdefault("entries", {})
    cache.setdefault("daily_usage", {})
    today = now_utc().date().isoformat()
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()

    if not api_key:
        print("API_FOOTBALL_KEY non configurata: quote API-Football saltate senza interrompere il calcolo.")
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return

    availability = read_json(AVAILABILITY_CACHE_FILE, {})
    fixture_index = {}
    for day, fixtures in (availability.get("fixtures_by_date") or {}).items():
        for fixture in fixtures or []:
            fixture_id = str(fixture.get("id") or "")
            if fixture_id:
                fixture_index[fixture_id] = fixture

    matches = [m for m in data.get("matches", []) if isinstance(m, dict) and m.get("status") != "NO BET"]
    candidates = []
    for match in matches:
        availability_data = match.get("availability_data") or {}
        fixture_id = str(availability_data.get("fixture_id") or "")
        if not fixture_id or fixture_id not in fixture_index:
            continue
        fixture = fixture_index[fixture_id]
        if str(fixture.get("date") or "")[:10] != str(match.get("date") or "")[:10]:
            continue
        entry = cache["entries"].get(fixture_id) or {}
        fetched_at = str(entry.get("fetched_at") or "")
        # Una richiesta al giorno per partita, anche se la risposta non contiene quote.
        if fetched_at[:10] == today:
            continue
        candidates.append((str(match.get("date") or ""), str(match.get("kickoff") or "99:99"), fixture_id, match, fixture))

    used = int(cache["daily_usage"].get(today, 0) or 0)
    remaining = max(0, MAX_NEW_REQUESTS_PER_DAY - used)
    # Prima le gare più vicine al calcio d'inizio; il limite giornaliero mantiene
    # margine per calendario, indisponibilità e formazioni sul piano gratuito.
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    fetched = 0
    for _, _, fixture_id, match, fixture in candidates[:remaining]:
        try:
            payload = api_get_odds(api_key, fixture_id)
            prices = parse_odds_payload(payload, match.get("home_team", ""), match.get("away_team", ""))
            complete = all(isinstance(prices.get(k), (int, float)) for k in ("home", "draw", "away"))
            cache["entries"][fixture_id] = {
                "fetched_at": now_utc().isoformat(),
                "date": str(match.get("date") or ""),
                "home_team": match.get("home_team"),
                "away_team": match.get("away_team"),
                "prices": prices if complete else None,
                "status": "available" if complete else "not_available",
            }
            if complete:
                calculate_value(match, prices)
                fetched += 1
                print(f"Quote API-Football abbinate: {match.get('home_team')} - {match.get('away_team')}.")
            else:
                print(f"Nessuna quota 1X2 completa per {match.get('home_team')} - {match.get('away_team')}; non invento valori.")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO quote API-Football {fixture_id}: {error}")
            # Anche gli errori vengono registrati per evitare di martellare una fixture
            # in caso di indisponibilità temporanea della fonte.
            cache["entries"][fixture_id] = {
                "fetched_at": now_utc().isoformat(),
                "date": str(match.get("date") or ""),
                "home_team": match.get("home_team"),
                "away_team": match.get("away_team"),
                "prices": None,
                "status": "error",
            }
        used += 1

    cache["daily_usage"] = {today: used}
    cache["updated_at"] = now_utc().isoformat()
    # Riusa la cache per mantenere quote disponibili anche se il provider non
    # restituisce più il fixture nel refresh corrente, purché l'associazione sia certa.
    for match in matches:
        fixture_id = str((match.get("availability_data") or {}).get("fixture_id") or "")
        entry = cache["entries"].get(fixture_id) if fixture_id else None
        if not entry or entry.get("status") != "available" or not isinstance(entry.get("prices"), dict):
            continue
        fixture = fixture_index.get(fixture_id, {})
        if str(entry.get("date") or "") != str(match.get("date") or ""):
            continue
        if team_key(entry.get("home_team")) != team_key(match.get("home_team")) or team_key(entry.get("away_team")) != team_key(match.get("away_team")):
            continue
        # Se le quote API-Football sono già state assegnate, non ricalcolare.
        if match.get("odds_source") != "API-Football":
            calculate_value(match, entry["prices"])

    data["odds_updated_at"] = now_utc().isoformat()
    data["odds_source_api_football"] = "API-Football"
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Quote API-Football complete: {fetched}; richieste quote oggi: {used}/{MAX_NEW_REQUESTS_PER_DAY}.")


if __name__ == "__main__":
    main()
