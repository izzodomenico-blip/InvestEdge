import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BadgeDollarSign, Banknote, PieChart as PieChartIcon, RefreshCw, RotateCcw, TrendingUp } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AllocationPlanner } from "../components/AllocationPlanner";
import { MetricCard } from "../components/MetricCard";
import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import {
  apiGet,
  apiPost,
  type PortfolioRecommendation,
  type PortfolioSnapshot,
  type PortfolioSummary,
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const colors = ["#22D3EE", "#34D399", "#60A5FA", "#F59E0B", "#FB7185", "#A78BFA"];
const baseCurrency = "EUR";

const assetTypeLabels: Record<string, string> = {
  stock: "Azioni",
  etf: "ETF",
  crypto: "Cripto",
  bond: "Bond",
  bond_etf: "ETF bond",
};

function pnlClass(value: number) {
  return value >= 0 ? "text-emerald-300" : "text-rose-300";
}

function recommendationTone(value: string | null) {
  if (value?.includes("BLOCK") || value === "SELL") {
    return "border-rose-300/20 bg-rose-400/10 text-rose-200";
  }
  if (value === "REDUCE") {
    return "border-amber-300/20 bg-amber-400/10 text-amber-200";
  }
  if (value === "BUY_ALLOWED") {
    return "border-emerald-300/20 bg-emerald-400/10 text-emerald-200";
  }
  return "border-slate-700 bg-slate-900 text-slate-300";
}

export function PortfolioPage() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [snapshots, setSnapshots] = useState<PortfolioSnapshot[]>([]);
  const [recommendations, setRecommendations] = useState<PortfolioRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showReset, setShowReset] = useState(false);
  const [resetCash, setResetCash] = useState("10000");
  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState<string | null>(null);

  async function loadPortfolio() {
    setLoading(true);
    setError(null);
    try {
      const [portfolio, snapshotData, recommendationData] = await Promise.all([
        apiGet<PortfolioSummary>("/portfolio"),
        apiGet<PortfolioSnapshot[]>("/portfolio/snapshots"),
        apiGet<PortfolioRecommendation[]>("/portfolio/recommendations"),
      ]);
      setSummary(portfolio);
      setSnapshots(snapshotData);
      setRecommendations(recommendationData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento del portafoglio.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshPortfolio() {
    setRefreshing(true);
    setError(null);
    try {
      const portfolio = await apiPost<PortfolioSummary>("/portfolio/refresh");
      const [snapshotData, recommendationData] = await Promise.all([
        apiGet<PortfolioSnapshot[]>("/portfolio/snapshots"),
        apiGet<PortfolioRecommendation[]>("/portfolio/recommendations"),
      ]);
      setSummary(portfolio);
      setSnapshots(snapshotData);
      setRecommendations(recommendationData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'aggiornamento del portafoglio.");
    } finally {
      setRefreshing(false);
    }
  }

  async function resetPortfolio() {
    const cash = Number(resetCash);
    if (!(cash > 0)) {
      setResetMsg("Inserisci un capitale maggiore di zero.");
      return;
    }
    setResetting(true);
    setResetMsg(null);
    try {
      await apiPost("/portfolio/init", { initial_cash: cash });
      setShowReset(false);
      setResetMsg("Portafoglio azzerato: posizioni e operazioni cancellate, liquidità reimpostata.");
      await loadPortfolio();
    } catch (err) {
      setResetMsg(err instanceof Error ? err.message : "Azzeramento non riuscito.");
    } finally {
      setResetting(false);
    }
  }

  useEffect(() => {
    void loadPortfolio();
  }, []);

  const allocationByType = useMemo(() => {
    if (!summary) {
      return [];
    }
    return Object.entries(summary.allocation_by_asset_type).map(([name, value], index) => ({
      name: assetTypeLabels[name] ?? name,
      value,
      color: colors[index % colors.length],
    }));
  }, [summary]);

  const allocationByCurrency = useMemo(() => {
    if (!summary) {
      return [];
    }
    return Object.entries(summary.allocation_by_currency).map(([name, value], index) => ({
      name,
      value,
      color: colors[(index + 2) % colors.length],
    }));
  }, [summary]);

  const recommendationBySymbol = useMemo(
    () => new Map(recommendations.map((item) => [item.symbol, item])),
    [recommendations],
  );

  if (loading) {
    return (
      <Panel title="Portafoglio">
        <div className="h-56 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel title="Errore">
        <p className="text-sm text-rose-300">{error}</p>
      </Panel>
    );
  }

  if (!summary) {
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
        eyebrow="Paper trading"
        index="03"
        title="Portafoglio"
        subtitle="Posizioni simulate, allocation, P/L e warning di rischio. Nessun ordine reale viene inviato."
        meta={
          <>
            <span>
              Posizioni <span className="text-cyan-300/80">{summary.positions.length}</span>
            </span>
            <span>
              Warning <span className="text-cyan-300/80">{summary.risk_warnings.length}</span>
            </span>
          </>
        }
        actions={
          <>
            <PageHeaderAction
              onClick={() => setShowReset((v) => !v)}
              icon={<RotateCcw className="h-4 w-4" aria-hidden="true" />}
            >
              Ricomincia
            </PageHeaderAction>
            <PageHeaderAction
              variant="primary"
              onClick={() => void refreshPortfolio()}
              disabled={refreshing}
              icon={<RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />}
            >
              Aggiorna prezzi
            </PageHeaderAction>
          </>
        }
      />

      {resetMsg && (
        <div className="rounded-2xl border border-cyan-300/20 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">{resetMsg}</div>
      )}

      {showReset && (
        <Panel eyebrow="Reset" title="Ricomincia il portafoglio da capo">
          <p className="text-sm text-slate-400">
            Cancella <span className="text-rose-200">tutte le posizioni e le operazioni</span> simulate e reimposta la liquidità.
            Utile per iniziare una nuova simulazione pulita. Nessun ordine reale viene toccato.
          </p>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="space-y-1">
              <span className="text-xs text-slate-400">Capitale virtuale di partenza (€)</span>
              <input
                type="number"
                value={resetCash}
                onChange={(e) => setResetCash(e.target.value)}
                className="block w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60 sm:w-56"
              />
            </label>
            <button
              onClick={() => void resetPortfolio()}
              disabled={resetting}
              className="inline-flex items-center justify-center gap-2 rounded-md border border-rose-300/30 bg-rose-400/15 px-4 py-2 text-sm font-semibold text-rose-100 transition hover:bg-rose-400/25 disabled:opacity-60"
            >
              <RotateCcw className={`h-4 w-4 ${resetting ? "animate-spin" : ""}`} aria-hidden="true" />
              {resetting ? "Azzero..." : "Azzera e riparti"}
            </button>
            <button
              onClick={() => setShowReset(false)}
              className="inline-flex items-center justify-center rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-800"
            >
              Annulla
            </button>
          </div>
        </Panel>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Valore totale" value={formatCurrency(summary.total_value, baseCurrency)} delta="Cash + posizioni" tone="cyan" icon={BadgeDollarSign} />
        <MetricCard label="Liquidita" value={formatCurrency(summary.cash, baseCurrency)} delta={`${formatPercent((summary.cash / Math.max(summary.total_value, 1)) * 100)} del portafoglio`} tone="green" icon={Banknote} />
        <MetricCard label="Capitale investito" value={formatCurrency(summary.invested_value, baseCurrency)} delta={`${summary.positions.length} posizioni aperte`} tone="amber" icon={PieChartIcon} />
        <MetricCard label="P/L totale" value={formatCurrency(summary.total_pnl, baseCurrency)} delta={formatPercent(summary.total_pnl_percent)} tone={summary.total_pnl >= 0 ? "green" : "rose"} icon={TrendingUp} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <MetricCard label="P/L realizzato" value={formatCurrency(summary.realized_pnl, baseCurrency)} delta="Da vendite simulate" tone={summary.realized_pnl >= 0 ? "green" : "rose"} icon={TrendingUp} />
        <MetricCard label="P/L non realizzato" value={formatCurrency(summary.unrealized_pnl, baseCurrency)} delta="Su posizioni aperte" tone={summary.unrealized_pnl >= 0 ? "green" : "rose"} icon={TrendingUp} />
        <MetricCard label="Warning rischio" value={`${summary.risk_warnings.length}`} delta="Concentrazione e liquidita" tone={summary.risk_warnings.length ? "rose" : "green"} icon={AlertTriangle} />
      </div>

      <AllocationPlanner />

      <Panel title="Posizioni">
        {summary.positions.length === 0 ? (
          <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 p-5">
            <h2 className="font-semibold text-amber-100">Portafoglio non inizializzato</h2>
            <p className="mt-2 text-sm text-slate-300">Esegui il seed oppure inizializza un portafoglio dal backend con `/portfolio/init`.</p>
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {summary.positions.map((position) => {
              const recommendation = recommendationBySymbol.get(position.symbol);
              const reco = recommendation?.final_recommendation ?? position.recommendation ?? "HOLD";
              return (
                <article key={position.symbol} className="rounded-2xl border border-slate-800/60 bg-slate-950/55 p-4 shadow-panel">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-mono text-base font-semibold text-white">{position.symbol}</p>
                        {position.technical_signal ? <SignalBadge signal={position.technical_signal} size="sm" /> : null}
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {assetTypeLabels[position.asset_type] ?? position.asset_type} · {position.quantity.toLocaleString("it-IT")} quote · peso {position.weight_percent.toFixed(0)}%
                      </p>
                    </div>
                    <span className={`inline-flex shrink-0 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${recommendationTone(reco)}`}>
                      {reco}
                    </span>
                  </div>

                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <div className="rounded-lg border border-slate-800/70 bg-slate-900/50 p-2.5">
                      <p className="eyebrow-muted">Valore</p>
                      <p className="num mt-1 text-sm font-semibold text-white">{formatCurrency(position.current_value, position.currency)}</p>
                    </div>
                    <div className="rounded-lg border border-slate-800/70 bg-slate-900/50 p-2.5">
                      <p className="eyebrow-muted">P/L</p>
                      <p className={`num mt-1 text-sm font-semibold ${pnlClass(position.unrealized_pnl)}`}>{formatCurrency(position.unrealized_pnl, position.currency)}</p>
                    </div>
                    <div className="rounded-lg border border-slate-800/70 bg-slate-900/50 p-2.5">
                      <p className="eyebrow-muted">P/L %</p>
                      <p className={`num mt-1 text-sm font-semibold ${pnlClass(position.unrealized_pnl_percent)}`}>{formatPercent(position.unrealized_pnl_percent)}</p>
                    </div>
                  </div>

                  <p className="mt-3 text-xs text-slate-500">
                    Medio {formatCurrency(position.average_price, position.currency)} → attuale {formatCurrency(position.current_price, position.currency)}
                  </p>
                  {recommendation?.reason && <p className="mt-1 text-xs text-slate-500">{recommendation.reason}</p>}
                </article>
              );
            })}
          </div>
        )}
      </Panel>

      <div className="grid gap-6 xl:grid-cols-3">
        <Panel title="Allocation asset class">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={allocationByType} layout="vertical" margin={{ left: 18, right: 12, top: 8, bottom: 8 }}>
                <XAxis type="number" stroke="#64748B" axisLine={false} tickLine={false} unit="%" />
                <YAxis dataKey="name" type="category" stroke="#94A3B8" axisLine={false} tickLine={false} width={82} />
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [`${Number(value).toFixed(2)}%`, "Peso"]} />
                <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                  {allocationByType.map((item) => (
                    <Cell key={item.name} fill={item.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Allocation valuta">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={allocationByCurrency} dataKey="value" nameKey="name" innerRadius={58} outerRadius={92} paddingAngle={3}>
                  {allocationByCurrency.map((item) => (
                    <Cell key={item.name} fill={item.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [`${Number(value).toFixed(2)}%`, "Peso"]} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Andamento portafoglio">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={snapshots} margin={{ left: 0, right: 12, top: 8, bottom: 8 }}>
                <XAxis dataKey="snapshot_date" hide />
                <YAxis stroke="#64748B" axisLine={false} tickLine={false} width={78} />
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatCurrency(Number(value), baseCurrency), "Valore"]} />
                <Area type="monotone" dataKey="total_value" stroke="#22D3EE" fill="#22D3EE" fillOpacity={0.16} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <Panel title="Risk warnings">
        {summary.risk_warnings.length === 0 ? (
          <p className="text-sm text-emerald-300">Nessun warning attivo sui limiti configurati.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {summary.risk_warnings.map((warning) => (
              <div key={`${warning.code}-${warning.symbol ?? "portfolio"}`} className="rounded-lg border border-amber-300/20 bg-amber-400/10 p-4">
                <p className="text-sm font-semibold text-amber-100">{warning.code}</p>
                <p className="mt-2 text-sm text-slate-300">{warning.message}</p>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
