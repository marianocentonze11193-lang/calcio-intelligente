# Calcio Intelligente

Dashboard statica di pronostici calcistici con aggiornamento automatico tramite GitHub Actions.

## Funzioni implementate
- Calendario e risultati da football-data.co.uk, con calendario ESPN di riserva.
- Solo massime divisioni nazionali supportate dalla fonte storica: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Scottish Premiership, Eredivisie, Primeira Liga, Belgian Pro League e Süper Lig turca. Le divisioni inferiori inglesi e scozzesi sono escluse.
- Stime Poisson basate su statistiche casa/trasferta, medie di lega e correzione Elo sequenziale.
- Stima preliminare per campioni ridotti; NO BET quando mancano osservazioni pertinenti.
- Probabilità 1X2, doppia chance, Over/Under, Goal/No Goal e risultati esatti stimati.
- Commenti Gemini quando il secret `GEMINI_API_KEY` è configurato; l'AI non inventa informazioni non fornite.
- Archivio della prima stima e verifica dei risultati finali, con accuratezza 1X2 e Brier score.
- Filtri per nazione e competizione; partite ordinate per nazione, competizione, data e orario.
- Aggiornamento pianificato ogni ora via GitHub Actions.

## Limiti e trasparenza
- Elo e Poisson sono un modello sperimentale; non è ancora dimostrata la sua redditività e la calibrazione va misurata su un campione storico ampio.
- Per alcuni campionati il calendario ESPN può essere disponibile senza dati storici equivalenti: in tal caso la partita resta NO BET.
- Le formazioni ufficiali, gli infortuni e le squalifiche non sono ancora coperti da una fonte automatica sufficientemente uniforme e verificata per tutte le leghe. Non vengono inventati.
- Le quote bookmaker e il valore atteso non sono disponibili finché non viene configurata una fonte di quote autorizzata e una chiave API. Una probabilità alta non equivale a una value bet.
- Le fonti gratuite hanno limiti di copertura, frequenza e condizioni d'uso. Il workflow segnala gli errori e può non aggiornare quando una fonte non è disponibile.
- Il sito è statico: il pulsante ricarica i dati pubblicati, non avvia il calcolo remoto.
- Nessun pronostico garantisce risultati o vincite.

## Fonti e codice
- Risultati: https://www.football-data.co.uk/
- Calendario di riserva: API pubblica ESPN.
- Workflow: `.github/workflows/update.yml`
- Modello: `scripts/update_predictions.py`
- Commenti AI: `scripts/enrich_with_gemini.py`
- Archivio e metriche: `scripts/archive_predictions.py`
- Test: `tests/test_predictions.py`

Questa applicazione è sperimentale e informativa. Le probabilità non costituiscono garanzia di esito.
