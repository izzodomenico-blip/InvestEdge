# InvestEdge — programma operativo

Fonte unica dello **stato di avanzamento**. Vale per Claude Code e Codex. Regole di lavoro in `AGENTS.md`; decisioni e confini in `docs/superpowers/specs/2026-09-30-investedge-profit-engine-program-design.md`.

Ultimo aggiornamento: 2026-10-02.

## Prossimo passo

**SP1 Task 1 — Fixture seed condivisa e guardia di rete globale.**

- Esecuzione: nuova chat con contesto pulito.
- Branch `investedge/sp1-task-1` da `origin/investedge/sp1-task-0` (verifica della base con il protocollo del piano).
- Ingressi: spec `docs/superpowers/specs/2026-10-02-investedge-sp1-truth-lab-design.md`, piano `docs/superpowers/plans/2026-10-02-investedge-sp1-truth-lab.md` (Task 1), registro SP1 qui sotto.
- Il Task 1 registra nel registro SP1 lo SHA del Task 0.

## Legenda

| Stato | Significato |
|---|---|
| NON INIZIATO | Nessun lavoro. Può partire solo se le dipendenze sono FATTE. |
| IN CORSO | Branch remoto del task pubblicato: il task appartiene all'owner indicato. |
| BLOCCATO | Serve una decisione dell'utente o una dipendenza esterna. Motivo in *Note di ripresa*. |
| FATTO | Test e gate del task verdi, commit pubblicato. |
| VERIFICATO | FATTO + gate di fine SP superato + merge fast-forward su `main`. |

Lo SHA di un task viene scritto dal commit successivo: un commit non può contenere il proprio SHA. Fino ad allora vale il branch remoto indicato.

## Quadro dei sottoprogetti

Ordine: SP0 → SP2a → SP1 → SP2b → SP3 → SP4 → SP5 → SP6 → SP7 → SP8 → SP9.

| SP | Titolo | Stato | Spec | Piano | Branch finale | In `main` |
|---|---|---|---|---|---|---|
| SP0 | Fondamenta (Fase 1) | VERIFICATO | spec 2026-08-16 | `2026-08-16-investedge-phase-1-foundations.md` | `codex/investedge-phase-1-task-11` | sì, `2e74518` (2026-09-30) |
| SP2a | Strumenti e dati di mercato (Fase 2) | VERIFICATO | spec 2026-08-16 | `2026-08-16-investedge-phase-2-instruments-and-market-data.md` | `codex/investedge-phase-2-task-18` | sì, `6acd3c4` (2026-10-01) |
| SP1 | Laboratorio di verità | IN CORSO | `2026-10-02-investedge-sp1-truth-lab-design.md` | `2026-10-02-investedge-sp1-truth-lab.md` | — | no |
| SP2b | Dati per l'alpha | NON INIZIATO | da scrivere | da scrivere | — | no |
| SP3 | Segnali v2 | NON INIZIATO | da scrivere | da scrivere | — | no |
| SP4 | ML v2 | NON INIZIATO | da scrivere | da scrivere | — | no |
| SP5 | Radar e società appena quotate | NON INIZIATO | da scrivere | da scrivere | — | no |
| SP6 | Esecuzione paper e reale | NON INIZIATO | da scrivere | da scrivere | — | no |
| SP7 | Telegram bidirezionale | NON INIZIATO | da scrivere | da scrivere | — | no |
| SP8 | Redesign UI | NON INIZIATO | spec 2026-08-16 §7–§8 + da scrivere | da scrivere | — | no |
| SP9 | Mobile | NON INIZIATO | spec 2026-08-16 §9 + da scrivere | da scrivere | — | no |

Ogni SP senza spec parte con brainstorming → spec → piano, approvati dall'utente, prima di scrivere codice.

## Registro SP0 — Fase 1 (fondamenta)

Report: `docs/reports/2026-08-16-phase-1-verification.md` (280 test verdi, review finale "ready to merge").

| Task | Titolo | Stato | Commit | Data | Owner |
|---|---|---|---|---|---|
| 1 | Runtime locale e toolchain frontend | FATTO | `2d423b2` | 2026-08-16 | Codex |
| 2 | Migrazioni e backup di avvio | FATTO | `637b5dd` | 2026-08-16 | Codex |
| 3 | Cancellazione asset protetta | FATTO | `6f6afc6` | 2026-08-16 | Codex |
| 4 | Cambi EUR tracciabili (BCE) | FATTO | `5f92220` | 2026-08-16 | Codex |
| 5 | Contabilità multivaluta | FATTO | `c77225e` | 2026-08-16 | Codex |
| 6 | Import sicuro e capitale preservato | FATTO | `b488675` | 2026-08-16 | Codex |
| 7 | Short negli scenari e nel fisco | FATTO | `2dbd14a` | 2026-08-16 | Codex |
| 8 | Leakage temporale ML | FATTO | `734815d` | 2026-08-16 | Codex |
| 9 | Segreti Telegram e job schedulati | FATTO | `4ec9a04` | 2026-08-16 | Codex |
| 10 | Azioni distruttive esplicite in UI | FATTO | `12d080e` | 2026-08-16 | Codex |
| 11 | Audit finale e report Fase 1 | FATTO | `2e74518` | 2026-08-16 | Codex |

Riverifica 2026-09-30 (Claude, worktree isolato su `2e74518`): `pytest` = 280 test, 279 verdi e 1 fallito solo per il layout del venv (`test_launcher` cerca `backend/.venv` nella radice del worktree; con il venv collegato i 3 test launcher passano); `ruff check backend scripts tests` verde. Unito in `main` con fast-forward a `2e74518`.

