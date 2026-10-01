# Verifica Fase 2 — Instruments and Market Data

Data di esecuzione: 1 ottobre 2026 (Europe/Rome). Esecutore: Claude (Claude Code), worktree `C:\Users\izzod\Documents\InvestEdge\.claude\worktrees\jolly-heisenberg-d8a20e`, branch `codex/investedge-phase-2-task-18`.

Dichiarazioni:

- **Nessuna API live è stata chiamata.** Test, smoke e review usano solo fixture locali o sintetiche. Una run completa della suite con DNS e socket non-loopback bloccati ha registrato 0 tentativi di rete.
- **La copertura è una metrica dinamica**, misurata da `GET /data/coverage` al momento della richiesta e soggetta a diminuire. Non è un numero garantito. Questo report non riporta percentuali di copertura reali perché nessun catalogo reale è stato scaricato.
- Tutti gli SHA, i conteggi e gli output sono stati osservati in questa sessione. Il commit del Task 18 non può contenere il proprio SHA: lo registra il commit successivo.

## Scope

- Perimetro auditato: diff cumulativo `origin/codex/investedge-phase-2-plan` = `56499829a85b59e7fc96ee668ac77bce7f3226ee` → `origin/codex/investedge-phase-2-task-17` = `8d95373f53959a814665d83a851f6e6d0f9728f7`, uguale a `origin/main` all'avvio (verificato con `git rev-parse` e `git ls-remote`).
- Dimensione: 99 file, 33.828 inserimenti, 1.250 rimozioni (`git diff --shortstat`).
- In scope: instrument master e listing, catalogo Trade Republic versionato, risoluzione OpenFIGI, tier di qualità, osservazioni di mercato, provider gratuiti e fallback, FX verso EUR, budget e refresh lazy prioritario, copertura, pagine Universe e Data Center.
- Esclusioni rispettate:
  - nessun portafoglio multiplo, paper broker, scheduler, hub UI, mobile o trading reale;
  - nessuna credenziale broker;
  - nessuno scraping o automazione di Trade Republic: il catalogo è il PDF ufficiale pubblico, aggiornato solo manualmente.
  - Verifica: elenco file per commit (sezione Commit chain) e review indipendente.
- Ambiente: Windows 11 Home 10.0.26200; PowerShell 7.6; Python 3.14.7 in `backend/.venv`, creato nel worktree e installato da rete senza deviazioni; pytest 8.4.2; Ruff 0.16.9; Node.js 24.19.0; npm 11.17.0; Vitest 4.1.10; Vite 7.3.6; ripgrep 15.2.0.
- Il database reale `data/investedge.db` non è mai stato aperto: ogni smoke usa `INVESTEDGE_DB_PATH` su file temporanei, poi rimossi.
- Correzioni del Task 18 (sezione Independent review): 17 file, 395 inserimenti, 33 rimozioni, più questo report, il piano e `PROGRAMMA-OPERATIVO.md`.

## Commit chain

Comandi: `git rev-list --count 5649982..8d95373` = **20** (exit 0); `git rev-list --merges --count` = **0**; `git log --format='%H %P'`: ogni commit ha **un solo parent**, uguale al commit precedente della catena.

| # | SHA | Task | Messaggio | Confronto con il piano |
|---:|---|---|---|---|
| 1 | `d75d8b0` | 1 | feat: add instrument master and listing identity | identico |
| 2 | `ad3e118` | 2 | feat: add provider budget and safe transport | identico |
| 3 | `d39a5dd` | 3 | feat: add versioned Trade Republic catalog | identico |
| 4 | `2ca7f5f` | 4 | feat: resolve and disambiguate instrument listings | identico |
| 5 | `127d899` | 5 | fix: bind destructive previews to resolved listings | identico (prefisso `fix:` previsto dal piano) |
| 6 | `415e870` | 6 | feat: add validated market data observations | identico |
| 7 | `d5599a1` | 7 | feat: add instrument quality tier assessments | identico |
| 8 | `98de55a` | 8 | feat: add governed EOD market data fallback | identico |
| 9 | `9503e70` | 9 | feat: add governed Finnhub US quotes | identico |
| 10 | `54b3faf` | 10 | chore: checkpoint partial Task 10 and add agent handoff | checkpoint autorizzato (registro decisioni 2026-09-30) |
| 11 | `49cdb82` | 10 | feat: add governed CoinGecko crypto data | identico |
| 12 | `6dda839` | — | docs: add operational program and agent protocol | commit documentale autorizzato (registro decisioni 2026-09-30) |
| 13 | `88fc20d` | 11 | feat: add governed EUR FX and reference data | identico |
| 14 | `dbbcc65` | 12 | chore: checkpoint Phase 2 Task 12 news providers | checkpoint per limite di utilizzo (Evidenza Task 12) |
| 15 | `edbc07e` | 12 | fix: govern real news providers and fallbacks | identico (prefisso `fix:` previsto dal piano) |
| 16 | `b1a39e2` | 13 | feat: add prioritized lazy market data refresh | identico |
| 17 | `62ed48b` | 14 | feat: expose catalog and attestation APIs | identico |
| 18 | `30069f0` | 15 | feat: add the paginated Universe catalog | identico |
| 19 | `d0d6b4c` | 16 | feat: add measurable market data coverage | identico |
| 20 | `8d95373` | 17 | feat: show governed coverage in Data Center | identico |

Il piano prevede 17 commit prima del Task 18 e 18 dopo. Il conteggio osservato è 20, per le tre eccezioni registrate: checkpoint Task 10, checkpoint Task 12 e commit documentale `6dda839`. Dopo il commit del Task 18 il conteggio atteso è **21**.

### File fuori dagli elenchi dei Task 1–17

Script di confronto: per ogni commit, `git diff-tree` contro le righe `Create/Modify/Test` del blocco *Files* del relativo Task. Risultato: 39 occorrenze fuori elenco, di cui **3 non registrate**.

