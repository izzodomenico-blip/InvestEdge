# InvestEdge — handoff immediato del Task 10 / Fase 2

Ultimo aggiornamento: 2026-08-17, fuso Europe/Rome.

## 1. Obiettivo originale

Eseguire esclusivamente il Task 10 della Fase 2: integrare prezzi crypto gratuiti e governati tramite CoinGecko, usando un `COINGECKO_ID` attestato e distinto dal ticker. Il lavoro doveva aggiungere EOD e QUOTE EUR/USD, budget conservativi, trasporto senza segreti in URL, backfill curato dei cinque asset legacy, fallback compatibile e attribuzione visibile.

Un'interruzione utente autoritativa ha fermato lo sviluppo prima della review finale. Questo documento e il codice parziale vengono salvati insieme nel checkpoint Git con subject:

```text
chore: checkpoint partial Task 10 and add agent handoff
```

## 2. Stato sintetico

**Task 10: IN PROGRESS.** L'implementazione e i test sono sostanzialmente presenti, ma la review indipendente è stata interrotta prima di consegnare un esito. Le checkbox del Task 10 nel piano restano volutamente non completate. Non considerare questo checkpoint come completamento del Task 10.

Ultimo gate noto sul codice contenuto nel checkpoint:

- Step 5: **293 test verdi**;
- Ruff sul set prescritto: **verde**;
- `git diff --check`: **verde** prima della creazione dei documenti; va riconfermato nel gate del checkpoint;
- review indipendente: **INTERRUPTED / nessun finding consegnato**;
- Task 11–18: **NOT STARTED**.

## 3. Repository, branch, commit e ambiente

- Repository: `C:\Users\izzod\.codex\worktrees\f80e\InvestEdge`
- Branch: `codex/investedge-phase-2-task-10`
- Base e HEAD prima del checkpoint: `9503e7080d7424ddac8f1ba3234dff06f695d955`
- Base remota verificata: `origin/codex/investedge-phase-2-task-9`
- Upstream prima del checkpoint: `origin/codex/investedge-phase-2-task-9`
- Branch remoto Task 10 prima del checkpoint: assente
- Commit checkpoint: il commit che contiene questo file; ricavarlo con `git rev-parse HEAD`
- Parent atteso del checkpoint: `9503e7080d7424ddac8f1ba3234dff06f695d955`
- Python: `3.14.7`
- pytest: `8.4.2`
- Ruff: `0.16.3`
- `core.autocrlf=true`
- Remote: `https://github.com/izzodomenico-blip/InvestEdge.git`

`backend/.venv` non è un file del progetto: è una junction Git-ignored verso `C:\Users\izzod\.codex\worktrees\314e\InvestEdge\backend\.venv`. Non aggiungerla, copiarla o committarla.

## 4. Catena Phase 2 verificata

Ogni commit seguente è presente localmente ed è stato verificato come discendente del precedente:

| Milestone | SHA | Stato |
|---|---|---|
| Piano Phase 2 | `56499829a85b59e7fc96ee668ac77bce7f3226ee` | VERIFIED |
| Task 1 | `d75d8b07dcd1722b052fd2a97f2cb85df384e758` | VERIFIED |
| Task 2 | `ad3e1187f6d520bdf8dbb01d3271d9c0c7984241` | VERIFIED |
| Task 3 | `d39a5ddeabd14d23a6934072f9cb38bacc88aeb0` | VERIFIED |
| Task 4 | `2ca7f5f634afabeb7de50ed008d3d4f9c6513730` | VERIFIED |
| Task 5 | `127d8992555a18860dc76a5b491564aab1d0771b` | VERIFIED |
| Task 6 | `415e87054749fa7e88d6cf8f65816811d35a284d` | VERIFIED |
| Task 7 | `d5599a1d1f5ee8dbc7791c15a9e4f4761db63bf9` | VERIFIED |
| Task 8 | `98de55a151c09953a1437c47f6df8c40a23063be` | VERIFIED |
| Task 9 / base Task 10 | `9503e7080d7424ddac8f1ba3234dff06f695d955` | VERIFIED locale e remoto |
| Task 10 | checkpoint corrente | IN PROGRESS |
| Task 11–18 | — | NOT STARTED |

