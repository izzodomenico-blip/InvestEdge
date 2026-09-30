# InvestEdge — istruzioni per agenti (Claude Code e Codex)

Questo file vale per ogni agente che lavora nel repository. Claude Code lo carica tramite `CLAUDE.md`; Codex lo legge direttamente.

## 1. Prima di qualsiasi modifica

1. Leggi integralmente `PROGRAMMA-OPERATIVO.md`: è la fonte unica di stato, ordine dei lavori e prossimo passo.
2. Leggi la spec del programma `docs/superpowers/specs/2026-09-30-investedge-profit-engine-program-design.md`, poi spec e piano del sottoprogetto (SP) indicato come attivo.
3. Controlla Git: `git fetch origin`, `git status --short`, branch corrente e base remota del task (colonna *Branch* del registro).
4. Se lo stato Git o il registro divergono da quanto scritto, fermati e chiedi all'utente. Non correggere la storia.

## 2. Regole di lavoro

- Comunica in italiano.
- I task sono **sequenziali**: esegui solo il primo task NON INIZIATO del SP attivo con tutte le dipendenze FATTE. Un task IN CORSO appartiene all'owner indicato nel registro.
- Un solo writer per task. Reviewer e analisi sono read-only.
- TDD obbligatorio: test RED che fallisce per il motivo previsto, implementazione minima, GREEN, poi review del diff.
- Test **offline**: solo fixture locali o sintetiche. Nessuna chiamata live nei test.
- Modifiche chirurgiche: tocca solo i file autorizzati dal task. Segnala il resto, non cambiarlo.
- Non dichiarare un task FATTO senza output di test/lint freschi.

## 3. Sicurezza (inderogabile)

- Nessun segreto (token, API key, password, chat id) in git, URL, query string, log, eccezioni, fixture, report, risposte API o messaggi Telegram.
- Gli agenti **non inseriscono credenziali** e **non attivano il trading reale**. Il trading reale è disattivato di default e si attiva solo per azione esplicita dell'utente.
- Nessuno scraping o automazione dell'app/web Trade Republic. Trade Republic resta solo manuale.
- Nessuna spesa: provider a pagamento solo se l'utente li configura.
- Dati demo/seed mai mescolati con dati reali nei calcoli di score, segnali, ML o portafoglio reale.

## 4. Git

- Branch per task come indicato nel piano del SP. Piani nuovi: `investedge/spN-task-M`.
- Un commit per task con il messaggio indicato nel piano, più eventuali commit di checkpoint documentati nel registro.
- Push del solo branch del task: `git push -u origin HEAD`. Poi gate remoto: `git ls-remote origin refs/heads/<branch>` deve coincidere con `HEAD`.
- Merge su `main` **solo fast-forward**, ai gate di fase verificati (autorizzazione utente del 2026-09-30).
- Vietati: force-push, rebase/amend di commit già pubblicati, reset distruttivi, cancellazione di branch remoti, `npm audit fix --force`.
- Lock di presa in carico: pubblicare subito il branch del task (anche senza commit) segnala che il task è preso.

## 5. Chiusura di un task

Nello stesso commit del task:

1. spunta le checkbox del task nel piano del SP;
2. aggiorna la riga del task in `PROGRAMMA-OPERATIVO.md`: stato FATTO, data, evidenza (comando e numero di test verdi);
3. aggiorna la sezione *Prossimo passo*.

Un commit non può contenere il proprio SHA: lo registra il task successivo (o il commit di merge del SP).

Se il lavoro viene interrotto: commit `chore: checkpoint <task> ...` con la sezione *Note di ripresa* del registro aggiornata, e push. Mai lasciare lavoro solo in locale.

## 6. Ambiente e comandi (Windows, PowerShell)

```powershell
py -3.14 -m venv backend\.venv
& '.\backend\.venv\Scripts\python.exe' -m pip install -r backend\requirements-dev.txt
& '.\backend\.venv\Scripts\python.exe' -m pytest -q
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend scripts tests
cd frontend; npm ci; npm run build
```

`backend/.venv`, database/log/backup/modelli sotto `data/`, `.env`, `frontend/node_modules` e `frontend/dist` sono ignorati da Git: non vanno mai committati. Non aprire né modificare il database reale dell'utente (`data/investedge.db`) durante test o smoke: usa `INVESTEDGE_DB_PATH` su file temporanei.