## Registro SP2a — Fase 2 (strumenti e dati di mercato)

Piano: commit `5649982`. Branch per task: `codex/investedge-phase-2-task-N`, ciascuno dal precedente.

| Task | Titolo | Stato | Commit | Data | Owner |
|---|---|---|---|---|---|
| 1 | Instrument master, listing e identificativi | FATTO | `d75d8b0` | 2026-08-16 | Codex |
| 2 | Trasporto sicuro e budget provider | FATTO | `ad3e118` | 2026-08-17 | Codex |
| 3 | Catalogo ufficiale Trade Republic versionato | FATTO | `d39a5dd` | 2026-08-17 | Codex |
| 4 | Risoluzione identificativi (OpenFIGI) | FATTO | `2ca7f5f` | 2026-08-17 | Codex |
| 5 | Resolution congelata nei token import/allocation | FATTO | `127d899` | 2026-08-17 | Codex |
| 6 | Osservazioni di mercato con provenienza | FATTO | `415e870` | 2026-08-17 | Codex |
| 7 | Tier Qualified / Observable / Reference only | FATTO | `d5599a1` | 2026-08-17 | Codex |
| 8 | EOD gratuito e fallback (Stooq) | FATTO | `98de55a` | 2026-08-17 | Codex |
| 9 | Quote USA (Finnhub) | FATTO | `9503e70` | 2026-08-17 | Codex |
| 10 | Prezzi crypto con identità CoinGecko | FATTO | `54b3faf` checkpoint + `49cdb82` | 2026-09-30 | Codex → Claude |
| 11 | FX BCE verso EUR e fallback FRED | FATTO | `88fc20d` | 2026-09-30 | Claude |
| 12 | Provider e fallback news reali (+ isolamento news demo) | FATTO | `dbbcc65` checkpoint + `edbc07e` | 2026-10-01 | Claude |
| 13 | Refresh lazy, prioritari, deduplicati | FATTO | `b1a39e2` | 2026-10-01 | Claude |
| 14 | API catalogo e conferme versionate | FATTO | `62ed48b` | 2026-10-01 | Claude |
| 15 | Catalogo paginato nella pagina Universe | FATTO | `30069f0` | 2026-10-01 | Claude |
| 16 | API e metriche di copertura dati | FATTO | `d0d6b4c` | 2026-10-01 | Claude |
| 17 | Copertura, qualità e budget nel Data Center | FATTO | `8d95373` | 2026-10-01 | Claude |
| 18 | Audit cumulativo e report Fase 2 | FATTO | `6acd3c4` | 2026-10-01 | Claude |

Evidenza Task 10 (2026-09-30, Claude):

- review indipendente sui sei rischi dell'handoff Codex: nessun Critical; 1 Important corretto con TDD (barre giornaliere CoinGecko datate un giorno avanti e giorno UTC in corso salvato come EOD);
- 2 test legati al calendario corretti bloccando l'orologio (`tests/test_market_data_observations.py`, fuori dall'elenco file del Task 10: deviazione solo di test);
- gate `pytest tests\test_coingecko_provider.py tests\test_provider_budget.py tests\test_market_data_observations.py tests\test_api.py` = 295 passati; Ruff verde; `git diff --check` verde;
- commit sopra il Task 9: 2 (checkpoint + completamento), come da deroga approvata.

Evidenza Task 11 (2026-09-30, Claude):

