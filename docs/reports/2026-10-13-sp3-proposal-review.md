# SP3 Task0 — proposta documentale e review

Data: 2026-10-13. Base verificata origin/main e origin/investedge/sp2b-task-12: `12ca2c36a2fc19451e70a08e37514089f3e11bb6`, registro integrazione dopo feature `d182cd547562b933ed1a2c92d4cab78dc8ed1316`. Branch documentale `investedge/sp3-task-0`, pubblicato subito come lock sulla base. Area gestita isolata di questa chat; checkout originale main96f7299 pulito e worktree della chat precedente preservati.

**Stato:** proposta completata, review documentale PASS; spec/piano da approvare prima del codice. [Spec](../superpowers/specs/2026-10-13-investedge-sp3-intraday-strategies-design.md), [piano](../superpowers/plans/2026-10-13-investedge-sp3-intraday-strategies.md), [programma](../../PROGRAMMA-OPERATIVO.md).

## Perimetro e risultati proposti

Quattro soli Markdown: spec, piano, questo report e programma operativo. Nessun codice/configurazione/dipendenza/database modificato; nessun ordine, collector live, paper, credenziale o spesa. Letture del programma completo/spec/piano/report SP2b alla base corrente, contratti/chiamanti SP1/SP2b e fonti primarie pubbliche necessarie.

- Timeline-only bounded, formato finestre/closure v2 compatibile v1, bundle G1 con denominatori immutati, gate prestazioni senza abbassare250ms/60s; RAM proposta≤2GiB. Retention RAM distinta dalle evidenze append-only, nessun purge; eventuale archivio fisico richiede addendum.
- Conversione quote-size e tick attestati as-of, daily da precedenti sedute complete; fonte primaria news con prova locale versionata. UNKNOWN/missing non inventati.
- Due famiglie candidate, TECH_ONLY/TECH_NEWS e NEWS_ONLY condivisa:20config/10policy, holding15/30 dal first_fill, ordini simulati quote successive e preflight ad ogni partial, stop/target/invalidazione/tempo/chiusura e residui irrisolti.
- Fee Alpaca separate da TR, scope/vintage/rounding attestati, slippage/latency/non-fill stress; IS126, OOS252, holdout63 e cinque sedute embargo (446+warm-up), bootstrap congiunto/Bonferroni, trial registry completo e holdout contaminato non promuovibile.
- Task1–12 sequenziali con allowlist/branch/base/commit/test; Task13 addendum dopo SP6a e backlog SP2b. Proposta numerica da approvare, nessun profitto dimostrato.

## Review indipendenti e correzioni documentali

Tre reviewer in sola lettura: compatibilità/contratti, metodologia, costi/fonti/esecuzione. Prima review: nessun Critical; nove Important distinti (alcuni rilevati da più reviewer), chiusi nella bozza corretta. Due re-review indipendenti finali PASS, una estesa al metodo, più controllo root: nessun Critical/Important residuo. Reviewer metodologico dedicato indisponibile per capacità del modello al tentativo di re-review; la verifica metodologica finale è stata completata dal reviewer costi/fonti e dal root. Anche il delta finale benchmark ha re-review PASS.