| Commit | Task | File fuori elenco | Registrazione |
|---|---|---|---|
| `ad3e118` | 2 | `backend/app/data_providers/finnhub_news.py` | **non registrato**. Porta le news Finnhub sul trasporto governato (token da query string a header). Il file è autorizzato nei Task 12 e 18. |
| `2ca7f5f` | 4 | `tests/test_database.py` | **non registrato**. Test di migrazione dell'indice `uq_instrument_listings_market_identity` con `instrument_id`; solo test. |
| `54b3faf` | 10 | `HANDOFF.md`, `NEXT_AGENT_PROMPT.md`, `ROADMAP.md` | registro decisioni 2026-09-30; spostati in `docs/handoff/` da `6dda839` |
| `49cdb82` | 10 | `tests/test_market_data_observations.py` | Evidenza Task 10 (orologio bloccato) |
| `6dda839` | — | 12 file documentali (`AGENTS.md`, `CLAUDE.md`, `PROGRAMMA-OPERATIVO.md`, spec 2026-09-30, `docs/handoff/…`, piano) | registro decisioni 2026-09-30 |
| `88fc20d` | 11 | `transport.py`, `models/__init__.py`, `instrument_service.py`, `tests/test_provider_budget.py`, `PROGRAMMA-OPERATIVO.md` | Evidenza Task 11; `PROGRAMMA-OPERATIVO.md` per AGENTS.md §5 |
| `dbbcc65`, `edbc07e` | 12 | `sentiment_engine.py`, `ml_dataset_service.py`, `market_data_service.py`, `tests/test_provider_budget.py`, `PROGRAMMA-OPERATIVO.md` | Evidenza Task 12 |
| `b1a39e2` | 13 | `news_engine.py`, `tests/test_news_providers.py` (registrati); `backend/app/models/__init__.py` (**non registrato**: esporta `CatalogEodEnqueueResult` e `RefreshRequestOut`); `PROGRAMMA-OPERATIVO.md` | Evidenza Task 13 |
| `62ed48b` | 14 | `tests/test_database.py`, `PROGRAMMA-OPERATIVO.md` | Evidenza Task 14 |
| `30069f0`, `d0d6b4c` | 15, 16 | `PROGRAMMA-OPERATIVO.md` | AGENTS.md §5 |
| `8d95373` | 17 | `frontend/package-lock.json`, `PROGRAMMA-OPERATIVO.md` | Evidenza Task 17 |

I tre file non registrati non introducono difetti: il primo rimuove un secret dalla query string, gli altri due sono un test e un export. Sono riportati qui come deviazioni storiche, senza riscrivere la storia.

## Schema and migrations

Il diff di `backend/app/database.py` aggiunge, in modo solo additivo:

- **20 tabelle**: `instruments`, `instrument_listings`, `instrument_identifiers`, `instrument_identifier_attestations`, `listing_metadata_versions`, `provider_symbols`, `catalog_snapshots`, `catalog_entries`, `catalog_listing_attestations`, `instrument_resolution_cases`, `provider_usage_windows`, `provider_request_log`, `market_observations`, `market_data_rejections`, `market_data_rejection_resolutions`, `market_data_selection_events`, `quality_assessments`, `refresh_requests`, `refresh_runs`, `trade_republic_attestations`;
- **29 indici**, di cui 12 univoci (prefisso `uq_`);
- **26 trigger**, che garantiscono append-only, no delete, sola retirement e supersedes;
- **4 colonne nullable**: `assets.instrument_listing_id`, `price_history.observation_id`, `instruments.quality_reason_code`, `instruments.quality_assessed_at`.

Ogni avvio passa da `prepare_database(reason="pre-migration", backup_existing=True)`.

**Smoke reale di migrazione** (script offline). Il DB è stato creato e popolato col codice della base `5649982`, estratto con `git archive` in una cartella temporanea, poi migrato due volte con il `lifespan` attuale. Eseguito sul codice del Task 17 e ripetuto sul codice finale del Task 18 con output identico. Exit 0:

```text
BASE_SEED=PASS legacy_tables=19 rows=14216
LIFESPAN_RUN_1=PASS
LIFESPAN_RUN_2=PASS
MIGRATION=PASS rows_preserved=14216 new_tables_checked=10 total_tables=39 listings_backfilled=25 assets_linked=25 crypto_fx_isin=0
BACKUPS=PASS count=2 pre_migration=2 first_backup_is_legacy=True integrity=ok
IDEMPOTENT_RERUN=PASS
BACKUP_FAILURE_STOPS_MIGRATION=PASS exit=1 schema_unchanged=True
TMP_REMOVED=True
```

Cosa dimostra:

- righe legacy invariate nelle 10 tabelle controllate;
- `integrity_check` e `foreign_key_check` puliti;
- primo backup ancora con schema legacy;
- rerun idempotente;
- con il backup impossibile (file al posto della cartella `backups`) l'avvio esce 1 e lo schema non cambia;
- nessun ISIN assegnato a crypto o FX.

**Difetto trovato e corretto (C2):** il riavvio dopo `seed_database --reset`, o dopo purge e ri-aggiunta di una crypto curata, falliva in `migrate_db` con `IntegrityError`. Dettagli nella sezione Independent review.

Test di schema e migrazione nella run finale: `tests/test_database.py` = 27 passati.

## Phase 1 compatibility

File di test della Fase 1 nella run finale, tutti verdi:

| File | Test |
|---|---:|
| `tests/test_alert_service.py` | 16 |
| `tests/test_api.py` (include i test API della Fase 2) | 193 |
| `tests/test_config.py` | 4 |
| `tests/test_database.py` | 27 |
| `tests/test_engines.py` | 55 |
| `tests/test_fx_service.py` | 13 |
| `tests/test_import_security.py` | 24 |
| `tests/test_launcher.py` | 3 |
| `tests/test_ml_dataset.py` | 15 |
| `tests/test_portfolio_accounting.py` | 15 |

Stato dei contratti della Fase 1:

