# InvestEdge — programma "motore di profitto" (SP0–SP9)

**Stato:** approvato dall'utente il 30 settembre 2026; priorità intraday/Alpaca aggiornata su richiesta dell'utente il 10 ottobre 2026 (§2.1).

**Relazione con la spec precedente:** integra e, dove indicato al §3, supera `docs/superpowers/specs/2026-08-16-investedge-broker-grade-redesign-design.md`. Tutto ciò che il §3 non supera resta valido.

**Esecuzione:** stato e ordine operativo vivono in `PROGRAMMA-OPERATIVO.md`. Ogni sottoprogetto (SP) riceve spec e piano propri prima dell'implementazione; questa spec fissa decisioni, confini e ordine.

## 1. Obiettivo

Cercare profitto con metodo verificabile:

- analisi tecnica migliore, per orizzonte;
- news ed eventi selezionati e classificati;
- previsioni di comportamento con modelli addestrati;
- scoperta di società con potenziale di forte crescita, incluse quelle appena quotate.

Principio guida: **un segnale entra nelle decisioni solo se dimostra capacità predittiva fuori campione e al netto dei costi.** Nessun rendimento è promesso; il sistema misura e rende visibile l'evidenza.

## 2. Decisioni approvate (2026-09-30)

| Area | Decisione |
|---|---|
| Orizzonti | Intraday, settimanale e mensile. Ogni strategia dichiara il proprio orizzonte; si usa quello adatto all'occorrenza. |
| Mercati | Azioni ed ETF USA e UE, crypto, società appena quotate (IPO). |
| Società appena quotate | Analisi di prospetto (S-1/F-1/424B, prospetti UE), profilo professionale pubblico di management, soci e finanziatori, lock-up, uso dei proventi, news a corredo. |
| Budget dati | Lo imposta l'utente. Il sistema supporta fonti gratuite e a pagamento tramite configurazione; nessun agente attiva spese. |
| Profilo di rischio | Scelto dall'utente: Standard o Aggressivo (Prudente resta disponibile). |
| Operatività | Manuale e automatica. |
| Trading reale | Previsto tramite broker con API ufficiale. Disattivato di default; si attiva solo per azione esplicita dell'utente, con doppia conferma, limiti e kill switch. Nessun agente lo attiva. |
| Trade Republic | Solo manuale: non esiste API ufficiale. Gli alert guidano l'esecuzione manuale. Niente scraping né automazione dell'app. |
| Alert | Telegram bidirezionale: notifiche in tempo reale e conferma/rifiuto degli ordini dal telefono, con whitelist della chat e codici di conferma. |
| Agenti | Il programma è eseguibile sia da Claude Code sia da Codex tramite `AGENTS.md` e `PROGRAMMA-OPERATIVO.md`. |
| Git | Push del branch di ogni task; merge su `main` solo fast-forward ai gate di fase verificati. |

### 2.1 Priorità approvata il 2026-10-10

- Prima correggere i problemi riprodotti nella review di SP1 Task 11: causalità della selezione walk-forward, riproducibilità benchmark e contratti frontend. R1–R3 precedono Task 12–16.
- Priorità operativa: holding di **15 o 30 minuti dal fill**, con analisi tecnica e news point-in-time. I timeframe delle feature e gli orizzonti daily di SP1 sono distinti; serve nuova validazione intraday.
- Alpaca è il broker di riferimento per il primo paper tramite Trading API ufficiale, con Market Data/news secondo diritti e budget configurati dall'utente.
- Prima fase: azioni/ETF USA liquidi, sessione regolare, long-only, esposizione entro equity/cassa interna disponibile (massimo 1× compresi ordini pendenti), nessun prestito, short o strumento a leva; niente overnight pianificato. Stop/target e uscita temporale gestiscono fill parziali, halt e mancata esecuzione.
- Due famiglie iniziali: trend/pullback e breakout/continuazione con volume. Tecnica sola, news sole e combinazione confrontate fuori campione; solo i vincitori dei gate entrano nel paper. Nessuna promessa di guadagno.
- Leva prevista come **opzione successiva alla validazione**, con stress dedicato prima in paper, capacità del conto e costi verificati, limiti e attivazione esplicita dell'utente. La pianificazione non attiva account, credenziali, spese o trading reale.

Requisiti delle strategie, dati/news, gate, fonti ufficiali e decisioni residue sono consolidati in `PROGRAMMA-OPERATIVO.md`, sezione *Priorità approvata — intraday 15–30 minuti e Alpaca*. Ogni fase riceve spec e piano prima del codice.

