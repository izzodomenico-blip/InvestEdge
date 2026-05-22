# InvestEdge

InvestEdge e una web app locale per analisi investimenti su azioni, ETF, cripto e bond/ETF obbligazionari.

La fase attuale include backend FastAPI, database SQLite, frontend React/Vite/TypeScript/Tailwind, analisi tecnica avanzata, scoring spiegabile, portafoglio simulato, paper trading, backtest, integrazione dati reali opzionale con cache, news/sentiment, Universe Manager, Machine Learning leggero, System Audit & Data Quality, Strategy Control Center, Alert & Scheduler, Portfolio Optimizer, Scenario Analysis, Backup & Data Management, User Settings, Tax Center e Google Sheets Import (read-only). Non include collegamenti reali a broker, ordini reali, deep learning, scraping non autorizzato o trading automatico.

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

- **Strategie**: `EQUAL_WEIGHT`, `SCORE_WEIGHTED`, `RISK_ADJUSTED`.
- **Ribilanciamento**: Confronta l'allocazione attuale con quella target e genera ordini simulati.

## Scenario Analysis & Stress Test (Step 13)

- **Preset Scenari**: `MARKET_CRASH`, `TECH_SELL_OFF`, `CRYPTO_CRASH`, `RECESSION`, `BULL_RALLY`.
- **Analisi Rischio**: Calcola la perdita stimata e suggerisce mitigazioni.

## Backup & Data Management (Step 15)

- **Backup & Restore**: Crea snapshot completi del database con checksum.
- **Data Export/Import**: Esportazione ed importazione di dataset in formato CSV o JSON.
- **Project Hardening**: Audit di sicurezza per file sensibili e integrità del database.

## User Settings & Profiles (Step 16)

InvestEdge si adatta al profilo dell'utente:
- **Risk Profiles**: Definisce i vincoli di rischio per le modalità `CONSERVATIVE`, `BALANCED` e `AGGRESSIVE`. Controlla pesi massimi, esposizione crypto e influenza di ML/News.
- **Strategy Profiles**: Configura i parametri operativi per il ranking e l'optimizer (soglie BUY/SELL, frequenza ribilanciamento, stop loss).
- **Personalizzazione Operativa**: Il sistema adatta automaticamente la validazione dei segnali e i piani strategici al profilo attivo.
- **Notifiche & UI**: Gestione centralizzata delle preferenze di avviso e dell'interfaccia.

## Tax Center / Fiscal Simulator (Step 18)

Simulatore fiscale **teorico** su ordini paper e portafogli simulati (focus iniziale Italia semplificata):

- Plusvalenze/minusvalenze realizzate, P/L non realizzato, imposta teorica su capital gain (default **26%** regime `ITALY_SIMPLIFIED`)
- Lot matching **FIFO** semplificato (fees opzionali nel cost basis)
- Report annuale per portafoglio o **GLOBAL** multi-portfolio
- Export report fiscale **CSV/JSON**
- Riepiloghi per asset class, simbolo e anno fiscale

**Disclaimer:** simulazione indicativa. Non sostituisce commercialista o normativa fiscale ufficiale. Non genera dichiarazioni ufficiali.

**Limitazioni v1:** dividendi non implementati; cripto/obbligazioni solo placeholder/warning; LIFO/AVG_COST non ancora operativi (solo FIFO).

**Endpoint principali:** `GET/PUT /tax/settings`, `GET /tax/summary`, `GET /tax/summary/global`, `GET /tax/lots`, `GET /tax/realized-events`, `POST /tax/recalculate`, `POST /tax/report/generate`, `GET /tax/reports`, `POST /tax/export`.

**UI:** pagina `/tax` (Tax Center) con impostazioni, summary, lots, eventi, report ed export.

## Google Sheets API Read-Only Import (Step 19)

InvestEdge supporta l'integrazione con Google Fogli per sincronizzare tracker esterni in modalità **Sola Lettura**:
- **Tracker Sincronizzato**: Importa posizioni, transazioni storiche, liquidità e watchlist da un Google Sheet.
- **Portafogli READ_ONLY**: Crea portafogli speciali di tipo `EXTERNAL_TRACKER` che riflettono lo stato del tracker reale (senza permettere ordini manuali diretti).
- **OAuth Desktop Auth**: Utilizza il flusso OAuth 2.0 per applicazioni Desktop (non richiede Service Account).
- **Template Flessibile**: Supporta tab `PORTFOLIO`, `TRANSACTIONS`, `CASH` e `WATCHLIST`.

### Configurazione Rapida
1. Ottieni un file `credentials.json` (OAuth Client ID Desktop) dalla Google Cloud Console.
2. Salvalo in `backend/secrets/google_oauth_credentials.json`.
3. Inserisci lo `SPREADSHEET_ID` nel file `.env`.
4. Vai alla pagina **Google Sheets Import** nel frontend e clicca su **Autorizza**.

## Multi-Portfolio Simulation (Step 17)

InvestEdge ora supporta la simulazione di più portafogli simultaneamente:
- **Portafogli Indipendenti**: Crea diversi account per testare strategie diverse (es. uno conservativo per ETF, uno speculativo per Crypto).
- **Context Switching**: Cambia rapidamente il portafoglio attivo dal selettore globale; tutte le pagine (Dashboard, Simulator, Strategy, etc.) mostreranno i dati relativi al portafoglio selezionato.
- **Vista Consolidata**: Visualizza un riepilogo aggregato di tutti i portafogli per monitorare l'esposizione totale e il P/L complessivo.
- **Profilo di Rischio per Portafoglio**: Ogni portafoglio può essere collegato a un profilo di rischio e a una strategia specifica.
- **Trasferimenti Interni**: Simula lo spostamento di liquidità tra portafogli o depositi/prelievi esterni.

### Routine Giornaliera Consigliata
1. **Backup**: Crea un backup prima di operazioni massive.
2. **Scheduler**: Esegui ciclo `ALERTS + QUALITY` per verificare lo stato.
3. **Alert Center**: Controlla nuovi alert critici.
4. **Operational Ranking**: Verifica nuovi candidati `BUY` validati.
5. **Strategy/Optimizer**: Genera un piano aggiornato o ottimizza i pesi.
6. **Reports**: Genera report giornaliero per tracciare lo storico.

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
