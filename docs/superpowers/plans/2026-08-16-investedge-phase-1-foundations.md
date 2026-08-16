# InvestEdge Phase 1 Reliability Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare i difetti critici emersi dall'audit e consegnare una base locale Windows sicura, contabilmente coerente e verificata, senza ancora introdurre portafogli multipli, strategie automatiche o il redesign a cinque hub.

**Architecture:** La fase mantiene l'architettura FastAPI + SQLite + React esistente, aggiunge un confine esplicito per i cambi in valuta base EUR e rende fail-closed le operazioni distruttive o dipendenti da dati mancanti. Ogni pacchetto è eseguito in una nuova task Codex, in ordine strettamente sequenziale, con test prima del codice, commit atomico e push verificato prima del pacchetto successivo.

**Tech Stack:** Python 3.11/3.12, FastAPI, SQLite, httpx, pandas/scikit-learn, pytest, Ruff, React 18, TypeScript, Vite, Tailwind CSS, Docker Compose, PowerShell, Git/GitHub.

## Global Constraints

- Specifica approvata: `docs/superpowers/specs/2026-08-16-investedge-broker-grade-redesign-design.md`.
- Branch di integrazione iniziale: `codex/investedge-phase-1-foundations`, creato dal commit che contiene questo piano e pubblicato su `origin`.
- Nessun ordine reale, scraping di Trade Republic, automazione della sua UI, credenziale broker o promessa di rendimento.
- Trade Republic resta futuro, ufficiale, disabilitato e fail-closed. Questa fase riguarda esclusivamente analisi e paper trading.
- Compatibilità: preservare route e formati esistenti salvo i cambi di sicurezza documentati (`/admin/seed` rimosso e cancellazione asset protetta).
- SQLite è la fonte di verità. Ogni modifica di schema deve funzionare sia su database nuovo sia su fixture legacy incomplete.
- Tutti i valori consolidati del portafoglio sono in EUR. I valori nativi restano disponibili e sono etichettati; se manca un cambio, il calcolo consolidato deve fallire con un errore comprensibile, non sommare divise.
- La fiscalità resta una stima indicativa. Le regole codificate devono citare fonti ufficiali e non attribuire automaticamente il 12,5% a tutti gli ETF obbligazionari.
- Non usare `npm audit fix --force`, force-push, push diretto su `main`, reset distruttivi o cancellazioni ricorsive.
- Prima di ogni Task: `git status --short`, `git log -1 --oneline`, lettura del blocco Task e delle aree chiamanti.
- Dopo ogni Task: test mirati, Ruff/build pertinenti, review del diff, commit singolo e push del branch corrente.
- Il passaggio al Task successivo è vietato se test, commit o push falliscono.

## Protocollo automatico: una nuova chat per ogni Task

Il termine “Task” in questo documento indica un pacchetto coerente e revisionabile, non ogni micro-comando TDD.

1. Una task orchestratrice legge questo piano e apre una nuova task Codex per il primo Task non completato.
2. La nuova task parte dal branch remoto prodotto dal Task precedente, in un worktree isolato.
3. Il prompt include: percorso della specifica, percorso del piano, numero Task, commit di partenza, branch/ref di partenza, comandi di verifica e vincolo di non eseguire Task successivi.
4. L'esecutore usa `superpowers:test-driven-development`; per bug riprodotti usa anche `superpowers:systematic-debugging`; prima di dichiarare completato usa `superpowers:verification-before-completion`.
5. L'esecutore aggiorna le checkbox del proprio Task, committa tutto con il messaggio indicato e pubblica il branch corrente con `git push -u origin HEAD`.
6. L'orchestratore attende la conclusione, verifica che `git status` sia pulito, legge test e diff, controlla che il commit remoto coincida con `HEAD`, quindi usa quel branch/ref come base del Task seguente.
7. Se un controllo fallisce, l'orchestratore invia la correzione nella stessa task; non apre un'altra task finché il gate non è verde.
8. Al completamento, la task viene lasciata consultabile con un riepilogo; l'archiviazione automatica avviene solo dopo che il suo commit è stato verificato nel ramo successivo.
9. Il Task 11 produce il branch finale lineare e un report. Il merge in `main` o l'apertura di una PR richiede una decisione separata.

---

### Task 1: Rendere locale il runtime e aggiornare la toolchain frontend vulnerabile

**Files:**

