#!/usr/bin/env python3
"""Arricchisce le partite con meteo Open-Meteo, solo informativo e senza alterare le probabilità."""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / "data" / "predictions.json"
COMPETITIONS = ROOT / "data" / "competition_data.json"
CACHE = ROOT / "data" / "weather_cache.json"
USER_AGENT = "CalcioIntelligente/1.0"
CACHE_TTL_HOURS = 3

COUNTRY_ALIASES = {
    "inghilterra": "united kingdom", "scozia": "united kingdom", "galles": "united kingdom",
    "irlanda": "ireland", "paesi bassi": "netherlands", "germania": "germany",
    "italia": "italy", "spagna": "spain", "francia": "france", "portogallo": "portugal",
    "belgio": "belgium", "turchia": "turkey", "austria": "austria", "danimarca": "denmark",
    "grecia": "greece", "finlandia": "finland", "norvegia": "norway", "polonia": "poland",
    "romania": "romania", "svezia": "sweden", "svizzera": "switzerland",
}

WEATHER_CODES = {
    0: "sereno", 1: "prevalentemente sereno", 2: "parzialmente nuvoloso", 3: "coperto",
    45: "nebbia", 48: "nebbia con brina", 51: "pioviggine debole", 53: "pioviggine moderata",
    55: "pioviggine intensa", 56: "pioviggine gelata debole", 57: "pioviggine gelata intensa",
    61: "pioggia debole", 63: "pioggia moderata", 65: "pioggia intensa",
    66: "pioggia gelata debole", 67: "pioggia gelata intensa", 71: "neve debole",
    73: "neve moderata", 75: "neve intensa", 77: "granuli di neve", 80: "rovesci deboli",
    81: "rovesci moderati", 82: "rovesci violenti", 85: "rovesci di neve deboli",
    86: "rovesci di neve intensi", 95: "temporale", 96: "temporale con grandine debole",
    99: "temporale con grandine intensa",
}


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def team_key(value):
    """Chiave tollerante ad accenti, punteggiatura e varianti note dei nomi."""
    import re
    import unicodedata
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char)).casefold()
    value = re.sub(r"[^a-z0-9]", "", value)
    aliases = {
        "athmadrid": "atleticodemadrid", "atleticomadrid": "atleticodemadrid",
        "athleticbilbao": "athleticclub", "espanyol": "espanol", "rcdespanyol": "espanol",
        "intermilan": "inter", "fcinternazionale": "inter", "internazionale": "inter",
        "acmilan": "milan", "juve": "juventus", "parissaintgermain": "psg",
        "manutd": "manchesterunited", "manchesterutd": "manchesterunited",
        "mancity": "manchestercity", "bayernmunchen": "bayernmunich", "fcbayern": "bayernmunich",
        "koln": "cologne", "fckoln": "cologne", "1fckoln": "cologne",
        "dortmund": "borussiadortmund", "gladbach": "borussiamonchengladbach",
        "monchengladbach": "borussiamonchengladbach", "psveindhoven": "psv",
        "sportinglisbon": "sportingcp", "redbullsalzburg": "salzburg",
    }
    return aliases.get(value, value)


def load_json(path, default):
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, (dict, list)) else default
    except (OSError, ValueError):
        return default


def get_location(city, country, cache, now):
    key = team_key(city + "," + country)
    cached = cache.get("locations", {}).get(key)
    if cached and cached.get("latitude") is not None and cached.get("longitude") is not None:
        return cached
    query = urllib.parse.urlencode({"name": city, "count": 10, "language": "en", "format": "json"})
    payload = fetch_json("https://geocoding-api.open-meteo.com/v1/search?" + query)
    results = payload.get("results") or []
    country_norm = team_key(COUNTRY_ALIASES.get(team_key(country), country))
    selected = next((item for item in results if country_norm and country_norm in team_key(item.get("country"))), None)
    # Non indovinare quando la città non coincide con il paese atteso.
    if not selected:
        return None
    result = {
        "latitude": selected.get("latitude"), "longitude": selected.get("longitude"),
        "timezone": selected.get("timezone") or "UTC", "resolved_name": selected.get("name", city),
        "country": selected.get("country", country), "cached_at": now.isoformat(),
    }
    if result["latitude"] is not None and result["longitude"] is not None:
        cache.setdefault("locations", {})[key] = result
        return result
    return None