## 3. Sezioni della spec 2026-08-16 superate

| Sezione | Prima | Ora |
|---|---|---|
| §1 Obiettivo | Solo analisi e simulazione | Anche esecuzione reale opzionale, attivata dall'utente |
| §2 Trade Republic / §4.7 | Adapter futuro disabilitato | `TradeRepublicBroker` resta `UNAVAILABLE`; si aggiungono adapter di broker con API ufficiale (Alpaca come riferimento per SP6a; reale opzionale in SP6b) |
| §4.2 Fonti | Solo fonti gratuite | Fonti gratuite e a pagamento, configurate dall'utente |
| §4.5 Intraday | Solo dove la qualità gratuita lo consente | Intraday dove la fonte configurata fornisce dati realtime o delayed dichiarati; mai trattare delayed come realtime |
| §6 Runtime | PC locale | Per intraday e trading reale serve un runtime sempre acceso (scelta hosting in SP6) |
| §12 Fasi | Sei fasi | Sottoprogetti SP0–SP9 (§4) |
| §15 Fuori ambito | Ordini reali, server a pagamento | Ammessi sotto attivazione e budget dell'utente |

Restano fuori ambito senza nuova approvazione: scraping o automazione di Trade Republic, conservazione delle sue credenziali, derivati complessi, promesse di rendimento. La leva rientra solo nella fase opzionale SP6b e nei gate del §2.1; nessun agente la attiva.

## 4. Sottoprogetti e ordine

Percorso prioritario: **SP0 → SP2a → SP1 (correzioni e gate finale) → SP2b (gate dati intraday) → SP3 (gate strategie intraday) → SP6a → completamento SP2b/SP3 → SP4 → SP5 → SP6b → SP7 → SP8 → SP9.**

Le spec SP2b/SP3 separeranno task e gate intraday dal backlog restante. Un gate parziale non chiude l'intero SP; le fasi restano sequenziali. ML e radar non sono prerequisiti del primo paper.

| SP | Titolo | Contenuto | Dipende da |
|---|---|---|---|
| SP0 | Fondamenta | Piano Fase 1 (`2026-08-16-investedge-phase-1-foundations.md`) | — |
| SP2a | Strumenti e dati di mercato | Piano Fase 2 (`2026-08-16-investedge-phase-2-instruments-and-market-data.md`), Task 1–18 | SP0 |
| SP1 | Laboratorio di verità | Pipeline feature unica e causale (multi-timeframe); score unico per live, backtest e ML; backtester onesto (fill alla barra successiva, costi reali, prezzi rettificati, EUR); harness di valutazione segnali (IC, spread decili, turnover); walk-forward vero con Sharpe corretto per i tentativi | SP2a |
| SP2b | Dati per l'alpha | Fondamentali point-in-time (SEC EDGAR e fonti UE), eventi (utili, revisioni, insider, 8-K), macro/regime, barre intraday, universo IPO, snapshot giornalieri dell'universo | SP1 |
| SP3 | Segnali v2 | Prima gate intraday 15/30 minuti: trend/pullback, breakout/volume, news point-in-time e validazione netta; poi altri orizzonti | Gate dati intraday SP2b; completamento restante SP2b per gli altri segnali |
| SP4 | ML v2 | Modelli per orizzonte con obiettivo di ranking cross-sezionale; validazione con purge ed embargo; calibrazione; registro champion/challenger; verifica ex-post delle previsioni live | SP2b/SP3 completati, dopo SP6a nel percorso prioritario |
| SP5 | Radar | Candidati ad alta crescita e società appena quotate, con tasso storico di successo dei profili simili, rischio e condizione di invalidazione | SP4 |
| SP6a | Alpaca paper senza leva | Trading API paper, risk engine 1×, uscita temporale, ordini idempotenti, kill switch, runtime e riconciliazione; track record conservativo | SP1 verificato e gate intraday SP2b/SP3 |
| SP6b | Reale e leva opzionali | Adapter reale disattivato, idoneità e promozione dal paper; eventuale leva prima stressata in paper e poi attivabile solo dall'utente | SP6a validato, SP5 nella sequenza restante, gate rischio/contabilità/operatività |
| SP7 | Telegram bidirezionale | Alert in tempo reale, conferma/rifiuto ordini, whitelist chat, codici di conferma, limiti | SP6a; dopo la valutazione SP6b nella sequenza, anche se reale/leva restano disattivati |
| SP8 | Redesign UI | Calm Intelligence e cinque hub (spec 2026-08-16 §7–§8) | SP7 |
| SP9 | Mobile | Client iOS/Android (spec 2026-08-16 §9) | SP8 |