- Modify: `docker-compose.yml`
- Modify: `frontend/src/lib/api.ts`
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/routes.py`
- Modify: `README.md`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Test: `tests/test_config.py`

**Contract:** Docker pubblica backend e frontend soltanto su loopback; il frontend usa sempre `VITE_API_BASE_URL` e la porta backend 8000; le variabili già presenti nel processo hanno precedenza sui file `.env`; l'API HTTP di seed non esiste più; `npm audit` non riporta vulnerabilità high o critical.

- [x] **Step 1: Scrivere i test/config check che descrivono il comportamento corretto**

Creare `tests/test_config.py` con test su `Settings.from_env()` che dimostrino che `INVESTEDGE_DB_PATH`, `INVESTEDGE_ENV` e `INVESTEDGE_CORS_ORIGINS` impostati nel processo vengono rispettati. Aggiungere un test route che verifichi `POST /admin/seed?reset=true == 404` in `tests/test_api.py`.

- [x] **Step 2: Eseguire i test e osservare il fallimento della route seed**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_config.py tests\test_api.py -k "config or admin_seed"
```

Expected: il test `/admin/seed` fallisce perché la route è ancora esposta.

- [x] **Step 3: Correggere binding, variabili e precedenza `.env`**

Applicare esattamente questi comportamenti:

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

```yaml
ports:
  - "127.0.0.1:5173:5173"
environment:
  VITE_API_BASE_URL: http://127.0.0.1:8000
```

In `frontend/src/lib/api.ts`, cambiare soltanto il fallback DEV da `http://127.0.0.1:8001` a `http://127.0.0.1:8000`.

In `backend/app/config.py`, caricare entrambi i file con `override=False`; l'ambiente del processo deve vincere anche su `backend/.env`.

- [x] **Step 4: Rimuovere l'endpoint seed distruttivo**

Eliminare da `routes.py` l'import HTTP-only di `seed_database` e la route `POST /admin/seed`. Conservare gli script CLI `scripts/seed_database.py` e `backend/scripts/seed_database.py`. Aggiornare l'elenco API nel README.

- [x] **Step 5: Aggiornare dipendenze frontend senza force**

Usare versioni fisse compatibili con Node 22.12+:

```powershell
npm install react-router-dom@7.18.2
npm install --save-dev vite@7.3.6 @vitejs/plugin-react@5.2.0 postcss@8.5.26
```

Correggere soltanto le incompatibilità di API effettivamente rilevate dal build. Non migrare l'architettura delle route.

- [x] **Step 6: Verificare Task 1**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_config.py tests\test_api.py -k "config or admin_seed or health"
backend\.venv\Scripts\python.exe -m ruff check backend tests
npm run build
npm audit --audit-level=high
docker compose config
```

Expected: tutti verdi; audit senza high/critical. Le moderate residue, se non risolvibili senza migrazioni estranee, vanno motivate nel report del Task.

- [x] **Step 7: Commit e push**

```powershell
git add docker-compose.yml frontend/src/lib/api.ts frontend/package.json frontend/package-lock.json backend/app/config.py backend/app/api/routes.py README.md tests/test_config.py tests/test_api.py
git commit -m "fix: harden local runtime and frontend toolchain"
git push -u origin HEAD
```

---

### Task 2: Rendere migrazioni e backup di avvio recuperabili

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/backup_service.py`
- Test: `tests/test_database.py`
- Test: `tests/test_api.py`

**Contract:** Un database legacy riceve prima un backup consistente, poi le colonne mancanti, infine gli indici che le usano. Un backup fallito su un DB esistente blocca la migrazione; un DB inesistente può inizializzarsi senza backup.

- [x] **Step 1: Riprodurre la migrazione legacy che oggi fallisce**

In `tests/test_database.py`, creare un file SQLite con tabelle legacy `signals`, `simulated_orders`, `news_items` e `api_cache` prive delle colonne moderne ma con dati sentinella. Chiamare `init_db()` tramite `INVESTEDGE_DB_PATH` temporaneo e verificare:

```python
assert "created_at" in table_columns(connection, "signals")
assert "order_date" in table_columns(connection, "simulated_orders")
assert connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
```

- [x] **Step 2: Eseguire il test e confermare `no such column` durante la creazione indice**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_database.py -k legacy -vv
```

- [x] **Step 3: Separare schema base e indici post-migrazione**

In `database.py` definire:

```python
BASE_SCHEMA = """...tutte le CREATE TABLE, nessun CREATE INDEX..."""
INDEX_SCHEMA = """...tutti i CREATE INDEX IF NOT EXISTS..."""
SCHEMA = BASE_SCHEMA + INDEX_SCHEMA
```

`SCHEMA` resta disponibile per i test in-memory esistenti. `init_db()` deve invece eseguire in quest'ordine:

```python
connection.executescript(BASE_SCHEMA)
migrate_db(connection)
connection.executescript(INDEX_SCHEMA)
```

Rimuovere da `migrate_db()` le duplicazioni di indici trasferite in `INDEX_SCHEMA`.

- [x] **Step 4: Rendere esplicito il backup pre-migrazione**

Sostituire il best-effort silenzioso con:

```python
def backup_before_migration() -> dict[str, Any]:
    return create_backup(reason="pre-migration")
