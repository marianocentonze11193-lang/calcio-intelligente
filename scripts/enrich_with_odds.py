#!/usr/bin/env python3
"""Aggiunge quote 1X2 opzionali e stime di valore atteso tramite The Odds API.

Richiede il secret ODDS_API_KEY. Se manca o la quota non è disponibile, non inventa valori.
"""
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATA_FILE = Path("data/predictions.json")
BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORTS = {
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "Serie A": "soccer_italy_serie_a",
    "Ligue 1": "soccer_france_ligue_one",
    "Scottish Premiership": "soccer_scotland_premiership",
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Primeira Liga": "soccer_portugal_primeira_liga",
    "Belgian Pro League": "soccer_belgium_first_div",
    "Super Lig turca": "soccer_turkey_super_league",
    "Bundesliga austriaca": "soccer_austria_bundesliga",
    "Superliga danese": "soccer_denmark_superliga",
    "Super League greca": "soccer_greece_super_league",
    "Veikkausliiga finlandese": "soccer_finland_veikkausliiga",
    "Premier Division irlandese": "soccer_league_of_ireland",
    "Eliteserien norvegese": "soccer_norway_eliteserien",
    "Ekstraklasa polacca": "soccer_poland_ekstraklasa",
    "Liga I rumena": "soccer_romania_liga_1",
    "Allsvenskan svedese": "soccer_sweden_allsvenskan",
    "Super League svizzera": "soccer_switzerland_superleague",
    # Le coppe sono mappate solo per le quote: il modello non genera pronostici per queste competizioni.
    "UEFA Champions League (quote)": "soccer_uefa_champs_league",
    "UEFA Europa League (quote)": "soccer_uefa_europa_league",
    "UEFA Conference League (quote)": "soccer_uefa_europa_conference_league",
}


def team_key(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value.lower())


