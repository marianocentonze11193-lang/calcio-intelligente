# Calcio Intelligente

Sito pubblico di analisi calcistiche con aggiornamento automatico tramite GitHub Actions.

## Funzioni attuali
- Calendario e risultati da football-data.co.uk, con calendario ESPN di riserva.
- Campionati nazionali selezionati e calendario UEFA.
- Stime sperimentali Poisson: 1X2, doppia chance, Over/Under, Goal/No Goal e risultati esatti più probabili.
- Stato NO BET quando manca lo storico minimo o i dati non sono comparabili.
- Commenti assistiti da Gemini se il secret GitHub Actions `GEMINI_API_KEY` è configurato.
- Aggiornamento automatico pianificato ogni ora, oltre all'avvio manuale dal workflow.

## Limiti da conoscere
- La soglia tecnica attuale è di almeno 3 partite casalinghe per la squadra di casa e 3 trasferte per quella ospite. È soltanto un filtro minimo, non una prova di affidabilità.
- Il modello Poisson non è ancora validato con un backtest fuori campione.
- Non sono importate quote bookmaker, quindi non viene calcolato il valore atteso delle scommesse.
- Gemini commenta esclusivamente i dati forniti dal modello: non verifica automaticamente infortuni, formazioni, notizie o quote e non modifica le probabilità.
- Il sito è statico: il pulsante aggiorna i dati pubblicati, non avvia un calcolo sul server.
- Nessun pronostico garantisce risultati o vincite.

## Fonti e aggiornamento
- Risultati: https://www.football-data.co.uk/
- Calendario alternativo: API pubblica ESPN.
- Workflow: `.github/workflows/update.yml`
- Script principale: `scripts/update_predictions.py`
- Commenti AI: `scripts/enrich_with_gemini.py`
- Test automatici: `tests/test_predictions.py`

## Prossime tappe di sviluppo
1. Archiviare ogni pronostico prima del calcio d'inizio.
2. Collegare i risultati finali alle previsioni archiviate.
3. Pubblicare metriche di verifica (accuratezza, Brier score e calibrazione) con campione esplicito.
4. Valutare una fonte autorizzata di quote prima di calcolare eventuale valore atteso.
5. Ampliare le leghe solo quando la copertura dati è verificata.

Questa applicazione è sperimentale e informativa, non costituisce consulenza finanziaria o garanzia di esito.