```

Nel lifespan, fuori dai test:

```python
backup_before_migration()
init_db()
```

Se il DB non esiste, `create_backup` restituisce `created=False`; se esiste e SQLite backup fallisce, propagare l'errore e non migrare. Non cancellare automaticamente backup in caso di errore.

- [x] **Step 5: Testare ordine, backup e failure mode**

Aggiungere test con monkeypatch/spie che verifichino `backup -> init`, più un test in cui il backup solleva e `init_db` non viene chiamato.

- [x] **Step 6: Verificare Task 2**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_database.py tests\test_api.py -k "legacy or backup or health"
backend\.venv\Scripts\python.exe -m ruff check backend tests
```

- [x] **Step 7: Commit e push**

```powershell
git add backend/app/database.py backend/app/main.py backend/app/services/backup_service.py tests/test_database.py tests/test_api.py
git commit -m "fix: back up before safe legacy migrations"
git push -u origin HEAD
```

---

### Task 3: Bloccare cancellazioni asset implicite e rendere esplicito il purge

**Files:**

- Modify: `backend/app/services/assets_service.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/models/schemas.py`
- Test: `tests/test_api.py`

**Contract:** `DELETE /assets/{symbol}` elimina direttamente solo asset senza dipendenze. Se esistono prezzi, posizioni, ordini, segnali o news collegate, restituisce 409. Il purge richiede `purge=true`, `confirm_symbol` esatto e backup riuscito.

- [ ] **Step 1: Aggiungere test di regressione della cascade**

I test devono coprire:

- asset inutilizzato: 200 e cancellato;
- asset seed con dipendenze: 409 e dati invariati;
- purge senza conferma esatta: 400;
- purge con conferma: backup chiamato, 200, dipendenze eliminate;
- backup che fallisce: 500/503 e asset invariato.

- [ ] **Step 2: Dimostrare il fallimento attuale**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_api.py -k "remove_asset or purge_asset" -vv
```

- [ ] **Step 3: Implementare conteggio dipendenze e purge protetto**

In `assets_service.py` aggiungere una funzione sola lettura:

```python
def asset_dependency_counts(connection: sqlite3.Connection, asset_id: int) -> dict[str, int]:
    ...
```

Contare almeno `price_history`, `portfolio_positions`, `simulated_orders`, `signals`, `news_items`. Non usare introspezione SQL dinamica da input utente.

La route accetta:

```python
purge: bool = Query(default=False)
confirm_symbol: str | None = Query(default=None)
```

Prima del purge chiamare `create_backup(reason=f"pre-asset-purge-{symbol.upper()}")` e richiedere `created=True`. Il DELETE rimane nella transazione della route.

- [ ] **Step 4: Verificare Task 3**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_api.py -k "remove_asset or purge_asset or backup"
backend\.venv\Scripts\python.exe -m ruff check backend tests
```

- [ ] **Step 5: Commit e push**

```powershell
git add backend/app/services/assets_service.py backend/app/api/routes.py backend/app/models/schemas.py tests/test_api.py
git commit -m "fix: guard destructive asset deletion"
git push -u origin HEAD
```

---

### Task 4: Introdurre cambi EUR tracciabili e una sorgente BCE gratuita

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Create: `backend/app/services/fx_service.py`
- Modify: `backend/scripts/seed_database.py`
- Modify: `.env.example`
- Test: `tests/test_fx_service.py`
- Test: `tests/test_database.py`

**Contract:** Il cambio rappresenta quante unità EUR valgono una unità della valuta nativa. EUR/EUR vale 1. I cambi diversi da 1 conservano provider, data osservata, ingestione e quality. Mancanza o staleness non produce mai un fallback numerico inventato.

- [ ] **Step 1: Scrivere test unitari per diretto, inverso, cache e assenza**

Definire l'interfaccia pubblica:

```python
class FXRateUnavailable(ValueError): ...

@dataclass(frozen=True)
class FXQuote:
    from_currency: str
    to_currency: str
    rate: float
    observed_at: str
    provider: str
    quality: str

class FXService:
    def get_rate(self, connection, from_currency: str, to_currency: str = "EUR") -> FXQuote: ...
    def refresh_ecb(self, connection, client: httpx.Client | None = None) -> int: ...
```

Usare fixture XML registrate nel test; nessuna chiamata internet in pytest.

- [ ] **Step 2: Aggiungere schema `fx_rates` dopo aver visto fallire i test**

```sql
CREATE TABLE IF NOT EXISTS fx_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_currency TEXT NOT NULL,
    to_currency TEXT NOT NULL,
    rate REAL NOT NULL CHECK(rate > 0),
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    provider TEXT NOT NULL,
    quality TEXT NOT NULL,
    UNIQUE(from_currency, to_currency, observed_at, provider)
);
```

