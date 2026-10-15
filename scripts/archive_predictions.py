#!/usr/bin/env python3
"""Archivia la prima stima per partita e aggiorna gli esiti quando i risultati sono disponibili."""
import csv
import io
import json
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS_FILE = ROOT / "data" / "predictions.json"
HISTORY_FILE = ROOT / "data" / "history.json"
SOURCE = "https://www.football-data.co.uk"
USER_AGENT = "CalcioIntelligente/1.0"
LEAGUES = {
    "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga",
    "I1": "Serie A", "F1": "Ligue 1", "SC0": "Scottish Premiership",
    "N1": "Eredivisie", "P1": "Primeira Liga", "B1": "Belgian Pro League", "T1": "Super Lig turca",
}
ESPN_LEAGUES = {
    "Premier League": "eng.1", "La Liga": "esp.1", "Bundesliga": "ger.1",
    "Serie A": "ita.1", "Ligue 1": "fra.1", "Scottish Premiership": "sco.1",
    "Eredivisie": "ned.1", "Primeira Liga": "por.1", "Belgian Pro League": "bel.1",
    "Super Lig turca": "tur.1",
}


def team_key(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def parse_date(value):
    value = str(value or "").strip()
    for candidate in (value, value[:10]):
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def season_code(today):
    start_year = today.year if today.month >= 7 else today.year - 1
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def read_csv(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode("cp1252", errors="replace").lstrip("\ufeffï»¿")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames:
        reader.fieldnames = [name.strip().lstrip("\ufeffï»¿") for name in reader.fieldnames]
    return list(reader)


def result_index(rows):
    index = {}
    for row in rows:
        match_date = parse_date(row.get("Date") or row.get("date"))
        home = (row.get("HomeTeam") or row.get("Home Team") or "").strip()
        away = (row.get("AwayTeam") or row.get("Away Team") or "").strip()
        hg = row.get("FTHG") or row.get("HG")
        ag = row.get("FTAG") or row.get("AG")
        if not match_date or not home or not away or hg in (None, "") or ag in (None, ""):
            continue
        try:
            score = (int(float(hg)), int(float(ag)))
        except (ValueError, TypeError):
            continue
        index[(match_date, team_key(home), team_key(away))] = score
    return index


def fetch_espn_results(league, dates):
    """Fallback gratuito ESPN per recuperare risultati conclusi non trovati nel CSV."""
    sport_code = ESPN_LEAGUES.get(league)
    if not sport_code:
        return {}
    found = {}
    for date_value in sorted(set(dates)):
        try:
            day = datetime.strptime(date_value, "%Y-%m-%d").strftime("%Y%m%d")
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{sport_code}/scoreboard?dates={day}&limit=100"
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
        for event in payload.get("events", []):
            competitions = event.get("competitions") or []
            if not competitions:
                continue
            competition = competitions[0]
            status = (competition.get("status") or {}).get("type") or {}
            if not status.get("completed"):
                continue
            event_date = parse_date(event.get("date", ""))
            home = away = None
            for competitor in competition.get("competitors", []):
                team = (competitor.get("team") or {}).get("displayName", "").strip()
                score = competitor.get("score")
                if competitor.get("homeAway") == "home":
                    home = (team, score)
                elif competitor.get("homeAway") == "away":
                    away = (team, score)
            if not event_date or not home or not away:
                continue
            try:
                score = (int(float(home[1])), int(float(away[1])))
            except (ValueError, TypeError):
                continue
            found[(event_date, team_key(home[0]), team_key(away[0]))] = score
    return found


def calculate_metrics(records):
    evaluated = [item for item in records if item.get("outcome") in ("1", "X", "2")
                 and isinstance(item.get("probabilities"), dict)]
    if not evaluated:
        return {"settled_matches": 0, "accuracy_1x2": None, "brier_score_1x2": None}
    correct = 0
    brier_total = 0.0
    for item in evaluated:
        probs = item["probabilities"]
        keys = ("home_win", "draw", "away_win")
        values = [float(probs.get(key, 0)) / 100 for key in keys]
        actual = [1.0 if item["outcome"] == label else 0.0 for label in ("1", "X", "2")]
        predicted = max(range(3), key=lambda idx: values[idx])
        actual_idx = ("1", "X", "2").index(item["outcome"])
        correct += int(predicted == actual_idx)
        brier_total += sum((values[idx] - actual[idx]) ** 2 for idx in range(3))
    return {
        "settled_matches": len(evaluated),
        "accuracy_1x2": round(correct / len(evaluated) * 100, 2),
        "brier_score_1x2": round(brier_total / len(evaluated), 4),
        "note": "Metriche descrittive su pronostici archiviati; non dimostrano redditività o affidabilità futura.",
    }


def calculate_metrics_by_league(records):
    """Metriche descrittive separate per competizione, solo su esiti già noti."""
    grouped = {}
    for item in records:
        league = item.get("league") or "Competizione sconosciuta"
        grouped.setdefault(league, []).append(item)
    return {
        league: calculate_metrics(items)
        for league, items in sorted(grouped.items())
        if any(x.get("outcome") in ("1", "X", "2") and isinstance(x.get("probabilities"), dict)
               for x in items)
    }


def main():
    if not PREDICTIONS_FILE.exists():
        raise SystemExit("File data/predictions.json non trovato.")
    data = json.loads(PREDICTIONS_FILE.read_text(encoding="utf-8"))
    if HISTORY_FILE.exists():
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    else:
        history = {"schema_version": 1, "records": []}
    records = history.get("records", [])
    known_ids = {item.get("id") for item in records}

    today = datetime.now(timezone.utc).date()
    for match in data.get("matches", []):
        match_date = parse_date(match.get("date"))
        match_id = match.get("id")
        if not match_id or match_id in known_ids or not match_date or match_date < today.isoformat():
            continue
        records.append({
            "id": match_id, "date": match_date, "league": match.get("league", ""),
            "home_team": match.get("home_team", ""), "away_team": match.get("away_team", ""),
            "status_at_archive": match.get("status", "NO BET"),
            "probabilities": match.get("probabilities") or {},
            "expected_home_goals": match.get("expected_home_goals"),
            "expected_away_goals": match.get("expected_away_goals"),
            "sample_matches": match.get("sample_matches", 0),
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "outcome": None, "home_goals": None, "away_goals": None,
        })
        known_ids.add(match_id)

    today = datetime.now(timezone.utc).date()
    current_season = season_code(today)
    indexes = {}
    # Scarica soltanto i campionati con partite da verificare già arrivate alla data odierna.
    # Così non si effettuano richieste inutili per tutte le leghe a ogni aggiornamento orario.
    leagues_to_check = {
        item.get("league") for item in records
        if item.get("outcome") is None and item.get("date", "") <= today.isoformat()
    }
    for code, league in LEAGUES.items():
        if league not in leagues_to_check:
            continue
        try:
            rows = read_csv(f"{SOURCE}/mmz4281/{current_season}/{code}.csv")
            indexes[league] = result_index(rows)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO: risultati per {league} ({current_season}) non disponibili: {error}")

    # Se il CSV principale non ha associato l'esito, tenta il tabellone risultati ESPN gratuito.
    pending_by_league = {}
    for item in records:
        if item.get("outcome") is None and item.get("date", "") <= today.isoformat():
            pending_by_league.setdefault(item.get("league"), []).append(item.get("date"))
    for league, dates in pending_by_league.items():
        fallback = fetch_espn_results(league, dates)
        if fallback:
            indexes.setdefault(league, {}).update(fallback)
            print(f"Risultati alternativi ESPN per {league}: {len(fallback)} risultati verificati.")

    settled = 0
    for item in records:
        if item.get("outcome") is not None:
            continue
        league_results = indexes.get(item.get("league"), {})
        key = (item.get("date"), team_key(item.get("home_team")), team_key(item.get("away_team")))
        score = league_results.get(key)
        if score is None:
            continue
        hg, ag = score
        item["home_goals"], item["away_goals"] = hg, ag
        item["outcome"] = "1" if hg > ag else "X" if hg == ag else "2"
        item["settled_at"] = datetime.now(timezone.utc).isoformat()
        settled += 1

    history["records"] = records
    history["updated_at"] = datetime.now(timezone.utc).isoformat()
    history["metrics"] = calculate_metrics(records)
    history["metrics_by_league"] = calculate_metrics_by_league(records)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Storico: {len(records)} partite archiviate; {settled} nuovi risultati associati.")
    print("Metriche 1X2:", json.dumps(history["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
