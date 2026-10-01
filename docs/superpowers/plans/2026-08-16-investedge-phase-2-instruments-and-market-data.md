# InvestEdge Phase 2 Instruments and Market Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consegnare un instrument master disambiguato, un catalogo dinamico e versionato, osservazioni di mercato con provenienza e freschezza, provider gratuiti governati da budget, FX verso EUR, refresh lazy e misure di copertura nel Data Center, preservando integralmente i contratti della Fase 1.

**Architecture:** `assets` resta la facciata dell'universo attivo compatibile con la Fase 1; un nuovo instrument master separa entità economica, listing, identificativi e simboli provider. I payload dei provider passano attraverso trasporto sicuro, budget manager, validazione e osservazioni append-only prima di alimentare il read model `price_history`. Catalogo e prezzi sono più ampi dell'universo attivo ma non attivano scansioni indiscriminate: una coda lazy assegna priorità esplicite. Ogni pacchetto vive in una nuova task/worktree, parte dal branch remoto completato precedente e produce un solo commit pubblicato e verificato.

**Tech Stack:** Python 3.11/3.12, FastAPI, Pydantic, SQLite, httpx, pypdf, pandas, pytest, Ruff, React 18, TypeScript 5.6, Vite 7, Vitest, Testing Library, Tailwind CSS, PowerShell e Git/GitHub.

## Global Constraints

- Specifica approvata e autoritativa: `docs/superpowers/specs/2026-08-16-investedge-broker-grade-redesign-design.md`, esclusivamente sezione Fase 2.
- Piano precedente e baseline verificata: `docs/superpowers/plans/2026-08-16-investedge-phase-1-foundations.md` e `docs/reports/2026-08-16-phase-1-verification.md`.
- Branch di integrazione del piano: `codex/investedge-phase-2-plan`; il suo parent obbligatorio è `2e7451898a8be2c02083eb82ddd718df77e61afe`, pubblicato anche come `origin/codex/investedge-phase-1-task-11`.
- Lo scope comprende solo instrument master, catalogo, risoluzione identificativi/listing, tier di qualità, osservazioni di mercato, provider gratuiti e fallback, FX EUR, budget/priorità lazy, copertura e aggiornamenti mirati di Universe/Data Center.
- Sono esclusi: portafogli multipli e paper broker (Fase 3), scheduler/risk automation (Fase 4), redesign completo a cinque hub (Fase 5), mobile/auth (Fase 6), trading reale, credenziali broker, scraping o automazione dell'interfaccia Trade Republic.
- `assets` continua a rappresentare soltanto gli strumenti attivati dall'utente. Il catalogo ampio non entra in `assets` e non cambia il significato di `/assets`, dashboard, watchlist, news, ML o refresh esistenti.
- Tutte le estensioni di API sono additive. I campi Fase 1 restano presenti con la stessa semantica, inclusi valori nativi e campi `*_base` in EUR, `base_currency: "EUR"`, prezzi/eseguiti storici e cambio congelato al momento dell'operazione.
- I token preview/apply di import e allocation restano SHA-256 canonici, confrontati con `hmac.compare_digest`; una risoluzione ambigua non può cambiare silenziosamente l'oggetto tra preview e apply e deve produrre HTTP 409 senza mutazioni.
- Ogni migrazione passa da `prepare_database(reason="pre-migration", backup_existing=True)`. Un errore di backup, schema o backfill è fail-closed; purge e reset mantengono conferma, backup e rollback della Fase 1.
- Nessun secret è ammesso in URL, query string, log, eccezioni, fingerprint, cache, fixture, report o risposta API. Le chiavi opzionali viaggiano solo in header; un provider che non offre autenticazione compatibile resta disabilitato con motivo esplicito.
- Non eseguire chiamate live nei test o negli smoke test. Tutti i payload provider sono fixture registrate da documentazione ufficiale oppure sintetiche, minime, ridotte e prive di secret.
- Non richiedere credenziali e non abilitare servizi a pagamento. I limiti sono policy locali conservative, non una promessa sulla disponibilità futura; HTTP 429 e header ufficiali possono ridurre dinamicamente il budget.
- Nessun refresh bulk del catalogo. Le sole unità di lavoro ammesse sono listing/capability espliciti e batch limitati scelti dal planner prioritario.
- I dati non validi, mancanti, stale, futuri, non finiti, incoerenti, in valuta inattesa o provenienti da mapping ambiguo non sovrascrivono l'ultimo dato valido. Le ragioni sono persistite con codici stabili e sanitizzati.
- I fallback sono ammessi soltanto tra provider/listing/capability/valuta/sessione compatibili. L'uso del fallback e la sua freschezza sono visibili; divergenza oltre soglia sospende la promozione e non viene mediata in silenzio.
- Non usare `npm audit fix --force`, force-push, push su `main`, PR, merge, reset distruttivi o cancellazioni ricorsive.
- **Override utente 2026-09-30:** push del branch di ogni task e merge fast-forward su `main` ai gate di fase verificati sono autorizzati. Stato, eccezioni ed evidenze sono in `PROGRAMMA-OPERATIVO.md`, che prevale su questo piano per stato e ordine dei lavori.
- Un solo writer modifica i file di ciascun Task. Subagent e reviewer eseguono analisi o review read-only e restituiscono rilievi al writer.

## Protocollo automatico: una nuova chat per ogni Task

Il termine “Task” indica un pacchetto minimo, coerente e indipendentemente revisionabile; le checkbox interne sono i passi TDD dello stesso pacchetto.

1. L'orchestratore legge integralmente specifica e piano, individua il primo Task non completato e apre una sola nuova task Codex in worktree isolato. I Task sono strettamente sequenziali: non esistono esecuzioni speculative o parallele.
2. Il branch del Task è `codex/investedge-phase-2-task-N`. Task 1 parte da `origin/codex/investedge-phase-2-plan`; ogni Task successivo parte esattamente da `origin/codex/investedge-phase-2-task-(N-1)`.
3. Prima di modificare file, l'esecutore verifica la base remota con questi comandi PowerShell, sostituendo esclusivamente i due valori indicati nel blocco del Task:

```powershell
$taskBaseRef = "origin/codex/investedge-phase-2-plan"
$taskBaseRemoteRef = "refs/heads/codex/investedge-phase-2-plan"
git fetch origin ($taskBaseRemoteRef -replace '^refs/heads/', '')
$taskBaseSha = (git rev-parse $taskBaseRef).Trim()
$taskRemoteSha = ((git ls-remote origin $taskBaseRemoteRef) -split "\s+")[0]
if ($LASTEXITCODE -ne 0 -or -not $taskRemoteSha -or $taskBaseSha -ne $taskRemoteSha) { throw "Base remota non verificata" }
git status --short
git branch --show-current
git rev-parse HEAD
```

Expected: working tree pulito, branch del Task corretto, `HEAD == $taskBaseSha == $taskRemoteSha`. Se il worktree non è sul branch esatto o contiene modifiche, fermarsi senza correggere la storia Git.

4. Il prompt della nuova task include numero/titolo, branch, base remota, SHA verificato, path completi autorizzati, contratti consumati/prodotti, caller da preservare e il divieto di iniziare il Task successivo.
5. L'esecutore usa `superpowers:test-driven-development`: scrive il test focalizzato, esegue il comando RED e conferma che fallisca per la ragione prevista, implementa il minimo, quindi esegue GREEN. Per qualsiasi anomalia, failure inattesa o comportamento intermittente usa `superpowers:systematic-debugging` prima di cambiare codice.
6. Prima del commit esegue test mirati, Ruff/type/build pertinenti, `git diff --check`, review completa del diff e `superpowers:requesting-code-review`. Ogni rilievo Critical o Important viene corretto e riverificato nella stessa task.
7. Prima di dichiarare completato usa `superpowers:verification-before-completion`, aggiorna soltanto le checkbox del proprio Task, crea un solo commit con il messaggio esatto indicato e pubblica esclusivamente il branch corrente con:

```powershell
git push -u origin HEAD
```

8. Dopo il push, task e orchestratore eseguono il gate remoto:

```powershell
$taskHead = (git rev-parse HEAD).Trim()
$taskParent = (git rev-parse HEAD^).Trim()
$taskUpstream = (git rev-parse --abbrev-ref --symbolic-full-name '@{u}').Trim()
$taskRemote = ((git ls-remote origin ("refs/heads/" + (git branch --show-current))) -split "\s+")[0]
git status --short
git rev-list --count "$taskParent..$taskHead"
if ($taskUpstream -ne ("origin/" + (git branch --show-current))) { throw "Upstream errato" }
if ($taskRemote -ne $taskHead) { throw "Remote e HEAD divergono" }
```

Expected: working tree pulito, count `1`, upstream del branch corrente, `ls-remote == HEAD`. L'orchestratore controlla inoltre che `$taskParent` sia lo SHA remoto verificato del Task precedente.

9. Se un gate fallisce, la correzione resta nella stessa task e nello stesso branch; non si apre un nuovo Task. Un secondo commit è vietato: prima del push si amenda il commit locale, dopo il push ci si ferma e si richiede decisione esplicita senza force-push.
10. La task completata resta consultabile con riepilogo di file, test, review, HEAD/parent e remote ref. L'apertura del Task seguente è autorizzata solo dopo il gate remoto verde.
11. Il Task 18 produce il branch finale lineare e il report di verifica. PR, merge o push su `main` richiedono una decisione separata e non fanno parte del piano.

---

## Mappa della baseline e confini di compatibilità

- Persistenza: `backend/app/database.py` inizializza `BASE_SCHEMA`, applica migrazioni additive basate sulla presenza colonne e crea gli indici. `assets`, `price_history`, `api_cache`, `api_usage` e `fx_rates` sono le tabelle da integrare, non da sostituire distruttivamente.
- Identità legacy: `assets` è unico per `(symbol, asset_type)`; diversi servizi risolvono `UPPER(symbol)=UPPER(?) LIMIT 1`. Il nuovo master usa ID interni e listing; gli endpoint legacy accettano il simbolo solo quando il match nell'universo attivo è univoco, altrimenti HTTP 409.
- Prezzi legacy: portfolio, allocation, dashboard, technical analysis, signals, backtest, ML, import Google Sheets e news leggono `assets`/`price_history`. Il nuovo layer mantiene un projection adapter e non cambia in blocco questi caller.
- API: restano compatibili `/assets`, `/assets/{symbol}`, `/prices/{symbol}`, `/data/status`, `/data/status/{symbol}`, `/data/refresh/{symbol}`, `/data/refresh-all` e `/data/usage`; nuovi endpoint usano `instrument_id` o `listing_id`.
- Frontend: `/universe` e `/data` esistono già. Gli interventi di Fase 2 estendono `UniversePage.tsx` e `DataCenterPage.tsx` senza introdurre la navigazione a cinque hub.
- Sicurezza Fase 1: il ciclo preview/apply, i backup fail-closed, la sanitizzazione delle configurazioni e il calcolo EUR sono contratti bloccanti, coperti dai test esistenti.

## Assunzioni provider verificate il 2026-08-16

