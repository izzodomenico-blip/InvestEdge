# InvestEdge

InvestEdge e una web app locale per analisi investimenti su azioni, ETF, cripto e bond/ETF obbligazionari.

La fase attuale include backend FastAPI, database SQLite, frontend React/Vite/TypeScript/Tailwind, analisi tecnica avanzata, scoring spiegabile, portafoglio simulato, paper trading, backtest, confronto multi-strategia, pianificatore di allocazione capitale, integrazione dati reali opzionale con cache e modulo news/sentiment. Non include collegamenti reali a broker, ordini reali, machine learning, scraping non autorizzato o trading automatico.

## Avvio rapido (one-click)

Su Windows, doppio click su `Avvia-InvestEdge.bat` nella cartella del progetto. Lo script `scripts/launcher.ps1`:

- crea il virtualenv e installa le dipendenze se mancanti o cambiate (hash di `requirements.txt`/`package-lock.json`);
- builda il frontend se `frontend/dist` e assente o piu vecchio di `src`;
- inizializza il database con il seed se vuoto;
- sceglie la prima porta libera tra 8001 e 8010;
- avvia un singolo processo uvicorn che serve sia l'API sia il frontend buildato;
- apre il browser e scrive un log in `data/launcher.log`.

Un lock file `data/.investedge.lock` evita avvii doppi. Flag utili: `-ForceSeed`, `-ForceRebuild`, `-ForceReinstall`, `-NoBrowser`.

In questa modalita il backend serve il frontend statico quando `INVESTEDGE_SERVE_FRONTEND=1`; la modalita di sviluppo classica (uvicorn + `npm run dev` separati) resta invariata.

## Struttura

```text
backend/
  app/
    api/
    data_providers/
    models/
    services/
    main.py
    config.py
    database.py
frontend/
  src/
data/
docs/
scripts/
tests/
```

## Seed database

Il database SQLite puo essere inizializzato con dati deterministici locali, senza API reali:

```powershell
backend\.venv\Scripts\python.exe scripts\seed_database.py --reset
```

Lo script:

- crea le tabelle se non esistono
- rimuove i dati seed precedenti con `--reset`
- inserisce 25 asset tra azioni USA, ETF, cripto, bond ed ETF obbligazionari
- genera 2 anni di storico prezzi giornaliero
- calcola indicatori tecnici avanzati e segnali STRONG_BUY/BUY/HOLD/REDUCE/SELL
- con `--reset` inizializza un portafoglio demo da 100000 con ordini simulati su AAPL, MSFT, NVDA, BTC, ETH, SPY e QQQ

## Analisi tecnica

Il motore in `backend/app/services/technical_analysis.py` usa solo pandas e numpy. Gli indicatori disponibili includono:

- medie SMA 10/20/50/100/200 ed EMA 12/26/50/200
- momentum: RSI 14, MACD, histogram, Stochastic, CCI 20, ROC 12
- volatilita: Bollinger Bands, ATR 14, volatilita annualizzata 30 giorni, max drawdown
- trend: ADX 14, +DI, -DI, Supertrend, Ichimoku
- volume: OBV, volume SMA 20, volume ratio
- supporti/resistenze tramite pivot locali su high/low

Lo scoring e spiegabile e combina:

- trend_score, peso 30%
- momentum_score, peso 25%
- volatility_score, peso 15%
- volume_score, peso 10%
- support_resistance_score, peso 10%
- risk_penalty, peso 10%

Ogni segnale salva score, confidence, risk_level, motivazioni, sotto-score e indicatori usati.

Lo score tecnico resta separato da quello news. Quando sono presenti news recenti, `final_score` puo includere una variazione leggera pari al massimo a `NEWS_SENTIMENT_WEIGHT` punti in positivo o negativo. Se non ci sono news recenti, `news_score = 0` e `final_score = technical_score`.

## Paper trading e portafoglio

Il paper trading e completamente simulato: ogni BUY o SELL aggiorna solo SQLite e non invia ordini a broker reali.

Il motore in `backend/app/services/portfolio_engine.py` gestisce:

- inizializzazione portafoglio con cash iniziale
- BUY simulato con controllo cash, commissioni, prezzo medio e ordine salvato
- SELL simulato con controllo quantita, commissioni e P/L realizzato
- aggiornamento prezzo corrente dall'ultimo close locale
- P/L realizzato e non realizzato
- pesi delle posizioni, allocation per asset class e valuta
- snapshot dell'andamento del portafoglio

## Conferme per le azioni distruttive

L'interfaccia separa sempre la scelta dalla conferma quando un'azione rimuove o sostituisce dati importanti:

- un asset senza dipendenze puo essere rimosso direttamente; se il backend risponde `409`, la UI elenca i dati collegati e richiede il ticker esatto prima del purge protetto da backup;
- la cancellazione di un backtest richiede il nome e l'id esatti del run;
- il reset del portafoglio dichiara che elimina posizioni, ordini simulati e snapshot storici prima di reimpostare la liquidita;
- allocation e import mostrano un riepilogo della sostituzione e richiedono un secondo click esplicito.

