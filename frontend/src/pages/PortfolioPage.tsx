import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, BadgeDollarSign, Banknote, PieChart as PieChartIcon, RefreshCw, TrendingUp, Scale, BriefcaseBusiness, Lock } from "lucide-react";
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

import { MetricCard } from "../components/MetricCard";
import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import {
  api,
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
  const navigate = useNavigate();
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [snapshots, setSnapshots] = useState<PortfolioSnapshot[]>([]);
  const [recommendations, setRecommendations] = useState<PortfolioRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadPortfolio() {
    setLoading(true);
    setError(null);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;
      
      const [portfolio, snapshotData, recommendationData] = await Promise.all([
        api.getPortfolio(pId),
        api.getPortfolioSnapshots(pId),
        api.getPortfolioRecommendations(pId),
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
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;
      
      const portfolio = await api.refreshPortfolio(pId);
      const [snapshotData, recommendationData] = await Promise.all([
        api.getPortfolioSnapshots(pId),
        api.getPortfolioRecommendations(pId),
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

  if (loading && !summary) {
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
      <header className="flex flex-col justify-between gap-4 md:flex-row md:items-end border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-cyan-400 mb-1">
             <BriefcaseBusiness size={14} /> 
             <span>Paper trading</span>
             <span className="text-slate-600">•</span>
             <span className="text-slate-400">Portafoglio Attivo</span>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
             {summary.settings ? `Portfolio Simulator` : "Portafoglio"}
             {summary.settings.portfolio_type === "EXTERNAL_TRACKER" && (
               <span className="px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[10px] font-bold uppercase border border-blue-500/30 flex items-center gap-1">
                 <Lock size={10} /> Read Only
               </span>
             )}
          </h1>
          <p className="text-slate-500 text-sm mt-1">Gestione posizioni e analisi dei limiti di rischio.</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate("/portfolios")}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-700"
          >
            Gestisci Portafogli
          </button>
          <button
            onClick={() => navigate("/optimizer")}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-indigo-300/30 bg-indigo-400/10 px-4 py-2 text-sm font-semibold text-indigo-100 transition hover:bg-indigo-400/20"
          >
            <Scale className="h-4 w-4" aria-hidden="true" />
            Ottimizza
          </button>
          <button
            onClick={() => void refreshPortfolio()}
            disabled={refreshing}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20 disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />
            Aggiorna prezzi
          </button>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Valore totale" value={formatCurrency(summary.total_value, summary.settings.max_cash_weight > 0 ? "USD" : "USD")} delta="Cash + posizioni" tone="cyan" icon={BadgeDollarSign} />
        <MetricCard label="Liquidita" value={formatCurrency(summary.cash)} delta={`${formatPercent((summary.cash / Math.max(summary.total_value, 1)) * 100)} del portafoglio`} tone="green" icon={Banknote} />
        <MetricCard label="Capitale investito" value={formatCurrency(summary.invested_value)} delta={`${summary.positions.length} posizioni aperte`} tone="amber" icon={PieChartIcon} />
        <MetricCard label="P/L totale" value={formatCurrency(summary.total_pnl)} delta={formatPercent(summary.total_pnl_percent)} tone={summary.total_pnl >= 0 ? "green" : "rose"} icon={TrendingUp} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <MetricCard label="P/L realizzato" value={formatCurrency(summary.realized_pnl)} delta="Da vendite simulate" tone={summary.realized_pnl >= 0 ? "green" : "rose"} icon={TrendingUp} />
        <MetricCard label="P/L non realizzato" value={formatCurrency(summary.unrealized_pnl)} delta="Su posizioni aperte" tone={summary.unrealized_pnl >= 0 ? "green" : "rose"} icon={TrendingUp} />
        <MetricCard label="Warning rischio" value={`${summary.risk_warnings.length}`} delta="Concentrazione e liquidita" tone={summary.risk_warnings.length ? "rose" : "green"} icon={AlertTriangle} />
      </div>

      <Panel title="Posizioni">
        {summary.positions.length === 0 ? (
          <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 p-5">
            <h2 className="font-semibold text-amber-100">Portafoglio vuoto</h2>
            <p className="mt-2 text-sm text-slate-300">Usa il simulatore per aggiungere asset al portafoglio attivo.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1180px] border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="px-3 pb-3 pl-0 font-medium">Symbol</th>
                  <th className="px-3 pb-3 font-medium">Asset type</th>
                  <th className="px-3 pb-3 text-right font-medium">Quantita</th>
                  <th className="px-3 pb-3 text-right font-medium">Prezzo medio</th>
                  <th className="px-3 pb-3 text-right font-medium">Prezzo attuale</th>
                  <th className="px-3 pb-3 text-right font-medium">Valore</th>
                  <th className="px-3 pb-3 text-right font-medium">P/L</th>
                  <th className="px-3 pb-3 text-right font-medium">P/L %</th>
                  <th className="px-3 pb-3 text-right font-medium">Peso</th>
                  <th className="px-3 pb-3 text-center font-medium">Segnale</th>
                  <th className="px-3 pb-3 pr-0 font-medium">Raccomandazione</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {summary.positions.map((position) => {
                  const recommendation = recommendationBySymbol.get(position.symbol);
                  return (
                    <tr key={position.symbol} className="align-top text-sm">
                      <td className="px-3 py-4 pl-0 font-semibold text-white">{position.symbol}</td>
                      <td className="px-3 py-4 text-slate-300">{assetTypeLabels[position.asset_type] ?? position.asset_type}</td>
                      <td className="px-3 py-4 text-right text-slate-300">{position.quantity.toLocaleString("it-IT")}</td>
                      <td className="px-3 py-4 text-right text-slate-300">{formatCurrency(position.average_price, position.currency)}</td>
                      <td className="px-3 py-4 text-right text-white">{formatCurrency(position.current_price, position.currency)}</td>
                      <td className="px-3 py-4 text-right font-semibold text-white">{formatCurrency(position.current_value, position.currency)}</td>
                      <td className={`px-3 py-4 text-right font-semibold ${pnlClass(position.unrealized_pnl)}`}>{formatCurrency(position.unrealized_pnl, position.currency)}</td>
                      <td className={`px-3 py-4 text-right font-semibold ${pnlClass(position.unrealized_pnl_percent)}`}>{formatPercent(position.unrealized_pnl_percent)}</td>
                      <td className="px-3 py-4 text-right text-cyan-200">{position.weight_percent.toFixed(2)}%</td>
                      <td className="px-3 py-4 text-center">{position.technical_signal ? <SignalBadge signal={position.technical_signal} /> : "N/D"}</td>
                      <td className="px-3 py-4 pr-0">
                        <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${recommendationTone(recommendation?.final_recommendation ?? position.recommendation)}`}>
                          {recommendation?.final_recommendation ?? position.recommendation ?? "HOLD"}
                        </span>
                        <p className="mt-2 max-w-72 text-xs text-slate-500">{recommendation?.reason}</p>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatCurrency(Number(value)), "Valore"]} />
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
