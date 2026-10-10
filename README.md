# InvestEdge

InvestEdge e una web app locale per analisi investimenti su azioni, ETF, cripto e bond/ETF obbligazionari.

La fase attuale include backend FastAPI, database SQLite, frontend React/Vite/TypeScript/Tailwind, analisi tecnica avanzata, scoring spiegabile, portafoglio simulato, paper trading, backtest, confronto multi-strategia, pianificatore di allocazione capitale, integrazione dati reali opzionale con cache e modulo news/sentiment. Include un modulo ML sperimentale sulla pipeline condivisa; collegamenti a broker e trading automatico restano nei sottoprogetti successivi.

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

Le sovrapposizioni dei grafici in `backend/app/services/technical_analysis.py` usano pandas e numpy. L'Analisi e lo score usano la pipeline causale SP1 descritta sotto. Le sovrapposizioni disponibili includono:

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

Lo score v1 è esclusivamente tecnico: `final_score = score = technical_score`. News e sentiment sono informativi e non modificano il punteggio; la loro validazione come segnali appartiene a SP3.

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

## Laboratorio di verità (SP1)

La pipeline `features-v1` / `score-v1` alimenta Analisi, segnali, Backtest e ML. Le feature sono causali e a finestra limitata; lo score D e i sottopunteggi sono quelli salvati in `features_daily`. Le barre W/M entrano solo a periodo di calendario chiuso. Lo score richiede 252 barre del proprio timeframe: prima si mostra storico insufficiente. I grafici possono mantenere sovrapposizioni diverse, incluso Ichimoku, senza usarle nei calcoli del laboratorio.

**REAL e DEMO:** REAL usa esclusivamente prezzi marcati reali; DEMO usa esclusivamente seed. Un asset con una serie REAL corta non ripiega sui prezzi demo. Backtest e training scelgono esplicitamente la modalità; l'Evidenza accetta solo REAL. DEMO non produce tentativi, DSR o verdetti. Il simulatore locale del portafoglio e il futuro Alpaca paper sono contesti distinti: prezzi REAL con esecuzioni PAPER non equivalgono a dati DEMO.

Alla migrazione i soli segnali derivati del vecchio `scoring_engine` senza `data_mode` sono invalidati: potevano contenere la vecchia correzione news. Tornano con un ricalcolo, refresh o seed esplicito; la migrazione non inventa l'origine dei dati e non ricalcola automaticamente gli asset.

### Job e pagina Backtest

`POST /backtests/run`, `/backtests/compare`, `/backtests/walk-forward`, `/lab/evidence` e `/ml/train` restituiscono **202 con JobOut**. L'identificativo è `id`: seguire `GET /lab/jobs/{id}` fino a `SUCCEEDED`, `FAILED`, `CANCELLED` o `INTERRUPTED`; `POST /lab/jobs/{id}/cancel` chiede un annullamento cooperativo. Un job interrotto richiede un nuovo avvio esplicito. La coda ha un worker; il riavvio nello stesso processo conserva un worker ancora vivo senza duplicarlo o segnalarlo come interrotto.

La pagina Backtest ha modalità Singolo, Confronto, Robustezza ed Evidenza. Singolo legge il dettaglio tramite `result_ref`; Confronto e Robustezza leggono `result`; Evidenza carica tutti gli ID in `result.report_ids`. Stati, avanzamento, errori e annullamento sono visibili nella pagina. Un 409 dichiara dati REAL assenti, periodo insufficiente o altri input non utilizzabili.

### Backtest in EUR e walk-forward

Le strategie sono `SCORE_THRESHOLD`, `TOP_N_SCORE` e `BUY_AND_HOLD`. La decisione usa la chiusura di t; il fill avviene all'apertura della barra successiva del listing. Stop e target usano high/low, con priorità allo stop se entrambi sono toccati. Gap e split sospetti separano segmenti, ognuno con il proprio warm-up.

I nuovi run v1 sono in EUR, con FX BCE as-of e costi salvati: default commissione 1 € per ordine e costo per lato 10 bps equity / 50 bps crypto, quote intere equity e ordine minimo 100 €. Il profilo è configurabile per run. Commissioni e spread/slippage sono già nella curva e non vengono sottratti due volte; imposte e bollo appartengono all'analisi netta. I vecchi run v0 mantengono i propri importi e unità legacy.