# Alias espliciti: niente fuzzy matching generico che rischierebbe di associare
# quote alla squadra sbagliata.
TEAM_ALIASES = {
    "inter": {"inter", "intermilan", "fcinternazionale", "internazionale", "internazionalefc"},
    "intermilan": {"inter", "intermilan", "fcinternazionale", "internazionale", "internazionalefc"},
    "fcinternazionale": {"inter", "intermilan", "fcinternazionale", "internazionale", "internazionalefc"},
    "internazionale": {"inter", "intermilan", "fcinternazionale", "internazionale", "internazionalefc"},
    "internazionalefc": {"inter", "intermilan", "fcinternazionale", "internazionale", "internazionalefc"},
    "milan": {"milan", "acmilan", "acmilan1899"},
    "acmilan": {"milan", "acmilan", "acmilan1899"},
    "acmilan1899": {"milan", "acmilan", "acmilan1899"},
    "bologna": {"bologna", "bolognafc", "bolognafc1909"},
    "bolognafc": {"bologna", "bolognafc", "bolognafc1909"},
    "bolognafc1909": {"bologna", "bolognafc", "bolognafc1909"},
    "atalanta": {"atalanta", "atalantabc", "atalantabergamasca"},
    "atalantabc": {"atalanta", "atalantabc", "atalantabergamasca"},
    "atalantabergamasca": {"atalanta", "atalantabc", "atalantabergamasca"},
    "juventus": {"juventus", "juve", "juventusfc"},
    "juve": {"juventus", "juve", "juventusfc"},
    "juventusfc": {"juventus", "juve", "juventusfc"},
    "roma": {"roma", "asroma", "associazionesportivaroma"},
    "asroma": {"roma", "asroma", "associazionesportivaroma"},
    "associazionesportivaroma": {"roma", "asroma", "associazionesportivaroma"},
    "napoli": {"napoli", "sscnapoli", "societasportivacalcionapoli"},
    "sscnapoli": {"napoli", "sscnapoli", "societasportivacalcionapoli"},
    "societasportivacalcionapoli": {"napoli", "sscnapoli", "societasportivacalcionapoli"},
    "fiorentina": {"fiorentina", "acfiorentina"},
    "acfiorentina": {"fiorentina", "acfiorentina"},
    "lazio": {"lazio", "sslazio"},
    "sslazio": {"lazio", "sslazio"},
    "torino": {"torino", "torinofc"},
    "torinofc": {"torino", "torinofc"},
    "verona": {"verona", "hellasverona"},
    "hellasverona": {"verona", "hellasverona"},
    "psg": {"psg", "parissaintgermain", "parissaintgermainfc"},
    "parissaintgermain": {"psg", "parissaintgermain", "parissaintgermainfc"},
    "parissaintgermainfc": {"psg", "parissaintgermain", "parissaintgermainfc"},
    "parisfc": {"parisfc", "parisfootballclub"},
    "parisfootballclub": {"parisfc", "parisfootballclub"},
    "ajax": {"ajax", "ajaxamsterdam", "afcajax"},
    "ajaxamsterdam": {"ajax", "ajaxamsterdam", "afcajax"},
    "afcajax": {"ajax", "ajaxamsterdam", "afcajax"},
    "groningen": {"groningen", "fcgroningen"},
    "fcgroningen": {"groningen", "fcgroningen"},
    "twente": {"twente", "fctwente"},
    "fctwente": {"twente", "fctwente"},
    "utrecht": {"utrecht", "fcutrecht"},
    "fcutrecht": {"utrecht", "fcutrecht"},
    "psv": {"psv", "psveindhoven"},
    "psveindhoven": {"psv", "psveindhoven"},
    "feyenoord": {"feyenoord", "feyenoordrotterdam"},
    "feyenoordrotterdam": {"feyenoord", "feyenoordrotterdam"},
    "az": {"az", "azalkmaar"},
    "azalkmaar": {"az", "azalkmaar"},
    "manutd": {"manutd", "manchesterunited", "manchesterutd"},
    "manchesterunited": {"manutd", "manchesterunited", "manchesterutd"},
    "manchesterutd": {"manutd", "manchesterunited", "manchesterutd"},
    "mancity": {"mancity", "manchestercity"},
    "manchestercity": {"mancity", "manchestercity"},
    "athleticclub": {"athleticclub", "athleticbilbao"},
    "athleticbilbao": {"athleticclub", "athleticbilbao"},
    "atleticodemadrid": {"atleticodemadrid", "atleticomadrid"},
    "atleticomadrid": {"atleticodemadrid", "atleticomadrid"},
    "fcbayern": {"fcbayern", "bayernmunich", "bayernmunchen"},
    "bayernmunich": {"fcbayern", "bayernmunich", "bayernmunchen"},
    "bayernmunchen": {"fcbayern", "bayernmunich", "bayernmunchen"},
    "sportingcp": {"sportingcp", "sportinglisbon"},
    "sportinglisbon": {"sportingcp", "sportinglisbon"},
    "salzburg": {"salzburg", "redbullsalzburg"},
    "redbullsalzburg": {"salzburg", "redbullsalzburg"},
    "tottenham": {"tottenham", "tottenhamhotspur"},
    "tottenhamhotspur": {"tottenham", "tottenhamhotspur"},
    "wolves": {"wolves", "wolverhamptonwanderers"},
    "wolverhamptonwanderers": {"wolves", "wolverhamptonwanderers"},
    "newcastle": {"newcastle", "newcastleunited"},
    "newcastleunited": {"newcastle", "newcastleunited"},
    "westham": {"westham", "westhamunited"},
    "westhamunited": {"westham", "westhamunited"},
    "leicester": {"leicester", "leicestercity"},
    "leicestercity": {"leicester", "leicestercity"},
    "brighton": {"brighton", "brightonandhovealbion"},
    "brightonandhovealbion": {"brighton", "brightonandhovealbion"},
    "eintrachtfrankfurt": {"eintrachtfrankfurt", "eintracht"},
    "eintracht": {"eintrachtfrankfurt", "eintracht"},
    "borussiadortmund": {"borussiadortmund", "dortmund"},
    "dortmund": {"borussiadortmund", "dortmund"},
    "borussiamonchengladbach": {"borussiamonchengladbach", "monchengladbach", "gladbach"},
    "monchengladbach": {"borussiamonchengladbach", "monchengladbach", "gladbach"},
    "gladbach": {"borussiamonchengladbach", "monchengladbach", "gladbach"},
    "rbleipzig": {"rbleipzig", "rasenballsportleipzig", "rbleipzig"},
    "rasenballsportleipzig": {"rbleipzig", "rasenballsportleipzig", "rbleipzig"},
    "rbleipzig": {"rbleipzig", "rasenballsportleipzig", "rbleipzig"},
    "olympiquedemarseille": {"olympiquedemarseille", "marseille"},
    "marseille": {"olympiquedemarseille", "marseille"},
    "olympiquelyonnais": {"olympiquelyonnais", "lyon"},
    "lyon": {"olympiquelyonnais", "lyon"},
    "realbetis": {"realbetis", "betis"},
    "betis": {"realbetis", "betis"},
    "realsociedad": {"realsociedad", "sociedad"},
    "sociedad": {"realsociedad", "sociedad"},
    "celta": {"celta", "celtavigo"},
    "celtavigo": {"celta", "celtavigo"},
    "internacional": {"internacional", "internacionalportoalegre"},
    "internacionalportoalegre": {"internacional", "internacionalportoalegre"},
}




