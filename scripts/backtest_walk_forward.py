#!/usr/bin/env python3
"""Walk-forward backtest: ogni previsione usa esclusivamente risultati di date precedenti."""
import json
import math
import urllib.error
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import update_predictions as model
import xg_provider_understat as xg_provider

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
        market_probabilities = None
        for names in (("AvgH", "AvgD", "AvgA"), ("B365H", "B365D", "B365A"),
                      ("PSH", "PSD", "PSA")):
            odds = [model.number(model.row_value(row, name)) for name in names]
            if all(value is not None and value > 1 for value in odds):
                inverse = [1.0 / value for value in odds]
                total = sum(inverse)
                if total > 0:
                    market_probabilities = {
                        "home_win": inverse[0] / total * 100,
                        "draw": inverse[1] / total * 100,
                        "away_win": inverse[2] / total * 100,
                    }
                break
        results.append((parsed_date, home_key, away_key, int(hg), int(ag), market_probabilities))
    return results


def history_for(results):
    history = defaultdict(lambda: {
        "played": 0, "home_games": 0, "away_games": 0,
        "home_scored": 0, "home_conceded": 0, "away_scored": 0, "away_conceded": 0,
    })
    completed = []
    for row in results:
        _, home, away, hg, ag = row[:5]
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
    predicted_index = max(range(3), key=lambda i: values[i])
    return {
        "correct": int(predicted_index == actual_index),
        "brier": sum((values[i] - actual[i]) ** 2 for i in range(3)),
        "log_loss": -math.log(max(1e-15, values[actual_index])),
        "predicted_confidence": values[predicted_index],
    }


def blend_probabilities(model_probabilities, market_probabilities, model_weight=0.5):
    """Miscela sperimentale modello/mercato; non viene usata nelle previsioni pubblicate."""
    if not isinstance(model_probabilities, dict) or not isinstance(market_probabilities, dict):
        return None
    keys = ("home_win", "draw", "away_win")
    try:
        model_values = [float(model_probabilities[key]) for key in keys]
        market_values = [float(market_probabilities[key]) for key in keys]
    except (KeyError, TypeError, ValueError):
        return None
    if any(value < 0 or value > 100 for value in model_values + market_values):
        return None
    if abs(sum(model_values) - 100) > 1.5 or abs(sum(market_values) - 100) > 1.5:
        return None
    blended = [model_weight * m + (1 - model_weight) * p for m, p in zip(model_values, market_values)]
    total = sum(blended)
    if total <= 0:
        return None
    return {key: value * 100 / total for key, value in zip(keys, blended)}