Non rifare né riscrivere i Task 1–9.

## 5. Fonti di istruzioni già lette

Prima dell'implementazione sono stati letti integralmente:

- `C:\Users\izzod\.codex\AGENTS.md`;
- `docs/superpowers/specs/2026-08-16-investedge-broker-grade-redesign-design.md`;
- `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`;
- `docs/reports/2026-08-16-phase-1-verification.md`;
- `README.md` e i file coinvolti nel percorso di esecuzione.

`AGENTS.md` non è stato modificato: non sono emerse nuove regole stabili valide per l'intero repository. Le informazioni temporanee restano qui e in `ROADMAP.md`.

## 6. Provenienza del working tree

Il branch è stato creato pulito dalla base esatta Task 9. Non risultavano modifiche preesistenti. Tutti i 15 path Task 10 elencati nella tabella sotto sono stati modificati o creati durante questa attività.

Elementi esclusi dal checkpoint:

- `backend/.venv/`: junction ignorata, dipendenza locale, non pertinente;
- segreti e credenziali: nessuno aggiunto;
- file generati/build/cache: nessuno aggiunto;
- `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`: non modificato per lasciare tutte le checkbox del Task 10 non completate;
- `AGENTS.md`: invariato;
- modifiche estranee o di provenienza ignota: nessuna rilevata.

## 7. Architettura e flusso dati coinvolti

Il percorso implementato è:

```text
asset legacy BTC/ETH/...
  -> instrument_listing attivo
  -> instrument_identifier COINGECKO_ID attestato
  -> ProviderRegistry EOD/QUOTE
  -> CoinGeckoProvider
  -> SafeProviderTransport (cache, in-flight, fingerprint, retry, budget)
  -> MarketObservationEnvelope
  -> MarketObservationService (validation, provenance, revision, projection)
  -> price_history / selection event / risposta refresh
```

Componenti principali:

- `InstrumentService.backfill_curated_crypto_ids()`: crea soltanto le identità curate legacy.
- `ProviderRegistry.providers_for()`: risolve capability EOD/QUOTE per listing crypto.
- `CoinGeckoProvider.fetch_daily()` e `fetch_quote()`: chiamano endpoint fissi e producono envelope governati.
- `MarketDataService._refresh_coingecko_data()`: ingest, projection e fallback.
- `MarketDataService._select_coingecko_compatible()`: limita il fallback a CoinGecko e alla valuta del listing.
- `ProviderBudgetManager` esistente: applica finestre minuto/mese e riduzioni upstream.

## 8. Metodologia seguita

- verifica iniziale di branch, base remota, HEAD e albero;
- lettura completa di spec, piano e report Fase 1;
- mapping di schema, caller, registry, transport, budget, validation e API;
- TDD RED → GREEN con fixture esclusivamente locali;
- debug sistematico delle failure prima delle correzioni;
- un solo writer sul codice;
- review indipendente read-only avviata dopo il GREEN, poi interrotta dall'utente;
- nessuna API live, credenziale reale, paid feature, trading reale, PR o merge.

## 9. Invarianti e regole NON TOCCARE