- Contratti preservati: `/assets`, `/assets/{symbol}`, `/prices/{symbol}`, `/data/status`, `/data/status/{symbol}`, `/data/refresh/{symbol}`, `/data/refresh-all` (payload `DataRefreshAllOut` invariato, ora bounded e prioritario) e `/data/usage`.
- Valori EUR: campi `*_base` e `base_currency: "EUR"` invariati; cambio congelato al momento dell'operazione invariato.
- Token preview/apply: SHA-256 canonici con `hmac.compare_digest`; 409 senza mutazioni su stale o ambiguità.
- Distruttivi: purge, reset e backup con conferma.
- Caller del read model `assets`/`price_history`: portfolio, allocation, dashboard, analysis, signals, backtest, ML, news.
- Estensioni additive: tutti i nuovi campi dello status sono successivi ai campi legacy (test `test_data_status_compat_keeps_legacy_fields_and_adds_budget_and_coverage`).

Cambi di contratto già registrati nelle evidenze dei task:

- news demo escluse da sentiment, score e ML (Task 12, estensione approvata);
- lock di univocità rilasciato prima dell'I/O di rete (Task 12);
- `/data/refresh-all` limitato a 1..25 con default 10 (Task 13).

Due rotture della Fase 1, trovate dalla review e corrette in questo task:

- **C1:** `/data/status` e `/news/status` andavano in 500 dopo la prima risposta salvata in cache dal trasporto.
- **I4:** il 409 di import e allocation è passato da messaggio stringa a `{"reason_code": …}` e la UI mostrava "API request failed: 409".

## Catalog and identity

- Catalogo Trade Republic: PDF ufficiale, parser `pypdf==6.16.1` fail-closed, snapshot versionati con SHA-256 e `retrieved_at`. Indice univoco sugli snapshot `COMPLETE` per sorgente e SHA. Lo stato TR `CATALOGED` deriva dagli snapshot e non diventa mai `VERIFIED` da solo; le attestazioni `VERIFIED`/`UNAVAILABLE` sono versionate e append-only.
- Risoluzione: OpenFIGI, con key opzionale solo in header e job batch conservativi. Esiti `RESOLVED`/`AMBIGUOUS`/`UNMATCHED`/`REJECTED` con reason code stabili. Nessun candidato scelto per primo, nessun ISIN inventato per crypto o FX, lookup legacy ambiguo → 409.
- `assets` resta l'universo attivo: il catalogo non entra in `assets` finché l'utente non attiva un listing `RESOLVED` (`POST /assets/from-listing/{listing_id}`).
- Test della run finale:
  - `tests/test_instrument_catalog.py` = 14;
  - `tests/test_instrument_resolution.py` = 30;
  - la pagina Universe (catalogo paginato, dettaglio, attivazione) è coperta da `UniversePage.test.tsx`.
- Limite rinviato su decisione dell'utente (I3): gli asset attivi della Fase 1 non possono essere ricollegati a un listing risolto (Residual risks).

## Observation quality gates

- Validazione condivisa: `MISSING_PRICE`, `NON_FINITE`, `NON_POSITIVE`, `CROSSED_QUOTE`, `INVALID_OHLC`, `NEGATIVE_VOLUME`, `CURRENCY_MISMATCH`, `INVALID_TIMESTAMP`, `FUTURE_TIMESTAMP`, `INVALID_TIMEZONE`, `INVALID_DELAY`, `MALFORMED_PAYLOAD`, `PROVIDER_NO_DATA`, `MISSING_VALUE`.
- Comportamento sulle rejection: persistite con hash e scope; un batch tutto invalido non tocca il read model.
- Osservazioni append-only:
  - revisioni con `supersedes`;
  - deduplica per hash logico;
  - provenienza completa: provider, timestamp osservato e di ingestione, timezone, sessione, valuta, ritardo, qualità sorgente ed effettiva;
  - eventi di selezione per fallback e last-good.
- Qualità effettiva `stale` oltre le soglie: quote 5 min, delayed 30 min, EOD 96 h, reference 7 giorni.
- Tier `QUALIFIED`/`OBSERVABLE`/`REFERENCE_ONLY` con evidence hash e reason code. `QUALIFIED` non equivale ad autorizzazione di trading.
- Difetti trovati e corretti in questo task (I2): una sessione in corso poteva diventare una barra EOD (CoinGecko via cache, Stooq).
- Test della run finale: `test_market_data_observations.py` = 61; `test_instrument_quality.py` = 30; `test_eod_providers.py` = 14; `test_coingecko_provider.py` = 22; `test_finnhub_provider.py` = 19.

## Provider matrix and budgets

**Fonti della matrice.** Lo stato osservato viene da uno smoke offline (`GET /data/status` e `GET /news/status`) su DB temporaneo con seed, trasporto HTTP bloccato, in tre scenari:

1. **default**: dati reali disattivati;
2. **opt-in senza key**: `ENABLE_REAL_DATA`, `ENABLE_STOOQ` ed `ENABLE_REAL_NEWS` attivi;
3. **opt-in con key sintetiche** `TEST_*`.

Risultato comune ai tre scenari: tutte le risposte HTTP 200, `secret_or_url_in_response=none` e DB temporaneo rimosso. I limiti vengono dai default di `backend/app/config.py` e dalle policy degli adapter.

Colonne della tabella:

- **Limiti**: minuto / giorno / mese; "–" significa nessun limite in quella finestra.
- **Stato osservato**: scenario 1 → scenario 2 → scenario 3.