def metric_summary(rows):
    if not rows:
        return {"matches": 0, "accuracy_1x2": None, "brier_score_1x2": None, "log_loss_1x2": None,
                "top_class_calibration": []}
    n = len(rows)
    bins = [(0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]
    calibration = []
    for lower, upper in bins:
        selected = [r for r in rows if lower <= r.get("predicted_confidence", 0) < upper]
        if selected:
            calibration.append({
                "confidence_range": f"{int(lower * 100)}-{min(100, int(upper * 100))}%",
                "matches": len(selected),
                "mean_predicted_confidence_pct": round(sum(r["predicted_confidence"] for r in selected) * 100 / len(selected), 2),
                "observed_accuracy_pct": round(sum(r["correct"] for r in selected) * 100 / len(selected), 2),
            })
    return {
        "matches": n,
        "accuracy_1x2": round(sum(r["correct"] for r in rows) * 100 / n, 2),
        "brier_score_1x2": round(sum(r["brier"] for r in rows) / n, 4),
        "log_loss_1x2": round(sum(r["log_loss"] for r in rows) / n, 4),
        "top_class_calibration": calibration,
    }



def outcome_calibration_summary(rows):
    """One-vs-rest Brier/log-loss and reliability bins separately for 1, X and 2."""
    result = {}
    bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0000001)]
    keys = (("1", "home_win"), ("X", "draw"), ("2", "away_win"))
    scored_by_outcome = {label: [] for label, _ in keys}
    for row in rows:
        probabilities = row.get("model_probabilities")
        if not isinstance(probabilities, dict):
            continue
        try:
            values = [float(probabilities[key]) for _, key in keys]
        except (KeyError, TypeError, ValueError):
            continue
        if any(not math.isfinite(value) or not 0 <= value <= 100 for value in values):
            continue
        if abs(sum(values) - 100) > 1.5:
            continue
        outcome = row.get("outcome")
        if outcome not in scored_by_outcome:
            continue
        for (label, _), value in zip(keys, values):
            scored_by_outcome[label].append((value / 100.0, 1.0 if outcome == label else 0.0))

    for label, _ in keys:
        scored = scored_by_outcome[label]
        calibration = []
        for lower, upper in bins:
            selected = [(p, a) for p, a in scored if lower <= p < upper]
            if selected:
                calibration.append({
                    "probability_range": f"{int(lower * 100)}-{min(100, int(upper * 100))}%",
                    "matches": len(selected),
                    "mean_predicted_pct": round(sum(p for p, _ in selected) * 100 / len(selected), 2),
                    "observed_frequency_pct": round(sum(a for _, a in selected) * 100 / len(selected), 2),
                })
        n = len(scored)
        result[label] = {
            "matches": n,
            "brier_score": round(sum((p - a) ** 2 for p, a in scored) / n, 5) if n else None,
            "log_loss": round(-sum(math.log(max(1e-15, min(1 - 1e-15, p))) if a else math.log(max(1e-15, 1 - p)) for p, a in scored) / n, 5) if n else None,
            "reliability_bins": calibration,
            "note": "Brier/log-loss binari one-vs-rest; punteggi più bassi sono migliori.",
        }
    return result

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



def load_league_xg(league_name, today):
    """Carica xG storici per le leghe coperte, senza fabbricare valori mancanti."""
    if league_name not in xg_provider.LEAGUES:
        return {}
    lookup = {}
    for season in range(START_DATE.year, today.year + 1):
        try:
            rows = xg_provider.fetch_league_xg(league_name, season)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError) as error:
            print(f"AVVISO Understat {league_name}/{season}: {error}")
            rows = []
        print(f"Understat {league_name}/{season}: {len(rows)} osservazioni xG valide.")
        for row in rows:
            try:
                match_date = date.fromisoformat(row["date"])
                home = model.team_key(row["home_team"])
                away = model.team_key(row["away_team"])
                home_xg, away_xg = float(row["home_xg"]), float(row["away_xg"])
            except (KeyError, TypeError, ValueError):
                continue
            if match_date < START_DATE or match_date >= today or not home or not away or home == away:
                continue
            if not (math.isfinite(home_xg) and math.isfinite(away_xg)
                    and 0 <= home_xg <= 10 and 0 <= away_xg <= 10):
                continue
            lookup[(match_date.isoformat(), home, away)] = (home_xg, away_xg)
    return lookup


def history_for_xg(prior_results, xg_lookup):
    """Statistiche xG di casa/trasferta calcolate solo da partite precedenti abbinate."""
    history = defaultdict(lambda: {
        "played": 0, "home_games": 0, "away_games": 0,
        "home_scored": 0.0, "home_conceded": 0.0,
        "away_scored": 0.0, "away_conceded": 0.0,
    })
    matched = []
    for row in prior_results:
        match_date, home, away = row[:3]
        xg = xg_lookup.get((match_date.isoformat(), home, away))
        if not xg:
            continue
        home_xg, away_xg = xg
        hs, aws = history[home], history[away]
        hs["played"] += 1
        hs["home_games"] += 1
        hs["home_scored"] += home_xg
        hs["home_conceded"] += away_xg
        aws["played"] += 1
        aws["away_games"] += 1
        aws["away_scored"] += away_xg
        aws["away_conceded"] += home_xg
        matched.append((home_xg, away_xg))
    if not matched:
        return history, None, None, 0
    home_avg = sum(item[0] for item in matched) / len(matched)
    away_avg = sum(item[1] for item in matched) / len(matched)
    return history, home_avg, away_avg, len(matched)