Aggiungere indice su `(from_currency, to_currency, observed_at)` in `INDEX_SCHEMA`.

- [ ] **Step 3: Implementare provider BCE limitato e sicuro**

Usare solo `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`, timeout distinti connect/read, limite risposta 1 MiB, status check e parser XML standard senza entità esterne. I reference rate BCE sono giornalieri e informativi: salvare `quality="reference"`, non `realtime`.

Dato che il feed esprime `1 EUR = N valuta`, memorizzare il reciproco come `valuta -> EUR`.

- [ ] **Step 4: Rendere esplicito il seed FX**

Il seed deve inserire un cambio sintetico USD/EUR deterministico marcato `provider="seed"`, `quality="seed"`; non presentarlo come BCE o dato reale. Non inserire cambi per valute sconosciute.

- [ ] **Step 5: Aggiungere configurazione minima**

In `Settings` e `.env.example` aggiungere soltanto:

```text
ECB_FX_MAX_AGE_DAYS=7
```

Il servizio deve poter distinguere un cambio stale; il blocco operativo verrà usato nel Task 5.

- [ ] **Step 6: Verificare Task 4**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_fx_service.py tests\test_database.py
backend\.venv\Scripts\python.exe -m ruff check backend tests
```

- [ ] **Step 7: Commit e push**

```powershell
git add backend/app/database.py backend/app/config.py backend/app/services/fx_service.py backend/scripts/seed_database.py .env.example tests/test_fx_service.py tests/test_database.py
git commit -m "feat: add traceable EUR exchange rates"
git push -u origin HEAD
```

---

### Task 5: Correggere la contabilità multivaluta del portafoglio esistente

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/services/portfolio_engine.py`
- Modify: `backend/app/services/scenario_service.py`
- Modify: `backend/app/services/report_service.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/PortfolioPage.tsx`
- Test: `tests/test_portfolio_accounting.py`
- Test: `tests/test_api.py`

**Contract:** Prezzo, valore e P/L nativi restano separati dagli equivalenti EUR. Cash, riepilogo, pesi, rischio, scenario e snapshot usano soltanto valori EUR. Ogni ordine congela il cambio usato; un cambio mancante/stale blocca l'ordine.

- [ ] **Step 1: Scrivere una matrice di test finanziari**

Copertura minima con cambio USD/EUR = 0,80:

```text
BUY 10 AAPL @ 100 USD = 800 EUR di controvalore
cash 10.000 EUR -> 9.200 EUR (fee zero)
mark 110 USD -> valore nativo 1.100 USD, valore base 880 EUR
P/L nativo 100 USD, P/L base 80 EUR
```

Testare anche SELL, short, fee in valuta nativa, cambio mancante, cambio stale e portafoglio misto AAPL USD + VWCE EUR.

- [ ] **Step 2: Estendere schema e modelli mantenendo i campi nativi**

Aggiungere a `portfolio_positions`:

```text
fx_rate_to_base, average_price_base, invested_amount_base, current_value_base,
realized_pnl_base, unrealized_pnl_base
```

Aggiungere a `simulated_orders`:

```text
currency, fx_rate_to_base, gross_amount_base, net_amount_base, fees_base
```

I campi esistenti `invested_amount`, `current_value`, `realized_pnl`, `unrealized_pnl`, `gross_amount`, `net_amount` rimangono nativi per compatibilità. `average_price_base` è la base di costo media EUR del lotto corrente e permette di realizzare correttamente P/L base anche quando il cambio varia tra apertura e chiusura. Le risposte API espongono i nuovi campi e `base_currency="EUR"`.

- [ ] **Step 3: Convertire una volta nel confine ordine/refresh**

In `simulate_order`, ottenere un `FXQuote` prima di verificare il cash. Salvare il rate nell'ordine e applicare cash/fee in EUR. In `refresh_portfolio`, valorizzare campi nativi e base, sommare soltanto `*_base` e calcolare i pesi sui valori base assoluti.

Non usare il cambio corrente per riscrivere il P/L realizzato storico: gli ordini conservano il rate di esecuzione.

- [ ] **Step 4: Aggiornare scenari, report e UI**

`scenario_service` usa `current_value_base`; `report_service` esporta colonne native, valuta, cambio e EUR. `PortfolioPage` mantiene prezzo/valore nativo per posizione e mostra accanto “Equivalente EUR”; i KPI consolidati restano EUR.

