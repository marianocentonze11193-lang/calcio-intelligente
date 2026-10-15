# Calcio Intelligente

Dashboard statica di pronostici calcistici con aggiornamento automatico tramite GitHub Actions.

## Funzioni implementate
- Calendario e risultati da football-data.co.uk, con calendario ESPN di riserva.
- Solo massime divisioni nazionali supportate dalla fonte storica: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Scottish Premiership, Eredivisie, Primeira Liga, Belgian Pro League, Süper Lig turca, Bundesliga austriaca, Superliga danese, Super League greca, Veikkausliiga finlandese, Premier Division irlandese, Eliteserien norvegese, Ekstraklasa polacca, Liga I rumena, Allsvenskan svedese e Super League svizzera. Il calendario e lo storico devono essere reperibili e abbinabili per ogni partita. Le divisioni inferiori inglesi e scozzesi sono escluse.
- Stime Poisson basate su statistiche casa/trasferta, medie di lega, Elo sequenziale e forma delle ultime cinque gare.
- Stima preliminare per campioni ridotti; NO BET quando mancano osservazioni pertinenti.
- Probabilità 1X2, doppia chance, Over/Under, Goal/No Goal e risultati esatti stimati.
- Commenti Gemini quando il secret `GEMINI_API_KEY` è configurato; l'AI non inventa informazioni non fornite.
- Importazione delle quote 1X2 quando presenti nei CSV gratuiti football-data.co.uk; integrazione opzionale di The Odds API tramite il secret `ODDS_API_KEY`; stima del valore atteso teorico.
- Archivio della prima stima e verifica dei risultati finali, con accuratezza 1X2 e Brier score.
- Filtri per nazione e competizione; partite ordinate per nazione, competizione, data e orario. Il filtro nazione viene popolato automaticamente dalle partite effettivamente caricate.
- Aggiornamento pianificato ogni ora via GitHub Actions.

## Limiti e trasparenza
- Elo e Poisson sono un modello sperimentale; non è ancora dimostrata la sua redditività e la calibrazione va misurata su un campione storico ampio.
- Per alcuni campionati il calendario ESPN può essere disponibile senza dati storici equivalenti: in tal caso la partita resta NO BET.
- Le formazioni ufficiali, gli infortuni e le squalifiche non sono ancora coperti da una fonte automatica gratuita, uniforme e verificata per tutte le leghe. Non vengono inventati: per integrarli in modo affidabile serve un provider con endpoint dedicati e limiti/condizioni compatibili; una semplice notizia o una formazione non confermata non viene trattata come dato certo.
- La copertura quote gratuita varia per partita: vengono usate le quote 1X2 presenti nei CSV football-data.co.uk. Per una copertura alternativa è supportata The Odds API con il secret `ODDS_API_KEY`; senza chiave l'app continua a usare le quote gratuite eventualmente disponibili.
- Il valore atteso è un calcolo teorico dipendente dalla qualità del modello, non una prova di profitto; la soglia EV del 3% genera soltanto candidati da verificare.
- Le fonti gratuite hanno limiti di copertura, frequenza e condizioni d'uso. Il workflow segnala gli errori e può non aggiornare quando una fonte non è disponibile.
- Il sito è statico: il pulsante ricarica i dati pubblicati, non avvia il calcolo remoto.
- Nessun pronostico garantisce risultati o vincite.

## Configurazione opzionale delle quote

Per attivare le quote, crea una chiave secondo le condizioni del fornitore The Odds API e aggiungila in GitHub: **Settings → Secrets and variables → Actions → New repository secret**, nome `ODDS_API_KEY`. Non inserire la chiave nei file del repository e non condividerla in chat. Se non è configurata, il workflow continua senza quote.

## Fonti e codice
- Risultati: https://www.football-data.co.uk/
- Calendario di riserva: API pubblica ESPN.
- Workflow: `.github/workflows/update.yml`
- Modello: `scripts/update_predictions.py`
- Quote e valore atteso opzionali: `scripts/enrich_with_odds.py`
- Commenti AI: `scripts/enrich_with_gemini.py`
- Archivio e metriche: `scripts/archive_predictions.py`
- Test: `tests/test_predictions.py`

Questa applicazione è sperimentale e informativa. Le probabilità non costituiscono garanzia di esito.


## Infortuni, squalifiche e formazioni

Il flusso opzionale `scripts/enrich_with_availability.py` usa API-Football (API-Sports) per cercare segnalazioni di infortuni/squalifiche e, vicino al calcio d'inizio, le formazioni disponibili. Richiede il secret GitHub Actions `API_FOOTBALL_KEY`. Se il secret non è configurato, le probabilità continuano a essere generate e l'app mostra chiaramente che i dati di disponibilità non sono configurati.

- La cache `data/availability_cache.json` riduce le chiamate: calendario e indisponibilità vengono aggiornati circa ogni 6 ore.
- Le formazioni vengono controllate vicino al calcio d'inizio, con al massimo una richiesta di formazione per esecuzione del workflow.
- Il matching usa data, ordine casa/trasferta e alias espliciti; se la partita non si abbina con certezza, i dati non vengono attribuiti.
- La fonte può avere copertura incompleta per campionato. Un elenco vuoto significa solo che non sono state trovate segnalazioni nella risposta, non che tutti i giocatori siano certamente disponibili.
- Le informazioni di disponibilità sono mostrate come contesto e non modificano automaticamente le probabilità del modello.
- Per attivare: repository GitHub → Settings → Secrets and variables → Actions → New repository secret → nome `API_FOOTBALL_KEY`, valore della chiave API-Football. Non inserire mai la chiave nei file del repository.