def team_keys(value):
    key = team_key(value)
    aliases = TEAM_ALIASES.get(key, {key})
    return {team_key(alias) for alias in aliases}


def same_team(first, second):
    return bool(team_keys(first) & team_keys(second))


def available_sports(api_key):
    """Legge le chiavi effettivamente disponibili nel piano/account senza consumare crediti odds."""
    query = urllib.parse.urlencode({"apiKey": api_key})
    request = urllib.request.Request(f"{BASE_URL}/?{query}",
                                     headers={"User-Agent": "CalcioIntelligente/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {item.get("key") for item in payload if item.get("key") and item.get("active", True)}


def fetch_odds(sport, api_key):
    query = urllib.parse.urlencode({
        "apiKey": api_key,
        "regions": os.environ.get("ODDS_REGIONS", "uk,eu"),
        "markets": "h2h",
        "oddsFormat": "decimal",
    })
    request = urllib.request.Request(f"{BASE_URL}/{sport}/odds/?{query}",
                                     headers={"User-Agent": "CalcioIntelligente/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def best_prices(event):
    prices = {"home": None, "draw": None, "away": None}
    home_name, away_name = event.get("home_team"), event.get("away_team")
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                name = team_key(outcome.get("name"))
                key = "draw" if name in ("draw", "pareggio", "tie") else (
                    "home" if same_team(outcome.get("name"), home_name) else "away" if same_team(outcome.get("name"), away_name) else None
                )
                price = outcome.get("price")
                if key and isinstance(price, (int, float)) and price > 1:
                    if prices[key] is None or price > prices[key]:
                        prices[key] = float(price)
    return prices


def main():
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not DATA_FILE.exists():
        raise SystemExit("File data/predictions.json non trovato.")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if not api_key:
        print("ODDS_API_KEY non configurata: quote e value bet lasciate non disponibili.")
        return

    events_by_league = {}
    try:
        active_sports = available_sports(api_key)
        print(f"Chiavi sport attive rilevate: {len(active_sports)}.")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        print(f"AVVISO: elenco sport non disponibile: {error}")
        active_sports = set()

    # Recupera le quote solo per le competizioni effettivamente presenti nei pronostici.
    # Le chiavi vengono validate contro l'endpoint ufficiale, così le leghe fuori stagione
    # o non incluse nel piano non causano richieste inutili.
    for league, sport in SPORTS.items():
        if not any(m.get("league") == league for m in data.get("matches", [])):
            continue
        if sport not in active_sports:
            print(f"Quote {league}: chiave {sport} non attiva/disponibile nell'account, salto.")
            continue
        try:
            events_by_league[league] = fetch_odds(sport, api_key)
            print(f"Quote scaricate per {league}: {len(events_by_league[league])} eventi.")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO: quote {league} non disponibili: {error}")

    matched = value_count = 0
    for match in data.get("matches", []):
        events = events_by_league.get(match.get("league"), [])
        # Match solo se casa e trasferta coincidono nell'ordine corretto.
        # Gli alias sono espliciti; niente associazioni approssimative non verificabili.
        event = next((e for e in events
                      if same_team(e.get("home_team"), match.get("home_team"))
                      and same_team(e.get("away_team"), match.get("away_team"))), None)
        if not event:
            continue
        prices = best_prices(event)
        probs = match.get("probabilities") or {}
        model = {
            "home": probs.get("home_win"),
            "draw": probs.get("draw"),
            "away": probs.get("away_win"),
        }
        if not all(prices[k] and isinstance(model[k], (int, float)) for k in prices):
            continue
        matched += 1
        match["value_bets"] = []
        match["odds_1x2"] = prices
        ev = {k: round((model[k] / 100) * prices[k] - 1, 4) for k in prices}
        match["expected_value_1x2"] = ev
        # Soglia conservativa solo indicativa; non equivale a redditività dimostrata.
        if match.get("status") == "Pronostico valutabile" and match.get("home_matches_sample", 0) >= 8 and match.get("away_matches_sample", 0) >= 8:
            for key, label in (("home", "1"), ("draw", "X"), ("away", "2")):
                if ev[key] >= 0.05:
                    match["value_bets"].append({
                        "market": label, "model_probability": model[key],
                        "best_odds": prices[key], "expected_value": ev[key],
                    })
                    value_count += 1

    data["odds_updated_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).replace(microsecond=0).isoformat()
    data["odds_source"] = "The Odds API" if matched else data.get("odds_source")
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Quote abbinate: {matched}; candidati value bet teorici (EV >= 5%, campione >= 8 gare per lato): {value_count}.")


if __name__ == "__main__":
    main()
