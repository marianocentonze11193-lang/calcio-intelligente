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
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS_FILE = ROOT / "data" / "predictions.json"
HISTORY_FILE = ROOT / "data" / "history.json"
SOURCE = "https://www.football-data.co.uk"
USER_AGENT = "CalcioIntelligente/1.0"
MIN_METRIC_MATCHES = 30
LEAGUES = {
    "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga",
    "I1": "Serie A", "F1": "Ligue 1", "SC0": "Scottish Premiership",
    "E1": "Championship", "E2": "League One", "E3": "League Two",
    "N1": "Eredivisie", "P1": "Primeira Liga", "B1": "Belgian Pro League", "T1": "Super Lig turca",
    "AUT": "Bundesliga austriaca", "DNK": "Superliga danese", "G1": "Super League greca",
    "FIN": "Veikkausliiga finlandese", "IRL": "Premier Division irlandese",
    "NOK": "Eliteserien norvegese", "POL": "Ekstraklasa polacca", "RO": "Liga I rumena",
    "SWE": "Allsvenskan svedese", "SWZ": "Super League svizzera",
}
EXTRA_FOOTBALL_DATA_LEAGUES = frozenset({
    "AUT", "DNK", "FIN", "IRL", "NOK", "POL", "RO", "SWE", "SWZ",
})
EXTRA_SOURCE_CODES = {"NOK": "NOR", "RO": "ROU"}
ESPN_LEAGUES = {
    "Premier League": "eng.1", "Championship": "eng.2", "League One": "eng.3", "League Two": "eng.4",
    "La Liga": "esp.1", "Bundesliga": "ger.1",
    "Serie A": "ita.1", "Ligue 1": "fra.1", "Scottish Premiership": "sco.1",
    "Eredivisie": "ned.1", "Primeira Liga": "por.1", "Belgian Pro League": "bel.1",
    "Super Lig turca": "tur.1", "Bundesliga austriaca": "aut.1", "Superliga danese": "den.1",
    "Super League greca": "gre.1", "Veikkausliiga finlandese": "fin.1",
    "Premier Division irlandese": "irl.1", "Eliteserien norvegese": "nor.1",
    "Ekstraklasa polacca": "pol.1", "Liga I rumena": "rou.1",
    "Allsvenskan svedese": "swe.1", "Super League svizzera": "sui.1",
}
ESPN_TIMEZONES = {
    "Premier League": "Europe/London", "Championship": "Europe/London",
    "League One": "Europe/London", "League Two": "Europe/London", "Scottish Premiership": "Europe/London",
    "La Liga": "Europe/Madrid", "Bundesliga": "Europe/Berlin", "Serie A": "Europe/Rome",
    "Ligue 1": "Europe/Paris", "Eredivisie": "Europe/Amsterdam", "Primeira Liga": "Europe/Lisbon",
    "Belgian Pro League": "Europe/Brussels", "Super Lig turca": "Europe/Istanbul",
    "Bundesliga austriaca": "Europe/Vienna", "Superliga danese": "Europe/Copenhagen",
    "Super League greca": "Europe/Athens", "Veikkausliiga finlandese": "Europe/Helsinki",
    "Premier Division irlandese": "Europe/Dublin", "Eliteserien norvegese": "Europe/Oslo",
    "Ekstraklasa polacca": "Europe/Warsaw", "Liga I rumena": "Europe/Bucharest",
    "Allsvenskan svedese": "Europe/Stockholm", "Super League svizzera": "Europe/Zurich",
}


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


