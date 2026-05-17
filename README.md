# InvestEdge

InvestEdge e una web app locale per analisi investimenti su azioni, ETF, cripto e bond/ETF obbligazionari.

La fase attuale include backend FastAPI, database SQLite, frontend React/Vite/TypeScript/Tailwind, analisi tecnica avanzata, scoring spiegabile, portafoglio simulato e paper trading. Non include collegamenti reali a broker, ordini reali, machine learning, scraping non autorizzato o trading automatico.

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

## Variabili ambiente

Copia `.env.example` in `.env` e modifica i valori se necessario.

Il database SQLite viene creato automaticamente in `data/investedge.db` al primo avvio del backend. Se la UI mostra `Database non inizializzato`, esegui il comando seed sopra e ricarica il frontend.

## Prossime estensioni previste

- provider dati autorizzati in `backend/app/data_providers`
- news e sentiment reali tramite provider autorizzati
- analisi scenario e confronti multi-strategia
- gestione capitale e pesi avanzata
- integrazioni broker solo in una fase futura e solo se esplicitamente abilitate
