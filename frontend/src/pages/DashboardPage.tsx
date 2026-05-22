import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { 
  Activity, 
  BadgeDollarSign, 
  BarChart3, 
  Database, 
  Newspaper, 
  ShieldAlert, 
  TrendingUp, 
  CheckCircle2,
  AlertTriangle,
  Zap,
  PieChart as PieIcon,
  Scale,
  Bell,
  } from "lucide-react";

import { 
  Area, 
  AreaChart, 
  Cell, 
  Pie, 
  PieChart, 
  ResponsiveContainer, 
  Tooltip, 
  XAxis, 
  YAxis 
} from "recharts";

import { MetricCard } from "../components/MetricCard";
import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { 
  api,
  type DashboardResponse, 
  type PortfolioPosition, 
  type PortfolioSnapshot, 
  type ValidatedSignal 
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

export function DashboardPage() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadDashboard() {
    setLoading(true);
    setError(null);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;
      
      setDashboard(await api.dashboard(pId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento della dashboard.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  const snapshots = useMemo(() => {
    if (!dashboard) return [];
    return dashboard.portfolio_snapshots;
  }, [dashboard]);

  const assetTypeData = useMemo(() => {
    if (!dashboard) return [];
    return Object.entries(dashboard.asset_type_breakdown).map(([name, value]) => ({ name, value }));
  }, [dashboard]);

  const signalData = useMemo(() => {
    if (!dashboard) return [];
    return Object.entries(dashboard.signal_breakdown).map(([name, value]) => ({ name, value }));
  }, [dashboard]);

  if (loading && !dashboard) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 animate-pulse rounded bg-slate-800" />
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-xl border border-slate-800 bg-slate-900/50" />
          ))}
        </div>
        <div className="h-96 animate-pulse rounded-xl border border-slate-800 bg-slate-900/50" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-96 flex-col items-center justify-center gap-4 rounded-xl border border-rose-300/20 bg-rose-400/5 p-8 text-center">
        <AlertTriangle className="h-12 w-12 text-rose-400" />
        <h2 className="text-xl font-semibold text-white">Oops! Qualcosa è andato storto</h2>
        <p className="max-w-md text-slate-400">{error}</p>
        <button
          onClick={() => void loadDashboard()}
          className="mt-2 rounded-lg bg-rose-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-rose-600"
        >
          Riprova
        </button>
      </div>
    );
  }

  if (!dashboard) return null;

  return (
    <div className="space-y-6">
      <header className="flex flex-col justify-between gap-4 md:flex-row md:items-end border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-2">
             <p className="text-sm font-medium text-cyan-300">InvestEdge</p>
             <span className="text-slate-600">•</span>
             <p className="text-sm font-medium text-slate-400">Dashboard</p>
          </div>
          <h1 className="mt-2 text-3xl font-bold text-white tracking-tight">
             {dashboard.active_strategy_profile?.profile_name ? 
               `${dashboard.active_strategy_profile.profile_name} Vision` : 
               "Visione Portafoglio"}
          </h1>
          <p className="text-slate-500 text-sm mt-1">Dati basati sul portafoglio attivo e profili configurati.</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate('/portfolios')}
            className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-700"
          >
            I miei Portafogli
          </button>
          <button
            onClick={() => void loadDashboard()}
            className="rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20"
          >
            Aggiorna
          </button>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Health sistema" value={dashboard.system_health?.status.toUpperCase() || "OK"} delta="Tutti i moduli attivi" tone="cyan" icon={Activity} />
        <MetricCard label="Valore portafoglio" value={formatCurrency(dashboard.portfolio_value, "USD")} delta={`${dashboard.positions_count} posizioni aperte`} tone="green" icon={BadgeDollarSign} />
        <MetricCard label="Liquidità" value={formatCurrency(dashboard.cash, "USD")} delta={`${formatPercent(dashboard.portfolio_value > 0 ? (dashboard.cash / dashboard.portfolio_value) * 100 : 0)} del totale`} tone="amber" icon={Database} />
        <MetricCard label="P/L totale" value={formatCurrency(dashboard.total_pnl, "USD")} delta={formatPercent(dashboard.total_pnl_percent)} tone={dashboard.total_pnl >= 0 ? "green" : "rose"} icon={TrendingUp} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Andamento valore" className="lg:col-span-2">
          <div className="h-80 w-full pt-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={snapshots}>
                <defs>
                  <linearGradient id="colorVal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22D3EE" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#22D3EE" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="snapshot_date" stroke="#475569" fontSize={10} tickFormatter={(val) => new Date(val).toLocaleDateString()} />
                <YAxis stroke="#475569" fontSize={10} tickFormatter={(val) => `$${val / 1000}k`} />
                <Tooltip 
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px" }}
                  itemStyle={{ color: "#22D3EE" }}
                />
                <Area type="monotone" dataKey="total_value" stroke="#22D3EE" fillOpacity={1} fill="url(#colorVal)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Composizione asset">
          <div className="h-80 w-full pt-4">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={assetTypeData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {assetTypeData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={["#22D3EE", "#818CF8", "#F472B6", "#FB923C"][index % 4]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px" }} />
              </PieChart>
            </ResponsiveContainer>
            <div className="mt-4 flex flex-wrap justify-center gap-4">
              {assetTypeData.map((item, index) => (
                <div key={item.name} className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full" style={{ background: ["#22D3EE", "#818CF8", "#F472B6", "#FB923C"][index % 4] }} />
                  <span className="text-xs text-slate-400 uppercase font-medium">{item.name}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Migliori opportunità (Operational Ranking)" icon={<TrendingUp className="h-4 w-4 text-emerald-400" />} action={<button onClick={() => navigate('/ranking')} className="text-xs text-indigo-400 hover:text-indigo-300 font-bold uppercase">Vedi tutto</button>}>
          <div className="space-y-4">
            {dashboard.top_buy_candidates.length > 0 ? (
              dashboard.top_buy_candidates.map((signal) => (
                <div key={signal.symbol} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/50 p-3 transition hover:border-slate-700">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-800 font-bold text-white">
                      {signal.symbol[0]}
                    </div>
                    <div>
                      <p className="font-bold text-white">{signal.symbol}</p>
                      <p className="text-xs text-slate-500 uppercase">{signal.action_suggested}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <SignalBadge signal={signal.validated_signal as any} />
                    <p className="mt-1 text-[10px] text-slate-500">Quality: {signal.data_quality_score}%</p>
                  </div>
                </div>
              ))
            ) : (
              <p className="py-4 text-center text-sm text-slate-500">Nessuna opportunità BUY rilevata.</p>
            )}
          </div>
        </Panel>

        <Panel title="Sentiment & News" icon={<Newspaper className="h-4 w-4 text-blue-400" />} action={<button onClick={() => navigate('/news')} className="text-xs text-indigo-400 hover:text-indigo-300 font-bold uppercase">Tutte le news</button>}>
           <div className="flex items-center gap-6 mb-6">
              <div className="flex-1">
                 <p className="text-xs text-slate-500 uppercase font-bold mb-1">Sentiment Medio</p>
                 <div className="flex items-center gap-2">
                    <span className={`text-xl font-bold ${
                      dashboard.market_sentiment.average_sentiment_score > 0 ? 'text-emerald-400' : 
                      dashboard.market_sentiment.average_sentiment_score < 0 ? 'text-rose-400' : 'text-slate-400'
                    }`}>
                      {dashboard.market_sentiment.sentiment_label}
                    </span>
                    <span className="text-sm text-slate-500">({dashboard.market_sentiment.average_sentiment_score.toFixed(2)})</span>
                 </div>
              </div>
              <div className="flex gap-4">
                 <div className="text-center">
                    <p className="text-emerald-500 text-lg font-bold">{dashboard.market_sentiment.positive_count}</p>
                    <p className="text-[10px] text-slate-500 uppercase">Pos</p>
                 </div>
                 <div className="text-center">
                    <p className="text-rose-500 text-lg font-bold">{dashboard.market_sentiment.negative_count}</p>
                    <p className="text-[10px] text-slate-500 uppercase">Neg</p>
                 </div>
              </div>
           </div>
           
           <div className="space-y-3">
             {dashboard.high_impact_news.slice(0, 3).map((news) => (
               <div key={news.id} className="group cursor-pointer rounded-lg border border-slate-800/50 p-3 hover:bg-slate-800/30 transition-colors">
                  <div className="flex justify-between gap-2 mb-1">
                     <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                        news.impact_level === 'HIGH' ? 'bg-rose-500/20 text-rose-400' : 'bg-blue-500/20 text-blue-400'
                     }`}>
                        {news.impact_level} IMPACT
                     </span>
                     <span className="text-[9px] text-slate-500">{new Date(news.published_at || "").toLocaleDateString()}</span>
                  </div>
                  <h4 className="text-sm font-medium text-slate-200 line-clamp-1 group-hover:text-white transition-colors">{news.title}</h4>
               </div>
             ))}
           </div>
        </Panel>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <Panel title="Active Strategy" className="flex flex-col justify-between h-full">
           <div>
              <div className="flex items-center gap-2 text-indigo-400 mb-2">
                 <Zap size={16} />
                 <span className="text-xs font-bold uppercase">Profilo Strategia</span>
              </div>
              <h3 className="text-lg font-bold text-white mb-1">{dashboard.active_strategy_profile?.profile_name || "Nessuna"}</h3>
              <p className="text-xs text-slate-500 line-clamp-2">{dashboard.active_strategy_profile?.description}</p>
           </div>
           <button onClick={() => navigate('/settings')} className="mt-4 w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded transition-colors uppercase">Modifica</button>
        </Panel>

        <Panel title="Risk Profile" className="flex flex-col justify-between h-full">
           <div>
              <div className="flex items-center gap-2 text-cyan-400 mb-2">
                 <ShieldAlert size={16} />
                 <span className="text-xs font-bold uppercase">Profilo Rischio</span>
              </div>
              <h3 className="text-lg font-bold text-white mb-1">{dashboard.active_risk_profile?.profile_name || "Standard"}</h3>
              <p className="text-xs text-slate-500">Max Asset Weight: {dashboard.active_risk_profile?.max_single_asset_weight}%</p>
           </div>
           <button onClick={() => navigate('/settings')} className="mt-4 w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded transition-colors uppercase">Configura</button>
        </Panel>

        <Panel title="Strategy Control" className="flex flex-col justify-between h-full">
           <div>
              <div className="flex items-center gap-2 text-amber-400 mb-2">
                 <Scale size={16} />
                 <span className="text-xs font-bold uppercase">Ultimo Piano</span>
              </div>
              {dashboard.latest_strategy_plan ? (
                <>
                   <h3 className="text-sm font-bold text-white truncate mb-1">{dashboard.latest_strategy_plan.plan_name}</h3>
                   <div className="flex justify-between items-center text-[10px]">
                      <span className="text-slate-500">{new Date(dashboard.latest_strategy_plan.created_at).toLocaleDateString()}</span>
                      <span className="text-emerald-400 font-bold">{dashboard.latest_strategy_plan.status}</span>
                   </div>
                </>
              ) : (
                <p className="text-xs text-slate-500 italic">Nessun piano generato.</p>
              )}
           </div>
           <button onClick={() => navigate('/strategy')} className="mt-4 w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded transition-colors uppercase">Vai a Control</button>
        </Panel>

        <Panel title="System Alerts" className="flex flex-col justify-between h-full">
           <div>
              <div className="flex items-center gap-2 text-rose-400 mb-2">
                 <Bell className="h-4 w-4" />
                 <span className="text-xs font-bold uppercase">Anomalie</span>
              </div>
              <div className="flex items-end gap-2">
                 <span className="text-3xl font-bold text-white">{dashboard.open_alerts_summary?.open_count || 0}</span>
                 <span className="text-xs text-slate-500 mb-1">Aperti</span>
              </div>
              {dashboard.open_alerts_summary?.critical_count ? (
                <p className="text-[10px] text-rose-500 font-bold mt-1 uppercase tracking-tighter">! {dashboard.open_alerts_summary.critical_count} Critici rilevati</p>
              ) : null}
           </div>
           <button onClick={() => navigate('/alerts')} className="mt-4 w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded transition-colors uppercase">Apri Center</button>
        </Panel>
      </div>
    </div>
  );
}
