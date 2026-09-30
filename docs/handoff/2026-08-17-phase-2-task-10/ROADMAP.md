# InvestEdge — roadmap dal checkpoint parziale Task 10

Stato alla data 2026-08-17. Questa roadmap non sostituisce il piano autoritativo `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`; ne registra soltanto il punto di ripartenza.

Legenda: `DONE`, `IN PROGRESS`, `NOT STARTED`, `BLOCKED`.

## P0 — stabilizzare e chiudere correttamente il Task 10

### [ ] P0.1 — Verificare il checkpoint e il perimetro

- Stato: **IN PROGRESS** fino alla verifica del prossimo agente.
- Dipendenze: branch `codex/investedge-phase-2-task-10`; parent atteso `9503e7080d7424ddac8f1ba3234dff06f695d955`.
- File/moduli: repository e tre documenti di handoff.
- Istruzioni:
  - leggere integralmente `AGENTS.md`, `HANDOFF.md`, `ROADMAP.md` e il blocco Task 10 del piano;
  - eseguire `git status --short --branch`, `git log -1 --format=fuller`, `git rev-parse HEAD^`, `git rev-parse '@{u}'` e `git ls-remote --heads origin refs/heads/codex/investedge-phase-2-task-10`;
  - non modificare file se branch, parent o remoto divergono.
- Criterio di accettazione: checkpoint presente sul branch corretto, parent esatto Task 9, working tree spiegabile.
- Test: soli controlli Git read-only.
- Rischi/vincoli: non usare reset, clean, rebase, amend o force-push.

### [ ] P0.2 — Ripetere la review indipendente read-only

- Stato: **NOT STARTED**. La review precedente è stata interrotta senza esito.
- Dipendenze: P0.1.
- File/moduli: i 15 path Task 10 elencati in `HANDOFF.md`.
- Istruzioni:
  - confrontare il checkpoint con `9503e7080d7424ddac8f1ba3234dff06f695d955`;
  - verificare ID-vs-ticker, budget mensile, header/keyless, valuta, UTC/24X7, attribuzione e fallback;
  - approfondire i sei rischi `DA VERIFICARE` di `HANDOFF.md`;
  - classificare finding Critical/Important/Minor con file:riga;
  - non modificare file durante la review.
- Criterio di accettazione: report completo; nessun Critical/Important non classificato.
- Test: eventuali test selettivi fixture-only, senza rete.
- Rischi/vincoli: l'assenza di un report non equivale a review verde.

### [ ] P0.3 — Correggere soltanto Critical/Important confermati

- Stato: **BLOCKED** finché P0.2 non consegna finding.
- Dipendenze: P0.2; skill/processo `receiving-code-review` e TDD.
- File/moduli: soltanto path autorizzati Task 10 coinvolti dal finding.
- Istruzioni:
  - riprodurre ogni finding;
  - aggiungere prima un test RED focalizzato;
  - implementare la correzione minima;
  - richiedere re-review read-only.
- Criterio di accettazione: ogni Critical/Important riprodotto, corretto e protetto da test; re-review senza Critical/Important.
- Test: test mirati del finding.
- Rischi/vincoli: non implementare Minor, refactoring o miglioramenti speculativi senza richiesta.

### [ ] P0.4 — Ripetere i gate Task 10