Queste conferme non sostituiscono i controlli backend, che restano l'ultima barriera di sicurezza.

Il motore in `backend/app/services/risk_engine.py` valuta concentrazione e rischio:

- singolo asset oltre soglia
- asset class oltre soglia
- cripto oltre soglia
- troppa o troppo poca liquidita
- concentrazione sui primi 3 asset
- peso eccessivo su asset con segnale SELL/REDUCE

Il segnale tecnico e la lettura dell'asset isolato. La raccomandazione finale considera anche il portafoglio: un asset con segnale BUY puo diventare HOLD o BLOCK_BUY_TOO_CONCENTRATED se pesa gia troppo.

## Backtest Engine

Il motore in `backend/app/services/backtest_engine.py` valida strategie su dati locali SQLite. Non usa broker, API reali, news reali o machine learning.

Le strategie disponibili sono:

- `SCORE_THRESHOLD`: compra asset con score rolling sopra la soglia BUY e vende/riduce sotto la soglia SELL.
- `BUY_AND_HOLD`: compra all'inizio del periodo e mantiene fino alla fine.
- `TOP_N_SCORE`: a ogni ribilanciamento mantiene i migliori N asset per score rolling.

Il backtest calcola gli indicatori in modalita rolling usando solo i dati disponibili fino alla data simulata. Questo riduce il look-ahead bias: i segnali di una data passata non usano prezzi futuri.

Metriche prodotte:

- total return, CAGR, max drawdown, Sharpe ratio
- win rate, profit factor, numero trade, valore finale
- benchmark return e alpha vs benchmark
- equity curve, drawdown curve, trade list e posizioni finali

Sono supportati stop loss, take profit, commissioni, cash residuo, peso massimo per asset e frequenza di ribilanciamento `DAILY`, `WEEKLY` o `MONTHLY`.

Attenzione: il backtest e una simulazione su dati storici generati localmente. Non garantisce rendimenti futuri e puo favorire overfitting se si ottimizzano troppe soglie sullo stesso periodo.

## Confronto multi-strategia

L'endpoint `POST /backtests/compare` esegue 2 o 3 strategie sullo stesso periodo, universo e benchmark, caricando i dati di mercato una sola volta e senza persistere i singoli run. Restituisce per ogni strategia il riepilogo metriche e la equity curve, piu un ranking per rendimento totale e l'indicazione della strategia migliore. Nel frontend la pagina Backtest ha un toggle Singolo/Confronto con tabella metriche affiancate ed equity curve sovrapposte.

## Validazione walk-forward (robustezza)

L'endpoint `POST /backtests/walk-forward` divide il periodo in N fold consecutivi e indipendenti, eseguendo la strategia su ciascun sottoperiodo separatamente. Restituisce metriche per fold, statistiche aggregate (rendimento medio/mediano, dispersione, periodi positivi, fold che battono il benchmark) e un verdetto di consistenza: `ROBUSTA`, `INCERTA` o `FRAGILE`.

Serve a smascherare l'overfitting: una strategia il cui rendimento sull'intero periodo dipende da poche finestre fortunate risulta FRAGILE, anche se il backtest singolo sembra ottimo. Nel frontend la pagina Backtest ha il terzo mode "Robustezza" con tabella per fold e badge del verdetto. Resta una simulazione su dati storici: non garantisce risultati futuri.

## Import posizioni reali da Google Sheets

L'endpoint `POST /import/google-sheets/apply` (e `/preview`) importa le posizioni reali da un Google Sheet **pubblicato in CSV** (File → Condividi → Pubblica sul web → CSV), senza OAuth nè librerie Google: legge l'URL CSV via HTTP. Intestazioni minime: `symbol`, `quantity`, `average_price` (accettati alias italiani: simbolo, quantità, prezzo_medio); opzionali `name`, `asset_type`, `currency`. Il parser gestisce formati europei e americani (`1.234,56`, `1,234.56`, `€ 383,47`).

L'import **sostituisce** le posizioni del portafoglio simulato con quelle del foglio (operazione locale, non tocca il broker). Prima dell'apply la UI mostra il numero di righe valide e non valide e richiede una conferma esplicita. Configura `GOOGLE_SHEETS_CSV_URL` in `backend/.env` oppure incolla il link nella pagina **Importa posizioni**. È il modo per far conoscere all'app il tuo portafoglio reale (es. da Trade Republic tracciato su un foglio).

## Backup / Archivio

Copia di sicurezza del database SQLite con l'API nativa `Connection.backup` (consistente anche a DB in uso). Backup **automatico a ogni avvio** in `data/backups/` (gitignored), rotazione delle ultime 10 copie. Endpoint: `POST /backups/create`, `GET /backups`. Bottone "Backup ora" ed elenco copie nel Data Center.

## Reports / Export

Esportazione in CSV (apribile con Excel/Google Sheets) di portafoglio, operazioni e report fiscale. Endpoint: `GET /reports/summary` (panoramica), `GET /reports/portfolio.csv`, `GET /reports/orders.csv`, `GET /reports/tax.csv` (download con `Content-Disposition`). Pagina frontend "Reports".