- [ ] **Step 5: Verificare Task 5**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_portfolio_accounting.py tests\test_api.py -k "portfolio or order or scenario or report"
backend\.venv\Scripts\python.exe -m ruff check backend tests
npm run build
```

- [ ] **Step 6: Commit e push**

```powershell
git add backend/app/database.py backend/app/models/schemas.py backend/app/services/portfolio_engine.py backend/app/services/scenario_service.py backend/app/services/report_service.py frontend/src/lib/api.ts frontend/src/pages/PortfolioPage.tsx tests/test_portfolio_accounting.py tests/test_api.py
git commit -m "fix: account for portfolio values in EUR"
git push -u origin HEAD
```

---

### Task 6: Rendere sicuro l'import Google Sheets e impedire creazione di capitale

**Files:**

- Modify: `backend/app/config.py`
- Modify: `backend/app/services/google_sheets_import_service.py`
- Modify: `backend/app/services/portfolio_engine.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `.env.example`
- Test: `tests/test_import_security.py`
- Test: `tests/test_api.py`

**Contract:** L'import funziona solo con flag attivo, URL HTTPS Google Sheets fidati, redirect nuovamente validati, massimo 5 MiB e messaggi sanitizzati. Preview e apply usano gli stessi dati. Apply sostituisce posizioni e imposta coerentemente capitale iniziale/cash in una transazione.

- [ ] **Step 1: Scrivere test SSRF e flag**

Testare almeno:

- flag false -> 403 per preview e apply, anche con URL valido;
- `http://`, localhost, IP privati, userinfo e host simili a Google -> rifiutati;
- `https://docs.google.com/spreadsheets/.../export?format=csv` -> accettato;
- redirect verso host non ammesso -> rifiutato;
- redirect Google consentito -> seguito fino a massimo 3;
- body > 5 MiB -> rifiutato;
- timeout/HTTP error -> messaggio senza URL, query, token o eccezione raw.

- [ ] **Step 2: Implementare validatore e download streaming**

Consentire host esatti `docs.google.com`, `drive.google.com` e sottodomini Google-owned che terminano in `.googleusercontent.com`; schema solo HTTPS, porta assente o 443, niente username/password. Usare `follow_redirects=False` e validare ogni `Location` assoluta/relativa prima della richiesta seguente.

Configurare:

```text
GOOGLE_SHEETS_IMPORT_MAX_BYTES=5242880
```

Leggere in streaming e interrompere appena superato il limite.

- [ ] **Step 3: Rendere la sostituzione economicamente esplicita**

Cambiare la firma in:

```python
def replace_positions(
    connection,
    items,
    *,
    initial_equity_base: float,
    current_cash_base: float,
) -> PortfolioSummaryOut:
```

L'apply allocation passa `total_capital` e `cash_buffer`. L'import passa come `initial_equity_base` la somma dei costi base delle posizioni importate e `current_cash_base=0`. Aggiornare `portfolio_settings.initial_cash/current_cash` nello stesso savepoint del DELETE/INSERT.

- [ ] **Step 4: Verificare rollback totale**

Aggiungere un test che forza errore sulla seconda posizione e dimostra che posizioni, asset creati e settings precedenti sono invariati.

- [ ] **Step 5: Verificare Task 6**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_import_security.py tests\test_api.py -k "import or allocation_apply or replace"
backend\.venv\Scripts\python.exe -m ruff check backend tests
```

- [ ] **Step 6: Commit e push**

```powershell
git add backend/app/config.py backend/app/services/google_sheets_import_service.py backend/app/services/portfolio_engine.py backend/app/api/routes.py backend/app/models/schemas.py .env.example tests/test_import_security.py tests/test_api.py
git commit -m "fix: secure imports and preserve portfolio capital"
git push -u origin HEAD
```

---

### Task 7: Correggere short negli scenari e nella stima fiscale

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/scripts/seed_database.py`
- Modify: `backend/app/services/scenario_service.py`
- Modify: `backend/app/services/tax_service.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/TaxPage.tsx`
- Test: `tests/test_engines.py`
- Test: `tests/test_api.py`

**Contract:** Uno short conserva valore firmato negli stress test; SELL può aprire un lotto short e BUY può chiuderlo realizzando P/L; le minusvalenze scadono dopo il quarto periodo successivo; le aliquote dipendono da categoria fiscale esplicita e anno.

- [ ] **Step 1: Scrivere test short e scadenze**

Testare:

- short -10 @ 100, mark/scenario +20% -> passività da -1.000 a -1.200 e impatto -200;
- short -10 @ 100, cover @ 80 -> utile realizzato, evento fiscale;
- short -10 @ 100, cover @ 120 -> perdita;
- flip long -> short e short -> long con fee proporzionate;
- perdita 2020 non usata nel 2025, perdita 2021 usabile nel 2025;
- `bond_etf` standard se non ha categoria governativa esplicita;
- crypto 2025 al 26% e 2026 al 33%.

- [ ] **Step 2: Correggere scenario firmato**

