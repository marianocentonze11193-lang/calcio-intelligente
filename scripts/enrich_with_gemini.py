#!/usr/bin/env python3
"""Arricchisce le stime con commenti Gemini senza modificare probabilità o mercati."""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

DATA_FILE = Path("data/predictions.json")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
MAX_MATCHES = 30


def extract_json(text):
    """Estrae un oggetto JSON anche se il modello aggiunge delimitatori Markdown."""
    text = (text or "").strip()
    text = re.sub(r"^\`\`\`(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\`\`\`$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Risposta Gemini senza oggetto JSON")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("La risposta Gemini non è un oggetto JSON")
    return value


def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("GEMINI_API_KEY non configurata: salto l'analisi AI; le stime statistiche restano disponibili.")
        return

    if not DATA_FILE.exists():
        raise SystemExit("File data/predictions.json non trovato.")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    matches = [
        match for match in data.get("matches", [])
        if match.get("status") in ("Pronostico valutabile", "Stima preliminare") and match.get("probabilities")
    ][:MAX_MATCHES]
    if not matches:
        print("Nessuna partita valutabile da inviare a Gemini.")
        return

    compact_matches = []
    for match in matches:
        compact_matches.append({
            "id": match.get("id", ""),
            "campionato": match.get("league", ""),
            "data": match.get("date", ""),
            "casa": match.get("home_team", ""),
            "trasferta": match.get("away_team", ""),
            "gol_attesi_modello": {
                "casa": match.get("expected_home_goals"),
                "trasferta": match.get("expected_away_goals"),
            },
            "probabilita_percentuali_modello": match.get("probabilities", {}),
            "campione_casa": match.get("home_matches_sample"),
            "campione_trasferta": match.get("away_matches_sample"),
            "forma_recente_casa": match.get("home_recent_form"),
            "forma_recente_trasferta": match.get("away_recent_form"),
            "elo_casa": match.get("elo_home"),
            "elo_trasferta": match.get("elo_away"),
            "fiducia_modello": match.get("confidence"),
            "stato_stima": match.get("status"),
            "disponibilita_verificata": {
                "stato": (match.get("availability_data") or {}).get("status"),
                "nota": (match.get("availability_data") or {}).get("note"),
                "indisponibili_segnalati": (match.get("availability_data") or {}).get("injuries", []),
                "formazioni_pubblicate": bool(
                    (match.get("availability_data") or {}).get("lineups")
                    and (
                        (match.get("availability_data") or {}).get("lineups", {}).get("home_starters")
                        or (match.get("availability_data") or {}).get("lineups", {}).get("away_starters")
                    )
                ),
            },
            "quote_1x2_disponibili": match.get("odds_1x2"),
            "mercati_selezionati_da_regole": match.get("suggested_markets", []),
        })

    prompt = (
        "Sei l'analista editoriale di Calcio Intelligente e scrivi in italiano naturale, "
        "con il tono di una persona competente che accompagna il lettore nella partita, "
        "senza gergo superfluo né entusiasmo artificiale. Per ogni incontro produci 5-6 frasi "
        "ben collegate, circa 110-160 parole: l'analisi deve essere più utile di una semplice "
        "lettura dei numeri, ma non deve diventare prolissa. Apri descrivendo in modo concreto "
        "quanto la gara appare equilibrata o sbilanciata. Interpreta le probabilità 1/X/2 e i "
        "gol attesi citando i valori più importanti in modo comprensibile; se utile, spiega "
        "che cosa suggeriscono sul possibile andamento, senza descrivere scenari come certi. "
        "Confronta la forma recente delle due squadre solo quando è presente nel JSON e "
        "riporta con prudenza gol fatti/subiti e punti medi; usa i valori Elo come indicatore "
        "secondario, non come classifica ufficiale. Indica il numero di gare nel campione casa/"
        "trasferta e spiega chiaramente se è piccolo, perché rende la stima meno stabile. "
        "Se ci sono quote, presentale solo come riferimento del mercato: non chiamarle "
        "convenienti senza un confronto quantitativo giustificato. Per indisponibilità e "
        "formazioni cita solo le informazioni esplicitamente fornite, specificando che la fonte "
        "può essere incompleta; se la partita è fuori copertura API o non ci sono segnalazioni, "
        "non lasciare intendere che tutti i giocatori siano disponibili. Non inventare notizie, "
        "precedenti, classifiche, motivazioni, tattiche, giocatori, quote o statistiche; se un "
        "dato manca, dichiaralo solo quando è utile e non riempire il vuoto con supposizioni. "
        "Spiega un limite concreto della previsione e ricorda, senza ripetere sempre la stessa "
        "formula, che il modello statistico è sperimentale e non ancora validato su un campione "
        "sufficiente. Non consigliare puntate, non promettere risultati e non modificare le "
        "probabilità o i mercati. Rendi ogni commento specifico ai dati di quella partita, "
        "evitando introduzioni e conclusioni identiche tra gli incontri. Restituisci SOLO JSON "
        "valido nel formato "
        '{"analyses":[{"id":"ID esatto","analysis":"analisi in italiano"}]}. '
        "Non inventare ID e non omettere le cautele. Dati:\\n"
        + json.dumps(compact_matches, ensure_ascii=False, separators=(",", ":"))
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 7000,
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = "".join(
            part.get("text", "")
            for part in payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            if isinstance(part, dict)
        )
        decoded = extract_json(text)
        analyses = decoded.get("analyses", [])
        if not isinstance(analyses, list):
            raise ValueError("Campo analyses mancante o non valido")
        allowed_ids = {match.get("id") for match in matches}
        by_id = {}
        for item in analyses:
            if not isinstance(item, dict):
                continue
            match_id = item.get("id")
            analysis = item.get("analysis")
            if match_id in allowed_ids and isinstance(analysis, str):
                clean = " ".join(analysis.split())
                if clean:
                    by_id[match_id] = clean[:1200]
        if not by_id:
            raise ValueError("Gemini non ha restituito commenti utilizzabili")

        updated = 0
        for match in data.get("matches", []):
            if match.get("id") in by_id:
                match["analysis"] = by_id[match["id"]]
                match["analysis_provider"] = "Gemini"
                updated += 1
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Analisi Gemini aggiunte a {updated} partite. Probabilità e mercati statistici non sono stati modificati.")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as error:
        # Un problema del servizio AI non deve bloccare la pubblicazione delle stime statistiche.
        print(f"AVVISO: Gemini non disponibile o risposta non valida ({error}). Mantengo le analisi statistiche originali.")


if __name__ == "__main__":
    main()