## Centro fiscale

L'endpoint `GET /tax/report` calcola plusvalenze e minusvalenze realizzate dagli ordini simulati con **lot matching FIFO**: ogni vendita viene abbinata agli acquisti più vecchi per determinare il costo. Restituisce eventi realizzati, riepilogo per anno fiscale (plus/minus, imposta dovuta), lotti aperti con plus/minus latenti e il riporto perdite (zainetto fiscale). Aliquote: 26% standard, 12,5% titoli di Stato/ETF governativi; compensazione perdite per categoria con riporto agli anni successivi. Stima indicativa, non sostituisce un commercialista. Pagina frontend "Centro fiscale".

## Analisi scenari (stress test)

L'endpoint `POST /scenarios/run` applica shock di prezzo al portafoglio attuale e stima la perdita. Scenari preset (crollo di mercato, sell-off tech, inverno cripto, rialzo tassi, shock inflazione, correzione moderata) o `CUSTOM` con shock per classe/asset. Restituisce valore sotto stress, perdita assoluta/percentuale, livello di rischio, impatto per asset e per classe, e suggerimenti di mitigazione. Sola lettura, non modifica il portafoglio. Pagina frontend "Scenari".

## Pianificatore allocazione capitale

L'endpoint `POST /portfolio/allocation/plan` suggerisce pesi target e quantita per un insieme di asset. Non esegue ordini: produce un piano da applicare manualmente dal simulatore. Metodi disponibili:

- `EQUAL_WEIGHT`: stesso peso a ogni asset.
- `RISK_PARITY`: peso inversamente proporzionale alla volatilita annualizzata (inverse-vol), cosi ogni asset contribuisce un rischio simile.
- `SCORE_WEIGHTED`: peso proporzionale allo score tecnico oltre 50.
- `VOL_TARGET`: parte da risk parity e scala la quota investita per centrare una volatilita target, lasciando il resto in liquidita.

Opzioni: `max_weight` (cap per singolo asset con redistribuzione), `target_volatility`, `lookback_days`. La volatilita di portafoglio e una stima conservativa (media pesata delle volatilita, assume correlazione 1). Nel frontend il pianificatore e nella pagina Portafoglio con grafico a torta e tabella pesi/capitale/quantita.

L'endpoint `POST /portfolio/allocation/apply` sostituisce direttamente le posizioni con quelle del piano; prima di invocarlo la UI richiede una conferma che mostra capitale totale e liquidita risultante. `POST /portfolio/allocation/rebalance` confronta invece il piano con il portafoglio attuale e restituisce i trade (BUY/SELL) necessari per allinearlo (ottimizzatore/ribilanciamento).

## Catalogo strumenti Trade Republic

`POST /data/catalog/refresh?force=false` importa manualmente il PDF pubblico dell'universo strumenti italiano da un URL ufficiale fisso. L'endpoint non accetta URL o body forniti dal client, non viene chiamato all'avvio o dai refresh aggregati e limita il download a 32 MiB. `force=true` ignora soltanto la cache valida: quota, cooldown, fingerprint, deduplica delle richieste concorrenti e validazione del trasporto restano attivi.

Ogni payload completo diverso crea uno snapshot versionato tramite SHA-256; lo stesso payload restituisce lo snapshot esistente con `unchanged=true`. Gli errori sono registrati con soli codici stabili e sanitizzati, senza sostituire l'ultimo snapshot completo. Il PDF attesta esclusivamente l'appartenenza storica al catalogo: non dimostra che uno strumento sia negoziabile oggi. L'import crea o associa soltanto l'identita instrument per un ISIN valido; non crea listing o righe `assets` e non aggiorna i prezzi.

Le soglie locali sono configurabili con `TRADE_REPUBLIC_CATALOG_CACHE_TTL_HOURS`, `TRADE_REPUBLIC_CATALOG_MINUTE_LIMIT`, `TRADE_REPUBLIC_CATALOG_DAILY_LIMIT` e `TRADE_REPUBLIC_CATALOG_MONTHLY_LIMIT`.

### Risoluzione identificativi e metadata listing

`POST /data/catalog/{snapshot_id}/resolve?offset=0&limit=5` risolve manualmente una pagina immutabile di entry `ACCEPTED`, ordinate per riga e ID. Ogni richiesta OpenFIGI usa al massimo cinque job `ID_ISIN` in una sola POST; `OPENFIGI_API_KEY` è opzionale e, se configurata, viaggia soltanto nell'header `X-OPENFIGI-APIKEY`. Nessun exchange code non verificato viene inviato e nessun candidate viene scelto per posizione nell'array.

Una candidate univoca non basta: lo stato diventa `RESOLVED` solo quando esiste una versione metadata locale `VERIFIED` con ticker, MIC/venue, valuta ISO 4217, timezone IANA e tipo coerenti. I metadata si confermano con il ciclo locale `POST /data/catalog/entries/{catalog_entry_id}/listing-metadata/preview` e `/apply`; il token SHA-256 lega payload, evidence hash e versione corrente. Apply non contatta provider. Le versioni precedenti e le attestazioni per snapshot restano append-only; il catalogo non crea righe `assets` e non modifica import o allocation.

