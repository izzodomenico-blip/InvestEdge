# Verifica Fase 1 — Reliability Foundations

Data di esecuzione: 16 agosto 2026 (Europe/Rome)

## Perimetro e riferimenti Git

- Branch locale verificato: `codex/investedge-phase-1-task-11`.
- Commit iniziale della Fase 1: `c583e5b7aa6e77a4076c6b04e609803850d71ae1` (`docs: plan phase 1 reliability foundations`).
- Commit finale del codice applicativo auditato, cioè la base del Task 11: `12d080ece923c09e2be5602aff4524e312c89eeb` (`fix: require explicit destructive UI actions`).
- Ref remota verificata: `origin/codex/investedge-phase-1-task-10` punta a `12d080ece923c09e2be5602aff4524e312c89eeb`.
- Branch finale previsto: `origin/codex/investedge-phase-1-task-11`. Al momento di questo report non esiste ancora sul remoto: commit e push spettano al controller.
- Il commit documentale del Task 11 non è riportato perché non esiste ancora e il report non può auto-referenziarsi. Dovrà avere messaggio `docs: verify phase 1 reliability foundations`.

Questa è l'evidenza finale dopo l'integrazione dei finding e la review indipendente conclusiva. Il verdict tecnico del reviewer è **Ready to merge: Yes**; commit/push e gate remoto restano al controller, quindi la Fase 1 non è ancora chiusa nel workflow Git.

## Ambiente usato

- Windows, PowerShell 7.6.4 come shell di verifica e Windows PowerShell 5.1.26100.9168 tramite `Avvia-InvestEdge.bat`.
- Python 3.14.7 in `backend/.venv`, ambiente virtuale locale Git-ignored creato nel worktree con le dipendenze di sviluppo del progetto.
- Node.js 24.19.0 e npm 11.17.0.
- Docker CLI non installata/disponibile nell'ambiente.
- Worktree isolato: `C:\Users\izzod\.codex\worktrees\314e\InvestEdge`.

Il worktree non conteneva inizialmente `backend/.venv`; è stato creato un venv locale Git-ignored e installato `requirements-dev.txt`. L'invocazione letterale `backend\.venv\Scripts\python.exe` è inoltre non valida in PowerShell senza call operator o prefisso `./`; le esecuzioni registrate sotto usano `& '.\backend\.venv\Scripts\python.exe'`.

## File cambiati per Task

I file elencati derivano da `git diff-tree --no-commit-id --name-only -r <commit>`.

| Task | Commit | File |
|---|---|---|
| 1 | `2d423b2` | `README.md`; `backend/app/api/routes.py`; `backend/app/config.py`; `docker-compose.yml`; piano Fase 1; `frontend/package.json`; `frontend/package-lock.json`; `frontend/src/lib/api.ts`; `tests/test_api.py`; `tests/test_config.py` |
| 2 | `637b5dd` | `backend/app/database.py`; `backend/app/main.py`; `backend/app/services/backup_service.py`; piano Fase 1; `tests/test_api.py`; `tests/test_database.py` |
| 3 | `6f6afc6` | `backend/app/api/routes.py`; `backend/app/models/schemas.py`; `backend/app/services/assets_service.py`; piano Fase 1; `tests/test_api.py` |
| 4 | `5f92220` | `.env.example`; `backend/app/config.py`; `backend/app/database.py`; `backend/app/services/fx_service.py`; `backend/scripts/seed_database.py`; piano Fase 1; `tests/test_database.py`; `tests/test_fx_service.py` |
| 5 | `c77225e` | `backend/app/database.py`; `backend/app/models/schemas.py`; `backend/app/services/portfolio_engine.py`; `backend/app/services/report_service.py`; `backend/app/services/scenario_service.py`; `backend/scripts/seed_database.py`; piano Fase 1; `frontend/src/lib/api.ts`; `frontend/src/pages/PortfolioPage.tsx`; `tests/test_api.py`; `tests/test_portfolio_accounting.py` |
| 6 | `b488675` | `.env.example`; `backend/app/api/routes.py`; `backend/app/config.py`; `backend/app/models/schemas.py`; `backend/app/services/google_sheets_import_service.py`; `backend/app/services/portfolio_engine.py`; piano Fase 1; `tests/test_api.py`; `tests/test_fx_service.py`; `tests/test_import_security.py` |
| 7 | `2dbd14a` | `backend/app/database.py`; `backend/app/models/schemas.py`; `backend/app/services/assets_service.py`; `backend/app/services/report_service.py`; `backend/app/services/scenario_service.py`; `backend/app/services/tax_service.py`; `backend/scripts/seed_database.py`; piano Fase 1; `frontend/src/lib/api.ts`; `frontend/src/pages/ScenarioPage.tsx`; `frontend/src/pages/TaxCenterPage.tsx`; `tests/test_api.py`; `tests/test_engines.py` |
| 8 | `734815d` | `backend/app/services/ml_dataset_service.py`; `backend/app/services/ml_engine.py`; piano Fase 1; `tests/test_api.py`; `tests/test_ml_dataset.py` |
| 9 | `4ec9a04` | `.github/workflows/daily-alert.yml`; `backend/app/services/alert_service.py`; piano Fase 1; `scripts/send_daily_alert.py`; `tests/test_alert_service.py` |
| 10 | `12d080e` | `README.md`; piano Fase 1; `frontend/src/components/AllocationPlanner.tsx`; `frontend/src/lib/api.ts`; `frontend/src/pages/BacktestPage.tsx`; `frontend/src/pages/ImportPage.tsx`; `frontend/src/pages/PortfolioPage.tsx`; `frontend/src/pages/UniversePage.tsx` |
| 11, diff pre-commit | — | 25 path: i 24 path tassativi della fix wave, incluso questo report (19 file produzione/documentazione e 5 test elencati in `final-fix-inventory.md`), più il piano con le sole checkbox Step 1–7 aggiornate. `README.md` e `Avvia-InvestEdge.bat` non sono stati modificati; Step 6–7 diventano effettivi soltanto col gate controller descritto sotto. |

Il diff cumulativo pre-Task11, da `c583e5b` a `12d080e`, comprende 42 file, 5.296 inserimenti e 652 rimozioni. Sopra quella base, la fix wave non committata chiude i 10 finding consolidati descritti nella sezione dedicata; il commit documentale Task 11 dovrà essere verificato dal controller senza auto-riferimento.

## Step 1 — Suite completa e toolchain

