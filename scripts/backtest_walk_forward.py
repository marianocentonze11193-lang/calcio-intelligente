#!/usr/bin/env python3
"""Walk-forward backtest: ogni previsione usa esclusivamente risultati di date precedenti."""
import json
import math
import urllib.error
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import update_predictions as model

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "backtest_report.json"
START_DATE = date(2024, 7, 1)
MIN_PRIOR_MATCHES = 60


def rows_to_results(rows, code, start_date, end_date):
    results = []
    for row in rows:
        home = str(model.row_value(row, "HomeTeam", "Home Team", "home_team", "home") or "").strip()
        away = str(model.row_value(row, "AwayTeam", "Away Team", "away_team", "away") or "").strip()
        match_date = model.parse_date(model.row_value(row, "Date", "date", "match_date"))
        hg = model.number(model.row_value(row, "FTHG", "HG", "fthg", "home_goals"))
        ag = model.number(model.row_value(row, "FTAG", "AG", "ftag", "away_goals"))
        if not home or not away or not match_date or hg is None or ag is None:
            continue
        try:
            parsed_date = match_date if isinstance(match_date, date) else date.fromisoformat(str(match_date))
        except (ValueError, TypeError):
            continue
        home_key, away_key = model.team_key(home), model.team_key(away)
        if not start_date <= parsed_date <= end_date or not home_key or not away_key or home_key == away_key:
            continue
        if not (0 <= hg <= 15 and 0 <= ag <= 15 and float(hg).is_integer() and float(ag).is_integer()):
            continue
        results.append((parsed_date, home_key, away_key, int(hg), int(ag)))
    return results


def history_for(results):
    history = defaultdict(lambda: {
        "played": 0, "home_games": 0, "away_games": 0,
        "home_scored": 0, "home_conceded": 0, "away_scored": 0, "away_conceded": 0,
    })
    completed = []
    for _, home, away, hg, ag in results:
        hs, aws = history[home], history[away]
        hs["played"] += 1
        hs["home_games"] += 1
        hs["home_scored"] += hg
        hs["home_conceded"] += ag
        aws["played"] += 1
        aws["away_games"] += 1
        aws["away_scored"] += ag
        aws["away_conceded"] += hg
        completed.append((home, away, hg, ag))
    return history, completed


def score_probabilities(probabilities, outcome):
    labels = ("1", "X", "2")
    values = [float(probabilities[key]) / 100 for key in ("home_win", "draw", "away_win")]
    actual_index = labels.index(outcome)
    actual = [1.0 if i == actual_index else 0.0 for i in range(3)]
    return {
        "correct": int(max(range(3), key=lambda i: values[i]) == actual_index),
        "brier": sum((values[i] - actual[i]) ** 2 for i in range(3)),
        "log_loss": -math.log(max(1e-15, values[actual_index])),
    }


def metric_summary(rows):
    if not rows:
        return {"matches": 0, "accuracy_1x2": None, "brier_score_1x2": None, "log_loss_1x2": None}
    n = len(rows)
    return {
        "matches": n,
        "accuracy_1x2": round(sum(r["correct"] for r in rows) * 100 / n, 2),
        "brier_score_1x2": round(sum(r["brier"] for r in rows) / n, 4),
        "log_loss_1x2": round(sum(r["log_loss"] for r in rows) / n, 4),
    }


