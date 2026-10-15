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
        "chiaro e concreto, come una persona competente che spiega la partita a un lettore. "
        "Per ogni incontro scrivi 4-5 frasi complete (circa 90-140 parole), con tono umano "
        "e senza formule ripetitive. Apri con una lettura sintetica dell'equilibrio tra le "
        "squadre; interpreta le probabilità 1/X/2 e i gol attesi citando i numeri pertinenti; "
        "commenta la forma recente solo se i dati sono presenti, spiegando gol fatti/subiti "
        "e punti medi senza trasformarli in certezze; indica chiaramente se il campione casa/"
        "trasferta è piccolo o manca del tutto e come questo limita la stima. Se sono presenti "
        "quote, descrivile come dato di mercato e non come prova di valore; non dichiarare che "
        "una quota sia conveniente senza calcolare e giustificare il confronto. Se i dati "
        "infortuni/formazioni sono presenti, riferisci soltanto ciò che la fonte segnala e "
        "precisa che l'elenco può essere incompleto; se la data è fuori copertura, dillo "
        "esplicitamente e non interpretare l'assenza di segnalazioni come disponibilità. "
        "Non inventare notizie, precedenti, motivazioni, forma, quote o giocatori; non "
        "dedurre informazioni mancanti. Non consigliare puntate, non promettere risultati e "
        "non modificare probabilità o mercati. Ricorda che il modello Poisson è sperimentale "
        "e non ancora validato con risultati sufficienti. Evita di ripetere sempre la stessa "
        "frase generica: rendi ogni analisi specifica ai numeri della partita. Restituisci "
        "SOLO JSON valido nel formato "
        '{"analyses":[{"id":"ID esatto","analysis":"analisi in italiano"}]}. '
        "Non inventare ID e non omettere le cautele. Dati:\\n"
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