- [Catalogo ufficiale Trade Republic Italia](https://assets.traderepublic.com/assets/files/IT/Instrument_Universe_IT_en.pdf): il PDF corrente contiene nome e ISIN, ma non espone una data di aggiornamento affidabile, MIC, valuta o conferma di negoziabilità corrente. Ogni acquisizione è quindi versionata con SHA-256 e `retrieved_at`; non equivale a disponibilità permanente.
- [OpenFIGI API](https://www.openfigi.com/api/documentation): l'accesso senza chiave ha limiti inferiori e mapping batch conservativo di 5 job; con chiave opzionale il segreto usa `X-OPENFIGI-APIKEY`. HTTP 429 e header di rate limit governano il budget effettivo.
- [ECB Data API](https://data.ecb.europa.eu/help/api/data): l'endpoint HTTPS ufficiale supporta serie EXR, filtri temporali, `updatedAfter` e `If-Modified-Since`; è la fonte primaria per FX verso EUR.
- [Alpha Vantage support](https://www.alphavantage.co/support/) e [pricing](https://www.alphavantage.co/premium/): il piano gratuito dichiara 25 richieste/giorno e il realtime USA è premium. Poiché l'autenticazione documentata usa query parameter, Alpha resta disabilitato dalla policy “nessun secret in URL”, senza aggiramenti.
- [Finnhub pricing](https://finnhub.io/pricing) e [API documentation](https://finnhub.io/docs/api): il piano gratuito è per uso personale, dichiara 60 richieste/minuto e copertura USA; il token può viaggiare nell'header `X-Finnhub-Token`. In Fase 2 si usa soltanto quote snapshot USA, non candle premium né copertura internazionale realtime.
- [CoinGecko Demo pricing](https://www.coingecko.com/en/api/pricing) e [keyless public API](https://docs.coingecko.com/docs/keyless-public-api): Demo dichiara 10.000 crediti/mese e 100 richieste/minuto; la modalità keyless è solo best-effort, con limite IP. Il piano applica margini locali inferiori e attribuzione visibile.
- [FRED API v1 series observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html), [FRED API v2](https://fred.stlouisfed.org/docs/api/fred/v2/) e [Terms of Use](https://fred.stlouisfed.org/docs/api/terms_of_use.html): v1 espone la chiave come query parameter; v2 accetta Bearer header ma offre soltanto download per release, non lookup lazy della singola serie. Entrambi sono incompatibili con almeno una policy bloccante di questa fase, quindi FRED resta reference locale/disabilitato e il Data Center mostra motivo e attribuzione obbligatoria.
- [Stooq](https://stooq.com/): è disponibile una distribuzione storica gratuita, ma non è stata individuata documentazione ufficiale stabile di API, SLA, schema o limiti. L'adapter è opt-in, EOD, fail-soft e fixture-first; un cambiamento upstream non può interrompere il read model valido.
- “Copertura massima” significa massimizzare e misurare, a parità di budget e policy, strumenti risolti e osservabili. Non implica una percentuale statica, realtime universale o disponibilità garantita.

---

### Task 1: Introdurre instrument master, listing e identificativi senza ampliare `assets`

**Branch:** `codex/investedge-phase-2-task-1`

**Base remota esatta:** `origin/codex/investedge-phase-2-plan`; il suo SHA è il commit che contiene questo piano e deve coincidere con `refs/heads/codex/investedge-phase-2-plan` via `git ls-remote`.

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/instrument_service.py`
- Modify: `backend/app/services/assets_service.py`
- Modify: `backend/app/api/routes.py`
- Modify: `tests/test_database.py`
- Modify: `tests/test_api.py`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Conservare ID e righe `assets`, tutte le FK esistenti, `AssetCreate`, `AssetOut`, `/assets`, portfolio, allocation, price, dashboard, technical analysis, signals, backtest, ML, import e news. Il backfill non inventa MIC, FIGI, venue o ISIN e non assegna ISIN a crypto/FX.

**Interfaces — Consumes:** schema SQLite legacy; `assets.id/symbol/name/asset_type/exchange/currency/isin`; `prepare_database()`; `assets_service.get_asset_by_symbol()`.

**Interfaces — Produces:**

```text
InstrumentType = Literal["STOCK", "ETF", "BOND", "ETC", "ETN", "CRYPTO", "FX", "INDEX", "RATE", "MACRO", "UNKNOWN"]
AssetClass = Literal["EQUITY", "FUND", "FIXED_INCOME", "COMMODITY", "CRYPTO", "FX", "REFERENCE", "UNKNOWN"]
QualityTier = Literal["QUALIFIED", "OBSERVABLE", "REFERENCE_ONLY"]
IdentifierScheme = Literal["ISIN", "FIGI", "OPENFIGI_TICKER", "COINGECKO_ID", "FRED_SERIES_ID", "ECB_SERIES_KEY"]

@dataclass(frozen=True)
class ListingKey:
    instrument_id: int
    ticker: str
    mic: str | None
    currency: str

class InstrumentService:
    @staticmethod
    def backfill_active_assets(connection: sqlite3.Connection) -> int
    @staticmethod
    def require_unique_active_asset(connection: sqlite3.Connection, symbol: str) -> sqlite3.Row | None
class AmbiguousInstrumentError(ValueError):
    symbol: str
    candidate_listing_ids: Sequence[int]
```

Nuove tabelle additive: `instruments`, `instrument_identifiers`, `instrument_identifier_attestations`, `instrument_listings`, `provider_symbols`; nuova colonna nullable `assets.instrument_listing_id`. `instruments` contiene nome canonico, tipo/classe, tier iniziale `REFERENCE_ONLY`, source/date e timestamp. `instrument_identifiers` conserva `scheme`, `normalized_value`, scope `INSTRUMENT|LISTING` e owner ID; ISIN e FIGI hanno unicità globale su `(scheme, normalized_value)` e non includono la fonte. `instrument_identifier_attestations` collega più fonti/timestamp/evidence hash alla stessa identità canonica. `instrument_listings` contiene ticker, MIC nullable, venue nullable, currency, timezone nullable, stato listing, `trade_republic_status` (`NEVER_SEEN`, `CATALOGED`, `VERIFIED`, `UNAVAILABLE`), `trade_republic_cataloged_at` e `trade_republic_verified_at`; quando MIC è noto, `(UPPER(ticker), UPPER(mic), UPPER(currency))` è globalmente unico. `provider_symbols` è versionato con provider, listing, capability, normalized symbol, status `CANDIDATE|VERIFIED|RETIRED`, source, observed/verified timestamp, evidence hash e `supersedes_provider_symbol_id`. Due indici univoci parziali, entrambi con `WHERE status='VERIFIED'`, impongono un solo record corrente sia per `(provider, listing_id, capability)` sia per `(provider, capability, normalized_symbol)`: lo stesso simbolo provider non può attribuire dati a listing diversi; dopo il retirement esplicito può essere riusato da una nuova versione.

- [x] **Step 1: Scrivere i test di migrazione e identità**

In `tests/test_database.py` aggiungere casi database nuovo e legacy che provino: creazione delle cinque tabelle/indici; colonna nullable su `assets`; backfill idempotente; conservazione degli ID; due listing omonimi su MIC diversi ammessi; collisione `(ticker, MIC, currency)` bloccata; stesso ISIN/FIGI attestato da fonti diverse ricondotto allo stesso instrument; tentativo concorrente di legare lo stesso identificativo a due instrument bloccato; lifecycle provider symbol; tentativi concorrenti di verificare lo stesso `(provider, capability, normalized_symbol)` su listing diversi bloccati; retirement e successivo riuso su un altro listing ammessi; nessuna identità inventata; backup chiamato prima della migrazione. In `tests/test_api.py` provare che `/assets` e `AssetOut` sono byte-for-byte compatibili nei campi preesistenti e che un lookup legacy ambiguo risponde 409.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_database.py tests\test_api.py -k "instrument_master or instrument_listing or legacy_symbol_ambiguity or assets_contract" -q
```

Expected: failure perché schema, backfill e gestione 409 non esistono; nessun failure estraneo alla selezione.

- [x] **Step 3: Aggiungere schema e backfill additivi**

In `BASE_SCHEMA` creare le tabelle per database nuovi; in `MIGRATIONS` aggiungere soltanto `assets.instrument_listing_id`. In `migrate_db()` eseguire un backfill transazionale e deterministico: una riga legacy genera un instrument e un listing con ticker uppercase, valuta uppercase, MIC/timezone null se non verificati; l'ISIN viene copiato solo se già presente, conforme al pattern `^[A-Z]{2}[A-Z0-9]{9}[0-9]$` e il tipo non è crypto/FX. Normalizzare ISIN/FIGI senza spazi e uppercase; per ticker/provider symbol applicare normalizzazione provider-specifica senza perdere il valore display. Usare transazione `BEGIN IMMEDIATE`, vincoli globali e attestazioni per rendere il rerun idempotente e impedire false duplicazioni cross-source.

- [x] **Step 4: Rendere esplicita l'ambiguità legacy**

`require_unique_active_asset()` esegue una query senza `LIMIT 1`: zero righe restituisce `None`, una riga restituisce il record, più righe solleva `AmbiguousInstrumentError(symbol, candidate_listing_ids)`. `assets_service` mappa l'errore a HTTP 409 senza modificare i payload di successo. Non migrare ancora tutti i caller a `listing_id`.

- [x] **Step 5: Eseguire GREEN e regressione Fase 1 mirata**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_database.py tests\test_api.py tests\test_portfolio_accounting.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\database.py backend\app\models backend\app\services\instrument_service.py backend\app\services\assets_service.py tests\test_database.py tests\test_api.py
```

Expected: tutti i test selezionati passano; Ruff termina con `All checks passed!`; portfolio/EUR e API legacy restano verdi.

- [x] **Step 6: Review, commit e gate remoto**

Eseguire `git diff --check`, review del diff e review indipendente focalizzata su migrazione reversibile, duplicati e caller symbol-only. Correggere ogni rilievo Critical/Important e rieseguire Step 5.

```powershell
git add backend/app/database.py backend/app/models/schemas.py backend/app/models/__init__.py backend/app/services/instrument_service.py backend/app/services/assets_service.py backend/app/api/routes.py tests/test_database.py tests/test_api.py docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add instrument master and listing identity"
git push -u origin HEAD
```

Expected: un solo commit sopra la base, branch remoto `codex/investedge-phase-2-task-1`, working tree pulito e `ls-remote == HEAD` secondo il protocollo.

---

### Task 2: Centralizzare trasporto sicuro e budget provider

**Branch:** `codex/investedge-phase-2-task-2`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-1`.

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Create: `backend/app/data_providers/transport.py`
- Create: `backend/app/services/provider_budget_service.py`
- Modify: `backend/app/data_providers/base.py`
- Modify: `backend/app/data_providers/news_base.py`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Create: `tests/test_provider_budget.py`
- Modify: `tests/test_api.py`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** `BaseMarketDataProvider.get_daily_prices()`, `BaseNewsProvider.get_news_for_symbol()`, cache `api_cache`, contatori `api_usage`, `DataProviderStatusOut` e `/data/usage` continuano a funzionare. FastAPI route, `MarketDataService`, `NewsEngine` e `FXService` sono sincroni: transport, adapter e planner restano sincroni end-to-end. I provider esistenti possono essere migrati uno per volta; nessuna chiave esistente viene esposta.

**Interfaces — Consumes:** `api_cache.request_url_hash`, `api_usage`, `Settings`, client `httpx`, provider `normalize_prices()`.

**Interfaces — Produces:**

```text
ProviderCapability = Literal["CATALOG", "IDENTITY", "EOD", "QUOTE", "FX", "REFERENCE", "NEWS"]
BudgetWindow = Literal["MINUTE", "DAY", "MONTH"]
RequestOutcome = Literal["SUCCEEDED", "CACHE_HIT", "RATE_LIMITED", "TIMED_OUT", "RETRY_EXHAUSTED", "REJECTED", "DISABLED"]
AvailabilityState = Literal["AVAILABLE", "DISABLED", "COOLDOWN"]

ProviderBudgetPolicy {
    minute_limit: int | None
    daily_limit: int | None
    monthly_limit: int | None
    max_attempts: int = 3
}

ProviderBudgetManager.reserve(connection: sqlite3.Connection, policy: ProviderBudgetPolicy, provider: str, operation: str, request_fingerprint: str, now: datetime) -> reservation_id: str
ProviderBudgetManager.complete(connection: sqlite3.Connection, reservation_id: str, outcome: RequestOutcome, status_code: int | None, retry_count: int, cooldown_until: datetime | None) -> None

ProviderAvailability {
    state: AvailabilityState
    reason_code: Literal["MISSING_CREDENTIAL", "SECRET_IN_QUERY_POLICY", "BULK_ONLY_POLICY", "NOT_PRIMARY_POLICY", "OPT_IN_DISABLED", "RATE_LIMITED", "BUDGET_EXHAUSTED", "UNSUPPORTED_CAPABILITY"] | None
    cooldown_until: datetime | None
}

ProviderResponse {
    status_code: int
    payload: object
    from_cache: bool
    attempts: int
    request_fingerprint: str
}

SafeProviderTransport.request(
    connection: sqlite3.Connection,
    policy: ProviderBudgetPolicy,
    provider: str,
    method: Literal["GET", "POST"],
    base_url: str,
    path: str,
    headers: Mapping[str, str],
    params: Mapping[str, str],
    json_body: Mapping[str, object] | Sequence[Mapping[str, object]] | None,
    operation: str,
    cache_scope: str,
    cache_ttl_seconds: int,
    max_response_bytes: int,
    decoder: Literal["json", "csv", "bytes"],
    now: datetime,
    sleeper: Callable[[float], None],
    bypass_cache: bool = False,
) -> ProviderResponse

SafeProviderTransport.with_client(client: httpx.Client) -> SafeProviderTransport
```

Nuove tabelle: `provider_usage_windows` con chiave `(provider, window_kind, window_start)` e `provider_request_log` con fingerprint SHA-256, operation, outcome, status/cooldown/retry e timestamp. Non persistono URL, query, header o corpo raw.

- [x] **Step 1: Scrivere i test RED del budget e della redazione**

Copertura obbligatoria: reservation atomica; limiti minuto/giorno/mese; rollback della reservation non consumata; cache hit prima della quota; `bypass_cache=true` con cache preesistente produce una richiesta fisica governata; due richieste force concorrenti con lo stesso fingerprint vengono coalesciate in-flight in una sola richiesta fisica; una reservation per ogni tentativo HTTP fisicamente inviato; GET e POST JSON canonico; hash del body OpenFIGI senza payload raw; limite byte/decompressione prima del decode; content-type allowlist; redirect rifiutato; HTTP 429 con `Retry-After` e rate-limit header ufficiali; retry soltanto per timeout, 429, 500, 502, 503, 504; backoff deterministico con clock/sleeper iniettati; nessun retry per 400/401/403/404; divieto dei parametri case-insensitive `apikey`, `api_key`, `token`, `access_token`, `key`; eccezioni/log/API senza secret sentinella.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_provider_budget.py tests\test_api.py -k "provider_budget or safe_transport or secret_redaction or data_usage_compat" -q
```

Expected: failure per moduli/tabelle mancanti e per mancata policy su query sensibili.

- [x] **Step 3: Implementare reservation e finestra temporale**

Normalizzare `window_start` in UTC: minuto `YYYY-MM-DDTHH:MM:00Z`, giorno `YYYY-MM-DD`, mese `YYYY-MM`. `reserve()` apre `BEGIN IMMEDIATE`, verifica tutte le finestre e crea una reservation unica; se una finestra è esaurita non incrementa nessun contatore. `complete()` è idempotente. Conservare `api_usage` come projection giornaliera per i caller Fase 1.

- [x] **Step 4: Implementare il trasporto fail-closed**

Accettare solo HTTPS e host allowlistati dal singolo adapter, `follow_redirects=False`, path separato e `base_url` privo di query/fragment/userinfo. Rifiutare qualsiasi query già incorporata nell'URL e qualsiasi secret nei params prima di costruire la richiesta. Il fingerprint usa `provider + operation + host + path + parametri non sensibili ordinati + SHA-256 del JSON canonico`, mai `str(request.url)`; il body raw non entra in DB/log. Controllare content type atteso e applicare `max_response_bytes` ai byte decompressi mentre si legge lo stream, prima del decode. Calcolare sempre il fingerprint e consultare sempre la deduplica in-flight prima di prenotare; consultare la cache persistente soltanto quando `bypass_cache=false`. `bypass_cache=true` salta esclusivamente il lookup della cache: non cambia fingerprint, in-flight dedupe, reservation/quota/cooldown, retry, validazione o scrittura della nuova risposta valida in cache. Ogni tentativo realmente inviato riserva quota e registra l'esito. Usare timeout espliciti, massimo 3 tentativi e delay `min(2 ** retry_index, 8)` secondi, rispettando un `Retry-After` numerico più lungo fino a 60 secondi e abbassando il budget/cooldown quando gli header ufficiali sono più restrittivi. `with_client()` sostituisce soltanto il client HTTP per fixture/test e conserva manager, cache, deduplica, policy, redazione e clock del transport; non esiste un percorso client diretto che bypassi `request()`. Le eccezioni pubbliche contengono solo provider, operation e codice stabile.

- [x] **Step 5: Adattare `BaseMarketDataProvider` senza cambiare il contratto legacy**

Iniettare transport e budget manager in `BaseMarketDataProvider` e `BaseNewsProvider`, mantenendo le firme sincrone `get_daily_prices(symbol, force=False) -> tuple[list[dict], bool]` e `get_news_for_symbol(symbol, force=False) -> tuple[list[dict], bool]`. Entrambi propagano letteralmente `force` come `bypass_cache=force` alla singola chiamata transport, senza usarlo per nessun altro gate. Eliminare hashing/cache basati sull'URL costruito in `news_base.py`; il contatore `calls_today` deriva dalla projection esistente. I nuovi dettagli saranno esposti additivamente nel Task 16.

- [x] **Step 6: Eseguire GREEN e regressione sicurezza**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_provider_budget.py tests\test_api.py tests\test_alert_service.py tests\test_import_security.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\config.py backend\app\data_providers backend\app\services\provider_budget_service.py tests\test_provider_budget.py tests\test_api.py
```

Expected: suite selezionata verde; sentinelle secret assenti; Ruff `All checks passed!`.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente focalizzata su race SQLite, doppio consumo quota, retry storm, SSRF, secret in eccezioni/cache e compatibilità `api_usage`. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add backend/app/database.py backend/app/config.py backend/app/data_providers/transport.py backend/app/services/provider_budget_service.py backend/app/data_providers/base.py backend/app/data_providers/news_base.py .env.example backend/.env.example tests/test_provider_budget.py tests/test_api.py docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add provider budget and safe transport"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 1, working tree pulito e gate remoto completo.

---

### Task 3: Importare e versionare il catalogo ufficiale Trade Republic

**Branch:** `codex/investedge-phase-2-task-3`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-2`.

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Modify: `backend/requirements.txt`
- Create: `backend/app/data_providers/trade_republic_catalog.py`
- Create: `backend/app/services/catalog_service.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/routes.py`
- Create: `tests/fixtures/catalogs/trade_republic_it_excerpt.pdf`
- Create: `tests/fixtures/catalogs/trade_republic_it_excerpt.expected.json`
- Create: `tests/test_instrument_catalog.py`
- Modify: `tests/test_database.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Non creare righe `assets`, non cambiare `/assets` e non eseguire price refresh. Il PDF è fonte storica di appartenenza al catalogo, non prova di tradability corrente. `prepare_database()` resta il gate per lo schema.

**Interfaces — Consumes:** URL ufficiale fisso del PDF; `SafeProviderTransport` con decoder bytes; instrument master; `pypdf==6.16.1`; timestamp UTC iniettato.

**Interfaces — Produces:**

```text
CatalogEntryStatus = Literal["ACCEPTED", "REJECTED", "AMBIGUOUS"]
CatalogReason = Literal["VALID_ISIN", "INVALID_ISIN", "MISSING_ISIN", "MISSING_NAME", "DUPLICATE_IN_SNAPSHOT", "UNSUPPORTED_ROW"]
CatalogSnapshotStatus = Literal["COMPLETE", "FAILED"]
CatalogFailureReason = Literal["DOWNLOAD_FAILED", "PAYLOAD_TOO_LARGE", "PARSER_ERROR", "EMPTY_CATALOG"]

@dataclass(frozen=True)
class CatalogIngestResult:
    snapshot_id: int
    content_sha256: str
    accepted: int
    rejected: int
    ambiguous: int
    unchanged: bool

@dataclass(frozen=True)
class ParsedCatalogRow:
    row_number: int
    isin: str | None
    name: str | None
    status: CatalogEntryStatus
    reason_code: CatalogReason
    raw_row_sha256: str

def parse_trade_republic_pdf(payload: bytes) -> list[ParsedCatalogRow]
def ingest_trade_republic_catalog(connection, payload: bytes, retrieved_at: datetime) -> CatalogIngestResult

POST /data/catalog/refresh?force=false -> CatalogIngestResult
```

Nuove tabelle: `catalog_snapshots(source, source_url, content_sha256, retrieved_at, source_date, row_count, status, parser_version, failure_reason_code)` e `catalog_entries(snapshot_id, row_number, isin, name, parse_status, reason_code, raw_row_sha256, instrument_id, listing_id)`. `failure_reason_code` accetta soltanto `CatalogFailureReason`, è `NULL` per COMPLETE e non contiene testo provider/eccezioni. `content_sha256` è obbligatorio e unico per source sugli snapshot COMPLETE, ma può essere `NULL` su FAILED quando download/size falliscono prima di ottenere un payload completo; gli snapshot precedenti non vengono cancellati.

- [x] **Step 1: Preparare fixture minima e test RED**

La fixture PDF contiene esclusivamente righe sintetiche rappresentative della struttura ufficiale: due ISIN validi, un duplicato, una riga senza ISIN e una pagina intestazione. L'expected JSON elenca valori e reason code senza copiare il catalogo completo. Testare limite byte, PDF malformato, zero righe, parsing multipagina, checksum, idempotenza dello stesso payload, nuova versione per payload diverso e route manuale con transport fixture. Con cache preesistente, `force=false` produce cache hit; `force=true` propaga `bypass_cache=true`, produce una sola richiesta fisica governata e aggiorna la cache. Due refresh force concorrenti dello stesso URL/fingerprint vengono deduplicati in-flight. Verificare i reason code FAILED `DOWNLOAD_FAILED`, `PAYLOAD_TOO_LARGE`, `PARSER_ERROR`, `EMPTY_CATALOG`; un failure di backup/pre-migration non scrive alcuno snapshot. La route non accetta URL/body, usa soltanto l'URL ufficiale fisso e non è chiamata all'avvio.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_instrument_catalog.py tests\test_database.py tests\test_api.py -k "catalog or trade_republic" -q
```

Expected: import/module o assert falliscono perché parser e tabelle non esistono.

- [x] **Step 3: Implementare parser limitato e deterministico**

Fissare host/path ufficiale, timeout tramite transport e dimensione massima 32 MiB. Il parser accetta solo righe con ISIN verificato anche nel check digit ISO 6166 e nome non vuoto; normalizza spazi Unicode, preserva il nome leggibile, calcola hash della riga normalizzata. `source_date` resta `NULL` quando il PDF non la dichiara; non derivarla dal nome file o dagli header HTTP.

- [x] **Step 4: Implementare ingest versionato**

La transazione inserisce snapshot COMPLETE+entries solo dopo parsing completo. In caso di download/size/parser/empty failure, dopo il rollback registra al massimo uno snapshot FAILED con checksum nullable, retrieved_at e `CatalogFailureReason` sanitizzato, senza entries e senza sostituire il latest COMPLETE. Un failure del backup/pre-migration resta invece fail-closed e non apre alcuna transazione applicativa né registra FAILED. Lo stesso SHA COMPLETE restituisce `unchanged=True`; un nuovo SHA crea una versione e conserva la precedente. Duplicati intra-snapshot sono `REJECTED/DUPLICATE_IN_SNAPSHOT`; nessuna scelta arbitraria tra omonimi. Associare o creare soltanto l'entità instrument per ISIN univoco, lasciando listing/MIC/currency irrisolti.

- [x] **Step 5: Collegare l'entrypoint manuale senza scheduler**

`POST /data/catalog/refresh` chiama transport e ingest una sola volta, applica timeout/32 MiB/budget e restituisce 200 anche per snapshot invariato. Propaga `force` esclusivamente come argomento `bypass_cache=force` di `SafeProviderTransport.request()`: anche con force restano invariati quota/cooldown, fingerprint, deduplica in-flight e validazione. Errori download/parser/backup sono sanitizzati e non lasciano snapshot `COMPLETE`; nessun caller automatico o refresh-all invoca questa route.

- [x] **Step 6: Eseguire GREEN, audit dipendenze e regressione DB**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pip install -r backend\requirements.txt
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_instrument_catalog.py tests\test_database.py tests\test_api.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\trade_republic_catalog.py backend\app\services\catalog_service.py tests\test_instrument_catalog.py
& '.\backend\.venv\Scripts\python.exe' -m pip check
```

Expected: test verdi, Ruff verde, `No broken requirements found.`; nessuna richiesta di rete durante pytest.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente su parser non fidato, decompression/size limit, check digit, idempotenza, rollback, copyright della fixture e assenza di mutazioni `assets`. Correggere Critical/Important e ripetere Step 5.

```powershell
git diff --check
git add backend/app/database.py backend/app/config.py backend/requirements.txt backend/app/data_providers/trade_republic_catalog.py backend/app/services/catalog_service.py backend/app/models/schemas.py backend/app/api/routes.py tests/fixtures/catalogs/trade_republic_it_excerpt.pdf tests/fixtures/catalogs/trade_republic_it_excerpt.expected.json tests/test_instrument_catalog.py tests/test_database.py tests/test_api.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add versioned Trade Republic catalog"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 2 e gate remoto verde.

---
### Task 4: Risolvere identificativi e disambiguare venue, valuta e tipo con OpenFIGI

**Branch:** `codex/investedge-phase-2-task-4`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-3`.

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/data_providers/openfigi.py`
- Create: `backend/app/services/instrument_resolution_service.py`
- Modify: `backend/app/api/routes.py`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Create: `tests/fixtures/catalogs/openfigi_mapping_success.json`
- Create: `tests/fixtures/catalogs/openfigi_mapping_ambiguous.json`
- Create: `tests/fixtures/catalogs/openfigi_mapping_unmatched.json`
- Create: `tests/test_instrument_resolution.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Nessun lookup legacy sceglie il primo candidato. Questo Task registra resolution evidence ma non modifica ancora import/allocation; il Task seguente le lega ai token. Nessun ISIN viene generato per crypto/FX.

**Interfaces — Consumes:** `catalog_entries` accettate; OpenFIGI `/v3/mapping`; transport/budget Task 2; `OPENFIGI_API_KEY` opzionale solo header; instrument/listing/identifier Task 1.

**Interfaces — Produces:**

```text
ResolutionStatus = Literal["RESOLVED", "AMBIGUOUS", "UNMATCHED", "REJECTED"]
ResolutionReason = Literal[
    "EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE",
    "MULTIPLE_COMPATIBLE_CANDIDATES",
    "NO_PROVIDER_MATCH",
    "TYPE_MISMATCH",
    "CURRENCY_MISMATCH",
    "MISSING_CURRENCY",
    "MISSING_VENUE",
    "MISSING_TIMEZONE",
    "INVALID_PROVIDER_PAYLOAD",
]
ListingMetadataSource = Literal["OFFICIAL_VENUE", "ISSUER_FACTSHEET", "LEGACY_ACTIVE_ASSET"]

@dataclass(frozen=True)
class ResolutionResult:
    catalog_entry_id: int
    status: ResolutionStatus
    reason_code: ResolutionReason
    instrument_id: int | None
    listing_id: int | None
    candidate_count: int
    evidence_hash: str

class ListingMetadataPreviewIn(BaseModel):
    ticker: str
    mic: str
    venue_name: str
    currency: str
    timezone: str
    instrument_type: InstrumentType
    source: ListingMetadataSource
    observed_at: datetime
    evidence_hash: str

class ListingMetadataPreviewOut(BaseModel):
    catalog_entry_id: int
    normalized_ticker: str
    normalized_mic: str
    normalized_currency: str
    normalized_timezone: str
    current_version: int | None
    confirmation_token: str

class InstrumentResolutionService:
    def resolve_catalog_entries(self, connection, entry_ids: Sequence[int]) -> list[ResolutionResult]
    def require_resolved_listing(self, connection, listing_id: int) -> sqlite3.Row

POST /data/catalog/{snapshot_id}/resolve?offset=0&limit=5 -> list[ResolutionResult]
POST /data/catalog/entries/{catalog_entry_id}/listing-metadata/preview -> ListingMetadataPreviewOut
POST /data/catalog/entries/{catalog_entry_id}/listing-metadata/apply -> ResolutionResult
```

Nuova tabella `instrument_resolution_cases` con entry, provider, request fingerprint, status/reason, candidate count, `candidate_hash`, `evidence_hash`, selected instrument/listing nullable e timestamp. `instrument_listings` rappresenta l'identità stabile cross-snapshot ed è univoca per `(instrument_id, UPPER(ticker), UPPER(mic), UPPER(currency))`. La nuova tabella append-only `listing_metadata_versions` è collegata a `instrument_listing_id` (non a una singola catalog entry) e contiene venue, timezone, instrument type, source code, observed_at, evidence hash, status `VERIFIED|RETIRED`, version e supersedes; un indice parziale ammette una sola versione VERIFIED corrente per listing stabile. La nuova `catalog_listing_attestations` ha FK non nullable verso `catalog_entries`, `instrument_listings` e `listing_metadata_versions`, più `evidence_hash` e `attested_at`; `UNIQUE(catalog_entry_id, instrument_listing_id, listing_metadata_version_id, evidence_hash)` è il conflict target dell'upsert e impedisce duplicati concorrenti senza impedire una nuova attestazione per una metadata version successiva. Gli array candidati raw, URL fonte e documenti originali non sono persistiti.

- [x] **Step 1: Scrivere i test RED di mapping e batch limitato**

Testare batch massimo 5 per ogni chiamata Phase 2 anche con key, header opzionale, ordine risposta per job, payload malformato, retry 429/500/503 via transport, exact match, multipli compatibili, mismatch tipo/valuta, venue mancante e zero risultati. Provare che una candidate OpenFIGI unica senza metadata verificati non diventa RESOLVED e produce `MISSING_CURRENCY`, `MISSING_VENUE` o `MISSING_TIMEZONE`. Per listing metadata coprire normalizzazione ticker/MIC/valuta/timezone/tipo, source allowlist, evidence SHA-256, preview/apply stale, `hmac.compare_digest`, version/supersedes, collisione e zero rete da apply. Aggiungere due snapshot COMPLETE con lo stesso ISIN: il secondo riusa instrument, listing e metadata version verificata, aggiunge soltanto l'attestazione entry e un nuovo resolution case; repeat e due apply concorrenti sulla stessa entry/version/evidence producono una sola attestazione; una metadata version successiva ammette una nuova attestazione; un metadata confliggente sulla stessa chiave stabile è bloccato. Testare route su snapshot inesistente/non COMPLETE, offset >=0 e limit 1..5. La pagina è sempre ricavata dall'insieme immutabile di tutte le entry ACCEPTED ordinate per `row_number, id`; coprire pagina 1, ripetizione pagina 1 e pagina 2 senza skip, anche quando la prima pagina è già stata risolta.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_instrument_resolution.py tests\test_api.py -k "openfigi or instrument_resolution or catalog_resolve or listing_metadata" -q
```

Expected: failure per adapter, servizio e route bounded mancanti.

- [x] **Step 3: Implementare adapter e normalizzazione provider**

Inviare job per `idType=ID_ISIN` e `idValue` valido; non includere un exchange code non verificato. Normalizzare FIGI, ticker, exchange code, market sector, security type e nome. OpenFIGI non viene trattato come fonte di currency, MIC o timezone canonici. Rifiutare candidate senza FIGI o con valori non stringa. Il provider symbol non diventa automaticamente ticker canonico.

- [x] **Step 4: Implementare selezione fail-closed**

Una candidate è selezionabile solo se identificativo e tipo sono compatibili e ogni campo locale già noto coincide. `RESOLVED` richiede sempre candidate univoca più una `listing_metadata_versions` VERIFIED corrente con ticker, MIC/venue, currency, timezone e tipo completi e coerenti; in assenza registra status `REJECTED` con il reason `MISSING_*` specifico e non crea `instrument_listings`. Se lo stesso instrument di un nuovo snapshot ha già un listing stabile/current metadata compatibile con ticker/exchange/type della candidate, il resolver riusa quel `listing_id` e aggiunge idempotentemente la nuova `catalog_listing_attestations`, senza richiedere una seconda apply. Zero candidate produce `UNMATCHED`; più di una `AMBIGUOUS`. Per un record PDF privo di venue/valuta, anche una candidate OpenFIGI unica resta non risolta finché i metadata non sono attestati localmente. Salvare FIGI e provider symbol soltanto dopo risoluzione completa. Quando la fonte è un catalog entry Trade Republic, il listing risolto diventa `CATALOGED` con `trade_republic_cataloged_at=snapshot.retrieved_at`; `trade_republic_verified_at` resta `NULL` e lo stato non diventa `VERIFIED`.

- [x] **Step 5: Implementare preview/apply locale dei metadata listing**

Preview accetta soltanto entry ACCEPTED e campi completi, risolve l'instrument stabile tramite ISIN e normalizza/valida ticker, MIC ISO 10383, valuta ISO 4217 uppercase, timezone IANA e tipo coerente con instrument/OpenFIGI; `source` è un codice allowlistato e `evidence_hash` è SHA-256, non un URL. La chiave listing stabile è `(instrument_id, normalized_ticker, normalized_mic, normalized_currency)` e il token SHA-256 canonico include entry, chiave stabile, venue/timezone/tipo, source, `observed_at` UTC, evidence e current metadata version. Apply usa `BEGIN IMMEDIATE`, ricostruisce lo stato locale, usa `hmac.compare_digest`, non chiama provider, crea o riusa l'unico `instrument_listings` della chiave, ritira/inserisce la metadata version e upserta l'attestazione sul conflict target esplicito prima di rieseguire la selezione. Stessi metadata/evidence su una nuova entry sono idempotenti sulla versione e aggiungono soltanto l'attestazione; repeat/concorrenza sulla stessa entry non duplicano; payload, conflitto o versione cambiati restituiscono 409 senza mutazioni.

- [x] **Step 6: Collegare gli entrypoint manuali e limitati**

La route pagina tutte le entry ACCEPTED dello snapshot `COMPLETE` con `ORDER BY row_number, id LIMIT ? OFFSET ?`, senza filtrare quelle già processate prima di applicare l'offset. Per ogni entry della pagina già processata restituisce il latest case/cache; crea job soltanto per le restanti, al massimo 5, li invia in un'unica POST JSON OpenFIGI e ricompone un risultato per entry nello stesso ordine. Nessun endpoint “resolve all” esiste. Ripetere pagina 1 è idempotente e pagina 2 non salta righe; un evidence hash invariato non consuma nuova quota.

- [x] **Step 7: Eseguire GREEN e regressione import**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_instrument_resolution.py tests\test_api.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\openfigi.py backend\app\services\instrument_resolution_service.py backend\app\models backend\app\api\routes.py tests\test_instrument_resolution.py tests\test_api.py
```

Expected: tutti i casi di mapping passano, nessun matching arbitrario, Ruff verde.

- [x] **Step 8: Review, commit e gate remoto**

Review indipendente su POST/fingerprint, batching massimo 5, conservazione dell'ordine, false merge, ISIN/FIGI, completezza venue/currency/timezone/type, evidence/token metadata, pagination e redazione della key. Correggere Critical/Important e rieseguire Step 7.

```powershell
git diff --check
git add backend/app/database.py backend/app/config.py backend/app/models/schemas.py backend/app/models/__init__.py backend/app/data_providers/openfigi.py backend/app/services/instrument_resolution_service.py backend/app/api/routes.py .env.example backend/.env.example tests/fixtures/catalogs/openfigi_mapping_success.json tests/fixtures/catalogs/openfigi_mapping_ambiguous.json tests/fixtures/catalogs/openfigi_mapping_unmatched.json tests/test_instrument_resolution.py tests/test_api.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: resolve and disambiguate instrument listings"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 3 e gate remoto verde.

---

### Task 5: Congelare la resolution locale nei token import e allocation

**Branch:** `codex/investedge-phase-2-task-5`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-4`.

**Files:**

- Modify: `backend/app/services/instrument_resolution_service.py`
- Modify: `backend/app/services/google_sheets_import_service.py`
- Modify: `backend/app/services/allocation_engine.py`
- Modify: `backend/app/api/routes.py`
- Modify: `tests/test_import_security.py`
- Modify: `tests/test_api.py`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Preservare formato SHA-256 a 64 caratteri, `hmac.compare_digest`, refetch/reparse CSV dell'import, payload input congelato dell'allocation, HTTP 409 stale e rollback Fase 1. Apply non contatta OpenFIGI o altri provider.

**Interfaces — Consumes:** ultimo `instrument_resolution_cases` persistito per entry/listing; `evidence_hash`; input canonico import/allocation; token Fase 1.

**Interfaces — Produces:**

```text
ResolutionSnapshot {
    instrument_id: int | None
    listing_id: int | None
    resolution_case_id: int | None
    status: Literal["RESOLVED", "UNMAPPED"]
    candidate_count: int
    evidence_hash: str
}

InstrumentResolutionService.snapshot_for_reference(connection: sqlite3.Connection, symbol: str, explicit_metadata: Mapping[str, str]) -> ResolutionSnapshot
InstrumentResolutionService.assert_snapshot_current(connection: sqlite3.Connection, snapshot: ResolutionSnapshot) -> None
```

- [x] **Step 1: Scrivere test RED import e allocation**

Aggiungere casi: preview con listing risolto; import legacy senza catalog match mantenuto come `UNMAPPED`; comparsa di un candidate locale dopo preview; cambio di `resolution_case_id`, `listing_id`, status o evidence hash prima di apply; due venue omonime; provider budget esaurito. Ogni cambio stale/ambiguo restituisce 409, nessuna mutazione e zero chiamate transport. Conservare i test Phase 1 su refetch CSV e input allocation congelato.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_import_security.py tests\test_api.py -k "resolution_snapshot or listing_token or allocation_token or stale_token" -q
```

Expected: i token correnti non includono la resolution locale e i casi di cambio non restituiscono ancora 409.

- [x] **Step 3: Canonicalizzare lo snapshot locale**

`snapshot_for_reference()` restituisce `RESOLVED` soltanto per un latest case univoco con instrument/listing/evidence hash presenti. Se non esiste alcun candidate locale, restituisce `UNMAPPED` con evidence hash dei metadata espliciti normalizzati e candidate count zero, preservando l'import legacy; se esiste più di un candidate solleva `AmbiguousInstrumentError`. Il payload canonico ordina chiavi e liste come in Fase 1 e aggiunge lo snapshot completo per ogni riga/asset interessato. Non include candidate raw, provider response o timestamp non deterministici.

- [x] **Step 4: Validare apply senza rete**

Import apply rifà soltanto fetch e parse del CSV già previsti, risolve il riferimento contro i case locali e confronta snapshot+token. Allocation apply ricalcola il piano sugli stessi input congelati e snapshot locali. Una differenza solleva l'errore stabile `RESOLUTION_CHANGED`, tradotto dalla route in 409; il controllo avviene prima di ogni write/savepoint applicativo.

- [x] **Step 5: Eseguire GREEN e regressione completa token**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_import_security.py tests\test_api.py -k "import or allocation or token or resolution" -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\services\instrument_resolution_service.py backend\app\services\google_sheets_import_service.py backend\app\services\allocation_engine.py backend\app\api\routes.py tests\test_import_security.py tests\test_api.py
```

Expected: token Phase 1 e nuovi casi resolution verdi; nessuna chiamata provider da apply; Ruff verde.

- [x] **Step 6: Review, commit e gate remoto**

Review indipendente su canonicalizzazione, TOCTOU locale, assenza rete, compare_digest, 409 e rollback. Correggere Critical/Important e ripetere Step 5.

```powershell
git diff --check
git add backend/app/services/instrument_resolution_service.py backend/app/services/google_sheets_import_service.py backend/app/services/allocation_engine.py backend/app/api/routes.py tests/test_import_security.py tests/test_api.py docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "fix: bind destructive previews to resolved listings"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 4 e gate remoto verde.

---

### Task 6: Registrare osservazioni di mercato con provenienza, freschezza e quality gate

**Branch:** `codex/investedge-phase-2-task-6`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-5`.

**Files:**

- Modify: `backend/app/database.py`
- Create: `backend/app/models/market_data.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/market_observation_service.py`
- Modify: `backend/app/services/market_data_service.py`
- Modify: `backend/app/services/prices_service.py`
- Create: `tests/test_market_data_observations.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_portfolio_accounting.py`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** `PricePointOut`, `PriceHistoryOut`, `price_history` e `MarketDataService.refresh_asset_prices()` restano utilizzabili. Portfolio, allocation, dashboard, technical analysis, signals, backtest, ML e import leggono la projection legacy. Un batch invalido non cancella né sostituisce l'ultimo dato buono.

**Interfaces — Consumes:** listing risolto, capability/provider, timestamp provider e ingestione UTC, valuta listing, righe OHLCV o quote, `price_history` legacy.

**Interfaces — Produces:**

```text
ObservationKind = Literal["QUOTE", "BAR"]
SourceObservationQuality = Literal["realtime", "delayed", "eod", "reference"]
EffectiveObservationQuality = Literal["realtime", "delayed", "eod", "reference", "stale"]
ValidationStatus = Literal["VALID", "REJECTED"]
ValidationReason = Literal[
    "MISSING_PRICE",
    "NON_FINITE",
    "NON_POSITIVE",
    "CROSSED_QUOTE",
    "INVALID_OHLC",
    "NEGATIVE_VOLUME",
    "CURRENCY_MISMATCH",
    "INVALID_TIMESTAMP",
    "FUTURE_TIMESTAMP",
    "INVALID_TIMEZONE",
    "INVALID_DELAY",
    "MALFORMED_PAYLOAD",
    "PROVIDER_NO_DATA",
    "MISSING_VALUE",
]

@dataclass(frozen=True)
class MarketObservationEnvelope:
    listing_id: int
    provider: str
    capability: ProviderCapability
    operation: str
    received_at: datetime
    provider_observed_at: datetime | None
    timezone: str | None
    session: str | None
    currency: str | None
    source_quality: SourceObservationQuality | None
    kind: ObservationKind | None
    raw_fields: Mapping[str, object]
    raw_payload_sha256: str

@dataclass(frozen=True)
class MarketObservation:
    listing_id: int
    provider: str
    capability: ProviderCapability
    operation: str
    provider_observed_at: datetime
    ingested_at: datetime
    timezone: str
    session: str
    currency: str
    delay_seconds: int
    source_quality: SourceObservationQuality
    kind: ObservationKind
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    adjusted_close: Decimal | None = None
    volume: Decimal | None = None

class MarketObservationService:
    def validate(self, listing, envelope: MarketObservationEnvelope, now: datetime) -> ValidatedObservation | ObservationRejection
    def ingest_batch(self, connection, envelopes: Sequence[MarketObservationEnvelope], now: datetime) -> IngestResult
    def latest_compatible(self, connection, listing_id: int, capability: str, now: datetime) -> MarketObservation | None
@dataclass(frozen=True)
class ValidatedObservation:
    observation: MarketObservation
    effective_quality: EffectiveObservationQuality
    observation_hash: str

@dataclass(frozen=True)
class ObservationRejection:
    listing_id: int
    provider: str
    capability: ProviderCapability
    operation: str
    received_at: datetime
    reason_code: ValidationReason
    raw_payload_sha256: str

@dataclass(frozen=True)
class IngestResult:
    accepted: int
    rejected: int
    duplicates: int
    revisions: int
    resolved_rejections: int
    projected_price_rows: int

MarketDataSelection {
    selected_observation_id: int
    requested_provider: str
    actual_provider: str
    selected_at: datetime
    fallback_reason: str | None
}
```

`MarketObservationEnvelope` rappresenta anche payload non validabili: timestamp/sessione/currency/kind possono mancare e `raw_fields` resta soltanto in memoria. La rejection persiste reason code, hash e scope stabile `(listing_id, provider, capability, operation)`, mai il payload raw; `PROVIDER_NO_DATA` e `MISSING_VALUE` seguono lo stesso lifecycle e possono essere risolti soltanto da una successiva observation valida dello scope. `source_quality` è metadata stabile dell'adapter/feed (`realtime|delayed|eod|reference`) ricavato soltanto da capability o metadata documentati del payload, mai dall'età al clock di ingestione; se il feed non documenta realtime si usa la classe conservativa `delayed` o `eod`. `delay_seconds` ed `effective_quality` sono invece derivati da `now - provider_observed_at`. `ValidatedObservation` aggiunge `effective_quality`, uguale a `stale` quando la soglia è superata. Nuove tabelle append-only: `market_observations`, `market_data_rejections`, `market_data_rejection_resolutions` e `market_data_selection_events`; nuova colonna nullable `price_history.observation_id`. La chiave logica delle observation valide è `(listing_id, provider, capability, operation, kind, provider_observed_at, session)`: stesso `observation_hash` è duplicato, hash diverso crea `revision = max + 1` con `supersedes_observation_id`, senza cancellare la revisione precedente. L'hash canonico include scope, kind, timestamp/sessione provider, timezone, valuta, source quality stabile e valori normalizzati; esclude `received_at`/`ingested_at`, `delay_seconds` ed `effective_quality`, che dipendono dal clock. Una resolution collega una rejection aperta dello stesso scope a una successiva observation valida; un selection event registra fallback/last-good senza mutare o duplicare l'osservazione. `PricePointOut` riceve campi nullable/additivi `listing_id`, `observation_id`, `provider_observed_at`, `ingested_at`, `timezone`, `session`, `currency`, `delay_seconds`, `source_quality`, `effective_quality` e `fallback_reason`; le righe legacy li restituiscono null.

- [x] **Step 1: Scrivere i test RED del quality gate**

Testare dati validi; tutti i prezzi mancanti; NaN/Inf; prezzi <= 0; bid > ask; OHLC incoerente; volume negativo; valuta diversa dal listing; timestamp assente/naive; futuro oltre 5 minuti; timezone invalida; delay negativo; payload corrotto; `PROVIDER_NO_DATA`; `MISSING_VALUE`; duplicato stesso hash anche con ingest time diverso; stesso payload/timestamp/source metadata ingerito a due clock diversi produce lo stesso hash, `duplicates += 1` e zero revisioni anche se delay/effective quality cambiano; timezone diversa produce hash diverso; correzione provider stesso timestamp con hash diverso; stessa data da provider diversi; corrupt con timestamp mancante → observation valida successiva nello stesso scope → rejection risolta; fallback cache/last-good; stato stale; batch misto. Aggiungere un test di consistenza che enumera tutti i reason code prodotti dagli adapter pianificati e li confronta con `ValidationReason`. Verificare che ogni rifiuto abbia reason code stabile, nessun payload raw e nessuna perdita di righe/revisioni valide precedenti.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_market_data_observations.py tests\test_api.py tests\test_portfolio_accounting.py -k "observation or provenance or stale or price_projection or last_good" -q
```

Expected: failure perché modello, tabelle, validator e projection non esistono.

- [x] **Step 3: Implementare validazione deterministica**

Usare `Decimal(str(value))` e `math.isfinite` prima del cast DB. Regole: almeno un prezzo rilevante; valori prezzo strettamente positivi; `bid <= ask`; `low <= min(open, close, high)` e `high >= max(open, close, low)` per i campi presenti; volume >= 0; valuta ISO uppercase uguale al listing; timestamp timezone-aware; `provider_observed_at <= now + 5 minuti`; timezone IANA uguale a quella attestata per BAR/sessione; delay >= 0. I valori di `ValidationReason` sopra sono l'allowlist esatta e sono tutti critici finché restano senza resolution nello scope; nessun testo di eccezione/provider entra nel reason code.

- [x] **Step 4: Implementare freschezza e ingest append-only**

Soglie default configurate per capability: quote 5 minuti, delayed 30 minuti, EOD 96 ore, reference/FX 7 giorni. La classificazione usa il clock iniettato e restituisce `effective_quality="stale"` senza riscrivere `source_quality`. Ogni batch è validato completamente prima della promozione; i rifiuti sono persistiti separatamente e un batch senza righe valide non tocca `price_history`. Una observation valida risolve tutte le rejection critiche aperte dello stesso `(listing_id, provider, capability, operation)` con `rejection.received_at <= observation.ingested_at`; una rejection già risolta resta storica ma non blocca il tier. La risoluzione non richiede timestamp/sessione nel payload rifiutato.

- [x] **Step 5: Implementare la projection compatibile**

Solo l'ultima revisione valida di una BAR genera/upserta la riga `price_history` corrispondente con `source`, `provider`, `is_real_data`, `fetched_at` e `observation_id`. Non cancellare l'intera serie per provider `full_history`; promuovere per data dentro la stessa transazione. `latest_compatible()` registra `market_data_selection_events` quando actual provider differisce dal requested o viene riusato last-good; `prices_service` deriva `fallback_reason` da quell'evento e continua a leggere righe legacy senza link.

- [x] **Step 6: Eseguire GREEN e regressione caller prezzi**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_market_data_observations.py tests\test_api.py tests\test_portfolio_accounting.py tests\test_engines.py tests\test_ml_dataset.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\models\market_data.py backend\app\services\market_observation_service.py backend\app\services\market_data_service.py backend\app\services\prices_service.py tests\test_market_data_observations.py
```

Expected: suite selezionata verde; read model Fase 1 invariato; Ruff verde.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente su decimal precision, timezone/session, hash/revision/supersedes, lifecycle rejection, selection fallback, transazioni, batch parziali, projection e ultimo dato buono. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add backend/app/database.py backend/app/models/market_data.py backend/app/models/schemas.py backend/app/models/__init__.py backend/app/services/market_observation_service.py backend/app/services/market_data_service.py backend/app/services/prices_service.py tests/test_market_data_observations.py tests/test_api.py tests/test_portfolio_accounting.py docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add validated market data observations"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 5 e gate remoto verde.

---

### Task 7: Valutare e versionare i tier Qualified, Observable e Reference only

**Branch:** `codex/investedge-phase-2-task-7`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-6`.

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/models/schemas.py`
- Create: `backend/app/services/instrument_quality_service.py`
- Modify: `backend/app/services/instrument_service.py`
- Modify: `backend/app/services/market_observation_service.py`
- Create: `tests/test_instrument_quality.py`
- Modify: `tests/test_market_data_observations.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** I tier sono informativi/gate per nuovi consumatori; non riscrivono `AssetOut`, ordini storici o dataset Fase 1. `REFERENCE_ONLY` è il nome API, `Reference only` la label UI. Nessuna promozione rende automaticamente tradabile uno strumento.

**Interfaces — Consumes:** instrument/listing/identifier, resolution cases, osservazioni validate/rejections, clock UTC, `MARKET_DATA_DIVERGENCE_BPS=500` e policy freshness.

**Interfaces — Produces:**

```text
QualityReason = Literal[
    "REFERENCE_INSTRUMENT",
    "AMBIGUOUS_IDENTITY",
    "MISSING_PRIMARY_ID",
    "MISSING_LISTING_METADATA",
    "UNRESOLVED_CRITICAL_REJECTION",
    "NO_VALID_OBSERVATION",
    "STALE_OBSERVATION",
    "INSUFFICIENT_HISTORY",
    "PROVIDER_DIVERGENCE",
    "COMPATIBLE_FALLBACK_IN_USE",
    "VALIDATED_OBSERVABLE",
    "QUALIFICATION_RULES_MET",
]

@dataclass(frozen=True)
class TierEvidenceScope:
    listing_id: int
    capability: ProviderCapability
    actual_provider: str
    operation: str
    selected_observation_ids: Sequence[int]

@dataclass(frozen=True)
class TierAssessment:
    instrument_id: int
    tier: QualityTier
    reason_codes: Sequence[QualityReason]
    assessed_at: datetime
    evidence_hash: str
    evidence_scopes: Sequence[TierEvidenceScope]

class InstrumentQualityService:
    def select_evidence_scopes(self, connection, instrument_id: int, target_tier: QualityTier, now: datetime) -> Sequence[TierEvidenceScope]
    def assess(self, connection, instrument_id: int, now: datetime) -> TierAssessment
    def assess_and_record(self, connection, instrument_id: int, now: datetime) -> TierAssessment
    def eligible_for_strategy(self, connection, instrument_id: int, now: datetime, require_trade_republic: bool) -> bool
```

Nuova tabella append-only `quality_assessments`; `instruments.quality_tier`, `quality_reason_code`, `quality_assessed_at` sono la projection corrente.

- [x] **Step 1: Scrivere la matrice di test RED**

Copertura: macro/rate/index/FX sempre `REFERENCE_ONLY`; mapping ambiguo; ISIN/FIGI mancante; crypto con `COINGECKO_ID` valido senza ISIN inventato; listing senza valuta/timezone/MIC per mercati regolamentati; nessun dato; dato stale; storia sotto/sopra soglia; promozione; declassamento; due provider divergenti; rejection critica aperta nello scope EOD selezionato; payload corrotto senza timestamp seguito da observation valida dello stesso scope, resolution persistita e tier nuovamente recuperabile; reassessment idempotente con stesso evidence hash. Aggiungere tre casi espliciti: rejection Finnhub QUOTE opzionale + 60 BAR EOD valide non declassa; rejection EOD aperta dell'actual provider selezionato declassa; primary EOD fallito ma fallback EOD compatibile/valido selezionato mantiene il tier possibile e aggiunge `COMPATIBLE_FALLBACK_IN_USE`.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_instrument_quality.py tests\test_market_data_observations.py -k "quality_tier or promote or demote or divergence" -q
```

Expected: failure per servizio/schema assenti.

- [x] **Step 3: Implementare regole di tier complete**

`select_evidence_scopes()` rende deterministico ciò che può bloccare il tier. Per `QUALIFIED`, la capability richiesta è soltanto EOD e lo scope rilevante è `(listing_id, EOD, actual_provider, operation)` selezionato da `latest_compatible()` per le 60 BAR e l'ultima barra; QUOTE, NEWS e REFERENCE opzionali non entrano nel gate. Per `OBSERVABLE`, lo scope rilevante è quello dell'observation compatibile effettivamente selezionata, EOD oppure QUOTE. Se un selection event sceglie un fallback compatibile, conta lo scope dell'`actual_provider`: una rejection aperta del requested provider resta visibile nell'evento/Data Center ma non blocca; una rejection aperta dell'actual provider usato come evidenza produce `UNRESOLVED_CRITICAL_REJECTION`. Gli ID observation, lo scope actual e l'eventuale fallback entrano nell'evidence hash.

Ordine fail-closed: reference types -> ambiguità/rejection rilevante/divergenza -> identità/listing incompleti -> assenza/stale -> storia insufficiente -> Qualified. `Observable` richiede mapping univoco e almeno un'osservazione valida compatibile nello scope selezionato. `Qualified` richiede: identità primaria verificata; currency+timezone e MIC per listing regolamentati oppure `COINGECKO_ID`+UTC per aggregato crypto; nessuna rejection critica aperta negli `evidence_scopes`; almeno 60 barre giornaliere valide dello scope EOD selezionato; ultima barra EOD non oltre 96 ore. Una rejection risolta da una successiva observation valida non blocca promozione o recupero del tier. Un fallback compatibile aggiunge il reason informativo `COMPATIBLE_FALLBACK_IN_USE` senza promuovere qualità o nascondere provenienza. Queste soglie sono configurabili ma i default restano coperti dai test.

`eligible_for_strategy()` richiede sempre `QUALIFIED`, identity non ambigua e osservazione non stale. Se `require_trade_republic=True`, richiede inoltre `trade_republic_status="VERIFIED"` e `trade_republic_verified_at` non più vecchio di 30 giorni; un semplice `CATALOGED` restituisce `False`. Questa è soltanto una guardia dati riusabile: non crea strategie, ordini o scheduler.

- [x] **Step 4: Implementare divergenza e storico**

Confrontare soltanto osservazioni `last`/`close` non stale, stessa currency e timestamp entro 10 minuti. Se `abs(a-b)/min(a,b) * 10_000 > 500`, registrare `PROVIDER_DIVERGENCE` e declassare a `REFERENCE_ONLY`; non mediare. Ogni cambio di tier crea assessment; stesso evidence hash e stesso tier non duplica la storia.

- [x] **Step 5: Eseguire GREEN**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_instrument_quality.py tests\test_market_data_observations.py tests\test_portfolio_accounting.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\services\instrument_quality_service.py backend\app\services\instrument_service.py backend\app\services\market_observation_service.py tests\test_instrument_quality.py
```

Expected: matrice tier e regressione EUR verdi; Ruff verde.

- [x] **Step 6: Review, commit e gate remoto**

Review indipendente su ordine delle regole, falsi Qualified, declassamento, crypto senza ISIN, soglia divergenza e idempotenza. Correggere Critical/Important e ripetere Step 5.

```powershell
git diff --check
git add backend/app/database.py backend/app/config.py backend/app/models/schemas.py backend/app/services/instrument_quality_service.py backend/app/services/instrument_service.py backend/app/services/market_observation_service.py tests/test_instrument_quality.py tests/test_market_data_observations.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add instrument quality tier assessments"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 6 e gate remoto verde.

---

### Task 8: Aggiungere EOD gratuito e fallback compatibile senza Yahoo primario

**Branch:** `codex/investedge-phase-2-task-8`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-7`.

**Files:**

- Modify: `backend/app/config.py`
- Create: `backend/app/data_providers/stooq.py`
- Modify: `backend/app/data_providers/alpha_vantage.py`
- Modify: `backend/app/data_providers/provider_registry.py`
- Modify: `backend/app/data_providers/__init__.py`
- Modify: `backend/app/services/market_data_service.py`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Create: `tests/fixtures/market_data/stooq_daily.csv`
- Create: `tests/fixtures/market_data/stooq_empty.csv`
- Create: `tests/fixtures/market_data/stooq_malformed.csv`
- Create: `tests/test_eod_providers.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Yahoo Finance non è più provider primario né fallback di rete, ma la classe può restare per compatibilità dei test/import esistenti. Alpha Vantage resta visibile come non disponibile per `SECRET_IN_QUERY_POLICY`; il codice non invia la sua key. `MarketDataService.refresh_asset_prices()` mantiene forma della risposta.

**Interfaces — Consumes:** listing con provider symbol Stooq verificato, capability `EOD`, transport/budget locale conservativo 5/minuto, 100/giorno e 1.000/mese, observation validator e tier assessment.

**Interfaces — Produces:**

```text
@dataclass(frozen=True)
class ProviderCapabilityMatch:
    provider: str
    capability: ProviderCapability
    listing_id: int
    provider_symbol: str
    currency: str
    priority: int

class ProviderRegistry:
    def providers_for(self, connection, listing_id: int, capability: ProviderCapability) -> Sequence[ProviderCapabilityMatch]
class StooqProvider(BaseMarketDataProvider):
    capability = "EOD"
    def fetch_observations(
        self,
        listing,
        start: date | None,
        end: date | None,
        bypass_cache: bool = False,
    ) -> list[MarketObservationEnvelope]
```

- [x] **Step 1: Scrivere test RED su capability e fallback**

Testare parsing CSV, date/decimal/volume, risposta vuota, colonne mancanti, HTML al posto del CSV, valuta divergente, ticker senza mapping, host/path fisso, opt-in disabilitato, limiti 5/minuto-100/giorno-1.000/mese, budget esaurito e fallback all'ultima observation compatibile. Verificare che `fetch_observations(listing, start, end, bypass_cache=true)` inoltri il flag esclusivamente al transport: cache preesistente ignorata, una richiesta fisica governata, stessa validation/fingerprint/deduplica e cache aggiornata. Provare che Yahoo/Alpha non vengono chiamati e che il fallback crea un selection event con `fallback_reason` senza cambiare currency, listing o observation originale.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_eod_providers.py tests\test_api.py -k "stooq or eod_capability or alpha_policy or compatible_fallback" -q
```

Expected: failure perché provider capability e adapter Stooq non esistono e registry è ancora first-match per asset type.

- [x] **Step 3: Implementare registry per capability**

Il registry interroga `provider_symbols` e restituisce una catena ordinata, non un singolo provider per asset type. Un match richiede stesso listing, capability, currency e tipo supportato. Per EOD: Stooq opt-in se mapping presente; poi cache/ultima observation valida dello stesso listing. Yahoo e Alpha non entrano nella catena di rete.

- [x] **Step 4: Implementare adapter Stooq fixture-first**

Consentire soltanto endpoint HTTPS/host noto e `ENABLE_STOOQ=false` di default. Non derivare il simbolo dal ticker con suffissi euristici: deve esistere `provider_symbols`. `bypass_cache` viene passato senza reinterpretazione soltanto a `SafeProviderTransport.request()`. Convertire ogni riga in `MarketObservationEnvelope` EOD con scope, timezone/session del listing e hash payload; il validator decide validità e costruisce la `MarketObservation` accettata.

- [x] **Step 5: Rendere esplicita la policy Alpha/Yahoo**

`AlphaVantageProvider` restituisce stato `DISABLED/SECRET_IN_QUERY_POLICY` prima del transport anche con key configurata. Yahoo restituisce `DISABLED/NOT_PRIMARY_POLICY`. Nessun URL con key viene costruito. Il Data Center consumerà questi reason code nel Task 17.

- [x] **Step 6: Eseguire GREEN e regressione refresh**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_eod_providers.py tests\test_market_data_observations.py tests\test_api.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers backend\app\services\market_data_service.py tests\test_eod_providers.py
```

Expected: adapter e fallback verdi, nessuna rete, Ruff verde.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente su assenza API/SLA Stooq, opt-in, simboli espliciti, HTML/error parsing, Yahoo/Alpha disabilitati, fallback e ultimo dato valido. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add backend/app/config.py backend/app/data_providers/stooq.py backend/app/data_providers/alpha_vantage.py backend/app/data_providers/provider_registry.py backend/app/data_providers/__init__.py backend/app/services/market_data_service.py .env.example backend/.env.example tests/fixtures/market_data/stooq_daily.csv tests/fixtures/market_data/stooq_empty.csv tests/fixtures/market_data/stooq_malformed.csv tests/test_eod_providers.py tests/test_api.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add governed EOD market data fallback"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 7 e gate remoto verde.

---

### Task 9: Integrare quote snapshot USA gratuite con Finnhub

**Branch:** `codex/investedge-phase-2-task-9`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-8`.

**Files:**

- Modify: `backend/app/config.py`
- Create: `backend/app/data_providers/finnhub_quote.py`
- Modify: `backend/app/data_providers/provider_registry.py`
- Modify: `backend/app/data_providers/__init__.py`
- Modify: `backend/app/services/market_data_service.py`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Create: `tests/fixtures/market_data/finnhub_quote.json`
- Create: `tests/fixtures/market_data/finnhub_quote_no_data.json`
- Create: `tests/test_finnhub_provider.py`
- Modify: `tests/test_provider_budget.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Nessuna quote Finnhub viene trasformata in candle storico. Gli strumenti non USA e i listing senza MIC/simbolo provider sono incompatibili. Key assente significa provider disabilitato, non errore globale.

**Interfaces — Consumes:** listing risolti su MIC USA allowlistati (`XNYS`, `XNAS`, `XASE`, `ARCX`, `BATS`), provider symbol esplicito, header `X-Finnhub-Token`, capability `QUOTE`, limite locale 55/minuto.

**Interfaces — Produces:**

```text
class FinnhubQuoteProvider(BaseMarketDataProvider):
    capability = "QUOTE"
    supported_mics = frozenset({"XNYS", "XNAS", "XASE", "ARCX", "BATS"})
    def fetch_quote(self, listing, now: datetime, bypass_cache: bool = False) -> MarketObservationEnvelope
```

La risposta `c/h/l/o/pc/t` produce `kind="QUOTE"`, `last=c`, timestamp provider `t` e session del listing. Poiché il payload/free plan non offre metadata stabili sufficienti a provare realtime, l'adapter assegna sempre la classe conservativa stabile `source_quality="delayed"`; la differenza col clock calcola soltanto `delay_seconds` ed `effective_quality`/stale. `h/l/o/pc` restano metadata di quote e non sono salvati come BAR giornaliera. Lo stesso payload a due clock diversi deve deduplicare senza creare revisioni.

- [x] **Step 1: Scrivere test RED**

Testare header token, assenza key, key sentinella assente da log/fingerprint, MIC USA/non-USA, mapping mancante, `t=0`, `c=0`, timestamp futuro, 429/cooldown, budget 55/min, quote valida e mancata scrittura in `price_history`. Verificare che `fetch_quote(listing, now, bypass_cache=true)` inoltri il flag soltanto al transport e mantenga fingerprint, in-flight dedupe, quota e validation.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_finnhub_provider.py tests\test_provider_budget.py -k "finnhub or us_quote" -q
```

Expected: failure per adapter/capability mancanti.

- [x] **Step 3: Implementare adapter e policy di copertura**

Usare endpoint fisso `/api/v1/quote`, simbolo da `provider_symbols`, key solo header. Passare `bypass_cache` senza reinterpretazione soltanto a `SafeProviderTransport.request()`. Classificare no-data con `ValidationReason="PROVIDER_NO_DATA"`, persisterlo in `market_data_rejections` sullo scope Finnhub QUOTE e lasciare che soltanto una quote valida successiva lo risolva; rifiutare timestamp zero/futuro e prezzo non positivo attraverso lo stesso validator. Non chiamare l'endpoint candle.

- [x] **Step 4: Collegare registry, budget e fallback**

Finnhub è candidate QUOTE solo per MIC allowlistati. In caso di key mancante, quota, timeout o no-data, `MarketDataService` cerca soltanto una quote non stale dello stesso listing; non usa EOD come realtime e non cambia provider symbol.

- [x] **Step 5: Eseguire GREEN**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_finnhub_provider.py tests\test_provider_budget.py tests\test_market_data_observations.py tests\test_api.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\finnhub_quote.py backend\app\data_providers\provider_registry.py backend\app\services\market_data_service.py tests\test_finnhub_provider.py
```

Expected: test verdi, nessun URL/secret, Ruff verde.

- [x] **Step 6: Review, commit e gate remoto**

Review indipendente su limiti del free tier, MIC, quote-vs-candle, timestamp, header token, fallback e budget. Correggere Critical/Important e ripetere Step 5.

```powershell
git diff --check
git add backend/app/config.py backend/app/data_providers/finnhub_quote.py backend/app/data_providers/provider_registry.py backend/app/data_providers/__init__.py backend/app/services/market_data_service.py .env.example backend/.env.example tests/fixtures/market_data/finnhub_quote.json tests/fixtures/market_data/finnhub_quote_no_data.json tests/test_finnhub_provider.py tests/test_provider_budget.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add governed Finnhub US quotes"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 8 e gate remoto verde.

---

### Task 10: Integrare prezzi crypto gratuiti con identità CoinGecko

**Branch:** `codex/investedge-phase-2-task-10`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-9`.

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/data_providers/coingecko.py`
- Modify: `backend/app/data_providers/provider_registry.py`
- Modify: `backend/app/services/instrument_service.py`
- Modify: `backend/app/services/market_data_service.py`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Create: `tests/fixtures/market_data/coingecko_market_chart.json`
- Create: `tests/fixtures/market_data/coingecko_simple_price.json`
- Create: `tests/fixtures/market_data/coingecko_rate_limit.json`
- Create: `tests/test_coingecko_provider.py`
- Modify: `tests/test_provider_budget.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Le righe legacy BTC/ETH restano accessibili per simbolo nell'universo attivo, ma le richieste usano esclusivamente `COINGECKO_ID`; nessun simbolo ambiguo viene trasformato euristicamente in provider ID. Nessun ISIN/MIC è inventato per crypto.

**Interfaces — Consumes:** `provider_symbols`/identifier `COINGECKO_ID`, currency del listing, Demo key opzionale in `x-cg-demo-api-key`, capability EOD/QUOTE, budget locali conservative.

**Interfaces — Produces:**

```text
class CoinGeckoProvider(BaseMarketDataProvider):
    supported_quote_currencies = frozenset({"EUR", "USD"})
    def fetch_daily(self, listing, days: int, bypass_cache: bool = False) -> list[MarketObservationEnvelope]
    def fetch_quote(self, listing, now: datetime, bypass_cache: bool = False) -> MarketObservationEnvelope
```

Policy budget: Demo massimo locale 90/minuto e 9.000/mese; keyless massimo locale 10/minuto e 1.000/mese. I limiti upstream/429 possono solo ridurre questi valori. Il Data Center espone l'attribuzione “Powered by CoinGecko API”.

- [x] **Step 1: Scrivere test RED su identità, payload e budget**

Testare ID `bitcoin` distinto dal ticker `BTC`, quote EUR/USD, timestamp millisecondi, duplicate timestamp, array non allineati, response vuota, prezzo zero/non finito, valuta non supportata, Demo header, keyless senza query secret, margini minuto/mese e 429 con cooldown. Per EOD e QUOTE verificare che `bypass_cache=true` arrivi soltanto al transport e conservi fingerprint, in-flight dedupe, budget e validation.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_coingecko_provider.py tests\test_provider_budget.py tests\test_api.py -k "coingecko or crypto_identity or crypto_budget" -q
```

Expected: failure perché l'adapter corrente mappa un set fisso di ticker e non produce observation governate.

- [x] **Step 3: Migrare l'adapter a ID e observation**

Richiedere un `COINGECKO_ID` verificato; usare endpoint/host fissi. Demo usa header, keyless nessuna credenziale. `fetch_daily()` e `fetch_quote()` passano `bypass_cache` senza reinterpretazione soltanto a `SafeProviderTransport.request()`. Normalizzare `market_chart` in BAR giornaliere UTC/24x7 e `simple/price` in QUOTE; il validator gestisce currency, timestamp e valori. La deduplica aggrega timestamp dello stesso giorno scegliendo l'ultimo campione solo dentro la stessa risposta/provider.

Per preservare gli asset seed esistenti, eseguire un backfill una tantum e idempotente soltanto per la mappa curata già supportata dalla baseline (`BTC=bitcoin`, `ETH=ethereum`, `SOL=solana`, `BNB=binancecoin`, `XRP=ripple`). Il backfill richiede `asset_type="crypto"`, simbolo univoco nell'universo attivo e instrument già collegato; salva scheme `COINGECKO_ID`, source `LEGACY_CURATED`, observed_at uguale alla migrazione. Non estendere la mappa per somiglianza di nome o ticker.

- [x] **Step 4: Collegare capability e fallback**

Registry supporta crypto EOD/QUOTE soltanto per ID esplicito. Il fallback è l'ultima observation CoinGecko compatibile, opportunamente stale; non usare una quotazione USD per un listing EUR senza passare dall'FX service e non effettuare qui conversioni implicite.

- [x] **Step 5: Eseguire GREEN**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_coingecko_provider.py tests\test_provider_budget.py tests\test_market_data_observations.py tests\test_api.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\coingecko.py backend\app\data_providers\provider_registry.py backend\app\services\market_data_service.py tests\test_coingecko_provider.py
```

Expected: test verdi, nessuna rete, nessuna identità inventata, Ruff verde.

- [x] **Step 6: Review, commit e gate remoto**

Review indipendente su ID-vs-ticker, budget mensile, header, keyless, valuta, UTC/24x7, attribuzione e fallback. Correggere Critical/Important e ripetere Step 5.

```powershell
git diff --check
git add backend/app/database.py backend/app/config.py backend/app/data_providers/coingecko.py backend/app/data_providers/provider_registry.py backend/app/services/instrument_service.py backend/app/services/market_data_service.py .env.example backend/.env.example tests/fixtures/market_data/coingecko_market_chart.json tests/fixtures/market_data/coingecko_simple_price.json tests/fixtures/market_data/coingecko_rate_limit.json tests/test_coingecko_provider.py tests/test_provider_budget.py tests/test_api.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add governed CoinGecko crypto data"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 9 e gate remoto verde.

---

### Task 11: Rendere operativo FX BCE verso EUR e governare il fallback FRED

**Branch:** `codex/investedge-phase-2-task-11`

**Base remota esatta:** `origin/investedge/programma-operativo` (commit documentale sopra `origin/codex/investedge-phase-2-task-10`, aggiunto il 2026-09-30 con `AGENTS.md` e `PROGRAMMA-OPERATIVO.md`).

**Files:**

- Modify: `backend/app/config.py`
- Create: `backend/app/data_providers/ecb.py`
- Modify: `backend/app/data_providers/fred.py`
- Modify: `backend/app/data_providers/provider_registry.py`
- Modify: `backend/app/data_providers/__init__.py`
- Modify: `backend/app/services/fx_service.py`
- Modify: `backend/app/services/market_data_service.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Create: `tests/fixtures/market_data/ecb_exr_usd_eur.csv`
- Create: `tests/fixtures/market_data/fred_series_observations.json`
- Create: `tests/fixtures/market_data/fred_missing_value.json`
- Modify: `tests/test_fx_service.py`
- Create: `tests/test_reference_providers.py`
- Modify: `tests/test_portfolio_accounting.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Preservare firma e semantica `FXService.get_rate(connection, from_currency, to_currency="EUR")`, `FXQuote`, direct/inverse/identity, stale/missing e cambio congelato degli ordini. `refresh_ecb(connection, client=None) -> int` resta disponibile con la semantica Fase 1 di refresh multi-currency da un solo documento ECB bounded; il nuovo entrypoint single-currency è additivo. Nessun ricalcolo retroattivo di trade/snapshot. FRED resta reference, non prezzo tradabile.

**Interfaces — Consumes:** ECB Data API serie EXR `D.<CURRENCY>.EUR.SP00.A`; `If-Modified-Since`/304; budget ECB locale 5/minuto, 50/giorno e 500/mese; FRED v1 per-serie con key in query; FRED v2 Bearer ma soltanto release bulk; allowlist FRED esistente; transport/budget/observation.

**Interfaces — Produces:**

```text
class EcbFxProvider:
    capability = "FX"
    provider_code = "ecb"
    policy = ProviderBudgetPolicy(minute_limit=5, daily_limit=50, monthly_limit=500)
    def __init__(self, transport: SafeProviderTransport)
    def with_client(self, client: httpx.Client) -> EcbFxProvider
    def fetch_rate(
        self,
        connection,
        from_currency: str,
        to_currency: Literal["EUR"],
        since: date | None,
        now: datetime,
    ) -> EcbFetchResult
    def fetch_reference_rates(self, connection, now: datetime) -> list[FXQuote]

FxRefreshStatus = Literal["UPDATED", "NOT_MODIFIED"]

@dataclass(frozen=True)
class EcbFetchResult:
    status: FxRefreshStatus
    quote: FXQuote | None

class FxRefreshResult(BaseModel):
    from_currency: str
    to_currency: Literal["EUR"]
    provider: Literal["ecb"]
    status: FxRefreshStatus
    rows_written: int
    observed_at: datetime | None
    ingested_at: datetime | None

class FXService:
    def __init__(self, ecb_provider: EcbFxProvider | None = None)
    def refresh_currency(
        self,
        connection,
        from_currency: str,
        now: datetime | None = None,
    ) -> FxRefreshResult
    def refresh_ecb(self, connection, client=None) -> int

class FredReferenceProvider(BaseMarketDataProvider):
    capability = "REFERENCE"
    allowed_series = frozenset({"DGS10", "DGS2", "FEDFUNDS"})
    legacy_aliases = {"BTP10Y": "DGS10"}
    def availability(self) -> ProviderAvailability
```

Il registry costruisce un `EcbFxProvider` con il `SafeProviderTransport` condiviso; `FXService(ecb_provider=injected_adapter)` è il seam dei test e il default risolve lo stesso adapter dal registry, senza creare un client non governato. Nuovo endpoint manuale `POST /data/fx/refresh?from_currency=USD -> FxRefreshResult`: chiama esclusivamente `FXService.refresh_currency()` e non il facade multi-currency; nessuna esecuzione automatica o scheduler. `UPDATED` restituisce `rows_written=1` e i timestamp della riga validata/upsertata. `NOT_MODIFIED` restituisce `rows_written=0` e i timestamp dell'ultima riga persistita della coppia; un 304 senza riga precedente è un provider failure sanitizzato, non un falso successo. Il provider code persistito, esposto e usato per budget/cache/coverage è sempre il canonico Fase 1 lowercase `ecb`; “ECB” è soltanto label/attribution UI. FX conserva un modello separato e già compatibile: l'adapter scrive soltanto `fx_rates`/`FXQuote`, non crea instrument listing né `MarketObservationEnvelope`. Il Task 16 misura quindi FX per currency direttamente da `fx_rates`, senza fingere un mapping currency→listing.

- [x] **Step 1: Scrivere test RED FX/reference**

ECB: `refresh_currency()` su CSV/SDMX valido, 304 con/senza riga precedente, valore mancante, rate <= 0, currency non allowlistata, stale 7 giorni, risultato/timestamp e idempotenza; `refresh_ecb()` legacy su XML multi-currency conserva firma, conteggio, direct/inverse/identity e idempotenza con un solo documento bounded. Per entrambi testare adapter/transport iniettato, cache prima della reservation, una reservation per tentativo fisico, 429/cooldown, una sola chiamata HTTP fisica nel caso senza retry, stesso provider code `ecb` e stesso bucket budget/coverage. Passare `client` al solo legacy dimostra che `with_client()` mantiene la governance. FRED: v1 non costruisce URL con key; v2 non avvia download release; stati `SECRET_IN_QUERY_POLICY`/`BULK_ONLY_POLICY`; fixture legacy con `.` missing; attribution e diritti serie dichiarati. API: refresh manuale usa adapter fixture, chiama una sola currency e non muta su failure.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_fx_service.py tests\test_reference_providers.py tests\test_portfolio_accounting.py tests\test_api.py -k "ecb or fx or fred or reference_provider" -q
```

Expected: failure per adapter/endpoints mancanti; i test Fase 1 direct/inverse continuano a documentare il contratto.

- [x] **Step 3: Implementare ECB Data API mantenendo il facade FX**

Usare host/path ufficiale e response CSV, limitando le righe e richiedendo `lastNObservations=2`; supportare `If-Modified-Since`. `EcbFxProvider.fetch_rate()` e `fetch_reference_rates()` chiamano esclusivamente `SafeProviderTransport.request()` con `provider="ecb"`, policy ECB, cache scope separati e limite 1 MiB; reservation, retry, 429/cooldown, deduplica e cache restano quindi comuni. `FXService.refresh_currency()` normalizza la singola quote ufficiale in `currency -> EUR`, salva `observed_at`, `ingested_at`, provider `ecb`, quality `reference` e costruisce `FxRefreshResult`. Estrarre un helper privato comune che valida e upserta quote senza cambiare l'ultimo valore buono su errore. `FXService.refresh_ecb()` mantiene il percorso Fase 1: se `client` è fornito usa temporaneamente `ecb_provider.with_client(client)`, che resta sul transport governato; una sola risposta XML ufficiale, limite 1 MiB/entity guard e massimo 64 currency, viene validata e persistita atomicamente dallo stesso helper e restituisce il numero di righe. Non chiama `refresh_currency()` in loop e non crea lavoro bulk sul catalogo.

- [x] **Step 4: Rendere FRED esplicitamente fail-closed e reference-only**

Non chiamare v1 perché richiede la key in query e non chiamare v2 perché l'unico endpoint documentato scarica intere release, violando il refresh lazy/bounded. Con key assente restituire `DISABLED/MISSING_CREDENTIAL`; con key presente restituire `DISABLED/SECRET_IN_QUERY_POLICY` per v1 e includere `BULK_ONLY_POLICY` nelle capability notes per v2. Conservare il parser fixture/righe già locali, convertire `.` in `ValidationReason="MISSING_VALUE"`, persistere la rejection sullo scope FRED REFERENCE e risolverla solo con un valore locale valido successivo; non trasformare rendimenti/tassi in prezzo e non promuovere oltre `REFERENCE_ONLY`. `BTP10Y` resta soltanto alias legacy del proxy USA `DGS10`, esplicitamente etichettato `REFERENCE_ONLY/US_10Y_PROXY` e mai descritto come rendimento BTP italiano. Registrare l'attribuzione FRED nel metadata provider.

- [x] **Step 5: Collegare endpoint manuale e regressione EUR**

La route valida valuta ISO, chiama esattamente `FXService.refresh_currency(connection, from_currency)` una volta e restituisce `FxRefreshResult`; il test sostituisce l'adapter nel service, non inventa un parametro route/client. La route mappa missing/rate-limit/provider failure in risposta sanitizzata. Un refresh fallito non elimina l'ultimo FX valido; le operazioni Fase 1 continuano a bloccare stale/missing senza mutazione. Il test chiama separatamente anche `refresh_ecb()` e dimostra il comportamento multi-currency legacy bounded sul medesimo bucket `ecb`.

- [x] **Step 6: Eseguire GREEN**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_fx_service.py tests\test_reference_providers.py tests\test_portfolio_accounting.py tests\test_api.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\ecb.py backend\app\data_providers\fred.py backend\app\services\fx_service.py backend\app\services\market_data_service.py backend\app\api\routes.py tests\test_fx_service.py tests\test_reference_providers.py
```

Expected: test FX/EUR e reference verdi; Ruff verde; nessun secret o chiamata live.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente su orientamento quote EUR, 304, stale, FX frozen, assenza di chiamate FRED v1/v2, reference-only, rights/attribution e autenticazione. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add backend/app/config.py backend/app/data_providers/ecb.py backend/app/data_providers/fred.py backend/app/data_providers/provider_registry.py backend/app/data_providers/__init__.py backend/app/services/fx_service.py backend/app/services/market_data_service.py backend/app/api/routes.py backend/app/models/schemas.py .env.example backend/.env.example tests/fixtures/market_data/ecb_exr_usd_eur.csv tests/fixtures/market_data/fred_series_observations.json tests/fixtures/market_data/fred_missing_value.json tests/test_fx_service.py tests/test_reference_providers.py tests/test_portfolio_accounting.py tests/test_api.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add governed EUR FX and reference data"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 10 e gate remoto verde.

---

### Task 12: Mettere in sicurezza provider e fallback delle news reali

**Branch:** `codex/investedge-phase-2-task-12`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-11`.

**Files:**

- Modify: `backend/app/config.py`
- Modify: `backend/app/data_providers/news_base.py`
- Modify: `backend/app/data_providers/finnhub_news.py`
- Modify: `backend/app/data_providers/alpha_vantage_news.py`
- Modify: `backend/app/data_providers/yahoo_news.py`
- Modify: `backend/app/data_providers/__init__.py`
- Modify: `backend/app/services/news_engine.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/routes.py`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Create: `tests/fixtures/market_data/finnhub_company_news.json`
- Create: `tests/fixtures/market_data/finnhub_company_news_empty.json`
- Create: `tests/test_news_providers.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_alert_service.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Estensione approvata 2026-09-30 (programma operativo, backlog SP2a):** le news demo/locali (`provider = 'mock_news'`) restano visibili ma non entrano mai in `aggregate_news_sentiment`, `news_score`/`final_score`, riepilogo sentiment di mercato o feature ML; un refresh non rinnova `published_at` delle news demo gia salvate. File aggiuntivi autorizzati: `backend/app/services/sentiment_engine.py`, `backend/app/services/ml_dataset_service.py`. Il conteggio `news_count` del sentiment in modalita demo diventa 0 (contratto aggiornato di proposito).

**Compatibility/caller:** Preservare `NewsEngine`, modelli/sentiment, news locali e route esistenti. Non cambiare scoring o introdurre hub news. Finnhub diventa l'unico provider news live ammesso; Alpha e Yahoo sono fail-closed con reason code, poi fallback locale.

**Interfaces — Consumes:** transport/budget Task 2, `FINNHUB_API_KEY` opzionale, listing/active asset univoco, un `provider_symbols` corrente `VERIFIED` per capability `NEWS` e venue compatibile, cache sanitizzata, articoli/sentiment Fase 1.

**Interfaces — Produces:**

```text
NewsProviderDecision {
    provider: Literal["finnhub_news", "alpha_vantage_news", "yahoo_news", "local"]
    availability: ProviderAvailability
    fallback_provider: Literal["local"] | None
}

FinnhubNewsProvider.get_news_for_symbol(symbol: str, force: bool = False) -> tuple[list[dict[str, object]], bool]
NewsEngine.refresh_all_news(connection: sqlite3.Connection, limit: int | None = None, force: bool = False) -> dict[str, object]
POST /news/refresh-all?limit=&force= -> NewsRefreshAllOut(summary: dict[str, int], results: list[NewsRefreshResultOut])
```

- [x] **Step 1: Scrivere test RED provider news**

Testare Finnhub GET con parametri non sensibili `symbol/from/to` e header `X-Finnhub-Token`; key sentinella assente da URL/fingerprint/cache/log/error; key mancante; payload list/errore/malformed; 429/cooldown e budget. Con cache preesistente verificare cache hit per `force=false`, una richiesta fisica governata e cache aggiornata per `force=true`, più due force concorrenti coalesciati sul fingerprint. Richiedere un provider symbol NEWS `VERIFIED` e venue compatibile: mapping mancante, ambiguo, retired o di venue incompatibile non chiama Finnhub e usa soltanto fallback locale. Verificare che Alpha non costruisca `_request_url`, Yahoo non effettui rete e che entrambi producano rispettivamente `SECRET_IN_QUERY_POLICY` e `NOT_PRIMARY_POLICY` con fallback locale.

- [x] **Step 2: Scrivere test RED batch bounded e compatibilità**

In `tests/test_api.py` coprire refresh singolo, firma `refresh_all_news(connection, limit=None, force=False)`, propagazione di `force`, payload vigente `NewsRefreshAllOut` con `summary/results`, refresh-all news con effective default 10 e range 1..25, soli active assets, simbolo ambiguo 409 e nessuna scansione catalogo. In `tests/test_alert_service.py` conservare scoring/news locali e sentinelle secret.

- [x] **Step 3: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_news_providers.py tests\test_api.py tests\test_alert_service.py -k "news_provider or news_refresh or news_secret or local_fallback" -q
```

Expected: Finnhub costruisce ancora token in query, Yahoo resta primario, Alpha costruisce apikey in query e refresh news non è governato dal nuovo budget.

- [x] **Step 4: Migrare Finnhub news al transport comune**

Usare host/path fissi, key solo header e params separati. `NewsEngine` risolve prima l'active asset in modo univoco e passa a Finnhub esclusivamente il provider symbol NEWS `VERIFIED` del listing, dopo il controllo della venue supportata; mapping assente/ambiguo/retired fallisce chiuso sul fallback locale. Applicare budget locale 55/minuto e il limite day/month configurato; normalizzare al massimo 50 articoli, validare timestamp/URL pubblici e mantenere il sentiment locale. Cache key usa request fingerprint sanitizzato; `FinnhubNewsProvider.get_news_for_symbol(symbol, force)` passa `bypass_cache=force` al transport.

- [x] **Step 5: Disabilitare Alpha/Yahoo e rendere bounded il batch**

`AlphaVantageNewsProvider` restituisce `DISABLED/SECRET_IN_QUERY_POLICY` prima di costruire URL. `YahooNewsProvider` restituisce `DISABLED/NOT_PRIMARY_POLICY` e non usa User-Agent/browser endpoint. `NewsEngine` prova Finnhub solo quando provider symbol e venue sono verificati, poi news locali; conserva il metodo `refresh_all_news(connection, limit=None, force=False)`, propaga `force` fino a `bypass_cache=force`, usa `assets` attivi ordinati, applica effective default 10/massimo 25 e non visita il catalogo. La route conserva il response model `NewsRefreshAllOut` e i campi `summary/results` correnti.

- [x] **Step 6: Eseguire GREEN e regressione news**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_news_providers.py tests\test_api.py tests\test_alert_service.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\news_base.py backend\app\data_providers\finnhub_news.py backend\app\data_providers\alpha_vantage_news.py backend\app\data_providers\yahoo_news.py backend\app\services\news_engine.py backend\app\api\routes.py tests\test_news_providers.py tests\test_api.py tests\test_alert_service.py
```

Expected: news fixture/locali verdi, nessun secret o rete live, batch bounded, Ruff verde.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente su query/header, cache fingerprint, provider priority, fallback locale, batch bound, symbol ambiguity e compatibilità sentiment. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add backend/app/config.py backend/app/data_providers/news_base.py backend/app/data_providers/finnhub_news.py backend/app/data_providers/alpha_vantage_news.py backend/app/data_providers/yahoo_news.py backend/app/data_providers/__init__.py backend/app/services/news_engine.py backend/app/models/schemas.py backend/app/api/routes.py .env.example backend/.env.example tests/fixtures/market_data/finnhub_company_news.json tests/fixtures/market_data/finnhub_company_news_empty.json tests/test_news_providers.py tests/test_api.py tests/test_alert_service.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "fix: govern real news providers and fallbacks"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 11 e gate remoto verde.

---

### Task 13: Pianificare refresh lazy, prioritari, deduplicati e limitati

**Branch:** `codex/investedge-phase-2-task-13`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-12`.

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/models/schemas.py`
- Create: `backend/app/services/refresh_planner_service.py`
- Modify: `backend/app/services/catalog_service.py`
- Modify: `backend/app/services/market_data_service.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/scripts/activate_real_data.py`
- Create: `tests/test_refresh_planner.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** `/data/refresh/{symbol}` resta refresh esplicito; `/data/refresh-all` resta disponibile con l'identico payload `DataRefreshAllOut(summary, results)` ma diventa sempre bounded e prioritario. `MarketDataService.refresh_all_watchlist(connection, limit=None, force=False)` conserva firma e propagazione di `force`. Nessun endpoint visita l'intero catalogo per default. Lo script non itera più ogni asset/provider e non contiene sleep fisso.

**Interfaces — Consumes:** posizioni esistenti, segnali/candidati analisi esistenti, `assets` come watchlist attiva, richieste/view esplicite, listing capability, freshness, tier e budget manager.

**Interfaces — Produces:**

```text
RefreshReason = Literal["POSITION", "STRATEGY_CANDIDATE", "WATCHLIST", "REQUESTED", "VIEWED", "CATALOG_EOD"]
RefreshState = Literal["PENDING", "RUNNING", "SUCCEEDED", "SKIPPED_FRESH", "BUDGET_DEFERRED", "FAILED"]

REFRESH_PRIORITY = {
    "POSITION": 10,
    "STRATEGY_CANDIDATE": 20,
    "WATCHLIST": 30,
    "REQUESTED": 40,
    "VIEWED": 50,
    "CATALOG_EOD": 60,
}

class RefreshPlannerService:
    def enqueue(self, connection, listing_id: int, capability: ProviderCapability, reason: RefreshReason, requested_at: datetime, force: bool = False) -> int
    def run_batch(self, connection, limit: int, now: datetime) -> RefreshBatchResult
@dataclass(frozen=True)
class RefreshBatchResult:
    selected: int
    succeeded: int
    skipped_fresh: int
    budget_deferred: int
    failed: int

MarketDataService.refresh_all_watchlist(connection: sqlite3.Connection, limit: int | None = None, force: bool = False) -> dict[str, object]
POST /data/refresh-all?limit=&force= -> DataRefreshAllOut(summary: dict[str, int], results: list[DataRefreshResultOut])

POST /data/refresh/viewed/{listing_id} -> refresh_request_id: int
CatalogEodEnqueueResult { enqueued: int, next_cursor: int | None }
POST /data/catalog/eod/enqueue?after_listing_id=0&limit=25 -> CatalogEodEnqueueResult
```

Nuove tabelle `refresh_requests` e `refresh_runs`; `refresh_requests` persiste anche `force` e la unique pending key `(listing_id, capability)` evita duplicati. `run_batch` accetta `1 <= limit <= 25`; config default 10.

- [x] **Step 1: Scrivere test RED su priorità e limiti**

Testare ordinamento esatto, tie-breaker requested_at/listing_id, deduplica reason con priorità più alta, skip fresh, budget deferred senza consumo, retry futuro senza loop e batch massimo 25. Una pending `force=false` seguita dalla stessa unità `force=true` deve promuovere atomicamente il flag; il contrario non lo declassa e `run_batch` consuma il valore persistito. Con cache provider preesistente, il run non-force usa cache; il run force passa `bypass_cache=true`, esegue una richiesta fisica soggetta a quota/validation e aggiorna la cache; due unità force concorrenti per lo stesso fingerprint restano coalesciate. Per `/data/refresh-all` verificare firma legacy, propagazione `force`, omissione limit -> 10, payload `DataRefreshAllOut`, chiavi summary vigenti `requested/updated/fallback/rows_inserted/rows_updated` e ogni result con tutti i campi `DataRefreshResultOut`. Coprire inoltre refresh singolo requested, endpoint viewed singolo, catalog EOD keyset limit 1..25 con pagina 1 → esecuzione → pagina 2 senza skip e assenza query che scansioni tutto `instrument_listings`.

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_refresh_planner.py tests\test_api.py -k "refresh_planner or refresh_all or priority or no_bulk" -q
```

Expected: failure perché refresh-all seleziona direttamente tutti gli `assets` e non esiste coda.

- [x] **Step 3: Implementare enqueue e scelta lazy**

`enqueue()` aggiorna una request pending esistente se arriva una priorità più alta o timestamp più vecchio e applica sempre `force = existing.force OR incoming.force` nella stessa transazione. `run_batch()` seleziona con `ORDER BY priority, requested_at, listing_id LIMIT ?`, marca RUNNING in transazione breve, legge il `force` persistito e poi esegue un listing per volta. Con `force=false`, stato fresh produce `SKIPPED_FRESH`; con `force=true` si salta la freshness e si chiama l'adapter con `bypass_cache=true`, ma fingerprint/deduplica in-flight, quota/cooldown e validation restano obbligatori. Errori sanitizzati diventano `FAILED` e non bloccano le altre unità.

- [x] **Step 4: Adattare API e sorgenti di priorità**

Refresh singolo risolve un solo active asset/listing univoco e accoda `REQUESTED` con il `force` ricevuto prima di eseguire. Refresh-all accoda con lo stesso flag: posizioni, candidati da segnali già esistenti e `assets` attivi; non accoda il catalogo. Un adapter converte ogni esito planner nel vigente `DataRefreshResultOut` (`symbol`, provider nullable, righe inserted/updated, cache/fallback e messaggio sanitizzato) e aggrega esattamente le chiavi summary Fase 1; gli stati deferred/failed sono fallback senza inventare provider o righe. `POST /data/refresh/viewed/{listing_id}` accoda una sola unità `VIEWED` non-force e sarà chiamato dal dettaglio Universe nel Task UI. `POST /data/catalog/eod/enqueue` usa keyset `WHERE listing_id > ? ORDER BY listing_id LIMIT ?` sui soli listing risolti, provider-mapped e non fresh, accoda al massimo 25 `CATALOG_EOD` non-force e restituisce come `next_cursor` l'ultimo listing ID esaminato o `NULL` a fine pagina. Non usa OFFSET: l'esecuzione della pagina precedente può cambiare freshness senza far saltare ID successivi. Non esiste default “tutto”. Impostare `limit=10` quando omesso per refresh-all e massimo 25 ovunque.

- [x] **Step 5: Correggere lo script operativo**

`activate_real_data.py` chiama esclusivamente il batch planner con `--limit` obbligatorio tra 1 e 25 e `--dry-run` default. Non cita Alpha come provider attivo, non dorme 13 secondi e non accetta un flag per tutto il catalogo.

- [x] **Step 6: Eseguire GREEN e regressione status**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_refresh_planner.py tests\test_api.py tests\test_provider_budget.py tests\test_market_data_observations.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\services\refresh_planner_service.py backend\app\services\market_data_service.py backend\app\api\routes.py backend\scripts\activate_real_data.py tests\test_refresh_planner.py
```

Expected: priorità/dedup/bounds verdi; route legacy compatibili; Ruff verde.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente su starvation, race/doppia esecuzione, default limit, scansioni catalogo, forced refresh, cooldown e script. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add backend/app/database.py backend/app/config.py backend/app/models/schemas.py backend/app/services/refresh_planner_service.py backend/app/services/catalog_service.py backend/app/services/market_data_service.py backend/app/api/routes.py backend/scripts/activate_real_data.py tests/test_refresh_planner.py tests/test_api.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add prioritized lazy market data refresh"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 12 e gate remoto verde.

---

### Task 14: Esporre API catalogo e conferme versionate di simboli e stato Trade Republic

**Branch:** `codex/investedge-phase-2-task-14`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-13`.

**Files:**

- Modify: `backend/app/database.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/catalog_service.py`
- Modify: `backend/app/services/instrument_service.py`
- Modify: `backend/app/services/assets_service.py`
- Modify: `backend/app/api/routes.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** `/assets` resta la lista piccola degli asset attivi e conserva create/delete/purge. Questo Task espone soltanto backend; la pagina Universe cambia nel Task successivo. Le conferme provider symbol e Trade Republic sono locali, versionate e protette da preview/apply, ma non eseguono rete, login, automazione UI o trading.

**Interfaces — Consumes:** instrument/listing/catalog/resolution/tier/current observation; stato iniziale TR `CATALOGED`; `AssetCreate` e protezioni purge; pagination query.

**Interfaces — Produces:**

```text
class InstrumentListItem(BaseModel):
    instrument_id: int
    canonical_name: str
    instrument_type: InstrumentType
    asset_class: AssetClass
    quality_tier: QualityTier
    quality_reasons: list[str]
    primary_identifier_scheme: IdentifierScheme | None
    primary_identifier: str | None
    listing_id: int | None
    ticker: str | None
    mic: str | None
    venue_name: str | None
    currency: str | None
    timezone: str | None
    trade_republic_status: str
    trade_republic_cataloged_at: datetime | None
    trade_republic_verified_at: datetime | None
    observation_quality: EffectiveObservationQuality | None
    observed_at: datetime | None

class InstrumentSearchOut(BaseModel):
    items: list[InstrumentListItem]
    total: int
    limit: int
    offset: int
    catalog_snapshot_id: int | None

class InstrumentIdentifierOut(BaseModel):
    scheme: IdentifierScheme
    value: str
    sources: list[str]
    first_observed_at: datetime
    last_observed_at: datetime

class InstrumentListingOut(BaseModel):
    listing_id: int
    ticker: str
    mic: str | None
    venue_name: str | None
    currency: str
    timezone: str | None
    resolution_status: ResolutionStatus
    trade_republic_status: str

class InstrumentDetailOut(InstrumentListItem):
    identifiers: list[InstrumentIdentifierOut]
    listings: list[InstrumentListingOut]

class ProviderSymbolPreviewIn(BaseModel):
    provider: Literal["stooq", "finnhub", "coingecko"]
    provider_symbol: str
    capability: ProviderCapability
    source: str
    observed_at: datetime
    expected_currency: str
    evidence_hash: str

class ProviderSymbolPreviewOut(BaseModel):
    listing_id: int
    normalized_provider_symbol: str
    current_version: int | None
    confirmation_token: str

class ProviderSymbolApplyIn(ProviderSymbolPreviewIn):
    confirmation_token: str

class ProviderSymbolApplyOut(BaseModel):
    listing_id: int
    provider: str
    capability: ProviderCapability
    normalized_provider_symbol: str
    version: int
    status: Literal["VERIFIED"]

TradeRepublicAttestationStatus = Literal["VERIFIED", "UNAVAILABLE"]
TradeRepublicAttestationSource = Literal["MANUAL_OFFICIAL_APP_CHECK", "OFFICIAL_SUPPORT_NOTICE"]

class TradeRepublicAttestationPreviewIn(BaseModel):
    status: TradeRepublicAttestationStatus
    source: TradeRepublicAttestationSource
    observed_at: datetime
    evidence_hash: str

class TradeRepublicAttestationPreviewOut(BaseModel):
    listing_id: int
    current_status: str
    current_version: int | None
    confirmation_token: str

class TradeRepublicAttestationApplyIn(TradeRepublicAttestationPreviewIn):
    confirmation_token: str

class TradeRepublicAttestationOut(BaseModel):
    listing_id: int
    status: TradeRepublicAttestationStatus
    source: TradeRepublicAttestationSource
    observed_at: datetime
    evidence_hash: str
    version: int
```

Endpoint:

```text
GET  /instruments?q=&asset_class=&instrument_type=&currency=&mic=&quality_tier=&trade_republic_status=&limit=50&offset=0
GET  /instruments/{instrument_id}
POST /assets/from-listing/{listing_id}
POST /instruments/listings/{listing_id}/provider-symbols/preview -> ProviderSymbolPreviewOut
POST /instruments/listings/{listing_id}/provider-symbols/apply -> ProviderSymbolApplyOut
POST /instruments/listings/{listing_id}/trade-republic/preview -> TradeRepublicAttestationPreviewOut
POST /instruments/listings/{listing_id}/trade-republic/apply -> TradeRepublicAttestationOut
```

Il POST di attivazione restituisce 201/`AssetOut`, è idempotente sullo stesso listing e restituisce 409 per mapping non risolto, conflitto legacy `(symbol, asset_type)` o listing cambiato. Provider symbol apply richiede lo stesso payload più `confirmation_token`, ricostruisce il token su stato locale e crea una nuova versione VERIFIED ritirando la precedente; stessa versione/evidence è idempotente. La nuova tabella history-preserving `trade_republic_attestations` contiene listing FK non nullable, business status `VERIFIED|UNAVAILABLE`, `record_status ACTIVE|RETIRED`, source allowlistata, observed_at UTC, evidence hash, version, supersedes FK nullable e created_at. `UNIQUE(listing_id, version)` mantiene la catena; l'indice parziale `UNIQUE(listing_id) WHERE record_status='ACTIVE'` ammette una sola versione corrente e rende implementabile il conflict gate concorrente. `instrument_listings.trade_republic_status/verified_at` è soltanto la projection atomica dell'attestation ACTIVE; `CATALOGED` non si auto-promuove.

- [x] **Step 1: Scrivere test API RED**

Testare ricerca case-insensitive su nome/ticker/ISIN/FIGI, filtri combinati, total, ordering stabile `canonical_name/instrument_id/listing_id`, limit 1..100, offset >=0, dettaglio 404, campi null espliciti, catalog snapshot, attivazione idempotente e conflitto venue. Per provider symbol testare provider/capability/valuta incompatibili, simbolo vuoto, source/evidence hash, normalizzazione provider-specifica, preview/apply stale 409 quando cambia anche solo `observed_at`, version/supersedes, idempotenza, vincolo VERIFIED per listing e collisione cross-listing del normalized symbol. Per Trade Republic provare: `CATALOGED` non diventa VERIFIED da solo; source/status allowlist; evidence hash; preview/apply stale e compare_digest; VERIFIED con verified_at; successivo UNAVAILABLE; catena `version/supersedes` e passaggio ACTIVE→RETIRED; repeat idempotente; due apply concorrenti producono una sola ACTIVE, una sola projection coerente e nessuna versione orfana; nessuna rete/credenziale/trading; output ricerca/dettaglio aggiornato. Verificare che `/assets` non includa instrument non attivati.

- [x] **Step 2: Eseguire RED backend**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_api.py -k "instrument_search or instrument_detail or activate_listing or assets_catalog_separation or provider_symbol or trade_republic_attestation" -q
```

Expected: 404 o failure schema perché endpoint, query e preview/apply provider symbol/TR non esistono.

- [x] **Step 3: Implementare API paginata e attivazione esplicita**

Costruire SQL parametrico con allowlist di filtri e due query coerenti count/items nella stessa connessione. Non interpolare sort/filter. Il dettaglio restituisce tutti i listing/candidate state, senza payload provider raw. Attivazione usa il listing selezionato, copia metadata verificati, collega `assets.instrument_listing_id` e non rilassa la unique legacy.

- [x] **Step 4: Implementare conferma provider symbol versionata**

Accettare soltanto provider/capability compatibili e listing `RESOLVED`; confrontare `expected_currency` con il listing. `source` è un codice descrittivo, non URL; `evidence_hash` è SHA-256 esadecimale. Il token canonico include listing/provider/symbol/capability/currency/source/`observed_at` UTC normalizzato/evidence/current version ed è confrontato con `hmac.compare_digest`. Apply non chiama provider, crea versione VERIFIED e ritira atomicamente l'eventuale versione corrente; ogni mutazione di `observed_at` tra preview/apply rende il token stale.

- [x] **Step 5: Implementare attestation Trade Republic locale**

Preview accetta soltanto listing RESOLVED e payload completo; token canonico include listing/status/source/observed_at/evidence/version dell'attestation ACTIVE. Apply usa `BEGIN IMMEDIATE`, ricostruisce/confronta con `hmac.compare_digest`, riusa idempotentemente lo stesso payload/evidence oppure aggiorna la precedente da ACTIVE a RETIRED, inserisce la nuova ACTIVE con `supersedes` e aggiorna la projection nella stessa transazione. L'ordine transazionale è retire precedente → insert nuova ACTIVE → update projection; qualsiasi errore, inclusa collisione concorrente dell'indice parziale, esegue rollback completo e viene riletto come idempotenza o 409 stale. `VERIFIED` imposta `trade_republic_verified_at=observed_at`; `UNAVAILABLE` imposta status UNAVAILABLE e verified_at NULL, conservando storia/cataloged_at. Nessun codice chiama provider o Trade Republic.

- [x] **Step 6: Eseguire GREEN backend**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_api.py -k "instrument or provider_symbol or trade_republic or assets" -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\database.py backend\app\models backend\app\services\catalog_service.py backend\app\services\instrument_service.py backend\app\services\assets_service.py backend\app\api\routes.py tests\test_api.py
```

Expected: API catalogo/identity/mapping verdi e Ruff verde.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente su paginazione/count, SQL injection, separazione catalogo/attivi, venue conflict, provider compatibility, evidence/token, version/supersedes, attestazioni TR e transazioni apply. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add backend/app/database.py backend/app/models/schemas.py backend/app/models/__init__.py backend/app/services/catalog_service.py backend/app/services/instrument_service.py backend/app/services/assets_service.py backend/app/api/routes.py tests/test_api.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: expose catalog and attestation APIs"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 13 e gate remoto verde.

---

### Task 15: Integrare il catalogo paginato nella pagina Universe

**Branch:** `codex/investedge-phase-2-task-15`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-14`.

**Files:**

- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/test/setup.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/DataQualityBadge.tsx`
- Create: `frontend/src/components/InstrumentIdentity.tsx`
- Modify: `frontend/src/pages/UniversePage.tsx`
- Create: `frontend/src/pages/UniversePage.test.tsx`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** `/universe`, form/azioni `Asset` e purge protetto restano disponibili. Nessuna modifica a App, Sidebar, Watchlist, Analysis o redesign a cinque hub. Il catalogo è un tab paginato separato dagli asset attivi.

**Interfaces — Consumes:** `InstrumentSearchOut`, `InstrumentDetailOut`, `AssetOut`, activation API e `POST /data/refresh/viewed/{listing_id}` prodotti dai Task backend precedenti.

**Interfaces — Produces:** tipi TypeScript omologhi `InstrumentListItem`, `InstrumentSearch`, `InstrumentDetail`, `InstrumentListing`, `EffectiveObservationQuality`; funzioni `getInstruments(filters)`, `getInstrument(id)`, `activateListing(id)`, `markListingViewed(id)`; test runner `npm run test:run`.

- [x] **Step 1: Installare il test runner**

```powershell
npm --prefix frontend install --save-dev vitest@4.1.10 @testing-library/react@16.3.2 @testing-library/jest-dom@7.0.1 jsdom@30.0.1
```

Expected: dipendenze e lockfile aggiornati; nessun test eseguito prima della configurazione.

- [x] **Step 2: Configurare il runner e scrivere i test UI**

Aggiungere esplicitamente `"test:run": "vitest run"` a `frontend/package.json`, creare `frontend/vitest.config.ts` con environment `jsdom` e creare `frontend/src/test/setup.ts` che importa `@testing-library/jest-dom/vitest`. Scrivere `UniversePage.test.tsx`: il test mocka `api.ts` e richiede tab “Attivi”/“Catalogo”, loading, empty, errore, debounce query, filtri/paginazione, badge tier/freschezza, ISIN/FIGI/MIC/valuta, mapping ambiguo non attivabile e nessun fetch bulk.

- [x] **Step 3: Eseguire RED UI**

```powershell
npm --prefix frontend run test:run -- UniversePage.test.tsx
```

Expected RED: Vitest/jsdom/setup partono correttamente e falliscono soltanto le aspettative UI catalogo non ancora implementate, non uno script, modulo o file di configurazione mancante.

- [x] **Step 4: Definire i tipi e il client sanitizzato**

Aggiungere i type senza cambiare `Asset`. Le funzioni codificano ogni query con `URLSearchParams`; `ApiError` conserva status e detail ma il messaggio di errore DEV usa metodo+pathname sanitizzato, mai URL/query completa. La fetch precedente viene abortita quando query/pagina cambia.

- [x] **Step 5: Implementare il tab catalogo**

Usare debounce 300 ms, `limit=50`, offset e ordering backend; non concatenare pagine. Aprire il dettaglio chiama una sola volta `markListingViewed(listing_id)` e non esegue subito il refresh provider. `DataQualityBadge` mostra tier/effective quality/stale; `InstrumentIdentity` mostra identifier, venue, currency e stato Trade Republic senza suggerire tradability. Attivazione resta esplicita e gestisce 409.

- [x] **Step 6: Eseguire GREEN e build**

```powershell
npm --prefix frontend run test:run -- UniversePage.test.tsx
npm --prefix frontend run build
```

Expected: test Universe verde e TypeScript/Vite build exit 0.

- [x] **Step 7: Review, commit e gate remoto**

Review indipendente su nullability Python/TypeScript, request abort/debounce, paginazione, URL sanitizzati, mark-viewed bounded, a11y e scope UI. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/test/setup.ts frontend/src/lib/api.ts frontend/src/components/DataQualityBadge.tsx frontend/src/components/InstrumentIdentity.tsx frontend/src/pages/UniversePage.tsx frontend/src/pages/UniversePage.test.tsx README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add the paginated Universe catalog"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 14 e gate remoto verde.

---

### Task 16: Calcolare API e metriche misurabili di copertura dati

**Branch:** `codex/investedge-phase-2-task-16`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-15`.

**Files:**

- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/data_coverage_service.py`
- Modify: `backend/app/services/market_data_service.py`
- Modify: `backend/app/api/routes.py`
- Create: `tests/test_data_coverage.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** `DataStatusOut` conserva `enable_real_data`, `provider_status`, `api_usage`, `cache_stats`, `global_last_update` e `data_mode`; `DataProviderStatusOut` conserva `provider`, `enabled`, `api_key_configured`, `daily_limit`, `calls_today`, `supports`. Questo Task espone soltanto backend; il Data Center cambia nel Task seguente.

**Interfaces — Consumes:** catalog snapshots/entries, resolution cases, instruments/listings/tier, market observations/rejections, `fx_rates`/FX freshness policy, provider budgets/log, refresh queue/runs, backup status.

**Interfaces — Produces:**

```text
class CoverageCount(BaseModel):
    key: str
    total: int
    resolved: int
    qualified: int
    observable: int
    reference_only: int

class ProviderCoverageOut(BaseModel):
    provider: str
    capability: ProviderCapability
    eligible_listings: int
    unmapped_listings: int
    mapped_listings: int
    fresh_listings: int
    stale_listings: int
    missing_observation_listings: int
    rejected_observations: int
    quality_counts: dict[str, int]
    delay_bucket_counts: dict[str, int]
    latest_provider_observed_at: datetime | None
    latest_ingested_at: datetime | None
    attribution: str | None

FxCoverageStatus = Literal["FRESH", "STALE", "MISSING"]
FxRateDirection = Literal["DIRECT", "INVERSE"]

class FxCoverageOut(BaseModel):
    from_currency: str
    to_currency: Literal["EUR"]
    status: FxCoverageStatus
    direction: FxRateDirection | None
    provider: str | None
    rate_to_eur: Decimal | None
    observed_at: datetime | None
    ingested_at: datetime | None
    age_seconds: int | None
    quality: str | None

# Contratto JSON: Pydantic serializza rate_to_eur come stringa decimale o null.
# Il client TypeScript usa esattamente `rate_to_eur: string | null`.

class DataCoverageOut(BaseModel):
    measured_at: datetime
    latest_catalog_snapshot_id: int | None
    latest_catalog_retrieved_at: datetime | None
    latest_catalog_sha256: str | None
    parse_accepted_entries: int
    parse_ambiguous_entries: int
    parse_rejected_entries: int
    parse_denominator: int
    resolution_resolved_entries: int
    resolution_ambiguous_entries: int
    resolution_unmatched_entries: int
    resolution_rejected_entries: int
    resolution_unprocessed_entries: int
    resolution_denominator: int
    resolved_percent: float
    tier_denominator: int
    tier_counts: dict[QualityTier, int]
    tier_percentages: dict[QualityTier, float]
    trade_republic_denominator: int
    trade_republic_status_counts: dict[str, int]
    trade_republic_verified_percent: float
    by_asset_class: list[CoverageCount]
    by_market: list[CoverageCount]
    rejection_reasons: dict[str, int]
    provider_coverage: list[ProviderCoverageOut]
    fx_currency_denominator: int
    fx_fresh_currencies: int
    fx_stale_currencies: int
    fx_missing_currencies: int
    fx_coverage: list[FxCoverageOut]
    pending_refresh: int
    budget_deferred: int
```

Nuovo endpoint `GET /data/coverage`; `/data/status` riceve un campo nullable/additivo `coverage_summary`. Percentuali hanno denominatore esplicito e `0.0` quando il totale è zero. Catalog count/resolution/rejection usano esclusivamente l'ultimo `catalog_snapshots.status="COMPLETE"`; per ogni entry ACCEPTED conta soltanto l'ultimo resolution case, oppure `resolution_unprocessed_entries` se non esiste. `parse_denominator` conta tutte le entry ACCEPTED/AMBIGUOUS/REJECTED dello snapshot e misura il parsing; deve valere `parse_accepted_entries + parse_ambiguous_entries + parse_rejected_entries == parse_denominator`. `resolution_denominator` coincide con `parse_accepted_entries`; deve valere `resolution_resolved_entries + resolution_ambiguous_entries + resolution_unmatched_entries + resolution_rejected_entries + resolution_unprocessed_entries == resolution_denominator`. Le rejection parser e resolution restano quindi distinte. `resolved_percent` usa soltanto `resolution_resolved_entries/resolution_denominator`. `tier_denominator` conta instrument distinti collegati alle entry ACCEPTED correnti. `trade_republic_denominator` coincide con le entry ACCEPTED correnti: ogni entry senza listing risolto entra nel bucket `UNRESOLVED_IDENTITY`, così gli irrisolti non spariscono dal denominatore TR; le altre entrano nello stato del listing. Le versioni precedenti restano consultabili ma non entrano nei denominatori correnti. `provider_coverage` esclude capability FX/listing: FX usa esclusivamente i campi `fx_*` derivati da `fx_rates`.

- [ ] **Step 1: Scrivere test RED su metriche**

Costruire fixture DB con due snapshot COMPLETE più uno FAILED, parse accepted/ambiguous/rejected, resolution case storici e latest per tutti gli stati `RESOLVED|AMBIGUOUS|UNMATCHED|REJECTED`, entry ACCEPTED mai processata, tre tier, TR unresolved/cataloged/verified prodotto tramite attestation service Task 14, provider EOD/QUOTE, mapping provider assente, mapping presente senza observation, dati fresh/stale/rejected e request deferred. Per FX usare `FXService.refresh_ecb()` con client fixture: una valuta fresh diretta, una inverse, una stale, una missing e EUR identity; verificare producer→coverage, denominatore e somma fresh/stale/missing senza creare listing/observation. Chiamare l'endpoint reale con `TestClient` e asserire che `rate_to_eur` valido sia una stringa decimale JSON e missing sia `null`, non un numero binary-float. Verificare inoltre che solo latest COMPLETE/latest case contino; le due invarianti di somma; rejection parser distinta da resolution; `resolved_percent` calcolato solo sugli ACCEPTED; irrisolti inclusi nel denominatore TR; conteggi e percentuali tier/TR; denominatore provider/capability; distinzione unmapped/missing observation; gruppi asset class/market, checksum, reason code, zero denominator, ordering, observed/ingested/delay e assenza di promesse statiche.

- [ ] **Step 2: Eseguire RED backend**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_data_coverage.py tests\test_api.py -k "coverage or data_status_compat" -q
```

Expected: failure perché servizio/endpoint/campi non esistono.

- [ ] **Step 3: Implementare aggregazioni coerenti**

Eseguire tutte le query con lo stesso `measured_at` e la stessa connessione. Selezionare prima latest snapshot COMPLETE e latest resolution case per entry con CTE/window deterministica; classificare con `CASE` ogni ACCEPTED in esattamente un bucket resolution, usando `UNPROCESSED` quando manca il case. Verificare le invarianti prima di costruire l'output. `resolved_percent = round(resolution_resolved_entries * 100 / resolution_denominator, 2)`; ogni tier percent usa `tier_denominator`; TR verified percent usa `trade_republic_denominator` e le entry senza listing restano `UNRESOLVED_IDENTITY`. “Fresh” usa la policy observation al momento della misura, non un flag persistito. Per market usare MIC; listing senza MIC sono bucket `UNRESOLVED`. Contare il catalogo una volta per `catalog_entry`, non per provider symbol o observation.

- [ ] **Step 4: Calcolare copertura, qualità e ritardo per provider**

Per ogni provider/capability non-FX definire `eligible_listings` come i listing risolti il cui tipo/metadata soddisfa la capability. Partizionare esattamente quel denominatore in `unmapped_listings` e `mapped_listings`; partizionare poi i mapped in `fresh_listings`, `stale_listings` e `missing_observation_listings`. Calcolare quality/delay bucket (`0-5m`, `5-30m`, `30m-24h`, `1-4d`, `>4d`), ultimo observed/ingested, rejection correnti e attribution. Usare l'ultima revisione observation valida e non moltiplicare listing per revision/eventi fallback.

Per FX costruire il set deterministico delle currency non-EUR distinte presenti in `assets`, `portfolio_positions` con quantità positiva e listing risolti. Per ciascuna cercare l'ultima riga diretta `currency/EUR`, altrimenti l'inversa `EUR/currency`, applicando la stessa soglia `ECB_FX_MAX_AGE_DAYS` e la stessa reciprocità di `FXService`; nessuna rete viene chiamata. Partizionare il denominatore in FRESH/STALE/MISSING e verificare la somma. EUR identity resta semantica `rate=1` di `FXService` ma non entra nel denominatore non-EUR. Non modificare o ricalcolare `fx_rate_to_base` congelati di posizioni/ordini.

- [ ] **Step 5: Estendere status provider additivamente e testare i timestamp**

Aggiungere capability, finestre minute/day/month con limit/used/remaining/reset_at, cooldown e ultimo outcome/reason. Non esporre key, URL, endpoint o fingerprint; i vecchi campi restano coerenti con la finestra giornaliera.

- [ ] **Step 6: Eseguire GREEN backend**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_data_coverage.py tests\test_api.py tests\test_provider_budget.py tests\test_refresh_planner.py tests\test_fx_service.py tests\test_portfolio_accounting.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\models backend\app\services\data_coverage_service.py backend\app\services\market_data_service.py backend\app\api\routes.py tests\test_data_coverage.py tests\test_api.py
```

Expected: metriche/status backend verdi e Ruff verde.

- [ ] **Step 7: Review, commit e gate remoto**

Review indipendente su latest snapshot/case, denominatori/percentuali, join moltiplicativi, freshness time-dependent, coverage FX separata/direct/inverse/identity, campi frozen EUR, observed/ingested/delay, segreti e attribuzioni. Correggere Critical/Important e ripetere Step 6.

```powershell
git diff --check
git add backend/app/models/schemas.py backend/app/models/__init__.py backend/app/services/data_coverage_service.py backend/app/services/market_data_service.py backend/app/api/routes.py tests/test_data_coverage.py tests/test_api.py README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: add measurable market data coverage"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 15 e gate remoto verde.

---

### Task 17: Presentare copertura, qualità e budget nel Data Center

**Branch:** `codex/investedge-phase-2-task-17`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-16`.

**Files:**

- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/DataCenterPage.tsx`
- Create: `frontend/src/pages/DataCenterPage.test.tsx`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Compatibility/caller:** Conservare pannello backup, status `SEED|MIXED|REAL`, provider/cache e route `/data`. Sostituire soltanto l'azione bulk indiscriminata con batch prioritario esplicitamente limitato; nessun nuovo hub/scheduler.

**Interfaces — Consumes:** `DataCoverageOut`, estensioni additive `DataStatusOut`/`DataProviderStatusOut`, `refreshAll(limit=10)`, backup API e tipi Universe già definiti.

**Interfaces — Produces:** tipi TypeScript omologhi per coverage/provider budget/FX, incluso `FxCoverage.rate_to_eur: string | null` coerente con il JSON Pydantic; `getDataCoverage()`; `refreshAll(limit: number)` che invia `POST /data/refresh-all?limit=<encoded>` senza body e restituisce il vigente `DataRefreshAllOut`; sezioni UI catalogo/resolution/tier/TR, provider freshness/delay/budget, FX EUR per currency, rejection e coda.

- [ ] **Step 1: Scrivere test UI RED**

`DataCenterPage.test.tsx` mocka `api.ts` e verifica: loading/empty/error; denominatori parsing/resolution, percentuali mapping, tier e TR inclusi gli irrisolti; provider eligible/unmapped/mapped/fresh/stale/missing observation, observed/ingested, delay bucket, quota/cooldown/reason; FX EUR separato con currency fresh/stale/missing, direct/inverse e timestamp; payload realistico `rate_to_eur: "0.923456789"`, valore null e stringa invalida visualizzata come `—`; rejection; attribution; backup panel invariato; bottone “Esegui batch prioritario (10)” che chiama una sola volta `refreshAll(10)`; assenza del testo/azione bulk indiscriminata. Aggiungere un test client che verifica metodo/path codificato e deserializzazione `DataRefreshAllOut`.

```powershell
npm --prefix frontend run test:run -- DataCenterPage.test.tsx
```

Expected RED: tipi, metriche e nuova azione non esistono.

- [ ] **Step 2: Aggiungere tipi e client coverage**

Modellare nullability e chiavi enum come nel backend; dichiarare `rate_to_eur: string | null` e un formatter che accetta solo una stringa decimale completa, verifica `Number.isFinite` dopo la conversione usata esclusivamente per la presentazione e restituisce `—` per null/invalido, senza usare il valore per calcoli. `getDataCoverage()` esegue una sola GET e usa error path sanitizzato. Implementare `refreshAll(limit)` in `api.ts` con validazione client `1..25`, `URLSearchParams` e una sola POST verso `/data/refresh-all`; preservare `summary/results` e tutti i campi `DataRefreshResult`. Non calcolare percentuali nel client: mostrare valori/denominatori restituiti dall'API.

- [ ] **Step 3: Implementare sezioni Data Center mirate**

Mostrare timestamp in timezone locale con UTC nel tooltip, quality/delay senza etichetta realtime quando stale, budget remaining/reset/cooldown e reason code leggibili. La sezione FX usa `fx_coverage`, non provider listing: mostra from/EUR, direct/inverse, fresh/stale/missing e observed/ingested senza modificare cambi congelati. Il batch button ha limit 10 fisso, loading separato e rieffettua status+coverage dopo successo. Mantenere intatti backup create/list e gestione errori.

- [ ] **Step 4: Eseguire GREEN, build e audit**

```powershell
npm --prefix frontend run test:run -- DataCenterPage.test.tsx UniversePage.test.tsx
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
```

Expected: test UI verdi, TypeScript/Vite build exit 0 e nessuna vulnerabilità high/critical.

- [ ] **Step 5: Review, commit e gate remoto**

Review indipendente su TypeScript/backend consistency, denominatori, stale/missing, timestamp/delay, secret/error, attribuzioni, backup panel e assenza bulk. Correggere Critical/Important e ripetere Step 4.

```powershell
git diff --check
git add frontend/src/lib/api.ts frontend/src/pages/DataCenterPage.tsx frontend/src/pages/DataCenterPage.test.tsx README.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git commit -m "feat: show governed coverage in Data Center"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 16 e gate remoto verde.

---

### Task 18: Eseguire audit cumulativo e pubblicare il report Fase 2

**Branch:** `codex/investedge-phase-2-task-18`

**Base remota esatta:** `origin/codex/investedge-phase-2-task-17`.

**Files:**

- Create: `docs/reports/2026-08-16-phase-2-verification.md`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

**Authorized correction paths (solo per correggere un rilievo Critical/Important riprodotto durante questo Task):**

- Modify: `.env.example`
- Modify: `backend/.env.example`
- Modify: `backend/requirements.txt`
- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/market_data.py`
- Modify: `backend/app/data_providers/__init__.py`
- Modify: `backend/app/data_providers/base.py`
- Modify: `backend/app/data_providers/transport.py`
- Modify: `backend/app/data_providers/provider_registry.py`
- Modify: `backend/app/data_providers/trade_republic_catalog.py`
- Modify: `backend/app/data_providers/openfigi.py`
- Modify: `backend/app/data_providers/stooq.py`
- Modify: `backend/app/data_providers/alpha_vantage.py`
- Modify: `backend/app/data_providers/finnhub_quote.py`
- Modify: `backend/app/data_providers/coingecko.py`
- Modify: `backend/app/data_providers/ecb.py`
- Modify: `backend/app/data_providers/fred.py`
- Modify: `backend/app/data_providers/news_base.py`
- Modify: `backend/app/data_providers/finnhub_news.py`
- Modify: `backend/app/data_providers/alpha_vantage_news.py`
- Modify: `backend/app/data_providers/yahoo_news.py`
- Modify: `backend/app/services/instrument_service.py`
- Modify: `backend/app/services/catalog_service.py`
- Modify: `backend/app/services/instrument_resolution_service.py`
- Modify: `backend/app/services/google_sheets_import_service.py`
- Modify: `backend/app/services/allocation_engine.py`
- Modify: `backend/app/services/provider_budget_service.py`
- Modify: `backend/app/services/market_observation_service.py`
- Modify: `backend/app/services/instrument_quality_service.py`
- Modify: `backend/app/services/market_data_service.py`
- Modify: `backend/app/services/prices_service.py`
- Modify: `backend/app/services/fx_service.py`
- Modify: `backend/app/services/refresh_planner_service.py`
- Modify: `backend/app/services/data_coverage_service.py`
- Modify: `backend/app/services/assets_service.py`
- Modify: `backend/app/services/news_engine.py`
- Modify: `backend/scripts/activate_real_data.py`
- Modify: `tests/fixtures/catalogs/trade_republic_it_excerpt.pdf`
- Modify: `tests/fixtures/catalogs/trade_republic_it_excerpt.expected.json`
- Modify: `tests/fixtures/catalogs/openfigi_mapping_success.json`
- Modify: `tests/fixtures/catalogs/openfigi_mapping_ambiguous.json`
- Modify: `tests/fixtures/catalogs/openfigi_mapping_unmatched.json`
- Modify: `tests/fixtures/market_data/stooq_daily.csv`
- Modify: `tests/fixtures/market_data/stooq_empty.csv`
- Modify: `tests/fixtures/market_data/stooq_malformed.csv`
- Modify: `tests/fixtures/market_data/finnhub_quote.json`
- Modify: `tests/fixtures/market_data/finnhub_quote_no_data.json`
- Modify: `tests/fixtures/market_data/coingecko_simple_price.json`
- Modify: `tests/fixtures/market_data/coingecko_market_chart.json`
- Modify: `tests/fixtures/market_data/coingecko_rate_limit.json`
- Modify: `tests/fixtures/market_data/ecb_exr_usd_eur.csv`
- Modify: `tests/fixtures/market_data/fred_series_observations.json`
- Modify: `tests/fixtures/market_data/fred_missing_value.json`
- Modify: `tests/fixtures/market_data/finnhub_company_news.json`
- Modify: `tests/fixtures/market_data/finnhub_company_news_empty.json`
- Modify: `tests/test_alert_service.py`
- Modify: `tests/test_database.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_import_security.py`
- Modify: `tests/test_provider_budget.py`
- Modify: `tests/test_instrument_catalog.py`
- Modify: `tests/test_instrument_resolution.py`
- Modify: `tests/test_market_data_observations.py`
- Modify: `tests/test_instrument_quality.py`
- Modify: `tests/test_eod_providers.py`
- Modify: `tests/test_finnhub_provider.py`
- Modify: `tests/test_coingecko_provider.py`
- Modify: `tests/test_fx_service.py`
- Modify: `tests/test_reference_providers.py`
- Modify: `tests/test_news_providers.py`
- Modify: `tests/test_refresh_planner.py`
- Modify: `tests/test_data_coverage.py`
- Modify: `tests/test_portfolio_accounting.py`
- Modify: `README.md`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vitest.config.ts`
- Modify: `frontend/src/test/setup.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/DataQualityBadge.tsx`
- Modify: `frontend/src/components/InstrumentIdentity.tsx`
- Modify: `frontend/src/pages/UniversePage.tsx`
- Modify: `frontend/src/pages/UniversePage.test.tsx`
- Modify: `frontend/src/pages/DataCenterPage.tsx`
- Modify: `frontend/src/pages/DataCenterPage.test.tsx`
- Modify: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`

Non modificare file fuori da questo elenco. Una correzione deve includere il test di regressione nello stesso Task; non aggiungere funzionalità o refactoring.

**Compatibility/caller:** L'audit copre l'intero diff cumulativo `origin/codex/investedge-phase-2-plan..HEAD`, con attenzione a tutti i caller Fase 1: portfolio/EUR, allocation, preview/apply import, purge/backup, prices, dashboard, analysis/signals, backtest, ML, news e frontend. Nessun servizio live è contattato.

**Interfaces — Consumes:** tutti i contratti e gate Task 1–17; specifica broker-grade Fase 2; report Fase 1; output test/build/audit; review indipendente.

**Interfaces — Produces:** report con sezioni obbligatorie `Scope`, `Commit chain`, `Schema and migrations`, `Phase 1 compatibility`, `Catalog and identity`, `Observation quality gates`, `Provider matrix and budgets`, `EUR FX`, `Lazy refresh`, `Coverage metrics`, `Security and backups`, `Verification evidence`, `Independent review`, `Residual risks`. Ogni comando riporta exit code e conteggio verificato; ogni rischio ha impatto e mitigazione corrente.

- [ ] **Step 1: Verificare storia lineare e scope cumulativo**

```powershell
$phase2Base = (git rev-parse origin/codex/investedge-phase-2-plan).Trim()
$phase2Head = (git rev-parse HEAD).Trim()
git rev-list --count "$phase2Base..$phase2Head"
git log --oneline --decorate "$phase2Base..$phase2Head"
git diff --name-status "$phase2Base..$phase2Head"
git status --short
```

Expected prima del commit finale: `17` commit lineari, solo file autorizzati dai Task 1–17, working tree pulito. Verificare per ogni commit un solo parent e il messaggio esatto del Task.

- [ ] **Step 2: Eseguire suite completa backend e controlli statici**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend scripts tests
& '.\backend\.venv\Scripts\python.exe' -m compileall -q backend\app backend\scripts scripts
& '.\backend\.venv\Scripts\python.exe' -m pip check
```

Expected: tutti i test passano senza rete; Ruff e compileall exit 0; pip riporta `No broken requirements found.`. Annotare nel report il numero effettivo di test/casi, senza copiarlo come promessa in questo piano.

- [ ] **Step 3: Eseguire suite, build e audit frontend**

```powershell
npm --prefix frontend ci
npm --prefix frontend run test:run
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
```

Expected: test Vitest verdi, TypeScript/Vite build exit 0, nessuna vulnerabilità high/critical. Non usare fix automatici forzati.

- [ ] **Step 4: Eseguire smoke fixture e gate dati**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_instrument_catalog.py tests\test_instrument_resolution.py tests\test_market_data_observations.py tests\test_instrument_quality.py tests\test_eod_providers.py tests\test_finnhub_provider.py tests\test_coingecko_provider.py tests\test_fx_service.py tests\test_reference_providers.py tests\test_news_providers.py tests\test_refresh_planner.py tests\test_data_coverage.py -q
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_database.py tests\test_portfolio_accounting.py tests\test_import_security.py -k "backup or migration or rollback or stale or missing or token or secret" -q
```

Expected: fixture smoke verde senza credenziali; gate valid/missing/stale/corrupt/ambiguous/rate-limit/fallback/dedup/tier/EUR verde; backup fail-closed e token stale verdi.

- [ ] **Step 5: Eseguire scan segreti, marcatori incompleti e diff**

```powershell
$phase2Files = @(
    git diff --name-only origin/codex/investedge-phase-2-plan...HEAD
    git diff --name-only
    git ls-files --others --exclude-standard
) | Sort-Object -Unique | Where-Object { $_ -and $_ -ne 'frontend/package-lock.json' -and $_ -notmatch '\.pdf$' -and (Test-Path -LiteralPath $_ -PathType Leaf) }
if ($phase2Files.Count -eq 0) { throw "Diff Fase 2 vuoto o non leggibile" }
$secretValuePattern = '(?i)(?:(?<![A-Za-z0-9])\Ksk-[A-Za-z0-9]{20,}|["'']?(?:api[_-]?key|access[_-]?token|token)["'']?\s*[:=]\s*["'']?\K[A-Za-z0-9._-]{20,}|(?:["'']?authorization["'']?\s*[:=]\s*["'']?)?bearer\s+\K[A-Za-z0-9._~+/-]{20,})'
$allowedSyntheticValue = '^(?:SENTINEL|TEST|DUMMY)_[A-Z0-9_]{4,}$'
function Test-AllowedSyntheticMatch([string]$match) { $separator = $match.IndexOf(':'); if ($separator -lt 1) { return $false }; $path = $match.Substring(0, $separator); $value = $match.Substring($separator + 1); return $path -match '^tests[\\/]' -and $value -match $allowedSyntheticValue }
$jsonProbe = 'ABCDEFGHIJKL' + 'MNOPQRSTUVWX'
$yamlProbe = 'ZYXWVUTSRQPO' + 'NMLKJIHGFEDC'
$bearerProbe = 'abcdefghijklmnop' + 'qrstuvwxyz012345'
$syntheticProbe = 'TEST_ALLOWED_' + 'TOKEN_12345'
$mixedRealProbe = 'REALVALUEABC' + 'DEFGHIJKLMNOP'
$scannerProbe = @('{"api_key":"' + $jsonProbe + '"}', 'token: ' + $yamlProbe, 'Authorization: Bearer ' + $bearerProbe, 'token: ' + $syntheticProbe + ' token: ' + $mixedRealProbe)
$probeValues = @($scannerProbe | & rg --pcre2 --only-matching --no-filename -- $secretValuePattern)
$probeMatches = @($probeValues | ForEach-Object { "tests/probe.py:$_" }) + @("backend/probe.py:$syntheticProbe")
$probeUnexpected = @($probeMatches | Where-Object { -not (Test-AllowedSyntheticMatch $_) })
if ($LASTEXITCODE -ne 0 -or $probeValues.Count -ne 5 -or $probeMatches.Count -ne 6 -or $probeUnexpected.Count -ne 5) { throw "Self-test secret scan JSON/YAML/Bearer/mixed/path fallito" }
$secretValues = @(& rg --pcre2 --only-matching --with-filename -- $secretValuePattern $phase2Files)
if ($LASTEXITCODE -gt 1) { throw "Secret scan non eseguito" }
$unexpectedSecretCount = @($secretValues | Where-Object { -not (Test-AllowedSyntheticMatch $_) }).Count
$allowedSyntheticCount = $secretValues.Count - $unexpectedSecretCount
if ($unexpectedSecretCount -gt 0) { throw "Candidate secret inatteso nel diff: count=$unexpectedSecretCount" }
"Secret scan: unexpected=0 synthetic=$allowedSyntheticCount"
$incomplete = @(& rg -n --no-heading '(T[B]D|FIXM[E]|X[X]X|pass[[:space:]]*#|NotImplementedErro[r])' -- $phase2Files)
if ($LASTEXITCODE -gt 1) { throw "Placeholder scan non eseguito" }
if ($incomplete.Count -gt 0) { $incomplete; throw "Placeholder introdotto dalla Fase 2" }
git diff --check origin/codex/investedge-phase-2-plan...HEAD
```

Expected: nessun candidate secret inatteso in file committed, modificati o untracked; sono tollerate soltanto sentinelle nominate `SENTINEL_*`, `TEST_*` o `DUMMY_*` dentro `tests/` e il report ne registra il conteggio. Il pattern copre assegnazioni/query/JSON/YAML con `:` o `=`, token Bearer e chiavi `sk-` di lunghezza realistica, senza intercettare i branch `task-N`. Nessun marcatore incompleto nel diff; `git diff --check` senza output. Le occorrenze preesistenti fuori dal diff non sono scansionate né modificate.

- [ ] **Step 6: Richiedere review indipendente cumulativa**

Usare `superpowers:requesting-code-review` con base `origin/codex/investedge-phase-2-plan`, head corrente e questo prompt minimo:

```text
Review the cumulative Phase 2 diff against the approved broker-grade spec and the Phase 2 plan. Verify scope boundaries, Phase 1 contracts, migrations/backup fail-closed, identity ambiguity, observation validation/freshness, provider budget/retry/fallback, no secrets in URLs/logs, EUR FX, lazy prioritization, coverage denominators, API/TypeScript consistency and fixture-only tests. Report Critical, Important and Minor findings with exact files/lines. Do not edit files.
```

Expected: review ricevuta e registrata nel report. Riprodurre ogni rilievo; usare `superpowers:systematic-debugging` per failure o comportamento inatteso. Correggere tutti i Critical/Important nei path autorizzati, aggiungere il test mirato, poi ripetere Steps 2–5 e richiedere re-review del delta. I Minor residui devono essere rischi reali documentati, non difetti funzionali o di sicurezza rinviati.

- [ ] **Step 7: Scrivere il report con evidenza reale**

Creare `docs/reports/2026-08-16-phase-2-verification.md` usando esclusivamente SHA, count, output e review appena osservati. Includere la matrice provider con capability effettive, limiti configurati, autenticazione, fallback e rischio; dichiarare esplicitamente che non sono state eseguite API live e che la copertura è una metrica dinamica, non un numero garantito.

- [ ] **Step 8: Verifica finale, commit e push**

Rieseguire `superpowers:verification-before-completion`, il controllo delle checkbox Task 1–18 e lo scan Step 5 dopo la creazione del report. Il secondo scan deve includere esplicitamente `docs/reports/2026-08-16-phase-2-verification.md` e ogni altra modifica/untracked del Task 18 prima dello staging.

```powershell
$phase2Files = @(
    git diff --name-only origin/codex/investedge-phase-2-plan...HEAD
    git diff --name-only
    git ls-files --others --exclude-standard
    'docs/reports/2026-08-16-phase-2-verification.md'
) | Sort-Object -Unique | Where-Object { $_ -and $_ -ne 'frontend/package-lock.json' -and $_ -notmatch '\.pdf$' -and (Test-Path -LiteralPath $_ -PathType Leaf) }
$secretValuePattern = '(?i)(?:(?<![A-Za-z0-9])\Ksk-[A-Za-z0-9]{20,}|["'']?(?:api[_-]?key|access[_-]?token|token)["'']?\s*[:=]\s*["'']?\K[A-Za-z0-9._-]{20,}|(?:["'']?authorization["'']?\s*[:=]\s*["'']?)?bearer\s+\K[A-Za-z0-9._~+/-]{20,})'
$allowedSyntheticValue = '^(?:SENTINEL|TEST|DUMMY)_[A-Z0-9_]{4,}$'
function Test-AllowedSyntheticMatch([string]$match) { $separator = $match.IndexOf(':'); if ($separator -lt 1) { return $false }; $path = $match.Substring(0, $separator); $value = $match.Substring($separator + 1); return $path -match '^tests[\\/]' -and $value -match $allowedSyntheticValue }
$jsonProbe = 'ABCDEFGHIJKL' + 'MNOPQRSTUVWX'
$yamlProbe = 'ZYXWVUTSRQPO' + 'NMLKJIHGFEDC'
$bearerProbe = 'abcdefghijklmnop' + 'qrstuvwxyz012345'
$syntheticProbe = 'TEST_ALLOWED_' + 'TOKEN_12345'
$mixedRealProbe = 'REALVALUEABC' + 'DEFGHIJKLMNOP'
$scannerProbe = @('{"api_key":"' + $jsonProbe + '"}', 'token: ' + $yamlProbe, 'Authorization: Bearer ' + $bearerProbe, 'token: ' + $syntheticProbe + ' token: ' + $mixedRealProbe)
$probeValues = @($scannerProbe | & rg --pcre2 --only-matching --no-filename -- $secretValuePattern)
$probeMatches = @($probeValues | ForEach-Object { "tests/probe.py:$_" }) + @("backend/probe.py:$syntheticProbe")
$probeUnexpected = @($probeMatches | Where-Object { -not (Test-AllowedSyntheticMatch $_) })
if ($LASTEXITCODE -ne 0 -or $probeValues.Count -ne 5 -or $probeMatches.Count -ne 6 -or $probeUnexpected.Count -ne 5) { throw "Self-test secret scan finale JSON/YAML/Bearer/mixed/path fallito" }
$secretValues = @(& rg --pcre2 --only-matching --with-filename -- $secretValuePattern $phase2Files)
if ($LASTEXITCODE -gt 1) { throw "Secret scan finale non eseguito" }
$unexpectedSecretCount = @($secretValues | Where-Object { -not (Test-AllowedSyntheticMatch $_) }).Count
$allowedSyntheticCount = $secretValues.Count - $unexpectedSecretCount
if ($unexpectedSecretCount -gt 0) { throw "Candidate secret inatteso nel gate finale: count=$unexpectedSecretCount" }
"Secret scan finale: unexpected=0 synthetic=$allowedSyntheticCount"
$incomplete = @(& rg -n --no-heading '(T[B]D|FIXM[E]|X[X]X|pass[[:space:]]*#|NotImplementedErro[r])' -- $phase2Files)
if ($LASTEXITCODE -gt 1 -or $incomplete.Count -gt 0) { $incomplete; throw "Placeholder scan finale fallito" }
git diff --check
git add .env.example backend/.env.example backend/requirements.txt backend/app/database.py backend/app/config.py backend/app/api/routes.py backend/app/models/schemas.py backend/app/models/__init__.py backend/app/models/market_data.py backend/app/data_providers/__init__.py backend/app/data_providers/base.py backend/app/data_providers/transport.py backend/app/data_providers/provider_registry.py backend/app/data_providers/trade_republic_catalog.py backend/app/data_providers/openfigi.py backend/app/data_providers/stooq.py backend/app/data_providers/alpha_vantage.py backend/app/data_providers/finnhub_quote.py backend/app/data_providers/coingecko.py backend/app/data_providers/ecb.py backend/app/data_providers/fred.py backend/app/data_providers/news_base.py backend/app/data_providers/finnhub_news.py backend/app/data_providers/alpha_vantage_news.py backend/app/data_providers/yahoo_news.py backend/app/services/instrument_service.py backend/app/services/catalog_service.py backend/app/services/instrument_resolution_service.py backend/app/services/google_sheets_import_service.py backend/app/services/allocation_engine.py backend/app/services/provider_budget_service.py backend/app/services/market_observation_service.py backend/app/services/instrument_quality_service.py backend/app/services/market_data_service.py backend/app/services/prices_service.py backend/app/services/fx_service.py backend/app/services/refresh_planner_service.py backend/app/services/data_coverage_service.py backend/app/services/assets_service.py backend/app/services/news_engine.py backend/scripts/activate_real_data.py tests/fixtures/catalogs/trade_republic_it_excerpt.pdf tests/fixtures/catalogs/trade_republic_it_excerpt.expected.json tests/fixtures/catalogs/openfigi_mapping_success.json tests/fixtures/catalogs/openfigi_mapping_ambiguous.json tests/fixtures/catalogs/openfigi_mapping_unmatched.json tests/fixtures/market_data/stooq_daily.csv tests/fixtures/market_data/stooq_empty.csv tests/fixtures/market_data/stooq_malformed.csv tests/fixtures/market_data/finnhub_quote.json tests/fixtures/market_data/finnhub_quote_no_data.json tests/fixtures/market_data/coingecko_simple_price.json tests/fixtures/market_data/coingecko_market_chart.json tests/fixtures/market_data/coingecko_rate_limit.json tests/fixtures/market_data/ecb_exr_usd_eur.csv tests/fixtures/market_data/fred_series_observations.json tests/fixtures/market_data/fred_missing_value.json tests/fixtures/market_data/finnhub_company_news.json tests/fixtures/market_data/finnhub_company_news_empty.json tests/test_alert_service.py tests/test_database.py tests/test_api.py tests/test_import_security.py tests/test_provider_budget.py tests/test_instrument_catalog.py tests/test_instrument_resolution.py tests/test_market_data_observations.py tests/test_instrument_quality.py tests/test_eod_providers.py tests/test_finnhub_provider.py tests/test_coingecko_provider.py tests/test_fx_service.py tests/test_reference_providers.py tests/test_news_providers.py tests/test_refresh_planner.py tests/test_data_coverage.py tests/test_portfolio_accounting.py README.md frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/test/setup.ts frontend/src/lib/api.ts frontend/src/components/DataQualityBadge.tsx frontend/src/components/InstrumentIdentity.tsx frontend/src/pages/UniversePage.tsx frontend/src/pages/UniversePage.test.tsx frontend/src/pages/DataCenterPage.tsx frontend/src/pages/DataCenterPage.test.tsx docs/reports/2026-08-16-phase-2-verification.md docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md
git diff --cached --check
git commit -m "chore: verify phase 2 instruments and market data"
git push -u origin HEAD
```

Expected: un solo commit sopra Task 17; nessun file fuori scope è staged.

- [ ] **Step 9: Eseguire gate remoto finale**

```powershell
$finalBranch = (git branch --show-current).Trim()
$finalHead = (git rev-parse HEAD).Trim()
$finalParent = (git rev-parse HEAD^).Trim()
$expectedParent = (git rev-parse origin/codex/investedge-phase-2-task-17).Trim()
$finalRemote = ((git ls-remote origin "refs/heads/codex/investedge-phase-2-task-18") -split "\s+")[0]
$finalUpstream = (git rev-parse --abbrev-ref --symbolic-full-name '@{u}').Trim()
$phase2Base = (git rev-parse origin/codex/investedge-phase-2-plan).Trim()
git status --short
git rev-list --count "$phase2Base..$finalHead"
if ($finalBranch -ne "codex/investedge-phase-2-task-18") { throw "Branch finale errato" }
if ($finalParent -ne $expectedParent) { throw "Parent finale errato" }
if ($finalRemote -ne $finalHead) { throw "Remote finale divergente" }
if ($finalUpstream -ne "origin/codex/investedge-phase-2-task-18") { throw "Upstream finale errato" }
```

Expected: working tree pulito, count cumulativo `18`, parent uguale a Task 17, upstream corretto e `ls-remote == HEAD`. Solo dopo questo gate la Fase 2 può essere dichiarata completa.

---

## Gate di completamento della Fase 2

- Instrument master e catalogo sono separati dall'universo attivo; identificativi e listing ambigui non vengono fusi o selezionati automaticamente.
- Ogni snapshot catalogo è versionato e misurabile; Trade Republic resta fonte storica, non garanzia di tradability.
- Ogni osservazione promossa è valida, deduplicata, tracciabile per provider/timestamp/session/currency/quality/fallback e non elimina l'ultimo dato buono.
- Tier e declassamenti hanno evidence hash e reason code; `Qualified` non equivale ad autorizzazione di trading.
- Provider gratuiti rispettano capability, budget, timeout/retry/cooldown e fallback compatibili; Alpha/Yahoo non sono primari e nessun secret entra in URL/log/cache.
- FX ECB verso EUR preserva direct/inverse/identity, stale/missing e cambio congelato della Fase 1; FRED resta reference-only.
- Refresh singolo e batch sono lazy, prioritari, deduplicati e limitati; nessun percorso default scansiona tutto il catalogo.
- Universe espone catalogo paginato senza sostituire `/assets`; Data Center mostra copertura reale, freschezza, rejection, tier, catalog version e budget senza promettere realtime universale.
- Suite completa, build, audit, fixture smoke, backup/rollback, secret scan, diff review, review indipendente e gate remoto finale sono verdi e documentati.

## Rischi residui e assunzioni da mantenere visibili

- Trade Republic può cambiare PDF, formato o universo senza preavviso; checksum/version history e parser fail-closed riducono l'impatto, ma non verificano la disponibilità corrente.
- OpenFIGI può restituire candidate multiple o cambiare limiti; l'ambiguità riduce la copertura ma non autorizza matching euristico.
- Stooq non offre nel materiale ufficiale individuato una API/SLA stabile; per questo resta opt-in, EOD e sostituibile senza perdere l'ultimo dato valido.
- Free tier, diritti d'uso, attribution e limiti di CoinGecko, Finnhub, FRED e Alpha possono cambiare. Le policy vanno riverificate sulle fonti ufficiali prima di una release, senza alzare automaticamente i budget. FRED resta disabilitato finché non esiste un percorso ufficiale per-serie che soddisfi insieme secret-in-header e refresh lazy.
- La quota Finnhub gratuita non fornisce uno storico candle universale e l'internazionale realtime non rientra nello scope; EOD e snapshot restano capability distinte.
- Alpha è deliberatamente inutilizzabile finché richiede un secret in query; la copertura inferiore è preferita alla violazione della policy.
- Le chiusure EOD attraversano weekend/festività e mercati/timezone diversi; le soglie di freschezza sono conservative e devono restare configurate e testate per capability.
- `assets` conserva la unique legacy `(symbol, asset_type)`: il master può rappresentare listing omonimi, ma l'attivazione simultanea di collisioni resta bloccata con 409 fino a una futura migrazione esplicita fuori da questa fase.
- “Copertura massima” resta un obiettivo ottimizzato entro identità verificata, fonti gratuite e budget; le metriche osservate nel Data Center sono l'unica misura accettabile e possono diminuire.