Il benchmark e i suoi prezzi/FX effettivi sono congelati nel run e nell'impronta: revisioni successive non cambiano risultati già salvati. Gli storici senza snapshot mostrano `NOT_RECORDED`, avviso e curva benchmark assente; non vengono completati con dati correnti.

Confronto ordina per Sharpe netto. Robustezza applica finestre IS/OOS in sedute, seleziona una piccola griglia solo sui rendimenti IS e prosegue con un'unica simulazione OOS. Ogni selezione usa un prefisso al cutoff, anche per segmenti ed eleggibilità. Sharpe IS/OOS e degrado del WFO sono annualizzati; SR/SR0 del DSR sono giornalieri. N conta configurazioni distinte con Sharpe definito nella famiglia segnale/timeframe, non il numero di esecuzioni.

### Evidenza e badge

Esempio di richiesta, su storico REAL locale sufficiente:

```json
{
  "signal_name": "score",
  "timeframe": "D",
  "horizons": [1, 5, 21],
  "start_date": "2019-01-01",
  "end_date": "2024-01-01"
}
```

L'harness misura IC Spearman, t di Newey-West, bucket e spread netto con turnover, poi walk-forward long-only e DSR. Default: almeno 10 nomi, 252 date IC e 252 sedute OOS. `VALIDATO` richiede IC medio positivo, t ≥ 2, spread netto positivo e DSR ≥ 0,95; altrimenti `NON_VALIDATO` o `INSUFFICIENTE`. Senza report: `NON_MISURATO`.

Report e tentativi sono append-only. `GET /lab/evidence`, `/lab/evidence/{id}` e `/lab/evidence/latest?signal_name=score&timeframe=D` leggono snapshot immutabili. I badge accanto allo score sono evidenza globale sul segnale/timeframe, non certificazioni del singolo asset; tooltip e report dichiarano periodo, universo e orizzonte. SP1 misura e mostra il verdetto: non lo applica ancora come blocco agli ordini.

### Cambi BCE storici

Il backfill è esplicito, nel provider governato esistente: `POST /data/fx/backfill` con `currencies` e `start_date`, oppure `python -m backend.scripts.backfill_fx_history --currency USD --start 2015-01-01`. La CLI è in anteprima senza `--apply`; applicare richiede configurazione utente `ENABLE_REAL_DATA=true`. Con dati reali disattivati il job rifiuta prima di chiamare la rete.

I cambi seed sono esclusi anche dai run DEMO. Per asset non EUR servono osservazioni storiche BCE valide; senza cambio as-of entro `ECB_FX_MAX_AGE_DAYS` (default 7) la barra è esclusa e conteggiata. EUR usa fattore 1.

### Limiti e verifica offline

L'universo attuale introduce survivorship bias; Stooq ha base di rettifica UNKNOWN e dividendi non verificati; split sospetti sono euristici. Un cambio di base del provider apre un segmento da quel punto, senza riscrivere il passato. Storico corto, FX mancanti, calendari misti e costi ipotizzati sono dichiarati nei risultati. Lo spread long-short dell'harness è diagnostico; il WFO è long-only. ML resta sperimentale e la revisione di target/metriche/split appartiene a SP4.

Le prove sintetiche verificano il software. Evidenza D/W/M e orizzonti 1/5/21 sedute non validano posizioni intraday di 15–30 minuti; i gate dati/news e strategie SP2b/SP3 precedono Alpaca paper senza leva, mentre reale e leva richiedono validazione e azioni esplicite successive.

Smoke riproducibile, con file nuovo nello scratch, rete bloccata e nessun provider live:

```powershell
$sp1PreviousDbPath = $env:INVESTEDGE_DB_PATH
try {
    $env:INVESTEDGE_DB_PATH = Join-Path $env:TEMP ("lab-perf-" + [guid]::NewGuid() + ".sqlite3")
    & '.\backend\.venv\Scripts\python.exe' -m backend.scripts.lab_perf_smoke
} finally {
    $env:INVESTEDGE_DB_PATH = $sp1PreviousDbPath
}
```