- Stato: **NOT STARTED** dopo l'handoff.
- Dipendenze: P0.2 e, se necessario, P0.3.
- File/moduli: provider, registry, service e test Task 10.
- Istruzioni:

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_coingecko_provider.py tests\test_provider_budget.py tests\test_market_data_observations.py tests\test_api.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\coingecko.py backend\app\data_providers\provider_registry.py backend\app\services\market_data_service.py tests\test_coingecko_provider.py
git diff --check
```

- Criterio di accettazione: 293 o più test verdi (conteggio può crescere solo per test focalizzati), Ruff verde, diff check verde, zero rete.
- Rischi/vincoli: non sostituire test fixture con chiamate live.

### [ ] P0.5 — Chiarire e completare il gate Git finale del Task 10

- Stato: **BLOCKED** da una discrepanza di processo.
- Dipendenze: P0.4.
- Problema: il piano originale richiedeva un solo commit `feat: add governed CoinGecko crypto data` sopra Task 9; l'interruzione autoritativa ha imposto un commit checkpoint diverso. I due requisiti non possono essere entrambi veri alla lettera senza riscrivere la storia.
- Istruzioni:
  - non fare amend/rebase/reset/force-push senza autorizzazione esplicita;
  - chiedere se il checkpoint supersede il vincolo `count=1` e se è ammesso un commit di completamento aggiuntivo;
  - solo dopo tale chiarimento aggiornare esclusivamente le checkbox del Task 10 effettivamente completate.
- Criterio di accettazione: strategia Git esplicitamente autorizzata, branch/upstream/ref remoto coerenti, Task 10 dichiarato completo soltanto dopo review e gate verdi.
- Test: gate Git read-only e `ls-remote == HEAD` dopo eventuale push.
- Rischi/vincoli: non iniziare Task 11 mentre questo punto è aperto.

## P1 — prosecuzione sequenziale della Fase 2

Tutte le attività seguenti sono **NOT STARTED** e dipendono dalla chiusura del Task 10. Seguire integralmente il relativo blocco del piano; una nuova chat/task per ciascun Task.

### [ ] Task 11 — FX BCE verso EUR e fallback FRED

- Stato: **NOT STARTED**.
- Dipendenze: Task 10 completo e ref remota verificata.
- File/moduli/test: definiti nel piano, righe 1215 e seguenti.
- Criterio di accettazione: quello del blocco Task 11.
- Non eseguire ora: nessuna modifica FX/FRED.

### [ ] Task 12 — Provider e fallback news reali

- Stato: **NOT STARTED**.
- Dipendenze: Task 11 completo.
- Criterio di accettazione/test: blocco Task 12 del piano.
- Non eseguire ora: nessuna modifica news.

### [ ] Task 13 — Refresh lazy, prioritari, deduplicati e limitati

- Stato: **NOT STARTED**.
- Dipendenze: Task 12 completo.
- Criterio di accettazione/test: blocco Task 13 del piano.
- Non eseguire ora: nessuno scheduler o orchestration.

### [ ] Task 14 — API catalogo e conferme versionate

- Stato: **NOT STARTED**.
- Dipendenze: Task 13 completo.
- Criterio di accettazione/test: blocco Task 14 del piano.
- Non eseguire ora: nessuna nuova route catalogo.

### [ ] Task 15 — Catalogo paginato nella pagina Universe

- Stato: **NOT STARTED**.
- Dipendenze: Task 14 completo.
- Criterio di accettazione/test: blocco Task 15 del piano.
- Non eseguire ora: nessuna modifica frontend Universe.

### [ ] Task 16 — API e metriche di copertura dati

- Stato: **NOT STARTED**.
- Dipendenze: Task 15 completo.
- Criterio di accettazione/test: blocco Task 16 del piano.
- Non eseguire ora: nessuna metrica nuova.

### [ ] Task 17 — Copertura, qualità e budget nel Data Center

- Stato: **NOT STARTED**.
- Dipendenze: Task 16 completo.
- Criterio di accettazione/test: blocco Task 17 del piano.
- Non eseguire ora: nessuna modifica frontend Data Center.

### [ ] Task 18 — Audit cumulativo e report Fase 2

- Stato: **NOT STARTED**.
- Dipendenze: Task 17 completo.
- Criterio di accettazione/test: blocco Task 18 del piano.
- Non eseguire ora: nessun audit finale anticipato.

## P2 — miglioramenti non indispensabili

Nessun P2 è autorizzato al momento. Eventuali refactoring, nuove astrazioni, dipendenze, budget più alti, provider aggiuntivi o redesign del Data Center devono essere proposti separatamente dopo la Fase 2.

## DONE verificato

- [x] Catena piano Phase 2 → Task 9 presente e ancestrale.
- [x] Task 10 avviato dalla base esatta Task 9.
- [x] TDD RED registrato.
- [x] Ultimo Step 5: 293 test verdi.
- [x] Ruff prescritto verde.
- [x] Junction `.venv` identificata e Git-ignored.
- [x] Handoff immediato creato senza completare checkbox del piano.
