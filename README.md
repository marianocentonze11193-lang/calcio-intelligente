# Calcio Intelligente

Dashboard statica di pronostici calcistici con aggiornamento automatico tramite GitHub Actions.

## Funzioni implementate
- Calendari stagionali per 20 campionati, tre coppe UEFA e nove coppe nazionali, usando API-Football quando la chiave è configurata; football-data.co.uk ed ESPN sono fonti di riserva. La sincronizzazione controlla date, squadre e punteggi, conserva la cache quando una fonte fallisce e pubblica lo stato per competizione.
- Il generatore di pronostici riutilizza `data/competition_data.json` per leggere risultati recenti e impegni futuri di coppe UEFA e nazionali; il fallback ESPN viene chiamato solo se la cache manca o supera 36 ore. Questo evita di interrogare ripetutamente tutti gli scoreboard a ogni aggiornamento orario. Il calendario viene comunque controllato per date, squadre, stato e punteggi prima di influenzare il modello.
- Pagina dedicata a [calendari e classifiche](./competitions.html), con filtri per competizione, partite future/concluse, fonte e ultimo aggiornamento. Le classifiche di Premier League, La Liga, Serie A e Champions League sono fornite da API-Football quando disponibili; le altre sono calcolate dai risultati e possono differire in caso di penalizzazioni o regole particolari.
- 20 massime divisioni configurate. Usa i CSV stagionali di football-data.co.uk per 11 competizioni (Inghilterra, Spagna, Germania, Italia, Francia, Scozia, Paesi Bassi, Portogallo, Belgio, Turchia e Grecia) e tenta anche i CSV cumulativi gratuiti `/new/{CODICE}.csv` per Austria, Danimarca, Finlandia, Irlanda, Norvegia, Polonia, Romania, Svezia e Svizzera. Per i CSV cumulativi vengono considerati solo i risultati dell'ultimo anno; ESPN resta una fonte di riserva. La copertura reale varia per lega e stagione e viene riportata nel JSON di aggiornamento. Le divisioni inferiori inglesi e scozzesi sono escluse.
- Stime Poisson basate su statistiche casa/trasferta, medie di lega, Elo sequenziale e forma delle ultime cinque gare.
- Stima preliminare solo quando entrambe le squadre hanno almeno due gare nel corretto contesto casa/trasferta; NO BET quando mancano dati o il campione è insufficiente.
- Probabilità 1X2, doppia chance, Over/Under, Goal/No Goal e risultati esatti stimati.
- Commenti Gemini quando il secret `GEMINI_API_KEY` è configurato; l'AI non inventa informazioni non fornite.
- Quote 1X2 e, quando disponibili nella risposta API-Football, Over/Under 1,5, 2,5 e 3,5, Gol/No Gol e doppia chance. Confronto con le probabilità del modello, stima del valore atteso teorico e metriche storiche separate per Over/Under e Gol/No Gol.
- Archivio immutabile della prima previsione disponibile per partita, con versione descrittiva del modello, orario del calcio d'inizio, timestamp di generazione e probabilità pre-partita. Gli snapshot dello stesso giorno sono esclusi se l'orario manca o il kickoff è già passato, per ridurre il rischio di leakage temporale.
- Audit probabilistico su risultati verificati: accuratezza 1X2, Brier score, log loss e calibrazione per fasce di probabilità. Le metriche complessive vengono pubblicate da almeno 30 partite valutate; i campioni per singolo campionato o fascia possono essere molto più piccoli e instabili. Il confronto modello-mercato usa le stesse partite concluse con quote archiviate.
- Filtri per nazione e competizione; partite ordinate per nazione, competizione, data e orario. Il filtro nazione viene popolato automaticamente dalle partite effettivamente caricate.
- Aggiornamento pianificato ogni ora via GitHub Actions.

## Audit della qualità dei pronostici

L'archivio valuta la prima fotografia conservata per ogni partita, non l'ultima probabilità aggiornata dopo aver conosciuto il risultato. Il controllo del kickoff usa il fuso orario della competizione; se una partita è in programma oggi ma non ha un orario attendibile, lo snapshot viene rimandato. I record storici creati prima del tracciamento della versione restano legacy: non è possibile ricostruire retroattivamente una versione del modello o un timestamp pre-partita che non era stato salvato.