Configurazione conservativa: `OPENFIGI_CACHE_TTL_HOURS`, `OPENFIGI_MINUTE_LIMIT`, `OPENFIGI_DAILY_LIMIT` e `OPENFIGI_MONTHLY_LIMIT`. OpenFIGI non è fonte canonica per MIC, valuta o timezone e i suoi simboli vengono salvati soltanto dopo la risoluzione completa.

### API catalogo, attivazione e conferme locali

Tutti questi endpoint leggono e scrivono soltanto il database locale: nessuna chiamata a provider, nessun login, nessuna automazione dell'app Trade Republic, nessun ordine.

- `GET /instruments?q=&asset_class=&instrument_type=&currency=&mic=&quality_tier=&trade_republic_status=&limit=50&offset=0` cerca nel catalogo (più ampio degli asset attivi): una riga per listing, oppure una riga senza listing per gli strumenti non ancora risolti. `q` è case-insensitive su nome, ticker, ISIN e FIGI; i filtri sono un'allowlist parametrica, `limit` va da 1 a 100, `offset` da 0. Ordine stabile `canonical_name`, `instrument_id`, `listing_id`; `total` e pagina sono letti nella stessa transazione. `catalog_snapshot_id` è l'ultimo snapshot completo del catalogo ufficiale.
- `GET /instruments/{instrument_id}` restituisce identificativi attestati (con fonti e prima/ultima osservazione) e tutti i listing con stato di risoluzione e stato Trade Republic, senza payload provider raw.
- `POST /assets/from-listing/{listing_id}` attiva esplicitamente un listing `RESOLVED` copiandone i metadata verificati (ticker, nome, tipo, MIC, valuta, ISIN) e collegando `assets.instrument_listing_id`: 201 alla creazione, 200 se il listing è già attivo. Risponde 409 per listing non risolto, identità ambigua, tipo non supportato o simbolo già attivo su un altro listing (anche legacy): il simbolo legacy non diventa mai ambiguo. `/assets` resta la lista degli strumenti attivati.
- `POST /instruments/listings/{listing_id}/provider-symbols/preview` e `/apply` confermano un simbolo provider (`stooq` EOD, `finnhub` QUOTE/NEWS su venue USA, `coingecko` per crypto) su un listing `RESOLVED`, con `source` codice descrittivo (mai URL), `evidence_hash` SHA-256, `observed_at` con fuso e `expected_currency` uguale alla valuta del listing. Il simbolo è normalizzato per provider (Stooq e CoinGecko minuscolo, Finnhub maiuscolo). Apply ricostruisce il token sullo stato locale (`hmac.compare_digest`), ritira la versione corrente e crea una nuova versione `VERIFIED` con `supersedes`; lo stesso payload è idempotente, un `observed_at` diverso rende il token stale (409) e lo stesso simbolo già verificato su un altro listing produce 409.
- `POST /instruments/listings/{listing_id}/trade-republic/preview` e `/apply` registrano una conferma manuale `VERIFIED` o `UNAVAILABLE` (fonti `MANUAL_OFFICIAL_APP_CHECK`, `OFFICIAL_SUPPORT_NOTICE`). La storia in `trade_republic_attestations` è append-only con una sola versione `ACTIVE` per listing; apply (`BEGIN IMMEDIATE`) ritira la precedente, inserisce la nuova e aggiorna la projection `instrument_listings.trade_republic_status/verified_at` nella stessa transazione. `CATALOGED` non diventa mai `VERIFIED` da solo; `UNAVAILABLE` azzera `verified_at` e conserva `cataloged_at`.

Gli errori hanno la forma `{"detail": {"reason_code": "..."}}`: 422 per payload non valido o incompatibile, 409 per stato cambiato o conflitto, 404 per listing o strumento inesistente.

### Tier di qualità degli strumenti

La qualità è valutata separatamente dalla negoziabilità e viene versionata in `quality_assessments`; `instruments.quality_tier`, `quality_reason_code` e `quality_assessed_at` sono soltanto la projection corrente. I nomi API sono `QUALIFIED`, `OBSERVABLE` e `REFERENCE_ONLY`; la label UI dell'ultimo è “Reference only”. Una promozione non crea asset, strategie o ordini e non rende automaticamente tradabile lo strumento.

- `QUALIFIED`: identità primaria verificata, listing completo, almeno 60 barre EOD su date distinte nello scope provider effettivamente selezionato e ultima barra non più vecchia di 96 ore.
- `OBSERVABLE`: mapping univoco e almeno un'osservazione EOD o QUOTE valida e non stale, ma requisiti di qualificazione incompleti.
- `REFERENCE_ONLY`: reference type, identità ambigua, rejection critica aperta nello scope selezionato, provider divergenti oltre soglia, oppure nessuna osservazione compatibile non stale.