Sostituire `max(0.0, current_value + impact)` con il valore firmato `current_value + impact`. Per le percentuali di classe usare un denominatore assoluto quando il valore è negativo; non etichettare un guadagno short come “perdita”.

- [ ] **Step 3: Aggiungere categoria fiscale esplicita**

Aggiungere `assets.tax_category TEXT NOT NULL DEFAULT 'standard'`. Valori iniziali ammessi: `standard`, `government_bond`, `crypto`, `euro_emt`. Il seed marca BTP come `government_bond`, crypto come `crypto`; gli ETF obbligazionari restano `standard` finché manca una quota governativa verificata.

Usare regole versionate per anno:

```python
STANDARD_RATE = 26.0
GOVERNMENT_BOND_RATE = 12.5
CRYPTO_RATE_BY_YEAR = ((2026, 33.0), (0, 26.0))
```

Fonti da citare nel codice/documentazione:

- art. 3 D.L. 66/2014 per 26% ed eccezioni titoli pubblici: <https://www.normattiva.it/uri-res/N2Ls?urn%3Anir%3Astato%3Adecreto.legge%3A2014-04-24%3B66~art3=>;
- art. 1 comma 24 L. 207/2024 per cripto 33% dal 2026: <https://www.normattiva.it/atto/caricaDettaglioAtto?atto.codiceRedazionale=24G00229>;
- art. 68 TUIR per riporto non oltre il quarto periodo: <https://www.normattiva.it/uri-res/N2Ls?urn%3Anir%3Apresidente.repubblica%3Adecreto%3A1986-12-22%3B917~art68-com6=>.

- [ ] **Step 4: Implementare lotti firmati senza fingere consulenza fiscale**

Conservare il metodo esistente come `SIMPLIFIED_FIFO` nel report. SELL chiude prima lotti long e apre un lotto short per l'eccedenza; BUY chiude prima short e apre long per l'eccedenza. Ogni evento conserva `open_side`, `close_side`, `realization_date`, valori nativi/base e aliquota applicata, usando i cambi congelati negli ordini dal Task 5 e mai il cambio corrente. Mantenere alias di risposta compatibili solo dove non sono semanticamente falsi.

- [ ] **Step 5: Implementare carryforward per annata**

Non usare un singolo float eterno. Conservare bucket `(origin_year, remaining)` e, prima di ogni anno, scartare quelli con `current_year > origin_year + 4`. Il report deve rendere visibile origine e scadenza oppure includere una nota esplicativa.

- [ ] **Step 6: Aggiornare UI/disclaimer**

La pagina fiscale deve mostrare “Stima fiscale semplificata, non dichiarazione”, metodo usato, fonti/anno e avvertimento per strumenti non classificati.

- [ ] **Step 7: Verificare Task 7**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_engines.py tests\test_api.py -k "tax or short or scenario"
backend\.venv\Scripts\python.exe -m ruff check backend tests
npm run build
```

- [ ] **Step 8: Commit e push**

```powershell
git add backend/app/database.py backend/scripts/seed_database.py backend/app/services/scenario_service.py backend/app/services/tax_service.py backend/app/models/schemas.py frontend/src/lib/api.ts frontend/src/pages/TaxPage.tsx tests/test_engines.py tests/test_api.py
git commit -m "fix: handle short risk and tax estimates"
git push -u origin HEAD
```

---

### Task 8: Eliminare leakage negli split ML temporali

**Files:**

- Modify: `backend/app/services/ml_dataset_service.py`
- Modify: `backend/app/services/ml_engine.py`
- Test: `tests/test_ml_dataset.py`
- Test: `tests/test_api.py`

**Contract:** Nessun campione di train può avere `target_date` uguale o successiva alla prima feature date del test. La stessa purga vale per ogni fold walk-forward.

- [ ] **Step 1: Scrivere dataset sintetico che espone il leakage**

Con feature date giornaliere e orizzonte 5, verificare:

```python
assert pd.to_datetime(train["target_date"]).max() < pd.to_datetime(test["date"]).min()
```

Scrivere lo stesso invariant per ogni fold.

- [ ] **Step 2: Eseguire e osservare il fallimento**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_ml_dataset.py -vv
```

- [ ] **Step 3: Purgare i bordi temporali**

Dopo aver calcolato `split_date`, usare:

```python
train = dataset[(dataset["date"] < split_date) & (dataset["target_date"] < split_date)].copy()
test = dataset[dataset["date"] >= split_date].copy()
```

Per i fold, definire `test_start` e applicare `train["target_date"] < test_start`. Normalizzare date prima del confronto e fallire su `NaT`.

- [ ] **Step 4: Aggiungere validazione split esplicita nell'engine**

`ml_engine.train_model` deve chiamare una funzione `validate_split_no_lookahead(train, test)` prima del fit e prima di ogni fit walk-forward. Un dataset insufficiente dopo purge restituisce errore chiaro.