| Provider | Capability effettive | Autenticazione | Limiti | Stato osservato | Fallback | Rischio |
|---|---|---|---|---|---|---|
| `stooq` | EOD, solo listing con simbolo `VERIFIED` | nessuna | 5 / 100 / 1000; cache 24 h | `DISABLED OPT_IN_DISABLED` → `AVAILABLE` → `AVAILABLE` | ultimo dato valido o seed, mai un provider alternativo silenzioso | nessuna API/SLA ufficiale; scarica lo storico completo (Minor 16) |
| `finnhub` (quote) | QUOTE, solo MIC USA allowlistati, `delayed` | header `X-Finnhub-Token` | 55 / – / –; cache 60 s | `DISABLED OPT_IN_DISABLED` → `DISABLED MISSING_CREDENTIAL` → `AVAILABLE` | ultimo dato valido marcato stale | quota condivisa con le news (Minor 9) |
| `coingecko` | EOD e QUOTE, solo `COINGECKO_ID` attestato, EUR/USD | keyless oppure header `x-cg-demo-api-key` | keyless 10 / – / 1000; demo 90 / – / 9000 | `DISABLED OPT_IN_DISABLED` → `AVAILABLE` (keyless) → `AVAILABLE` (demo) | stale solo CoinGecko della stessa valuta | keyless best-effort; attribuzione "Powered by CoinGecko API" |
| `alpha_vantage` | nessuna (EOD dichiarata) | key in query → bloccata | – / 20 / – | `DISABLED SECRET_IN_QUERY_POLICY` in tutti gli scenari | — | copertura minore accettata dal piano |
| `yahoo_finance` | nessuna (EOD dichiarata) | — | – / – / – | `DISABLED NOT_PRIMARY_POLICY` in tutti gli scenari | — | nessuno |
| `fred` | REFERENCE, mai prezzo | v1 key in query, v2 solo bulk | – / – / – | `DISABLED MISSING_CREDENTIAL` → `MISSING_CREDENTIAL` → `SECRET_IN_QUERY_POLICY` | — | macro e tassi assenti finché non esiste un percorso per serie compatibile |
| `ecb` | FX verso EUR, `reference` | nessuna | 5 / 50 / 500; cache 6 h | assente da `provider_status` (minore noto, Task 16) | ultimo cambio valido; stale oltre 7 giorni blocca le operazioni | budget FX non visibile nello status |
| catalogo Trade Republic | PDF catalogo | nessuna | 2 / 4 / 31; cache 24 h | refresh manuale `POST /data/catalog/refresh` | resta l'ultimo snapshot `COMPLETE` | formato PDF modificabile senza preavviso |
| `openfigi` | mapping identificativi | opzionale, header `X-OPENFIGI-APIKEY` | 5 / 100 / 1000; cache 168 h | non esposto in `provider_status` | ambiguo → `AMBIGUOUS`/`UNMATCHED`, nessuna euristica | 429 restituito come 502 (Minor 12) |
| `finnhub_news` | NEWS stock/ETF USA | header `X-Finnhub-Token` | 55 / 20 (`NEWS_DAILY_LIMIT`) / –; max 50 articoli | `disabled OPT_IN_DISABLED` → `MISSING_CREDENTIAL` → `enabled` | news locali | quota condivisa con le quote (Minor 9) |
| `alpha_vantage_news` | nessuna | key in query → bloccata | – / 20 / – | `SECRET_IN_QUERY_POLICY` in tutti gli scenari | — | README cita ancora le news Alpha (Minor 14) |
| `yahoo_news` | nessuna | — | – / 0 / – | `NOT_PRIMARY_POLICY` in tutti gli scenari | — | nessuno |
| `mock_news` | demo | — | — | `enabled` | — | escluse da sentiment, score, riepilogo di mercato e ML (Task 12) |

Regole comuni a tutti i provider:

- **Budget:** riservato prima di ogni tentativo fisico, finestre minuto/giorno/mese, cooldown su 429 e `Retry-After` (massimo 60 s), retry limitati (3).
- **Rete:** HTTPS su host allowlistati, redirect rifiutati, letture limitate in dimensione, deduplica in-flight.
- **Cache:** la cache hit non consuma budget.
- **Secret:** mai in URL, query, log, eccezioni, fingerprint o cache.

## EUR FX

- La BCE è la fonte primaria: CSV ECB Data Portal `EXR D.<VAL>.EUR.SP00.A` con `lastNObservations=2` e `If-Modified-Since`/304. Il percorso legacy `refresh_ecb()` legge l'XML giornaliero sotto lo stesso bucket `ecb`.
- `FXService`: diretto, inverso (reciproco) e identità EUR; stale oltre `ECB_FX_MAX_AGE_DAYS=7`; mancante → `FXRateUnavailable`.
- Le operazioni della Fase 1 bloccano su cambio mancante o stale senza mutazioni; i cambi congelati delle operazioni storiche restano intatti.
- FRED resta reference-only; l'alias `BTP10Y` è etichettato `REFERENCE_ONLY/US_10Y_PROXY`.
- **Difetto trovato e corretto** (Minor 13 della review, riclassificato Important): un `TIME_PERIOD` BCE futuro veniva accettato. Sarebbe diventato il cambio più recente usato per ogni conversione EUR, senza mai risultare stale, contro il vincolo globale del piano sui dati futuri. Ora è rifiutato con `ecb:FX:FUTURE_TIMESTAMP`.
- Test della run finale: `test_fx_service.py` = 13; `test_reference_providers.py` = 21.

## Lazy refresh

- `RefreshPlannerService` con priorità POSITION 10, STRATEGY_CANDIDATE 20, WATCHLIST 30, REQUESTED 40, VIEWED 50, CATALOG_EOD 60.
- Deduplica: una sola unità aperta per listing e capability (indice univoco parziale); `force` promosso e mai declassato.
- Batch: 1..25, default 10; claim atomico, nessuna doppia esecuzione.
- Rinvio per budget senza consumo; errori sanitizzati che non bloccano le altre unità.
- Catalogo EOD: keyset senza OFFSET, nessun percorso di default che scansioni tutto il catalogo.
- **Difetto trovato e corretto (I1):** lo skip "fresco" usava la soglia stale EOD di 96 h, quindi una barra EOD veniva aggiornata al più ogni ~4 giorni. Ora il refresh non forzato EOD non viene saltato se l'ultima barra ha più di 24 h. L'etichetta stale e i tier restano invariati, e la cache del trasporto (24 h) evita chiamate doppie.
- Test della run finale: `test_refresh_planner.py` = 18; `test_provider_budget.py` = 60; `test_news_providers.py` = 21.