Comandi post-fix e risultati freschi:

| Comando | Exit | Risultato sintetico |
|---|---:|---|
| `& '.\backend\.venv\Scripts\python.exe' -m pytest` | 0 | 280 passed, 937 warning di dipendenze in 290,89 s |
| `& '.\backend\.venv\Scripts\python.exe' -m ruff check backend scripts tests` | 0 | `All checks passed!` |
| `& '.\backend\.venv\Scripts\python.exe' -m pip check` | 0 | `No broken requirements found.` |
| `npm ci` da `frontend` | 0 | 179 package installati, 180 auditati; 1 vulnerabilità low |
| `npm run build` da `frontend` | 0 | 2.233 moduli; bundle JS 860,99 kB, gzip 230,10 kB |
| `npm audit --audit-level=high` da `frontend` | 0 | nessuna high/critical; 1 low in `@babel/core` |
| `docker compose config` | non eseguibile | comando `docker` assente; fallback locale sotto exit 0 |

Fallback locale per Compose, eseguito con Python/PyYAML: parsing di `docker-compose.yml` e assert sui binding `127.0.0.1:8000:8000`, `127.0.0.1:5173:5173` e su `VITE_API_BASE_URL=http://127.0.0.1:8000`; exit 0. Il comando integrale è nell'Appendice A.

Warning non bloccanti osservati:

- 936 warning `joblib`/NumPy e un warning Starlette/httpx nella suite;
- chunk Vite oltre 500 kB;
- npm 11 segnala lo script di installazione di `esbuild@0.28.2` non ancora coperto da `allowScripts`;
- `npm audit` conserva la vulnerabilità low `GHSA-4x5r-pxfx-6jf8` in `@babel/core`.

## Step 2 — Migrazione, backup fallito e restore

È stato creato con `New-Item` un root dedicato sotto `%TEMP%`, con directory separate `success`, `failure` e `restore`; `INVESTEDGE_DB_PATH` è stato impostato esclusivamente su file sotto quel root. Nessun database in `data/` o database utente è stato aperto.

Il harness one-off ha usato `sqlite3` per creare due fixture legacy equivalenti a quella di `tests/test_database.py::test_init_db_migrates_legacy_tables_before_creating_indexes`, con sentinelle distinte in `assets`, `signals`, `simulated_orders`, `news_items` e `api_cache`. Ha poi eseguito il vero `backend.app.main.lifespan` e le funzioni reali di backup/migrazione. Il sorgente completo, incluse verifica del path, variabili d'ambiente, assert e cleanup, è nell'Appendice B.

Output sintetico, exit 0:

```text
MIGRATION_BACKUP=PASS
SENTINEL_AFTER_MIGRATION=PASS
BACKUP_FAILURE_STOPS_MIGRATION=PASS
PRE_MIGRATION_RESTORE_SQLITE=PASS
BACKUP_COUNT=1
```

Controlli effettuati:

1. backup SQLite creato prima della migrazione e ancora con schema legacy;
2. schema principale migrato, `PRAGMA integrity_check=ok` e tutte le sentinelle preservate;
3. guasto reale del backup ottenuto mettendo un file al posto della directory `backups`: `lifespan` ha sollevato `FileExistsError`, lo schema è rimasto legacy e la sentinella invariata;
4. copia del backup pre-migrazione ripristinata con `shutil.copy2`, aperta con `sqlite3`, `integrity_check=ok`, sentinella presente e successiva migrazione riuscita.

Le due directory temporanee create (incluso il primo tentativo fermato da un controllo path troppo restrittivo) sono state risolte sotto `%TEMP%`, verificate per prefisso/nome, rimosse e controllate come assenti.

## Step 3 — Launcher Windows, UI e rete

### Anomalia riprodotta e fix TDD

Primo smoke reale:

```powershell
& '.\Avvia-InvestEdge.bat' -PortStart 8000 -PortEnd 8000 -NoBrowser
```

con `INVESTEDGE_DB_PATH` puntato a una directory creata con `New-Item` sotto `%TEMP%`, real data/news, alert e import remoto disabilitati. Il launcher è uscito 1 prima di avviare uvicorn: `Get-FileHash` non era disponibile nella sessione Windows PowerShell.

Causa radice: `Get-FileHash256` dipendeva dal caricamento automatico della funzione `Get-FileHash` esportata da `Microsoft.PowerShell.Utility`. Una probe con module autoload disabilitato ha restituito `GET_FILE_HASH=UNAVAILABLE` ed exit 17; con autoload normale ha risolto `Function:Microsoft.PowerShell.Utility` ed exit 0.