- [ ] **Step 5: Verificare Task 8**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_ml_dataset.py tests\test_api.py -k "ml or lookahead"
backend\.venv\Scripts\python.exe -m ruff check backend tests
```

- [ ] **Step 6: Commit e push**

```powershell
git add backend/app/services/ml_dataset_service.py backend/app/services/ml_engine.py tests/test_ml_dataset.py tests/test_api.py
git commit -m "fix: purge temporal leakage from ML splits"
git push -u origin HEAD
```

---

### Task 9: Sanitizzare Telegram e rendere osservabili i fallimenti schedulati

**Files:**

- Modify: `backend/app/services/alert_service.py`
- Modify: `scripts/send_daily_alert.py`
- Modify: `.github/workflows/daily-alert.yml`
- Test: `tests/test_alert_service.py`

**Contract:** Il token Telegram non compare mai in eccezioni, risposte o log. Uno script schedulato fallito esce non-zero. I secret GitHub sono disponibili solo nello step di invio, non durante checkout/setup/install.

- [ ] **Step 1: Scrivere test con token sentinella**

Mockare una `httpx.HTTPStatusError` la cui request URL contiene `SENTINEL_SECRET_TOKEN`; verificare che `str(RuntimeError)` non contenga token, URL o query. Testare exit code 1 per not configured/runtime error e 0 solo per disabilitato/inviato.

- [ ] **Step 2: Implementare errore sanitizzato**

Non interpolare `str(exc)`. Il messaggio pubblico deve essere stabile, per esempio:

```python
raise RuntimeError("Invio Telegram fallito per errore di rete o risposta non valida.") from exc
```

La Bot API richiede il token nel path della request: il requisito è impedirne l'esposizione, non dichiarare falsamente che non sia trasmesso a Telegram.

- [ ] **Step 3: Restituire exit code reale nello script**

Cambiare `main() -> int` e terminare con `raise SystemExit(main())`. `AlertNotConfigured` e altri errori di invio restituiscono 1. Il refresh prezzi può restare fail-soft, ma il suo log non deve includere URL/segreti.

- [ ] **Step 4: Ridurre scope dei secret GitHub**

Spostare `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` e le API key da `jobs.send-alert.env` a `steps[-1].env` nello step `Run daily alert`. Mantenere il schedule disabilitato come già deciso.

- [ ] **Step 5: Verificare Task 9**

```powershell
backend\.venv\Scripts\python.exe -m pytest tests\test_alert_service.py tests\test_api.py -k "alert or telegram"
backend\.venv\Scripts\python.exe -m ruff check backend scripts tests
```

- [ ] **Step 6: Commit e push**

```powershell
git add backend/app/services/alert_service.py scripts/send_daily_alert.py .github/workflows/daily-alert.yml tests/test_alert_service.py
git commit -m "fix: prevent secret leaks in scheduled alerts"
git push -u origin HEAD
```

---

### Task 10: Rendere esplicite le azioni distruttive nell'interfaccia attuale

**Files:**

- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/UniversePage.tsx`
- Modify: `frontend/src/pages/BacktestPage.tsx`
- Modify: `frontend/src/pages/ImportPage.tsx`
- Modify: `frontend/src/components/AllocationPlanner.tsx`
- Modify: `frontend/src/pages/PortfolioPage.tsx`
- Modify: `README.md`

**Contract:** Nessuna cancellazione o sostituzione importante parte da un singolo click ambiguo. Il testo indica ciò che sarà rimosso/sostituito. Il backend resta l'ultima barriera di sicurezza.

- [ ] **Step 1: Mappare e riprodurre manualmente le azioni**

Con backend e frontend locali, registrare il comportamento corrente per: rimuovi asset, cancella backtest, reset portafoglio, apply allocation, apply import. Non modificare route non correlate.

- [ ] **Step 2: Rendere disponibile status/detail dell'errore API**

Introdurre una classe compatibile:

```ts
export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}
```

`apiGet/Post/Delete` devono sollevare `ApiError` per risposte HTTP non-ok, preservando il comportamento `Error.message` dei chiamanti esistenti.

- [ ] **Step 3: Aggiungere conferme chirurgiche senza redesign**

- Universe: prima prova DELETE normale; su 409 mostra le conseguenze e richiede digitazione esatta del ticker prima di chiamare `?purge=true&confirm_symbol=...`.
- Backtest: conferma con nome/id prima della cancellazione.
- Portfolio reset: testo esplicito su posizioni, ordini e snapshot.
- Allocation: CTA “Sostituisci il portafoglio con questo piano” e conferma con capitale/cash.
- Import: CTA “Sostituisci le posizioni con l'import” e conferma con righe valide/invalid.

