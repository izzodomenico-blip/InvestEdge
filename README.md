# InvestEdge

InvestEdge e una web app locale per analisi investimenti su azioni, ETF, cripto e bond/ETF obbligazionari.

La fase attuale include backend FastAPI, database SQLite, frontend React/Vite/TypeScript/Tailwind, analisi tecnica avanzata, scoring spiegabile, portafoglio simulato, paper trading, backtest, integrazione dati reali opzionale con cache, news/sentiment, Universe Manager, Machine Learning leggero, System Audit & Data Quality, Strategy Control Center e Alert & Scheduler. Non include collegamenti reali a broker, ordini reali, deep learning, scraping non autorizzato o trading automatico.

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
- inizializza regole di alert di default
- con `--reset` inizializza un portafoglio demo da 100000 con ordini simulati su AAPL, MSFT, NVDA, BTC, ETH, SPY e QQQ

## Analisi tecnica

Il motore in `backend/app/services/technical_analysis.py` usa solo pandas e numpy. Gli indicatori disponibili includono medie, momentum (RSI, MACD), volatilita (Bollinger, ATR), trend (ADX, Ichimoku) e volumi.

## Paper trading e portafoglio

Il paper trading e completamente simulato: ogni BUY o SELL aggiorna solo SQLite e non invia ordini a broker reali. Include gestione cash, commissioni e analisi del rischio (concentrazione, esposizione cripto).

## Backtest Engine

Valida strategie su dati locali SQLite. Include strategie `SCORE_THRESHOLD`, `BUY_AND_HOLD` e `TOP_N_SCORE`. Produce metriche CAGR, Sharpe, Drawdown e Alpha vs Benchmark.

## Universe Manager

Gestisce un universo scalabile di asset suddiviso in `CORE` (principali), `EXTENDED` e `CANDIDATE`. Permette l'importazione da CSV e la promozione di livello degli asset.

## Machine Learning leggero

Modulo ML probabilistico (Logistic Regression, Random Forest) per stimare la probabilita di ritorni positivi o sovraperformance del benchmark, con spiegazione delle feature.

## System Audit & Data Quality (Step 9)

- **Data Quality**: Score 0-100 basato su completezza e freschezza.
- **Signal Validation**: Incrocio tra tecnica, ML, news e vincoli di portafoglio.
- **Operational Ranking**: BUY, WATCH, REDUCE o EXCLUDED.

## Strategy Control Center (Step 10)

Trasforma i ranking in piani operativi:
- **Pianificazione**: Modalità `CONSERVATIVE`, `BALANCED`, `AGGRESSIVE`.
- **Target Allocation**: Calcolo pesi ottimali e ordini proposti.
- **Paper Trading**: Esecuzione simulata del piano sul portafoglio.

## Alert & Scheduler (Step 11)

Sistema di monitoraggio e reporting:
- **Alert Center**: Notifiche su cambi segnale, qualità dati bassa, concentrazione rischio o news critiche.
- **Scheduler Operations**: Cicli manuali di aggiornamento dati, ricalcolo ranking e valutazione alert.
- **Operational Reports**: Generazione di report sintetici (Daily/Weekly) in formato Markdown con stato sistema e portafoglio.

## Portfolio Optimizer & Rebalancing (Step 12)

Il **Portfolio Optimizer** aiuta a costruire un portafoglio target e ribilanciare quello attuale.
- **Strategie**: `EQUAL_WEIGHT`, `SCORE_WEIGHTED`, `RISK_ADJUSTED`, `CONSERVATIVE`, `AGGRESSIVE`.
- **Ribilanciamento**: Confronta l'allocazione attuale con quella target e genera ordini di acquisto/vendita simulati.
- **Vincoli**: Rispetta limiti di peso per asset, classi di attività e riserva di cash.

Differenza tra Strategy Plan e Optimization:
- **Strategy Plan**: Piano operativo focalizzato sui nuovi segnali e candidati `BUY`.
- **Portfolio Optimization**: Analisi globale del portafoglio per allineare tutti i pesi a un modello teorico ottimale.

## Scenario Analysis & Stress Test (Step 13)

Il modulo di **Scenario Analysis** permette di simulare l'impatto di shock estremi sul portafoglio.
- **Preset Scenari**: `MARKET_CRASH`, `TECH_SELL_OFF`, `CRYPTO_CRASH`, `RECESSION`, `BULL_RALLY`.
- **Shock Custom**: Possibilità di definire shock percentuali per asset class o per singolo simbolo.
- **Analisi Rischio**: Calcola la perdita stimata, il contributo di ogni asset alla perdita e il livello di rischio (LOW, MEDIUM, HIGH, EXTREME).
- **Suggerimenti**: Genera azioni di mitigazione basate sull'impatto simulato (es. ridurre asset concentrati, aumentare cash).

### Routine Giornaliera Consigliata
1. **Scheduler**: Esegui ciclo `ALERTS + QUALITY` per verificare lo stato.
2. **Alert Center**: Controlla nuovi alert critici.
3. **Operational Ranking**: Verifica nuovi candidati `BUY` validati.
4. **Strategy Center**: Genera un piano aggiornato se necessario.
5. **Reports**: Genera report giornaliero per tracciare lo storico.

## Avvio backend

```powershell
backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8001
```

## Avvio frontend

```powershell
cd frontend
npm run dev
```

## Test

```powershell
backend\.venv\Scripts\python.exe -m pytest
```

## Safety Note
InvestEdge è uno strumento di simulazione. **Non collega broker reali e non esegue trade reali.** Tutti i dati e gli ordini sono strettamente per scopi di analisi e paper trading locale.
