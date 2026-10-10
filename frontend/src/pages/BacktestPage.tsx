import { useEffect, useMemo, useRef, useState } from "react";
import { GitCompareArrows, RotateCcw, ShieldCheck, Trash2, Trophy } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  apiDelete,
  apiGet,
  apiPost,
  apiReasonCode,
  getLabSignals,
  type BacktestCostProfile,
  type DataMode,
  type SignalTimeframe,
  type Asset,
  type BacktestCompareInput,
  type BacktestCompareResult,
  type BacktestResult,
  type BacktestRunInput,
  type BacktestStrategy,
  type BacktestSummary,
  type JobOut,
  type RebalanceFrequency,
  type WalkForwardInput,
  type WalkForwardResult,
} from "../lib/api";
import { cancelJob, getBacktestJobResult, getInlineJobResult, waitForJob } from "../lib/jobs";
import { formatPercent } from "../lib/format";
import { Activity, BarChart3, BadgeDollarSign, Receipt, ShieldAlert } from "lucide-react";

type BacktestMode = "single" | "compare" | "walkforward";

const compareSeriesColors = ["#22D3EE", "#A78BFA", "#34D399"];
const benchmarkColor = "#94A3B8";

const jobLabels: Record<JobOut["status"], string> = {
  QUEUED: "Accodato", RUNNING: "In esecuzione", SUCCEEDED: "Completato",
  FAILED: "Non riuscito", CANCELLED: "Annullato", INTERRUPTED: "Interrotto",
};

function formatBacktestCurrency(value: number, engineVersion: string) {
  if (engineVersion === "v1") return new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
  return value.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) +
    " (unita legacy)";
}

function optionalNumber(value: number | null) {
  return value === null ? "N/D" : value.toFixed(2);
}


const errorGuides: Record<string, string> = {
  LAB_NO_REAL_SERIES: "Carica dati reali per gli asset selezionati, oppure scegli DEMO per una simulazione separata.",
  LAB_PERIOD_TOO_SHORT: "Estendi il periodo o riduci le finestre IS/OOS, includendo lo storico necessario al warm-up.",
};

type ExecutionCostsProps = {
  title: string;
  metrics: Pick<BacktestSummary, "commission_eur" | "spread_cost_eur" | "turnover" | "exposure">;
  engineVersion?: string;
  dataMode: DataMode | null;
  signalName?: string | null;
  signalTimeframe?: SignalTimeframe | null;
  costProfile?: BacktestCostProfile | null;
  warnings: string[];
  excluded: Record<string, string>;
};

function ExecutionCosts({ title, metrics, engineVersion = "v1", dataMode, signalName,
  signalTimeframe, costProfile, warnings, excluded }: ExecutionCostsProps) {
  const money = (value: number | null) => value === null ? "N/D" : formatBacktestCurrency(value, engineVersion);
  return (
    <Panel title={title}>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className={dataMode === "DEMO" ? "font-semibold text-amber-200" : "text-slate-300"}>
          {dataMode === "DEMO" ? "DEMO · simulazione" : dataMode === "REAL" ? "REAL · dati reali" : "motore precedente"}
        </span>
        {signalName && <span className="text-slate-300">{signalName} · {signalTimeframe ?? "N/D"}</span>}
      </div>
      {engineVersion === "v1" ? (
        <>
          <p className="mt-3 text-sm text-slate-300">Esecuzione all'apertura della barra successiva</p>
          <p className="mt-1 text-sm text-slate-400">Commissioni e spread/slippage sono già inclusi nei rendimenti, prima delle imposte stimate.</p>
          <dl className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2">
            {[["Commissioni eseguite", money(metrics.commission_eur)],
              ["Spread / slippage eseguito", money(metrics.spread_cost_eur)],
              ["Turnover", metrics.turnover === null ? "N/D" : metrics.turnover.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "×"],
              ["Esposizione media", metrics.exposure === null ? "N/D" : formatPercent(metrics.exposure * 100)]].map(([label, value]) => (
              <div key={label}><dt className="text-sm text-slate-400">{label}</dt><dd className="num mt-1 text-white">{value}</dd></div>
            ))}
          </dl>
          <p className="mt-3 text-sm text-slate-400">Turnover = valore scambiato / equity media; esposizione = quota media investita.</p>
          {costProfile && (
            <p className="mt-3 text-sm text-slate-300">
              Profilo salvato: {money(costProfile.commission_eur)} per ordine; azioni/ETF {costProfile.cost_bps_equity} bps,
              crypto {costProfile.cost_bps_crypto} bps per lato; minimo {money(costProfile.min_trade_eur)};
              azioni/ETF {costProfile.fractional_shares ? "frazionari" : "a quote intere"}.
            </p>
          )}
        </>
      ) : <p className="mt-3 text-sm text-slate-400">Costi per voce non registrati dal motore precedente.</p>}
      {warnings.length > 0 && (
        <div className="mt-4"><h3 className="font-medium text-amber-200">Avvisi</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-200">{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
        </div>
      )}
      {Object.keys(excluded).length > 0 && (
        <div className="mt-4"><h3 className="font-medium text-slate-200">Asset esclusi</h3>
          <dl className="mt-2 space-y-2 text-sm">{Object.entries(excluded).map(([symbol, reason]) => (
            <div key={symbol} className="flex flex-wrap gap-x-3"><dt className="font-semibold text-white">{symbol}</dt><dd className="break-all text-slate-300">{reason}</dd></div>
          ))}</dl>
        </div>
      )}
    </Panel>
  );
}

type FormState = {
  name: string;
  strategy_name: BacktestStrategy;
  symbols: string[];
  initial_cash: string;
  start_date: string;
  end_date: string;
  benchmark_symbol: string;
  buy_threshold: string;
  sell_threshold: string;
  max_asset_weight: string;
  stop_loss_percent: string;
  take_profit_percent: string;
  rebalance_frequency: RebalanceFrequency;
  top_n: string;
  data_mode: DataMode;
  signal_name: string;
  signal_timeframe: SignalTimeframe;
  commission_eur: string;
  cost_bps_equity: string;
  cost_bps_crypto: string;
  min_trade_eur: string;
  fractional_shares: "" | "true" | "false";
};

const defaultForm: FormState = {
  name: "Backtest score weekly",
  strategy_name: "SCORE_THRESHOLD",
  symbols: ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
  initial_cash: "100000",
  start_date: "2025-01-01",
  end_date: "2026-05-15",
  benchmark_symbol: "SPY",
  buy_threshold: "70",
  sell_threshold: "40",
  max_asset_weight: "0.15",
  stop_loss_percent: "8",
  take_profit_percent: "25",
  rebalance_frequency: "WEEKLY",
  top_n: "5",
  data_mode: "REAL",
  signal_name: "score",
  signal_timeframe: "D",
  commission_eur: "",
  cost_bps_equity: "",
  cost_bps_crypto: "",
  min_trade_eur: "",
  fractional_shares: "",
};

const strategyLabels: Record<BacktestStrategy, string> = {
  SCORE_THRESHOLD: "Score threshold",
  BUY_AND_HOLD: "Buy and hold",
  TOP_N_SCORE: "Top N score",
};