## Coverage metrics

- `GET /data/coverage` (`DataCoverageService`): una sola transazione di lettura e un solo `measured_at`; nessuna scrittura e nessuna chiamata provider.
- Ogni percentuale ha un denominatore esplicito; a denominatore zero vale `0.0`.
- Ogni entry del catalogo è in un solo bucket; i tier sono contati su instrument distinti.
- Provider: idonei → non mappati/mappati → freschi/stale/mancanti; rejection parser e risoluzione distinte; FX separato; coda `PENDING`/`BUDGET_DEFERRED`.
- Le invarianti di partizione sono verificate prima della risposta: se una fallisce, 500 `COVERAGE_INVARIANT_FAILED` e `coverage_summary` null in `/data/status`.
- Nello smoke della matrice provider `/data/coverage` ha risposto 200 nei tre scenari. Sul DB seed non esiste alcuno snapshot di catalogo, quindi i denominatori del catalogo valgono 0.
- La copertura reale dipende dagli snapshot importati, dalle risoluzioni e dal budget: va letta nel Data Center al momento d'uso. Non è un valore promesso.
- Test della run finale: `test_data_coverage.py` = 12; `DataCenterPage.test.tsx` incluso nei 24 test Vitest.

## Security and backups

- **Secret scan (Step 5).**
  - Pattern, sentinelle e self-test del piano (self-test: 5 valori, 6 match, 5 inattesi, come previsto) su 97 file del diff, escluso `frontend/package-lock.json`.
  - Risultato: 18 match, di cui **3 sintetici** e **15 inattesi**.
  - Classificati riga per riga, i 15 inattesi sono tutti riferimenti a codice, non valori letterali. Esempi: header costruiti da `self.settings.*_api_key`, chiamate `self._*_token(...)`, `preview.confirmation_token`. Risultato: **`unexpected` letterali = 0**, `synthetic` = 3.
  - Lo script letterale del piano esce 1 per questi falsi positivi: deviazione del gate, sezione Verification evidence.
  - Placeholder scan: 0. `git diff --check plan...HEAD`: nessun output.
- **Risposte API.** In tutti e tre gli scenari della matrice provider, nessuna key sintetica e nessun URL compare in `/data/status`, `/data/coverage` o `/news/status`.
- **Rete nei test.** Run completa con plugin pytest che blocca DNS e socket non-loopback (self-test: blocca `example.org`, ammette loopback), eseguita sul codice del Task 17: 679 passati, exit 0, **0 tentativi di rete**. I test aggiunti dal Task 18 usano solo `MockTransport`, fixture e DB temporanei.
- **Backup.** Prima di ogni migrazione, fail-closed: smoke di migrazione in Schema and migrations e test `backup`/`migration`/`rollback` dello smoke B.
- **Trading.** Il trading reale resta disattivato e non esiste alcun adapter attivo; nessuna credenziale inserita.

## Verification evidence

### Baseline, codice del Task 17 (`8d95373`), prima delle correzioni

| Comando | Exit | Risultato |
|---|---:|---|
| `pytest -p no:cacheprovider --junitxml …` (processo distaccato) | 0 (riepilogo senza fallimenti) | 679 passati, 0 falliti, 0 errori, 693,7 s |
| stesso comando con plugin di blocco rete | 0 | 679 passati, `NETWORK_BLOCK attempts=0` |
| `ruff check backend scripts tests` | 0 | `All checks passed!` |
| `compileall -q backend\app backend\scripts scripts` | 0 | nessun output |
| `pip check` | 0 | `No broken requirements found.` |
| `npm --prefix frontend ci` | 0 | 264 pacchetti aggiunti, 265 auditati |
| `npm --prefix frontend run test:run` | 0 | 2 file, 23 test passati |
| `npm --prefix frontend run build` | 0 | 2.235 moduli; JS 895,56 kB (gzip 239,46 kB) |
| `npm --prefix frontend audit --audit-level=high` | 0 | 4 vulnerabilità: 2 low, 2 moderate, 0 high/critical |
| smoke A (12 file fixture dello Step 4) | 0 | 271 passati |
| smoke B (`-k "backup or migration or rollback or stale or missing or token or secret"`) | 0 | 12 passati |

### Gate finale, codice del Task 18 con le correzioni

| Comando | Exit | Risultato |
|---|---:|---|
| `pytest -p no:cacheprovider --junitxml …` | 0 | 687 passati, 0 falliti, 0 errori, 0 saltati, 819,5 s (JUnit XML; 8 test di regressione nuovi rispetto ai 679 della baseline). Run eseguita dopo la correzione I-1, con l'hash del delta di codice verificato identico prima e dopo. La run precedente, senza I-1, aveva dato 687 passati con exit 0 |
| `ruff check backend scripts tests` | 0 | `All checks passed!` |
| `compileall -q backend\app backend\scripts scripts` | 0 | nessun output |
| `pip check` | 0 | `No broken requirements found.` |
| `npm --prefix frontend ci` | 0 | 264 pacchetti aggiunti, 265 auditati |
| `npm --prefix frontend run test:run` | 0 | 2 file, 24 test passati |
| `npm --prefix frontend run build` | 0 | 2.235 moduli; JS 895,82 kB (gzip 239,59 kB); avviso dimensione bundle già presente |
| `npm --prefix frontend audit --audit-level=high` | 0 | 4 vulnerabilità: 2 low, 2 moderate, 0 high/critical |
| smoke A (Step 4) | 0 | 275 passati (4 test di regressione nuovi; ripetuto dopo I-1) |
| smoke B (Step 4) | 0 | 12 passati (ripetuto dopo I-1) |
| smoke di migrazione Fase 1 → Fase 2 sul codice finale | 0 | output identico alla baseline (sezione Schema and migrations) |
| secret scan classificato (Step 5) | 0 | 97 file; `unexpected` letterali 0, synthetic 3; placeholder 0 |
| `git diff --check` | 0 | nessun output |
| scan finale Step 8, con il report incluso | 0 | 98 file, report incluso; match 18: synthetic 3, inattesi 15, tutti riferimenti a codice, `unexpected` letterali 0; placeholder 0; `git diff --check` senza output. Lo script letterale del piano esce 1 sugli stessi 15 falsi positivi |

