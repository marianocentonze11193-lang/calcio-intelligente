#!/usr/bin/env python3
"""Calcola probabilità implicite senza margine e valore atteso dalle quote 1X2."""
import json
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = Path("data/predictions.json")


def market_analysis(match):
    odds = match.get("odds_1x2")
    probabilities = match.get("probabilities")
    if not isinstance(odds, dict) or not isinstance(probabilities, dict):
        return False
    keys = ("home", "draw", "away")
    labels = ("home_win", "draw", "away_win")
    try:
        prices = {key: float(odds[key]) for key in keys}
        model = {key: float(probabilities[label]) / 100 for key, label in zip(keys, labels)}
    except (KeyError, TypeError, ValueError):
        return False
    if any(price <= 1 for price in prices.values()):
        return False
    if any(prob < 0 or prob > 1 for prob in model.values()) or abs(sum(model.values()) - 1) > 0.015:
        return False

    raw = {key: 1 / prices[key] for key in keys}
    overround = sum(raw.values())
    if overround <= 0:
        return False
    implied = {key: round(raw[key] / overround * 100, 2) for key in keys}
    # EV uses the model probability and the best available decimal price.
    ev = {key: round(model[key] * prices[key] - 1, 4) for key in keys}
    delta = {key: round(model[key] * 100 - implied[key], 2) for key in keys}
    match["market_implied_probability_1x2"] = implied
    match["market_overround_1x2"] = round((overround - 1) * 100, 2)
    match["model_vs_market_delta_1x2"] = delta
    match["expected_value_1x2"] = ev
    match["market_analysis_updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return True


def market_analysis_additional(match):
    """Confronta probabilità e quote per mercati binari e doppia chance."""
    odds_markets = match.get("odds_markets")
    probabilities = match.get("probabilities")
    if not isinstance(odds_markets, dict) or not isinstance(probabilities, dict):
        return False
    specs = {
        "over_under_1_5": ("over_1_5", "under_1_5", "over", "under"),
        "over_under_2_5": ("over_2_5", "under_2_5", "over", "under"),
        "over_under_3_5": ("over_3_5", "under_3_5", "over", "under"),
        "btts": ("btts_yes", "btts_no", "yes", "no"),
    }
    results = {}
    for market_key, (model_a_key, model_b_key, outcome_a, outcome_b) in specs.items():
        prices = odds_markets.get(market_key)
        try:
            price_a, price_b = float(prices[outcome_a]), float(prices[outcome_b])
            model_a, model_b = float(probabilities[model_a_key]) / 100, float(probabilities[model_b_key]) / 100
        except (TypeError, ValueError, KeyError):
            continue
        if price_a <= 1 or price_b <= 1 or not (0 <= model_a <= 1 and 0 <= model_b <= 1):
            continue
        raw_a, raw_b = 1 / price_a, 1 / price_b
        total = raw_a + raw_b
        market_a, market_b = raw_a / total, raw_b / total
        results[market_key] = {
            "odds": {outcome_a: price_a, outcome_b: price_b},
            "model_probability": {outcome_a: round(model_a * 100, 2), outcome_b: round(model_b * 100, 2)},
            "market_implied_probability": {outcome_a: round(market_a * 100, 2), outcome_b: round(market_b * 100, 2)},
            "delta_percentage_points": {outcome_a: round((model_a - market_a) * 100, 2), outcome_b: round((model_b - market_b) * 100, 2)},
            "expected_value": {outcome_a: round(model_a * price_a - 1, 4), outcome_b: round(model_b * price_b - 1, 4)},
            "overround": round((total - 1) * 100, 2),
        }
    dc = odds_markets.get("double_chance")
    if isinstance(dc, dict):
        dc_map = {"1x": "double_chance_1x", "x2": "double_chance_x2", "12": "double_chance_12"}
        dc_results = {}
        for selection, model_key in dc_map.items():
            try:
                price = float(dc[selection])
                model_probability = float(probabilities[model_key])
            except (TypeError, ValueError, KeyError):
                continue
            if price <= 1 or not 0 <= model_probability <= 100:
                continue
            raw_market = 100 / price
            dc_results[selection] = {
                "odds": price, "model_probability": round(model_probability, 2),
                "market_implied_probability": round(raw_market, 2),
                "delta_percentage_points": round(model_probability - raw_market, 2),
                "expected_value": round((model_probability / 100) * price - 1, 4),
            }
        if dc_results:
            results["double_chance"] = dc_results
    match["market_analysis_markets"] = results
    return bool(results)


def main():
    if not DATA_FILE.exists():
        raise SystemExit("File data/predictions.json non trovato.")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    analyzed = 0
    additional_analyzed = 0
    for match in data.get("matches", []):
        if not isinstance(match, dict):
            continue
        if market_analysis(match):
            analyzed += 1
        if market_analysis_additional(match):
            additional_analyzed += 1
    data["market_analysis"] = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "matches_analyzed": analyzed,
        "additional_markets_analyzed": additional_analyzed,
        "supported_additional_markets": ["Over/Under 1,5", "Over/Under 2,5", "Over/Under 3,5", "Gol/No Gol", "Doppia chance"],
        "method": "Probabilità implicite normalizzate per mercati binari; per doppia chance l'implied è 1/quota perché gli esiti si sovrappongono; EV teorico = probabilità modello × quota decimale − 1",
    }
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Analisi mercato completata: {analyzed} partite con quote 1X2; {additional_analyzed} con mercati aggiuntivi analizzati.")


if __name__ == "__main__":
    main()