def season_code_for_match(match_date):
    parsed = datetime.strptime(match_date, "%Y-%m-%d").date()
    return season_code(parsed)


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
        home = (row.get("HomeTeam") or row.get("Home Team") or row.get("home_team") or "").strip()
        away = (row.get("AwayTeam") or row.get("Away Team") or row.get("away_team") or "").strip()
        hg = row.get("FTHG") or row.get("HG") or row.get("fthg")
        ag = row.get("FTAG") or row.get("AG") or row.get("ftag")
        if not match_date or not home or not away or hg in (None, "") or ag in (None, ""):
            continue
        try:
            raw_home, raw_away = float(hg), float(ag)
            if not raw_home.is_integer() or not raw_away.is_integer():
                continue
            score = (int(raw_home), int(raw_away))
        except (ValueError, TypeError):
            continue
        if not (0 <= score[0] <= 15 and 0 <= score[1] <= 15):
            continue
        home_key, away_key = team_key(home), team_key(away)
        if not home_key or not away_key or home_key == away_key:
            continue
        key = (match_date, home_key, away_key)
        if key in index and index[key] != score:
            index[key] = None
        elif key not in index:
            index[key] = score
    return {key: score for key, score in index.items() if score is not None}


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
            raw_date = event.get("date", "")
            try:
                event_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                event_date = event_dt.astimezone(
                    ZoneInfo(ESPN_TIMEZONES.get(league, "Europe/Rome"))
                ).date().isoformat()
            except (ValueError, TypeError):
                event_date = parse_date(raw_date)
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
    evaluated = []
    for item in records:
        probs = item.get("probabilities")
        if item.get("outcome") not in ("1", "X", "2") or not isinstance(probs, dict):
            continue
        values = [probs.get(key) for key in ("home_win", "draw", "away_win")]
        if not all(isinstance(value, (int, float)) and 0 <= value <= 100 for value in values):
            continue
        if abs(sum(values) - 100) > 1.5:
            continue
        evaluated.append(item)
    if len(evaluated) < MIN_METRIC_MATCHES:
        return {
            "settled_matches": len(evaluated), "accuracy_1x2": None, "brier_score_1x2": None,
            "minimum_matches_required": MIN_METRIC_MATCHES,
            "note": f"Metriche non pubblicate: servono almeno {MIN_METRIC_MATCHES} partite concluse con probabilità archiviate.",
        }
    import math
    correct = 0
    brier_total = 0.0
    logloss_total = 0.0
    for item in evaluated:
        probs = item["probabilities"]
        keys = ("home_win", "draw", "away_win")
        values = [float(probs.get(key, 0)) / 100 for key in keys]
        actual = [1.0 if item["outcome"] == label else 0.0 for label in ("1", "X", "2")]
        predicted = max(range(3), key=lambda idx: values[idx])
        actual_idx = ("1", "X", "2").index(item["outcome"])
        correct += int(predicted == actual_idx)
        brier_total += sum((values[idx] - actual[idx]) ** 2 for idx in range(3))
        logloss_total += -math.log(max(1e-15, values[actual_idx]))
    return {
        "settled_matches": len(evaluated),
        "accuracy_1x2": round(correct / len(evaluated) * 100, 2),
        "brier_score_1x2": round(brier_total / len(evaluated), 4),
        "log_loss_1x2": round(logloss_total / len(evaluated), 4),
        "note": "Metriche descrittive su pronostici archiviati; Brier e log loss più bassi sono migliori. Non dimostrano redditività o affidabilità futura.",
    }


def calculate_value_bet_metrics(records):
    """Valuta i candidati 1X2 archiviati con quota al momento della previsione."""
    settled = []
    for item in records:
        outcome = item.get("outcome")
        if outcome not in ("1", "X", "2"):
            continue
        bets = item.get("value_bets")
        if not isinstance(bets, list):
            continue
        for bet in bets:
            if not isinstance(bet, dict) or bet.get("market") not in ("1", "X", "2"):
                continue
            try:
                odds = float(bet.get("best_odds"))
            except (TypeError, ValueError):
                continue
            if odds <= 1 or odds > 100:
                continue
            profit = odds - 1 if bet["market"] == outcome else -1.0
            settled.append({"won": bet["market"] == outcome, "profit": profit})
    count = len(settled)
    wins = sum(1 for bet in settled if bet["won"])
    profit_units = sum(bet["profit"] for bet in settled)
    return {
        "settled_bets": count,
        "wins": wins,
        "losses": count - wins,
        "net_units_per_one_unit_stake": round(profit_units, 4),
        "roi_percent": round(profit_units / count * 100, 2) if count >= MIN_METRIC_MATCHES else None,
        "minimum_bets_required_for_roi": MIN_METRIC_MATCHES,
        "note": "Solo candidati 1X2 archiviati con quota registrata. ROI pubblicato da almeno 30 selezioni concluse; simulazione teorica, non risultato delle schedine personali.",
    }


def calculate_metrics_by_league(records):
    """Metriche descrittive separate per competizione, solo su esiti già noti."""
    grouped = {}
    for item in records:
        league = item.get("league") or "Competizione sconosciuta"
        grouped.setdefault(league, []).append(item)
    metrics_by_league = {}
    for league, items in sorted(grouped.items()):
        metrics = calculate_metrics(items)
        # Applica la soglia dopo tutti i controlli di validità, non contando
        # semplicemente i record che contengono un dizionario probabilità.
        if metrics.get("settled_matches", 0) >= MIN_METRIC_MATCHES:
            metrics_by_league[league] = metrics
    return metrics_by_league


