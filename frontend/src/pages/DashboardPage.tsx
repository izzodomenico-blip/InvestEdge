import { useEffect, useMemo, useState } from "react";
import { Activity, BadgeDollarSign, BarChart3, Database, Newspaper, ShieldAlert, TrendingUp, CheckCircle2, AlertTriangle, ShieldCheck } from "lucide-react";
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

      <Panel title="Universe Manager">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Universe totale</p>
            <p className="mt-1 font-semibold text-white">{dashboard.universe_summary.total_assets}</p>
            <p className="mt-1 text-xs text-slate-500">{dashboard.universe_summary.priced_assets_count} con storico prezzi</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Core universe</p>
            <p className="mt-1 font-semibold text-cyan-200">{dashboard.universe_summary.core_count}</p>
            <p className="mt-1 text-xs text-slate-500">Default training ML</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Watchlist</p>
            <p className="mt-1 font-semibold text-emerald-300">{dashboard.universe_summary.watchlist_count}</p>
            <p className="mt-1 text-xs text-slate-500">Asset monitorati in UI</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Refresh candidates</p>
            <p className="mt-1 font-semibold text-amber-300">{dashboard.universe_summary.refresh_candidates_count}</p>
            <p className="mt-1 text-xs text-slate-500">Refresh-all limitato</p>
          </div>
        </div>
      </Panel>

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

      <Panel title="Machine Learning">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">ML status</p>
            <p className={dashboard.ml_status.ml_ready ? "mt-1 font-semibold text-emerald-300" : "mt-1 font-semibold text-amber-300"}>
              {dashboard.ml_status.ml_ready ? "READY" : "NO MODEL"}
            </p>
            <p className="mt-1 text-xs text-slate-500">{dashboard.ml_status.message}</p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Ultimo modello</p>
            <p className="mt-1 font-semibold text-white">{dashboard.ml_status.latest_model?.model_name ?? "N/D"}</p>
            <p className="mt-1 text-xs text-slate-500">
              {dashboard.ml_status.latest_model ? `${dashboard.ml_status.latest_model.model_type} ${dashboard.ml_status.latest_model.horizon_days}d` : "Addestra da AI Lab"}
            </p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Ultima prediction</p>
            <p className="mt-1 font-semibold text-cyan-200">{dashboard.latest_ml_prediction?.symbol ?? "N/D"}</p>
            <p className="mt-1 text-xs text-slate-500">
              {dashboard.latest_ml_prediction ? `${dashboard.latest_ml_prediction.predicted_label} · ${dashboard.latest_ml_prediction.confidence}` : "Nessuna prediction salvata"}
            </p>
          </div>
        </div>
      </Panel>

      <Panel title="System Audit & Operational Ranking" icon={<ShieldCheck className="w-5 h-5 text-indigo-400" />}>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-500">Health di Sistema</p>
              {dashboard.system_health?.status === 'healthy' ? 
                <CheckCircle2 className="w-4 h-4 text-emerald-500" /> : 
                <AlertTriangle className="w-4 h-4 text-amber-500" />
              }
            </div>
            <p className="mt-1 font-semibold text-white capitalize">{dashboard.system_health?.status || 'N/D'}</p>
            <p className="mt-1 text-xs text-slate-500">DB: {dashboard.system_health?.database}</p>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Top Buy Candidates</p>
            <div className="mt-2 space-y-1">
              {dashboard.top_buy_candidates.length > 0 ? (
                dashboard.top_buy_candidates.slice(0, 3).map(s => (
                  <div key={s.symbol} className="flex items-center justify-between text-xs">
                    <span className="font-bold text-indigo-400">{s.symbol}</span>
                    <span className="text-emerald-400 font-medium">Valid {s.validated_signal}</span>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-600 italic">Nessun candidato BUY validato</p>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-sm text-slate-500">Data Quality Warnings</p>
            <div className="mt-2 space-y-1">
              {dashboard.data_quality_warnings.length > 0 ? (
                dashboard.data_quality_warnings.slice(0, 3).map((w, i) => (
                  <p key={i} className="text-[10px] text-amber-400 font-medium truncate">{w}</p>
                ))
              ) : (
                <p className="text-xs text-emerald-500 font-medium">Tutti i dati sono validi</p>
              )}
            </div>
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

      <div className="grid gap-6 xl:grid-cols-[1.4fr_0.9fr]">
        <Panel title="Ultime news high impact">
          {dashboard.high_impact_news.length === 0 ? (
            <p className="text-sm text-slate-400">
              Nessuna news high impact disponibile. Aggiorna le news dal modulo dedicato.
            </p>
          ) : (
            <div className="space-y-3">
              {dashboard.high_impact_news.slice(0, 5).map((item) => (
                <article key={item.id} className="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900/60 p-4 md:flex-row md:items-start md:justify-between">
                  <div className="flex gap-3">
                    <span className="mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-700 bg-slate-950 text-slate-300">
                      <Newspaper className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div>
                      <p className="text-xs uppercase text-slate-500">
                        {item.symbol ?? "mercato"} · {item.source ?? "fonte"} · {item.published_at ?? "N/D"}
                      </p>
                      <p className="mt-1 text-sm font-semibold text-white">{item.title}</p>
                    </div>
                  </div>
                  <span
                    className={`inline-flex w-fit rounded-md border px-2 py-1 text-xs font-semibold ${
                      item.sentiment_label === "POSITIVE"
                        ? "border-emerald-300/30 bg-emerald-400/10 text-emerald-200"
                        : item.sentiment_label === "NEGATIVE"
                          ? "border-rose-300/30 bg-rose-400/10 text-rose-200"
                          : "border-slate-700 bg-slate-900 text-slate-200"
                    }`}
                  >
                    {item.sentiment_label}
                  </span>
                </article>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Sentiment mercato">
          {dashboard.market_sentiment.news_count === 0 ? (
            <p className="text-sm text-slate-400">
              Nessuna news disponibile per stimare il sentiment del mercato.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Average sentiment</p>
                <p
                  className={`mt-1 text-2xl font-semibold ${
                    dashboard.market_sentiment.sentiment_label === "POSITIVE"
                      ? "text-emerald-300"
                      : dashboard.market_sentiment.sentiment_label === "NEGATIVE"
                        ? "text-rose-300"
                        : "text-slate-200"
                  }`}
                >
                  {dashboard.market_sentiment.average_sentiment_score.toFixed(2)}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {dashboard.market_sentiment.sentiment_label} · {dashboard.market_sentiment.news_count} news
                </p>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-md border border-emerald-300/20 bg-emerald-400/10 p-2 text-emerald-200">
                  <p className="font-semibold">{dashboard.market_sentiment.positive_count}</p>
                  <p>positive</p>
                </div>
                <div className="rounded-md border border-slate-700 bg-slate-900 p-2 text-slate-300">
                  <p className="font-semibold">{dashboard.market_sentiment.neutral_count}</p>
                  <p>neutral</p>
                </div>
                <div className="rounded-md border border-rose-300/20 bg-rose-400/10 p-2 text-rose-200">
                  <p className="font-semibold">{dashboard.market_sentiment.negative_count}</p>
                  <p>negative</p>
                </div>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