QUOTE, NEWS e REFERENCE opzionali non bloccano una qualificazione basata su EOD. Se viene usato un fallback compatibile, l'evidence conserva l'actual provider e aggiunge `COMPATIBLE_FALLBACK_IN_USE`; una rejection del provider richiesto non nasconde né declassa il fallback valido, mentre una rejection aperta del provider effettivamente usato è bloccante. Due prezzi `last`/`close` non stale, nella stessa valuta e distanti al massimo dieci minuti, causano `PROVIDER_DIVERGENCE` quando lo scarto supera 500 bps; i valori non vengono mediati.

Le soglie sono configurabili tramite `MARKET_DATA_QUOTE_MAX_AGE_MINUTES` (default 5), `MARKET_DATA_DELAYED_MAX_AGE_MINUTES` (30), `MARKET_DATA_EOD_MAX_AGE_HOURS` (96), `MARKET_DATA_REFERENCE_MAX_AGE_DAYS` (7), `MARKET_DATA_QUALIFIED_HISTORY_BARS` (60), `MARKET_DATA_DIVERGENCE_BPS` (500) e `TRADE_REPUBLIC_VERIFIED_MAX_AGE_DAYS` (30). La guardia strategia richiede un tier `QUALIFIED` già registrato e dati ancora validi; quando è richiesta Trade Republic, accetta solo `VERIFIED` recente, mai il solo stato `CATALOGED`.

## Dati reali con cache

### Attivazione rapida

1. Copia `backend/.env.example` in `backend/.env`.
2. Per i prezzi EOD imposta `ENABLE_REAL_DATA=true` e `ENABLE_STOOQ=true`; ogni listing deve avere un simbolo Stooq `VERIFIED` esplicito in `provider_symbols`. Per le quote snapshot USA configura `FINNHUB_API_KEY` e un simbolo Finnhub `QUOTE/VERIFIED` sul listing. Per le news Alpha Vantage, configura separatamente la key e `ENABLE_REAL_NEWS=true`.
3. Riavvia `Avvia-InvestEdge.bat`.
4. Apri la pagina **Dati** e clicca **Aggiorna tutti i dati** (e nella pagina **News**, **Aggiorna tutte**).

Finche non fai questo, l'app mostra dati simulati: il banner in dashboard indica la modalita corrente (SEED/MIXED/REAL). Il file `backend/.env` non va mai committato (e gia in `.gitignore`).

Lo Step 6 aggiunge provider esterni autorizzati, ma non li usa automaticamente all'apertura della dashboard. I refresh reali partono solo dagli endpoint `/data/refresh/*` o dalla pagina frontend `Dati`.

Provider predisposti:

- `StooqProvider`: barre EOD per listing compatibili, soltanto in opt-in e con mapping verificato; non deriva suffissi o simboli dal ticker locale.
- `FinnhubQuoteProvider`: quote snapshot soltanto per listing su MIC USA allowlistati e simbolo `QUOTE/VERIFIED`; usa `X-Finnhub-Token`, classifica conservativamente il feed come `delayed` e non crea barre in `price_history`.
- `AlphaVantageProvider`: visibile ma disabilitato per i prezzi con reason code `SECRET_IN_QUERY_POLICY`; la key non viene inserita in URL o transport.
- `YahooFinanceProvider`: mantenuto per compatibilita, ma disabilitato come provider prezzo primario o fallback di rete con reason code `NOT_PRIMARY_POLICY`.
- `CoinGeckoProvider`: barre EOD e quote EUR/USD soltanto con un `COINGECKO_ID` verificato; i cinque asset crypto legacy ricevono esclusivamente il mapping curato BTC=`bitcoin`, ETH=`ethereum`, SOL=`solana`, BNB=`binancecoin`, XRP=`ripple`. Non deriva l'identita dal ticker, dal nome, da ISIN o da MIC. Le barre giornaliere sono in UTC: il punto delle 00:00 UTC chiude il giorno precedente e il giorno UTC in corso, incompleto, non diventa una barra EOD. Powered by CoinGecko API.
- `EcbFxProvider`: cambi di riferimento BCE verso EUR (ECB Data Portal, serie EXR `D.<VALUTA>.EUR.SP00.A` in CSV, `lastNObservations=2`, `If-Modified-Since`/304). Keyless, budget locale 5/minuto, 50/giorno e 500/mese, qualita `reference` e mai realtime. Refresh manuale di una sola valuta con `POST /data/fx/refresh?from_currency=USD` (richiede `ENABLE_REAL_DATA=true`); un refresh fallito non tocca l'ultimo cambio valido e le operazioni continuano a bloccarsi su cambio mancante o stale.
- `FredReferenceProvider` (alias storico `FredProvider`): serie DGS10, DGS2 e FEDFUNDS soltanto come riferimento, mai come prezzo. Disabilitato per policy: senza key `MISSING_CREDENTIAL`, con key `SECRET_IN_QUERY_POLICY` (FRED v1 richiede la key in query string); FRED v2 offre solo download bulk (`BULK_ONLY_POLICY`). Nessuna chiamata di rete. `BTP10Y` e' soltanto un alias legacy del proxy USA `DGS10`, etichettato `REFERENCE_ONLY/US_10Y_PROXY`. Fonte: FRED®, Federal Reserve Bank of St. Louis.