def calculate_metrics_by_european_context(records):
    """Confronta la calibrazione in partite con/senza un impegno UEFA recente verificato."""
    groups = {
        "recent_european_match": [item for item in records if item.get("european_context")],
        "no_recent_european_match": [item for item in records if not item.get("european_context")],
    }
    output = {}
    for key, items in groups.items():
        metrics = calculate_metrics(items)
        metrics["context_matches_archived"] = len(items)
        output[key] = metrics
    return {
        "groups": output,
        "note": "Il confronto è descrittivo e non dimostra che le coppe causino differenze. Le metriche compaiono solo dopo la soglia minima di partite concluse.",
    }


def calculate_model_market_metrics(records):
    """Confronto modello/mercato sugli stessi incontri conclusi con quote archiviate."""
    import math
    evaluated = []
    for item in records:
        if item.get("outcome") not in ("1", "X", "2"):
            continue
        model_probs = item.get("probabilities")
        market_probs = item.get("market_implied_probability_1x2")
        if not isinstance(model_probs, dict) or not isinstance(market_probs, dict):
            continue
        try:
            model = [float(model_probs[k]) / 100 for k in ("home_win", "draw", "away_win")]
            market = [float(market_probs[k]) / 100 for k in ("home", "draw", "away")]
        except (KeyError, TypeError, ValueError):
            continue
        if any(p < 0 or p > 1 for p in model + market):
            continue
        if abs(sum(model) - 1) > 0.015 or abs(sum(market) - 1) > 0.03:
            continue
        evaluated.append((model, market, ("1", "X", "2").index(item["outcome"])))
    if len(evaluated) < MIN_METRIC_MATCHES:
        return {
            "settled_matches_with_model_and_odds": len(evaluated),
            "minimum_matches_required": MIN_METRIC_MATCHES,
            "model": None,
            "market": None,
            "comparison": None,
            "note": f"Confronto non conclusivo: servono almeno {MIN_METRIC_MATCHES} partite concluse con probabilità modello e quote archiviate.",
        }
    results = {}
    for name, idx in (("model", 0), ("market", 1)):
        correct = 0
        brier_sum = 0.0
        logloss_sum = 0.0
        for model, market, actual_idx in evaluated:
            probs = (model, market)[idx]
            predicted_idx = max(range(3), key=lambda i: probs[i])
            correct += int(predicted_idx == actual_idx)
            actual = [1.0 if i == actual_idx else 0.0 for i in range(3)]
            brier_sum += sum((probs[i] - actual[i]) ** 2 for i in range(3))
            logloss_sum += -math.log(max(1e-15, probs[actual_idx]))
        n = len(evaluated)
        results[name] = {
            "accuracy_1x2": round(correct / n * 100, 2),
            "brier_score_1x2": round(brier_sum / n, 4),
            "log_loss_1x2": round(logloss_sum / n, 4),
        }
    comparison = {
        "accuracy_difference_percentage_points_model_minus_market": round(results["model"]["accuracy_1x2"] - results["market"]["accuracy_1x2"], 2),
        "brier_difference_model_minus_market": round(results["model"]["brier_score_1x2"] - results["market"]["brier_score_1x2"], 4),
        "log_loss_difference_model_minus_market": round(results["model"]["log_loss_1x2"] - results["market"]["log_loss_1x2"], 4),
        "interpretation": "Differenze positive favoriscono il modello per accuracy; differenze negative favoriscono il modello per Brier score e log loss.",
    }
    return {
        "settled_matches_with_model_and_odds": len(evaluated),
        "minimum_matches_required": MIN_METRIC_MATCHES,
        "model": results["model"],
        "market": results["market"],
        "comparison": comparison,
        "note": "Confronto descrittivo sugli stessi incontri. Brier score e log loss più bassi sono migliori; non dimostra redditività né causalità.",
    }


