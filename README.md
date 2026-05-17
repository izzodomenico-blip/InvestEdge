# InvestEdge

InvestEdge e una web app locale per analisi investimenti su azioni, ETF, cripto e bond/ETF obbligazionari.

Questa fase crea uno scheletro tecnico funzionante con backend FastAPI, database SQLite e frontend React/Vite/TypeScript/Tailwind. Dashboard, Watchlist e Analisi Asset leggono dati seed dal backend; le altre aree restano predisposte per step successivi. Non include collegamenti reali a broker, ordini reali, machine learning, scraping non autorizzato o trading automatico.

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
python scripts\seed_database.py --reset
```

Lo script:

- crea le tabelle se non esistono
- rimuove i dati seed precedenti con `--reset`
- inserisce 25 asset tra azioni USA, ETF, cripto, bond ed ETF obbligazionari
- genera 2 anni di storico prezzi giornaliero
- calcola indicatori tecnici avanzati e segnali STRONG_BUY/BUY/HOLD/REDUCE/SELL

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

## Avvio backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
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
- `GET /signals`
- `GET /signals/{symbol}`
- `GET /dashboard`
- `POST /admin/seed?reset=true`

La documentazione interattiva FastAPI e disponibile su `http://127.0.0.1:8001/docs`.

## Avvio frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend locale: `http://127.0.0.1:5173`.

## Test

```powershell
python -m pytest
```

## Variabili ambiente

Copia `.env.example` in `.env` e modifica i valori se necessario.

Il database SQLite viene creato automaticamente in `data/investedge.db` al primo avvio del backend. Se la UI mostra `Database non inizializzato`, esegui il comando seed sopra e ricarica il frontend.

## Prossime estensioni previste

- provider dati autorizzati in `backend/app/data_providers`
- analisi tecnica in `backend/app/services/technical_analysis.py`
- scoring BUY/HOLD/REDUCE/SELL in `backend/app/services/scoring_engine.py`
- motore rischio, portafoglio, news, sentiment e backtest nei servizi dedicati
