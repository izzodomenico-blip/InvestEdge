# InvestEdge

InvestEdge e una web app locale per analisi investimenti su azioni, ETF, cripto e bond/ETF obbligazionari.

La fase attuale include backend FastAPI, database SQLite, frontend React/Vite/TypeScript/Tailwind, analisi tecnica avanzata, scoring spiegabile, portafoglio simulato, paper trading, backtest, integrazione dati reali opzionale con cache, news/sentiment, Universe Manager e Machine Learning leggero. Non include collegamenti reali a broker, ordini reali, deep learning, scraping non autorizzato o trading automatico.

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
  universe/
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
- importa l'universo investibile statico da `data/universe/`
- genera 2 anni di storico prezzi giornaliero
- calcola indicatori tecnici avanzati e segnali STRONG_BUY/BUY/HOLD/REDUCE/SELL
- con `--reset` inizializza un portafoglio demo da 100000 con ordini simulati su AAPL, MSFT, NVDA, BTC, ETH, SPY e QQQ

I 25 asset seed sono solo la demo minima con storico prezzi generato. Il limite operativo del sistema e definito dal Universe Manager.

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

## Dati reali con cache

Lo Step 6 aggiunge provider esterni autorizzati, ma non li usa automaticamente all'apertura della dashboard. I refresh reali partono solo dagli endpoint `/data/refresh/*`, dalla pagina frontend `Dati` o dalla pagina `Universe`.

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

`POST /data/refresh-all` non significa "aggiorna tutto l'universo": aggiorna solo i candidati selezionati dal Universe Manager, con default `limit=10` e massimo 50.

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

## News e sentiment base

Lo Step 7 aggiunge un modulo news con sentiment euristico per supportare le decisioni di investimento. Le news sono un supporto decisionale, non una garanzia di previsione, e il sentiment e una stima keyword-based, non un modello di machine learning.

Provider news predisposti:

- `AlphaVantageNewsProvider`: integra Alpha Vantage News & Sentiment se `ENABLE_REAL_NEWS=true` e la API key Alpha Vantage e configurata.
- `MockNewsProvider`: usato per test, fallback e modalita demo.

Sorgenti news:

- `demo` (mock): generate da `MockNewsProvider`, deterministiche per symbol, usate quando `ENABLE_REAL_NEWS=false`, quando la API key manca, quando il provider fallisce o il limite giornaliero e raggiunto.
- `cache`: la cache `api_cache` viene condivisa con i provider prezzo distinguendo `provider` e `endpoint`. Il TTL e definito da `NEWS_CACHE_TTL_HOURS`.
- `real`: news scaricate dal provider reale e salvate in `news_items` con sentiment, impact, relevance e raw payload.

Regole operative:

- nessuna chiamata automatica all'apertura della dashboard: il refresh news parte solo da `POST /news/refresh/{symbol}` o dalla pagina `News`;
- se `ENABLE_REAL_NEWS=false` il backend ricade su `mock_news` e mostra `News reali disattivate. Stai usando news demo/locali.`;
- se la API key Alpha Vantage manca, il backend ricade su `mock_news` e mostra `Provider news non configurato.`;
- se il limite giornaliero e raggiunto, il backend usa news locali e mostra `Limite news giornaliero raggiunto, uso news locali.`;
- le news vengono deduplicate per `url` (indice unico) e per coppia `title + published_at` quando l'url manca;
- le API key reali non vengono mai stampate nei log, nel frontend, nei test o in questa documentazione.

Sentiment euristico:

- `sentiment_label`: `POSITIVE`, `NEGATIVE`, `NEUTRAL`;
- `sentiment_score`: range `-1.0 ... +1.0`;
- `impact_level`: `LOW`, `MEDIUM`, `HIGH` (rafforzato da keyword critiche come `bankruptcy`, `earnings beat`, `lawsuit`, `guidance cut`);
- `relevance_score`: range `0 ... 100`;
- keyword positive: `earnings beat`, `revenue growth`, `raises guidance`, `upgrade`, `partnership`, `approval`, `buyback`, `dividend increase`;
- keyword negative: `earnings miss`, `revenue decline`, `lawsuit`, `downgrade`, `investigation`, `recall`, `bankruptcy`, `guidance cut`, `regulatory risk`.