- Nessuna euristica ticker→CoinGecko ID oltre il backfill curato esplicito.
- Non inventare ISIN o MIC per crypto.
- Demo key soltanto nell'header `x-cg-demo-api-key`; keyless senza credenziali.
- Host ed endpoint CoinGecko fissi; nessun URL arbitrario.
- Valute supportate soltanto EUR e USD.
- Nessuna conversione implicita USD→EUR nel provider o nel fallback.
- Fallback soltanto all'ultima observation CoinGecko della stessa valuta/listing; la qualità stale deve restare visibile.
- BAR giornaliere UTC, sessione `24X7`; QUOTE separata da EOD.
- `bypass_cache` controlla soltanto il transport e non salta fingerprint, deduplica in-flight, budget o validation.
- Budget massimi locali: Demo 90/min e 9.000/mese; keyless 10/min e 1.000/mese. Header upstream/429 possono soltanto ridurre.
- Backfill solo `BTC=bitcoin`, `ETH=ethereum`, `SOL=solana`, `BNB=binancecoin`, `XRP=ripple`, con source `LEGACY_CURATED`.
- Test senza rete; fixture sintetiche/locali.
- Non iniziare Task 11 finché Task 10 non è realmente chiuso.

## 10. Decisioni tecniche e motivazioni

1. **Identità separata dal ticker.** Il provider riceve `coingecko_id`; `get_daily_prices(symbol)` non ricrea la vecchia mappa. Questo impedisce associazioni euristiche.
2. **Trasporto governato riusato.** Cache, request fingerprint, in-flight dedupe, retry e budget restano nel `SafeProviderTransport`, evitando un secondo percorso di rete.
3. **Budget dinamico key/keyless.** La policy viene costruita dalla presenza della Demo key e applica cap inferiori ai massimi dichiarati.
4. **Envelope prima della projection.** Il payload CoinGecko entra nel validator condiviso prima di aggiornare `price_history`.
5. **Deduplica locale alla singola risposta.** Per più campioni nello stesso giorno UTC si sceglie l'ultimo timestamp soltanto dentro la risposta corrente.
6. **Backfill idempotente.** Le identità curate sono attestate con `LEGACY_CURATED` e timestamp della migrazione, senza ricerca per nome.
7. **Fallback dedicato.** Il ramo di failure CoinGecko non usa la selezione generica cross-provider/cross-currency.
8. **Attribuzione nel Data Center.** In assenza di un campo dedicato nello schema API corrente, `Powered by CoinGecko API` è esposta nell'elenco `supports` del provider.

## 11. Alternative scartate

- Mappa runtime `BTC -> bitcoin`: scartata perché confonde ticker e identità provider.
- ID derivato dal nome, ISIN o MIC: scartato perché non verificabile e fuori contratto.
- API key in query: scartata per policy secret-in-URL.
- Conversione USD/EUR dentro il provider: scartata perché bypasserebbe il futuro FX service.
- Fallback generico all'observation più recente: scartato perché può cambiare provider o valuta.
- Budget giornaliero legacy: scartato per CoinGecko in favore di minuto/mese.
- Test live: scartati per determinismo, sicurezza e zero rete.

## 12. Lavoro completato nel checkpoint

- fixture CoinGecko sintetiche per market chart, simple price e 429;
- test RED per identità, payload, valuta, header, keyless, cache, in-flight, budget, backfill, registry, API e fallback;
- adapter CoinGecko governato EOD/QUOTE;
- configurazione cache e budget Demo/keyless;
- backfill curato idempotente collegato alla migrazione;
- registry e percorso refresh crypto basati sull'identità esplicita;
- fallback CoinGecko stessa valuta e stale;
- attribuzione Data Center;
- aggiornamenti degli esempi env e README;
- correzione del test API legacy che saturava il vecchio limite giornaliero CoinGecko.

## 13. Lavoro parziale o mancante

- Review indipendente finale: avviata ma interrotta; nessun finding è stato consegnato.
- Eventuali Critical/Important: `UNKNOWN` finché una nuova review non termina.
- Re-review dopo eventuali correzioni: non eseguita.
- Checkbox del Task 10: volutamente ancora `[ ]`.
- Commit finale originariamente previsto `feat: add governed CoinGecko crypto data`: non creato; l'interruzione impone invece il checkpoint parziale.
- Gate finale originale `count=1` con quel subject: non più compatibile alla lettera con il checkpoint obbligatorio. Non riscrivere la storia senza autorizzazione esplicita; trattare il checkpoint come override operativo e chiarire il gate finale prima di chiudere Task 10.

