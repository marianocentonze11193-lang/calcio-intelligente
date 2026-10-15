#!/usr/bin/env python3
"""Controlli d'integrità sui JSON pubblicati prima del commit automatico."""
import json
import math
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS_FILE = ROOT / "data" / "predictions.json"
HISTORY_FILE = ROOT / "data" / "history.json"


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate():
    predictions = load_json(PREDICTIONS_FILE)
    history = load_json(HISTORY_FILE)
    errors = []

    matches = predictions.get("matches")
    if not isinstance(matches, list):
        errors.append("predictions.json: 'matches' deve essere una lista.")
        matches = []
    records = history.get("records")
    if not isinstance(records, list):
        errors.append("history.json: 'records' deve essere una lista.")
        records = []

    seen_matches = set()
    for index, match in enumerate(matches):
        label = f"predictions.json matches[{index}]"
        if not isinstance(match, dict):
            errors.append(f"{label}: record non valido.")
            continue
        match_id = match.get("id")
        if not match_id:
            errors.append(f"{label}: id mancante.")
        elif match_id in seen_matches:
            errors.append(f"{label}: id duplicato {match_id!r}.")
        else:
            seen_matches.add(match_id)
        try:
            date.fromisoformat(str(match.get("date", "")))
        except ValueError:
            errors.append(f"{label}: data non valida.")
        home, away = str(match.get("home_team", "")).strip(), str(match.get("away_team", "")).strip()
        if not home or not away or home.casefold() == away.casefold():
            errors.append(f"{label}: nomi delle squadre mancanti o identici.")

        probabilities = match.get("probabilities")
        if probabilities is None:
            continue
        if not isinstance(probabilities, dict):
            errors.append(f"{label}: probabilities deve essere un oggetto.")
            continue
        core = [probabilities.get(key) for key in ("home_win", "draw", "away_win")]
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100 for value in core):
            errors.append(f"{label}: probabilità 1X2 non numeriche o fuori intervallo.")
        elif not 98.5 <= sum(core) <= 101.5:
            errors.append(f"{label}: probabilità 1X2 non sommano circa 100%.")
        for key, value in probabilities.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                errors.append(f"{label}: probabilità {key!r} non valida.")
                break
        for key in ("expected_home_goals", "expected_away_goals"):
            value = match.get(key)
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                errors.append(f"{label}: {key} non valido.")

    seen_records = set()
    for index, record in enumerate(records):
        label = f"history.json records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label}: record non valido.")
            continue
        record_id = record.get("id")
        if record_id and record_id in seen_records:
            errors.append(f"{label}: id duplicato {record_id!r}.")
        elif record_id:
            seen_records.add(record_id)
        outcome = record.get("outcome")
        hg, ag = record.get("home_goals"), record.get("away_goals")
        if outcome is not None:
            if outcome not in ("1", "X", "2"):
                errors.append(f"{label}: outcome deve essere 1, X, 2 o null.")
            if not all(isinstance(v, int) and 0 <= v <= 15 for v in (hg, ag)):
                errors.append(f"{label}: esito valorizzato senza punteggi finali validi.")
            else:
                expected = "1" if hg > ag else "X" if hg == ag else "2"
                if outcome != expected:
                    errors.append(f"{label}: outcome incoerente con il punteggio.")
        elif hg is not None or ag is not None:
            errors.append(f"{label}: punteggio presente ma outcome mancante.")

    if not isinstance(predictions.get("coverage"), dict):
        errors.append("predictions.json: diagnostica coverage mancante.")
    if not isinstance(history.get("metrics"), dict):
        errors.append("history.json: metriche mancanti.")

    if errors:
        raise SystemExit("CONTROLLO DATI FALLITO:\n- " + "\n- ".join(errors))
    print(
        "Controllo dati superato: "
        f"{len(matches)} partite, {len(records)} record archivio, "
        f"{sum(1 for row in records if isinstance(row, dict) and row.get('outcome') is not None)} esiti verificati."
    )


if __name__ == "__main__":
    validate()