def walk_forward_league(league_name, results, xg_lookup=None):
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
            xg_history, xg_home_avg, xg_away_avg, xg_prior_matches = history_for_xg(prior_results, xg_lookup or {})
            home_avg = sum(row[2] for row in completed) / len(completed)
            away_avg = sum(row[3] for row in completed) / len(completed)
            if home_avg > 0 and away_avg > 0:
                elo = model.calculate_elo(completed)
                recent = model.calculate_recent_form(completed)
                motivation = model.build_motivation_table(completed)
                outcomes = [("1" if row[3] > row[4] else "X" if row[3] == row[4] else "2") for row in prior_results]
                baseline_counts = {label: outcomes.count(label) + 1 for label in ("1", "X", "2")}
                baseline_total = sum(baseline_counts.values())
                baseline_probs = {label: baseline_counts[label] / baseline_total for label in baseline_counts}
                for fixture in day_fixtures:
                    _, home, away, hg, ag = fixture[:5]
                    market_probabilities = fixture[5] if len(fixture) > 5 else None
                    outcome = "1" if hg > ag else "X" if hg == ag else "2"
                    variants = {}
                    model_probabilities = None
                    variant_args = {
                        "poisson_only": (None, False),
                        "poisson_elo": (elo, False),
                        "poisson_form": (None, True),
                        "model": (elo, False),
                        "poisson_elo_form": (elo, True),
                    }
                    for variant, (variant_elo, use_form) in variant_args.items():
                        forecast = model.make_forecast(
                            home, away, league_name, match_day, "", history, home_avg, away_avg,
                            variant_elo, recent if use_form else {}, [], motivation,
                            apply_form_adjustment=use_form, apply_competition_adjustment=False,
                        )
                        probs = forecast.get("probabilities") or {}
                        if all(key in probs for key in ("home_win", "draw", "away_win")):
                            variants[variant] = score_probabilities(probs, outcome)
                            if variant == "model":
                                model_probabilities = probs
                    xg_model_probabilities = None
                    if xg_prior_matches >= MIN_PRIOR_MATCHES and xg_home_avg and xg_away_avg:
                        xg_forecast = model.make_forecast(
                            home, away, league_name, match_day, "", xg_history,
                            xg_home_avg, xg_away_avg, None, {}, [], {},
                            apply_form_adjustment=False, apply_competition_adjustment=False,
                        )
                        xg_probs = xg_forecast.get("probabilities") or {}
                        if all(key in xg_probs for key in ("home_win", "draw", "away_win")):
                            xg_model_probabilities = xg_probs
                            variants["xg_model"] = score_probabilities(xg_probs, outcome)
                    if "model" not in variants:
                        continue
                    baseline = {key: baseline_probs[label] * 100 for key, label in zip(("home_win", "draw", "away_win"), ("1", "X", "2"))}
                    scored_market = score_probabilities(market_probabilities, outcome) if market_probabilities else None
                    blended = blend_probabilities(model_probabilities, market_probabilities) if market_probabilities else None
                    if blended:
                        variants["market_blend_50_50"] = score_probabilities(blended, outcome)
                    predictions.append({
                        "date": match_day.isoformat(), "outcome": outcome,
                        "model_probabilities": model_probabilities,
                        "xg_model_probabilities": xg_model_probabilities,
                        "variants": variants, "baseline": score_probabilities(baseline, outcome),
                        "market_baseline": scored_market,
                    })
        prior_results.extend(day_fixtures)
        cursor = end
    return predictions


