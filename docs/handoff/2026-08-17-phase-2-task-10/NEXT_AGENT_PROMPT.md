# Prompt pronto per il prossimo coding agent

Copia integralmente il testo seguente nel prossimo agente:

---

Lavora nel repository InvestEdge esclusivamente per riprendere e chiudere il **Task 10 della Fase 2**, attualmente **IN PROGRESS**. Non iniziare Task 11–18.

## Letture obbligatorie prima di agire

Leggi integralmente, in quest'ordine:

1. `C:\Users\izzod\.codex\AGENTS.md` applicabile al worktree;
2. `HANDOFF.md`;
3. `ROADMAP.md`;
4. `docs/superpowers/specs/2026-08-16-investedge-broker-grade-redesign-design.md`;
5. il blocco Task 10 in `docs/superpowers/plans/2026-08-16-investedge-phase-2-instruments-and-market-data.md`;
6. `docs/reports/2026-08-16-phase-1-verification.md`.

Non modificare file prima di aver completato le letture e verificato lo stato Git.

## Stato di partenza atteso

- Repository: `C:\Users\izzod\.codex\worktrees\f80e\InvestEdge`
- Branch: `codex/investedge-phase-2-task-10`
- Commit di partenza: checkpoint corrente con subject `chore: checkpoint partial Task 10 and add agent handoff`; risolvi lo SHA con `git rev-parse HEAD`.
- Parent/base atteso: `9503e7080d7424ddac8f1ba3234dff06f695d955`.
- Base remota originaria: `origin/codex/investedge-phase-2-task-9`.
- Task 10: IN PROGRESS.
- Task 11–18: NOT STARTED.
- Ultimo gate noto: 293 test verdi, Ruff verde, `git diff --check` verde prima del checkpoint.
- Review indipendente precedente: interrotta senza report e senza finding consegnati.

Verifica subito:

```powershell
Get-Location
git branch --show-current
git log -1 --format=fuller
git rev-parse HEAD^
git status --short --branch
git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
git ls-remote --heads origin refs/heads/codex/investedge-phase-2-task-10
```

Se branch, parent, working tree o ref remota divergono sostanzialmente da `HANDOFF.md`, fermati e chiedi chiarimenti. Non usare reset, clean, rebase, amend o force-push per “correggere” la discrepanza.

## Catena da preservare

- Piano Phase 2: `56499829a85b59e7fc96ee668ac77bce7f3226ee`
- Task 1: `d75d8b07dcd1722b052fd2a97f2cb85df384e758`
- Task 2: `ad3e1187f6d520bdf8dbb01d3271d9c0c7984241`
- Task 3: `d39a5ddeabd14d23a6934072f9cb38bacc88aeb0`
- Task 4: `2ca7f5f634afabeb7de50ed008d3d4f9c6513730`
- Task 5: `127d8992555a18860dc76a5b491564aab1d0771b`
- Task 6: `415e87054749fa7e88d6cf8f65816811d35a284d`
- Task 7: `d5599a1d1f5ee8dbc7791c15a9e4f4761db63bf9`
- Task 8: `98de55a151c09953a1437c47f6df8c40a23063be`
- Task 9/base: `9503e7080d7424ddac8f1ba3234dff06f695d955`

Non rifare, riscrivere o re-analizzare i Task 1–9 salvo una verifica read-only strettamente necessaria.

## Obiettivo

Completare la review e il gate del Task 10: CoinGecko governato con `COINGECKO_ID` esplicito, EOD/QUOTE EUR/USD, Demo key solo header, keyless senza credenziali, UTC/24X7, budget minuto/mese, backfill curato, fallback stessa valuta/provider e attribuzione.

## Primo intervento concreto

Parti dalla prima attività P0 non completata in `ROADMAP.md`: esegui una **review indipendente read-only** del diff tra il checkpoint e la base Task 9. Non modificare file durante la review. Classifica Critical/Important/Minor con file:riga e verifica in particolare i sei rischi elencati nella sezione 17 di `HANDOFF.md`.

Se esistono Critical/Important:

1. applica `receiving-code-review` e verifica tecnicamente il finding;
2. scrivi prima un test RED focalizzato;
3. implementa la correzione minima soltanto nei path Task 10;
4. esegui il test mirato e richiedi re-review.

Non implementare Minor o refactoring non richiesti.

## Vincoli inderogabili

- Identità CoinGecko distinta dal ticker; nessuna euristica, ISIN o MIC inventata.
- Demo key soltanto in `x-cg-demo-api-key`; keyless senza secret.
- Nessuna API live, credenziale reale, paid feature o test di rete.
- Nessuna conversione USD→EUR implicita.
- Budget massimo Demo 90/min e 9.000/mese; keyless 10/min e 1.000/mese; upstream può solo ridurre.
- Writer unico; reviewer read-only.
- Modifiche piccole, chirurgiche e verificabili.
- Non modificare aree dichiarate intoccabili in `HANDOFF.md`.
- Non creare PR, merge, main, trading reale, scheduler o Task successivi.
- Non aggiornare checkbox fuori dal Task 10.
- Non committare `backend/.venv`, segreti, cache, build o file generati.
- Non riscrivere la storia Git senza autorizzazione esplicita.

## Gate di test dopo eventuali correzioni

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_coingecko_provider.py tests\test_provider_budget.py tests\test_market_data_observations.py tests\test_api.py -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend\app\data_providers\coingecko.py backend\app\data_providers\provider_registry.py backend\app\services\market_data_service.py tests\test_coingecko_provider.py
git diff --check
```

Criterio minimo: almeno 293 test verdi, Ruff verde, diff check verde, review/re-review senza Critical/Important, zero rete.

## Discrepanza Git da chiarire

Il piano originale richiedeva un solo commit finale `feat: add governed CoinGecko crypto data` sopra Task 9. L'interruzione ha imposto il checkpoint `chore: checkpoint partial Task 10 and add agent handoff`. Non tentare di soddisfare entrambi con amend/rebase/reset/force-push. Chiedi un'istruzione esplicita sulla strategia finale prima di dichiarare Task 10 completo o aggiornare tutte le sue checkbox.

## Disciplina di handoff

- Conferma che il repository corrisponda allo stato descritto.
- Non rifare il lavoro già completato.
- Dopo ogni milestone aggiorna `HANDOFF.md` e `ROADMAP.md` con evidenze, comandi e risultati.
- Fermati e chiedi chiarimenti per discrepanze sostanziali o nuove autorizzazioni necessarie.
- Solo dopo la chiusura verificata del Task 10 si potrà aprire una nuova attività separata per Task 11.

---
