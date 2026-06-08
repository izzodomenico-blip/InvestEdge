import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, AlertTriangle, BadgeDollarSign, BarChart3, CheckCircle2, Database, FlaskConical, RefreshCw, ShieldAlert, TrendingUp } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
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

const newsSentimentTone: Record<string, string> = {
  POSITIVE: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
  NEUTRAL: "border-cyan-300/30 bg-cyan-400/10 text-cyan-200",
  NEGATIVE: "border-rose-300/30 bg-rose-400/10 text-rose-200",
};

const newsImpactTone: Record<string, string> = {
  HIGH: "border-rose-300/30 bg-rose-400/10 text-rose-200",
  MEDIUM: "border-amber-300/30 bg-amber-400/10 text-amber-200",
  LOW: "border-slate-700 bg-slate-900 text-slate-300",
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
      <PageHeader
        eyebrow="InvestEdge / Cockpit"
        index="01"
        title="Dashboard"
        subtitle="Panoramica unificata di portafoglio, segnali, news e stato dati. Aggiornata su richiesta, senza chiamate API automatiche."
        meta={
          <>
            <span>
              Asset <span className="text-cyan-300/80">{dashboard.assets_count}</span>
            </span>
            <span>
              Posizioni <span className="text-cyan-300/80">{dashboard.positions_count}</span>
            </span>
            <span>
              Segnali <span className="text-cyan-300/80">{dashboard.signals_count}</span>
            </span>
          </>
        }
        actions={
          <PageHeaderAction
            variant="primary"
            icon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
            onClick={() => void loadDashboard()}
          >
            Aggiorna
          </PageHeaderAction>
        }
      />

      <DataModeBanner mode={dashboard.data_status.data_mode} enableRealData={dashboard.data_status.enable_real_data} />

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

      <div className="grid gap-6 xl:grid-cols-[0.8fr_1.2fr]">
        <Panel title="Market news sentiment">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Sentiment</p>
              <span className={`mt-2 inline-flex rounded-md border px-2.5 py-1 text-xs font-semibold ${newsSentimentTone[dashboard.market_news_summary.sentiment_label] ?? newsSentimentTone.NEUTRAL}`}>
                {dashboard.market_news_summary.sentiment_label ?? "NEUTRAL"}
              </span>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">News count</p>
              <p className="mt-1 font-semibold text-white">{dashboard.market_news_summary.news_count ?? 0}</p>
              <p className="mt-1 text-xs text-slate-500">Ultimi 7 giorni</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Impatto</p>
              <span className={`mt-2 inline-flex rounded-md border px-2.5 py-1 text-xs font-semibold ${newsImpactTone[dashboard.market_news_summary.impact_level] ?? newsImpactTone.LOW}`}>
                {dashboard.market_news_summary.impact_level ?? "LOW"}
              </span>
            </div>
          </div>
        </Panel>

        <Panel title="Ultime news high impact">
          <div className="space-y-3">
            {dashboard.latest_high_impact_news.map((item) => (
              <article key={`${item.id}-${item.title}`} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase text-slate-500">{item.symbol ?? "N/D"} - {item.source ?? "N/D"}</p>
                    <p className="mt-2 line-clamp-2 text-sm font-semibold text-white">{item.title}</p>
                  </div>
                  <span className={`inline-flex shrink-0 rounded-md border px-2.5 py-1 text-xs font-semibold ${newsSentimentTone[item.sentiment_label ?? "NEUTRAL"] ?? newsSentimentTone.NEUTRAL}`}>
                    {item.sentiment_label ?? "NEUTRAL"}
                  </span>
                </div>
              </article>
            ))}
            {dashboard.latest_high_impact_news.length === 0 && (
              <p className="text-sm text-slate-400">Nessuna news high impact salvata.</p>
            )}
          </div>
        </Panel>
      </div>

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

type DataModeBannerProps = {
  mode: "SEED" | "MIXED" | "REAL";
  enableRealData: boolean;
};

function DataModeBanner({ mode, enableRealData }: DataModeBannerProps) {
  if (mode === "REAL" && enableRealData) {
    return (
      <div className="relative overflow-hidden rounded-2xl border border-emerald-300/25 bg-gradient-to-br from-emerald-400/[0.08] via-slate-950/40 to-slate-950/60 p-5 shadow-panel">
        <div aria-hidden="true" className="pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full bg-emerald-400/20 blur-3xl" />
        <div className="relative flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-4">
            <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-emerald-300/30 bg-emerald-400/10 text-emerald-200">
              <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <p className="eyebrow text-emerald-300/90">Stato dati / live</p>
              <p className="mt-1 font-display text-lg font-medium leading-tight text-white">
                Stai vedendo dati reali.
              </p>
              <p className="mt-1 max-w-xl text-sm text-emerald-100/80">
                Tutti i prezzi nel database provengono da provider esterni configurati.
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (mode === "MIXED") {
    return (
      <div className="relative overflow-hidden rounded-2xl border border-cyan-300/25 bg-gradient-to-br from-cyan-400/[0.08] via-slate-950/40 to-slate-950/60 p-5 shadow-panel">
        <div aria-hidden="true" className="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-cyan-400/20 blur-3xl" />
        <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-4">
            <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-cyan-300/30 bg-cyan-400/10 text-cyan-200">
              <Database className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <p className="eyebrow">Stato dati / misti</p>
              <p className="mt-1 font-display text-lg font-medium leading-tight text-white">
                Dataset misto: reale + seed.
              </p>
              <p className="mt-1 max-w-xl text-sm text-cyan-100/80">
                Alcuni asset hanno prezzi reali, altri usano ancora dati seed. Aggiorna i restanti dal Data Center.
              </p>
            </div>
          </div>
          <Link
            to="/data"
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-cyan-300/40 bg-cyan-400/15 px-4 py-2.5 text-sm font-medium text-cyan-50 transition-all hover:border-cyan-300/60 hover:bg-cyan-400/25 hover:shadow-glow"
          >
            Apri Data Center →
          </Link>
        </div>
      </div>
    );
  }

  const title = enableRealData
    ? "Stai vedendo dati simulati."
    : "Stai vedendo dati simulati (modalita demo).";
  const subtitle = enableRealData
    ? "Real data abilitati ma nessun asset ancora aggiornato. Apri il Data Center e clicca Aggiorna tutti i dati."
    : "ENABLE_REAL_DATA=false. Configura backend/.env con le tue API key, poi torna qui per attivare dati reali.";

  return (
    <div className="relative overflow-hidden rounded-2xl border border-amber-300/30 bg-gradient-to-br from-amber-400/[0.09] via-slate-950/40 to-slate-950/60 p-5 shadow-panel">
      <div aria-hidden="true" className="pointer-events-none absolute -right-20 -top-24 h-56 w-56 rounded-full bg-amber-400/15 blur-3xl" />
      <div aria-hidden="true" className="pointer-events-none absolute -left-12 -bottom-16 h-40 w-40 rounded-full bg-rose-400/8 blur-3xl" />
      <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-4">
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-amber-300/30 bg-amber-400/10 text-amber-200">
            <FlaskConical className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <p className="eyebrow text-amber-300/90">Stato dati / sandbox</p>
            <p className="mt-1 font-display text-lg font-medium leading-tight text-white">
              {title}
            </p>
            <p className="mt-1 max-w-xl text-sm text-amber-100/85">{subtitle}</p>
          </div>
        </div>
        <Link
          to="/data"
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-amber-300/40 bg-amber-400/15 px-4 py-2.5 text-sm font-medium text-amber-50 transition-all hover:border-amber-300/60 hover:bg-amber-400/25"
        >
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
          Apri Data Center
        </Link>
      </div>
    </div>
  );
}
