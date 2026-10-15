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
            "mercati_selezionati_da_regole": match.get("suggested_markets", []),
        })

    prompt = (
        "Sei l'assistente editoriale di Calcio Intelligente. Scrivi un commento in italiano "
        "breve e prudente per ogni partita usando ESCLUSIVAMENTE i dati JSON forniti. "
        "Non cercare di inventare infortuni, formazioni, forma recente, motivazioni, quote, "
        "meteo o notizie: non sono presenti. Non modificare né ricalcolare le probabilità, "
        "non consigliare puntate e non promettere risultati. Evidenzia l'incertezza e i limiti "
        "del campione; interpreta le probabilità come stime sperimentali di un modello Poisson "
        "non ancora validato. Se le probabilità sono vicine, dillo. Per ciascun ID restituisci "
        "un commento massimo di 2 frasi. Rispondi SOLO con JSON valido nel formato "
        '{"analyses":[{"id":"ID esatto","analysis":"commento in italiano"}]}. '
        "Non inventare ID e non omettere il carattere prudente. Dati:\n"
        + json.dumps(compact_matches, ensure_ascii=False, separators=(",", ":"))
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 5000,
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
                    by_id[match_id] = clean[:700]
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