def get_weather(location, kickoff_utc, now, cache):
    try:
        kickoff = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            return None
        local_kickoff = kickoff.astimezone(ZoneInfo(location["timezone"]))
    except (ValueError, TypeError, KeyError):
        return None
    if local_kickoff < now.astimezone(ZoneInfo(location["timezone"])) - timedelta(hours=3):
        return None
    cache_key = f'{location["latitude"]},{location["longitude"]}:{local_kickoff.strftime("%Y-%m-%dT%H")}'
    cached = cache.get("forecasts", {}).get(cache_key)
    if cached:
        try:
            saved_at = datetime.fromisoformat(cached.get("cached_at", ""))
            if now - saved_at < timedelta(hours=CACHE_TTL_HOURS):
                return cached
        except (ValueError, TypeError):
            pass
    params = urllib.parse.urlencode({
        "latitude": location["latitude"], "longitude": location["longitude"],
        "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,weather_code",
        "forecast_days": 7, "timezone": location["timezone"],
    })
    payload = fetch_json("https://api.open-meteo.com/v1/forecast?" + params)
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    target = local_kickoff.strftime("%Y-%m-%dT%H:00")
    if target not in times:
        return None
    index = times.index(target)
    def at(field):
        values = hourly.get(field) or []
        return values[index] if index < len(values) else None
    code = at("weather_code")
    result = {
        "status": "disponibile", "provider": "Open-Meteo",
        "location": location.get("resolved_name") or "",
        "timezone": location["timezone"], "kickoff_local": target,
        "temperature_c": at("temperature_2m"),
        "precipitation_probability_pct": at("precipitation_probability"),
        "precipitation_mm": at("precipitation"),
        "wind_speed_kmh": at("wind_speed_10m"),
        "weather_code": code, "description": WEATHER_CODES.get(code, "condizioni non specificate"),
        "cached_at": now.isoformat(),
        "note": "Contesto orientativo: il meteo non modifica le probabilità del modello.",
    }
    cache.setdefault("forecasts", {})[cache_key] = result
    return result


def weather_unavailable_reason(fixture):
    if not fixture:
        return "Partita non abbinata con certezza al calendario con dati dello stadio."
    if not fixture.get("kickoff_utc"):
        return "Orario ufficiale con fuso orario non verificato."
    if not str(fixture.get("venue_city") or "").strip():
        return "Città dello stadio non disponibile nella fonte."
    return "Previsione oraria non restituita dalla fonte meteo per questa sede e data."


def enrich():
    now = datetime.now(timezone.utc)
    predictions = load_json(PREDICTIONS, {})
    competitions = load_json(COMPETITIONS, {})
    cache = load_json(CACHE, {"locations": {}, "forecasts": {}})
    if not isinstance(cache, dict):
        cache = {"locations": {}, "forecasts": {}}
    cache.setdefault("locations", {})
    cache.setdefault("forecasts", {})
    fixtures = competitions.get("fixtures", []) if isinstance(competitions, dict) else []
    index = {}
    for fixture in fixtures:
        key = (fixture.get("date"), team_key(fixture.get("home_team")), team_key(fixture.get("away_team")))
        if all(key):
            existing = index.get(key)
            score = int(bool(fixture.get("venue_city"))) + int(bool(fixture.get("kickoff_utc")))
            old_score = int(bool((existing or {}).get("venue_city"))) + int(bool((existing or {}).get("kickoff_utc")))
            if existing is None or score > old_score:
                index[key] = fixture
    total = unavailable = failures = 0
    for group in ("matches", "no_bet_matches"):
        records = predictions.get(group, [])
        for match in records if isinstance(records, list) else []:
            match.pop("weather_context", None)
            key = (match.get("date"), team_key(match.get("home_team")), team_key(match.get("away_team")))
            fixture = index.get(key)
            reason = weather_unavailable_reason(fixture)
            if fixture and fixture.get("kickoff_utc") and str(fixture.get("venue_city") or "").strip():
                city = str(fixture["venue_city"]).strip()
                country = str(fixture.get("venue_country") or "").strip()
                try:
                    location = get_location(city, country, cache, now)
                    if location:
                        weather = get_weather(location, fixture["kickoff_utc"], now, cache)
                        if weather:
                            weather["venue"] = fixture.get("venue_name") or ""
                            weather["source_fixture"] = fixture.get("source", "calendario")
                            match["weather_context"] = weather
                            total += 1
                            continue
                        reason = "La fonte meteo non ha una previsione oraria disponibile per questa data."
                    else:
                        reason = "Città non geolocalizzata in modo univoco: previsione omessa per evitare una sede errata."
                except (OSError, ValueError, KeyError, TimeoutError) as error:
                    failures += 1
                    reason = "Servizio meteo temporaneamente non disponibile."
                    print(f"AVVISO meteo {match.get('home_team')} - {match.get('away_team')}: {error}")
            match["weather_context"] = {
                "status": "non_disponibile", "reason": reason, "provider": "Open-Meteo",
                "note": "Il meteo è solo informativo e non modifica le probabilità del modello.",
            }
            unavailable += 1
    predictions["weather_updated_at"] = now.isoformat()
    predictions["weather_summary"] = {
        "available": total, "unavailable": unavailable, "failures": failures,
        "note": "Il meteo è solo informativo e non modifica le probabilità.",
    }
    PREDICTIONS.write_text(json.dumps(predictions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Meteo: {total} disponibili, {unavailable} non disponibili, {failures} errori di servizio. Probabilità invariate.")


if __name__ == "__main__":
    enrich()