## 14. File modificati

| Percorso | Motivo | Stato | Verifica associata |
|---|---|---|---|
| `.env.example` | Config CoinGecko Demo/keyless, cache e budget | Completo rispetto ai test; review mancante | `git diff --check` |
| `README.md` | Identità esplicita, header, fallback, budget, attribuzione | Completo rispetto ai requisiti noti; review mancante | review documentale |
| `backend/.env.example` | Configurazione locale e limiti | Completo rispetto ai test; review mancante | `git diff --check` |
| `backend/app/config.py` | Nuovi settings cache/budget | Completo rispetto ai test; review mancante | provider/budget/API suite |
| `backend/app/data_providers/coingecko.py` | Provider governato EOD/QUOTE | Completo rispetto ai test; review mancante | `tests/test_coingecko_provider.py`, Ruff |
| `backend/app/data_providers/provider_registry.py` | Capability crypto e identità | Parziale: review P0 richiesta | test registry, Ruff |
| `backend/app/database.py` | Invocazione backfill in migrazione | Completo rispetto ai test; review transazione mancante | test backfill/API |
| `backend/app/services/instrument_service.py` | Backfill curato idempotente | Parziale: review P0 richiesta | test backfill |
| `backend/app/services/market_data_service.py` | Refresh, ingest e fallback CoinGecko | Parziale: review P0 richiesta | test service/fallback, Ruff |
| `tests/fixtures/market_data/coingecko_market_chart.json` | Fixture EOD | Completo | provider suite |
| `tests/fixtures/market_data/coingecko_simple_price.json` | Fixture QUOTE | Completo | provider suite |
| `tests/fixtures/market_data/coingecko_rate_limit.json` | Fixture 429 | Completo | provider suite |
| `tests/test_coingecko_provider.py` | Matrice TDD Task 10 | Completo rispetto ai casi scritti; review copertura mancante | 19 test verdi, Ruff |
| `tests/test_provider_budget.py` | Budget minuto/mese CoinGecko | Completo rispetto ai casi scritti | 59 test nel modulo verdi |
| `tests/test_api.py` | Compatibilità symbol/API, attribuzione, seed e budget | Completo rispetto ai casi scritti | 154 test nel modulo verdi |
| `HANDOFF.md` | Stato e passaggio consegne | Completo | review manuale + diff check |
| `ROADMAP.md` | Priorità residue | Completo | review manuale + diff check |
| `NEXT_AGENT_PROMPT.md` | Prompt operativo per il prossimo agente | Completo | review manuale + diff check |

Il piano Phase 2 è autorizzato per il Task 10 ma non è stato modificato, per ordine esplicito di non completare le checkbox.

## 15. Test e verifiche eseguite

### Baseline

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_provider_budget.py tests\test_market_data_observations.py tests\test_api.py -q
```

Esito: exit code 0. Conteggio non conservato nell'output disponibile; warning preesistenti Starlette/joblib.

### RED iniziale

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_coingecko_provider.py tests\test_provider_budget.py tests\test_api.py -k "coingecko or crypto_identity or crypto_budget" -q
```

Esito iniziale atteso: **23 failed, 1 passed**. Cause: adapter/registry/metodi/policy/config/backfill non ancora implementati.

### GREEN mirato

Stesso comando del RED dopo l'implementazione.

Esito: **24 passed**, exit code 0, circa 10 secondi.

