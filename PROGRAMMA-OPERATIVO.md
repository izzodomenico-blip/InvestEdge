# InvestEdge — programma operativo

Fonte unica dello **stato di avanzamento**. Vale per Claude Code e Codex. Regole di lavoro in `AGENTS.md`; decisioni e confini in `docs/superpowers/specs/2026-09-30-investedge-profit-engine-program-design.md`.

Ultimo aggiornamento: 2026-10-03.

## Prossimo passo

**SP1 Task 9 — Costi Trade Republic, strategie e simulatore.**

- Esecuzione: nuova chat con contesto pulito, salvo deroga dell'utente.
- Branch `investedge/sp1-task-9` da `origin/investedge/sp1-task-8` (verifica della base con il protocollo del piano).
- Ingressi: spec `docs/superpowers/specs/2026-10-02-investedge-sp1-truth-lab-design.md` §6.2, §6.4 e §7, piano `docs/superpowers/plans/2026-10-02-investedge-sp1-truth-lab.md` (Task 9), registro SP1 qui sotto (note dei Task 4 e 6 su serie, segmenti, `EurConverter` e `FeatureStore`).
- Il Task 9 registra nel registro SP1 lo SHA del Task 8.

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
| SP1 | Laboratorio di verità | IN CORSO | `2026-10-02-investedge-sp1-truth-lab-design.md` | `2026-10-02-investedge-sp1-truth-lab.md` | — | Task 0–7: `bcd7179` (2026-10-03) |
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
| 0 | Brainstorming, spec e piano | FATTO | `e579667`, `fcb6392`, `aa13c44`, `53fe614` | 2026-10-02 | Claude |
| 1 | Fixture seed condivisa e guardia di rete globale | FATTO | `a115dab` | 2026-10-02 | Claude |
| 2 | Pipeline di feature causale a finestra limitata (D) | FATTO | `90b49ab` | 2026-10-03 | Claude |
| 3 | Barre W/M e score v1 | FATTO | `b76fff5` | 2026-10-03 | Claude |
| 4 | Serie reale/demo, segmenti, guardia split e conversione EUR | FATTO | `86d6f73` | 2026-10-03 | Claude |
| 5 | Backfill storico dei cambi BCE | FATTO | `0bd6c0e` | 2026-10-03 | Claude |
| 6 | Feature store `features_daily` incrementale | FATTO | `96f7299` | 2026-10-03 | Claude |
| 7 | Score unico in segnali e analisi tecnica | FATTO | `bcd7179` | 2026-10-03 | Claude |
| 8 | Job asincroni del laboratorio | FATTO | branch `investedge/sp1-task-8` | 2026-10-03 | Claude |
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

