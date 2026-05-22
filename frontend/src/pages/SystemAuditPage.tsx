import { useEffect, useState } from "react";
import { Activity, CheckCircle2, AlertTriangle, XCircle, Database, Server, Zap, ShieldAlert, ShieldCheck } from "lucide-react";
import { Panel } from "../components/Panel";
import { api, type SystemHealth, type DataQualityCheck, type HardeningReport } from "../lib/api";

export function SystemAuditPage() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [quality, setQuality] = useState<DataQualityCheck[]>([]);
  const [hardening, setHardening] = useState<HardeningReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [h, q, hard] = await Promise.all([
        api.getSystemHealth(),
        api.getAllDataQuality(),
        api.getHardeningReport(),
      ]);
      setHealth(h);
      setQuality(q);
      setHardening(hard);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento dei dati di audit.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  if (loading) return <div className="p-8 text-center">Caricamento audit di sistema...</div>;
  if (error) return <div className="p-8 text-center text-red-500">{error}</div>;

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "healthy":
      case "connected":
        return <CheckCircle2 className="w-5 h-5 text-emerald-500" />;
      case "degraded":
      case "no_api_key":
        return <AlertTriangle className="w-5 h-5 text-amber-500" />;
      default:
        return <XCircle className="w-5 h-5 text-rose-500" />;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <ShieldAlert className="w-6 h-6 text-indigo-500" />
          System Audit & Data Quality
        </h1>
        <button
          onClick={loadData}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors text-sm font-medium"
        >
          Aggiorna Audit
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Panel title="Stato Sistema" icon={<Activity className="w-5 h-5 text-indigo-500" />}>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Status Generale</span>
              <div className="flex items-center gap-2">
                {getStatusIcon(health?.status || "")}
                <span className="capitalize font-medium">{health?.status}</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Database</span>
              <div className="flex items-center gap-2">
                {getStatusIcon(health?.database || "")}
                <span className="capitalize">{health?.database}</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Cache</span>
              <span className="text-sm">{health?.cache}</span>
            </div>
            <div className="text-xs text-slate-500 mt-2">
              Ultimo controllo: {health?.timestamp && new Date(health.timestamp).toLocaleString()}
            </div>
          </div>
        </Panel>

        <Panel title="Provider Dati" icon={<Server className="w-5 h-5 text-indigo-500" />}>
          <div className="space-y-3">
            {health && Object.entries(health.providers).map(([name, status]) => (
              <div key={name} className="flex items-center justify-between">
                <span className="text-slate-400 capitalize">{name}</span>
                <div className="flex items-center gap-2">
                  {getStatusIcon(status)}
                  <span className="text-xs">{status}</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Metriche Qualità" icon={<Zap className="w-5 h-5 text-indigo-500" />}>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Media Score</span>
              <span className="text-xl font-bold text-indigo-400">
                {(quality.reduce((acc, q) => acc + q.score, 0) / (quality.length || 1)).toFixed(1)}%
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Asset Validi</span>
              <span className="font-medium text-emerald-400">
                {quality.filter(q => q.is_valid).length} / {quality.length}
              </span>
            </div>
          </div>
        </Panel>

        <Panel title="Hardening" icon={<ShieldCheck className="w-5 h-5 text-emerald-500" />}>
           <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Security Status</span>
                <span className={`font-bold ${hardening?.overall_status === 'OK' ? 'text-emerald-400' : 'text-amber-400'}`}>
                   {hardening?.overall_status}
                </span>
              </div>
              <div className="space-y-1">
                 {hardening?.checks.slice(0, 3).map((c, i) => (
                    <div key={i} className="flex items-center gap-2 text-[10px]">
                       {c.status === 'OK' ? <CheckCircle2 className="w-3 h-3 text-emerald-500" /> : <AlertTriangle className="w-3 h-3 text-amber-500" />}
                       <span className="text-slate-400 truncate">{c.check_name}</span>
                    </div>
                 ))}
              </div>
           </div>
        </Panel>
      </div>

      <Panel title="Dettaglio Qualità Dati per Asset">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 text-sm">
                <th className="pb-3 font-medium">Symbol</th>
                <th className="pb-3 font-medium">Score</th>
                <th className="pb-3 font-medium">Grade</th>
                <th className="pb-3 font-medium">History</th>
                <th className="pb-3 font-medium">Real Data</th>
                <th className="pb-3 font-medium">Freshness</th>
                <th className="pb-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {quality.map((q) => (
                <tr key={q.symbol} className="hover:bg-slate-800/50 transition-colors">
                  <td className="py-4 font-bold text-indigo-400">{q.symbol}</td>
                  <td className="py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-2 bg-slate-700 rounded-full overflow-hidden">
                        <div 
                          className={`h-full ${q.score >= 80 ? 'bg-emerald-500' : q.score >= 50 ? 'bg-amber-500' : 'bg-rose-500'}`}
                          style={{ width: `${q.score}%` }}
                        />
                      </div>
                      <span className="text-xs">{q.score.toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="py-4">
                    <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                      q.grade === 'A' ? 'bg-emerald-500/20 text-emerald-400' :
                      q.grade === 'B' ? 'bg-blue-500/20 text-blue-400' :
                      q.grade === 'C' ? 'bg-amber-500/20 text-amber-400' :
                      'bg-rose-500/20 text-rose-400'
                    }`}>
                      {q.grade}
                    </span>
                  </td>
                  <td className="py-4 text-sm">{q.details.history_length} days</td>
                  <td className="py-4 text-sm">{q.checks.real_data ? 'Yes' : 'No'}</td>
                  <td className="py-4 text-sm">{q.details.days_since_last}d ago</td>
                  <td className="py-4">
                    {q.is_valid ? 
                      <span className="text-xs text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3"/> Valid</span> :
                      <span className="text-xs text-rose-400 flex items-center gap-1"><XCircle className="w-3 h-3"/> Excluded</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
