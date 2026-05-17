# InvestEdge

InvestEdge e una web app locale per analisi investimenti su azioni, ETF, cripto e bond/ETF obbligazionari.

Questa prima fase crea lo scheletro tecnico funzionante con backend FastAPI, database SQLite e frontend React/Vite/TypeScript/Tailwind con dati mock. Non include collegamenti reali a broker, ordini reali, machine learning, scraping non autorizzato o trading automatico.

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

## Avvio backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Endpoint iniziali:

- `GET /health`
- `GET /assets`
- `POST /assets`
- `GET /portfolio`
- `GET /signals`
- `GET /dashboard`

La documentazione interattiva FastAPI e disponibile su `http://127.0.0.1:8000/docs`.

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

Il database SQLite viene creato automaticamente in `data/investedge.db` al primo avvio del backend.

## Prossime estensioni previste

- provider dati autorizzati in `backend/app/data_providers`
- analisi tecnica in `backend/app/services/technical_analysis.py`
- scoring BUY/HOLD/REDUCE/SELL in `backend/app/services/scoring_engine.py`
- motore rischio, portafoglio, news, sentiment e backtest nei servizi dedicati
