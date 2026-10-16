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


def main():
    if not DATA_FILE.exists():
        raise SystemExit("File data/predictions.json non trovato.")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    analyzed = 0
    for match in data.get("matches", []):
        if isinstance(match, dict) and market_analysis(match):
            analyzed += 1
    data["market_analysis"] = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "matches_analyzed": analyzed,
        "method": "Probabilità implicite normalizzate rimuovendo il margine 1X2; EV teorico = probabilità modello × quota decimale − 1",
    }
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(f"Analisi mercato completata: {analyzed} partite con quote 1X2 complete.")


if __name__ == "__main__":
    main()
