import { useEffect, useMemo, useState } from "react";
import { Activity, BadgeDollarSign, BarChart3, Database, PieChart as PieIcon } from "lucide-react";
import {
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
import { formatCurrency } from "../lib/format";

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
          <p className="mt-3 text-sm text-slate-500">Esegui `python scripts/seed_database.py --reset` e ricarica la pagina.</p>
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
        <MetricCard label="Righe prezzo" value={dashboard.price_points_count.toLocaleString("it-IT")} delta="Storico deterministico SQLite" tone="green" icon={Database} />
        <MetricCard label="Score medio" value={dashboard.average_score?.toFixed(1) ?? "N/D"} delta={`${dashboard.signals_count} segnali calcolati`} tone="amber" icon={BarChart3} />
        <MetricCard label="Valore portfolio" value={formatCurrency(dashboard.portfolio_value)} delta="In attesa di posizioni personali" tone="rose" icon={BadgeDollarSign} />
      </div>

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
    </div>
  );
}
