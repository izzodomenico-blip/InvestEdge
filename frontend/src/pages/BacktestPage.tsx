import { useEffect, useMemo, useState } from "react";
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
  type Asset,
  type BacktestCompareInput,
  type BacktestCompareResult,
  type BacktestResult,
  type BacktestRunInput,
  type BacktestStrategy,
  type BacktestSummary,
  type RebalanceFrequency,
  type WalkForwardInput,
  type WalkForwardResult,
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";
import { Activity, BarChart3, BadgeDollarSign, Receipt, ShieldAlert } from "lucide-react";

type BacktestMode = "single" | "compare" | "walkforward";

const compareSeriesColors = ["#22D3EE", "#A78BFA", "#34D399"];
const benchmarkColor = "#94A3B8";

const consistencyTone: Record<string, string> = {
  ROBUSTA: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
  INCERTA: "border-amber-300/30 bg-amber-400/10 text-amber-200",
  FRAGILE: "border-rose-300/30 bg-rose-400/10 text-rose-200",
};

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
  fee_percent: string;
  stop_loss_percent: string;
  take_profit_percent: string;
  rebalance_frequency: RebalanceFrequency;
  top_n: string;
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
  fee_percent: "0.10",
  stop_loss_percent: "8",
  take_profit_percent: "25",
  rebalance_frequency: "WEEKLY",
  top_n: "5",
};

const strategyLabels: Record<BacktestStrategy, string> = {
  SCORE_THRESHOLD: "Score threshold",
  BUY_AND_HOLD: "Buy and hold",
  TOP_N_SCORE: "Top N score",
};

function metricTone(value: number) {
  return value >= 0 ? "green" : "rose";
}

function numberOrUndefined(value: string) {
  if (value.trim() === "") {
    return undefined;
  }
  return Number(value);
}