def calculate_additional_market_metrics(records):
    """Metriche binarie per Over/Under e Gol/No Gol, su partite concluse."""
    import math
    specs = {
        "over_under_1_5": ("over", 1.5, "total"),
        "over_under_2_5": ("over", 2.5, "total"),
        "over_under_3_5": ("over", 3.5, "total"),
        "btts": ("yes", None, "btts"),
    }
    output = {}
    for market_key, (positive_side, line, kind) in specs.items():
        evaluated = []
        for item in records:
            if item.get("outcome") not in ("1", "X", "2"):
                continue
            analysis = (item.get("market_analysis_markets") or {}).get(market_key) or {}
            model_probs = analysis.get("model_probability") or {}
            market_probs = analysis.get("market_implied_probability") or {}
            try:
                model_p = float(model_probs[positive_side]) / 100
                market_p = float(market_probs[positive_side]) / 100
                hg, ag = int(item.get("home_goals")), int(item.get("away_goals"))
            except (TypeError, ValueError, KeyError):
                continue
            if not (0 <= model_p <= 1 and 0 <= market_p <= 1):
                continue
            actual_yes = (hg + ag > line) if kind == "total" else (hg > 0 and ag > 0)
            evaluated.append((model_p, market_p, int(actual_yes)))
        if len(evaluated) < MIN_METRIC_MATCHES:
            output[market_key] = {
                "settled_matches_with_model_and_odds": len(evaluated),
                "minimum_matches_required": MIN_METRIC_MATCHES,
                "model": None, "market": None, "comparison": None,
                "note": f"Servono almeno {MIN_METRIC_MATCHES} partite concluse con quote e probabilità per questo mercato.",
            }
            continue
        metrics = {}
        for name, index in (("model", 0), ("market", 1)):
            probs = [row[index] for row in evaluated]
            actuals = [row[2] for row in evaluated]
            accuracy = sum(int((p >= 0.5) == bool(y)) for p, y in zip(probs, actuals)) / len(probs) * 100
            brier = sum((p - y) ** 2 for p, y in zip(probs, actuals)) / len(probs)
            logloss = sum(-math.log(max(1e-15, p if y else 1 - p)) for p, y in zip(probs, actuals)) / len(probs)
            metrics[name] = {"accuracy": round(accuracy, 2), "brier_score": round(brier, 4), "log_loss": round(logloss, 4)}
        output[market_key] = {
            "settled_matches_with_model_and_odds": len(evaluated),
            "minimum_matches_required": MIN_METRIC_MATCHES,
            "model": metrics["model"], "market": metrics["market"],
            "comparison": {
                "accuracy_difference_percentage_points_model_minus_market": round(metrics["model"]["accuracy"] - metrics["market"]["accuracy"], 2),
                "brier_difference_model_minus_market": round(metrics["model"]["brier_score"] - metrics["market"]["brier_score"], 4),
                "log_loss_difference_model_minus_market": round(metrics["model"]["log_loss"] - metrics["market"]["log_loss"], 4),
            },
            "note": "Brier score e log loss più bassi sono migliori; confronto descrittivo, non prova di redditività.",
        }
    return output


