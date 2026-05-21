import { useEffect, useState } from "react";
import { 
  Play, 
  Clock, 
  CheckCircle2, 
  AlertTriangle, 
  XCircle, 
  RefreshCw, 
  Zap,
  BarChart,
  ShieldCheck,
  Bell,
  FileText
} from "lucide-react";
import { Panel } from "../components/Panel";
import { api, type SchedulerRun } from "../lib/api";

export function SchedulerPage() {
  const [runs, setRuns] = useState<SchedulerRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(10);
  const [force, setForce] = useState(false);
  const [generateReport, setGenerateReport] = useState(true);

  async function loadRuns() {
    setLoading(true);
    try {
      setRuns(await api.listSchedulerRuns());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento cronologia scheduler.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadRuns();
  }, []);

  async function handleRun(type: string) {
    setExecuting(true);
    setError(null);
    try {
      await api.runScheduler({
        run_type: type,
        limit: type.includes('DATA') || type === 'FULL_MANUAL' ? limit : undefined,
        force,
        generate_report: generateReport
      });
      loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'esecuzione del ciclo.");
    } finally {
      setExecuting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Clock className="w-6 h-6 text-indigo-500" />
          Scheduler & Operations
        </h1>
        <button 
          onClick={loadRuns}
          className="p-2 hover:bg-slate-800 rounded-lg transition-colors"
          title="Aggiorna cronologia"
        >
          <RefreshCw className={`w-5 h-5 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-lg text-rose-400 text-sm flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 flex-shrink-0" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <Panel title="Configurazione Ciclo" icon={<Zap className="w-4 h-4" />}>
            <div className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs text-slate-500">Asset Limit (per Refresh)</label>
                <input 
                  type="number" 
                  value={limit} 
                  onChange={e => setLimit(parseInt(e.target.value))}
                  className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
                />
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-slate-900/60 border border-slate-800">
                <span className="text-xs text-slate-400">Force Refresh</span>
                <button 
                  onClick={() => setForce(!force)}
                  className={`w-8 h-4 rounded-full transition-colors relative ${force ? 'bg-indigo-600' : 'bg-slate-700'}`}
                >
                  <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${force ? 'left-4.5' : 'left-0.5'}`} />
                </button>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-slate-900/60 border border-slate-800">
                <span className="text-xs text-slate-400">Genera Report Finale</span>
                <button 
                  onClick={() => setGenerateReport(!generateReport)}
                  className={`w-8 h-4 rounded-full transition-colors relative ${generateReport ? 'bg-indigo-600' : 'bg-slate-700'}`}
                >
                  <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${generateReport ? 'left-4.5' : 'left-0.5'}`} />
                </button>
              </div>
            </div>
          </Panel>

          <Panel title="Comandi Manuali" icon={<Play className="w-4 h-4" />}>
            <div className="grid grid-cols-1 gap-2">
              <SchedulerButton 
                label="Full Manual Cycle" 
                onClick={() => handleRun('FULL_MANUAL')} 
                executing={executing} 
                variant="indigo" 
                icon={<Zap className="w-4 h-4" />}
              />
              <div className="grid grid-cols-2 gap-2 mt-2">
                <SchedulerButton label="Data Refresh" onClick={() => handleRun('DATA_REFRESH')} executing={executing} icon={<RefreshCw className="w-3 h-3" />} />
                <SchedulerButton label="Audit Quality" onClick={() => handleRun('QUALITY')} executing={executing} icon={<ShieldCheck className="w-3 h-3" />} />
                <SchedulerButton label="Recalc Ranking" onClick={() => handleRun('RANKING')} executing={executing} icon={<BarChart className="w-3 h-3" />} />
                <SchedulerButton label="Eval Alerts" onClick={() => handleRun('ALERTS')} executing={executing} icon={<Bell className="w-3 h-3" />} />
              </div>
              <SchedulerButton 
                label="Genera Report Ora" 
                onClick={() => handleRun('REPORT')} 
                executing={executing} 
                variant="slate" 
                icon={<FileText className="w-4 h-4" />}
                className="mt-2"
              />
            </div>
          </Panel>
        </div>

        <div className="lg:col-span-2">
          <Panel title="Cronologia Scheduler Runs" icon={<Clock className="w-4 h-4" />}>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500 text-[10px] uppercase">
                    <th className="pb-3 font-medium">Data / Tipo</th>
                    <th className="pb-3 font-medium text-center">Status</th>
                    <th className="pb-3 font-medium text-right">Durata</th>
                    <th className="pb-3 font-medium">Summary</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {runs.map(run => (
                    <tr key={run.id} className="hover:bg-slate-800/20">
                      <td className="py-4">
                        <div className="flex flex-col">
                          <span className="text-sm font-bold text-slate-200">{run.run_type}</span>
                          <span className="text-[10px] text-slate-500">{new Date(run.started_at).toLocaleString()}</span>
                        </div>
                      </td>
                      <td className="py-4 text-center">
                        <div className="flex justify-center">
                          {run.status === 'SUCCESS' ? <CheckCircle2 className="w-4 h-4 text-emerald-500" /> :
                           run.status === 'WARNING' ? <AlertTriangle className="w-4 h-4 text-amber-500" /> :
                           <XCircle className="w-4 h-4 text-rose-500" />}
                        </div>
                      </td>
                      <td className="py-4 text-right text-xs tabular-nums text-slate-400">
                        {run.duration_seconds?.toFixed(1)}s
                      </td>
                      <td className="py-4 pl-6">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(run.summary).map(([key, val]) => (
                            <span key={key} className="text-[9px] px-1 bg-slate-800 text-slate-400 rounded">
                              {key}: {typeof val === 'object' ? JSON.stringify(val) : val}
                            </span>
                          ))}
                          {run.errors.map((err, i) => (
                            <span key={i} className="text-[9px] px-1 bg-rose-500/10 text-rose-400 rounded truncate max-w-[100px]" title={err}>
                              err: {err}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function SchedulerButton({ label, onClick, executing, variant = "slate", icon, className = "" }: { 
  label: string, 
  onClick: () => void, 
  executing: boolean, 
  variant?: "indigo" | "slate",
  icon?: React.ReactNode,
  className?: string
}) {
  const base = "px-3 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-2 disabled:opacity-50";
  const variants = {
    indigo: "bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg shadow-indigo-900/20",
    slate: "bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700"
  };
  
  return (
    <button 
      onClick={onClick} 
      disabled={executing} 
      className={`${base} ${variants[variant]} ${className}`}
    >
      {icon}
      {label}
    </button>
  );
}