Evidenza Task 1 (2026-10-02, Claude, nella stessa chat del Task 0 su richiesta dell'utente):

- `tests/conftest.py`: guardia di rete autouse su `socket.create_connection`, `socket.socket.connect`, `socket.socket.connect_ex` e `socket.getaddrinfo` (`RuntimeError("NETWORK_BLOCKED_IN_TESTS")`, risolve il Minor 15 della Fase 2); template seed di sessione (`seeded_db_template`) con la riga FX USD→EUR della vecchia fixture; fixture `client` che copia il template per test con lo stesso ambiente (`CLIENT_ENV`);
- RED verificato: senza guardia la richiesta reale a `example.com` partiva (test `httpx` senza eccezione) e la fixture del template non esisteva;
- deviazioni: la fixture `client` è spostata da `tests/test_api.py` a `tests/conftest.py` (necessario per condividerla con `tests/test_test_infrastructure.py`); il loopback (`127.0.0.1`, `::1`, `localhost`) resta ammesso, perché su Windows l'event loop asyncio di `TestClient` crea una `socketpair` su `127.0.0.1` (il piano assumeva nessun socket); test aggiuntivo `test_loopback_socketpair_is_allowed`; `gc.collect()` dopo il seed del template per chiudere connessioni già committate ma non chiuse;
- tempi: `pytest tests\test_api.py` da 711,99 s a 45,23 s (193 passati in entrambi, JUnit XML); `backend/.venv` creato nel worktree con i comandi di AGENTS.md (Python 3.14.7, `pip check` pulito);
- minore preesistente, fuori perimetro: `init_db` (`with get_connection()`) e il seed lasciano connessioni SQLite non chiuse (`ResourceWarning`);
- gate: `pytest tests\test_test_infrastructure.py` = 4 passati; suite completa `pytest -p no:cacheprovider` = 691 passati, 0 falliti, 0 errori (JUnit XML, 83 s, guardia di rete attiva su tutti i test); `ruff check backend scripts tests` verde; `git diff --check` verde; review del diff senza rilievi Critical o Important.

Evidenza Task 2 (2026-10-03, Claude):

- `backend/app/lab/contracts.py` (contratti condivisi: `DataMode`, `Timeframe`, versioni, `PERIODS_PER_YEAR`, `LabError`) e `backend/app/lab/features.py`: 34 colonne `features-v1` con le finestre W della spec §5.3; ogni riduzione lavora sulla propria finestra (`sliding_window_view`, nessuna somma cumulata dall'inizio serie); warm-up applicato per colonna (NaN prima di W barre); EMA/Wilder troncati con pesi `(1 − α)^k` normalizzati; Supertrend vettoriale con la macchina a stati attuale ricalcolata sulle ultime 100 barre; pivot ±2 confermati sulle ultime 180 barre; O/H/L/C × `adjusted_close/close`; nessun import da `technical_analysis`, nessuna nuova dipendenza;
- RED verificato: `ModuleNotFoundError: No module named 'backend.app.lab'`; test e fixture identici al piano;
- verifiche aggiuntive in scratch (non committate): uguali agli indicatori attuali entro 1e-12 SMA, stocastico, ROC, volatilità, ATR, Bollinger, volume ratio, Supertrend e supporti/resistenze; MACD e DI/ADX differiscono solo per il troncamento (MACD ≤ 0,5% della mediana, ADX ≤ 0,05 punti); `max_drawdown_252` uguale al calcolo a forza bruta; indipendenza **bit a bit** dalla finestra su 34 righe × 34 colonne e warm-up stretto (W − 1 barre → NaN); 1500 barre in circa 15 ms;
- scelte interpretative: `macd_line_pct` resta NaN fino a 139 barre (W della spec, attivazione insieme al segnale); `atr_14_pct` e `macd_*_pct` come frazione (diviso per il close, spec §5.3); `support_distance_pct`/`resistance_distance_pct` e `roc_12` in percento come gli indicatori attuali (unità attese dal Task 3); divisioni per zero → NaN come oggi;
- deviazioni: nessun file fuori elenco; review del diff svolta nella chat del task;
- minori aperti: `compute_features` non valida ordinamento e unicità delle date (precondizione del chiamante: serie e segmenti del Task 4, feature store del Task 6); una serie piatta dà NaN su RSI, stocastico, Bollinger e DI/ADX, quindi nel Task 3 il warm-up dello score non risulterà mai completo per quella serie;
- ambiente: `backend/.venv` creato nel worktree con i comandi di AGENTS.md (Python 3.14.7, `pip check` pulito);
- gate: `pytest tests\test_lab_features.py` = 10 passati (anche con `-W error::RuntimeWarning`); suite completa `pytest -p no:cacheprovider` = 701 passati, 0 falliti, 0 errori, 0 skip (JUnit XML, 138 s); `ruff check backend scripts tests` verde; `git diff --cached --check` verde; review del diff senza rilievi Critical o Important.

Evidenza Task 3 (2026-10-03, Claude):

- `backend/app/lab/resample.py`: `resample_bars(daily, "W" | "M", as_of)` con `available_at` = domenica o ultimo giorno del mese e solo periodi chiusi entro `as_of`; open primo, high massimo, low minimo, close ultimo, volume somma, fattore di rettifica dell'ultima daily; vettoriale (`reduceat`);
- `backend/app/lab/score_v1.py`: `SUBSCORE_COLUMNS`, `SCORE_INPUT_COLUMNS` (20 colonne, compreso `close_adj`), `explain(row, risk_level)` e `score_frame(features, risk_level)` sulla stessa funzione interna per riga; sottopunteggi, pesi, soglie, motivazioni, rischio, confidenza, condizioni, sintesi e bias portati da `ScoringEngine`/`TechnicalAnalysisService` con le sostituzioni del piano; `warmup_complete` = tutti gli input finiti tranne supporti e resistenze; clamp e soglie del segnale riusati da `services.common` (nessuna copia); nessun import da `technical_analysis` o `scoring_engine`, nessuna nuova dipendenza;
- Step 1: 6 `GOLDEN_CASES` catturati dalla formula attuale con uno script nello scratchpad (patch di `calculate_full_technical_analysis`; condizioni e sintesi del caso calcolate con il codice attuale): coprono STRONG_BUY/HOLD/REDUCE/SELL, rischio LOW/MEDIUM/HIGH, confidenza HIGH/MEDIUM e tutti i rami RSI; letterali nel test, che non importa moduli legacy;
- RED verificato: `ModuleNotFoundError: No module named 'backend.app.lab.resample'`;
- verifiche aggiuntive in scratch (non committate): `explain` identico alla formula attuale su 20.000 casi casuali con valori di soglia (score, segnale, rischio, confidenza, motivazioni con tipo, sottopunteggi, condizioni, supporti/resistenze, sintesi, `technical_summary`); `resample_bars` identico a un `groupby` pandas su 40 combinazioni, stabile come prefisso e indipendente dalle daily successive su 868 `as_of`; `score_frame` = `explain` su 1500 righe, prima riga completa alla 252ª barra, circa 31 ms; W da 1500 daily: 299 barre, 48 complete;
- scelte interpretative:
  - O/H/L delle barre W/M aggregati sui prezzi rettificati e riportati nella scala del fattore dell'ultima daily: uguali all'aggregazione dei grezzi con fattore costante (identici con fattore 1), coerenti con uno split nel periodo (la lettura letterale darebbe high 198,5 invece di 99,5 nel caso di prova);
  - una serie che inizia a metà periodo produce una prima barra W/M parziale (causale);
  - `explain`: `indicators` con i nomi `features-v1` (valori finiti arrotondati a 6 cifre come oggi), `support_resistance` con le chiavi attuali (`support_distance_percent`, ...), `conditions` senza golden/death cross, `latest_close` = `close_adj`; lo score usa i valori non arrotondati (oggi a 6 cifre: differenza solo sul filo delle soglie); ATR come `atr_14 / close_adj`, come oggi;
- deviazioni: nel test del piano `{name: value for ...}` → `dict(indicators)` (Ruff C416); chiave `name` nei `GOLDEN_CASES`; nessun file fuori elenco;
- note per i task successivi:
  - Task 6: `features_json` deve contenere anche `close_adj` (in `SCORE_INPUT_COLUMNS`, non in `FEATURE_COLUMNS_V1`), altrimenti `explain` sulla riga salvata non riproduce lo score;
  - Task 7: `AnalysisPage` legge `indicators.volatility_annualized_30d` e `indicators.max_drawdown`, che con `explain` diventano `volatility_30d` e `max_drawdown_252`;
  - l'allineamento W/M sulle date daily (`merge_asof`, spec §5.4) è nel Task 6 (`signal_panel`);
- minori aperti: `resample_bars` non valida ordinamento e unicità delle date (precondizione, come `compute_features`); serie piatta: `warmup_complete` resta 0 (dichiarato nel Task 2, non corretto);
- ambiente: `backend/.venv` creato nel worktree con i comandi di AGENTS.md (Python 3.14.7, `pip check` pulito);
- gate: `pytest tests\test_lab_score.py tests\test_lab_features.py -p no:cacheprovider` = 19 passati (anche con `-W error::RuntimeWarning`); suite completa `pytest -p no:cacheprovider` = 710 passati, 0 falliti, 0 errori, 0 skip (JUnit XML, 78 s); `ruff check backend scripts tests` verde; `git diff --cached --check` verde; review del diff senza rilievi Critical o Important.

Evidenza Task 4 (2026-10-03, Claude):

- `backend/app/lab/series.py`:
  - `load_series(connection, asset_id, data_mode)`: solo le righe del `data_mode` (REAL = `is_real_data = 1`, DEMO = `0`, mai mescolate), una riga per data (`substr(date, 1, 10)`, vince l'`id` maggiore), date ordinate e uniche in ogni segmento; `None` senza asset o senza righe; `available_data_modes` e `preferred_data_mode` (REAL se esiste, altrimenti DEMO, `None` senza prezzi);
  - `PROVIDER_ADJUSTMENT_BASIS` (`coingecko` → `NOT_APPLICABLE`, `stooq` → `UNKNOWN`); base della serie = base comune dei provider delle righe usate, altrimenti `UNKNOWN`;
  - `split_into_segments` vettoriale: buchi oltre `LAB_SEGMENT_MAX_GAP_SESSIONS` (giorni lavorativi con `numpy.busday_count` per azioni/ETF, di calendario per `crypto`); guardia split solo con base `UNKNOWN` (rapporti 2, 3, 4, 5, 10, 3/2; close e open entro `LAB_SPLIT_TOLERANCE` relativa); `segment_id` da 0, `SplitEvent` (data, rapporto, `FORWARD`/`REVERSE`), `gap_starts`;
  - `EurConverter.rate_on` e `convert_bars` (`open/high/low/close_eur` = prezzi rettificati × cambio, NaN senza cambio valido, più il conteggio delle barre escluse): ultima osservazione con data ≤ barra ed età ≤ `max_age_days`; riga diretta X→EUR, altrimenti inversa EUR→X con reciproco, come `FXService.get_rate`; EUR = 1;
  - nessun import da `technical_analysis`, nessuna nuova dipendenza, nessuna migrazione;
- impostazioni `lab_segment_max_gap_sessions` (5) e `lab_split_tolerance` (0.03) in `config.py`, documentate in `.env.example` e `backend/.env.example`;
- test: helper `insert_asset`, `insert_bars` (`source` = provider, oppure `real`/`mock`) e `insert_fx` (righe dirette) in `tests/lab_fixtures.py`; fixture `lab_connection` in `tests/conftest.py` (DB temporaneo con `init_db`, nessun seed; fixture esistenti invariate); gli 8 test del piano in `tests/test_lab_series.py` con i nomi del piano;
- RED verificato: `ModuleNotFoundError: No module named 'backend.app.lab.series'`;
- scelte interpretative:
  - spec §5.1 "con base `UNKNOWN` il fattore vale 1": `load_series` pone `adjusted_close = close` con base `UNKNOWN` o `NOT_APPLICABLE`; con base dichiarata (`SPLIT`, `SPLIT_DIVIDEND`, oggi nessun provider) un `adjusted_close` NULL diventa `close`;
  - `EurConverter` esclude le righe FX con provider `seed` (dato demo: vincolo REAL/DEMO del piano);
  - preferenza diretta/inversa valutata alla data della barra: una riga diretta con data ≤ barra ma più vecchia di `max_age_days` dà NaN, senza ripiegare sull'inversa (come `FXService`, che la restituisce marcata `stale`);
  - un buco e uno split sulla stessa barra aprono un solo segmento e compaiono in entrambi gli elenchi; con più rapporti compatibili vince il primo di `SPLIT_RATIOS` (con la tolleranza di default gli intervalli non si sovrappongono);
  - `test_eur_converter_matches_fx_service_direction`: orologio di `fx_service` bloccato al 2024-01-08 e date fisse ("oggi" = 2024-01-08; verificata anche `quality == "reference"`);
- deviazioni: 2 test oltre gli 8 del piano, per coprire con TDD le due scelte fail-closed (`test_unknown_basis_ignores_unverified_adjusted_close`, `test_eur_converter_ignores_seed_rates`); `test_real_series_never_contains_seed_rows` verifica anche la regola "vince l'`id` maggiore"; nessun file fuori elenco;
- verifiche aggiuntive in scratch (non committate): 1500 barre con buco di 8 sedute e split 2:1 → 3 segmenti con date ordinate e uniche, `compute_features` e `resample_bars` su ogni segmento; `load_series` circa 7 ms, `convert_bars` circa 1 ms; `rate_on` coerente con `convert_bars` riga per riga;
- note per i task successivi:
  - `EurConverter` legge i cambi di una valuta una sola volta per istanza: nel Task 5 il convertitore va creato dopo il backfill;
  - `LabSeries.currency` è `assets.currency` com'è salvato (il convertitore normalizza maiuscole e spazi);
  - le barre dei segmenti hanno le colonne `date, open, high, low, close, adjusted_close, volume`; `open/high/low/volume` restano NaN se NULL nel DB;
- minori aperti: nessuna validazione di `close ≤ 0` o di date malformate (dati validati all'ingestione); `SeriesSegment` e `LabSeries` sono frozen con un `DataFrame`: l'uguaglianza fra istanze non è definita;
- ambiente: `backend/.venv` creato nel worktree con i comandi di AGENTS.md (Python 3.14.7, `pip check` pulito); la suite mostra 2 `StarletteDeprecationWarning` delle versioni installate, senza effetti sui test;
- gate: `pytest tests\test_lab_series.py tests\test_config.py tests\test_fx_service.py -p no:cacheprovider` = 27 passati (10 di `test_lab_series.py`, anche con `-W error::RuntimeWarning`); `pytest tests\test_lab_features.py tests\test_lab_score.py -p no:cacheprovider` = 19 passati; suite completa `pytest -p no:cacheprovider` = 720 passati, 0 falliti, 0 errori, 0 skip (JUnit XML, 139 s); `ruff check backend scripts tests` verde; `git diff --cached --check` verde; review del diff senza rilievi Critical o Important.

Evidenza Task 5 (2026-10-03, Claude):

- `EcbFxProvider.fetch_history(connection, from_currency, start, end, now)`: una sola GET `EXR/D.<VAL>.EUR.SP00.A` con `format=csvdata`, `startPeriod`, `endPeriod` (nessun `lastNObservations` né `If-Modified-Since`), stesso trasporto governato e bucket `ecb` (1 unità per chiamata, cache `fx-history:<VAL>:<start>:<end>` con il TTL BCE esistente); quote `X → EUR` reciproche, `reference`, ordinate per data; `start > end` rifiutato con `ValueError` prima del trasporto; filtro della serie e parsing della data estratti in `_series_observation`, condiviso con `fetch_rate` (comportamento invariato);
- `FxBackfillResult` (dataclass del servizio) e `FXService.backfill_history(connection, currency, start, now=None)`: intervallo da `start` al giorno UTC di `now`; inserimento idempotente con `_persist_quotes(..., replace_existing=False)` (validazione preventiva, savepoint, righe esistenti mai modificate); `existing` = quote già presenti sul vincolo univoco; prima e ultima osservazione ricevute;
- `backend/scripts/backfill_fx_history.py`: `--currency` (ripetibile, allowlist BCE, deduplicata), `--start`, `--apply`; anteprima di default senza chiamate né apertura del DB; con `--apply` una chiamata per valuta ed esito per valuta, `ProviderError` sanitizzato → exit 1; exit 2 con `ENABLE_REAL_DATA` falso, `--start` futura o argomenti non validi;
- fixture `tests/fixtures/market_data/ecb_exr_usd_eur_history.csv`: header di `ecb_exr_usd_eur.csv`, 10 righe sintetiche (2024-01-02…2024-01-15, valori 1,1000…1,1090) più la riga 2099-01-01;
- test del piano, con `now` esplicito 2024-01-16T12:00Z (mai la data reale): `test_ecb_fetch_history_requests_period_once_and_drops_future_rows` (richiesta del `MockTransport`, 1 unità in ogni finestra del budget `ecb`, riga futura scartata, 10 quote `reference`); `test_backfill_history_is_idempotent_and_feeds_the_eur_converter` (10 inserite; rerun 0 inserite e 10 `existing` dalla cache, una sola chiamata; `EurConverter` creato dopo il backfill = riga diretta del 2024-01-10); `test_backfill_script_refuses_without_real_data_before_any_call` (exit 2 con e senza `--apply`, nessuna riga in `provider_request_log`, guardia di rete attiva);
- RED verificato: `AttributeError` per `fetch_history`/`backfill_history` assenti, `ImportError` per lo script assente;
- scelte interpretative:
  - `FUTURE_TIMESTAMP` scarta la sola riga; anche un giorno senza valore (`MISSING_VALUE`: vuoto, `NaN`, `NA`, `.`) viene scartato senza bloccare le altre righe (nessun cambio inventato: quella data usa l'ultima osservazione entro `ECB_FX_MAX_AGE_DAYS`); un valore non valido (`INVALID_RATE`, `MALFORMED_PAYLOAD`) rifiuta l'intera risposta senza scritture;
  - "ON CONFLICT DO NOTHING" realizzato con l'`INSERT OR IGNORE` esistente di `_persist_quotes`: equivalente sul vincolo univoco `(from_currency, to_currency, observed_at, provider)` perché ogni quota è validata prima della scrittura;
  - lo script con `ENABLE_REAL_DATA` falso rifiuta anche l'anteprima (exit 2 prima di ogni altra verifica, come il 409 della route); intervallo fino al giorno UTC corrente, nessuna opzione `--end`;
  - risposta CSV senza righe valide → `inserted = existing = 0` e date `None`, nessun errore; un 304 (inatteso senza `If-Modified-Since`) → `ecb:FX:NOT_MODIFIED_WITHOUT_BASELINE`, come `fetch_reference_rates`;
- deviazioni: 2 test oltre il piano (`test_ecb_fetch_history_skips_missing_values_without_dropping_valid_days`, con `start > end` senza chiamate; `test_backfill_script_previews_without_calls_and_applies_on_request`: anteprima senza chiamate, `--start` futura → exit 2, `--apply` → 10 righe); `main()` dello script accetta `service` e `now` iniettabili per i test; il test di `backfill_history` verifica anche `start` futura → `ValueError` senza chiamate; prima nota di ripresa aggiornata allo stato reale di `main`; nessun file fuori elenco;
- smoke CLI (DB temporaneo, nessun `--apply`, nessuna rete): `ENABLE_REAL_DATA=false` → exit 2; anteprima con `--currency usd --currency GBP --currency USD` → "valute USD, GBP", exit 0, DB non creato; `--currency XYZ` → exit 2;
- note per i task successivi:
  - Task 8 (job `FX_BACKFILL`, `POST /data/fx/backfill`): riusare `FXService.backfill_history`, con il controllo di `ENABLE_REAL_DATA` (409 `REAL_DATA_DISABLED`) prima di ogni chiamata; il budget richiede una connessione senza transazione aperta, come `refresh_currency`;
  - `EurConverter` va creato dopo il backfill (legge i cambi una volta per istanza);
- minori aperti:
  - il limite di risposta BCE di 1 MiB (byte decompressi, condiviso con `fetch_rate`) vale anche per lo storico: con circa 150 byte per riga `csvdata` (stima, non verificabile senza chiamate live) uno storico oltre circa 20 anni, per esempio dal 1999, potrebbe superarlo e fallire fail-closed con `ecb:FX:RESPONSE_TOO_LARGE`, senza scritture; l'esempio del piano (dal 2015) resta sotto;
  - la risposta storica resta nella cache del trasporto per il TTL BCE (6 h);
  - `lab_connection` (`init_db`) lascia una connessione SQLite non chiusa (`ResourceWarning`, minore preesistente del Task 1);
- ambiente: `backend/.venv` creato nel worktree con i comandi di AGENTS.md (Python 3.14.7, `pip check` pulito); la suite mostra 2 `StarletteDeprecationWarning` delle versioni installate, senza effetti sui test;
- gate: `pytest tests\test_reference_providers.py tests\test_fx_service.py tests\test_lab_series.py -p no:cacheprovider` = 49 passati (i 5 nuovi anche con `-W error::RuntimeWarning`); suite completa `pytest -p no:cacheprovider` = 725 passati, 0 falliti, 0 errori, 0 skip (JUnit XML, 115 s); `ruff check backend scripts tests` verde; `git diff --cached --check` verde; review del diff senza rilievi Critical o Important.

Evidenza Task 6 (2026-10-03, Claude, nella stessa chat del Task 5 su richiesta dell'utente):

- `features_daily` in `BASE_SCHEMA` (colonne, CHECK e vincolo univoco del piano, FK `ON DELETE CASCADE`) e `idx_features_daily_lookup` in `INDEX_SCHEMA`: migrazione additiva (la tabella nasce con `init_db` anche sui DB esistenti), nessuna tabella esistente toccata;
- `backend/app/lab/feature_store.py`: `FeatureRefreshResult` e `FeatureStore` con `compute_rows` (puro), `refresh_asset`, `read_frame`, `signal_panel`, `latest_row`:
  - righe D (barre fino ad `as_of`), W e M (`resample_bars(..., as_of)` per segmento), feature `features-v1` e score `score-v1` sul livello di rischio dell'asset; `features_json` con `close_adj` e le 34 feature (NaN → `null`, JSON senza NaN);
  - `window_hash` come da piano: digest a 64 bit per barra sul `repr` dei float, somma modulo 2⁶⁴ con somme cumulative `uint64`, finestra `[max(inizio segmento, i − 251), i]`, versioni, timeframe, segmento, rischio, prima e ultima data, numero di barre;
  - refresh: confronto degli hash con le righe salvate della stessa `pipeline_version`; ricalcolo delle sole righe nuove o cambiate su una slice che parte 251 barre prima della prima da ricalcolare; upsert sul vincolo univoco e cancellazione delle righe non più candidate in un savepoint (commit se la connessione non ha transazioni aperte, altrimenti dentro quella del chiamante); `None` se l'asset non esiste;
  - `signal_panel`: nome del segnale in allowlist (score, sottopunteggi, feature) prima di qualsiasi SQL; D solo con la riga a quella data; W/M ultima riga con data ≤ data (`merge_asof`), solo se completa e dello stesso segmento della data;
  - nessun import da `technical_analysis`, nessuna nuova dipendenza;
- RED verificato: `ModuleNotFoundError: No module named 'backend.app.lab.feature_store'` e tabella assente nel test di schema;
- test: gli 8 del piano con i nomi del piano, 2 aggiuntivi e il test di schema in `tests/test_database.py` (colonne, ordine dell'indice, vincolo univoco, CHECK, `ON DELETE CASCADE` da `delete_asset(..., purge=True)`); `test_incremental_equals_full_recompute` confronta anche `window_hash` e `features_json` come stringhe (valori identici bit a bit) dopo una revisione e la cancellazione dell'ultima barra; `compute_rows` coincide con le righe salvate (hash e score);
- scelte interpretative:
  - due barre W/M con la stessa `available_at` in segmenti diversi (split a metà settimana o mese) violerebbero il vincolo univoco: resta quella del segmento successivo (registro decisioni);
  - `signal_panel` W/M: oltre a `warmup_complete`, la riga as-of deve avere lo stesso `segment_id` della riga D as-of della data (spec §6.2: nessun valore di un segmento precedente dopo un buco o uno split); una riga as-of incompleta dà NaN, senza ripiegare su righe complete più vecchie;
  - le righe D si fermano ad `as_of` (giorno UTC di `now`), come le barre W/M;
  - `latest_row` restituisce l'ultima riga D anche con warm-up incompleto (`warmup_complete` booleano) e le feature del JSON (`None` se mancanti), per il messaggio "storico insufficiente" del Task 7;
  - `signal_panel` legge i valori dalle colonne REAL o dal JSON con il parser Python (stessi float di `read_frame`, nessun `json_extract` di SQLite);
- deviazioni: 2 test oltre il piano (`test_split_mid_week_keeps_later_segment_and_panel_stops_at_boundary`, `test_rows_without_bars_are_deleted`); nel test settimanale `datetime.timedelta` al posto di `pd.Timedelta` (con le versioni installate `pd.Timedelta(days=...)` emette un `DeprecationWarning` di NumPy); nessun file fuori elenco;
- prestazioni (scratch, DB temporaneo, 50 asset × 1500 barre, 93.453 righe): calcolo completo 26,2 s (obiettivo della spec ≤ 60 s); incrementale di una barra 0,26 s (≤ 5 s); refresh senza modifiche 3,5 s per 50 asset; `signal_panel` D 0,9 s e W 1,9 s su 1500 date; `read_frame` D 3,8 s per 62.451 righe (parsing JSON);
- note per i task successivi:
  - Task 7: `latest_row` contiene tutte le chiavi lette da `explain` (`close_adj` compreso); il refresh incrementale del solo asset rinfrescato è `refresh_asset(connection, asset_id, data_mode, now)`, utilizzabile anche dentro una transazione del chiamante (savepoint);
  - Task 8, 10, 12 e 13: `read_frame` e `signal_panel` leggono solo la `pipeline_version` corrente; aggiornare gli asset dell'universo con `refresh_asset` prima di leggere;
- minori aperti: `read_frame` analizza il JSON riga per riga (circa 60 µs per riga); un refresh senza modifiche ricalcola comunque gli hash (circa 70 ms per asset da 1500 barre); `features_daily` non entra nei conteggi di dipendenza della cancellazione protetta (deriva da `price_history`, che già la blocca);
- ambiente: stesso `backend/.venv` del Task 5;
- gate: `pytest tests\test_lab_feature_store.py tests\test_database.py tests\test_lab_features.py tests\test_lab_score.py tests\test_lab_series.py -p no:cacheprovider` = 67 passati (anche con `-W error::RuntimeWarning`); suite completa `pytest -p no:cacheprovider` = 736 passati, 0 falliti, 0 errori, 0 skip (JUnit XML, 93 s); `ruff check backend scripts tests` verde; `git diff --cached --check` verde; review del diff senza rilievi Critical o Important.

Evidenza Task 7 (2026-10-03, Claude):

- verifica Git iniziale: `origin/investedge/sp1-task-6` = `origin/main` = `96f7299` (un commit sopra `origin/investedge/sp1-task-5` = `0bd6c0e`); il fast-forward di `main` a `96f7299` del 2026-10-03 (Task 4–6, richiesta dell'utente) è registrato qui (quadro, registro decisioni, note di ripresa);
- `signals_service.recalculate_signal(connection, asset_id, now=None)`: serie REAL se esiste, altrimenti DEMO (`preferred_data_mode`), `FeatureStore.refresh_asset` incrementale del solo asset, ultima riga D di `features_daily`, `explain` sul livello di rischio dell'asset; `score = technical_score = final_score`, segnale da `signal_from_score(score)`, `signals.data_mode` valorizzato; `news_score` = sentiment medio 7 giorni × peso entro ±peso (solo informativo, news demo escluse come prima); senza riga completa nessun segnale (quello vecchio di `scoring_engine` viene rimosso); `score_unavailable_reason(connection, asset_id)` = "Storico reale insufficiente (N barre, servono 252)." oppure `None`;
- `MarketDataService._recalculate_signal` delega a `recalculate_signal` (attributo `scoring_engine` rimosso); `ScoringEngine.score_prices` con la stessa firma = `compute_features` sul frame (un segmento) + `explain` dell'ultima riga, più la chiave `warmup_complete` (helper legacy rimasti senza uso eliminati); nessun import di `technical_analysis`;
- `/technical-analysis/{symbol}` da `features`/`explain` sull'ultimo segmento della serie del segnale (barre fino al giorno UTC corrente): `data_mode`, `final_score = score`, news informative; serie REAL corta → 409 `{"reason_code": "INSUFFICIENT_REAL_HISTORY", "message": "Storico reale insufficiente (N barre, servono 252)."}`;
- schemi additivi: `data_mode` su `SignalOut`, `TechnicalAnalysisOut`, `ActionItemOut`; `signal_data_mode` e `score_unavailable_reason` su `AssetOut` (in coda, default `null`);
- migrazione additiva `signals.data_mode` con CHECK `NULL`/`REAL`/`DEMO` in `MIGRATIONS["signals"]`, `SIGNALS_REBUILD_SQL` (colonna e copia) e `BASE_SCHEMA`;
- seed: segnali via `recalculate_signal`; con la sola serie demo l'orologio è quello del seed (`2026-05-17T00:00:00`, come il vecchio `created_at`), con una serie reale quello attuale; `signals_inserted` conta le righe create;
- test: `tests/test_lab_boundaries.py` (`ast` su `backend/app/lab/*.py` e sui 7 servizi del piano, `PENDING_BOUNDARY = {"backtest_engine.py", "ml_dataset_service.py"}` con `xfail(strict=True)`, controllo che il rilevatore veda l'import legittimo di `prices_service`); `tests/test_lab_signals.py` con i 5 test del piano; in `tests/test_api.py` contratto `/assets` con i 2 campi additivi e 4 test (`data_mode` di `/signals` e `/assets`, score di `/technical-analysis` = segnale, 409 `INSUFFICIENT_REAL_HISTORY` con `score_unavailable_reason` su `/assets`, `data_mode` delle azioni dell'action board); `test_provider_failure_fallback_to_demo_does_not_change_final_score` (in `tests/test_news_providers.py`, non in `tests/test_api.py`) verde e invariato;
- RED verificato: `ImportError` di `recalculate_signal`; confine fallito su `scoring_engine.py` (2 xfail strict sui moduli pendenti); `KeyError: 'data_mode'`; 200 invece di 409; contratto `AssetOut` senza i nuovi campi; regressione news: score 0 riportato a 50 (vedi deviazioni);
- scelte interpretative:
  - "riga D più recente con `warmup_complete`" = l'ultima riga D deve essere completa: nessun ripiego su righe più vecchie o su un segmento precedente (dopo un buco o uno split il segmento nuovo ha il proprio warm-up); `N` del messaggio = barre del segmento corrente;
  - `score_unavailable_reason` solo per le serie REAL; una serie DEMO corta non ha segnale né motivo e `/technical-analysis` risponde 404;
  - l'analisi tecnica ricalcola in memoria (nessuna scrittura in una GET), uguale alla riga di `features_daily` per la proprietà di finestra limitata (test di uguaglianza con il segnale);
  - il 409 porta anche `message` (testo sicuro) oltre al `reason_code`;
  - `ActionItemOut.data_mode` = `data_mode` dell'ultimo segnale del simbolo per BUY/REDUCE/SELL, `null` per RISK/OK;
  - la finestra news di `aggregate_news_sentiment` resta sull'orologio reale anche quando `recalculate_signal` riceve `now` (`sentiment_engine.py` non toccato); i test bloccano l'orologio di `sentiment_engine`;
- deviazioni:
  - `backend/app/services/news_engine.py` (fuori elenco): `_update_signal_news_score` sommava la correzione news a `final_score`, `score` e `signal` a ogni refresh news reale, rompendo `final_score = score` e l'uguaglianza con `features_daily`; ora aggiorna solo la parte informativa (`final_score = score = technical_score`); corretta anche la catena `technical_score or score or 50`, che riportava uno score 0 a 50;
  - 7 test oltre i 5 del piano in `tests/test_lab_signals.py`: refresh news, score 0, analisi tecnica (uguaglianza e `LabError`), migrazione (ricostruzione e `ALTER`), schema nuovo;
  - il `-k "... boundary ..."` del piano non seleziona il test del rilevatore (modulo `test_lab_boundaries`): i file nuovi sono stati eseguiti per intero;
- impatto frontend (non toccato, in attesa di decisione dell'utente): `AnalysisPage` legge `indicators.volatility_annualized_30d` e `indicators.max_drawdown`, ora `volatility_30d` e `max_drawdown_252`, quindi i riquadri "Volatilita" e "Max drawdown" mostrano "N/D"; per un asset REAL corto la pagina mostra "API request failed: 409" (`api.ts` traduce solo i reason code noti); i tipi di `api.ts` non hanno ancora `data_mode`, `signal_data_mode`, `score_unavailable_reason`; nessun crash;
- tempi: sullo stesso PC il seed con lo score v1 è più rapido della base `96f7299` (template 4,0 s contro 5,9 s; i test che eseguono il seed 3,3–5,9 s contro 4,6–8,6 s); una prima esecuzione della suite a 174 s era rumore della macchina (finale 94 s);
- note per i task successivi:
  - Task 10 e 13: rimuovere la propria voce da `PENDING_BOUNDARY` in `tests/test_lab_boundaries.py`;
  - Task 15 (Analisi, badge, marcatore DEMO): adeguare `AnalysisPage` ai nomi `features-v1`, mostrare `score_unavailable_reason`/`message` del 409 e `data_mode`; tipi `api.ts` omologhi ai nuovi campi (anche Task 14);
  - ogni ricalcolo del segnale aggiorna `features_daily` del solo asset (D, W, M) nella serie del segnale;
- minori aperti: una serie REAL con almeno 252 barre ma input NaN (serie piatta) non ha segnale e `score_unavailable_reason` è `None`; `/assets` carica la serie di ogni asset senza segnale per il motivo; l'analisi tecnica ricalcola le feature a ogni richiesta (circa 15 ms per 1500 barre);
- ambiente: `backend/.venv` creato nel worktree con i comandi di AGENTS.md (Python 3.14.7, `pip check` pulito);
- gate: `pytest tests\test_lab_boundaries.py tests\test_lab_signals.py tests\test_lab_feature_store.py tests\test_lab_score.py tests\test_lab_features.py tests\test_lab_series.py tests\test_database.py tests\test_news_providers.py -p no:cacheprovider -W error::RuntimeWarning` = 113 passati, 2 xfail; `pytest tests\test_lab_boundaries.py tests\test_lab_signals.py tests\test_api.py -k "signal or technical or boundar or news or assets or action_board"` = 58 passati, 2 xfail; suite completa `pytest -p no:cacheprovider` = 767 test, 765 passati, 2 xfail (strict), 0 falliti, 0 errori (JUnit XML, 94 s); `ruff check backend scripts tests` verde; `git diff --cached --check` verde; review del diff: nessun rilievo Critical o Important aperto (la regressione score 0 → 50 trovata in review è stata corretta con TDD).

Evidenza Task 8 (2026-10-03, Claude, nella stessa chat del Task 7 su richiesta dell'utente):

- verifica Git iniziale: su richiesta dell'utente `main` portato con fast-forward da `96f7299` a `bcd7179` (Task 7, push del solo SHA verificato come discendente, nessun force); `origin/investedge/sp1-task-7` = `bcd7179`, base del task verificata con il protocollo del piano;
- tabella `lab_jobs` in `BASE_SCHEMA` (colonne e CHECK del piano) con `idx_lab_jobs_status_created` e l'indice univoco parziale `uq_lab_jobs_open` (`QUEUED`/`RUNNING`) in `INDEX_SCHEMA`: migrazione additiva;
- `backend/app/lab/jobs.py`: `JobKind`, `JobStatus`, `JobCancelled`, `JobNotCancellable` (`JOB_NOT_CANCELLABLE`), `JobNotFound` (`JOB_NOT_FOUND`), `JobRecord`, `JobOutcome`, `JobContext` (`set_progress`, `raise_if_cancelled`), `register_job_handler`, `JobService` (`enqueue` con deduplica su `kind` + SHA-256 dei parametri canonici sotto `BEGIN IMMEDIATE`, `get`, `list`, `cancel`, `recover_interrupted`, `start`, `stop`) e `get_job_service()`; un worker FIFO in un thread daemon, una connessione per operazione e transazioni brevi; `LabError` → `FAILED` con codice e messaggio, altre eccezioni → `FAILED` `INTERNAL_ERROR` "Errore interno del job." (testo mai salvato), `JobCancelled` → `CANCELLED`; in modalità `inline` `enqueue` esegue subito il job;
- `backend/app/lab/handlers.py`: `FEATURE_REFRESH` (`FeatureStore.refresh_asset` per asset, `data_mode` richiesto o preferito, `raise_if_cancelled` e avanzamento fra un asset e l'altro, risultato `assets`/`inserted`/`updated`/`deleted`/`unchanged`) e `FX_BACKFILL` (`FXService.backfill_history` per valuta su connessione senza transazione aperta, commit dopo ogni valuta, risultato per valuta);
- `backend/app/api/lab_routes.py`: `GET /lab/jobs?limit=1..100&status=`, `GET /lab/jobs/{job_id}` (404), `POST /lab/jobs/{job_id}/cancel` (409 `JOB_NOT_CANCELLABLE`), `POST /lab/features/refresh` (202), `POST /data/fx/backfill` (202; 409 `REAL_DATA_DISABLED` prima di accodare; 422 per valuta non BCE, data non valida o futura, elenco vuoto o oltre 10); modelli `JobOut`, `FeatureRefreshIn`, `FxBackfillIn` in `backend/app/models/lab.py`, esportati da `backend/app/models/__init__.py`;
- `LAB_JOBS_EXECUTOR` (`thread` di default, `inline` nei test) in `config.py`, `.env.example`, `backend/.env.example` e `CLIENT_ENV` di `tests/conftest.py`; lifespan: dopo `prepare_database` `recover_interrupted()` e `start()`, allo shutdown `stop()`;
- test: gli 8 del piano e 4 test API in `tests/test_lab_jobs.py`; fixture `handlers` che isola il registro degli handler;
- RED verificato: `ImportError` (modulo `backend.app.lab.jobs` assente);
- scelte interpretative:
  - 404 con `{"reason_code": "JOB_NOT_FOUND"}`; 409 con `reason_code` e `message` (come il 409 del Task 7); 422 di valuta e data con messaggio testuale, come la route FX esistente;
  - `enqueue` di un tipo senza handler registrato → `LabError("JOB_KIND_UNAVAILABLE")` senza creare il job;
  - parametri canonici (JSON con chiavi ordinate) per l'hash; `asset_ids` deduplicati e ordinati; valute normalizzate e deduplicate nell'ordine ricevuto;
  - `FEATURE_REFRESH`: asset senza prezzi o inesistenti saltati e non contati (`assets` = asset aggiornati);
  - `FX_BACKFILL`: `ENABLE_REAL_DATA` ricontrollato all'esecuzione (`REAL_DATA_DISABLED`); errore del provider → `FAILED` `FX_BACKFILL_FAILED` con la valuta, le valute già completate restano salvate (rerun idempotente);
  - `recover_interrupted` tocca solo i `RUNNING`: i `QUEUED` restano in coda e il worker li esegue dopo l'avvio; elenco dal più recente; `progress` = 1 e risultato solo per `SUCCEEDED`; un annullamento chiesto a un job che termina senza un altro `raise_if_cancelled` lascia `SUCCEEDED` con `cancel_requested` vero;
  - `get_job_service()` ricrea il servizio se cambia `LAB_JOBS_EXECUTOR` (valore non valido → errore all'avvio); `stop()` attende il worker al più 10 s, un job ancora in corso diventa `INTERRUPTED` al riavvio;
- deviazioni:
  - `tests/test_api.py` (fuori elenco, solo test): i 2 test del lifespan sostituiscono `prepare_database` senza database; con il nuovo lifespan avrebbero aperto un DB non temporaneo, quindi usano un servizio job finto e verificano l'ordine `prepare` → `recover` → `start` → `yield` → `stop` (nessun job avviato se il backup fallisce);
  - 4 test oltre il piano in `tests/test_lab_jobs.py`: ordine FIFO del worker, `JobCancelled` nell'handler, tipo non registrato, schema (indice parziale e CHECK);
  - fix automatico Ruff SIM117 (with annidati) su `jobs.py`;
- note per i task successivi:
  - Task 10–13: registrare gli handler `BACKTEST`, `COMPARE`, `WALK_FORWARD`, `EVIDENCE`, `ML_TRAIN` con `register_job_handler` in un modulo importato da `lab_routes.py` (oggi `handlers.py`); ogni handler apre la propria `get_connection()`, chiama `raise_if_cancelled()` fra un passo e l'altro e usa `LabError` per gli errori attesi; nei test API vale `LAB_JOBS_EXECUTOR=inline`, nei test unitari la fixture `handlers`;
  - Task 14 e 15: polling di `GET /lab/jobs/{id}` e annullamento con `POST /lab/jobs/{id}/cancel`;
- minori aperti: un errore SQLite nella scrittura finale lascia il job `RUNNING` fino al riavvio; in modalità `inline` il job gira nel thread della richiesta (solo test); nessuna pulizia delle righe di `lab_jobs`;
- ambiente: stesso `backend/.venv` del Task 7;
- gate: `pytest tests\test_lab_jobs.py tests\test_lab_boundaries.py tests\test_config.py tests\test_database.py -p no:cacheprovider -W error::RuntimeWarning` = 63 passati, 2 xfail; suite completa `pytest -p no:cacheprovider` = 785 test, 783 passati, 2 xfail (strict, Task 7), 0 falliti, 0 errori (JUnit XML, 110 s); `ruff check backend scripts tests` verde; `git diff --cached --check` verde; review del diff senza rilievi Critical o Important.

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
| 2026-10-02 | Piano SP1 approvato; merge fast-forward su `main` di spec e piano (Task 0) | utente |
| 2026-10-02 | SP1 Task 1 eseguito nella stessa chat del Task 0 (deroga alla regola "nuova chat per task") | utente |
| 2026-10-02 | Guardia di rete dei test: ammesso solo il loopback, necessario all'event loop asyncio di `TestClient` su Windows | Claude, motivata nel Task 1 |
| 2026-10-03 | Merge fast-forward su `main` dei task SP1 su richiesta esplicita dell'utente (`main` = `b76fff5`, Task 0–3, verificato nel Task 5) | utente |
| 2026-10-03 | SP1 Task 6 eseguito nella stessa chat del Task 5 (deroga alla regola "nuova chat per task", solo per il Task 6) | utente |
| 2026-10-03 | `features_daily`: con due barre W/M della stessa `available_at` in segmenti diversi (split a metà periodo) resta quella del segmento successivo; `signal_panel` W/M usa la riga as-of solo se è dello stesso segmento della data | Claude, motivata nel Task 6 |
| 2026-10-03 | Merge fast-forward su `main` dei Task 4–6 su richiesta esplicita dell'utente (`main` = `96f7299`) | utente |
| 2026-10-03 | Score unico nei segnali: l'ultima riga D deve avere `warmup_complete`, senza ripiego su righe o segmenti precedenti; anche il refresh news lascia `final_score = score` (correzione news solo informativa, `news_engine.py` fuori elenco) | Claude, motivata nel Task 7 |
| 2026-10-03 | Adeguamento di `AnalysisPage` ai nomi `features-v1` e al 409 `INSUFFICIENT_REAL_HISTORY` rinviato al Task 15 | utente |
| 2026-10-03 | Merge fast-forward su `main` del Task 7 su richiesta esplicita dell'utente (`main` = `bcd7179`) | utente |
| 2026-10-03 | SP1 Task 8 eseguito nella stessa chat del Task 7 (deroga alla regola "nuova chat per task", solo per il Task 8) | utente |

## Note di ripresa

- Spec e piano SP1 sono in `main` (`53fe614`, fast-forward confermato dall'utente il 2026-10-02); il 2026-10-03, su richiesta dell'utente, `main` è avanzato con fast-forward a `b76fff5` (Task 0–3), poi a `96f7299` (Task 4–6) e a `bcd7179` (Task 7). I task SP1 partono dal branch remoto del task precedente, non da `main`; altri merge su `main` solo su richiesta esplicita dell'utente (al più tardi al gate finale).
- Test: `tests/conftest.py` blocca la rete (solo loopback ammesso) e fornisce la fixture `client` su copia di un DB seed creato una volta per sessione; un test che deve parlare con un provider usa `httpx.MockTransport` o fixture locali.
- I worktree Codex `C:\Users\izzod\.codex\worktrees\f80e` (Task 10) ed `e139` (Task 6) sono superati: non riprendere da lì.
- `backend/.venv` non è versionato: ogni worktree lo crea con i comandi di `AGENTS.md`.
- Test legati al calendario: un test non deve dipendere dalla data reale. Se un servizio legge `datetime.now`, il test blocca l'orologio (vedi `_freeze_service_clock` in `tests/test_market_data_observations.py`).
- Test frontend con orari: fissare il fuso con `vi.stubEnv("TZ", ...)` (il build TypeScript non conosce `process`) e creare gli `Intl.DateTimeFormat` al render, non a livello di modulo.
- `npm audit` dipende da advisory pubblicati dopo l'ultimo task: il gate puo fallire senza modifiche al codice.
- `pytest.ini` imposta gia `addopts = -q`: aggiungere `-q` nasconde la riga di riepilogo; usare `--junitxml` per i conteggi.
- Lo script di secret scan del piano Fase 2 segnala come candidati anche riferimenti a codice (assegnazioni di token calcolati da metodi o letti dalle settings): classificare ogni candidato rispetto alla riga sorgente prima di trattarlo come segreto.