Lo smoke usa 50 asset sintetici marcati REAL × 1500 daily, calcola D/W/M, aggiunge una barra a un asset e avvia Evidenza su cinque anni. Rifiuta un file già esistente o chiamato `investedge.db`. Conserva il DB sintetico nello scratch per ispezione. Obiettivi indicativi, non gate bloccanti: 60 / 5 / 120 secondi. Risultati finali, audit e limiti in [report SP1](docs/reports/2026-10-10-sp1-truth-lab-verification.md).

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
2. Per i prezzi EOD imposta `ENABLE_REAL_DATA=true` e `ENABLE_STOOQ=true`; ogni listing deve avere un simbolo Stooq `VERIFIED` esplicito in `provider_symbols`. Limite noto: gli asset attivati prima della Fase 2 (inclusi azioni ed ETF del seed demo, come SPY o AAPL) hanno un listing legacy senza MIC che non diventa mai `RESOLVED`, quindi non possono ricevere un simbolo provider; attivare il listing risolto con lo stesso ticker risponde 409 `LEGACY_SYMBOL_CONFLICT`. Restano su dati seed finche un sottoprogetto successivo non aggiunge il ricollegamento esplicito; oggi ricevono dati reali solo i listing attivati dal catalogo e le cinque crypto curate. Per le quote snapshot USA configura `FINNHUB_API_KEY` e un simbolo Finnhub `QUOTE/VERIFIED` sul listing. Per le news Alpha Vantage, configura separatamente la key e `ENABLE_REAL_NEWS=true`.
3. Riavvia `Avvia-InvestEdge.bat`.
4. Apri la pagina **Dati** e clicca **Esegui batch prioritario (10)** (e nella pagina **News**, **Aggiorna tutte**).

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

### Copertura dati misurabile

`GET /data/coverage` misura la copertura sul database locale, senza chiamate provider e senza scritture: tutte le query usano la stessa connessione, la stessa transazione di lettura e lo stesso `measured_at`. Ogni percentuale ha un denominatore esplicito e vale `0.0` quando il denominatore e zero; nessun numero di strumenti o percentuale obiettivo e promesso.

- Catalogo: solo l'ultimo snapshot `COMPLETE` del catalogo Trade Republic. `parse_denominator` = entry `ACCEPTED`/`AMBIGUOUS`/`REJECTED`; `resolution_denominator` = entry `ACCEPTED`, ciascuna in un solo bucket del suo ultimo resolution case (`RESOLVED`, `AMBIGUOUS`, `UNMATCHED`, `REJECTED`) oppure `UNPROCESSED`. `resolved_percent` usa soltanto gli `ACCEPTED`. `rejection_reasons` tiene distinte le cause del parser (`PARSE:<codice>`) e della resolution (`RESOLUTION:<codice>`).
- Tier: instrument distinti collegati alle entry `ACCEPTED` correnti. Stato Trade Republic: denominatore = entry `ACCEPTED`; le entry senza listing risolto restano nel bucket `UNRESOLVED_IDENTITY`. Gruppi per asset class e per MIC (`UNRESOLVED` se manca il listing risolto o il MIC).
- Provider (`coingecko` EOD/QUOTE, `finnhub` QUOTE, `stooq` EOD): `eligible_listings` = listing attivi risolti (metadata verificati e case `RESOLVED`) compatibili con la capability, partizionati in `unmapped`/`mapped` e i mapped in `fresh`/`stale`/`missing_observation`. La freschezza usa la policy delle observation al momento della misura; il bucket di ritardo (`0-5m`, `5-30m`, `30m-24h`, `1-4d`, `>4d`) usa il ritardo all'ingestione dell'ultima revisione. `rejected_observations` conta le rejection non ancora risolte. I listing legacy degli asset seed non sono risolti e non entrano nei denominatori provider.
- FX: valute non-EUR distinte di asset attivi, posizioni con quantita positiva e listing risolti; per ciascuna l'ultima riga diretta `valuta/EUR`, altrimenti l'inversa, con la soglia `ECB_FX_MAX_AGE_DAYS` e la reciprocita di `FXService`. `rate_to_eur` e una stringa decimale JSON (`null` se `MISSING`). EUR resta identita e non entra nel denominatore; i cambi congelati di posizioni e ordini non vengono toccati.
- Coda: `pending_refresh` (`PENDING`) e `budget_deferred` (`BUDGET_DEFERRED`).

`GET /data/status` resta compatibile e aggiunge `coverage_summary` (nullable: `null` se una partizione non somma al proprio denominatore, mentre `/data/coverage` risponde 500 con `COVERAGE_INVARIANT_FAILED`). Ogni provider aggiunge `capabilities`, `budget_windows` (minuto/giorno/mese con `limit`, `used`, `remaining`, `reset_at`), `cooldown_until`, `availability_state`/`availability_reason` e `last_outcome`/`last_outcome_at`; `daily_limit` e `calls_today` restano coerenti con la finestra giornaliera. Nessuna key, URL, endpoint o fingerprint viene esposto.