### Step 5 completo finale

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_coingecko_provider.py tests\test_provider_budget.py tests\test_market_data_observations.py tests\test_api.py -q
```

Esito finale dopo la correzione del guard budget API: **293 passed**, exit code 0, circa 9 minuti e 30 secondi. Conteggio raccolto separatamente: API 154, CoinGecko 19, market observations 61, provider budget 59. Warning non bloccanti e preesistenti: Starlette TestClient, 936 warning joblib/NumPy, una costante FastAPI deprecata.

### Ruff

```powershell
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\coingecko.py backend\app\data_providers\provider_registry.py backend\app\services\market_data_service.py tests\test_coingecko_provider.py
```

Esito: `All checks passed!`, exit code 0, meno di un secondo.

### Diff

```powershell
git diff --check
```

Esito prima dei documenti di handoff: exit code 0. Va eseguito una sola volta sul diff finale prima del commit checkpoint.

La lunga suite da 293 test non deve essere rilanciata durante questo handoff.

## 16. Failure incontrate e risolte

1. Primo GREEN: 3 failure.
   - Il 429 keyless con `remaining=0` riduceva subito il budget: il test è stato allineato al comportamento conservativo (un solo invio fisico, cooldown attivo).
   - Due test fallback osservavano una selezione generica successiva da provider/valuta incompatibili: nel ramo di failure CoinGecko è stata evitata la valutazione qualità generica.
2. Ruff: due import inutilizzati nel nuovo test; rimossi.
3. Primo Step 5 completo: `test_api_rate_limit_guard` usava `daily_limit=0` del nuovo provider e non bloccava. Il test ora satura la finestra mensile governata e verifica `RateLimitExceeded` senza rete.

Tutte le correzioni sopra sono incluse nell'ultimo Step 5 verde.

## 17. Rischi e assunzioni da verificare in review

Questi punti **non sono finding consegnati dal reviewer**; sono controlli P0 suggeriti e restano da confermare:

1. `ProviderRegistry.providers_for()` valuta prima i `provider_symbols` verificati. Verificare che una riga crypto con valore ticker non possa aggirare l'obbligo di un `COINGECKO_ID` attestato.
2. `InstrumentService.backfill_curated_crypto_ids()` esegue `continue` se l'attestazione esiste. Verificare l'idempotenza anche quando la timezone legacy è vuota ma l'attestazione è già presente.
3. Sul refresh CoinGecko riuscito, `_assess_quality()` resta generico. Verificare che non registri in seguito una selection cross-provider/cross-currency in presenza di dati anomali già memorizzati.
4. Il parser usa `prices` e `total_volumes`; verificare se il requisito “array disallineati” debba includere anche `market_caps`, benché non sia proiettato.
5. `CoinGeckoProvider.api_key_configured()` restituisce `True` anche in keyless per preservare la semantica operativa legacy. Verificare se il Data Center debba invece distinguere esplicitamente Demo key assente da provider disponibile.
6. L'attribuzione è inserita in `supports` perché il modello API non ha un campo dedicato. Verificare che questa rappresentazione sia accettabile lato Data Center.

Rischio di processo: la review interrotta non ha prodotto un verdetto. Non assumere che l'assenza di finding consegnati equivalga a review verde.

## 18. Dipendenze e configurazione

- Usare la junction locale `backend/.venv` già presente oppure creare un ambiente equivalente senza commetterlo.
- Test e sviluppo devono restare offline/fixture-first.
- `ENABLE_REAL_DATA=false` resta il default.
- Una Demo key reale, se usata manualmente fuori dai test, va in `COINGECKO_API_KEY` e viene inviata solo via header.
- Nessuna credenziale è necessaria per completare review e test.

## 19. Punto esatto da cui riprendere

Riprendere dal checkpoint corrente di `codex/investedge-phase-2-task-10`. Verificare che il suo parent sia `9503e7080d7424ddac8f1ba3234dff06f695d955`, leggere integralmente `AGENTS.md`, questo file e `ROADMAP.md`, quindi eseguire una nuova review indipendente read-only del diff Task 10. Non riaprire l'analisi dei Task 1–9.

Primi tre passi:

1. Fotografare `git status`, `git log -1`, parent, upstream e ref remoto; fermarsi se divergono da questo handoff.
2. Completare la review P0 sui punti elencati e classificare finding Critical/Important/Minor con file e riga.
3. Applicare soltanto Critical/Important confermati con TDD, ripetere Step 5/Ruff/diff check, poi chiarire il gate commit-count prima di marcare il Task 10 completo.
