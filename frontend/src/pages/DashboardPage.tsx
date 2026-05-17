import { useEffect, useMemo, useState } from "react";
import { Activity, BadgeDollarSign, BarChart3, Database, ShieldAlert, TrendingUp } from "lucide-react";
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
import { apiGet, type DashboardResponse } from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const colors = ["#22D3EE", "#34D399", "#60A5FA", "#F59E0B", "#FB7185", "#A78BFA"];

const assetTypeLabels: Record<string, string> = {
  stock: "Azioni",
  etf: "ETF",
  crypto: "Cripto",
  bond: "Bond",
  bond_etf: "ETF bond",
};

export function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadDashboard() {
    setLoading(true);
    setError(null);
    try {
      setDashboard(await apiGet<DashboardResponse>("/dashboard"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento della dashboard.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  const allocation = useMemo(() => {
    if (!dashboard) {
      return [];
    }
    return Object.entries(dashboard.asset_type_breakdown).map(([name, value], index) => ({
      name: assetTypeLabels[name] ?? name,
      value,
      color: colors[index % colors.length],
    }));
  }, [dashboard]);

  if (loading) {
    return (
      <Panel title="Dashboard">
        <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
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

  if (!dashboard?.initialized) {
    return (
      <div className="space-y-6">
        <header>
          <p className="text-sm font-medium text-cyan-300">InvestEdge</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Dashboard</h1>
        </header>
        <Panel title="Database non inizializzato">
          <p className="text-slate-300">{dashboard?.message ?? "Database non inizializzato."}</p>
          <p className="mt-3 text-sm text-slate-500">Esegui `backend\.venv\Scripts\python.exe scripts\seed_database.py --reset` e ricarica la pagina.</p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-sm font-medium text-cyan-300">InvestEdge</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Dashboard</h1>
        </div>
        <button
          onClick={() => void loadDashboard()}
          className="rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20"
        >
          Aggiorna
        </button>
      </header>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Asset monitorati" value={`${dashboard.assets_count}`} delta="Universe seed locale" tone="cyan" icon={Activity} />
        <MetricCard label="Valore portafoglio" value={formatCurrency(dashboard.portfolio_value, "EUR")} delta={`${dashboard.positions_count} posizioni aperte`} tone="green" icon={BadgeDollarSign} />
        <MetricCard label="Liquidita" value={formatCurrency(dashboard.cash, "EUR")} delta="Cash paper trading" tone="amber" icon={Database} />
        <MetricCard label="P/L totale" value={formatCurrency(dashboard.total_pnl, "EUR")} delta={formatPercent(dashboard.total_pnl_percent)} tone={dashboard.total_pnl >= 0 ? "green" : "rose"} icon={TrendingUp} />
      </div>

      <Panel title="Stato dati">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Modalita</p>
            <p className={dashboard.data_status.data_mode === "SEED" ? "mt-1 font-semibold text-amber-300" : "mt-1 font-semibold text-emerald-300"}>
              {dashboard.data_status.data_mode}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {dashboard.data_status.enable_real_data ? "Real data abilitati" : "Dati reali disattivati. Stai usando dati seed/demo."}
            </p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Ultimo aggiornamento</p>
            <p className="mt-1 font-semibold text-white">{dashboard.data_status.global_last_update ?? "N/D"}</p>
            <p className="mt-1 text-xs text-slate-500">Nessuna chiamata API automatica</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Provider disponibili</p>
            <p className="mt-1 font-semibold text-cyan-200">
              {dashboard.data_status.provider_status.filter((provider) => provider.api_key_configured).length}/{dashboard.data_status.provider_status.length}
            </p>
            <p className="mt-1 text-xs text-slate-500">{dashboard.data_status.provider_status.map((provider) => provider.provider).join(", ")}</p>
          </div>
        </div>
      </Panel>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Strong buy" value={`${dashboard.signal_breakdown.STRONG_BUY ?? 0}`} delta="Segnali tecnici ad alta forza" tone="green" icon={TrendingUp} />
        <MetricCard label="Buy" value={`${dashboard.signal_breakdown.BUY ?? 0}`} delta="Setup favorevoli" tone="cyan" icon={TrendingUp} />
        <MetricCard label="Hold" value={`${dashboard.signal_breakdown.HOLD ?? 0}`} delta="Situazioni neutrali" tone="amber" icon={BarChart3} />
        <MetricCard
          label="Reduce / Sell"
          value={`${(dashboard.signal_breakdown.REDUCE ?? 0) + (dashboard.signal_breakdown.SELL ?? 0)}`}
          delta="Asset con profilo tecnico debole"
          tone="rose"
          icon={ShieldAlert}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1.2fr]">
        <Panel title="Sintesi portafoglio">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Top posizione</p>
              <p className="mt-1 font-semibold text-white">{dashboard.top_position?.symbol ?? "N/D"}</p>
              <p className="mt-1 text-sm text-cyan-200">
                {dashboard.top_position ? `${dashboard.top_position.weight_percent.toFixed(2)}%` : "0.00%"}
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Warning rischio</p>
              <p className={dashboard.risk_warnings_count > 0 ? "mt-1 font-semibold text-amber-300" : "mt-1 font-semibold text-emerald-300"}>
                {dashboard.risk_warnings_count}
              </p>
              <p className="mt-1 text-sm text-slate-500">Da risk engine</p>
            </div>
          </div>
        </Panel>

        <Panel title="Andamento portafoglio">
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={dashboard.portfolio_snapshots} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                <XAxis dataKey="snapshot_date" hide />
                <YAxis stroke="#64748B" axisLine={false} tickLine={false} width={78} />
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatCurrency(Number(value), "EUR"), "Valore"]} />
                <Area type="monotone" dataKey="total_value" stroke="#22D3EE" fill="#22D3EE" fillOpacity={0.16} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <Panel title="Ultimo backtest">
        {dashboard.latest_backtest ? (
          <div className="grid gap-3 md:grid-cols-4">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Run</p>
              <p className="mt-1 font-semibold text-white">{dashboard.latest_backtest.name}</p>
              <p className="mt-1 text-xs text-slate-500">{dashboard.latest_backtest.strategy_name}</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Rendimento</p>
              <p className={dashboard.latest_backtest.total_return_percent >= 0 ? "mt-1 font-semibold text-emerald-300" : "mt-1 font-semibold text-rose-300"}>
                {formatPercent(dashboard.latest_backtest.total_return_percent)}
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Max drawdown</p>
              <p className="mt-1 font-semibold text-rose-300">{formatPercent(dashboard.latest_backtest.max_drawdown)}</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Alpha vs benchmark</p>
              <p className={dashboard.latest_backtest.alpha_vs_benchmark >= 0 ? "mt-1 font-semibold text-emerald-300" : "mt-1 font-semibold text-rose-300"}>
                {formatPercent(dashboard.latest_backtest.alpha_vs_benchmark)}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-400">Nessun backtest eseguito.</p>
        )}
      </Panel>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_0.9fr]">
        <Panel title="Top score asset">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dashboard.top_assets} margin={{ left: 0, right: 12, top: 12, bottom: 0 }}>
                <XAxis dataKey="symbol" stroke="#64748B" tickLine={false} axisLine={false} />
                <YAxis stroke="#64748B" tickLine={false} axisLine={false} domain={[0, 100]} />
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} />
                <Bar dataKey="score" fill="#22D3EE" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Distribuzione asset">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={allocation} dataKey="value" nameKey="name" innerRadius={58} outerRadius={90} paddingAngle={3}>
                  {allocation.map((item) => (
                    <Cell key={item.name} fill={item.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="space-y-3">
            {allocation.map((item) => (
              <div key={item.name} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 text-slate-300">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                  {item.name}
                </span>
                <span className="font-medium text-white">{item.value}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Segnali recenti">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {dashboard.latest_signals.map((item) => (
            <article key={item.id} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-semibold text-white">{item.symbol}</p>
                <SignalBadge signal={item.signal} />
              </div>
              <p className="mt-3 line-clamp-3 text-sm text-slate-400">{item.technical_summary}</p>
              <div className="mt-4 h-2 rounded-full bg-slate-800">
                <div className="h-2 rounded-full bg-cyan-300" style={{ width: `${item.score}%` }} />
              </div>
              <p className="mt-2 text-right text-xs text-slate-500">{item.score.toFixed(1)}/100</p>
            </article>
          ))}
        </div>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Top 5 asset per score">
          <div className="space-y-3">
            {dashboard.top_assets.map((asset) => (
              <div key={asset.symbol} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <div>
                  <p className="font-semibold text-white">{asset.symbol}</p>
                  <p className="mt-1 text-sm text-slate-500">{asset.technical_summary ?? asset.name}</p>
                </div>
                <div className="text-right">
                  {asset.signal && <SignalBadge signal={asset.signal} />}
                  <p className="mt-2 text-sm font-semibold text-cyan-200">{asset.score?.toFixed(1)}/100</p>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Asset piu rischiosi">
          <div className="space-y-3">
            {dashboard.risky_assets.map((asset) => (
              <div key={asset.symbol} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <div>
                  <p className="font-semibold text-white">{asset.symbol}</p>
                  <p className="mt-1 text-sm text-slate-500">{asset.name}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold capitalize text-rose-200">{asset.risk_level.replace("_", " ")}</p>
                  <p className="mt-2 text-xs text-slate-500">{asset.confidence ?? "N/D"} confidence</p>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