Le metriche da leggere insieme sono:
- **Accuracy 1X2**: quota di esiti corretti scegliendo la probabilità più alta; da sola ignora quanto erano calibrate le probabilità.
- **Brier score e log loss**: valutano le probabilità assegnate ai tre esiti; più bassi è meglio.
- **Calibrazione**: confronta probabilità media prevista e frequenza osservata per fasce e per esito.
- **Modello contro mercato**: confronto sulle stesse partite per cui esistono probabilità e quote archiviate, senza ricostruire quote a posteriori.

Queste metriche sono un audit prospettico delle previsioni effettivamente archiviate, non un backtest storico completo ricostruito da zero. Un backtest senza leakage richiede di rigenerare ogni previsione usando soltanto dati disponibili prima del relativo kickoff e di confrontarla con una baseline sullo stesso periodo. Finché non è stato completato e validato questo passaggio, non si dichiara dimostrato alcun vantaggio del modello, né si attivano automaticamente fattori sperimentali (motivazione, stanchezza da coppe o indisponibilità) come correzioni delle probabilità.

## Backtest cronologico e confronto con baseline

Lo script `scripts/backtest_walk_forward.py` ricostruisce previsioni storiche per le 11 leghe con CSV stagionali diretti, dal luglio 2024 all'ultimo giorno concluso disponibile. Per ogni data usa esclusivamente partite di date precedenti; tutte le gare dello stesso giorno vengono previste prima di aggiungere qualsiasi risultato di quella giornata. Il report `data/backtest_report.json` confronta accuracy, Brier score e log loss del modello con una baseline semplice basata sulle frequenze 1/X/2 osservate fino a quel momento, con smoothing di Laplace.

Il workflow dedicato si può avviare manualmente da GitHub Actions e lo aggiorna settimanalmente. Il report indica copertura ed errori delle fonti; se la fonte manca, la lega non viene spacciata per verificata. Questo backtest ricostruisce il modello attuale su dati storici e non include coppe, indisponibilità o formazioni: è un primo confronto cronologico, non una prova di redditività futura.

## Limiti e trasparenza
- Elo e Poisson sono un modello sperimentale; non è ancora dimostrata la sua redditività e la calibrazione va misurata su un campione storico ampio.
- Per alcuni campionati il calendario ESPN può essere disponibile senza dati storici equivalenti. Il flusso evita richieste CSV alle divisioni non supportate dalla fonte primaria e prova un recupero storico ESPN recente; se la fonte non restituisce risultati verificabili, la partita resta NO BET con una causa esplicita. La disponibilità del fallback può variare e non garantisce copertura completa.
- Le formazioni ufficiali, gli infortuni e le squalifiche non sono ancora coperti da una fonte automatica gratuita, uniforme e verificata per tutte le leghe. Non vengono inventati: per integrarli in modo affidabile serve un provider con endpoint dedicati e limiti/condizioni compatibili; una semplice notizia o una formazione non confermata non viene trattata come dato certo.
- La copertura quote gratuita varia per partita e campionato. Sono supportate le quote 1X2 nei CSV football-data.co.uk, The Odds API se il piano dell’account include calcio e API-Football tramite `API_FOOTBALL_KEY`. Il piano gratuito di The Odds API attualmente pubblicizza NBA e MLB, non il calcio; per evitare dipendenze da un piano a pagamento, il flusso prova API-Football quando la chiave è configurata. API-Football offre un piano gratuito con 100 richieste al giorno, ma la copertura delle quote non è garantita per ogni partita. Il nuovo flusso limita prudenzialmente le richieste quote a 15 al giorno, con cache persistente, perché la stessa chiave è usata anche per calendario, indisponibilità e formazioni.
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
- Quote e valore atteso opzionali: `scripts/enrich_with_odds.py` (The Odds API) e `scripts/enrich_with_api_football_odds.py` (API-Football, cache in `data/odds_cache.json`)
- Commenti AI: `scripts/enrich_with_gemini.py`
- Archivio e metriche: `scripts/archive_predictions.py`
- Test: `tests/test_predictions.py`