RED ripetibile: il test persistente `tests/test_launcher.py::test_launcher_hash_works_without_get_file_hash` estrae tramite AST la vera funzione `Get-FileHash256` da `scripts/launcher.ps1`, sostituisce `Get-FileHash` con una sentinella indisponibile e calcola l'hash di un file temporaneo noto. Con la sola funzione ripristinata temporaneamente alla versione pre-fix, il comando seguente è uscito 1 per la causa attesa:

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_launcher.py -q
```

```text
SENTINEL_GET_FILE_HASH_UNAVAILABLE
```

Fix minimo finale: `Get-FileHash256` inizializza stream e hasher a `$null`, li acquisisce dentro il `try`, usa `System.IO.File.OpenRead`, `System.Security.Cryptography.SHA256.Create` e `System.BitConverter`, e li dispone condizionalmente nel `finally`. In questo modo lo stream viene chiuso anche se la seconda acquisizione fallisce; nessun'altra logica del launcher è cambiata.

GREEN: lo stesso test persistente, lasciando `Get-FileHash` indisponibile, ha restituito exit 0 e SHA-256 atteso `B5C050D121CAA341E0B935677E58F99A0EE6E4C15622FBA754A3D7E797027687`. Il test completo è il riferimento tracciato riproducibile; non dipende da un harness eliminato.

### Smoke post-fix

Lo smoke negativo ha usato un DB non-SQLite temporaneo con sentinella. Il launcher non ha eseguito seed automatico su un file esistente, uvicorn è fallito durante il backup, l'exit `3` è stato propagato, l'hash della sentinella è rimasto identico e non sono rimasti listener o lock.

Lo smoke positivo della fix wave ha avviato direttamente `scripts/launcher.ps1` con un DB inesistente sotto `C:\Users\izzod\AppData\Local\Temp\InvestEdge-Task11-Positive-Final`, porta esclusiva `8121`, browser e fonti remote disabilitati. Evidenza osservata:

- `/health`, `/`, `/assets`, `/alerts/status`, `/action-board` e due asset statici JS/CSS hanno restituito 200;
- `/assets` ha restituito 25 asset e AAPL esponeva `fx_rate_to_base`/`last_price_base`;
- `Get-NetTCPConnection` ha mostrato un solo listener `127.0.0.1`;
- catena verificata: PID launcher/lock `10096` -> shim Python venv `31680` -> uvicorn/listener `19032`;
- è stato fermato esclusivamente il PID uvicorn `19032`, identificato come discendente del launcher; il launcher ha eseguito il cleanup e propagato exit `1`;
- i tre PID, il listener e il lock erano assenti dopo lo shutdown; `PRAGMA integrity_check=ok`, un backup `pre-migration`, scan log secret `0`, log preesistente ripristinato e root temporaneo eliminato.

Il protocollo riproducibile a due console con gli stessi assert e cleanup confinato resta nell'Appendice C. I PID sopra appartengono soltanto a questo run e non devono essere riutilizzati.

## Final cumulative fix wave

I RED elencati sono stati osservati sul codice pre-fix del relativo sottocaso; ogni comando pytest usa il prefisso esatto `& '.\backend\.venv\Scripts\python.exe' -m pytest <node-id> -q`. Il test di concorrenza I2, aggiunto dopo il fix atomico del primo sottocaso, è risultato subito verde ed è registrato come copertura regressiva, non come RED distinto. I test persistenti tracciati sono il riferimento riproducibile.

| Finding | RED osservato | Fix minimo e GREEN |
|---|---|---|
| I2 backup | `test_same_second_backups_preserve_distinct_contents_and_reasons`: stesso nome/un solo file; `test_prune_backups_keeps_newest_filesystem_timestamp`: eliminato il file più nuovo | reason slug + prenotazione atomica, cleanup parziale e ordinamento `st_mtime_ns`; `tests/test_database.py` 9 passed |
| C1 DB effettivo | launcher decideva sul default assente e il reset legacy non aveva backup pre-reset | risoluzione `Settings.from_env()`, seed automatico solo su target assente, entrypoint fail-closed `backup -> init`; launcher/database/lifespan GREEN |
| I5 exit launcher | fake server exit 23 diventava exit 0 dopo cleanup | cattura immediata, cleanup `finally`, exit esplicito; `tests/test_launcher.py` 3 passed |
| I1 import secret | 3 failure: cause/context/traceback conservavano la sentinella URL | errore pubblico sollevato fuori dagli `except`; `tests/test_import_security.py` 23 passed |
| I4 metadata import | currency/type espliciti incompatibili accettati; colonne omesse usavano default non canonici; nella verifica residuale una cella opzionale vuota era ancora trattata come esplicita se l'header esisteva | flag parser per singola cella trim non vuota, reject dei mismatch realmente espliciti e riuso metadata asset; caso multi-riga residuale più gruppo import GREEN |
| I3 binding/barriere | import/allocation/reset/delete restituivano 200 e mutavano stato senza binding/conferma | token SHA-256 canonici confrontati con `hmac.compare_digest`, conferme reset/delete backend e caller UI coordinati; gruppo I3 4 passed |
| C2 valori base | cash EUR `0` anziché residuo `31,4651`; `price_base` assente; rebalance USD `SELL` spurio; campi asset base assenti | quantità/costi/cash e rebalance in EUR, prezzo nativo preservato, campi base API e UI; 4 casi GREEN, aggregato allocazione/rebalance 12 passed, build TypeScript exit 0 |
| M1 Telegram | headline/symbol/title/reason contenevano markup dinamico grezzo | `html.escape(..., quote=False)` solo sui campi dinamici; `tests/test_alert_service.py` 16 passed |
| M2 short dashboard | posizione short visibile ma `positions_count=0` | condizione epsilon firmata; GREEN mirata |
| I6 rollback | `rg` trovava `data/backups/investedge-*.db` hard-coded | path derivato dal DB effettivo, candidati per reason, selezione singola e integrity check; `rg` senza match e probe path assoluto/relativo `PASS` |

Correzione residuale I4: il nuovo `test_import_optional_metadata_is_explicit_per_nonempty_row_cell` usa AAPL con celle opzionali vuote seguito da VWCE con valore esplicito incompatibile. RED: status 400 con errore attribuito ad AAPL invece che a VWCE. Dopo il fix minimo per-riga, GREEN mirata 1 passed e gate `pytest tests\test_import_security.py tests\test_api.py -q -k import` 35 passed, exit 0. La variante esplicitamente compatibile applica AAPL come `stock/USD` canonico e VWCE come `etf/EUR`.

Il gate mirato cumulativo finale (launcher, database, import security, escaping e 14 node-id API, pari a 15 casi inclusa la parametrizzazione I4) ha eseguito 51 test con exit 0. Un primo tentativo storico non ha eseguito test ed è uscito 1 soltanto perché un node-id lifespan era scritto con nome inesatto; il comando è stato corretto dopo `rg '^def test_lifespan'` senza modificare produzione.

## Esito review indipendente finale

Gli hash sotto sono SHA-256 degli artefatti di review locali, non commit Git e non introducono auto-riferimenti al futuro commit documentale Task 11.

| Review | Package | SHA-256 | Esito |
|---|---|---|---|
| Task 11 iniziale | `review-task11-worktree.diff` | `0893F5C1717D56288D77CFDE55939258F455BA5F503E69039B290E14C4981BDB` | 2 Important e 1 Minor individuati |
| Task 11 fix | `review-task11-fix-round-1-worktree.diff` | `77BB418807538C3D477D7895B959CB501390DADBC06A8E3D4BCB66E124EE7531` | 3/3 addressed; checklist Task 11 finale 10/10 PASS |
| Cumulativa iniziale | `review-phase1-final-precommit.diff` | `3F519B7A57D049682FE435C6C2E94F058076280B4CA596EEE8B2D439EAF58643` | 10 finding: 2 Critical, 6 Important, 2 Minor |
| Cumulativa fix wave | `review-phase1-final-fix-wave-precommit.diff` | `70B9598F964658E73C45BE4D054D3ADE1461106CFC986510A6C9849BF11FA29A` | 10/10 finding originari addressed; rilevato un residual Important I4 per-cell |
| Cumulativa residuale | `review-phase1-residual-i4-precommit.diff` | `2B0506E146B755F33402869BC4BE4B91421A05792FFC89D4EC2C1D223C49792C` | residual I4 addressed; nessuna nuova rottura; **Ready to merge: Yes** |

Verdetto finale: tutti i 10 finding originari sono **ADDRESSED**, il residual optional metadata per-cell è **ADDRESSED**, la checklist Task 11 è **10/10 PASS** e non restano finding noti Critical o Important aperti. Questo verdict chiude Step 4; l'integrazione del presente esito nel report chiude Step 5.

## Checklist verificata dalla review indipendente

Il reviewer indipendente ha verificato questi controlli sul diff finale cumulativo; l'esito complessivo è PASS.

| Controllo | Evidenza implementatore |
|---|---|
| Secret in diff/log/URL di errore | scan value-aware delle variabili segrete note: 0 valori nel diff; 0 private key; 0 token-shaped literal in produzione. Cinque URL con nomi di parametri sensibili sono soltanto sentinelle in `tests/test_alert_service.py` e `tests/test_import_security.py`, zero nel codice di produzione. Log launcher: 0 match. Test completi di alert/import inclusi nel gate mirato, exit 0. |
| Somme multivaluta | `portfolio_engine`, report e scenario consolidano `current_value_base`, `realized_pnl_base` e `unrealized_pnl_base`; `test_mixed_currency_summary_weights_and_scenario_use_eur_values` è verde. |
| Allocation/rebalance/UI | piano e rebalance usano prezzi/costi base EUR, preservando il prezzo ordine nativo; residuo intero riconciliato, USD e campi asset base protetti dai quattro test C2 e dal build TypeScript. |
| Redirect import | zero occorrenze di `follow_redirects=True`; il client usa `follow_redirects=False` e gestisce al massimo tre redirect trusted. Tutto `tests/test_import_security.py` è verde. |
| Binding e distruttività | import e allocation richiedono il token della preview/piano corrente (409 se missing/stale); reset e delete backtest richiedono conferma backend esplicita (400 se assente/errata). |
| Route seed | zero decorator `/admin/seed`; `test_admin_seed_route_is_not_exposed` verifica 404 ed è verde. |
| Cascade asset | DELETE normale con dipendenze restituisce 409 senza modifiche; purge richiede simbolo esatto e backup creato, altrimenti conserva i dati. I quattro test mirati di conflitto/backup sono verdi. |
| ML leakage | `ml_dataset_service.py` impone `max(train.target_date) < min(test.date)` e purga split/fold; entrambi i test temporali mirati sono verdi. |
| Scenario short | usa `current_value_base` firmato; il test di short con shock +20%/-20% verifica valori stressati -1.200/-800 ed è verde. |
| Package audit | `npm audit --audit-level=high` exit 0: nessuna high/critical, una low residua. |

Il gate mirato finale sui finding è uscito 0 con 51 test; il comando esatto è nell'Appendice D. La suite completa post-fix è il riferimento quantitativo: 280 test raccolti ed eseguiti al 100% con exit 0.

## Appendice A — Fallback Compose riproducibile

Da eseguire dalla root del repository quando `docker compose config` non è disponibile:

```powershell
$ErrorActionPreference = "Stop"
@'
import pathlib
import yaml

