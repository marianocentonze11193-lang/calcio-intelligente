#!/usr/bin/env python3
"""Aggiunge quote 1X2 da API-Football usando la chiave già prevista per disponibilità.

La chiave è opzionale. Il limite prudenziale di richieste quote protegge la quota
gratuita condivisa con gli altri endpoint API-Football. Le risposte sono salvate
in cache e non vengono richieste più volte nello stesso giorno per lo stesso match.
"""
import json
import os
import re
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
MAX_ODDS_AGE_HOURS = 24
USER_AGENT = "CalcioIntelligente/1.0"


def quote_is_fresh(entry, now=None):
    """Le quote API vengono riutilizzate solo per 24 ore dalla richiesta."""
    fetched_at = str((entry or {}).get("fetched_at") or "")
    try:
        stamp = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    now = now or now_utc()
    age = (now - stamp.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= MAX_ODDS_AGE_HOURS * 3600


def odds_payload_diagnostics(payload):
    """Riassume copertura effettiva senza esporre chiavi o dati sensibili."""
    response = payload.get("response", []) or []
    bookmakers = [b for event in response for b in (event.get("bookmakers", []) or [])]
    bet_names = sorted({str(bet.get("name") or "") for book in bookmakers for bet in (book.get("bets", []) or [])})
    return {"events": len(response), "bookmakers": len(bookmakers), "bet_types": bet_names[:20]}


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


def parse_all_odds_payload(payload, home, away):
    """Estrae 1X2, Over/Under, Gol/No Gol e doppia chance dalla stessa risposta."""
    one_x_two = {"home": None, "draw": None, "away": None}
    markets = {
        "over_under_1_5": {"over": None, "under": None},
        "over_under_2_5": {"over": None, "under": None},
        "over_under_3_5": {"over": None, "under": None},
        "btts": {"yes": None, "no": None},
        "double_chance": {"1x": None, "x2": None, "12": None},
    }

    def save_best(target, key, price):
        if key in target and price > 1 and (target[key] is None or price > target[key]):
            target[key] = price

    for event in payload.get("response", []) or []:
        for bookmaker in event.get("bookmakers", []) or []:
            for bet in bookmaker.get("bets", []) or []:
                name = team_key(bet.get("name"))
                bet_id = str(bet.get("id", ""))
                is_1x2 = name in {"matchwinner", "1x2", "fulltimeresult", "matchresult"} or bet_id == "1"
                is_totals = ("overunder" in name or "goalsoverunder" in name or "totalgoals" in name or bet_id == "5")
                is_btts = ("bothteamsscore" in name or "bothteams" in name or bet_id == "8")
                is_double = ("doublechance" in name or bet_id == "12")
                if not (is_1x2 or is_totals or is_btts or is_double):
                    continue
                for value in bet.get("values", []) or []:
                    raw_value = str(value.get("value", "")).strip()
                    normalized = team_key(raw_value)
                    try:
                        price = float(str(value.get("odd", "")).replace(",", "."))
                    except (TypeError, ValueError):
                        continue
                    if price <= 1:
                        continue
                    if is_1x2:
                        key = outcome_key(raw_value, home, away)
                        if key:
                            save_best(one_x_two, key, price)
                    elif is_totals:
                        line_match = re.search(r"(?:over|under)\s*([0-9]+(?:[.,][0-9]+)?)", raw_value, re.I)
                        if not line_match:
                            line_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", raw_value)
                        if not line_match:
                            continue
                        try:
                            line = float(line_match.group(1).replace(",", "."))
                        except ValueError:
                            continue
                        side = "over" if normalized.startswith("over") else "under" if normalized.startswith("under") else None
                        market_key = {1.5: "over_under_1_5", 2.5: "over_under_2_5", 3.5: "over_under_3_5"}.get(line)
                        if side and market_key:
                            save_best(markets[market_key], side, price)
                    elif is_btts:
                        side = "yes" if normalized in {"yes", "y", "si", "true"} else "no" if normalized in {"no", "n", "false"} else None
                        if side:
                            save_best(markets["btts"], side, price)
                    elif is_double:
                        compact = normalized.replace("home", "1").replace("draw", "x").replace("away", "2")
                        compact = compact.replace("local", "1").replace("tie", "x").replace("visitor", "2")
                        key = compact if compact in {"1x", "x2", "12"} else None
                        if not key:
                            if "1" in compact and "x" in compact:
                                key = "1x"
                            elif "x" in compact and "2" in compact:
                                key = "x2"
                            elif "1" in compact and "2" in compact:
                                key = "12"
                        if key:
                            save_best(markets["double_chance"], key, price)

    clean_markets = {}
    for key, values in markets.items():
        if key == "double_chance":
            valid = {k: v for k, v in values.items() if isinstance(v, (int, float))}
            if valid:
                clean_markets[key] = valid
        elif all(isinstance(values.get(k), (int, float)) for k in values):
            clean_markets[key] = values
    return {"one_x_two": one_x_two, "markets": clean_markets}


def parse_odds_payload(payload, home, away):
    """Compatibilità con il parser storico delle sole quote 1/X/2."""
    return parse_all_odds_payload(payload, home, away)["one_x_two"]


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


def calculate_value(match, prices, markets=None):
    probs = match.get("probabilities") or {}
    if isinstance(markets, dict) and markets:
        match["odds_markets"] = markets
        match["odds_markets_source"] = "API-Football"
    model = {"home": probs.get("home_win"), "draw": probs.get("draw"), "away": probs.get("away_win")}
    complete_1x2 = all(isinstance((prices or {}).get(k), (int, float)) and isinstance(model.get(k), (int, float)) for k in model)
    if complete_1x2:
        match["odds_1x2"] = prices
        match["odds_source"] = "API-Football"
        match["expected_value_1x2"] = {k: round((model[k] / 100) * prices[k] - 1, 4) for k in model}
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
    if not complete_1x2 and not markets:
        return


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
            parsed = parse_all_odds_payload(payload, match.get("home_team", ""), match.get("away_team", ""))
            prices, markets = parsed["one_x_two"], parsed["markets"]
            complete_1x2 = all(isinstance(prices.get(k), (int, float)) for k in ("home", "draw", "away"))
            available = complete_1x2 or bool(markets)
            cache["entries"][fixture_id] = {
                "fetched_at": now_utc().isoformat(),
                "date": str(match.get("date") or ""),
                "home_team": match.get("home_team"),
                "away_team": match.get("away_team"),
                "prices": prices if complete_1x2 else None,
                "markets": markets,
                "status": "available" if available else "not_available",
            }
            if available:
                calculate_value(match, prices, markets)
                match["odds_fetched_at"] = cache["entries"][fixture_id]["fetched_at"]
                fetched += 1
                print(f"Quote API-Football abbinate: {match.get('home_team')} - {match.get('away_team')} (1X2 completo: {complete_1x2}; mercati aggiuntivi: {len(markets)}).")
            else:
                diagnostics = odds_payload_diagnostics(payload)
                print(f"Nessuna quota per {match.get('home_team')} - {match.get('away_team')}: eventi={diagnostics['events']}, bookmaker={diagnostics['bookmakers']}, mercati={diagnostics['bet_types'] or 'nessuno'}. Possibile copertura/provider senza quote; non invento valori.")
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
        if not entry or entry.get("status") != "available":
            continue
        if not quote_is_fresh(entry):
            print(f"Cache quote scaduta per {match.get('home_team')} - {match.get('away_team')}: oltre {MAX_ODDS_AGE_HOURS} ore; non riutilizzo il prezzo.")
            continue
        prices = entry.get("prices") if isinstance(entry.get("prices"), dict) else {}
        markets = entry.get("markets") if isinstance(entry.get("markets"), dict) else {}
        if not prices and not markets:
            continue
        fixture = fixture_index.get(fixture_id, {})
        if str(entry.get("date") or "") != str(match.get("date") or ""):
            continue
        if team_key(entry.get("home_team")) != team_key(match.get("home_team")) or team_key(entry.get("away_team")) != team_key(match.get("away_team")):
            continue
        # Se le quote API-Football sono già state assegnate, non ricalcolare.
        if match.get("odds_source") != "API-Football" or not match.get("odds_markets"):
            calculate_value(match, prices, markets)
            match["odds_fetched_at"] = entry.get("fetched_at")

    data["odds_updated_at"] = now_utc().isoformat()
    data["odds_source_api_football"] = "API-Football"
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    available_entries = sum(1 for item in cache["entries"].values() if item.get("status") == "available" and quote_is_fresh(item))
    no_market_entries = sum(1 for item in cache["entries"].values() if item.get("status") == "not_available" and str(item.get("fetched_at") or "")[:10] == today)
    print(f"Quote API-Football complete: {fetched}; cache fresche: {available_entries}; risposte senza quote oggi: {no_market_entries}; richieste oggi: {used}/{MAX_NEW_REQUESTS_PER_DAY}.")


if __name__ == "__main__":
    main()
