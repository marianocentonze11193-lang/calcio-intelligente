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
            "motivazioni_e_classifica": match.get("motivation_context", {}),
            "impegni_ravvicinati": match.get("recent_competition_context", []),
        })

    def request_batch(batch):
        prompt = (
            "Sei il commentatore calcistico di Calcio Intelligente. Scrivi in italiano naturale, "
            "caldo e concreto, come una persona competente che aiuta a leggere la partita. "
            "Per ogni incontro scrivi 3-4 frasi, circa 45-70 parole: apri con l'idea principale, "
            "riassumi il pronostico più interessante tra quelli già indicati dal modello e spiega "
            "in parole semplici perché può avere senso. Dai priorità a consigli pratici e leggibili, "
            "non a elenchi di percentuali o statistiche. Usa al massimo un dato numerico se davvero utile. "
            "Considera la classifica e le motivazioni solo se il campo fornito contiene indizi verificabili; "
            "presentali come segnali e non come certezze. Se non ci sono mercati consigliati o i dati sono "
            "deboli, dillo chiaramente e suggerisci prudenza / nessuna giocata, senza inventare alternative. "
            "Tieni conto degli impegni ravvicinati verificati quando presenti. Non inventare notizie, "
            "infortuni, formazioni, obiettivi già raggiunti o retrocessioni matematiche. Non promettere vincite "
            "e non cambiare probabilità o mercati: il tuo compito è spiegare, non creare nuove selezioni. "
            "Evita formule robotiche e ripetizioni; varia il linguaggio tra le partite. "
            "Rispondi SOLO con JSON valido nel formato "
            '{"analyses":[{"id":"ID esatto","analysis":"commento breve e umano"}]}. '
            "Includi un commento per ogni ID. Dati:\n"
            + json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.45,
                "maxOutputTokens": 2200,
                "responseMimeType": "application/json",
            },
        }
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        candidates = payload.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini non ha restituito candidati")
        response_text = "".join(
            part.get("text", "")
            for part in candidates[0].get("content", {}).get("parts", [])
            if isinstance(part, dict)
        )
        decoded = extract_json(response_text)
        analyses = decoded.get("analyses", [])
        if not isinstance(analyses, list):
            raise ValueError("Campo analyses mancante o non valido")
        allowed_ids = {item.get("id") for item in batch}
        result = {}
        for item in analyses:
            if not isinstance(item, dict):
                continue
            match_id, analysis = item.get("id"), item.get("analysis")
            if match_id in allowed_ids and isinstance(analysis, str):
                clean = " ".join(analysis.split())
                if clean:
                    result[match_id] = clean[:1200]
        return result

    # Risposte brevi per gruppi piccoli: riduce il rischio di JSON troncato.
    by_id = {}
    batch_size = 4
    for offset in range(0, len(compact_matches), batch_size):
        batch = compact_matches[offset:offset + batch_size]
        try:
            by_id.update(request_batch(batch))
            print(f"Gemini: completato gruppo {offset + 1}-{offset + len(batch)}.")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as error:
            print(f"AVVISO: batch Gemini {offset + 1}-{offset + len(batch)} non riuscito ({error}); continuo con il gruppo successivo.")

    if not by_id:
        print("AVVISO: Gemini non ha restituito analisi utilizzabili; mantengo le analisi statistiche.")
        return
    updated = 0
    for match in data.get("matches", []):
        if match.get("id") in by_id:
            match["analysis"] = by_id[match["id"]]
            match["analysis_provider"] = "Gemini"
            updated += 1
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(f"Analisi Gemini aggiunte a {updated} partite. Probabilità e mercati statistici non sono stati modificati.")


if __name__ == "__main__":
    main()