News score nello scoring:

- `technical_score` resta invariato e visibile;
- `news_score` opzionale ricavato dall'aggregato news degli ultimi 7 giorni, limitato a `±NEWS_SENTIMENT_WEIGHT` punti (default ±5);
- `final_score = clamp(technical_score + news_score, 0, 100)`;
- se non ci sono news recenti `news_score = 0` e `final_score = technical_score`;
- i campi `technical_score`, `news_score`, `final_score`, `news_sentiment_label`, `news_impact_level`, `news_count` sono restituiti dall'endpoint `GET /technical-analysis/{symbol}`.

Variabili `.env` per le news:

```env
ENABLE_REAL_NEWS=false
NEWS_CACHE_TTL_HOURS=6
NEWS_DAILY_LIMIT=20
NEWS_SENTIMENT_WEIGHT=5
```

Endpoint news:

- `GET /news?limit=50&symbol=...` lista news recenti, opzionalmente filtrate per asset.
- `GET /news/{symbol}` news per asset.
- `POST /news/refresh/{symbol}?force=false` aggiorna le news del symbol rispettando cache e rate limit.
- `GET /news/sentiment/{symbol}?lookback_days=7` aggregato sentiment (count per classe, score medio, impatto, ultime 5 news).
- `GET /news/status` stato `enable_real_news`, provider, uso API news, cache, ultimo refresh.

Note finali sulle news:

- il sentiment e euristico e basato su keyword, non e una previsione certa ne sostituisce una valutazione fondamentale;
- non c'e scraping web: il provider reale chiama solo l'endpoint ufficiale Alpha Vantage News & Sentiment;
- la UI non si blocca se le news falliscono, mostra messaggi di fallback chiari.

## Universe Manager

InvestEdge non e limitato ai 25 asset seed. Il seed iniziale crea uno storico prezzi locale solo per 25 asset demo, ma il Universe Manager mantiene un universo investibile piu ampio e scalabile in `asset_universe`.

Livelli disponibili:

- `CORE`: asset principali sempre monitorati, default per training ML; lo statico iniziale contiene 75 asset.
- `EXTENDED`: asset importanti ma aggiornati meno spesso; lo statico iniziale contiene 256 asset.
- `CANDIDATE`: asset importati o disponibili per screening, aggiornati solo su richiesta; struttura pronta per 1000+ asset futuri.

File CSV statici:

- `data/universe/core_universe.csv`
- `data/universe/extended_universe.csv`
- `data/universe/crypto_universe.csv`
- `data/universe/etf_universe.csv`

Perche non si aggiorna tutto ogni volta:

- molte API gratuite o retail hanno limiti giornalieri stretti;
- aggiornare centinaia di asset a ogni apertura UI renderebbe instabile il sistema;
- `refresh-all` usa solo `get_refresh_candidates(limit)` e il default e 10 asset;
- la priorita favorisce asset in portafoglio, watchlist, CORE, segnali forti, news high impact, EXTENDED e infine CANDIDATE.

Relazioni operative:

- `Universe`: catalogo scalabile degli asset disponibili.
- `Watchlist`: mostra solo asset watchlisted o presenti in portafoglio.
- `Backtest`: puo selezionare da watchlist, CORE o EXTENDED, con limite pratico locale.
- `ML`: se non passi simboli a `/ml/train`, usa di default il `CORE_UNIVERSE` con storico prezzi disponibile.

Import CSV:

```http
POST /universe/import
{
  "file_name": "extended_universe.csv",
  "universe_level": "EXTENDED"
}
```

## Machine Learning leggero

Lo Step 8 aggiunge un modulo ML probabilistico e spiegabile. Il modello non sostituisce lo score tecnico: produce una probabilita operativa, una confidence e una spiegazione delle feature piu rilevanti.

Modelli supportati:

- `LOGISTIC_REGRESSION`: modello lineare interpretabile con coefficienti per feature.
- `RANDOM_FOREST`: modello ad alberi leggero con feature importances.

Target supportati:

- `POSITIVE_RETURN`: label 1 se il rendimento futuro a `horizon_days` e maggiore di 0.
- `OUTPERFORM_BENCHMARK`: label 1 se l'asset batte il benchmark, default `SPY`, sullo stesso orizzonte.
- `DRAWDOWN_RISK`: label 1 se nei prossimi `horizon_days` il drawdown scende sotto `-8%`.

Feature iniziali:

- tecniche: ritorni 1/5/20 giorni, volatilita 30 giorni, RSI, MACD, percentuale Bollinger, ATR, ADX, distanza da SMA50/SMA200, max drawdown recente e volume ratio;
- score esistenti: technical_score, trend, momentum, volatility, volume, support/resistance e risk penalty;
- news opzionali: sentiment 7 giorni, conteggi positive/negative/high impact;
- portafoglio opzionale: peso asset e raccomandazione corrente codificata.

Controlli anti look-ahead:

- ogni riga con data `T` usa solo prezzi e indicatori calcolabili fino a `T`;
- il target usa solo dati futuri `T + horizon_days`;
- lo split train/test e time-based;
- se `symbols` e vuoto, il training usa il `CORE_UNIVERSE` con dati prezzo disponibili;
- `EXTENDED_UNIVERSE` va selezionato esplicitamente e conviene limitarlo;
- il seed non addestra modelli automaticamente e resta veloce.

Differenza tra segnali:

- `technical_score`: lettura tecnica deterministica dell'asset;
- `news_score`: aggiustamento euristico basato su sentiment news;
- `ML prediction`: probabilita stimata da dati storici e feature, con confidence e spiegazione.

Avvertenza: il ML e sperimentale, non prevede il prezzo esatto, non garantisce rendimento e puo soffrire di overfitting. Va usato come supporto probabilistico insieme a score tecnico, news e risk management.

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
- `GET /backtests`
- `GET /backtests/{backtest_id}`
- `DELETE /backtests/{backtest_id}`
- `GET /data/status`
- `GET /data/status/{symbol}`
- `POST /data/refresh/{symbol}?force=false`
- `POST /data/refresh-all?limit=10&force=false`
- `GET /data/usage`
- `GET /universe`
- `GET /universe/summary`
- `POST /universe/import`
- `POST /universe/{symbol}/watchlist`
- `DELETE /universe/{symbol}/watchlist`
- `POST /universe/{symbol}/promote`
- `GET /universe/refresh-candidates`
- `GET /signals`
- `GET /signals/{symbol}`
- `GET /dashboard`
- `GET /news?limit=50&symbol=AAPL`
- `GET /news/{symbol}`
- `POST /news/refresh/{symbol}?force=false`
- `GET /news/sentiment/{symbol}?lookback_days=7`
- `GET /news/status`
- `GET /ml/status`
- `POST /ml/train`
- `GET /ml/models`
- `GET /ml/models/{model_id}`
- `POST /ml/predict/{symbol}`
- `POST /ml/predict-all`
- `GET /ml/predictions/{symbol}`
- `GET /ml/training-runs`
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

Esempio training ML:

```http
POST /ml/train
{
  "model_name": "InvestEdge logistic 14d",
  "model_type": "LOGISTIC_REGRESSION",
  "target_type": "POSITIVE_RETURN",
  "horizon_days": 14,
  "symbols": [],
  "benchmark_symbol": "SPY",
  "test_size_time_percent": 25,
  "min_samples": 200
}
```

Con `symbols: []` il backend usa il `CORE_UNIVERSE` filtrato agli asset con storico prezzi locale.

Esempio prediction ML:

```http
POST /ml/predict/AAPL
{
  "model_id": 1
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
npm.cmd run build
```

## Variabili ambiente

Copia `.env.example` in `.env` e modifica i valori se necessario. Per le chiavi reali usa preferibilmente `backend/.env`, che deve restare locale e non committato.

Il database SQLite viene creato automaticamente in `data/investedge.db` al primo avvio del backend. Se la UI mostra `Database non inizializzato`, esegui il comando seed sopra e ricarica il frontend.

## Prossime estensioni previste

- analisi scenario e confronti multi-strategia
- gestione capitale e pesi avanzata
- valutazione fondamentale opzionale a complemento dell'analisi tecnica
- integrazioni broker solo in una fase futura e solo se esplicitamente abilitate