Vulnerabilità npm residue, tutte invariate rispetto al Task 17:

- moderate: `@vitest/mocker` e `vitest` (GHSA-82fw-gwwq-j7x9);
- low: `@babel/core` (GHSA-4x5r-pxfx-6jf8) e `postcss-selector-parser` (GHSA-w9m9-85wc-3x92).

Sono dipendenze di sviluppo e build. Nessun `npm audit fix` è stato eseguito.

### Deviazioni del Task 18

1. **Secret scan del piano.** Lo script letterale esce 1 su 15 falsi positivi, tutti espressioni di codice. È stato affiancato da uno script con stesso pattern, sentinelle e self-test, che classifica ogni candidato rispetto alla riga sorgente: catena di identificatori Python non tra apici. Fallisce solo se resta un valore letterale.
2. **Conteggio della catena.** 20 commit prima del Task 18 e 21 dopo, invece di 17 e 18 (eccezioni registrate).
3. **Riepilogo pytest.** `pytest.ini` imposta già `addopts = -q`, quindi i comandi `-q` del piano diventano `-qq` e non stampano il riepilogo. I conteggi vengono dal JUnit XML e le suite lunghe girano come processi distaccati.
4. **Smoke B.** Il filtro `-k` del piano seleziona 8 test di `test_database.py`, 4 di `test_portfolio_accounting.py` e **0** di `test_import_security.py`. I token stale di import e allocation sono coperti dalla suite completa (`test_api.py`, `test_import_security.py`).
5. **File fuori elenco del Task 18.**
   - `PROGRAMMA-OPERATIVO.md`, aggiornato nello stesso commit per AGENTS.md §5.
   - `README.md` è nell'elenco autorizzato e documenta il limite I3 su decisione dell'utente.
   - Le correzioni toccano solo path autorizzati: `routes.py`, `coingecko.py`, `ecb.py`, `stooq.py`, `transport.py`, `instrument_service.py`, `market_data_service.py`, `news_engine.py`, `api.ts`, più i test autorizzati.
6. **Push e merge.** Push del branch e merge fast-forward su `main` autorizzati dall'utente (override 2026-09-30), che prevale sul punto 11 del protocollo del piano.

## Independent review

Review cumulativa read-only (`superpowers:requesting-code-review`) su `56499829..8d95373`, con il prompt minimo del piano. Il reviewer ha letto il diff in cinque passaggi e ha riprodotto offline ogni Critical e Important.

- **Esito iniziale:** 2 Critical, 5 Important, 17 Minor. **Ready to merge: No.**
- **Riproduzione:** ogni rilievo accettato è stato riprodotto con un test che falliva per il motivo previsto (RED), poi corretto nei path autorizzati (GREEN).

| Rilievo | Riproduzione (RED) | Correzione | Test di regressione |
|---|---|---|---|
| **C1** `/data/status` e `/news/status` in 500 dopo la prima risposta in cache del trasporto (`expires_at` con "Z" confrontato con un datetime naive) | `TypeError: can't compare offset-naive and offset-aware datetimes` | `parse_stored_utc` e confronto UTC aware in `_cache_stats`/`_cache_status` (`market_data_service.py`) e `_cache_stats` (`news_engine.py`) | `test_api.py::test_status_endpoints_count_cache_rows_written_by_governed_transport` |
| **C2** avvio impossibile dopo `seed_database --reset` o dopo purge e ri-aggiunta di una crypto curata | 2 test: `IntegrityError: CoinGecko curated identity conflicts with another instrument.` | `_backfill_asset` riusa l'instrument che possiede già il `COINGECKO_ID` curato, come il ramo ISIN; completato dopo la re-review (I-1): il fuso `UTC` viene impostato anche sul listing riaggiunto (`instrument_service.py`) | `test_database.py::test_seed_reset_then_restart_reuses_curated_crypto_identity`, `::test_purged_curated_crypto_can_be_added_again_and_restarted` (con controllo `timezone == 'UTC'`) |
| **I1** skip "fresco" EOD con soglia stale di 96 h | barra di lunedì valutata mercoledì sera: `skipped_fresh=1` | refresh EOD dovuto oltre 24 h (`_EOD_REFRESH_DUE_AFTER`, `market_data_service.py`) | `test_refresh_planner.py::test_eod_bar_older_than_a_day_is_refreshed_even_if_not_stale` |
| **I2** sessione in corso salvata come barra EOD | CoinGecko via cache: barra parziale del 17/08 presente; Stooq: riga del giorno di download presente | CoinGecko: un giorno è completo solo se il payload contiene il campione che lo chiude. Trasporto: campo additivo `ProviderResponse.fetched_at`. Stooq: scarta la riga del giorno locale del download, anche da cache | `test_coingecko_provider.py::test_coingecko_cached_market_chart_never_turns_partial_day_into_eod_bar`, `test_eod_providers.py::test_stooq_never_turns_the_download_day_session_into_an_eod_bar` |
| **I3** asset legacy della Fase 1 senza percorso verso dati reali | confermato leggendo il codice: listing legacy senza MIC mai `RESOLVED`; `LEGACY_SYMBOL_CONFLICT` sull'attivazione | **rinviato su decisione dell'utente**: il piano esclude la migrazione legacy dalla Fase 2 e il fix sarebbe una funzionalità nuova. README "Attivazione rapida" aggiornato | — (rischio residuo) |
| **I4** 409 di import e allocation: `detail` da stringa a oggetto, la UI mostrava "API request failed: 409" | test client: messaggio `API request failed: 409` | `parseError` (`api.ts`) traduce `RESOLUTION_CHANGED`/`LISTING_METADATA_CHANGED` nel messaggio guida; `detail` e `apiReasonCode` invariati. `ImportPage.tsx` e `AllocationPlanner.tsx` sono fuori dai path autorizzati e restano invariati | `UniversePage.test.tsx` › "keeps the Phase 1 guidance for stale import and allocation conflicts" |
| **I5** `POST /data/catalog/refresh` `async` con download, retry e parsing PDF sincroni sull'event loop | il servizio girava con un event loop attivo nel thread | validazione async invariata; lavoro bloccante in `run_in_threadpool` (`routes.py`) | `test_api.py::test_catalog_refresh_runs_blocking_work_outside_the_event_loop` |
| **Minor 13 → Important** `TIME_PERIOD` BCE futuro accettato | `DID NOT RAISE` | `_reject_future` → `ecb:FX:FUTURE_TIMESTAMP` su CSV e XML (`ecb.py`) | `test_reference_providers.py::test_ecb_future_time_period_never_becomes_the_latest_rate` |

