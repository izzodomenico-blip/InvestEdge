# InvestEdge — programma operativo

Fonte unica dello **stato di avanzamento**. Vale per Claude Code e Codex. Regole di lavoro in `AGENTS.md`; decisioni e confini in `docs/superpowers/specs/2026-09-30-investedge-profit-engine-program-design.md`.

Ultimo aggiornamento: 2026-10-01.

## Prossimo passo

**SP2a · Fase 2 · Task 15 — Catalogo paginato nella pagina Universe.**

- Piano: `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`, blocco *Task 15*.
- Branch: `codex/investedge-phase-2-task-15`.
- Base remota: `origin/codex/investedge-phase-2-task-14`.
- Esecuzione: nuova chat con contesto pulito (decisione utente 2026-10-01).
- Vincolo: nessun altro task della Fase 2 prima della chiusura del Task 15.

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
| SP2a | Strumenti e dati di mercato (Fase 2) | IN CORSO | spec 2026-08-16 | `2026-08-16-investedge-phase-2-instruments-and-market-data.md` | `codex/investedge-phase-2-task-18` | a ogni task (dal Task 11) |
| SP1 | Laboratorio di verità | NON INIZIATO | da scrivere | da scrivere | — | no |
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
| 14 | API catalogo e conferme versionate | FATTO | branch `codex/investedge-phase-2-task-14` | 2026-10-01 | Claude |
| 15 | Catalogo paginato nella pagina Universe | NON INIZIATO | — | — | — |
| 16 | API e metriche di copertura dati | NON INIZIATO | — | — | — |
| 17 | Copertura, qualità e budget nel Data Center | NON INIZIATO | — | — | — |
| 18 | Audit cumulativo e report Fase 2 | NON INIZIATO | — | — | — |

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

## Backlog per i sottoprogetti futuri

Raccolto dalla review del 2026-09-30. Ogni voce entra nella spec del proprio SP.

- **SP2a Task 12:** news demo mai incluse in sentiment, `news_score` o feature ML; nessun rinnovo della data di pubblicazione delle news demo.
- **SP1 (efficienza test):** la fixture `client` di `tests/test_api.py` ricrea il seed a ogni test; usare un database di esempio creato una volta e copiato per test.
- **SP1:** pipeline di feature unica e causale (test: il valore alla riga *i* non cambia aggiungendo dati futuri); rimozione di `chikou_span` dai dati di calcolo; score unico per interfaccia, backtest e ML; fill all'apertura della barra successiva; prezzi rettificati per i rendimenti; costi reali (Trade Republic 1 €) e cambio EUR; harness IC, spread per decili e turnover; walk-forward con ottimizzazione in-sample e Sharpe corretto per i tentativi; tabella `features_daily` e job asincroni per backtest e training.
- **SP2b:** fondamentali point-in-time (SEC EDGAR), eventi (utili, revisioni, insider Form 4, 8-K), macro/regime, barre intraday dalla fonte scelta dall'utente, universo IPO (S-1/F-1/424B), snapshot giornalieri dell'universo.
- **SP3:** famiglie tecniche "trend di qualità" e "breakout" per orizzonte; forza relativa; volatilità che si comprime; news classificate per tipo di evento, deduplicate, pesate per fonte e tempo; pesi stimati dai dati.
- **SP4:** feature di training identiche a quelle di previsione; obiettivo di ranking cross-sezionale; purge ed embargo; calibrazione; champion/challenger; verifica ex-post delle previsioni live.
- **SP5:** radar con tasso storico dei profili simili, rischio, condizione di invalidazione; schede IPO con prospetto, management, soci, finanziatori, lock-up.
- **SP6:** portafogli paper multipli, paper broker, profili di rischio a scelta dell'utente, adapter broker ufficiali disattivati, kill switch, runtime sempre acceso, riconciliazione, aggiornamento automatico schedulato.
- **SP7:** Telegram bidirezionale con whitelist chat, codici di conferma e limiti.

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

## Note di ripresa

- I worktree Codex `C:\Users\izzod\.codex\worktrees\f80e` (Task 10) ed `e139` (Task 6) sono superati: non riprendere da lì.
- `backend/.venv` non è versionato: ogni worktree lo crea con i comandi di `AGENTS.md`.
- Test legati al calendario: un test non deve dipendere dalla data reale. Se un servizio legge `datetime.now`, il test blocca l'orologio (vedi `_freeze_service_clock` in `tests/test_market_data_observations.py`).