def main():
    today = datetime.now(timezone.utc).date()
    all_by_league = {}
    all_model = []
    all_baseline = []
    all_market = []
    all_variants = defaultdict(list)
    all_evaluated = []
    all_xg_evaluated = []
    errors = []
    for code in sorted(model.FOOTBALL_DATA_LEAGUES):
        league = model.LEAGUES[code]
        try:
            results = load_league_results(code, today)
            if not results:
                errors.append(f"{league}: nessun risultato storico valido")
                continue
            xg_lookup = load_league_xg(league, today)
            xg_matched_source_matches = sum(
                1 for item in results
                if (item[0].isoformat(), item[1], item[2]) in xg_lookup
            )
            evaluated = walk_forward_league(league, results, xg_lookup)
            all_evaluated.extend(evaluated)
            xg_evaluated = [item for item in evaluated if item.get("xg_model_probabilities")]
            all_xg_evaluated.extend(xg_evaluated)
            all_by_league[league] = {
                "source_matches": len(results),
                "xg_source_matches_matched": xg_matched_source_matches,
                "xg_validation": {
                    "matched_predictions": len(xg_evaluated),
                    "model_on_same_matches": metric_summary([item["variants"]["model"] for item in xg_evaluated]),
                    "xg_only_candidate": metric_summary([item["variants"]["xg_model"] for item in xg_evaluated]),
                    "market_on_same_matches": metric_summary([item["market_baseline"] for item in xg_evaluated if item.get("market_baseline")]),
                },
                "variants": {name: metric_summary([item["variants"][name] for item in evaluated if name in item["variants"]])
                             for name in ("poisson_only", "poisson_elo", "poisson_form", "model", "poisson_elo_form", "market_blend_50_50", "xg_model")},
                "prior_frequency_baseline": metric_summary([item["baseline"] for item in evaluated]),
                "market_baseline": metric_summary([item["market_baseline"] for item in evaluated if item.get("market_baseline")]),
                "market_coverage_matches": sum(1 for item in evaluated if item.get("market_baseline")),
                "outcome_calibration": outcome_calibration_summary(evaluated),
                "period_start": min((item["date"] for item in evaluated), default=None),
                "period_end": max((item["date"] for item in evaluated), default=None),
            }
            all_model.extend(item["variants"]["model"] for item in evaluated if "model" in item["variants"])
            all_baseline.extend(item["baseline"] for item in evaluated)
            all_market.extend(item["market_baseline"] for item in evaluated if item.get("market_baseline"))
            for name in ("poisson_only", "poisson_elo", "poisson_form", "poisson_elo_form", "market_blend_50_50"):
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
            "market_baseline": metric_summary(all_market),
            "market_coverage_matches": len(all_market),
            "outcome_calibration": outcome_calibration_summary(all_evaluated),
            "xg_validation": {
                "matched_predictions": len(all_xg_evaluated),
                "model_on_same_matches": metric_summary([item["variants"]["model"] for item in all_xg_evaluated]),
                "xg_only_candidate": metric_summary([item["variants"]["xg_model"] for item in all_xg_evaluated]),
                "market_on_same_matches": metric_summary([item["market_baseline"] for item in all_xg_evaluated if item.get("market_baseline")]),
            },
            "comparison_note": "Confronto su identiche partite; per Brier score e log loss un valore più basso è migliore. Il mercato è confrontato solo sulle partite con quote storiche complete.",
        },
        "leagues": all_by_league,
        "leagues_with_results": len(all_by_league),
        "errors": errors,
        "limitations": [
            "Copertura limitata alle 11 leghe con CSV stagionali diretti di football-data.co.uk.",
            "Le gare dello stesso giorno vengono tutte previste prima di aggiungere i risultati di quel giorno, per evitare leakage intra-giornaliero.",
            "Le coppe, gli infortuni, le squalifiche e le formazioni ufficiali non sono inclusi in questo backtest.",
            "Il risultato è un test storico ricostruito con il modello corrente e non prova da solo prestazioni future o redditività.",
            "Il benchmark di mercato usa AvgH/AvgD/AvgA, con fallback B365H/D/A e PSH/PSD/PSA, solo quando le quote storiche sono complete; le probabilità sono normalizzate per rimuovere il margine.",
            "La miscela 50/50 modello-mercato è sperimentale e resta esclusa dai pronostici pubblicati finché non supera una validazione fuori campione.",
            "La calibrazione top-class confronta la probabilità dell'esito più probabile con la frequenza di correttezza nella stessa fascia.",
            "La variante xG è sperimentale: usa solo xG storici abbinati per data e squadre, disponibili prima della partita; i confronti sono riportati sulle stesse partite con copertura xG.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report walk-forward scritto in {OUTPUT}; leghe: {len(all_by_league)}; errori: {len(errors)}")
    print("XG_VALIDATION_SUMMARY=" + json.dumps(report["overall"]["xg_validation"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