La pagina **Dati** (Data Center) mostra questi valori così come arrivano dall'API, senza ricalcolare percentuali: parsing e risoluzione del catalogo con i rispettivi denominatori, tier e stato Trade Republic (irrisolti inclusi), gruppi per classe e MIC, copertura provider (idonei, non mappati, mappati, freschi, non aggiornati, senza osservazione, rejection aperte), qualità effettiva e bucket di ritardo, budget minuto/giorno/mese con reset, cooldown, motivo di disponibilità e ultimo esito per provider, cambi verso EUR per valuta (diretto/inverso, fresco/non aggiornato/mancante) separati dai provider, motivi di rejection e coda. Gli orari sono nel fuso locale con l'UTC nel tooltip; un dato non aggiornato non viene mai etichettato come tempo reale e un `rate_to_eur` non decimale viene mostrato come `—`. L'unica azione aggregata è **Esegui batch prioritario (10)** (`POST /data/refresh-all?limit=10`), che poi ricarica status e copertura; il pannello backup e il refresh del singolo asset restano invariati. Se la copertura non è disponibile (per esempio `COVERAGE_INVARIANT_FAILED`) il resto della pagina resta consultabile.

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
- `GET /data/coverage`
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
  "data_mode": "REAL",
  "signal_name": "score",
  "signal_timeframe": "D",
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

La pagina **Universe** ha due tab. **Attivi** è la lista degli asset monitorati, con aggiunta, rimozione e purge protetto. **Catalogo** cerca nel catalogo strumenti (`GET /instruments`) con ricerca debounced (300 ms), filtri per classe, tier, stato Trade Republic, valuta e MIC, e pagine da 50 risultati senza caricare l'intero catalogo. Ogni riga mostra identificativo, venue, valuta, tier, freschezza del dato e stato Trade Republic, che indica la fonte della conferma e non la negoziabilità. Aprire un dettaglio segnala il listing come visualizzato una sola volta (`POST /data/refresh/viewed/{listing_id}`, nessun refresh provider immediato). L'attivazione è sempre esplicita, consentita solo per listing `RESOLVED` e con identità non ambigua; i conflitti 409 sono spiegati in pagina.

## Test

```powershell
backend\.venv\Scripts\python.exe -m pytest
```

Test e build frontend (Vitest + Testing Library in jsdom, API sempre simulate):

```powershell
cd frontend
npm run test:run
npm run build
```

## Variabili ambiente

Copia `.env.example` in `.env` e modifica i valori se necessario. Per le chiavi reali usa preferibilmente `backend/.env`, che deve restare locale e non committato.

Il database SQLite viene creato automaticamente in `data/investedge.db` al primo avvio del backend. Se la UI mostra `Database non inizializzato`, esegui il comando seed sopra e ricarica il frontend.

## Machine Learning (AI Lab)

Modulo ML sperimentale basato su scikit-learn. Training su job 202; modelli con versione della pipeline, modelli legacy da riaddestrare (409). Endpoint: `GET /ml/status`, `POST /ml/train`, `GET /ml/models`, `POST /ml/predict/{symbol}`, `POST /ml/predict-all`, `GET /ml/predictions/{symbol}`.

- **Modelli**: regressione logistica, random forest, **gradient boosting** (HistGradientBoosting, consigliato).
- **Target**: rendimento positivo, batte il benchmark, rischio forte ribasso, su un orizzonte configurabile.
- **31 feature**: tecniche adimensionali della pipeline `features-v1`, score e sottopunteggi; news e portafoglio esclusi. Training e previsione usano la modalità REAL/DEMO registrata nel modello.
- **No look-ahead**: i target usano solo rendimenti futuri via shift; `validate_no_lookahead` blocca eventuali bias.
- **Validazione walk-forward**: oltre allo split temporale, la metrica viene mediata su N fold a finestra espansiva — se è debole il modello non generalizza.
- **Explainability**: feature importance (nativa o permutation importance) e probabilità con livello di confidenza.

È uno strumento di supporto: fornisce probabilità, non certezze. Le metriche sintetiche non provano generalizzazione o rendimento sui mercati; la validazione economica resta separata. I modelli serializzati vivono in `data/ml_models/` (non committati).

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