## 5. Principi trasversali

- **Misurare prima di ottimizzare.** Ogni segnale passa l'harness di SP1 prima di pesare nelle decisioni.
- **Point-in-time.** Nessun dato è usato prima della sua disponibilità reale (data di deposito, orario di pubblicazione, chiusura della barra).
- **Una sola verità.** Stessa pipeline di feature e stesso score per interfaccia, backtest e ML.
- **Fail-closed per gli ordini, fail-soft per la consultazione.**
- **Demo separata dal reale.** Dati seed o demo non influenzano mai score, segnali, ML o portafoglio reale.
- **Costi realistici.** Commissioni del broker scelto (per Trade Republic 1 € fisso), spread, slippage, cambio, tasse italiane.

### 5.1 Gate intraday e Alpaca

- Dataset e replay as-of: barre complete, quote bid/ask, prima ricezione e versioni di barre/news, calendario e universo storico; nessun testo aggiornato retrodatato.
- Regole e parametri dichiarati ex ante; selezione IS, purge/embargo per holding sovrapposti, holdout finale, registro completo dei tentativi e confronti tecnica/news.
- Validazione a 15/30 minuti distinta dalla daily: costi Alpaca e fill realistici, stress di latenza/spread/non-fill, P&L e rischio fuori campione. Sharpe/DSR su rendimenti per seduta; soglie/campione fissati nella spec prima degli esperimenti.
- Primo paper con capitale e limiti rappresentativi; endpoint paper e portafogli separati, kill switch, riconciliazione e protezioni durante disconnessioni. Dati REAL usati in un portafoglio PAPER non sono dati DEMO.
- IEX ha copertura parziale; SIP/delayed e diritti dati dichiarati. Nessun abbonamento acquistato dagli agenti. Cambiare feed richiede nuova verifica.
- Paper Alpaca ha limiti di simulazione; misurare discrepanze rispetto al replay conservativo. Le fonti primarie e i gate dettagliati sono nel programma operativo.

## 6. Attivazione del trading reale

L'attivazione è una decisione dell'utente. Il sistema la rende consapevole:

- mostra il track record paper della strategia e lo scarto rispetto al backtest;
- raccomanda almeno 3–6 mesi di paper coerente con il backtest prima dell'attivazione;
- richiede doppia conferma, limiti per ordine, per giorno e per perdita, e kill switch globale e per portafoglio;
- registra ogni ordine con la versione di strategia e di rischio usata;
- verifica prima idoneità del conto personale, residenza, strumenti e autorizzazioni effettive; disponibilità paper non prova disponibilità live;
- per la leva richiede un gate separato dopo validazione senza leva: stress dei drawdown, costi di finanziamento/margine, buying power corrente e rischio di liquidazione; nessun moltiplicatore fissato dal programma. La sola durata paper o redditività lorda non basta.

## 7. Difetti della review del 2026-09-30 e SP di destinazione

| Difetto | SP |
|---|---|
| Tre formule diverse di score (interfaccia, backtest, ML) | SP1 |
| Fill sulla stessa barra del segnale | SP1 |
| Pesi dello score non calibrati; nessuna misura di capacità predittiva | SP1 |
| Score che penalizza la volatilità (esclude i titoli esplosivi) | SP3 |
| `chikou_span` calcolato con prezzi futuri; test di causalità degli indicatori | SP1 |
| OBV assoluto, drawdown da inizio serie, RSI non Wilder, feature non stazionarie | SP1/SP3 |
| Divergenza tra feature di training e di previsione (peso portafoglio, raccomandazione, news) | SP4 |
| Obiettivo ML "sale sì/no" misurato con accuratezza | SP4 |
| News demo mescolate alle reali e ricaricate con data odierna | SP2a Task 12 |
| Sentiment a parole chiave e peso fisso ±5 | SP3 |
| Assenza di fondamentali ed eventi; universo ristretto | SP2b |
| Backtest su chiusura non rettificata; commissione percentuale invece di 1 € | SP1 |
| Previsioni ML mai verificate ex-post; modello scelto = ultimo | SP4 |
| Aggiornamento automatico dei dati e dei segnali | SP2a Task 13 (refresh) e SP6 (runtime) |
| Endpoint lenti e bloccanti; ricalcolo indicatori a ogni richiesta | SP1 |