export function BacktestPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
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
  const [folds, setFolds] = useState("4");
  const [walkResult, setWalkResult] = useState<WalkForwardResult | null>(null);
  const [walking, setWalking] = useState(false);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [assetData, historyData] = await Promise.all([
        apiGet<Asset[]>("/assets"),
        apiGet<BacktestSummary[]>("/backtests"),
      ]);
      setAssets(assetData);
      setHistory(historyData);
      if (historyData[0]) {
        setResult(await apiGet<BacktestResult>(`/backtests/${historyData[0].id}`));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento dei backtest.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
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

  async function runBacktest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const validation = validate();
    if (validation) {
      setError(validation);
      return;
    }
    setRunning(true);
    try {
      const payload: BacktestRunInput = {
        name: form.name,
        strategy_name: form.strategy_name,
        symbols: form.symbols,
        initial_cash: Number(form.initial_cash),
        start_date: form.start_date,
        end_date: form.end_date,
        benchmark_symbol: form.benchmark_symbol,
        buy_threshold: Number(form.buy_threshold),
        sell_threshold: Number(form.sell_threshold),
        max_asset_weight: Number(form.max_asset_weight),
        fee_percent: Number(form.fee_percent),
        stop_loss_percent: numberOrUndefined(form.stop_loss_percent),
        take_profit_percent: numberOrUndefined(form.take_profit_percent),
        rebalance_frequency: form.rebalance_frequency,
        top_n: form.strategy_name === "TOP_N_SCORE" ? Number(form.top_n) : undefined,
      };
      const nextResult = await apiPost<BacktestResult>("/backtests/run", payload);
      setResult(nextResult);
      setHistory(await apiGet<BacktestSummary[]>("/backtests"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'esecuzione del backtest.");
    } finally {
      setRunning(false);
    }
  }

  async function deleteRun(id: number | null) {
    if (!id) {
      return;
    }
    setError(null);
    try {
      await apiDelete(`/backtests/${id}`);
      setHistory(await apiGet<BacktestSummary[]>("/backtests"));
      if (result?.backtest_id === id) {
        setResult(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante la cancellazione del backtest.");
    }
  }

  function toggleCompareStrategy(strategy: BacktestStrategy) {
    setCompareStrategies((current) =>
      current.includes(strategy)
        ? current.filter((item) => item !== strategy)
        : [...current, strategy],
    );
  }

  async function runCompare(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const validation = validate();
    if (validation) {
      setError(validation);
      return;
    }
    if (compareStrategies.length < 2) {
      setError("Seleziona almeno due strategie da confrontare.");
      return;
    }
    setComparing(true);
    try {
      const payload: BacktestCompareInput = {
        name: form.name,
        strategy_names: compareStrategies,
        symbols: form.symbols,
        initial_cash: Number(form.initial_cash),
        start_date: form.start_date,
        end_date: form.end_date,
        benchmark_symbol: form.benchmark_symbol,
        buy_threshold: Number(form.buy_threshold),
        sell_threshold: Number(form.sell_threshold),
        max_asset_weight: Number(form.max_asset_weight),
        fee_percent: Number(form.fee_percent),
        stop_loss_percent: numberOrUndefined(form.stop_loss_percent),
        take_profit_percent: numberOrUndefined(form.take_profit_percent),
        rebalance_frequency: form.rebalance_frequency,
        top_n: compareStrategies.includes("TOP_N_SCORE") ? Number(form.top_n) : undefined,
      };
      setCompareResult(await apiPost<BacktestCompareResult>("/backtests/compare", payload));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il confronto delle strategie.");
    } finally {
      setComparing(false);
    }
  }

  async function runWalkForward(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const validation = validate();
    if (validation) {
      setError(validation);
      return;
    }
    setWalking(true);
    try {
      const payload: WalkForwardInput = {
        name: form.name,
        strategy_name: form.strategy_name,
        symbols: form.symbols,
        initial_cash: Number(form.initial_cash),
        start_date: form.start_date,
        end_date: form.end_date,
        benchmark_symbol: form.benchmark_symbol,
        buy_threshold: Number(form.buy_threshold),
        sell_threshold: Number(form.sell_threshold),
        max_asset_weight: Number(form.max_asset_weight),
        fee_percent: Number(form.fee_percent),
        stop_loss_percent: numberOrUndefined(form.stop_loss_percent),
        take_profit_percent: numberOrUndefined(form.take_profit_percent),
        rebalance_frequency: form.rebalance_frequency,
        top_n: form.strategy_name === "TOP_N_SCORE" ? Number(form.top_n) : undefined,
        folds: Number(folds),
      };
      setWalkResult(await apiPost<WalkForwardResult>("/backtests/walk-forward", payload));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante la validazione walk-forward.");
    } finally {
      setWalking(false);
    }
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
        subtitle="Valida strategie su dati locali con rolling indicators, stop loss/take profit e benchmark. Simulazione storica, nessuna garanzia di rendimenti futuri."
        actions={
          <div className="inline-flex rounded-lg border border-slate-800/80 bg-slate-950/60 p-1">
            <button
              type="button"
              onClick={() => setMode("single")}
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

      {error && <div className="rounded-lg border border-rose-300/20 bg-rose-400/10 p-4 text-sm text-rose-200">{error}</div>}

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.35fr]">
        <Panel title="Configurazione">
          <form
            onSubmit={(event) =>
              void (mode === "compare"
                ? runCompare(event)
                : mode === "walkforward"
                  ? runWalkForward(event)
                  : runBacktest(event))
            }
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
                <span className="text-sm text-slate-400">Commissioni %</span>
                <input type="number" step="0.01" value={form.fee_percent} onChange={(event) => updateField("fee_percent", event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
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
                <label className="space-y-2">
                  <span className="text-sm text-slate-400">Numero fold (2-12)</span>
                  <input type="number" min="2" max="12" value={folds} onChange={(event) => setFolds(event.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-300/60" />
                </label>
              )}
            </div>

            {mode === "compare" ? (
              <button disabled={comparing} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-violet-300/30 bg-violet-400/15 px-4 py-2.5 text-sm font-semibold text-violet-100 transition hover:bg-violet-400/25 disabled:opacity-60">
                <GitCompareArrows className={`h-4 w-4 ${comparing ? "animate-pulse" : ""}`} aria-hidden="true" />
                {comparing ? "Confronto in corso..." : "Confronta strategie"}
              </button>
            ) : mode === "walkforward" ? (
              <button disabled={walking} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-emerald-300/30 bg-emerald-400/15 px-4 py-2.5 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-400/25 disabled:opacity-60">
                <ShieldCheck className={`h-4 w-4 ${walking ? "animate-pulse" : ""}`} aria-hidden="true" />
                {walking ? "Validazione in corso..." : "Valida robustezza"}
              </button>
            ) : (
              <button disabled={running} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20 disabled:opacity-60">
                <RotateCcw className={`h-4 w-4 ${running ? "animate-spin" : ""}`} aria-hidden="true" />
                {running ? "Esecuzione..." : "Esegui backtest"}
              </button>
            )}
          </form>
        </Panel>

        <div className="space-y-6">
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
                              <td className={entry.summary.alpha_vs_benchmark >= 0 ? "px-3 py-3 text-right font-semibold text-emerald-300" : "px-3 py-3 text-right font-semibold text-rose-300"}>{formatPercent(entry.summary.alpha_vs_benchmark)}</td>
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
                          <td className="px-3 py-3 text-right text-slate-400">{formatPercent(compareResult.benchmark_return_percent)}</td>
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

                <Panel eyebrow="Equity curve sovrapposte" title="Andamento confronto">
                  <div className="h-96">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={compareChartData} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                        <CartesianGrid stroke="#1E293B" vertical={false} />
                        <XAxis dataKey="date" stroke="#64748B" axisLine={false} tickLine={false} minTickGap={40} />
                        <YAxis stroke="#64748B" axisLine={false} tickLine={false} width={80} />
                        <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => formatCurrency(Number(value), "EUR")} />
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
                <Panel
                  eyebrow={`Validazione out-of-sample · ${walkResult.folds} periodi`}
                  title="Verdetto robustezza"
                  action={
                    <span className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-semibold ${consistencyTone[walkResult.consistency] ?? consistencyTone.INCERTA}`}>
                      <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                      {walkResult.consistency}
                    </span>
                  }
                >
                  <p className="text-sm leading-relaxed text-slate-300">{walkResult.verdict}</p>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                      <p className="text-xs uppercase text-slate-500">Periodi positivi</p>
                      <p className="num mt-1 text-lg font-semibold text-white">{walkResult.positive_folds}/{walkResult.folds}</p>
                    </div>
                    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                      <p className="text-xs uppercase text-slate-500">Battono benchmark</p>
                      <p className="num mt-1 text-lg font-semibold text-cyan-200">{walkResult.folds_beating_benchmark}/{walkResult.folds}</p>
                    </div>
                    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                      <p className="text-xs uppercase text-slate-500">Rendimento medio</p>
                      <p className={`num mt-1 text-lg font-semibold ${walkResult.mean_return_percent >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{formatPercent(walkResult.mean_return_percent)}</p>
                    </div>
                    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                      <p className="text-xs uppercase text-slate-500">Dispersione (std)</p>
                      <p className="num mt-1 text-lg font-semibold text-amber-200">{formatPercent(walkResult.std_return_percent)}</p>
                    </div>
                  </div>
                  <p className="mt-4 text-xs text-slate-500">
                    Intero periodo: <span className="num text-slate-300">{formatPercent(walkResult.full_period_return_percent)}</span>
                    {"  ·  "}peggior fold: <span className="num text-rose-300">{formatPercent(walkResult.worst_fold_return_percent)}</span>
                    {"  ·  "}miglior fold: <span className="num text-emerald-300">{formatPercent(walkResult.best_fold_return_percent)}</span>
                    {"  ·  "}alpha medio: <span className="num text-slate-300">{formatPercent(walkResult.mean_alpha_vs_benchmark)}</span>
                  </p>
                </Panel>

                <Panel eyebrow="Dettaglio per periodo" title="Risultati fold">
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[620px] border-collapse">
                      <thead>
                        <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                          <th className="px-3 pb-3 pl-0 font-medium">Fold</th>
                          <th className="px-3 pb-3 font-medium">Periodo</th>
                          <th className="px-3 pb-3 text-right font-medium">Return</th>
                          <th className="px-3 pb-3 text-right font-medium">Drawdown</th>
                          <th className="px-3 pb-3 text-right font-medium">Sharpe</th>
                          <th className="px-3 pb-3 text-right font-medium">Alpha</th>
                          <th className="px-3 pb-3 pr-0 text-right font-medium">Trade</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/80">
                        {walkResult.fold_results.map((fold) => (
                          <tr key={fold.fold} className="text-sm">
                            <td className="px-3 py-3 pl-0 font-semibold text-white">#{fold.fold}</td>
                            <td className="px-3 py-3 text-xs text-slate-400">{fold.start_date} → {fold.end_date}</td>
                            <td className={fold.total_return_percent >= 0 ? "num px-3 py-3 text-right font-semibold text-emerald-300" : "num px-3 py-3 text-right font-semibold text-rose-300"}>{formatPercent(fold.total_return_percent)}</td>
                            <td className="num px-3 py-3 text-right text-rose-300">{formatPercent(fold.max_drawdown)}</td>
                            <td className="num px-3 py-3 text-right text-slate-300">{fold.sharpe_ratio.toFixed(2)}</td>
                            <td className={fold.alpha_vs_benchmark >= 0 ? "num px-3 py-3 text-right font-semibold text-emerald-300" : "num px-3 py-3 text-right font-semibold text-rose-300"}>{formatPercent(fold.alpha_vs_benchmark)}</td>
                            <td className="num px-3 py-3 pr-0 text-right text-slate-300">{fold.total_trades}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              </>
            ) : (
              <Panel title="Validazione robustezza">
                <p className="text-sm text-slate-400">
                  Scegli strategia e numero di fold, poi premi "Valida robustezza". Il periodo viene diviso in segmenti
                  consecutivi indipendenti: una strategia solida resta positiva nella maggior parte dei segmenti, non solo
                  sull'intero periodo.
                </p>
              </Panel>
            )
          ) : result ? (
            <>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Rendimento" value={formatPercent(result.summary.total_return_percent)} delta="Totale periodo" tone={metricTone(result.summary.total_return_percent)} icon={Activity} />
                <MetricCard label="CAGR" value={formatPercent(result.summary.cagr)} delta="Annualizzato" tone={metricTone(result.summary.cagr)} icon={BarChart3} />
                <MetricCard label="Max drawdown" value={formatPercent(result.summary.max_drawdown)} delta="Peggior discesa" tone="rose" icon={ShieldAlert} />
                <MetricCard label="Valore finale" value={formatCurrency(result.summary.final_value, "EUR")} delta={`${result.summary.total_trades} trade`} tone="cyan" icon={BadgeDollarSign} />
              </div>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Sharpe" value={result.summary.sharpe_ratio.toFixed(2)} delta="Rischio/rendimento" tone="cyan" icon={BarChart3} />
                <MetricCard label="Win rate" value={formatPercent(result.summary.win_rate)} delta="Trade SELL vincenti" tone="green" icon={Activity} />
                <MetricCard label="Profit factor" value={result.summary.profit_factor.toFixed(2)} delta="Profitti / perdite" tone="amber" icon={BarChart3} />
                <MetricCard label="Alpha benchmark" value={formatPercent(result.benchmark_comparison.alpha_vs_benchmark)} delta={result.benchmark_comparison.benchmark_symbol ?? "Benchmark"} tone={metricTone(result.benchmark_comparison.alpha_vs_benchmark)} icon={Activity} />
              </div>

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
                          <p className="text-xs uppercase text-slate-500">Rendimento lordo</p>
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
                          <span className="num text-lg font-semibold text-white">{formatCurrency(result.net_analysis.net_final_value, "EUR")}</span>
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
                            <td className="num px-4 py-2.5 text-right text-slate-200">{formatCurrency(result.net_analysis.realized_gains_taxable, "EUR")}</td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2.5 text-slate-400">Imposta plusvalenze (26% / 12,5%)</td>
                            <td className="num px-4 py-2.5 text-right text-rose-300">- {formatCurrency(result.net_analysis.capital_gains_tax, "EUR")}</td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2.5 text-slate-400">Slippage / spread stimato</td>
                            <td className="num px-4 py-2.5 text-right text-rose-300">- {formatCurrency(result.net_analysis.slippage_costs, "EUR")}</td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2.5 text-slate-400">Imposta di bollo (0,2% annuo)</td>
                            <td className="num px-4 py-2.5 text-right text-rose-300">- {formatCurrency(result.net_analysis.stamp_duty, "EUR")}</td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2.5 text-slate-500">Commissioni (gia nel lordo)</td>
                            <td className="num px-4 py-2.5 text-right text-slate-500">{formatCurrency(result.net_analysis.commission_costs, "EUR")}</td>
                          </tr>
                          <tr className="bg-slate-900/40">
                            <td className="px-4 py-2.5 font-semibold text-amber-100">Totale costi e tasse</td>
                            <td className="num px-4 py-2.5 text-right font-semibold text-amber-200">- {formatCurrency(result.net_analysis.total_costs_and_taxes, "EUR")}</td>
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
                      <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatCurrency(Number(value), "EUR"), "Valore"]} />
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
                        <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatCurrency(Number(value), "EUR"), "Valore"]} />
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
                      <td className="px-3 py-3 text-right text-slate-300">{formatCurrency(trade.price, "USD")}</td>
                      <td className={trade.pnl >= 0 ? "px-3 py-3 text-right font-semibold text-emerald-300" : "px-3 py-3 text-right font-semibold text-rose-300"}>{formatCurrency(trade.pnl, "USD")}</td>
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
                      <td className="px-3 py-3 text-right text-slate-300">{formatCurrency(position.average_price, "USD")}</td>
                      <td className="px-3 py-3 text-right text-slate-300">{formatCurrency(position.final_price, "USD")}</td>
                      <td className="px-3 py-3 text-right font-semibold text-white">{formatCurrency(position.final_value, "USD")}</td>
                      <td className={position.unrealized_pnl + position.realized_pnl >= 0 ? "px-3 py-3 pr-0 text-right font-semibold text-emerald-300" : "px-3 py-3 pr-0 text-right font-semibold text-rose-300"}>
                        {formatCurrency(position.unrealized_pnl + position.realized_pnl, "USD")}
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
                    <button onClick={() => item.id && apiGet<BacktestResult>(`/backtests/${item.id}`).then(setResult).catch((err) => setError(err instanceof Error ? err.message : "Errore caricamento backtest."))} className="font-semibold text-white hover:text-cyan-200">
                      {item.name}
                    </button>
                    <p className="mt-1 text-xs text-slate-500">{item.created_at ? new Date(item.created_at).toLocaleString("it-IT") : "-"}</p>
                  </td>
                  <td className="px-3 py-4 text-slate-300">{strategyLabels[item.strategy_name as BacktestStrategy] ?? item.strategy_name}</td>
                  <td className={item.total_return_percent >= 0 ? "px-3 py-4 text-right font-semibold text-emerald-300" : "px-3 py-4 text-right font-semibold text-rose-300"}>{formatPercent(item.total_return_percent)}</td>
                  <td className="px-3 py-4 text-right font-semibold text-rose-300">{formatPercent(item.max_drawdown)}</td>
                  <td className={item.alpha_vs_benchmark >= 0 ? "px-3 py-4 text-right font-semibold text-emerald-300" : "px-3 py-4 text-right font-semibold text-rose-300"}>{formatPercent(item.alpha_vs_benchmark)}</td>
                  <td className="px-3 py-4 text-right text-slate-300">{item.total_trades}</td>
                  <td className="px-3 py-4 pr-0">
                    <button onClick={() => void deleteRun(item.id)} className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-700 text-slate-400 transition hover:border-rose-300/40 hover:text-rose-200" aria-label="Cancella backtest">
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
    </div>
  );
}