function metricTone(value: number) {
  return value >= 0 ? "green" : "rose";
}

function numberOrNull(value: string) {
  if (value.trim() === "") {
    return null;
  }
  return Number(value);
}

export function BacktestPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [signals, setSignals] = useState<string[]>([]);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [history, setHistory] = useState<BacktestSummary[]>([]);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [form, setForm] = useState<FormState>(defaultForm);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<BacktestMode>("single");
  const [compareStrategies, setCompareStrategies] = useState<BacktestStrategy[]>([
    "SCORE_THRESHOLD",
    "BUY_AND_HOLD",
    "TOP_N_SCORE",
  ]);
  const [compareResult, setCompareResult] = useState<BacktestCompareResult | null>(null);
  const [comparing, setComparing] = useState(false);
  const [isSessions, setIsSessions] = useState("504");
  const [oosSessions, setOosSessions] = useState("126");
  const [job, setJob] = useState<JobOut | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const operationController = useRef<AbortController | null>(null);
  const [walkResult, setWalkResult] = useState<WalkForwardResult | null>(null);
  const [walking, setWalking] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<BacktestSummary | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const backtestOperationInFlight = useRef(false);
  const resultRequestId = useRef(0);

  const normalizedDeleteName = deleteTarget?.name.trim().replace(/\s+/g, " ") ?? "";
  const deleteConfirmationToken = deleteTarget?.id
    ? normalizedDeleteName ? `${normalizedDeleteName} #${deleteTarget.id}` : `#${deleteTarget.id}`
    : "";

  async function loadData(signal: AbortSignal) {
    setLoading(true);
    setError(null);
    setErrorCode(null);
    try {
      const [assetData, historyData, signalData] = await Promise.all([
        apiGet<Asset[]>("/assets", { signal }),
        apiGet<BacktestSummary[]>("/backtests", { signal }),
        getLabSignals(signal).catch((err: unknown) => {
          signal.throwIfAborted();
          setCatalogError(err instanceof Error ? err.message : "Catalogo segnali non disponibile. Ricarica la pagina.");
          return [];
        }),
      ]);
      signal.throwIfAborted();
      setSignals(signalData);
      if (signalData.length === 0) setCatalogError((current) => current ?? "Catalogo segnali vuoto. Ricarica la pagina.");
      setAssets(assetData);
      setHistory(historyData);
      if (historyData[0]?.id) {
        const previous = await apiGet<BacktestResult>("/backtests/" + historyData[0].id, { signal });
        signal.throwIfAborted();
        setResult(previous);
      }
    } catch (err) {
      if (!signal.aborted) {
        setError(err instanceof Error ? err.message : "Errore durante il caricamento dei backtest.");
      }
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadData(controller.signal);
    return () => {
      controller.abort();
      operationController.current?.abort();
    };
  }, []);

  const selectedAssetSet = useMemo(() => new Set(form.symbols), [form.symbols]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function toggleSymbol(symbol: string) {
    setForm((current) => {
      const active = new Set(current.symbols);
      if (active.has(symbol)) {
        active.delete(symbol);
      } else {
        active.add(symbol);
      }
      return { ...current, symbols: Array.from(active) };
    });
  }

  function validate(): string | null {
    if (!signals.includes(form.signal_name)) return "Seleziona un segnale disponibile nel catalogo.";
    for (const [value, max] of [[form.commission_eur, 100], [form.cost_bps_equity, 1000],
      [form.cost_bps_crypto, 1000], [form.min_trade_eur, 1000000]] as const) {
      if (value.trim() !== "" && (!Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > max)) {
        return "Profilo costi non valido: rispetta i limiti dei campi o lascia il valore vuoto per il default.";
      }
    }
    if (!form.name.trim()) {
      return "Inserisci un nome backtest.";
    }
    if (form.symbols.length === 0) {
      return "Seleziona almeno un asset.";
    }
    if (!form.start_date || !form.end_date || form.end_date < form.start_date) {
      return "Intervallo date non valido.";
    }
    if (Number(form.initial_cash) <= 0) {
      return "Il capitale iniziale deve essere positivo.";
    }
    if (Number(form.max_asset_weight) <= 0 || Number(form.max_asset_weight) > 1) {
      return "Il peso massimo deve essere tra 0 e 1.";
    }
    return null;
  }

  async function runOperation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (backtestOperationInFlight.current) return;
    setError(null);
    setErrorCode(null);
    const validation = validate();
    if (validation) {
      setError(validation);
      return;
    }
    if (mode === "compare" && compareStrategies.length < 2) {
      setError("Seleziona almeno due strategie da confrontare.");
      return;
    }
    if (mode === "walkforward" && (
      !Number.isInteger(Number(isSessions)) || Number(isSessions) < 2 || Number(isSessions) > 10000 ||
      !Number.isInteger(Number(oosSessions)) || Number(oosSessions) < 1 || Number(oosSessions) > 10000
    )) {
      setError("Finestre non valide: IS da 2 a 10000 sedute, OOS da 1 a 10000.");
      return;
    }
    backtestOperationInFlight.current = true;
    resultRequestId.current += 1;
    const controller = new AbortController();
    operationController.current = controller;
    const signal = controller.signal;
    setHistoryBusy(true);
    setRunning(mode === "single");
    setComparing(mode === "compare");
    setWalking(mode === "walkforward");
    setJob(null);
    setCancelling(false);
    if (mode === "single") setResult(null);
    if (mode === "compare") setCompareResult(null);
    if (mode === "walkforward") setWalkResult(null);
    const input: BacktestRunInput = {
      data_mode: form.data_mode, signal_name: form.signal_name, signal_timeframe: form.signal_timeframe,
      commission_eur: numberOrNull(form.commission_eur), cost_bps_equity: numberOrNull(form.cost_bps_equity),
      cost_bps_crypto: numberOrNull(form.cost_bps_crypto), min_trade_eur: numberOrNull(form.min_trade_eur),
      fractional_shares: form.fractional_shares === "" ? null : form.fractional_shares === "true",
      name: form.name, strategy_name: form.strategy_name, symbols: form.symbols,
      initial_cash: Number(form.initial_cash), start_date: form.start_date, end_date: form.end_date,
      benchmark_symbol: form.benchmark_symbol, buy_threshold: Number(form.buy_threshold),
      sell_threshold: Number(form.sell_threshold), max_asset_weight: Number(form.max_asset_weight),
      stop_loss_percent: numberOrNull(form.stop_loss_percent),
      take_profit_percent: numberOrNull(form.take_profit_percent),
      rebalance_frequency: form.rebalance_frequency,
      top_n: (mode === "compare" ? compareStrategies.includes("TOP_N_SCORE") : form.strategy_name === "TOP_N_SCORE")
        ? Number(form.top_n) : undefined,
    };
    const { strategy_name: _strategy, ...settings } = input;
    const payload: BacktestRunInput | BacktestCompareInput | WalkForwardInput = mode === "compare"
      ? { ...settings, strategy_names: compareStrategies }
      : mode === "walkforward"
        ? { ...input, is_sessions: Number(isSessions), oos_sessions: Number(oosSessions) }
        : input;
    const path = mode === "single" ? "/backtests/run" : mode === "compare"
      ? "/backtests/compare" : "/backtests/walk-forward";
    const kind = mode === "single" ? "BACKTEST" : mode === "compare" ? "COMPARE" : "WALK_FORWARD";
    try {
      const initial = await apiPost<JobOut>(path, payload, { signal });
      if (initial.kind !== kind) throw new Error("Tipo di elaborazione inatteso.");
      const completed = await waitForJob(initial, { signal, onUpdate: setJob });
      if (mode === "single") {
        setResult(await getBacktestJobResult(completed, signal));
        setHistory(await apiGet<BacktestSummary[]>("/backtests", { signal }));
      } else if (mode === "compare") {
        const next = getInlineJobResult<BacktestCompareResult>(completed);
        if (!Array.isArray(next.entries)) throw new Error("Risultato del confronto non disponibile.");
        setCompareResult(next);
      } else {
        const next = getInlineJobResult<WalkForwardResult>(completed);
        if (!Array.isArray(next.windows) || !next.oos_metrics) throw new Error("Risultato walk-forward non disponibile.");
        setWalkResult(next);
      }
    } catch (err) {
      if (!signal.aborted) {
        setError(err instanceof Error ? err.message : "Errore durante l'elaborazione.");
        setErrorCode(apiReasonCode(err));
      }
    } finally {
      backtestOperationInFlight.current = false;
      if (!signal.aborted) {
        setHistoryBusy(false);
        setRunning(false);
        setComparing(false);
        setWalking(false);
        setCancelling(false);
      }
      if (operationController.current === controller) operationController.current = null;
    }
  }

  async function requestCancellation() {
    const controller = operationController.current;
    if (!controller || !job || cancelling) return;
    setCancelling(true);
    try {
      const next = await cancelJob(job.id, controller.signal);
      if (!controller.signal.aborted && operationController.current === controller) setJob(next);
    } catch (err) {
      if (!controller.signal.aborted && operationController.current === controller) {
        setCancelling(false);
        setError(err instanceof Error ? err.message : "Annullamento non riuscito.");
      }
    }
  }

  async function loadRunResult(id: number) {
    if (backtestOperationInFlight.current) {
      return;
    }
    backtestOperationInFlight.current = true;
    setHistoryBusy(true);
    setError(null);
    setErrorCode(null);
    const requestId = ++resultRequestId.current;
    try {
      const nextResult = await apiGet<BacktestResult>(`/backtests/${id}`);
      if (requestId === resultRequestId.current) {
        setResult(nextResult);
      }
    } catch (err) {
      if (requestId === resultRequestId.current) {
        setError(err instanceof Error ? err.message : "Errore caricamento backtest.");
      }
    } finally {
      backtestOperationInFlight.current = false;
      setHistoryBusy(false);
    }
  }

  async function deleteRun(target: BacktestSummary) {
    if (!target.id || backtestOperationInFlight.current) {
      return;
    }
    backtestOperationInFlight.current = true;
    resultRequestId.current += 1;
    setHistoryBusy(true);
    setDeleting(true);
    setError(null);
    setErrorCode(null);
    try {
      await apiDelete(`/backtests/${target.id}?confirmation=${encodeURIComponent(deleteConfirmation)}`);
      setHistory((current) => current.filter((item) => item.id !== target.id));
      setResult((current) => current?.backtest_id === target.id ? null : current);
      setDeleteTarget((current) => current?.id === target.id ? null : current);
      setDeleteConfirmation("");
      try {
        setHistory(await apiGet<BacktestSummary[]>("/backtests"));
      } catch (err) {
        const detail = err instanceof Error ? err.message : "refresh non riuscito";
        setError(`Backtest cancellato, ma l'elenco non è stato aggiornato: ${detail}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante la cancellazione del backtest.");
    } finally {
      backtestOperationInFlight.current = false;
      setHistoryBusy(false);
      setDeleting(false);
    }
  }

  function toggleCompareStrategy(strategy: BacktestStrategy) {
    setCompareStrategies((current) =>
      current.includes(strategy)
        ? current.filter((item) => item !== strategy)
        : [...current, strategy],
    );
  }

  const compareChartData = useMemo(() => {
    if (!compareResult) {
      return [];
    }
    const byDate = new Map<string, Record<string, number | string>>();
    for (const entry of compareResult.entries) {
      for (const point of entry.equity_curve) {
        const row = byDate.get(point.date) ?? { date: point.date };
        row[entry.label] = point.portfolio_value;
        if (point.benchmark_value != null) {
          row.benchmark = point.benchmark_value;
        }
        byDate.set(point.date, row);
      }
    }
    return Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  }, [compareResult]);

  if (loading) {
    return (
      <Panel title="Backtest">
        <div className="h-56 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  if (assets.length === 0) {
    return (
      <Panel title="Database non inizializzato">
        <p className="text-slate-300">Database non inizializzato.</p>
        <p className="mt-2 text-sm text-slate-500">Esegui `backend\.venv\Scripts\python.exe scripts\seed_database.py --reset` e ricarica.</p>
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Strategie simulate"
        index="07"
        title="Backtest"
        subtitle="Valuta strategie sui dati locali con segnali condivisi, costi di esecuzione in EUR e risultati fuori campione."
        actions={
          <div className="inline-flex rounded-lg border border-slate-800/80 bg-slate-950/60 p-1">
            <button
              type="button"
              onClick={() => setMode("single")}
              disabled={historyBusy}
              className={`inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                mode === "single"
                  ? "bg-cyan-400/15 text-cyan-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Singolo
            </button>
            <button
              type="button"
              onClick={() => setMode("compare")}
              disabled={historyBusy}
              className={`inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                mode === "compare"
                  ? "bg-violet-400/15 text-violet-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <GitCompareArrows className="h-4 w-4" aria-hidden="true" />
              Confronto
            </button>
            <button
              type="button"
              onClick={() => setMode("walkforward")}
              disabled={historyBusy}
              className={`inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                mode === "walkforward"
                  ? "bg-emerald-400/15 text-emerald-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              Robustezza
            </button>
          </div>
        }
      />

      {(error || catalogError) && <div role="alert" className="space-y-2 rounded-lg border border-rose-300/20 bg-rose-400/10 p-4 text-sm text-rose-200">
        {error && <p>{error}</p>}
        {errorCode && errorGuides[errorCode] && <p>{errorGuides[errorCode]}</p>}
        {catalogError && <p>{catalogError} Ricarica la pagina per riprovare il catalogo.</p>}
      </div>}

      {job && (running || comparing || walking) && (
        <Panel title="Elaborazione">
          <div role="status" aria-live="polite" className="space-y-3">
            <p>{jobLabels[job.status]} · {Math.round(Math.max(0, Math.min(1, job.progress)) * 100)}%</p>
            <progress aria-label="Avanzamento elaborazione" value={job.progress} max={1} className="w-full" />
            {(cancelling || job.cancel_requested) && <p>Annullamento richiesto: attendo la conferma.</p>}
          </div>
          <button type="button" onClick={() => void requestCancellation()}
            disabled={cancelling || job.cancel_requested || (job.status !== "QUEUED" && job.status !== "RUNNING")}
            className="mt-3 rounded-md border border-slate-700 px-3 py-2 text-sm disabled:opacity-50">
            Annulla elaborazione
          </button>
        </Panel>
      )}

      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.35fr)]">
        <Panel title="Configurazione">
          <form
            onSubmit={(event) => void runOperation(event)}
            className="space-y-4"
          >
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Nome backtest</span>
              <input value={form.name} onChange={(event) => updateField("name", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
            </label>

            {mode === "compare" ? (
              <div className="space-y-2">
                <span className="text-sm text-slate-400">Strategie da confrontare</span>
                <div className="grid gap-2 rounded-md border border-slate-800 bg-slate-900/40 p-3 sm:grid-cols-3">
                  {Object.entries(strategyLabels).map(([value, label]) => (
                    <label key={value} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-300 hover:bg-slate-800/70">
                      <input
                        type="checkbox"
                        checked={compareStrategies.includes(value as BacktestStrategy)}
                        onChange={() => toggleCompareStrategy(value as BacktestStrategy)}
                        className="h-4 w-4 accent-violet-300"
                      />
                      <span className="text-white">{label}</span>
                    </label>
                  ))}
                </div>
                <label className="block space-y-2">
                  <span className="text-sm text-slate-400">Benchmark</span>
                  <select value={form.benchmark_symbol} onChange={(event) => updateField("benchmark_symbol", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                    {assets.map((asset) => (
                      <option key={asset.symbol} value={asset.symbol}>
                        {asset.symbol}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-2">
                  <span className="text-sm text-slate-400">Strategia</span>
                  <select value={form.strategy_name} onChange={(event) => updateField("strategy_name", event.target.value as BacktestStrategy)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                    {Object.entries(strategyLabels).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-2">
                  <span className="text-sm text-slate-400">Benchmark</span>
                  <select value={form.benchmark_symbol} onChange={(event) => updateField("benchmark_symbol", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                    {assets.map((asset) => (
                      <option key={asset.symbol} value={asset.symbol}>
                        {asset.symbol}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}

            <div>
              <p className="mb-2 text-sm text-slate-400">Asset</p>
              <div className="grid max-h-56 gap-2 overflow-y-auto rounded-md border border-slate-800 bg-slate-900/40 p-3 sm:grid-cols-2">
                {assets.map((asset) => (
                  <label key={asset.symbol} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-300 hover:bg-slate-800/70">
                    <input type="checkbox" checked={selectedAssetSet.has(asset.symbol)} onChange={() => toggleSymbol(asset.symbol)} className="h-4 w-4 accent-cyan-300" />
                    <span className="font-semibold text-white">{asset.symbol}</span>
                    <span className="truncate text-slate-500">{asset.asset_type}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Capitale iniziale</span>
                <input type="number" value={form.initial_cash} onChange={(event) => updateField("initial_cash", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Frequenza</span>
                <select value={form.rebalance_frequency} onChange={(event) => updateField("rebalance_frequency", event.target.value as RebalanceFrequency)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                  <option value="DAILY">DAILY</option>
                  <option value="WEEKLY">WEEKLY</option>
                  <option value="MONTHLY">MONTHLY</option>
                </select>
              </label>
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Data inizio</span>
                <input type="date" value={form.start_date} onChange={(event) => updateField("start_date", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Data fine</span>
                <input type="date" value={form.end_date} onChange={(event) => updateField("end_date", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Soglia BUY</span>
                <input type="number" value={form.buy_threshold} onChange={(event) => updateField("buy_threshold", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Soglia SELL</span>
                <input type="number" value={form.sell_threshold} onChange={(event) => updateField("sell_threshold", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Peso max asset</span>
                <input type="number" step="0.01" value={form.max_asset_weight} onChange={(event) => updateField("max_asset_weight", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>

              <label className="space-y-2">
                <span className="text-sm text-slate-400">Stop loss %</span>
                <input type="number" value={form.stop_loss_percent} onChange={(event) => updateField("stop_loss_percent", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Take profit %</span>
                <input type="number" value={form.take_profit_percent} onChange={(event) => updateField("take_profit_percent", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              {(mode === "compare" ? compareStrategies.includes("TOP_N_SCORE") : form.strategy_name === "TOP_N_SCORE") && (
                <label className="space-y-2">
                  <span className="text-sm text-slate-400">Top N</span>
                  <input type="number" min="1" value={form.top_n} onChange={(event) => updateField("top_n", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
                </label>
              )}
              {mode === "walkforward" && (
                <>
                  <label className="space-y-2">
                    <span className="text-sm text-slate-400">Finestra IS (sedute)</span>
                    <input type="number" min="2" max="10000" value={isSessions} onChange={(event) => setIsSessions(event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm text-slate-400">Finestra OOS (sedute)</span>
                    <input type="number" min="1" max="10000" value={oosSessions} onChange={(event) => setOosSessions(event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
                  </label>
                </>
              )}
            </div>


            <fieldset disabled={historyBusy} className="space-y-4">
              <legend className="mb-3 font-medium text-slate-200">Dati e segnale</legend>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-2">
                  <span className="text-sm text-slate-400">Modalità dati</span>
                  <select value={form.data_mode} onChange={(event) => updateField("data_mode", event.target.value as DataMode)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white">
                    <option value="REAL">REAL · dati reali</option><option value="DEMO">DEMO · simulazione</option>
                  </select>
                </label>
                <label className="space-y-2">
                  <span className="text-sm text-slate-400">Segnale</span>
                  <select value={form.signal_name} disabled={signals.length === 0} onChange={(event) => updateField("signal_name", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white disabled:opacity-60">
                    {signals.length === 0 && <option value="">Catalogo indisponibile</option>}
                    {signals.map((signalName) => <option key={signalName} value={signalName}>{signalName}</option>)}
                  </select>
                </label>
                <label className="space-y-2">
                  <span className="text-sm text-slate-400">Timeframe del segnale</span>
                  <select value={form.signal_timeframe} onChange={(event) => updateField("signal_timeframe", event.target.value as SignalTimeframe)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white">
                    <option value="D">D · giornaliero</option><option value="W">W · settimanale</option><option value="M">M · mensile</option>
                  </select>
                </label>
              </div>
              <p className="text-sm text-slate-400">REAL e DEMO restano separati. D/W/M descrivono il segnale; frequenza e finestre si riferiscono alle sedute.</p>
            </fieldset>
            <fieldset disabled={historyBusy} className="space-y-4">
              <legend className="mb-3 font-medium text-slate-200">Costi Trade Republic</legend>
              <p className="text-sm text-slate-400">Lascia vuoti i valori per usare le impostazioni configurate. Zero disattiva quel costo. 1 bps = 0,01%; spread e slippage si applicano a ogni lato.</p>
              <div className="grid gap-4 sm:grid-cols-2">
                {([["commission_eur", "Commissione per ordine (€)", 100],
                  ["cost_bps_equity", "Costo azioni / ETF (bps per lato)", 1000],
                  ["cost_bps_crypto", "Costo crypto (bps per lato)", 1000],
                  ["min_trade_eur", "Ordine minimo (€)", 1000000]] as const).map(([key, label, max]) => (
                  <label key={key} className="space-y-2">
                    <span className="text-sm text-slate-400">{label}</span>
                    <input type="number" min="0" max={max} step="any" value={form[key]} onChange={(event) => updateField(key, event.target.value)} placeholder="Default configurato" className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white" />
                  </label>
                ))}
                <label className="space-y-2">
                  <span className="text-sm text-slate-400">Quote azioni / ETF</span>
                  <select value={form.fractional_shares} onChange={(event) => updateField("fractional_shares", event.target.value as FormState["fractional_shares"])} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white">
                    <option value="">Default configurato</option><option value="false">Quote intere</option><option value="true">Quote frazionarie</option>
                  </select>
                </label>
              </div>
              <p className="text-sm text-slate-400">Le crypto ammettono sempre quote frazionarie. Il profilo effettivo viene salvato nel risultato.</p>
            </fieldset>

            {mode === "compare" ? (
              <button disabled={comparing || historyBusy || signals.length === 0} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-violet-300/30 bg-violet-400/15 px-4 py-2.5 text-sm font-semibold text-violet-100 transition hover:bg-violet-400/25 disabled:opacity-60">
                <GitCompareArrows className={`h-4 w-4 ${comparing ? "animate-pulse" : ""}`} aria-hidden="true" />
                {comparing ? "Confronto in corso..." : "Confronta strategie"}
              </button>
            ) : mode === "walkforward" ? (
              <button disabled={walking || historyBusy || signals.length === 0} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-emerald-300/30 bg-emerald-400/15 px-4 py-2.5 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-400/25 disabled:opacity-60">
                <ShieldCheck className={`h-4 w-4 ${walking ? "animate-pulse" : ""}`} aria-hidden="true" />
                {walking ? "Validazione in corso..." : "Valida robustezza"}
              </button>
            ) : (
              <button disabled={running || historyBusy || signals.length === 0} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20 disabled:opacity-60">
                <RotateCcw className={`h-4 w-4 ${running ? "animate-spin" : ""}`} aria-hidden="true" />
                {running ? "Esecuzione..." : "Esegui backtest"}
              </button>
            )}
          </form>
        </Panel>

        <div className="min-w-0 space-y-6">
          {mode === "compare" ? (
            compareResult ? (
              <>
                <Panel
                  eyebrow={`Confronto · ${compareResult.entries.length} strategie`}
                  title="Classifica strategie"
                  action={
                    <span className="inline-flex items-center gap-2 rounded-md border border-violet-300/30 bg-violet-400/10 px-3 py-1.5 text-xs font-semibold text-violet-100">
                      <Trophy className="h-3.5 w-3.5" aria-hidden="true" />
                      {strategyLabels[compareResult.best_strategy as BacktestStrategy] ?? compareResult.best_strategy}
                    </span>
                  }
                >
                  <div className="overflow-x-auto">
                    <p className="mb-4 text-sm text-slate-300">Confronto senza correzione per i tentativi: per l'evidenza usa il walk-forward</p>
                    <table className="w-full min-w-[640px] border-collapse">
                      <thead>
                        <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                          <th className="px-3 pb-3 pl-0 font-medium">#</th>
                          <th className="px-3 pb-3 font-medium">Strategia</th>
                          <th className="px-3 pb-3 text-right font-medium">Return</th>
                          <th className="px-3 pb-3 text-right font-medium">CAGR</th>
                          <th className="px-3 pb-3 text-right font-medium">Drawdown</th>
                          <th className="px-3 pb-3 text-right font-medium">Sharpe</th>
                          <th className="px-3 pb-3 text-right font-medium">Alpha</th>
                          <th className="px-3 pb-3 pr-0 text-right font-medium">Trade</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/80">
                        {[...compareResult.entries]
                          .sort((a, b) => a.rank - b.rank)
                          .map((entry, index) => (
                            <tr key={entry.strategy_name} className="text-sm">
                              <td className="px-3 py-3 pl-0">
                                <span
                                  className="inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold"
                                  style={{
                                    color: compareSeriesColors[index % compareSeriesColors.length],
                                    background: `${compareSeriesColors[index % compareSeriesColors.length]}1a`,
                                  }}
                                >
                                  {entry.rank}
                                </span>
                              </td>
                              <td className="px-3 py-3 font-semibold text-white">{entry.label}</td>
                              <td className={entry.summary.total_return_percent >= 0 ? "px-3 py-3 text-right font-semibold text-emerald-300" : "px-3 py-3 text-right font-semibold text-rose-300"}>{formatPercent(entry.summary.total_return_percent)}</td>
                              <td className="px-3 py-3 text-right text-slate-300">{formatPercent(entry.summary.cagr)}</td>
                              <td className="px-3 py-3 text-right text-rose-300">{formatPercent(entry.summary.max_drawdown)}</td>
                              <td className="px-3 py-3 text-right text-slate-300">{entry.summary.sharpe_ratio.toFixed(2)}</td>
                              <td className={entry.summary.alpha_vs_benchmark >= 0 ? "px-3 py-3 text-right font-semibold text-emerald-300" : "px-3 py-3 text-right font-semibold text-rose-300"}>{entry.summary.benchmark_snapshot_status === "UNAVAILABLE" ? "N/D" : formatPercent(entry.summary.alpha_vs_benchmark)}</td>
                              <td className="px-3 py-3 pr-0 text-right text-slate-300">{entry.summary.total_trades}</td>
                            </tr>
                          ))}
                        <tr className="text-sm">
                          <td className="px-3 py-3 pl-0">
                            <span className="inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold text-slate-400" style={{ background: `${benchmarkColor}1a` }}>
                              ~
                            </span>
                          </td>
                          <td className="px-3 py-3 font-semibold text-slate-400">Benchmark ({compareResult.benchmark_symbol ?? "N/D"})</td>
                          <td className="px-3 py-3 text-right text-slate-400">{compareResult.entries.every((entry) => entry.summary.benchmark_snapshot_status === "UNAVAILABLE") ? "N/D" : formatPercent(compareResult.benchmark_return_percent)}</td>
                          <td className="px-3 py-3 text-right text-slate-600">-</td>
                          <td className="px-3 py-3 text-right text-slate-600">-</td>
                          <td className="px-3 py-3 text-right text-slate-600">-</td>
                          <td className="px-3 py-3 text-right text-slate-600">-</td>
                          <td className="px-3 py-3 pr-0 text-right text-slate-600">-</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </Panel>

                {compareResult.entries.map((entry) => (
                  <ExecutionCosts key={entry.strategy_name} title={"Costi ed esclusioni · " + entry.label}
                    metrics={entry.summary} engineVersion={entry.summary.engine_version} dataMode={entry.summary.data_mode}
                    signalName={entry.summary.signal_name} signalTimeframe={entry.summary.signal_timeframe}
                    costProfile={entry.summary.cost_profile} warnings={entry.summary.warnings} excluded={entry.summary.excluded} />
                ))}
                <Panel eyebrow="Equity curve sovrapposte" title="Andamento confronto">
                  <div className="h-96">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={compareChartData} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                        <CartesianGrid stroke="#1E293B" vertical={false} />
                        <XAxis dataKey="date" stroke="#64748B" axisLine={false} tickLine={false} minTickGap={40} />
                        <YAxis stroke="#64748B" axisLine={false} tickLine={false} width={80} />
                        <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => formatBacktestCurrency(Number(value), "v1")} />
                        <Legend wrapperStyle={{ fontSize: "12px" }} />
                        {compareResult.entries.map((entry, index) => (
                          <Line
                            key={entry.strategy_name}
                            type="monotone"
                            dataKey={entry.label}
                            stroke={compareSeriesColors[index % compareSeriesColors.length]}
                            strokeWidth={2.5}
                            dot={false}
                          />
                        ))}
                        <Line type="monotone" dataKey="benchmark" name={`Benchmark ${compareResult.benchmark_symbol ?? ""}`} stroke={benchmarkColor} strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>
              </>
            ) : (
              <Panel title="Confronto strategie">
                <p className="text-sm text-slate-400">Seleziona almeno due strategie e premi "Confronta strategie" per vedere metriche affiancate e equity curve sovrapposte.</p>
              </Panel>
            )
          ) : mode === "walkforward" ? (
            walkResult ? (
              <>
                <Panel title="Risultati fuori campione" eyebrow={walkResult.data_mode + " · " + walkResult.oos_sessions + " sedute OOS"}>
                  <div className="grid gap-4 sm:grid-cols-2 [&_.number-xl]:text-2xl [&_.number-xl]:whitespace-normal [&_.number-xl]:break-words [&_.eyebrow-muted]:whitespace-normal">
                    <MetricCard label="Rendimento OOS" value={formatPercent(walkResult.oos_metrics.total_return_percent)} delta="Rendimento netto" tone={metricTone(walkResult.oos_metrics.total_return_percent)} icon={Activity} />
                    <MetricCard label="Max drawdown OOS" value={formatPercent(walkResult.oos_metrics.max_drawdown)} delta="Serie OOS continua" tone="rose" icon={ShieldAlert} />
                    <MetricCard label="Valore finale OOS" value={formatBacktestCurrency(walkResult.oos_metrics.final_value, "v1")} delta="Valore finale" tone="cyan" icon={BadgeDollarSign} />
                  </div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                    {[["Sharpe IS medio", optionalNumber(walkResult.is_sharpe_mean)],
                      ["Sharpe OOS", optionalNumber(walkResult.oos_sharpe)],
                      ["Degrado IS − OOS", optionalNumber(walkResult.degradation)],
                      ["DSR", walkResult.dsr === null ? "N/D" : (walkResult.dsr.dsr * 100).toFixed(1) + "%"],
                      ["N configurazioni", walkResult.n_trials ?? "N/D"]].map(([label, value]) => (
                      <div key={label} className="rounded-lg border border-slate-800 p-3">
                        <p className="text-xs text-slate-400">{label}</p><p className="mt-1 font-semibold">{value}</p>
                      </div>
                    ))}
                  </div>
                  <p className="mt-4 text-sm text-slate-400">
                    Finestre: {walkResult.window_is_sessions} sedute IS / {walkResult.window_oos_sessions} OOS.
                    Sharpe annualizzati; DSR e N non disponibili per i run DEMO.
                  </p>
                  <p className="mt-2 text-sm text-slate-400">N conta le configurazioni distinte già provate nella famiglia segnale/timeframe, non le finestre. DSR è una probabilità corretta per i tentativi.</p>
                </Panel>
                <ExecutionCosts title="Costi ed esclusioni OOS" metrics={walkResult.oos_metrics}
                  dataMode={walkResult.data_mode} warnings={walkResult.warnings} excluded={walkResult.excluded} />
                <Panel title="Finestre walk-forward">
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[620px]">
                      <thead><tr className="text-left text-xs text-slate-400">
                        <th>Finestra</th><th>In-sample</th><th>Fuori campione</th><th>Parametri scelti</th><th>Sharpe IS</th>
                      </tr></thead>
                      <tbody>{walkResult.windows.map((window) => (
                        <tr key={window.index} className="border-t border-slate-800 text-sm">
                          <td className="py-3">{window.index + 1}</td>
                          <td>{window.is_start} → {window.is_end}</td>
                          <td>{window.oos_start} → {window.oos_end}</td>
                          <td>{window.chosen.name}; buy {window.chosen.buy_threshold} / sell {window.chosen.sell_threshold}; Top N {window.chosen.top_n}; peso max {formatPercent(window.chosen.max_asset_weight * 100)}; {window.chosen.rebalance_frequency}</td>
                          <td>{optionalNumber(window.is_sharpe)}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>
                </Panel>
              </>
            ) : (
              <Panel title="Validazione robustezza">
                <p className="text-sm text-slate-400">
                  Scegli strategia e finestre in sedute, poi premi "Valida robustezza". I parametri vengono scelti
                  in-sample e applicati alla finestra successiva; il portafoglio prosegue in un'unica simulazione fuori campione.
                </p>
              </Panel>
            )
          ) : result ? (
            <>
              {result.summary.engine_version !== "v1" && (
                <p className="text-sm text-amber-200">
                  Run storico v0: unita monetaria non dichiarata; importi salvati senza conversione.
                </p>
              )}
              <div className="grid gap-4 sm:grid-cols-2 [&_.number-xl]:text-2xl [&_.number-xl]:whitespace-normal [&_.number-xl]:break-words [&_.eyebrow-muted]:whitespace-normal">
                <MetricCard label="Rendimento" value={formatPercent(result.summary.total_return_percent)} delta="Totale periodo" tone={metricTone(result.summary.total_return_percent)} icon={Activity} />
                <MetricCard label="CAGR" value={formatPercent(result.summary.cagr)} delta="Annualizzato" tone={metricTone(result.summary.cagr)} icon={BarChart3} />
                <MetricCard label="Max drawdown" value={formatPercent(result.summary.max_drawdown)} delta="Peggior discesa" tone="rose" icon={ShieldAlert} />
                <MetricCard label="Valore finale" value={formatBacktestCurrency(result.summary.final_value, result.summary.engine_version)} delta={`${result.summary.total_trades} trade`} tone="cyan" icon={BadgeDollarSign} />
              </div>

              <div className="grid gap-4 sm:grid-cols-2 [&_.number-xl]:text-2xl [&_.number-xl]:whitespace-normal [&_.number-xl]:break-words [&_.eyebrow-muted]:whitespace-normal">
                <MetricCard label="Sharpe" value={result.summary.sharpe_ratio.toFixed(2)} delta="Rischio/rendimento" tone="cyan" icon={BarChart3} />
                <MetricCard label="Win rate" value={formatPercent(result.summary.win_rate)} delta="Trade SELL vincenti" tone="green" icon={Activity} />
                <MetricCard label="Profit factor" value={result.summary.profit_factor.toFixed(2)} delta="Profitti / perdite" tone="amber" icon={BarChart3} />
                <MetricCard label="Alpha benchmark" value={result.summary.benchmark_snapshot_status === "UNAVAILABLE" ? "N/D" : formatPercent(result.benchmark_comparison.alpha_vs_benchmark)} delta={result.benchmark_comparison.benchmark_symbol ?? "Benchmark"} tone={metricTone(result.benchmark_comparison.alpha_vs_benchmark)} icon={Activity} />
              </div>

              <ExecutionCosts title="Costi ed esclusioni" metrics={result.summary}
                engineVersion={result.summary.engine_version} dataMode={result.summary.data_mode}
                signalName={result.summary.signal_name} signalTimeframe={result.summary.signal_timeframe}
                costProfile={result.summary.cost_profile} warnings={result.summary.warnings} excluded={result.summary.excluded} />

              {result.net_analysis && (
                <Panel
                  eyebrow="Netto in tasca (Italia)"
                  title="Tasse e costi"
                  action={
                    <span className="inline-flex items-center gap-2 rounded-md border border-amber-300/30 bg-amber-400/10 px-3 py-1.5 text-xs font-semibold text-amber-100">
                      <Receipt className="h-3.5 w-3.5" aria-hidden="true" />
                      stima
                    </span>
                  }
                >
                  <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
                    <div className="space-y-3">
                      <div className="flex items-end justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                        <div>
                          <p className="text-xs uppercase text-slate-500">{result.summary.engine_version === "v1" ? "Rendimento prima delle imposte" : "Rendimento lordo"}</p>
                          <p className={`num mt-1 text-2xl font-semibold ${result.net_analysis.gross_return_percent >= 0 ? "text-slate-200" : "text-rose-300"}`}>
                            {formatPercent(result.net_analysis.gross_return_percent)}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs uppercase text-slate-500">Rendimento netto</p>
                          <p className={`num mt-1 text-2xl font-semibold ${result.net_analysis.net_return_percent >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                            {formatPercent(result.net_analysis.net_return_percent)}
                          </p>
                        </div>
                      </div>
                      <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-slate-400">Valore finale netto</span>
                          <span className="num text-lg font-semibold text-white">{formatBacktestCurrency(result.net_analysis.net_final_value, result.summary.engine_version)}</span>
                        </div>
                        <div className="mt-2 flex items-center justify-between text-xs">
                          <span className="text-slate-500">Aliquota effettiva sulle plusvalenze</span>
                          <span className="num text-slate-300">{formatPercent(result.net_analysis.effective_tax_rate_percent)}</span>
                        </div>
                      </div>
                    </div>

                    <div className="overflow-hidden rounded-lg border border-slate-800">
                      <table className="w-full border-collapse text-sm">
                        <tbody className="divide-y divide-slate-800/80">
                          <tr>
                            <td className="px-4 py-2.5 text-slate-400">Plusvalenze tassabili</td>
                            <td className="num px-4 py-2.5 text-right text-slate-200">{formatBacktestCurrency(result.net_analysis.realized_gains_taxable, result.summary.engine_version)}</td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2.5 text-slate-400">Imposta plusvalenze (26% / 12,5%)</td>
                            <td className="num px-4 py-2.5 text-right text-rose-300">- {formatBacktestCurrency(result.net_analysis.capital_gains_tax, result.summary.engine_version)}</td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2.5 text-slate-400">{result.summary.engine_version === "v1" ? "Spread / slippage (già incluso)" : "Slippage / spread stimato"}</td>
                            <td className="num px-4 py-2.5 text-right text-rose-300">{result.summary.engine_version !== "v1" && "- "}{formatBacktestCurrency(result.net_analysis.slippage_costs, result.summary.engine_version)}</td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2.5 text-slate-400">Imposta di bollo (0,2% annuo)</td>
                            <td className="num px-4 py-2.5 text-right text-rose-300">- {formatBacktestCurrency(result.net_analysis.stamp_duty, result.summary.engine_version)}</td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2.5 text-slate-500">Commissioni (già incluse)</td>
                            <td className="num px-4 py-2.5 text-right text-slate-500">{formatBacktestCurrency(result.net_analysis.commission_costs, result.summary.engine_version)}</td>
                          </tr>
                          <tr className="bg-slate-900/40">
                            <td className="px-4 py-2.5 font-semibold text-amber-100">{result.summary.engine_version === "v1" ? "Totale imposte stimate" : "Totale costi e tasse"}</td>
                            <td className="num px-4 py-2.5 text-right font-semibold text-amber-200">- {formatBacktestCurrency(result.net_analysis.total_costs_and_taxes, result.summary.engine_version)}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                  <ul className="mt-4 space-y-1 text-xs text-slate-500">
                    {result.net_analysis.notes.map((note) => (
                      <li key={note}>· {note}</li>
                    ))}
                  </ul>
                </Panel>
              )}

              <Panel title="Equity curve">
                <div className="h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={result.equity_curve} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                      <CartesianGrid stroke="#1E293B" vertical={false} />
                      <XAxis dataKey="date" stroke="#64748B" axisLine={false} tickLine={false} minTickGap={32} />
                      <YAxis stroke="#64748B" axisLine={false} tickLine={false} width={80} />
                      <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatBacktestCurrency(Number(value), result.summary.engine_version), "Valore"]} />
                      <Line type="monotone" dataKey="portfolio_value" stroke="#22D3EE" strokeWidth={2.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </Panel>

              <div className="grid gap-6 xl:grid-cols-2">
                <Panel title="Drawdown curve">
                  <div className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={result.equity_curve} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                        <XAxis dataKey="date" hide />
                        <YAxis stroke="#64748B" axisLine={false} tickLine={false} width={72} />
                        <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatPercent(Number(value)), "Drawdown"]} />
                        <Area type="monotone" dataKey="drawdown_percent" stroke="#FB7185" fill="#FB7185" fillOpacity={0.16} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>

                <Panel title="Portfolio vs benchmark">
                  <div className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={result.equity_curve} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                        <XAxis dataKey="date" hide />
                        <YAxis stroke="#64748B" axisLine={false} tickLine={false} width={80} />
                        <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatBacktestCurrency(Number(value), result.summary.engine_version), "Valore"]} />
                        <Line type="monotone" dataKey="portfolio_value" stroke="#22D3EE" strokeWidth={2.5} dot={false} />
                        <Line type="monotone" dataKey="benchmark_value" stroke="#94A3B8" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>
              </div>
            </>
          ) : (
            <Panel title="Risultati">
              <p className="text-sm text-slate-400">Esegui un backtest o selezionane uno dallo storico.</p>
            </Panel>
          )}
        </div>
      </div>

      {mode === "single" && result && (
        <div className="grid gap-6 xl:grid-cols-2">
          <Panel title="Trades">
            <div className="max-h-96 overflow-auto">
              <table className="w-full min-w-[820px] border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                    <th className="px-3 pb-3 pl-0 font-medium">Data</th>
                    <th className="px-3 pb-3 font-medium">Symbol</th>
                    <th className="px-3 pb-3 font-medium">Tipo</th>
                    <th className="px-3 pb-3 text-right font-medium">Qty</th>
                    <th className="px-3 pb-3 text-right font-medium">Prezzo</th>
                    <th className="px-3 pb-3 text-right font-medium">Commissione</th>
                    <th className="px-3 pb-3 text-right font-medium">Spread / slippage</th>
                    <th className="px-3 pb-3 text-right font-medium">P/L</th>
                    <th className="px-3 pb-3 pr-0 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {result.trades.map((trade, index) => (
                    <tr key={`${trade.date}-${trade.symbol}-${index}`} className="text-sm">
                      <td className="px-3 py-3 pl-0 text-slate-400">{trade.date}</td>
                      <td className="px-3 py-3 font-semibold text-white">{trade.symbol}</td>
                      <td className={trade.order_type === "BUY" ? "px-3 py-3 font-semibold text-emerald-300" : "px-3 py-3 font-semibold text-rose-300"}>{trade.order_type}</td>
                      <td className="px-3 py-3 text-right text-slate-300">{trade.quantity.toLocaleString("it-IT")}</td>
                      <td className="px-3 py-3 text-right text-slate-300">{formatBacktestCurrency(trade.price, result.summary.engine_version)}</td>
                      <td className="px-3 py-3 text-right text-slate-300">{trade.commission === null ? "N/D" : formatBacktestCurrency(trade.commission, result.summary.engine_version)}</td>
                      <td className="px-3 py-3 text-right text-slate-300">{trade.spread_cost === null ? "N/D" : formatBacktestCurrency(trade.spread_cost, result.summary.engine_version)}</td>
                      <td className={trade.pnl >= 0 ? "px-3 py-3 text-right font-semibold text-emerald-300" : "px-3 py-3 text-right font-semibold text-rose-300"}>{formatBacktestCurrency(trade.pnl, result.summary.engine_version)}</td>
                      <td className="max-w-72 px-3 py-3 pr-0 text-slate-500">{trade.reason ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Final positions">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                    <th className="px-3 pb-3 pl-0 font-medium">Symbol</th>
                    <th className="px-3 pb-3 text-right font-medium">Qty</th>
                    <th className="px-3 pb-3 text-right font-medium">Avg</th>
                    <th className="px-3 pb-3 text-right font-medium">Final</th>
                    <th className="px-3 pb-3 text-right font-medium">Value</th>
                    <th className="px-3 pb-3 pr-0 text-right font-medium">P/L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {result.final_positions.map((position) => (
                    <tr key={position.symbol} className="text-sm">
                      <td className="px-3 py-3 pl-0 font-semibold text-white">{position.symbol}</td>
                      <td className="px-3 py-3 text-right text-slate-300">{position.quantity.toLocaleString("it-IT")}</td>
                      <td className="px-3 py-3 text-right text-slate-300">{formatBacktestCurrency(position.average_price, result.summary.engine_version)}</td>
                      <td className="px-3 py-3 text-right text-slate-300">{formatBacktestCurrency(position.final_price, result.summary.engine_version)}</td>
                      <td className="px-3 py-3 text-right font-semibold text-white">{formatBacktestCurrency(position.final_value, result.summary.engine_version)}</td>
                      <td className={position.unrealized_pnl + position.realized_pnl >= 0 ? "px-3 py-3 pr-0 text-right font-semibold text-emerald-300" : "px-3 py-3 pr-0 text-right font-semibold text-rose-300"}>
                        {formatBacktestCurrency(position.unrealized_pnl + position.realized_pnl, result.summary.engine_version)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}

      <Panel title="Backtest history">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                <th className="px-3 pb-3 pl-0 font-medium">Nome</th>
                <th className="px-3 pb-3 font-medium">Strategia</th>
                <th className="px-3 pb-3 text-right font-medium">Return</th>
                <th className="px-3 pb-3 text-right font-medium">Drawdown</th>
                <th className="px-3 pb-3 text-right font-medium">Alpha</th>
                <th className="px-3 pb-3 text-right font-medium">Trade</th>
                <th className="px-3 pb-3 pr-0 font-medium">Azioni</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {history.map((item) => (
                <tr key={item.id} className="text-sm">
                  <td className="px-3 py-4 pl-0">
                    <button
                      onClick={() => item.id && void loadRunResult(item.id)}
                      disabled={historyBusy || deleteTarget !== null}
                      className="font-semibold text-white hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {item.name}
                    </button>
                    {item.engine_version === "v0" && <span className="ml-2 text-xs text-amber-200">motore precedente</span>}
                    {item.data_mode === "DEMO" && <span className="ml-2 text-xs text-amber-200">DEMO</span>}
                    <p className="mt-1 text-xs text-slate-500">{item.created_at ? new Date(item.created_at).toLocaleString("it-IT") : "-"}</p>
                  </td>
                  <td className="px-3 py-4 text-slate-300">{strategyLabels[item.strategy_name as BacktestStrategy] ?? item.strategy_name}</td>
                  <td className={item.total_return_percent >= 0 ? "px-3 py-4 text-right font-semibold text-emerald-300" : "px-3 py-4 text-right font-semibold text-rose-300"}>{formatPercent(item.total_return_percent)}</td>
                  <td className="px-3 py-4 text-right font-semibold text-rose-300">{formatPercent(item.max_drawdown)}</td>
                  <td className={item.alpha_vs_benchmark >= 0 ? "px-3 py-4 text-right font-semibold text-emerald-300" : "px-3 py-4 text-right font-semibold text-rose-300"}>{item.benchmark_snapshot_status === "UNAVAILABLE" ? "N/D" : formatPercent(item.alpha_vs_benchmark)}</td>
                  <td className="px-3 py-4 text-right text-slate-300">{item.total_trades}</td>
                  <td className="px-3 py-4 pr-0">
                    <button
                      onClick={() => {
                        if (backtestOperationInFlight.current || deleteTarget) {
                          return;
                        }
                        setDeleteTarget(item);
                        setDeleteConfirmation("");
                        setError(null);
                        setErrorCode(null);
                      }}
                      disabled={historyBusy || deleteTarget !== null}
                      className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-slate-700 text-slate-400 transition hover:border-rose-300/40 hover:text-rose-200"
                      aria-label={`Cancella backtest ${item.name} #${item.id}`}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {history.length === 0 && <p className="py-8 text-sm text-slate-400">Nessun backtest eseguito.</p>}
        </div>
      </Panel>

      {deleteTarget && (
        <Panel eyebrow="Conferma cancellazione" title={`Cancella ${deleteTarget.name} #${deleteTarget.id}?`}>
          <p className="text-sm text-slate-300">
            Verranno rimossi definitivamente il run di backtest, la relativa equity curve, i trade e le posizioni finali salvate.
          </p>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="space-y-1">
              <span className="text-xs text-slate-400">Digita esattamente {deleteConfirmationToken}</span>
              <input
                value={deleteConfirmation}
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                autoComplete="off"
                className="block min-h-11 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-rose-300/60 sm:w-80"
              />
            </label>
            <button
              onClick={() => void deleteRun(deleteTarget)}
              disabled={deleteConfirmation !== deleteConfirmationToken || deleting}
              className="inline-flex min-h-11 items-center justify-center rounded-md border border-rose-300/30 bg-rose-400/15 px-4 py-2 text-sm font-semibold text-rose-100 transition hover:bg-rose-400/25 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {deleting ? "Cancellazione..." : "Cancella definitivamente il backtest"}
            </button>
            <button
              onClick={() => {
                setDeleteTarget(null);
                setDeleteConfirmation("");
              }}
              disabled={deleting}
              className="inline-flex min-h-11 items-center justify-center rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-800 disabled:opacity-50"
            >
              Annulla
            </button>
          </div>
        </Panel>
      )}
    </div>
  );
}