**Minor valutati e non riclassificati.**

- Minor 1 (commit parziale dopo un'eccezione nel planner): resta Minor. Il `DELETE signals` è seguito subito dall'`INSERT`; lo scenario realistico conserva dati validi e marca l'unità FAILED.
- Gli altri Minor restano rischi documentati (Residual risks), come da istruzione dell'utente.

**Minori già noti dalle evidenze dei Task 13–17.**

- Confermati Minor dal reviewer.
- Il minore del Task 14 "listing legacy `NEVER_SEEN`" è stato ricondotto a I3.

**Re-review del delta di correzione** (sola lettura). Il reviewer ha rieseguito gli 8 test di regressione:

- sul checkout: 8 passati;
- su un export di `HEAD` con i soli nuovi test: 8 falliti, ciascuno per il motivo atteso.

Altri controlli: suite mirate 242 + 234 passati, `ruff` verde, `tsc --noEmit` exit 0.

| Rilievo | Esito |
|---|---|
| C1, I1, I2, I4, I5, Minor 13 | VERIFIED |
| C2 | PARTIAL |
| I3 | non riaperto; testo README corretto |
| Scope | solo path autorizzati |

Rilievo nuovo **I-1 (Important)**. Con il riuso dell'instrument, `backfill_curated_crypto_ids` usciva con `continue` (attestazione già presente) prima di impostare `timezone = 'UTC'` sul listing riaggiunto, quindi le barre CoinGecko sarebbero state rifiutate con `INVALID_TIMEZONE`.

- RED: i due test C2 estesi fallivano con `assert None == 'UTC'`.
- Correzione: l'`UPDATE` idempotente del fuso viene eseguito prima del controllo sull'attestazione.
- GREEN: 91 passati su `test_database.py`, `test_coingecko_provider.py`, `test_data_coverage.py` e `test_instrument_quality.py`.
- Gli script di riproduzione del reviewer ora mostrano `ValidatedObservation` sul listing riaggiunto e `timezone='UTC'` per le 5 crypto dopo il reset del seed.

Minor della re-review, documentati nei rischi residui: M-1, M-2, M-3, M-4. Per M-3 l'helper di test che ignorava il simbolo è stato corretto insieme a I-1.

**Re-review dell'incremento I-1:** I-1 **VERIFIED** con verifiche aggiuntive:

- ordine pre-fix ricreato in memoria: entrambi i test falliscono con `assert None == 'UTC'`;
- conteggio `inserted` e idempotenza invariati;
- fuso già impostato conservato;
- simboli non univoci esclusi;
- `pytest tests/test_database.py tests/test_coingecko_provider.py`: 49 passati.

Nessun nuovo Critical o Important. **Ready to commit: Yes.** Resta solo un refuso cosmetico in un commento.

## Residual risks

Ogni rischio è riportato con impatto e mitigazione corrente.

| Rischio | Impatto | Mitigazione corrente |
|---|---|---|
| **I3** asset attivati prima della Fase 2 (seed demo inclusi) non collegabili a un listing risolto | azioni ed ETF legacy restano su dati seed anche con dati reali attivi; la priorità POSITION non porta dati reali per quelle posizioni | limite dichiarato nel README; dati reali disponibili per i listing attivati dal catalogo e per le 5 crypto curate; ricollegamento esplicito (preview/apply con token) da pianificare in un sottoprogetto successivo |
| Catalogo Trade Republic: PDF, formato o universo possono cambiare | snapshot rifiutato o copertura ridotta | parser fail-closed, SHA-256 e storico versioni; la presenza nel catalogo non garantisce la negoziabilità corrente |
| OpenFIGI: candidati multipli o limiti modificati | copertura di risoluzione inferiore | nessuna euristica; esiti `AMBIGUOUS`/`UNMATCHED` visibili nel Data Center |
| Stooq senza API/SLA ufficiale | refresh EOD può fallire | opt-in, solo EOD, fail-soft; l'ultimo dato valido resta |
| Free tier e diritti d'uso (CoinGecko, Finnhub, FRED, Alpha) possono cambiare | budget o disponibilità diversi | limiti locali conservativi, 429 e `Retry-After` governano il cooldown; riverifica sulle fonti ufficiali prima di una release; FRED e Alpha restano disabilitati per policy |
| Finnhub free senza storico candle universale né realtime internazionale | EOD e quote restano capability distinte | quote classificate `delayed`, mai realtime |
| Soglie di freschezza EOD su weekend, festività e fusi | etichetta `eod` fino a 96 h | soglie configurabili; dopo la correzione I1 il refresh EOD è dovuto oltre 24 h |
| Riga Stooq del giorno di download scartata (correzione I2); con la cache EOD di 24 h (M-1 della re-review) | la chiusura del giorno arriva al primo download del giorno locale successivo: dopo un weekend l'ultima barra può risultare temporaneamente `stale` fino alla scadenza della cache; per EOD `SKIPPED_FRESH` non scatta più e ogni batch rilegge la storia Stooq dalla cache, deduplicata per hash | scelta conservativa, una seduta forse aperta non diventa mai `eod`; un refresh forzato risolve; al massimo 1 chiamata per listing ogni 24 h; da valutare: scadenza della cache EOD alla mezzanotte locale del listing |
| M-2: listing crypto orfani dopo purge o reset del seed | restano ACTIVE con il mapping CoinGecko dell'instrument; `/data/catalog/eod/enqueue` può aggiornarli e consumare budget | stesso schema già esistente per i listing con ISIN; batch limitati a 25 e budget governato |
| M-3: dettagli nei test del Task 18 (il test frontend usa un path di allocazione semplificato e non copre `LISTING_METADATA_CHANGED`; la mappa dei reason code è un oggetto semplice) | copertura di test più stretta del comportamento | `fetch` mockato e mappa limitata a codici noti del backend; helper di test del simbolo corretto |
| M-4: `refresh_ecb` legacy usa l'orologio reale; con `_reject_future` una fixture XML con data 2026-09-30 richiede un sistema con data successiva | un orologio di sistema anteriore farebbe fallire il test di copertura | date delle fixture nel passato rispetto a oggi; nessun impatto in produzione |
| Unique legacy `(symbol, asset_type)` su `assets` | collisioni tra listing omonimi bloccate con 409 | migrazione esplicita fuori dalla Fase 2 (vedi I3) |
| "Copertura massima" | non è una percentuale garantita e può diminuire | metrica misurata e visibile nel Data Center |
| Minor 1: `_run_claimed` non fa rollback dopo un'eccezione; `_write_transaction` committa il lavoro parziale | in caso raro un'unità FAILED lascia scritture parziali (dati validi già ingeriti) | il `DELETE`/`INSERT` dei segnali è contiguo; al refresh successivo i segnali vengono ricalcolati |
| Minor 2: `ingest_batch` usa `BEGIN` deferred | `SQLITE_BUSY` sotto contesa | unità indipendenti; l'errore è sanitizzato e non blocca le altre |
| Minor 3: correzioni A→B→A sulla stessa barra | A non viene ripromossa; il read model resta su B | revisioni conservate append-only e visibili |
| Minor 4: priorità stretta con `refresh_watchlist` che riaccoda posizioni, candidati e watchlist | con almeno `limit` asset attivi, VIEWED e CATALOG_EOD possono non essere mai eseguiti | batch manuali dedicati (`/data/refresh/viewed`, `/data/catalog/eod/enqueue`) |
| Minor 5: GET che prendono il lock di scrittura (`/prices`, backfill) | latenza sotto contesa | transazioni brevi; nessuna I/O di rete sotto lock |
| Minor 6: una coppia legacy ambigua blocca `/data/refresh-all` e `/ml/predict-all` | refresh globale in 409 | 409 esplicito; refresh del singolo simbolo ancora possibile |
| Minor 7: ISIN dedotti dal ticker nel seed attestati dal backfill | identità seed meno affidabile | riguarda solo il seed demo, mai mescolato con dati reali nei calcoli |
| Minor 8: attivazione di un BOND dal catalogo con `tax_category='standard'` | stima fiscale 26% invece di 12,5% per titoli di Stato | stima prudenziale (più alta); correzione della categoria da pianificare |
| Minor 9: quote e news Finnhub con due bucket da 55/min sulla stessa key | fino a 110/min contro 60/min dichiarati upstream | 429 e `Retry-After` attivano il cooldown; batch limitati a 25 |
| Minor 10: due `POST /data/refresh/{symbol}` concorrenti sullo stesso listing | il secondo riceve 404 | ripetere la richiesta |
| Minor 11: unità RUNNING mai recuperate dopo un crash | il listing resta bloccato in coda | da gestire con il runtime sempre acceso (SP6) |
| Minor 12: 429 OpenFIGI dopo i retry restituito come 502 | messaggio meno preciso | cooldown applicato comunque |
| Minor 14: README "Attivazione rapida" cita ancora le news Alpha Vantage, ora disabilitate | documentazione imprecisa | lo stato reale è visibile in `/news/status` (`SECRET_IN_QUERY_POLICY`) |
| Minor 15: nessuna guardia di rete globale nei test; `cache_clear` fuori da `finally` in un test | un test futuro potrebbe chiamare la rete | in questa verifica la suite completa con rete bloccata ha registrato 0 tentativi |
| Minor 16: Stooq scarica sempre lo storico completo | più righe validate per refresh | cache 24 h e budget 100/giorno |
| Minor 17: ~7 `httpx.Client` per `ProviderRegistry` mai chiusi | risorse e latenza (~30 ms per istanza) | nessun impatto funzionale osservato |
| Task 13: con budget giornaliero o mensile esaurito il rinvio è di 1 minuto | unità riproposte a ogni batch, senza consumo | nessun consumo di budget |
| Task 14: arricchimento per riga ~250 ms per pagina da 100 | latenza del catalogo | pagina default 50; SQL ~35 ms su 20.000 strumenti |
| Task 15: numero di pagina incoerente se il totale scende sotto l'offset; stato del tab catalogo azzerato | UX | il pulsante "Precedente" resta disponibile |
| Task 16: età massima di `VERIFIED` TR non applicata; ECB assente da `provider_status`; copertura misurata anche in `/data/status`; errore SQL della copertura non fail-soft | stato TR potenzialmente datato; budget FX non visibile; doppia misura | invarianti fail-soft; `rate_to_eur` e freschezza FX visibili nella copertura |
| Task 17: `rate_to_eur` in notazione scientifica mostrato `—`; ricarica completa dopo il batch; esempio README `limit=50` oltre il massimo 25 | casi limite di presentazione e documentazione | nessuna valuta BCE attuale sotto 1e-6; il backend rifiuta `limit>25` |
| npm: 2 moderate e 2 low in dipendenze di sviluppo e build | nessuna in runtime di produzione | nessuna high/critical; nessun `--force` |