compose = yaml.safe_load(pathlib.Path("docker-compose.yml").read_text(encoding="utf-8"))
assert compose["services"]["backend"]["ports"] == ["127.0.0.1:8000:8000"]
assert compose["services"]["frontend"]["ports"] == ["127.0.0.1:5173:5173"]
assert (
    compose["services"]["frontend"]["environment"]["VITE_API_BASE_URL"]
    == "http://127.0.0.1:8000"
)
print("COMPOSE_FALLBACK=PASS")
'@ | & '.\backend\.venv\Scripts\python.exe' -
if ($LASTEXITCODE -ne 0) { throw "Fallback Compose fallito" }
```

Output osservato: `COMPOSE_FALLBACK=PASS`, exit 0.

## Appendice B — Migrazione e restore riproducibili

Il blocco è autosufficiente: crea soltanto directory sotto `%TEMP%`, imposta nel processo figlio un DB dedicato, usa l'effettivo `lifespan`, verifica gli assert e rimuove il root solo dopo averne riconfermato il confinamento.

```powershell
$ErrorActionPreference = "Stop"
$task11TempBase = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$task11MigrationRoot = Join-Path $task11TempBase (
    "InvestEdge-Task11-Migration-" + [guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $task11MigrationRoot -Force | Out-Null
$task11ResolvedRoot = (Resolve-Path -LiteralPath $task11MigrationRoot).Path
if (-not $task11ResolvedRoot.StartsWith(
    $task11TempBase + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Directory migrazione fuori dal temp di sistema"
}
if (-not ([IO.Path]::GetFileName($task11ResolvedRoot) -like "InvestEdge-Task11-Migration-*")) {
    throw "Nome directory migrazione non valido"
}

$task11PreviousPytest = [Environment]::GetEnvironmentVariable("PYTEST_CURRENT_TEST", "Process")
$task11PreviousTempRoot = [Environment]::GetEnvironmentVariable(
    "INVESTEDGE_TASK11_TEMP_ROOT",
    "Process"
)
try {
    $task11SuccessDir = Join-Path $task11ResolvedRoot "success"
    $task11FailureDir = Join-Path $task11ResolvedRoot "failure"
    $task11RestoreDir = Join-Path $task11ResolvedRoot "restore"
    New-Item -ItemType Directory -Path @(
        $task11SuccessDir,
        $task11FailureDir,
        $task11RestoreDir
    ) -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $task11FailureDir "backups") -Force | Out-Null

    $env:INVESTEDGE_TASK11_TEMP_ROOT = $task11ResolvedRoot
    Remove-Item Env:PYTEST_CURRENT_TEST -ErrorAction SilentlyContinue
    @'
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
from pathlib import Path

root = Path(os.environ["INVESTEDGE_TASK11_TEMP_ROOT"]).resolve()
success_db = root / "success" / "investedge.db"
failure_db = root / "failure" / "investedge.db"
restored_db = root / "restore" / "restored-pre-migration.db"

LEGACY_SQL = """
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    exchange TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, asset_type)
);
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    signal TEXT NOT NULL,
    score REAL NOT NULL,
    rationale TEXT,
    source TEXT NOT NULL DEFAULT 'scoring_engine',
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE simulated_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'SIMULATED',
    executed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);
CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    source TEXT,
    published_at TEXT,
    sentiment_score REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE api_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    payload TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def create_legacy(path: Path, marker: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SQL)
        connection.execute(
            "INSERT INTO assets (id, symbol, name, asset_type, currency) "
            "VALUES (1, 'LEGACY', ?, 'stock', 'EUR')",
            (marker,),
        )
        connection.execute(
            "INSERT INTO signals (asset_id, signal, score, rationale) "
            "VALUES (1, 'BUY', 75, ?)",
            (marker,),
        )
        connection.execute(
            "INSERT INTO simulated_orders (asset_id, side, quantity, price, notes) "
            "VALUES (1, 'BUY', 2, 10, ?)",
            (marker,),
        )
        connection.execute(
            "INSERT INTO news_items (asset_id, title, url) "
            "VALUES (1, ?, 'https://example.test/legacy')",
            (marker,),
        )
        connection.execute(
            "INSERT INTO api_cache (cache_key, provider, payload) "
            "VALUES (?, 'legacy-provider', '{}')",
            (marker,),
        )


create_legacy(success_db, "SENTINEL_SUCCESS")
create_legacy(failure_db, "SENTINEL_FAILURE")

os.environ["INVESTEDGE_DB_PATH"] = str(success_db)
from backend.app.config import get_settings
from backend.app.database import init_db
from backend.app.main import lifespan


def set_database(path: Path) -> None:
    os.environ["INVESTEDGE_DB_PATH"] = str(path)
    get_settings.cache_clear()


async def open_once() -> None:
    async with lifespan(None):
        pass


set_database(success_db)
asyncio.run(open_once())
backup_files = sorted((success_db.parent / "backups").glob("investedge-*.db"))
assert len(backup_files) == 1
pre_migration = backup_files[0]

with sqlite3.connect(success_db) as connection:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute(
        "SELECT name FROM assets WHERE symbol='LEGACY'"
    ).fetchone()[0] == "SENTINEL_SUCCESS"
    for table, column in {
        "signals": "created_at",
        "simulated_orders": "order_date",
        "news_items": "updated_at",
        "api_cache": "symbol",
    }.items():
        assert column in columns(connection, table)

with sqlite3.connect(pre_migration) as connection:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "created_at" not in columns(connection, "signals")
    assert connection.execute("SELECT rationale FROM signals").fetchone()[0] == (
        "SENTINEL_SUCCESS"
    )

shutil.copy2(pre_migration, restored_db)
with sqlite3.connect(restored_db) as connection:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute(
        "SELECT name FROM assets WHERE symbol='LEGACY'"
    ).fetchone()[0] == "SENTINEL_SUCCESS"

set_database(restored_db)
init_db()
with sqlite3.connect(restored_db) as connection:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "created_at" in columns(connection, "signals")

set_database(failure_db)
try:
    asyncio.run(open_once())
except FileExistsError:
    pass
else:
    raise AssertionError("Il guasto reale del backup non ha interrotto l'avvio")

with sqlite3.connect(failure_db) as connection:
    assert "created_at" not in columns(connection, "signals")
    assert connection.execute(
        "SELECT name FROM assets WHERE symbol='LEGACY'"
    ).fetchone()[0] == "SENTINEL_FAILURE"
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

print("MIGRATION_BACKUP=PASS")
print("SENTINEL_AFTER_MIGRATION=PASS")
print("BACKUP_FAILURE_STOPS_MIGRATION=PASS")
print("PRE_MIGRATION_RESTORE_SQLITE=PASS")
print(f"BACKUP_COUNT={len(backup_files)}")
'@ | & '.\backend\.venv\Scripts\python.exe' -
    if ($LASTEXITCODE -ne 0) { throw "Smoke migrazione/restore fallito" }
} finally {
    if ($null -eq $task11PreviousTempRoot) {
        Remove-Item Env:INVESTEDGE_TASK11_TEMP_ROOT -ErrorAction SilentlyContinue
    } else {
        [Environment]::SetEnvironmentVariable(
            "INVESTEDGE_TASK11_TEMP_ROOT",
            $task11PreviousTempRoot,
            "Process"
        )
    }
    if ($null -eq $task11PreviousPytest) {
        Remove-Item Env:PYTEST_CURRENT_TEST -ErrorAction SilentlyContinue
    } else {
        [Environment]::SetEnvironmentVariable(
            "PYTEST_CURRENT_TEST",
            $task11PreviousPytest,
            "Process"
        )
    }
    if (Test-Path -LiteralPath $task11MigrationRoot) {
        $task11CleanupRoot = (Resolve-Path -LiteralPath $task11MigrationRoot).Path
        if (-not $task11CleanupRoot.StartsWith(
            $task11TempBase + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Cleanup migrazione fuori dal temp di sistema"
        }
        if (-not ([IO.Path]::GetFileName($task11CleanupRoot) -like "InvestEdge-Task11-Migration-*")) {
            throw "Nome cleanup migrazione non valido"
        }
        [IO.Directory]::Delete($task11CleanupRoot, $true)
    }
}
if (Test-Path -LiteralPath $task11MigrationRoot) {
    throw "Directory migrazione residua"
}
"MIGRATION_CLEANUP=PASS"
```

Output osservato: i cinque marker `PASS`, `BACKUP_COUNT=1`, `MIGRATION_CLEANUP=PASS`; exit 0.

## Appendice C — Smoke launcher/rete/processi riproducibile

Il protocollo usa due console per poter inviare Ctrl+C esclusivamente al batch avviato dal test. Prima di iniziare, entrambe le console devono trovarsi nella root dello stesso worktree.

Console A — setup confinato e avvio bloccante:

```powershell
$ErrorActionPreference = "Stop"
if (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count) {
    throw "Porta 8000 già occupata: non terminare processi estranei"
}
$task11LauncherBase = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$task11LauncherRoot = Join-Path $task11LauncherBase (
    "InvestEdge-Task11-Launcher-" + [guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $task11LauncherRoot -Force | Out-Null
$task11LauncherRoot = (Resolve-Path -LiteralPath $task11LauncherRoot).Path
if (-not $task11LauncherRoot.StartsWith(
    $task11LauncherBase + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) { throw "Directory launcher fuori dal temp di sistema" }

$task11DataDir = Join-Path (Resolve-Path '.').Path "data"
$task11Log = Join-Path $task11DataDir "launcher.log"
$task11State = @{
    DataDirExisted = [IO.Directory]::Exists($task11DataDir)
    LogExisted = [IO.File]::Exists($task11Log)
}
if ($task11State.LogExisted) {
    [IO.File]::Copy($task11Log, (Join-Path $task11LauncherRoot "launcher-log-before.bin"))
}
[IO.File]::WriteAllText(
    (Join-Path $task11LauncherRoot "pre-state.json"),
    ($task11State | ConvertTo-Json -Compress),
    [Text.UTF8Encoding]::new($false)
)

$task11EnvironmentNames = @(
    "INVESTEDGE_DB_PATH",
    "INVESTEDGE_ENV",
    "ENABLE_REAL_DATA",
    "ENABLE_REAL_NEWS",
    "ENABLE_ALERTS",
    "ENABLE_GOOGLE_SHEETS_IMPORT"
)
$task11PreviousEnvironment = @{}
foreach ($task11Name in $task11EnvironmentNames) {
    $task11PreviousEnvironment[$task11Name] = [Environment]::GetEnvironmentVariable(
        $task11Name,
        "Process"
    )
}
try {
    $env:INVESTEDGE_DB_PATH = Join-Path $task11LauncherRoot "smoke.db"
    $env:INVESTEDGE_ENV = "local"
    $env:ENABLE_REAL_DATA = "false"
    $env:ENABLE_REAL_NEWS = "false"
    $env:ENABLE_ALERTS = "false"
    $env:ENABLE_GOOGLE_SHEETS_IMPORT = "false"
    "TASK11_LAUNCHER_ROOT=$task11LauncherRoot"
    & '.\Avvia-InvestEdge.bat' -PortStart 8000 -PortEnd 8000 -NoBrowser
} finally {
    foreach ($task11Name in $task11EnvironmentNames) {
        $task11OldValue = $task11PreviousEnvironment[$task11Name]
        if ($null -eq $task11OldValue) {
            Remove-Item "Env:$task11Name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($task11Name, $task11OldValue, "Process")
        }
    }
}
```

Console B — mentre Console A è bloccata su uvicorn, scoperta fail-closed del solo root appena creato e assert live:

```powershell
$ErrorActionPreference = "Stop"
$task11LauncherBase = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
$task11Candidates = @(Get-ChildItem -LiteralPath $task11LauncherBase -Directory |
    Where-Object Name -Like "InvestEdge-Task11-Launcher-*")
if ($task11Candidates.Count -ne 1) {
    throw "Atteso un solo root launcher Task 11, trovati $($task11Candidates.Count)"
}
$task11LauncherRoot = $task11Candidates[0].FullName

$task11Health = $null
for ($task11Attempt = 0; $task11Attempt -lt 60; $task11Attempt++) {
    try {
        $task11Health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" `
            -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        if ($task11Health.StatusCode -eq 200) { break }
    } catch {
        Start-Sleep -Milliseconds 250
    }
}
if ($null -eq $task11Health -or $task11Health.StatusCode -ne 200) {
    throw "Health non disponibile"
}
$task11Ui = Invoke-WebRequest -Uri "http://127.0.0.1:8000/" `
    -UseBasicParsing -TimeoutSec 5
$task11AssetsResponse = Invoke-WebRequest -Uri "http://127.0.0.1:8000/assets" `
    -UseBasicParsing -TimeoutSec 5
$task11Assets = $task11AssetsResponse.Content | ConvertFrom-Json
$task11Alerts = Invoke-WebRequest -Uri "http://127.0.0.1:8000/alerts/status" `
    -UseBasicParsing -TimeoutSec 5
$task11ActionBoard = Invoke-WebRequest -Uri "http://127.0.0.1:8000/action-board" `
    -UseBasicParsing -TimeoutSec 5
$task11StaticPaths = @(
    [regex]::Matches($task11Ui.Content, '(?:src|href)="(?<path>/static/[^"]+)"') |
        ForEach-Object { $_.Groups['path'].Value } |
        Sort-Object -Unique
)
$task11StaticResponses = @(
    foreach ($task11Path in $task11StaticPaths) {
        Invoke-WebRequest -Uri "http://127.0.0.1:8000$task11Path" `
            -UseBasicParsing -TimeoutSec 5
    }
)
$task11Connections = @(Get-NetTCPConnection -LocalPort 8000 -State Listen)
$task11Addresses = @($task11Connections.LocalAddress | Sort-Object -Unique)
$task11ServerPids = @($task11Connections.OwningProcess | Sort-Object -Unique)
$task11Lock = Get-Content '.\data\.investedge.lock'
$task11LauncherPid = [int]$task11Lock[0]
$task11ServerPid = [int]$task11ServerPids[0]

if ($task11Health.Content -notmatch '"status":"ok"') { throw "Health body inatteso" }
if ($task11Ui.StatusCode -ne 200 -or $task11Ui.Content -notmatch '<div id="root"></div>') {
    throw "Shell UI non caricata"
}
if (@($task11Assets).Count -ne 25) {
    throw "Numero asset inatteso: $(@($task11Assets).Count)"
}
if ($task11Alerts.StatusCode -ne 200) { throw "Alerts status non 200" }
if ($task11ActionBoard.StatusCode -ne 200) { throw "Action board non 200" }
if ($task11StaticPaths.Count -lt 2 -or
    @($task11StaticResponses | Where-Object StatusCode -ne 200).Count -ne 0) {
    throw "Asset statici JS/CSS assenti o non raggiungibili"
}
if ($task11Addresses.Count -ne 1 -or $task11Addresses[0] -ne "127.0.0.1") {
    throw "Listener non confinato a loopback: $($task11Addresses -join ',')"
}
if ($task11ServerPids.Count -ne 1) { throw "PID server ambiguo" }
if ($task11Lock[1] -ne "8000") { throw "Porta lock inattesa" }
if (-not (Get-Process -Id $task11LauncherPid -ErrorAction SilentlyContinue)) {
    throw "PID launcher assente"
}
if (-not (Get-Process -Id $task11ServerPid -ErrorAction SilentlyContinue)) {
    throw "PID server assente"
}
"HEALTH_STATUS=$($task11Health.StatusCode)"
"UI_STATUS=$($task11Ui.StatusCode)"
"ASSET_COUNT=$(@($task11Assets).Count)"
"ALERTS_STATUS=$($task11Alerts.StatusCode)"
"ACTION_BOARD_STATUS=$($task11ActionBoard.StatusCode)"
"STATIC_COUNT=$($task11StaticPaths.Count)"
"LISTENER_ADDRESSES=$($task11Addresses -join ',')"
"LAUNCHER_PID=$task11LauncherPid"
"SERVER_PID=$task11ServerPid"
```

A questo punto aprire `http://127.0.0.1:8000/` in un browser, verificare titolo `InvestEdge — Investment Intelligence`, heading `Cosa fare oggi` e console senza warning/error. Poi tornare in Console A, premere Ctrl+C e rispondere `S` all'eventuale prompt del batch. Senza chiudere Console B, eseguire il post-shutdown seguente: usa esclusivamente i PID appena acquisiti e non invoca `Stop-Process`.

```powershell
for ($task11Attempt = 0; $task11Attempt -lt 40; $task11Attempt++) {
    $task11PortAlive = @(
        Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    ).Count -gt 0
    $task11LauncherAlive = [bool](
        Get-Process -Id $task11LauncherPid -ErrorAction SilentlyContinue
    )
    $task11ServerAlive = [bool](
        Get-Process -Id $task11ServerPid -ErrorAction SilentlyContinue
    )
    if (-not $task11PortAlive -and -not $task11LauncherAlive -and -not $task11ServerAlive) {
        break
    }
    Start-Sleep -Milliseconds 250
}
if ($task11PortAlive -or $task11LauncherAlive -or $task11ServerAlive) {
    throw "Residui launcher/server: non terminare processi non identificati"
}
if (Test-Path '.\data\.investedge.lock') { throw "Lock launcher residuo" }

$task11SmokeDb = Join-Path $task11LauncherRoot "smoke.db"
@'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
print("SMOKE_DB_INTEGRITY=ok")
'@ | & '.\backend\.venv\Scripts\python.exe' - $task11SmokeDb
if ($LASTEXITCODE -ne 0) { throw "DB smoke non integro" }

$task11Log = Join-Path (Resolve-Path '.').Path "data\launcher.log"
$task11SecretPattern = (
    '(?i)(telegram_bot_token|telegram_chat_id|alpha_vantage_api_key|' +
    'coingecko_api_key|finnhub_api_key|fred_api_key|authorization\s*:|' +
    'bearer\s+|token=|api[_-]?key=|secret=)'
)
$task11SecretMatches = @(
    Select-String -LiteralPath $task11Log -Pattern $task11SecretPattern -AllMatches
)
if ($task11SecretMatches.Count -ne 0) { throw "Pattern secret nel log launcher" }

$task11PreState = Get-Content (Join-Path $task11LauncherRoot "pre-state.json") -Raw |
    ConvertFrom-Json
$task11LogBackup = Join-Path $task11LauncherRoot "launcher-log-before.bin"
if ($task11PreState.LogExisted) {
    [IO.File]::Copy($task11LogBackup, $task11Log, $true)
} else {
    [IO.File]::Delete($task11Log)
}
$task11DataDir = Join-Path (Resolve-Path '.').Path "data"
if (-not $task11PreState.DataDirExisted -and
    [IO.Directory]::Exists($task11DataDir) -and
    [IO.Directory]::GetFileSystemEntries($task11DataDir).Count -eq 0) {
    [IO.Directory]::Delete($task11DataDir, $false)
}

$task11CleanupRoot = (Resolve-Path -LiteralPath $task11LauncherRoot).Path
if (-not $task11CleanupRoot.StartsWith(
    $task11LauncherBase + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) { throw "Cleanup launcher fuori dal temp di sistema" }
if (-not ([IO.Path]::GetFileName($task11CleanupRoot) -like "InvestEdge-Task11-Launcher-*")) {
    throw "Nome cleanup launcher non valido"
}
[IO.Directory]::Delete($task11CleanupRoot, $true)
if (Test-Path -LiteralPath $task11CleanupRoot) { throw "Root launcher residuo" }
"LAUNCHER_SHUTDOWN_CLEANUP=PASS"
```

Output fresco del gate `verification-before-completion`: gli stessi controlli HTTP/rete/cleanup sono passati sulla porta 8000; PID launcher `12176`, uvicorn `24396`, exit propagato `1`, `SMOKE_DB_INTEGRITY=ok`, `LAUNCHER_SHUTDOWN_CLEANUP=PASS`, zero listener, lock e root temporanei residui. I PID sono evidenza effimera e non devono essere riutilizzati.

## Appendice D — Gate mirato regressioni/sicurezza

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest -q `
    tests\test_launcher.py `
    tests\test_database.py `
    tests\test_import_security.py `
    tests\test_alert_service.py::test_format_board_escapes_dynamic_html_fields `
    tests\test_api.py::test_lifespan_backs_up_before_initializing_outside_tests `
    tests\test_api.py::test_lifespan_does_not_initialize_when_backup_fails `
    tests\test_api.py::test_import_apply_rejects_explicit_existing_asset_metadata_mismatch `
    tests\test_api.py::test_import_apply_uses_canonical_metadata_when_optional_columns_are_omitted `
    tests\test_api.py::test_import_optional_metadata_is_explicit_per_nonempty_row_cell `
    tests\test_api.py::test_import_apply_rejects_stale_preview `
    tests\test_api.py::test_allocation_apply_rejects_stale_plan `
    tests\test_api.py::test_portfolio_init_requires_backend_confirmation `
    tests\test_api.py::test_delete_backtest_requires_backend_confirmation `
    tests\test_api.py::test_allocation_apply_reconciles_integer_residual_in_eur `
    tests\test_api.py::test_allocation_apply_uses_base_price_for_usd_asset `
    tests\test_api.py::test_rebalance_uses_base_values_for_usd_position `
    tests\test_api.py::test_assets_expose_eur_reference_prices `
    tests\test_api.py::test_dashboard_counts_short_only_positions
if ($LASTEXITCODE -ne 0) { throw "Gate mirato fallito" }
```

Output osservato: 51 test selezionati passati, un solo warning Starlette/httpx, exit 0.

## Limiti e rischi residui

1. Docker non è disponibile: il parsing YAML e i binding sono stati verificati localmente, ma `docker compose config` e un avvio reale dei container non sono stati validati.
2. I client API che chiamavano direttamente import/allocation apply senza una preview/piano devono ora ottenere e inviare il token; ricevono intenzionalmente 409 se missing/stale. Reset portfolio e delete backtest ricevono intenzionalmente 400 senza conferma backend.
3. Resta una vulnerabilità npm low in `@babel/core`; high e critical sono zero.
4. Il bundle JS principale resta 860,99 kB minificato, oltre la soglia Vite di 500 kB.
5. Restano 937 warning di deprecazione da dipendenze durante pytest.
6. Questa esecuzione usa Python 3.14.7; non sostituisce una matrice esplicita su Python 3.11/3.12 indicati nel piano.
7. L'ambiente Python è un venv locale Git-ignored creato nel worktree; non è una junction verso il venv Task 10 autorizzato.
8. Nello snapshot pre-commit del report, commit/push e confronto remoto `HEAD == git ls-remote` non sono ancora eseguibili; le checkbox Step 6–7 sono preparate per il commit unico ma restano subordinate al gate controller post-push.

## Rollback

Prima di qualsiasi rollback:

1. fermare InvestEdge e verificare che non vi siano listener/lock attivi;
2. creare una copia SQLite consistente del DB corrente e conservarla fuori dal path che verrà ripristinato;
3. verificare `PRAGMA integrity_check` sia sulla copia corrente sia sul backup pre-migrazione scelto;
4. usare soltanto path assoluti verificati e `Copy-Item -LiteralPath`, mai reset Git distruttivi.

Per annullare soltanto il futuro commit Task 11 dopo il merge, individuarlo senza auto-riferimento e creare un revert tracciabile:

```powershell
$task11Commit = git log -1 --format=%H --grep '^docs: verify phase 1 reliability foundations$'
git revert $task11Commit
```

Per annullare l'intera Fase 1 preservando la storia, dopo aver revertito l'eventuale Task 11:

```powershell
git revert 12d080e 4ec9a04 734815d 2dbd14a b488675 c77225e 5f92220 6f6afc6 637b5dd 2d423b2
```

Se il rollback del codice richiede lo schema legacy, arrestare prima l'app ed eseguire il seguente harness dalla root del repository. La directory backup deriva dal parent del DB effettivo risolto da `Settings.from_env()` (anche quando `INVESTEDGE_DB_PATH` è relativo); i candidati automatici pre-reset e pre-migrazione sono elencati separatamente. La scelta resta intenzionalmente manuale e deve identificare un solo file.

```powershell
$rollbackPython = (Resolve-Path '.\backend\.venv\Scripts\python.exe').Path
$effectiveDb = (& $rollbackPython -c "from backend.app.config import Settings; print(Settings.from_env().database_path.resolve())").Trim()
if ($LASTEXITCODE -ne 0 -or -not $effectiveDb) { throw "Impossibile risolvere il DB effettivo" }
$backupDir = Join-Path (Split-Path -Parent $effectiveDb) 'backups'
if (-not (Test-Path -LiteralPath $effectiveDb -PathType Leaf)) { throw "DB corrente assente: $effectiveDb" }
if (-not (Test-Path -LiteralPath $backupDir -PathType Container)) { throw "Directory backup assente: $backupDir" }

$preReset = @(Get-ChildItem -LiteralPath $backupDir -File -Filter 'investedge-*-pre-seed-reset-*.db')
$preMigration = @(Get-ChildItem -LiteralPath $backupDir -File -Filter 'investedge-*-pre-migration-*.db')
"PRE_SEED_RESET_CANDIDATES=$($preReset.Count)"
$preReset | ForEach-Object FullName
"PRE_MIGRATION_CANDIDATES=$($preMigration.Count)"
$preMigration | ForEach-Object FullName

$chosenInput = (Read-Host 'Incolla il path assoluto di UN backup elencato').Trim()
$chosenBackup = (Resolve-Path -LiteralPath $chosenInput -ErrorAction Stop).Path
$allowed = @($preReset + $preMigration | ForEach-Object FullName)
if ($allowed -notcontains $chosenBackup) { throw "Il backup scelto non è uno dei candidati elencati" }

$currentCopy = Join-Path $backupDir ("rollback-current-{0}.db" -f (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'))
if (Test-Path -LiteralPath $currentCopy) { throw "Copia corrente già esistente: $currentCopy" }
@'
import sqlite3
import sys

source_path, target_path = sys.argv[1:]
source = sqlite3.connect(source_path)
target = sqlite3.connect(target_path)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
'@ | & $rollbackPython - $effectiveDb $currentCopy
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $currentCopy -PathType Leaf)) {
    throw "Copia consistente del DB corrente fallita"
}

foreach ($candidate in @($currentCopy, $chosenBackup)) {
    $integrity = (& $rollbackPython -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()" $candidate).Trim()
    if ($LASTEXITCODE -ne 0 -or $integrity -ne 'ok') { throw "Integrity check fallito: $candidate" }
}

Copy-Item -LiteralPath $chosenBackup -Destination $effectiveDb -Force
$restoredIntegrity = (& $rollbackPython -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()" $effectiveDb).Trim()
if ($LASTEXITCODE -ne 0 -or $restoredIntegrity -ne 'ok') { throw "Integrity check del DB ripristinato fallito" }
"ROLLBACK_DB_RESTORE=PASS; CURRENT_COPY=$currentCopy"
```

Non eliminare la copia `rollback-current-*` finché il rollback non è stato validato. Il comando non sceglie automaticamente il backup quando esistono più candidati e non stampa altre variabili d'ambiente.

## Trading reale e roadmap

Il trading reale resta disabilitato. Le sole route di ordine sono simulate (`/orders/simulate`), lo stato scritto è `SIMULATED`, il motore dichiara paper trading e non esiste un adapter broker reale attivo. Nessuna credenziale broker, scraping o automazione Trade Republic è stata introdotta.

La Fase 2, da pianificare separatamente soltanto dopo commit/push e gate remoto della Fase 1, è **Strumenti e dati reali**: catalogo più ampio possibile, instrument master, fonti gratuite, FX, quality tier e budget provider. Portafogli multipli, automazione locale, redesign Calm Intelligence e mobile restano nelle Fasi 3–6.

## Azioni riservate al controller

1. Creare l'unico commit sopra `12d080e` con messaggio esatto `docs: verify phase 1 reliability foundations` e pubblicare `codex/investedge-phase-1-task-11`.
2. Verificare tree pulito, branch, `HEAD` e `git ls-remote origin codex/investedge-phase-1-task-11` identici; solo allora considerare effettivamente soddisfatte Step 6–7.