Usare per questa fase i pattern esistenti e target touch >=44 px. Il dialog system accessibile completo appartiene alla Fase 5; non introdurre ora un nuovo design system.

- [ ] **Step 4: Verificare build e smoke browser**

```powershell
npm run build
npm audit --audit-level=high
```

Smoke manuale desktop e viewport mobile: annulla conferma, conferma errata, conferma corretta, errore backend. Verificare che nessuna operazione parta con un solo click.

- [ ] **Step 5: Commit e push**

```powershell
git add frontend/src/lib/api.ts frontend/src/pages/UniversePage.tsx frontend/src/pages/BacktestPage.tsx frontend/src/pages/ImportPage.tsx frontend/src/components/AllocationPlanner.tsx frontend/src/pages/PortfolioPage.tsx README.md
git commit -m "fix: require explicit destructive UI actions"
git push -u origin HEAD
```

---

### Task 11: Eseguire audit finale, smoke Windows e report della Fase 1

**Files:**

- Create: `docs/reports/2026-08-16-phase-1-verification.md`
- Modify if required by evidence only: `README.md`
- Modify if required by evidence only: `Avvia-InvestEdge.bat`
- Modify if required by evidence only: `scripts/launcher.ps1`

**Contract:** Il report contiene comandi, risultati, rischi residui e rollback. Nessun “tutto risolto” senza output recente. Qualsiasi correzione emersa nello smoke riceve prima un test di regressione.

- [ ] **Step 1: Eseguire la suite completa pulita**

```powershell
backend\.venv\Scripts\python.exe -m pytest
backend\.venv\Scripts\python.exe -m ruff check backend scripts tests
backend\.venv\Scripts\python.exe -m pip check
npm ci
npm run build
npm audit --audit-level=high
docker compose config
```

- [ ] **Step 2: Provare migrazione e restore reali su copie temporanee**

Usare soltanto directory temporanee create con PowerShell `New-Item`; non toccare il DB utente. Verificare:

- legacy -> backup -> migrazione -> dati sentinella presenti;
- backup fallito -> nessuna migrazione;
- ripristino della copia pre-migration e apertura valida SQLite.

- [ ] **Step 3: Eseguire smoke launcher e rete locale**

Avviare con gli script esistenti, verificare health, caricamento UI, frontend->backend sulla porta 8000, processi chiusi senza residui e porte non esposte su interfacce diverse da loopback. Non cancellare processi non avviati dal test.

- [ ] **Step 4: Eseguire review regressioni/sicurezza**

Usare `superpowers:requesting-code-review` su diff completo della Fase 1. Verificare esplicitamente:

- nessun secret in `git diff`, log di test o URL di errore;
- nessuna somma diretta di valori posizione multivaluta nei riepiloghi;
- nessun `follow_redirects=True` nell'import;
- nessuna route `/admin/seed`;
- nessuna cascade asset senza purge/backup;
- invariant ML train target < test feature;
- scenario short firmato;
- package audit senza high/critical.

- [ ] **Step 5: Scrivere report riproducibile**

Il report deve includere: commit iniziale/finale, branch remoto, file cambiati per Task, test e output sintetico, limiti noti, istruzioni di rollback, conferma che trading reale resta disabilitato e roadmap Fase 2.

- [ ] **Step 6: Commit e push del report**

```powershell
git add docs/reports/2026-08-16-phase-1-verification.md README.md Avvia-InvestEdge.bat scripts/launcher.ps1
git commit -m "docs: verify phase 1 reliability foundations"
git push -u origin HEAD
```

- [ ] **Step 7: Gate finale remoto**

Verificare:

```powershell
git status --short
git rev-parse HEAD
$currentBranch = git branch --show-current
git ls-remote origin $currentBranch
```

Expected: working tree pulito e hash remoto uguale a `HEAD`. Solo allora la Fase 1 può essere proposta per PR/merge e può iniziare il piano della Fase 2 “Strumenti e dati reali”.

---

## Verifica di completezza del piano

- Requisiti audit 1–12 della specifica: coperti dai Task 1–10.
- Nuova UI, intraday, portafogli multipli, strategie, catalogo esteso e mobile: volutamente esclusi dal codice di questa fase; restano nelle Fasi 2–6 approvate.
- Nessun placeholder `TODO`, `TBD`, “implementare qui” o pseudocodice senza contratto ammesso durante l'esecuzione.
- Ogni Task ha un singolo proprietario di scrittura, test mirati, commit e push.
- Le nuove task sono sequenziali per evitare modifiche concorrenti agli stessi file centrali (`database.py`, `schemas.py`, `portfolio_engine.py`, `api.ts`).
- La Fase 2 dovrà partire dal branch finale verificato della Fase 1 e ricevere un nuovo piano dedicato.