| Rilievo | Correzione e test pianificato |
|---|---|
| Rischio prima del fill e partial successivi | Preflight al limite/prezzo candidato prima di cash/posizione; residual risk/cash/weight/fee ad ogni partial, stop non allargato; RED Task7. |
| Tick attestato senza artefatto | price-increment-attestation-v1/table/Task3 e rounding avverso; due incrementi, UNKNOWN e revisione futura. |
| Continuità holding potenzialmente futura | Ingresso solo su prove note; futuri GAP non alterano trade/sizing, gate operativo ex-post; Task4/7. |
| Parità policy richiesta prima che esista | Task2 timeline/proiezioni/closure; parità feature/fill/policy ai Task4/7/12. |
| Holdout bypassabile con API dati generiche | Seal dichiarata del workflow SP3; ispezione esterna registrata CONTAMINATED e G2 bloccato, dichiarazione d'integrità necessaria; limite filesystem/API dichiarato, Task9/10. |
| Source news non prova issuer | news-source-attestation-v1 con originali consentiti, authority/tempi/fact binding/ref; assenza UNKNOWN, schemaTask1/importTask5. |
| Sharpe/minimi fuori dal rollingIS | Calcolo limitato alle126sedute IS correnti; prefisso precedente solo stato/warm-up; test scelta prefisso vs finestra Task9. |
| Costi ricorrenti solo nel segno puntuale | Due netti espliciti; lower bound del rendimento giornaliero dopo ricorrenti obbligatorio, flat/cost-only nelle repliche; Task8/10. |
| Premium M&A trasferito all'acquirente | Positivo solo target/class/valuta/unità compatibili; target+acquirer nello stesso articolo, Task5. |

Riferimenti verificati: quote_state_from_rows conserva size_conversion_attested=False; SnapshotService/route snapshot materializzano prefisso; features_daily mutable; lab.trials scarta non-finite/cancel/DEMO. Questi limiti motivano i task, non sono dichiarati risolti da documenti.

## Verifiche del passo documentale

Script stdlib nello scratch della nuova chat, fuori Git: `sp3-document-checks.py <worktree>`;24 controlli su presenza/integrità/link/base/approvazione/G1/prestazioni/quote/daily/feature/regole/ablation/fill/costi/news/registry/split/gate/stress/sequenza/branch/allowlist/sicurezza/prossimo passo. RED prima dei documenti:23 falliti/1 passato, causa prevista spec/piano/report/registro assenti; **GREEN24/24 PASS** dopo correzioni. Controllo allowlist inizialmente vacuo sul piano assente, rafforzato prima del gate. Primo GREEN tentato23/24 per slice dello script che contava13 anziché14 blocchi; corretto il solo checker, nessuna soglia documentale aggirata.

Diff/scope PASS su quattro soli Markdown; UTF-8/link PASS. Secret scan fresco `sp3-secret-scan.ps1 -TaskRoot <worktree>` con pattern/self-test Fase2 JSON/YAML/Bearer/mixed/path: **4 file, self-test PASS,0 candidati inattesi,0 placeholder**. Nessuna sentinella statica introdotta. Controlli ripetuti sui documenti finali prima del commit, `git diff --check` e `git diff --cached --check` richiesti PASS al gate. Test backend/frontend/build non ripetuti per modifiche esclusivamente documentali:1874 backend/162 frontend/build/lint precedenti sono evidenza storica sul codice invariato, non nuovi PASS di SP3.

Fonti primarie Alpaca verificate il 2026-10-13: [tariffario canonico revisionato1ottobre2026](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf), [disclosure](https://alpaca.markets/disclosures), [quote/barre](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data), [paper](https://docs.alpaca.markets/us/docs/paper-trading). Nessun accesso autenticato/dato live; tariffe correnti non certificano applicabilità storica.

## Consegna e stato residuo

Workflow autorizzato: commit sul solo branch Task0, push/gate SHA=HEAD, fetch/ascendenza main e push non forzato fast-forward, ls-remote main=HEAD e worktree pulito. Nessun commit vuoto/rebase/amend/force o spostamento del main locale originale. Lo SHA di questa consegna si registra nel task successivo; esiti remoti verificati dopo commit nella risposta finale e nello scratch, senza anticipare il proprio SHA qui.

**G1_TECH PASS; G1_DATA INSUFFICIENTE; G2 NON VALUTATO.** Limiti SP2b immutati: replay280,178s/query p95 1005,879ms/RAM10,18GiB e nessun manifest REAL verificato. La proposta è la consegna richiesta; codice SP3 parte solo dopo approvazione esplicita spec/piano. Validazione economica REAL/holdout richiede input idonei, costi/authority/risorse e incarico concreto; SP6a richiede G1_DATA READY e G2, reale/leva restano successivi.