def unresolved_past_matches(records, today=None):
    """Partite con data passata ancora senza esito associato: diagnostica, non esiti inventati."""
    today_value = (today or datetime.now(timezone.utc).date()).isoformat()
    return [
        item for item in records
        if isinstance(item, dict)
        and item.get("outcome") is None
        and isinstance(item.get("date"), str)
        and item.get("date") < today_value
    ]


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
            "data_quality": match.get("data_quality", "non_dichiarata"),
            "expected_home_goals": match.get("expected_home_goals"),
            "expected_away_goals": match.get("expected_away_goals"),
            "sample_matches": match.get("sample_matches", 0),
            "european_context": match.get("european_context") or [],
            "european_fatigue_status": match.get("european_fatigue_status"),
            "suggested_markets": match.get("suggested_markets") or [],
            "value_bets": match.get("value_bets") or [],
            "odds_fetched_at": match.get("odds_fetched_at"),
            "odds_1x2": match.get("odds_1x2"),
            "odds_markets": match.get("odds_markets"),
            "odds_markets_source": match.get("odds_markets_source"),
            "market_analysis_markets": match.get("market_analysis_markets"),
            "odds_source": match.get("odds_source"),
            "market_implied_probability_1x2": match.get("market_implied_probability_1x2"),
            "market_overround_1x2": match.get("market_overround_1x2"),
            "expected_value_1x2": match.get("expected_value_1x2"),
            "odds_snapshot_at": match.get("market_analysis_updated_at"),
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "outcome": None, "home_goals": None, "away_goals": None,
        })
        known_ids.add(match_id)

    # Arricchisce gli archivi futuri creati prima dell'introduzione delle quote.
    # Lo snapshot potrebbe non essere la quota di apertura: la data viene conservata.
    current_by_id = {item.get("id"): item for item in data.get("matches", []) if item.get("id")}
    for item in records:
        current = current_by_id.get(item.get("id"))
        if not current or item.get("outcome") is not None:
            continue
        if not item.get("european_context") and current.get("european_context"):
            item["european_context"] = current.get("european_context")
            item["european_fatigue_status"] = current.get("european_fatigue_status")
        if not item.get("suggested_markets") and current.get("suggested_markets"):
            item["suggested_markets"] = current.get("suggested_markets")
        if not item.get("market_analysis_markets") and current.get("market_analysis_markets"):
            item["odds_markets"] = current.get("odds_markets")
            item["odds_markets_source"] = current.get("odds_markets_source")
            item["market_analysis_markets"] = current.get("market_analysis_markets")
        if item.get("market_implied_probability_1x2"):
            continue
        if current.get("odds_1x2") and current.get("market_implied_probability_1x2"):
            item["odds_1x2"] = current.get("odds_1x2")
            item["odds_source"] = current.get("odds_source")
            item["market_implied_probability_1x2"] = current.get("market_implied_probability_1x2")
            item["market_overround_1x2"] = current.get("market_overround_1x2")
            item["expected_value_1x2"] = current.get("expected_value_1x2")
            item["odds_snapshot_at"] = current.get("market_analysis_updated_at")

    today = datetime.now(timezone.utc).date()
    indexes = {}
    # Recupera la stagione corretta per ogni partita pendente, anche oltre il cambio stagione.
    pending = [
        item for item in records
        if item.get("outcome") is None and item.get("date", "") <= today.isoformat()
    ]
    pending_by_league_season = {}
    for item in pending:
        try:
            season = season_code_for_match(item.get("date", ""))
        except ValueError:
            continue
        pending_by_league_season.setdefault((item.get("league"), season), []).append(item.get("date"))
    code_by_league = {league: code for code, league in LEAGUES.items()}
    for (league, season), dates in pending_by_league_season.items():
        code = code_by_league.get(league)
        if not code:
            continue
        try:
            # Per Austria, Danimarca, Finlandia, Irlanda, Norvegia, Polonia,
            # Romania, Svezia e Svizzera i risultati sono nel CSV cumulativo.
            url = (f"{SOURCE}/new/{EXTRA_SOURCE_CODES.get(code, code)}.csv" if code in EXTRA_FOOTBALL_DATA_LEAGUES
                   else f"{SOURCE}/mmz4281/{season}/{code}.csv")
            rows = read_csv(url)
            indexes.setdefault(league, {}).update(result_index(rows))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO: risultati per {league} ({season}) non disponibili: {error}")

    # Se il CSV principale non ha associato l'esito, tenta il tabellone risultati ESPN gratuito.
    pending_by_league = {}
    for item in pending:
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
        if (not isinstance(hg, int) or not isinstance(ag, int) or
                not (0 <= hg <= 15 and 0 <= ag <= 15) or
                not item.get("home_team") or not item.get("away_team") or
                team_key(item.get("home_team")) == team_key(item.get("away_team"))):
            print(f"AVVISO: risultato scartato per controllo qualità: {item.get('id')}")
            continue
        item["home_goals"], item["away_goals"] = hg, ag
        item["outcome"] = "1" if hg > ag else "X" if hg == ag else "2"
        item["settled_at"] = datetime.now(timezone.utc).isoformat()
        settled += 1

    unresolved = unresolved_past_matches(records, today)
    history["result_matching"] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "unresolved_past_matches": len(unresolved),
        "examples": [
            {"date": item.get("date"), "league": item.get("league"),
             "home_team": item.get("home_team"), "away_team": item.get("away_team")}
            for item in unresolved[:20]
        ],
        "note": "Le partite passate senza esito restano escluse dalle metriche finché il risultato non è associato con certezza.",
    }
    if unresolved:
        print(f"AVVISO: {len(unresolved)} partite con data passata restano senza esito associato; non vengono usate per le metriche.")
    history["records"] = records
    history["updated_at"] = datetime.now(timezone.utc).isoformat()
    history["metrics"] = calculate_metrics(records)
    history["value_bet_metrics"] = calculate_value_bet_metrics(records)
    history["metrics_by_league"] = calculate_metrics_by_league(records)
    history["metrics_by_european_context"] = calculate_metrics_by_european_context(records)
    history["model_vs_market_metrics"] = calculate_model_market_metrics(records)
    history["additional_market_metrics"] = calculate_additional_market_metrics(records)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Storico: {len(records)} partite archiviate; {settled} nuovi risultati associati.")
    print("Metriche 1X2:", json.dumps(history["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