Questa applicazione è sperimentale e informativa. Le probabilità non costituiscono garanzia di esito.


## Analisi probabilità modello vs mercato

Lo script `scripts/analyze_market_odds.py` calcola per ogni match con quote 1X2 complete le probabilità implicite del mercato normalizzando gli inversi delle quote, una stima indicativa del margine grezzo, lo scarto in punti percentuali tra modello e mercato e l'EV teorico per ciascun esito (`probabilità modello × quota − 1`). Le quote migliori possono provenire da bookmaker diversi, quindi margine e probabilità depurate sono indicatori comparativi e non una quotazione di un singolo bookmaker. Un EV positivo è una stima teorica, non una garanzia di profitto.

L'archivio salva la fotografia delle probabilità e delle quote. Lo storico calcola quindi, sulle stesse partite concluse con quote disponibili, accuratezza 1X2, Brier score e log loss sia per il modello sia per il mercato. Il confronto viene pubblicato solo dopo almeno 30 partite abbinate; Brier score e log loss più bassi indicano migliori probabilità previsionali. Per i vecchi record senza una quota archiviata al momento del pronostico non è possibile ricostruire in modo affidabile le quote storiche a posteriori; il confronto diventa significativo man mano che si accumulano nuovi risultati.

## Quote calcistiche da API-Football

Il flusso `scripts/enrich_with_api_football_odds.py` riutilizza il secret `API_FOOTBALL_KEY` già previsto per disponibilità, senza esporre la chiave al browser. Cerca le quote pre-partita 1X2 per gli incontri abbinati con certezza tramite l’ID fixture, salva le risposte in `data/odds_cache.json` e non inventa quote mancanti. Per proteggere il piano gratuito limita le nuove richieste quote a 15 al giorno e non ripete la richiesta per la stessa partita nello stesso giorno. Il limite si somma comunque all’uso degli altri endpoint API-Football, quindi la copertura dipende dalla quota residua e dalla disponibilità della competizione.

Le quote migliori tra quelle restituite vengono confrontate con le probabilità del modello per calcolare l’EV teorico. Un EV positivo non prova che esista un vantaggio reale: la calibrazione deve essere verificata sui risultati storici.

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
- Il pannello di stato mostra la copertura delle quote 1X2 e dei mercati aggiuntivi. Se The Odds API non è configurata, impostare il secret ODDS_API_KEY in GitHub → Settings → Secrets and variables → Actions; non inserire mai la chiave nel codice.
- Le statistiche storiche (accuratezza 1X2 e Brier score) sono mostrate solo dopo l'associazione a risultati finali verificati e almeno 30 valutazioni valide. Un campione piccolo non dimostra un vantaggio sulle quote o una redditività positiva.

### Aggiornamento e controllo

GitHub Actions tenta l'aggiornamento ogni ora. In caso di errore di una fonte, controllare la scheda Actions del repository. Il completamento del workflow prova che il processo è terminato senza errori tecnici, non che ogni campionato abbia dati completi.


## Mercati quote aggiuntivi

Quando The Odds API o API-Football restituiscono i mercati per una partita, il flusso salva le migliori quote disponibili per Over/Under 1,5, 2,5 e 3,5, Gol/No Gol e doppia chance. The Odds API richiede h2h, totals, btts e double_chance quando supportati dal piano e dalla competizione; se alcuni mercati vengono rifiutati, il sistema riprova con un set più piccolo. La copertura dipende da campionato, partita, bookmaker e piano API: se il provider non restituisce un mercato, viene lasciato non disponibile senza valori inventati. Le probabilità modello per questi mercati derivano dalla matrice di punteggi Poisson già usata per il pronostico; le quote aggiuntive non modificano automaticamente il modello.

Per Over/Under e Gol/No Gol si calcolano probabilità implicite normalizzate, scarto modello-mercato ed EV teorico. Per doppia chance le selezioni si sovrappongono: viene mostrata la probabilità grezza 1/quota, non una probabilità depurata dal margine. Lo storico valuta Over/Under e Gol/No Gol separatamente, dopo almeno 30 partite concluse con quote e probabilità archiviate. Le metriche sono descrittive e non provano redditività.