Modalita dati:

- `SEED`: solo dati locali generati dallo script seed.
- `MIXED`: storico locale con alcune righe reali aggiornate manualmente.
- `REAL`: tutte le righe prezzo presenti sono reali.

Regole operative:

- se `ENABLE_REAL_DATA=false`, il backend non chiama API esterne e usa seed/demo;
- Stooq richiede anche `ENABLE_STOOQ=true` e un mapping `provider_symbols` esplicito e verificato;
- Finnhub richiede una key solo header, un mapping esplicito e uno dei MIC `XNYS`, `XNAS`, `XASE`, `ARCX`, `BATS`; key assente, quota o timeout disabilitano/fanno fallire soltanto quel provider e il fallback accetta esclusivamente una QUOTE non stale dello stesso listing;
- CoinGecko usa la Demo key opzionale soltanto nell'header `x-cg-demo-api-key`; in modalita keyless non invia credenziali. Il fallback conserva esclusivamente l'ultima observation CoinGecko della valuta del listing, senza conversioni USD/EUR implicite;
- se la cache non e scaduta, il backend usa la cache;
- se manca una API key, se il provider fallisce o se un budget e raggiunto, l'app seleziona l'ultima observation compatibile senza mutarne listing o valuta;
- ogni chiamata reale incrementa `api_usage`;
- le API key non vengono stampate nei log, nel frontend, nei test o in questa documentazione.

### Refresh prioritario e limitato

I refresh passano da una coda (`refresh_requests`, esiti in `refresh_runs`) con priorita esplicite: posizioni (10), candidati da segnali BUY/STRONG_BUY (20), watchlist attiva (30), refresh richiesto (40), strumento visualizzato (50), catalogo EOD (60). Ogni listing/capability ha al massimo un'unita aperta: una richiesta successiva puo solo alzare la priorita, anticipare l'orario o attivare `force`, mai disattivarlo.

- `POST /data/refresh-all` esegue al massimo 25 unita (10 se `limit` e omesso) e non visita mai il catalogo; restituisce lo stesso formato `DataRefreshAllOut`.
- `POST /data/refresh/{symbol}` accoda un'unita `REQUESTED` con il `force` ricevuto e la esegue subito.
- `POST /data/refresh/viewed/{listing_id}` accoda un'unita `VIEWED` non forzata.
- `POST /data/catalog/eod/enqueue?after_listing_id=0&limit=25` accoda il catalogo per pagine keyset (al massimo 25 listing esaminati, solo con mapping provider verificato e dati non freschi); `next_cursor` indica da dove ripartire.
- Senza `force` un dato fresco viene saltato; con `force` si salta la freschezza e si ignora la cache, ma quota, cooldown, deduplica e validazione restano obbligatori. Un provider in cooldown rinvia l'unita senza consumare budget.
- Script: `backend\.venv\Scripts\python.exe backend\scripts\activate_real_data.py --limit 10` mostra l'anteprima; aggiungere `--execute` per eseguire. Default del batch configurabile con `REFRESH_BATCH_DEFAULT_LIMIT` (10).

Configura le variabili in `backend/.env` o nell'ambiente locale. Il file `backend/.env` puo contenere chiavi reali e non deve essere committato.

```env
ENABLE_REAL_DATA=false
ENABLE_STOOQ=false
STOOQ_CACHE_TTL_HOURS=24
STOOQ_MINUTE_LIMIT=5
STOOQ_DAILY_LIMIT=100
STOOQ_MONTHLY_LIMIT=1000
FINNHUB_API_KEY=
FINNHUB_QUOTE_CACHE_TTL_SECONDS=60
FINNHUB_QUOTE_MINUTE_LIMIT=55
ALPHA_VANTAGE_API_KEY=
COINGECKO_API_KEY=
COINGECKO_EOD_CACHE_TTL_HOURS=24
COINGECKO_QUOTE_CACHE_TTL_SECONDS=60
COINGECKO_DEMO_MINUTE_LIMIT=90
COINGECKO_DEMO_MONTHLY_LIMIT=9000
COINGECKO_KEYLESS_MINUTE_LIMIT=10
COINGECKO_KEYLESS_MONTHLY_LIMIT=1000
FRED_API_KEY=
API_CACHE_TTL_HOURS=24
ALPHA_VANTAGE_DAILY_LIMIT=20
FRED_DAILY_LIMIT=100
```

## News reali e sentiment base

Il modulo News collega notizie agli asset senza fare scraping web e senza trasformare il sentiment in una previsione certa. Le news sono un supporto decisionale: il motore sentiment e euristico, basato su keyword, e puo sbagliare tono o importanza.

Provider disponibili:

