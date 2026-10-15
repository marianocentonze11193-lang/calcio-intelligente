# Calcio Intelligente

Dashboard statica di pronostici calcistici con aggiornamento automatico tramite GitHub Actions.

## Funzioni implementate
- Calendario e risultati da football-data.co.uk, con calendario ESPN di riserva.
- 20 massime divisioni configurate. Usa i CSV stagionali di football-data.co.uk per 11 competizioni (Inghilterra, Spagna, Germania, Italia, Francia, Scozia, Paesi Bassi, Portogallo, Belgio, Turchia e Grecia) e tenta anche i CSV cumulativi gratuiti `/new/{CODICE}.csv` per Austria, Danimarca, Finlandia, Irlanda, Norvegia, Polonia, Romania, Svezia e Svizzera. Per i CSV cumulativi vengono considerati solo i risultati dell'ultimo anno; ESPN resta una fonte di riserva. La copertura reale varia per lega e stagione e viene riportata nel JSON di aggiornamento. Le divisioni inferiori inglesi e scozzesi sono escluse.
- Stime Poisson basate su statistiche casa/trasferta, medie di lega, Elo sequenziale e forma delle ultime cinque gare.
- Stima preliminare solo quando entrambe le squadre hanno almeno due gare nel corretto contesto casa/trasferta; NO BET quando mancano dati o il campione è insufficiente.
- Probabilità 1X2, doppia chance, Over/Under, Goal/No Goal e risultati esatti stimati.
- Commenti Gemini quando il secret `GEMINI_API_KEY` è configurato; l'AI non inventa informazioni non fornite.
- Importazione delle quote 1X2 quando presenti nei CSV gratuiti football-data.co.uk; integrazione opzionale di The Odds API tramite il secret `ODDS_API_KEY`; stima del valore atteso teorico.
- Archivio della prima stima e verifica dei risultati finali, con controlli su data, squadre, punteggi e coerenza delle probabilità. Accuratezza 1X2 e Brier score vengono pubblicati solo dopo almeno 30 partite valutate; anche le metriche per campionato richiedono almeno 30 esiti verificati.
- Filtri per nazione e competizione; partite ordinate per nazione, competizione, data e orario. Il filtro nazione viene popolato automaticamente dalle partite effettivamente caricate.
- Aggiornamento pianificato ogni ora via GitHub Actions.

## Limiti e trasparenza
- Elo e Poisson sono un modello sperimentale; non è ancora dimostrata la sua redditività e la calibrazione va misurata su un campione storico ampio.
- Per alcuni campionati il calendario ESPN può essere disponibile senza dati storici equivalenti. Il flusso evita richieste CSV alle divisioni non supportate dalla fonte primaria e prova un recupero storico ESPN recente; se la fonte non restituisce risultati verificabili, la partita resta NO BET con una causa esplicita. La disponibilità del fallback può variare e non garantisce copertura completa.
- Le formazioni ufficiali, gli infortuni e le squalifiche non sono ancora coperti da una fonte automatica gratuita, uniforme e verificata per tutte le leghe. Non vengono inventati: per integrarli in modo affidabile serve un provider con endpoint dedicati e limiti/condizioni compatibili; una semplice notizia o una formazione non confermata non viene trattata come dato certo.
- La copertura quote gratuita varia per partita: vengono usate le quote 1X2 presenti nei CSV football-data.co.uk. Per una copertura alternativa è supportata The Odds API con il secret `ODDS_API_KEY`; senza chiave l'app continua a usare le quote gratuite eventualmente disponibili.
- Il valore atteso è un calcolo teorico dipendente dalla qualità del modello, non una prova di profitto; la soglia EV teorica del 5% genera candidati solo con almeno 8 gare pertinenti per entrambe le squadre; non è una prova di vantaggio reale.
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


## Obiettivo e limiti

Il progetto usa un modello statistico sperimentale (Poisson, prior di lega, Elo e forma recente). Le probabilità sono stime, non certezze e non costituiscono una garanzia di vincita o redditività. Le etichette di fiducia descrivono la quantità di dati, non una probabilità di successo verificata.

### Funzioni gratuite e integrazioni opzionali

- Il sito statico e gli aggiornamenti pianificati sono pubblicati tramite GitHub Pages e GitHub Actions.
- I calendari e i risultati provengono da fonti pubbliche gratuite quando disponibili; le coperture possono variare per competizione e stagione.
- Gemini, quote bookmaker e dati su infortuni/formazioni sono integrazioni opzionali con chiavi personali e quote/limiti del rispettivo fornitore. Non sono necessarie per visualizzare le stime statistiche di base e non si deve presumere che ogni endpoint o piano resti gratuito per sempre.
- Quando mancano dati, il sistema deve mostrare NO BET e spiegare il motivo, senza inventare probabilità, quote, infortuni o formazioni.
- Le statistiche storiche (accuratezza 1X2 e Brier score) sono mostrate solo dopo l'associazione a risultati finali verificati e almeno 30 valutazioni valide. Un campione piccolo non dimostra un vantaggio sulle quote o una redditività positiva.

### Aggiornamento e controllo

GitHub Actions tenta l'aggiornamento ogni ora. In caso di errore di una fonte, controllare la scheda Actions del repository. Il completamento del workflow prova che il processo è terminato senza errori tecnici, non che ogni campionato abbia dati completi.