def load_league_results(code, today):
    if code not in model.FOOTBALL_DATA_LEAGUES:
        return []
    rows = []
    season_codes = []
    for start_year in range(2024, today.year + 1):
        season_codes.append(f"{start_year % 100:02d}{(start_year + 1) % 100:02d}")
    for season in season_codes:
        try:
            rows.extend(model.fetch_csv(f"{model.SOURCE}/mmz4281/{season}/{code}.csv"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            print(f"AVVISO backtest {code}/{season}: {error}")
    return rows_to_results(rows, code, START_DATE, today - timedelta(days=1))


def walk_forward_league(league_name, results):
    results.sort(key=lambda row: row[0])
    predictions = []
    prior_results = []
    cursor = 0
    while cursor < len(results):
        match_day = results[cursor][0]
        end = cursor
        while end < len(results) and results[end][0] == match_day:
            end += 1
        day_fixtures = results[cursor:end]
        # Tutte le gare della stessa data sono previste prima di aggiungere qualunque risultato del giorno.
        if len(prior_results) >= MIN_PRIOR_MATCHES:
            history, completed = history_for(prior_results)
            home_avg = sum(row[2] for row in completed) / len(completed)
            away_avg = sum(row[3] for row in completed) / len(completed)
            if home_avg > 0 and away_avg > 0:
                elo = model.calculate_elo(completed)
                recent = model.calculate_recent_form(completed)
                motivation = model.build_motivation_table(completed)
                outcomes = [("1" if hg > ag else "X" if hg == ag else "2") for _, _, _, hg, ag in prior_results]
                baseline_counts = {label: outcomes.count(label) + 1 for label in ("1", "X", "2")}
                baseline_total = sum(baseline_counts.values())
                baseline_probs = {label: baseline_counts[label] / baseline_total for label in baseline_counts}
                for _, home, away, hg, ag in day_fixtures:
                    outcome = "1" if hg > ag else "X" if hg == ag else "2"
                    variants = {}
                    variant_args = {
                        "poisson_only": (None, {}),
                        "poisson_elo": (elo, {}),
                        "poisson_form": (None, recent),
                        "model": (elo, {}),
                        "poisson_elo_form": (elo, recent),
                    }
                    for variant, (variant_elo, variant_form) in variant_args.items():
                        forecast = model.make_forecast(
                            home, away, league_name, match_day, "", history, home_avg, away_avg,
                            variant_elo, variant_form, [], motivation,
                        )
                        probs = forecast.get("probabilities") or {}
                        if all(key in probs for key in ("home_win", "draw", "away_win")):
                            variants[variant] = score_probabilities(probs, outcome)
                    if "model" not in variants:
                        continue
                    baseline = {key: baseline_probs[label] * 100 for key, label in zip(("home_win", "draw", "away_win"), ("1", "X", "2"))}
                    predictions.append({
                        "date": match_day.isoformat(), "outcome": outcome,
                        "variants": variants, "baseline": score_probabilities(baseline, outcome),
                    })
        prior_results.extend(day_fixtures)
        cursor = end
    return predictions


def main():
    today = datetime.now(timezone.utc).date()
    all_by_league = {}
    all_model = []
    all_baseline = []
    all_variants = defaultdict(list)
    errors = []
    for code in sorted(model.FOOTBALL_DATA_LEAGUES):
        league = model.LEAGUES[code]
        try:
            results = load_league_results(code, today)
            if not results:
                errors.append(f"{league}: nessun risultato storico valido")
                continue
            evaluated = walk_forward_league(league, results)
            all_by_league[league] = {
                "source_matches": len(results),
                "variants": {name: metric_summary([item["variants"][name] for item in evaluated if name in item["variants"]])
                             for name in ("poisson_only", "poisson_elo", "poisson_form", "model", "poisson_elo_form")},
                "prior_frequency_baseline": metric_summary([item["baseline"] for item in evaluated]),
                "period_start": min((item["date"] for item in evaluated), default=None),
                "period_end": max((item["date"] for item in evaluated), default=None),
            }
            all_model.extend(item["variants"]["model"] for item in evaluated if "model" in item["variants"])
            all_baseline.extend(item["baseline"] for item in evaluated)
            for name in ("poisson_only", "poisson_elo", "poisson_form"):
                all_variants[name].extend(item["variants"][name] for item in evaluated if name in item["variants"])
            print(f"{league}: {len(results)} risultati sorgente, {len(evaluated)} previsioni walk-forward.")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
            errors.append(f"{league}: {error}")
            print(f"ERRORE backtest {league}: {error}")

# Le metriche aggregate vengono ricalcolate dalle metriche partita, non dalla media delle medie di lega.
    for league, report in all_by_league.items():
        if report["variants"]["model"]["matches"]:
            report["note"] = "Validazione cronologica: ogni previsione usa solo gare con data strettamente precedente; coppe e indisponibilità non sono incluse."
    report = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "method": "walk-forward cronologico per data, con baseline di frequenza 1/X/2 calcolata solo sui risultati precedenti e smoothing di Laplace",
        "period_start_requested": START_DATE.isoformat(),
        "period_end_requested": (today - timedelta(days=1)).isoformat(),
        "overall": {
            "walk_forward": metric_summary(all_model),
            "ablations": {name: metric_summary(rows) for name, rows in all_variants.items()},
            "prior_frequency_baseline": metric_summary(all_baseline),
            "comparison_note": "Confronto su identiche partite; per Brier score e log loss un valore più basso è migliore.",
        },
        "leagues": all_by_league,
        "leagues_with_results": len(all_by_league),
        "errors": errors,
        "limitations": [
            "Copertura limitata alle 11 leghe con CSV stagionali diretti di football-data.co.uk.",
            "Le gare dello stesso giorno vengono tutte previste prima di aggiungere i risultati di quel giorno, per evitare leakage intra-giornaliero.",
            "Le coppe, gli infortuni, le squalifiche e le formazioni ufficiali non sono inclusi in questo backtest.",
            "Il risultato è un test storico ricostruito con il modello corrente e non prova da solo prestazioni future o redditività.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report walk-forward scritto in {OUTPUT}; leghe: {len(all_by_league)}; errori: {len(errors)}")


if __name__ == "__main__":
    main()