- `FinnhubNewsProvider`: unico provider news live. Richiede `ENABLE_REAL_NEWS=true`, `FINNHUB_API_KEY` (inviata solo nell'header `X-Finnhub-Token`), un simbolo `provider_symbols` Finnhub `NEWS/VERIFIED` del listing e una venue USA supportata (`XNYS`, `XNAS`, `XASE`, `ARCX`, `BATS`). Budget locale 55/minuto, piu i limiti giornaliero (`NEWS_DAILY_LIMIT`) e mensile (`FINNHUB_NEWS_MONTHLY_LIMIT`); al massimo 50 articoli per risposta, scartati quelli senza orario valido o con orario futuro, URL accettati solo se http(s) pubblici.
- `AlphaVantageNewsProvider`: disabilitato con reason code `SECRET_IN_QUERY_POLICY` (la key andrebbe in query string); non costruisce URL.
- `YahooNewsProvider`: disabilitato con reason code `NOT_PRIMARY_POLICY`; nessuna richiesta di rete.
- `NewsProviderMock`: news demo/locali per test, demo e fallback. Restano visibili (provider `mock_news`, fonte "InvestEdge Demo") ma non entrano mai in sentiment, `news_score`/`final_score`, riepilogo di mercato o feature ML, e un refresh non ne rinnova la data di pubblicazione.

Modalita operative:

- con `ENABLE_REAL_NEWS=false` il backend non chiama API esterne e usa news demo/locali;
- con real news abilitate ma key Finnhub assente, simbolo NEWS non verificato o venue non supportata, l'app non chiama Finnhub e usa news locali;
- `POST /news/refresh-all` aggiorna soltanto gli asset attivi: 10 di default, al massimo 25 (`limit` fra 1 e 25), e inoltra `force` come semplice bypass della cache;
- se la cache news e valida, il backend riusa `api_cache`;
- se il limite giornaliero e raggiunto o il provider fallisce, vengono usate news gia presenti nel database o fallback demo;
- dashboard e watchlist non avviano chiamate news esterne automaticamente;
- nessuna API key viene stampata nei log, nel frontend, nei test o nella documentazione.

Variabili news:

```env
ENABLE_REAL_NEWS=false
FINNHUB_API_KEY=
FINNHUB_NEWS_MINUTE_LIMIT=55
FINNHUB_NEWS_MONTHLY_LIMIT=0
NEWS_CACHE_TTL_HOURS=6
NEWS_DAILY_LIMIT=20
NEWS_SENTIMENT_WEIGHT=5
```

Campi principali salvati in `news_items`: `symbol`, `provider`, `title`, `summary`, `url`, `source`, `published_at`, `sentiment_score`, `sentiment_label`, `impact_level`, `relevance_score` e `raw_json`.

Keyword positive iniziali: earnings beat, revenue growth, raises guidance, upgrade, partnership, approval, buyback, dividend increase.

Keyword negative iniziali: earnings miss, revenue decline, lawsuit, downgrade, investigation, recall, bankruptcy, guidance cut, regulatory risk.

## Avvio backend

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Endpoint iniziali:

- `GET /health`
- `GET /assets`
- `GET /assets/{symbol}`
- `POST /assets`
- `POST /assets/from-listing/{listing_id}`
- `DELETE /assets/{symbol}`
- `GET /instruments?q=&limit=50&offset=0`
- `GET /instruments/{instrument_id}`
- `POST /instruments/listings/{listing_id}/provider-symbols/preview`
- `POST /instruments/listings/{listing_id}/provider-symbols/apply`
- `POST /instruments/listings/{listing_id}/trade-republic/preview`
- `POST /instruments/listings/{listing_id}/trade-republic/apply`
- `GET /prices/{symbol}`
- `GET /technical-analysis/{symbol}`
- `GET /portfolio`
- `POST /portfolio/init`
- `POST /portfolio/refresh`
- `GET /portfolio/snapshots`
- `GET /portfolio/recommendations`
- `POST /orders/simulate`
- `GET /orders`
- `POST /backtests/run`
- `POST /backtests/compare`
- `POST /backtests/walk-forward`
- `POST /portfolio/allocation/plan`
- `GET /import/google-sheets/status`
- `POST /import/google-sheets/preview`
- `POST /import/google-sheets/apply`
- `GET /action-board`
- `GET /alerts/status`
- `POST /alerts/test`
- `POST /alerts/send-today`
- `GET /backtests`
- `GET /backtests/{backtest_id}`
- `DELETE /backtests/{backtest_id}`
- `GET /data/status`
- `GET /data/status/{symbol}`
- `POST /data/catalog/refresh?force=false`
- `POST /data/catalog/{snapshot_id}/resolve?offset=0&limit=5`
- `POST /data/catalog/entries/{catalog_entry_id}/listing-metadata/preview`
- `POST /data/catalog/entries/{catalog_entry_id}/listing-metadata/apply`
- `POST /data/refresh/{symbol}?force=false`
- `POST /data/refresh-all?limit=5&force=false`
- `POST /data/refresh/viewed/{listing_id}`
- `POST /data/catalog/eod/enqueue?after_listing_id=0&limit=25`
- `POST /data/fx/refresh?from_currency=USD`
- `GET /data/usage`
- `GET /news?limit=50&symbol=AAPL`
- `GET /news/{symbol}`
- `POST /news/refresh/{symbol}?force=false`
- `POST /news/refresh-all?limit=50&force=false`
- `GET /news/sentiment/{symbol}`
- `GET /news/status`
- `GET /signals`
- `GET /signals/{symbol}`
- `GET /dashboard`

Esempio inizializzazione portafoglio:

```http
POST /portfolio/init
{
  "initial_cash": 100000,
  "max_single_asset_weight": 25,
  "max_asset_class_weight": 55,
  "default_fee_percent": 0.1
}
```

Esempio ordine simulato:

```http
POST /orders/simulate
{
  "symbol": "AAPL",
  "order_type": "BUY",
  "quantity": 5,
  "price": 180,
  "fees": 1,
  "note": "Paper trade locale",
  "strategy_tag": "Demo"
}
```

Esempio backtest:

```http
POST /backtests/run
{
  "name": "Weekly top score",
  "strategy_name": "TOP_N_SCORE",
  "symbols": ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
  "initial_cash": 100000,
  "start_date": "2025-01-01",
  "end_date": "2026-05-15",
  "benchmark_symbol": "SPY",
  "buy_threshold": 70,
  "sell_threshold": 40,
  "max_asset_weight": 0.15,
  "fee_percent": 0.10,
  "stop_loss_percent": 8,
  "take_profit_percent": 25,
  "rebalance_frequency": "WEEKLY",
  "top_n": 5
}
```

Esempio refresh dati:

```http
POST /data/refresh/AAPL?force=false
```

Risposta sintetica:

```json
{
  "symbol": "AAPL",
  "provider": "stooq",
  "rows_inserted": 0,
  "rows_updated": 730,
  "used_cache": false,
  "used_fallback": false,
  "message": "Prezzi aggiornati da provider reale."
}
```

La documentazione interattiva FastAPI e disponibile su `http://127.0.0.1:8000/docs`.

## Avvio frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend locale: `http://127.0.0.1:5173`.

Il frontend usa `VITE_API_BASE_URL` se presente, con fallback a `http://127.0.0.1:8000`.

## Test

```powershell
backend\.venv\Scripts\python.exe -m pytest
```

Build frontend:

```powershell
cd frontend
npm run build
```

## Variabili ambiente

Copia `.env.example` in `.env` e modifica i valori se necessario. Per le chiavi reali usa preferibilmente `backend/.env`, che deve restare locale e non committato.

Il database SQLite viene creato automaticamente in `data/investedge.db` al primo avvio del backend. Se la UI mostra `Database non inizializzato`, esegui il comando seed sopra e ricarica il frontend.

## Machine Learning (AI Lab)

Modulo ML sperimentale basato su scikit-learn. Endpoint: `GET /ml/status`, `POST /ml/train`, `GET /ml/models`, `POST /ml/predict/{symbol}`, `POST /ml/predict-all`, `GET /ml/predictions/{symbol}`.

- **Modelli**: regressione logistica, random forest, **gradient boosting** (HistGradientBoosting, consigliato).
- **Target**: rendimento positivo, batte il benchmark, rischio forte ribasso, su un orizzonte configurabile.
- **28 feature**: tecniche (trend/momentum/volatilità/volume), sotto-score, sentiment news, peso in portafoglio.
- **No look-ahead**: i target usano solo rendimenti futuri via shift; `validate_no_lookahead` blocca eventuali bias.
- **Validazione walk-forward**: oltre allo split temporale, la metrica viene mediata su N fold a finestra espansiva — se è debole il modello non generalizza.
- **Explainability**: feature importance (nativa o permutation importance) e probabilità con livello di confidenza.

È uno strumento di supporto: fornisce probabilità, non certezze. Su dati simulati l'accuratezza è vicina al caso (~50%); diventa più informativo con dati reali, ma non garantisce rendimenti. I modelli serializzati vivono in `data/ml_models/` (non committati).

## Sviluppo: lint, test, CI

Il linting Python usa ruff, configurato in `ruff.toml`. Installa le dipendenze di sviluppo e lancia i controlli:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
backend\.venv\Scripts\ruff.exe check backend tests scripts
backend\.venv\Scripts\ruff.exe format backend tests scripts
```

Hook pre-commit disponibili in `.pre-commit-config.yaml` (ruff + controlli base). Attiva con `pip install pre-commit && pre-commit install`.

La pipeline CI in `.github/workflows/ci.yml` esegue su push e pull request: ruff + pytest sul backend e build del frontend. Il frontend non usa eslint separato: il type-check avviene con `tsc -b` durante `npm run build`.

## Prossime estensioni previste

- analisi scenario avanzata (shock di prezzo, regime change)
- ottimizzazione pesi con matrice di correlazione reale (oltre la stima conservativa attuale)
- code-splitting del bundle frontend
- integrazioni broker solo in una fase futura e solo se esplicitamente abilitate
