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

L'import **sostituisce** le posizioni del portafoglio simulato con quelle del foglio (operazione locale, non tocca il broker). Configura `GOOGLE_SHEETS_CSV_URL` in `backend/.env` oppure incolla il link nella pagina **Importa posizioni**. È il modo per far conoscere all'app il tuo portafoglio reale (es. da Trade Republic tracciato su un foglio).

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

L'endpoint `POST /portfolio/allocation/apply` crea direttamente le posizioni dal piano; `POST /portfolio/allocation/rebalance` confronta il piano con il portafoglio attuale e restituisce i trade (BUY/SELL) necessari per allinearlo (ottimizzatore/ribilanciamento).

## Dati reali con cache

### Attivazione rapida

1. Copia `backend/.env.example` in `backend/.env`.
2. Inserisci almeno la chiave Alpha Vantage (gratuita: https://www.alphavantage.co/support/#api-key) e imposta `ENABLE_REAL_DATA=true` (e `ENABLE_REAL_NEWS=true` per le news).
3. Riavvia `Avvia-InvestEdge.bat`.
4. Apri la pagina **Dati** e clicca **Aggiorna tutti i dati** (e nella pagina **News**, **Aggiorna tutte**).

Finche non fai questo, l'app mostra dati simulati: il banner in dashboard indica la modalita corrente (SEED/MIXED/REAL). Il file `backend/.env` non va mai committato (e gia in `.gitignore`).

Lo Step 6 aggiunge provider esterni autorizzati, ma non li usa automaticamente all'apertura della dashboard. I refresh reali partono solo dagli endpoint `/data/refresh/*` o dalla pagina frontend `Dati`.

Provider predisposti:

- `AlphaVantageProvider`: azioni, ETF ed ETF obbligazionari quotati.
- `CoinGeckoProvider`: cripto mappate BTC, ETH, SOL, BNB, XRP.
- `FredProvider`: serie macro/tassi e bond proxy, tra cui DGS10, DGS2 e FEDFUNDS.

Modalita dati:

- `SEED`: solo dati locali generati dallo script seed.
- `MIXED`: storico locale con alcune righe reali aggiornate manualmente.
- `REAL`: tutte le righe prezzo presenti sono reali.

Regole operative:

- se `ENABLE_REAL_DATA=false`, il backend non chiama API esterne e usa seed/demo;
- se la cache non e scaduta, il backend usa la cache;
- se manca una API key, se il provider fallisce o se il limite giornaliero e raggiunto, l'app usa i dati locali;
- ogni chiamata reale incrementa `api_usage`;
- le API key non vengono stampate nei log, nel frontend, nei test o in questa documentazione.

Configura le variabili in `backend/.env` o nell'ambiente locale. Il file `backend/.env` puo contenere chiavi reali e non deve essere committato.

```env
ENABLE_REAL_DATA=false
ALPHA_VANTAGE_API_KEY=
COINGECKO_API_KEY=
FRED_API_KEY=
API_CACHE_TTL_HOURS=24
ALPHA_VANTAGE_DAILY_LIMIT=20
COINGECKO_DAILY_LIMIT=100
FRED_DAILY_LIMIT=100
```

## News reali e sentiment base

Il modulo News collega notizie agli asset senza fare scraping web e senza trasformare il sentiment in una previsione certa. Le news sono un supporto decisionale: il motore sentiment e euristico, basato su keyword, e puo sbagliare tono o importanza.

Provider disponibili:

- `AlphaVantageNewsProvider`: usa Alpha Vantage News & Sentiment solo se `ENABLE_REAL_NEWS=true` e la chiave Alpha Vantage e configurata.
- `NewsProviderMock`: fallback deterministico per test, demo e assenza di configurazione reale.

Modalita operative:

- con `ENABLE_REAL_NEWS=false` il backend non chiama API esterne e usa news demo/locali;
- con real news abilitate ma API key assente, l'app non va in crash e usa news locali;
- se la cache news e valida, il backend riusa `api_cache`;
- se il limite giornaliero e raggiunto o il provider fallisce, vengono usate news gia presenti nel database o fallback demo;
- dashboard e watchlist non avviano chiamate news esterne automaticamente;
- nessuna API key viene stampata nei log, nel frontend, nei test o nella documentazione.

Variabili news:

```env
ENABLE_REAL_NEWS=false
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
backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8001
```

Endpoint iniziali:

- `GET /health`
- `GET /assets`
- `GET /assets/{symbol}`
- `POST /assets`
- `DELETE /assets/{symbol}`
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
- `POST /data/refresh/{symbol}?force=false`
- `POST /data/refresh-all?limit=5&force=false`
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
- `POST /admin/seed?reset=true`

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
  "provider": "alpha_vantage",
  "rows_inserted": 0,
  "rows_updated": 730,
  "used_cache": false,
  "used_fallback": false,
  "message": "Prezzi aggiornati da provider reale."
}
```

La documentazione interattiva FastAPI e disponibile su `http://127.0.0.1:8001/docs`.

## Avvio frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend locale: `http://127.0.0.1:5173`.

Il frontend usa `VITE_API_BASE_URL` se presente, con fallback a `http://127.0.0.1:8001`.

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