- nuovo `EcbFxProvider` (ECB Data Portal CSV, `If-Modified-Since`/304, budget 5/min · 50/giorno · 500/mese, bucket `ecb`); `FXService.refresh_currency()` e route `POST /data/fx/refresh`; `refresh_ecb()` legacy passa dal trasporto governato con firma e conteggio invariati;
- `FredReferenceProvider` fail-closed (`MISSING_CREDENTIAL`/`SECRET_IN_QUERY_POLICY`, nota `BULK_ONLY_POLICY`), nessuna chiamata di rete; osservazioni FRED `REFERENCE`/QUOTE mai proiettate in `price_history`; alias `BTP10Y` = `REFERENCE_ONLY/US_10Y_PROXY`;
- deviazioni: `backend/app/data_providers/transport.py` e `tests/test_provider_budget.py` modificati per gestire il 304 come `NOT_MODIFIED` (fuori dall'elenco file del task); la route FX rispetta `ENABLE_REAL_DATA=false` (409, nessuna chiamata); `backend/app/models/__init__.py` esporta `FxRefreshResult`; nuova impostazione `ECB_FX_CACHE_TTL_HOURS`; autofix Ruff UP012 in `instrument_service.py` (violazione lasciata dal checkpoint Task 10, avrebbe fatto fallire la CI);
- gate: suite completa `pytest` = 595 passati; `ruff check backend scripts tests` verde; `git diff --check` verde.

Evidenza Task 12 (2026-10-01, Claude):

- Finnhub unico provider news live: key solo header, simbolo `NEWS/VERIFIED` del listing, venue USA supportata, budget 55/min + limiti giornaliero/mensile configurati, massimo 50 articoli, scartati orari invalidi/futuri, URL solo http(s) pubblici; Alpha (`SECRET_IN_QUERY_POLICY`) e Yahoo (`NOT_PRIMARY_POLICY`) news fail-closed senza rete; batch `refresh-all` default 10, massimo 25, solo asset attivi;
- estensione approvata: news demo (`mock_news`) visibili ma escluse da sentiment, `news_score`/`final_score`, riepilogo di mercato e feature ML; la data delle news demo non viene rinnovata (in demo il sentiment conta 0 news: contratto aggiornato di proposito);
- **correzione Critical trasversale:** le route di refresh tenevano `BEGIN IMMEDIATE` durante le chiamate provider e il budget (Task 2) rifiuta transazioni del chiamante: ogni refresh reale via API (`/data/refresh*`, `/news/refresh*`) cadeva in `TRANSPORT_FAILED`. Ora il controllo di univocita resta sotto lock e il lock viene rilasciato prima dell'I/O di rete (`_ensure_unambiguous_before_provider_calls`); `_asset` sceglie sempre l'asset originale (`ORDER BY id`). Il test Task 5 sul lock e stato aggiornato al nuovo contratto;
- deviazioni di file: `sentiment_engine.py`, `ml_dataset_service.py` (estensione demo), `market_data_service.py` (ordinamento `_asset`), `tests/test_provider_budget.py` (test di inoltro `force` spostato da Yahoo a Finnhub); `tests/test_alert_service.py` non richiedeva modifiche;
- gate: suite completa `pytest` = 618 passati; `ruff check backend scripts tests` verde; `git diff --check` verde; commit sopra il Task 11: 2 (checkpoint per limite di utilizzo + completamento).

Evidenza Task 13 (2026-10-01, Claude):

- `RefreshPlannerService` con tabelle `refresh_requests`/`refresh_runs`: priorita POSITION 10 → CATALOG_EOD 60, una sola unita aperta per listing/capability (indice univoco parziale), `force` promosso e mai declassato, batch 1..25 (default `REFRESH_BATCH_DEFAULT_LIMIT=10`), skip dei dati freschi, rinvio senza consumo di budget su cooldown, errori sanitizzati che non bloccano le altre unita, selezione atomica (nessuna doppia esecuzione fra batch concorrenti);
- `/data/refresh-all` sempre limitato e prioritario con payload `DataRefreshAllOut` invariato; `/data/refresh/{symbol}` accoda `REQUESTED` ed esegue; nuovi `POST /data/refresh/viewed/{listing_id}` e `POST /data/catalog/eod/enqueue` (keyset, mai OFFSET, mai scansioni complete); script `activate_real_data.py` con `--limit` obbligatorio, anteprima di default, nessuna pausa fissa;
- **correzione Critical:** `ingest_batch` lascia la transazione al chiamante e il budget rifiutava le chiamate successive nello stesso batch (`TRANSPORT_FAILED` dalla seconda unita): ora planner e batch news confermano ogni unita; regressioni in `tests/test_refresh_planner.py` e `tests/test_news_providers.py`;
- deviazioni: `news_engine.py` e `tests/test_news_providers.py` (stessa correzione sul batch news del Task 12); `market_data_service.py` rifattorizzato (`select_provider`, `refresh_asset_row`, `_asset_for_listing`) con firma pubblica invariata; il controllo di ambiguita di `/data/refresh-all` copre tutti gli asset attivi; test RACELOCK aggiornato a `refresh_asset_row`; il planner rifiuta transazioni del chiamante in sospeso (come il budget);
- minore aperto: con budget giornaliero/mensile esaurito il rinvio e di 1 minuto (nessun consumo, ma l'unita viene riproposta a ogni batch); da affinare rinviando all'apertura della finestra successiva;
- gate: suite completa `pytest` = 641 passati; `ruff check backend scripts tests` verde; `git diff --check` verde.

Evidenza Task 14 (2026-10-01, Claude):

- `GET /instruments` (ricerca case-insensitive su nome/ticker/ISIN/FIGI, filtri in allowlist parametrica, LIKE con escape, limit 1..100, offset >= 0, ordine `canonical_name/instrument_id/listing_id`, count e pagina nella stessa transazione di lettura, `catalog_snapshot_id` = ultimo snapshot COMPLETE) e `GET /instruments/{id}` (identificativi attestati con fonti e prima/ultima osservazione, tutti i listing con stato di risoluzione, nessun payload raw);
- `POST /assets/from-listing/{listing_id}`: attivazione esplicita di un listing RESOLVED con metadata verificati e `assets.instrument_listing_id`, idempotente, 409 per listing non risolto, identita ambigua, tipo non supportato o simbolo gia attivo;
- conferme provider symbol (`stooq` EOD, `finnhub` QUOTE/NEWS su venue USA, `coingecko` crypto) e Trade Republic (`VERIFIED`/`UNAVAILABLE`) con preview/apply: token SHA-256 canonico confrontato con `hmac.compare_digest`, `BEGIN IMMEDIATE`, retire -> insert -> projection, versioni con `supersedes`, idempotenza, rollback completo; nuova tabella append-only `trade_republic_attestations` con indice parziale ACTIVE e trigger di sola retirement/no delete/no replace; nessuna chiamata di rete (test con trasporto HTTP bloccato);
- deviazioni: trigger `trg_provider_symbols_supersedes_insert/update` estesi alla versione ritirata dello stesso listing (prima ammettevano solo lo stesso simbolo) con migrazione drop/ricrea in `migrate_db`; nuovo test di migrazione in `tests/test_database.py` (fuori elenco file, solo test); attivazione ripetuta risponde 200 (201 solo alla creazione); l'attivazione blocca qualsiasi asset con lo stesso simbolo, non solo `(symbol, asset_type)`, per non creare ambiguita legacy; righe catalogo senza listing con stato TR `CATALOGED` derivato dagli snapshot COMPLETE; listing non risolto con `resolution_status` dell'ultimo case dello strumento oppure `UNMATCHED`; `observed_at` futuro rifiutato (`FUTURE_OBSERVED_AT`); `verified_at` del provider symbol = `observed_at`;
- review: corretto un Important di prestazioni (filtro ISIN/FIGI da `EXISTS` correlato a sottoquery non correlata, piano `LIST SUBQUERY`); su 20.000 strumenti sintetici la SQL impiega ~35 ms, la pagina da 100 ~250 ms per l'arricchimento per riga (minore aperto);
- minore aperto: un listing legacy `NEVER_SEEN` di uno strumento presente nel catalogo resta `NEVER_SEEN` (lo stato TR e per listing): da rendere chiaro nella UI del Task 15;
- gate: suite completa `pytest` = 665 passati; `ruff check backend scripts tests` verde; `git diff --check` verde; frontend non toccato.

Evidenza Task 15 (2026-10-01, Claude):

- test runner frontend: Vitest 4.1.10, Testing Library React 16.3.2, jest-dom 7.0.1, jsdom 30.0.1 (`@testing-library/dom` installato come peer); `npm run test:run`; lockfile: 85 pacchetti aggiunti, nessuna versione esistente cambiata o rimossa;
- pagina Universe con tab **Attivi** (contenuto, form e purge protetto invariati) e **Catalogo**: ricerca debounced 300 ms, filtri classe/tier/stato TR/valuta/MIC (valuta e MIC inviati solo come codici completi), `limit=50` con offset del backend e pagine sostituite (mai concatenate), richiesta precedente abortita, stati loading/vuoto/errore; `DataQualityBadge` (tier e freschezza effettiva) e `InstrumentIdentity` (identificativo, venue, valuta, stato TR come fonte della conferma, non negoziabilita); dettaglio con identificativi e listing, `markListingViewed` una sola volta per listing e solo all'apertura; attivazione esplicita solo per listing `RESOLVED` con identita non ambigua, 409 spiegati per `reason_code`; nessun fetch del catalogo finche il tab non viene aperto;
- client `api.ts`: tipi omologhi agli schemi Python (nullability verificata campo per campo), `getInstruments`/`getInstrument`/`activateListing`/`markListingViewed` con `URLSearchParams` e `encodeURIComponent`, `ApiError` con `detail`, `apiReasonCode`, `AbortSignal` su `apiGet`;
- deviazioni: il messaggio DEV di errore di rete ora usa metodo e pathname per tutte le richieste (prima includeva URL e query completi); `setup.ts` registra anche la pulizia di Testing Library (necessaria senza `globals`); test del client API dentro `UniversePage.test.tsx` (nessun file extra); sottotitolo della pagina aggiornato; review a11y: testo visibile dei pulsanti incluso nel nome accessibile; esecuzione nella stessa chat del Task 14 su richiesta esplicita dell'utente;
- note: npm 11 segnala lo script `postinstall` di esbuild non approvato (non approvato di proposito, la build funziona); l'avviso Vite sulla dimensione del bundle era gia presente;
- minori aperti: se il totale scende sotto l'offset corrente la pagina vuota mostra un numero di pagina incoerente (resta il pulsante "Precedente"); lo stato del tab catalogo si azzera cambiando tab;
- gate: `npm run test:run -- UniversePage.test.tsx` = 9 passati; `npm run build` exit 0; backend invariato: suite `pytest` = 665 passati; `git diff --check` verde.

Evidenza Task 16 (2026-10-01, Claude):

- `GET /data/coverage` (`DataCoverageService`): stessa connessione, stessa transazione di lettura e stesso `measured_at`; solo l'ultimo snapshot TR `COMPLETE` e l'ultimo resolution case per entry (`ROW_NUMBER` su id), ogni entry `ACCEPTED` in un solo bucket (`UNPROCESSED` senza case); percentuali con denominatore esplicito e `0.0` a denominatore zero; tier su instrument distinti; TR con bucket `UNRESOLVED_IDENTITY`; gruppi per asset class e MIC (`UNRESOLVED`); provider eligible → unmapped/mapped → fresh/stale/missing con freschezza alla misura, quality e delay bucket sull'ultima revisione, rejection non risolte, attribution; FX separato da `fx_rates` (direct/inverse, `ECB_FX_MAX_AGE_DAYS`, reciprocita di `FXService`, `rate_to_eur` stringa decimale JSON o `null`, EUR identita fuori denominatore, cambi congelati intatti); coda `PENDING`/`BUDGET_DEFERRED`; invarianti di partizione verificate prima della risposta (violazione → 500 `COVERAGE_INVARIANT_FAILED`); nessuna chiamata provider (trasporto HTTP bloccato nei test) e nessuna scrittura (`total_changes` invariato);
- `/data/status` additivo: `coverage_summary` nullable (null se un'invariante fallisce) e, per provider, `capabilities`, `budget_windows` minuto/giorno/mese con `limit`/`used`/`remaining`/`reset_at`, `cooldown_until`, `availability_state`/`availability_reason`, `last_outcome`/`last_outcome_at`; `daily_limit` e `calls_today` invariati e coerenti con la finestra giornaliera; nessuna key, URL, endpoint o fingerprint;
- scelte interpretative registrate: `rejection_reasons` con prefisso `PARSE:`/`RESOLUTION:`; `provider_coverage` sulle sole coppie mappabili su listing (NEWS escluso: non produce observation); listing risolti = metadata VERIFIED + case `RESOLVED` e `ACTIVE` (i listing legacy degli asset seed non entrano nei denominatori provider); bucket di ritardo dal `delay_seconds` all'ingestione; nuovo schema `DataCoverageSummaryOut`; `get_global_status(now=None)` opzionale per test deterministici; riuso di helper privati esistenti (`_window_values`, `_policy_limits`, `_PROVIDER_INSTRUMENT_TYPES`, `ProviderBudgetManager._active_cooldown`/`_minimum_limit`, `provider._budget_policy`) senza toccare file fuori elenco; nella fixture la richiesta `BUDGET_DEFERRED` e impostata direttamente in tabella;
- prestazioni (DB temporaneo sintetico, trasporto HTTP bloccato): 20.000 entry, 10.000 listing risolti, 500 mappati × 30 barre → `measure` ~170 ms; piani con `idx_catalog_entries_snapshot_row`, `idx_instrument_resolution_cases_entry_latest`, `idx_market_observations_latest` e sottoquery non correlate (`LIST SUBQUERY`), nessuna sottoquery correlata per riga del catalogo;
- minori aperti: lo stato TR `VERIFIED` viene dalla projection del listing senza applicare `TRADE_REPUBLIC_VERIFIED_MAX_AGE_DAYS`; ECB non compare in `provider_status` (budget FX non visibile nello status); `/data/status` esegue anche la misura di copertura; un errore SQL inatteso della copertura non e fail-soft (lo sono solo le invarianti);
- gate: `pytest tests\test_data_coverage.py` = 12 passati; `pytest tests\test_api.py -k "coverage or data_status"` = 4 passati; suite completa `pytest -p no:cacheprovider` = 679 passati (0 falliti, JUnit XML); `ruff check backend scripts tests` verde; `git diff --check` verde; frontend non toccato.

Evidenza Task 17 (2026-10-01, Claude):

- client `api.ts`: tipi omologhi a `DataCoverageOut`, `DataCoverageSummaryOut`, `CoverageCount`, `ProviderCoverageOut`, `FxCoverageOut` (`rate_to_eur: string | null`), `ProviderBudgetWindowOut` e alle estensioni di `DataStatusOut`/`DataProviderStatusOut` (campi e nullability confrontati automaticamente con i modelli Pydantic: 10 coppie coerenti); `getDataCoverage()` (una GET), `refreshAll(limit)` (intero 1..25 validato nel client, `URLSearchParams`, una POST senza body, `DataRefreshAllOut` invariato), `formatRateToEur` (solo stringa decimale completa e finita, altrimenti `—`, conversione solo per la presentazione);
- Data Center: copertura catalogo (parsing/risoluzione con denominatori, tier e stato Trade Republic con irrisolti, gruppi per classe e MIC, snapshot e SHA-256), copertura provider (idonei/non mappati/mappati/freschi/non aggiornati/senza osservazione/rejection, qualità effettiva senza etichetta tempo reale per i dati stale, bucket di ritardo, ultima osservazione/ingestione, attribuzione), budget per provider (finestre minuto/giorno/mese con reset, cooldown, motivo leggibile con reason code, ultimo esito), FX verso EUR per valuta separato dai provider (diretto/inverso, fresco/non aggiornato/mancante, osservato/ingerito, età), rejection parser/risoluzione distinte e coda; orari locali con UTC nel tooltip; percentuali mostrate come arrivano dall'API (test con percentuali volutamente diverse dal rapporto); copertura con loading/errore propri (`COVERAGE_INVARIANT_FAILED` spiegato, status legacy e backup restano visibili); "Aggiorna tutti i dati" sostituito da **Esegui batch prioritario (10)** con loading separato e ricarica di status e copertura; pannello backup, status `SEED/MIXED/REAL`, provider/cache, refresh del singolo asset e route `/data` invariati;
- test deterministici: fuso fissato con `vi.stubEnv("TZ", "Europe/Rome")` (verificato verde anche con `TZ` di ambiente New York e Tokyo) e solo `Date` finto con orario fisso;
- deviazioni: `frontend/package-lock.json` fuori elenco file: il gate `npm audit --audit-level=high` falliva per advisory high nuovi su `browserslist` 4.28.2 (GHSA-c83g-rgw3-j3cx, GHSA-73wf-gq98-2v4g), dipendenza transitiva di build preesistente; `npm update browserslist` (senza `--force`, `package.json` invariato) aggiorna solo browserslist 4.29.3, baseline-browser-mapping 2.11.26, caniuse-lite, electron-to-chromium, node-releases, update-browserslist-db 1.3.3; restano 2 low e 2 moderate (vitest/@vitest/mocker, @babel/core, postcss-selector-parser); ambiente: all'avvio il DNS non risolveva (GitHub, PyPI, npm irraggiungibili), quindi `backend/.venv` e stato popolato copiando `site-packages` dal venv del worktree Task 16 (stesso Python 3.14.7 e stessi requirements, `pip check` pulito), `npm ci --offline` dalla cache e il lock remoto del branch e stato pubblicato appena tornata la rete (base e `main` verificati a `d0d6b4c`); test client nello stesso file di test della pagina; `coverage_summary` tipizzato ma non usato dalla UI (la pagina legge `/data/coverage` completo); messaggio del batch "senza fallback / con fallback" (una cache hit non e un aggiornamento dal provider);
- minori aperti: un `rate_to_eur` in notazione scientifica (Decimal da float sotto 1e-6, es. `1E-7`) viene mostrato `—` (nessuna valuta BCE attuale e sotto quella soglia; correzione naturale nel backend con quantize); ECB assente da `provider_status`, quindi budget FX non visibile (gia noto dal Task 16); dopo il batch la pagina ricarica con lo skeleton completo (comportamento preesistente di `loadDataCenter`) e fra ricariche sovrapposte vince l'ultima risposta; l'esempio README `POST /news/refresh-all?limit=50` supera il massimo 25 (fuori scope, non modificato);
- gate: `npm --prefix frontend run test:run -- DataCenterPage.test.tsx UniversePage.test.tsx` = 23 passati (14 Data Center + 9 Universe); `npm --prefix frontend run build` exit 0 (avviso dimensione bundle preesistente); `npm --prefix frontend audit --audit-level=high` exit 0; backend invariato: suite completa `pytest -p no:cacheprovider` = 679 passati (0 falliti, JUnit XML); `ruff check backend scripts tests` verde; `git diff --check` verde.

Evidenza Task 18 (2026-10-01, Claude):

- audit cumulativo `5649982..8d95373`: 20 commit lineari (0 merge, un parent ciascuno), 17 messaggi identici al piano più 2 checkpoint e il commit documentale `6dda839`; 99 file. File fuori elenco: 39 occorrenze, 3 non registrate (`finnhub_news.py` nel Task 2, `tests/test_database.py` nel Task 4, `models/__init__.py` nel Task 13), senza difetti; report `docs/reports/2026-08-16-phase-2-verification.md`;
- review indipendente cumulativa (sola lettura): 2 Critical, 5 Important, 17 Minor; ogni rilievo accettato è stato riprodotto con un test RED e corretto nei path autorizzati:
  - **C1:** `/data/status` e `/news/status` in 500 dopo la prima cache del trasporto (`expires_at` con "Z"); confronto UTC aware;
  - **C2:** avvio impossibile dopo `seed --reset` o purge e ri-aggiunta di una crypto curata; il backfill riusa l'instrument che possiede il `COINGECKO_ID`;
  - **I1:** skip "fresco" EOD con soglia stale 96 h; refresh EOD dovuto oltre 24 h;
  - **I2:** sessione in corso salvata come EOD; CoinGecko accetta un giorno solo se il payload contiene il campione di chiusura; campo additivo `ProviderResponse.fetched_at`; Stooq scarta la riga del giorno locale del download;
  - **I4:** messaggio guida dei 409 di import e allocation ripristinato in `api.ts`;
  - **I5:** catalog refresh fuori dall'event loop (`run_in_threadpool`);
  - **Minor 13 riclassificato Important:** `TIME_PERIOD` BCE futuro rifiutato (`FUTURE_TIMESTAMP`);
  - **I3 rinviato su decisione dell'utente:** asset legacy non ricollegabili a listing risolti; README aggiornato, backlog;
- re-review del delta: C1, I1, I2, I4, I5 e Minor 13 VERIFIED; C2 PARTIAL per il nuovo rilievo I-1 (listing crypto riaggiunto senza fuso `UTC`, barre CoinGecko rifiutate), corretto con TDD (`UPDATE` del fuso prima del controllo sull'attestazione); re-review dell'incremento: I-1 VERIFIED, "Ready to commit: Yes"; Minor M-1…M-4 nei rischi residui del report;
- deviazioni:
  - secret scan del piano a exit 1 su 15 falsi positivi (riferimenti a codice), affiancato da uno scan con stesso pattern e classificazione riga per riga: 0 valori letterali, 3 sintetici;
  - `pytest.ini` ha già `addopts = -q`: i `-q` del piano nascondono il riepilogo, conteggi letti dal JUnit XML;
  - lo smoke B del piano seleziona 0 test di `test_import_security.py`;
  - `PROGRAMMA-OPERATIVO.md` aggiornato nello stesso commit (AGENTS.md §5);
  - `ImportPage.tsx` e `AllocationPlanner.tsx` non autorizzati: fix I4 nel solo client;
- verifiche aggiuntive:
  - smoke di migrazione reale da un DB creato col codice `5649982`: righe preservate, backup pre-migrazione, rerun idempotente, backup fallito che blocca la migrazione;
  - matrice provider offline in 3 scenari senza key né URL nelle risposte;
  - suite completa con rete bloccata: 679 passati, 0 tentativi di rete;
- gate finale:
  - suite completa `pytest -p no:cacheprovider` = 687 passati (0 falliti, JUnit XML, exit 0; run finale dopo I-1);
  - `ruff check backend scripts tests` verde; `compileall` exit 0; `pip check` pulito;
  - `npm ci` exit 0; `npm run test:run` = 24 passati; `npm run build` exit 0; `npm audit --audit-level=high` exit 0 (2 low, 2 moderate invariati);
  - smoke A 275 e smoke B 12 passati;
  - scan finale: 98 file con il report, 0 valori letterali inattesi, 3 sintetici, 0 placeholder; `git diff --check` verde.

## Registro SP1 — Laboratorio di verità

Spec: `docs/superpowers/specs/2026-10-02-investedge-sp1-truth-lab-design.md`. Piano: `docs/superpowers/plans/2026-10-02-investedge-sp1-truth-lab.md`. Branch per task: `investedge/sp1-task-N`, ciascuno dal precedente; il Task 1 parte da `origin/investedge/sp1-task-0`.

| Task | Titolo | Stato | Commit | Data | Owner |
|---|---|---|---|---|---|
| 0 | Brainstorming, spec e piano | FATTO | branch `investedge/sp1-task-0` | 2026-10-02 | Claude |
| 1 | Fixture seed condivisa e guardia di rete globale | NON INIZIATO | — | — | — |
| 2 | Pipeline di feature causale a finestra limitata (D) | NON INIZIATO | — | — | — |
| 3 | Barre W/M e score v1 | NON INIZIATO | — | — | — |
| 4 | Serie reale/demo, segmenti, guardia split e conversione EUR | NON INIZIATO | — | — | — |
| 5 | Backfill storico dei cambi BCE | NON INIZIATO | — | — | — |
| 6 | Feature store `features_daily` incrementale | NON INIZIATO | — | — | — |
| 7 | Score unico in segnali e analisi tecnica | NON INIZIATO | — | — | — |
| 8 | Job asincroni del laboratorio | NON INIZIATO | — | — | — |
| 9 | Costi Trade Republic, strategie e simulatore | NON INIZIATO | — | — | — |
| 10 | Backtest onesto in EUR come job, con registro dei tentativi | NON INIZIATO | — | — | — |
| 11 | Statistiche, walk-forward vero e DSR | NON INIZIATO | — | — | — |
| 12 | Harness di valutazione, report di evidenza e verdetto | NON INIZIATO | — | — | — |
| 13 | ML sulla pipeline condivisa | NON INIZIATO | — | — | — |
| 14 | Pagina Backtest su job, costi TR ed EUR | NON INIZIATO | — | — | — |
| 15 | Evidenza, badge del verdetto e pagina ML | NON INIZIATO | — | — | — |
| 16 | Prestazioni, documentazione e verifica finale SP1 | NON INIZIATO | — | — | — |

Evidenza Task 0 (2026-10-01/02, Claude):

- verifica Git iniziale: `origin/main` = `origin/codex/investedge-phase-2-task-18` = `6acd3c4`; primo commit `e579667` registra lo SHA del Task 18 Fase 2;
- brainstorming con l'utente: 10 decisioni e approccio di architettura (registro decisioni); design approvato in 6 sezioni;
- spec `fcb6392` e autorevisione; nella stesura del piano aggiunto il flag `warmup_complete` (spec §5.5–5.6, §6.1, §7.1, §8.2), segnalato all'utente;
- piano a 16 task con copertura della spec verificata (tabella finale del piano); solo documenti, nessun codice né test eseguiti; `git diff --check` verde.

## Backlog per i sottoprogetti futuri

Raccolto dalla review del 2026-09-30. Ogni voce entra nella spec del proprio SP.

- **SP2a Task 12:** news demo mai incluse in sentiment, `news_score` o feature ML; nessun rinnovo della data di pubblicazione delle news demo.
- **SP1 (efficienza test):** assorbita nella spec SP1 (Task 1, insieme alla guardia di rete globale, Minor 15 Fase 2).
- **SP1:** assorbita nella spec SP1 2026-10-02 (pipeline causale, score unico, backtester onesto, harness, walk-forward con DSR, `features_daily`, job asincroni).
- **SP2b:** fondamentali point-in-time (SEC EDGAR), eventi (utili, revisioni, insider Form 4, 8-K), macro/regime, barre intraday dalla fonte scelta dall'utente, universo IPO (S-1/F-1/424B), snapshot giornalieri dell'universo; fonte di eventi societari (split, dividendi) per rettificare le serie con base `UNKNOWN` (spec SP1 §6.3); ricollegamento esplicito di un asset legacy della Fase 1 a un listing `RESOLVED` dello stesso instrument (preview/apply con token SHA-256 e `compare_digest`, 409 senza mutazioni), rilievo I3 del Task 18 Fase 2, assegnato dall'utente il 2026-10-01.
- **SP3:** famiglie tecniche "trend di qualità" e "breakout" per orizzonte; forza relativa; volatilità che si comprime; news classificate per tipo di evento, deduplicate, pesate per fonte e tempo; pesi stimati dai dati.
- **SP4:** feature di training identiche a quelle di previsione; obiettivo di ranking cross-sezionale; purge ed embargo; calibrazione; champion/challenger; verifica ex-post delle previsioni live.
- **SP5:** radar con tasso storico dei profili simili, rischio, condizione di invalidazione; schede IPO con prospetto, management, soci, finanziatori, lock-up.
- **SP6:** portafogli paper multipli, paper broker, profili di rischio a scelta dell'utente, adapter broker ufficiali disattivati, kill switch, runtime sempre acceso, riconciliazione, aggiornamento automatico schedulato.
- **SP7:** Telegram bidirezionale con whitelist chat, codici di conferma e limiti.
- **Da assegnare:** minori aperti nel report Fase 2, sezione *Residual risks* (il Minor 15 è coperto dal Task 1 SP1).

## Registro decisioni

| Data | Decisione | Fonte |
|---|---|---|
| 2026-08-16 | Spec broker-grade e piani Fase 1 e Fase 2 approvati | spec 2026-08-16 |
| 2026-09-30 | Programma SP0–SP9, orizzonti, mercati, IPO, trading reale attivabile solo dall'utente, budget e profilo a scelta dell'utente, Telegram bidirezionale | spec 2026-09-30 |
| 2026-09-30 | La Fase 2 si chiude prima di SP1 (evita conflitti sugli stessi file) | utente |
| 2026-09-30 | Task 10: si conserva il checkpoint `54b3faf` più un commit di completamento, senza riscrivere la storia | utente |
| 2026-09-30 | Push del branch di ogni task e merge fast-forward su `main` ai gate di fase verificati: supera il divieto di merge/push su `main` dei piani Fase 1 e Fase 2 | utente |
| 2026-09-30 | Documenti di handoff Codex del Task 10 archiviati in `docs/handoff/2026-08-17-phase-2-task-10/` | Claude |
| 2026-09-30 | Push e merge fast-forward su `main` a ogni task: l'app non è in uso fino al completamento del programma | utente |
| 2026-10-01 | Le route che chiamano provider rilasciano il lock di univocita prima dell'I/O di rete (il budget non accetta transazioni del chiamante; un lock durante retry di rete bloccherebbe tutte le scritture) | Claude, motivata nel Task 12 |
| 2026-10-01 | Una nuova versione del provider symbol puo sostituire (`supersedes`) la versione ritirata dello stesso listing anche con simbolo diverso; trigger estesi con migrazione | Claude, motivata nel Task 14 |
| 2026-10-01 | Task 15 eseguito nella stessa chat del Task 14 (deroga alla regola "nuova chat per task") | utente |
| 2026-10-01 | Copertura: denominatori provider sui soli listing risolti (metadata VERIFIED + case RESOLVED, ACTIVE) e sulle coppie mappabili su listing (coingecko EOD/QUOTE, finnhub QUOTE, stooq EOD); `rejection_reasons` con prefisso `PARSE:`/`RESOLUTION:`; invariante violata → `/data/coverage` 500 e `coverage_summary` null | Claude, motivata nel Task 16 |
| 2026-10-01 | Gate audit del Task 17: aggiornamento del solo lockfile (`npm update browserslist`, nessun `--force`, `package.json` invariato) per eliminare advisory high su una dipendenza transitiva di build; moderate/low residui lasciati visibili | Claude, motivata nel Task 17 |
| 2026-10-01 | Rilievo I3 (asset legacy senza percorso verso listing risolti) rinviato e documentato, nessun codice nuovo nel Task 18 | utente |
| 2026-10-01 | Refresh EOD dovuto oltre 24 h, distinto dalla soglia stale di 96 h; una seduta che può essere ancora aperta non diventa mai barra EOD (`ProviderResponse.fetched_at` additivo) | Claude, motivata nel Task 18 |
| 2026-10-01 | SP1 misura e dichiara un verdetto (`VALIDATO` / `NON VALIDATO` / `INSUFFICIENTE`) senza blocchi operativi: il gate su decisioni e ordini arriva con SP6 | utente |
| 2026-10-01 | Score unico v1 solo tecnico (formula attuale dell'interfaccia su indicatori corretti); correzione news fuori dal `final_score` fino a SP3 | utente |
| 2026-10-01 | Indicatori causali e a finestra limitata (via `chikou_span` dai dati di calcolo, RSI di Wilder, ricorsivi troncati, drawdown 252, OBV relativo); timeframe D/W/M dalle daily, orizzonti 1/5/21 | utente |
| 2026-10-01 | Rettifiche: base dichiarata per provider (Stooq `UNKNOWN`) e guardia split fail-closed; fonte eventi societari in SP2b; backfill storico BCE in SP1 | utente |
| 2026-10-01 | Entrano in SP1 fixture di test veloce, `features_daily` e job asincroni; rilievo I3 assegnato a SP2b | utente |
| 2026-10-01 | Interfaccia SP1: adattamento minimo della pagina Backtest, modalità Evidenza e badge del verdetto; soglie Standard (t NW ≥ 2, spread netto > 0, DSR ≥ 0,95); feature ML = pipeline v1 senza news e portafoglio | utente |
| 2026-10-01 | Architettura SP1: pacchetto `backend/app/lab/` con `features_daily` unica fonte; branch documenti `investedge/sp1-task-0` | utente |
| 2026-10-02 | Spec SP1 approvata; dettagli fissati in stesura: badge una volta per sezione, `SEGMENT_EXIT`, *N* del DSR = configurazioni distinte, feature ML adimensionali, guardia di rete globale nei test, `warmup_complete` | utente (spec), Claude (dettagli, segnalati) |
| 2026-10-02 | Merge fast-forward su `main` dei documenti SP1 e del codice SP1 solo con conferma esplicita dell'utente | utente |

## Note di ripresa

- Spec e piano SP1 vivono sul branch `investedge/sp1-task-0`; finché l'utente non conferma il merge fast-forward, `main` resta a `6acd3c4` e i task SP1 partono dal branch, non da `main`.
- I worktree Codex `C:\Users\izzod\.codex\worktrees\f80e` (Task 10) ed `e139` (Task 6) sono superati: non riprendere da lì.
- `backend/.venv` non è versionato: ogni worktree lo crea con i comandi di `AGENTS.md`.
- Test legati al calendario: un test non deve dipendere dalla data reale. Se un servizio legge `datetime.now`, il test blocca l'orologio (vedi `_freeze_service_clock` in `tests/test_market_data_observations.py`).
- Test frontend con orari: fissare il fuso con `vi.stubEnv("TZ", ...)` (il build TypeScript non conosce `process`) e creare gli `Intl.DateTimeFormat` al render, non a livello di modulo.
- `npm audit` dipende da advisory pubblicati dopo l'ultimo task: il gate puo fallire senza modifiche al codice.
- `pytest.ini` imposta gia `addopts = -q`: aggiungere `-q` nasconde la riga di riepilogo; usare `--junitxml` per i conteggi.
- Lo script di secret scan del piano Fase 2 segnala come candidati anche riferimenti a codice (assegnazioni di token calcolati da metodi o letti dalle settings): classificare ogni candidato rispetto alla riga sorgente prima di trattarlo come segreto.
