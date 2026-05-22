import { useEffect, useState } from "react";
import { 
  Bell, 
  AlertTriangle, 
  Info, 
  XCircle, 
  CheckCircle2, 
  Clock, 
  Filter,
  RefreshCw,
  Settings
} from "lucide-react";
import { Panel } from "../components/Panel";
import { api, type Alert, type AlertSummary, type AlertRule } from "../lib/api";

export function AlertCenterPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [summary, setSummary] = useState<AlertSummary | null>(null);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterSeverity, setFilterSeverity] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("OPEN");

  async function loadData() {
    setLoading(true);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const [alertsData, summaryData, rulesData] = await Promise.all([
        api.listAlerts(filterStatus, filterSeverity, undefined, pId),
        api.getAlertSummary(pId),
        api.getAlertRules()
      ]);
      setAlerts(alertsData);
      setSummary(summaryData);
      setRules(rulesData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento alert.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [filterSeverity, filterStatus]);

  async function handleAcknowledge(id: number) {
    await api.acknowledgeAlert(id);
    loadData();
  }

  async function handleClose(id: number) {
    await api.closeAlert(id);
    loadData();
  }

  async function handleToggleRule(id: number, enabled: boolean) {
    await api.toggleAlertRule(id, !enabled);
    loadData();
  }

  async function handleEvaluate() {
    setLoading(true);
    await api.evaluateAlerts();
    loadData();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Bell className="w-6 h-6 text-indigo-500" />
          Alert Center
        </h1>
        <div className="flex gap-2">
          <button 
            onClick={handleEvaluate}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors text-sm font-medium flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" /> Valuta Regole Ora
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <AlertStatCard label="Aperti" value={summary?.open_count || 0} icon={<Bell className="w-4 h-4" />} color="indigo" />
        <AlertStatCard label="Critici" value={summary?.critical_count || 0} icon={<XCircle className="w-4 h-4" />} color="rose" />
        <AlertStatCard label="Warning" value={summary?.warning_count || 0} icon={<AlertTriangle className="w-4 h-4" />} color="amber" />
        <AlertStatCard label="Info" value={summary?.info_count || 0} icon={<Info className="w-4 h-4" />} color="blue" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <Panel title="Filtri" icon={<Filter className="w-4 h-4" />}>
            <div className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs text-slate-500">Stato</label>
                <select 
                  value={filterStatus} 
                  onChange={e => setFilterStatus(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
                >
                  <option value="OPEN">Aperti</option>
                  <option value="ACKNOWLEDGED">Presi in carico</option>
                  <option value="CLOSED">Chiusi</option>
                  <option value="">Tutti</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-slate-500">Severità</label>
                <select 
                  value={filterSeverity} 
                  onChange={e => setFilterSeverity(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
                >
                  <option value="">Tutte</option>
                  <option value="CRITICAL">Critical</option>
                  <option value="WARNING">Warning</option>
                  <option value="INFO">Info</option>
                </select>
              </div>
            </div>
          </Panel>

          <Panel title="Regole Alert" icon={<Settings className="w-4 h-4" />}>
            <div className="space-y-3">
              {rules.map(rule => (
                <div key={rule.id} className="flex items-center justify-between group">
                  <div className="flex flex-col">
                    <span className="text-[11px] font-medium text-slate-300 truncate max-w-[120px]">{rule.rule_name}</span>
                    <span className="text-[9px] text-slate-500">{rule.severity}</span>
                  </div>
                  <button 
                    onClick={() => handleToggleRule(rule.id, rule.enabled)}
                    className={`w-7 h-4 rounded-full transition-colors relative ${rule.enabled ? 'bg-indigo-600' : 'bg-slate-700'}`}
                  >
                    <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${rule.enabled ? 'left-3.5' : 'left-0.5'}`} />
                  </button>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {loading ? (
            <div className="p-12 text-center text-slate-500 italic">Caricamento alert...</div>
          ) : alerts.length > 0 ? (
            alerts.map(alert => (
              <div 
                key={alert.id}
                className={`p-4 rounded-xl border flex gap-4 transition-all ${
                  alert.severity === 'CRITICAL' ? 'bg-rose-500/5 border-rose-500/20' :
                  alert.severity === 'WARNING' ? 'bg-amber-500/5 border-amber-500/20' :
                  'bg-slate-900/40 border-slate-800'
                }`}
              >
                <div className="mt-1">
                  {alert.severity === 'CRITICAL' ? <XCircle className="w-5 h-5 text-rose-500" /> :
                   alert.severity === 'WARNING' ? <AlertTriangle className="w-5 h-5 text-amber-500" /> :
                   <Info className="w-5 h-5 text-blue-500" />}
                </div>
                <div className="flex-1 space-y-1">
                  <div className="flex items-center justify-between">
                    <h3 className="font-bold text-slate-100 flex items-center gap-2">
                      {alert.symbol && <span className="text-indigo-400">[{alert.symbol}]</span>}
                      {alert.title}
                    </h3>
                    <span className="text-[10px] text-slate-500 flex items-center gap-1">
                      <Clock className="w-3 h-3" /> {new Date(alert.created_at).toLocaleString()}
                    </span>
                  </div>
                  <p className="text-sm text-slate-400">{alert.message}</p>
                  <div className="pt-2 flex items-center justify-between">
                    <span className="text-[10px] text-slate-600 uppercase font-bold tracking-wider">{alert.source_module}</span>
                    <div className="flex gap-2">
                      {alert.status === 'OPEN' && (
                        <button 
                          onClick={() => handleAcknowledge(alert.id)}
                          className="px-2 py-1 text-[10px] font-bold bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                        >
                          Presa in carico
                        </button>
                      )}
                      {alert.status !== 'CLOSED' && (
                        <button 
                          onClick={() => handleClose(alert.id)}
                          className="px-2 py-1 text-[10px] font-bold bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-400 rounded border border-indigo-500/30"
                        >
                          Chiudi Alert
                        </button>
                      )}
                      {alert.status === 'CLOSED' && (
                        <span className="text-[10px] text-emerald-500 flex items-center gap-1 font-bold">
                          <CheckCircle2 className="w-3 h-3" /> Chiuso il {alert.closed_at && new Date(alert.closed_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="h-[300px] flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-xl bg-slate-900/20 text-slate-500">
              <CheckCircle2 className="w-12 h-12 mb-4 text-emerald-500/20" />
              <p className="text-lg font-medium">Nessun alert attivo</p>
              <p className="text-sm">Il sistema è monitorato e non ci sono anomalie.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AlertStatCard({ label, value, icon, color }: { label: string, value: number, icon: React.ReactNode, color: string }) {
  const colors: Record<string, string> = {
    indigo: "text-indigo-400 border-indigo-500/20 bg-indigo-500/5",
    rose: "text-rose-400 border-rose-500/20 bg-rose-500/5",
    amber: "text-amber-400 border-amber-500/20 bg-amber-500/5",
    blue: "text-blue-400 border-blue-500/20 bg-blue-500/5",
  };
  
  return (
    <div className={`p-4 rounded-xl border ${colors[color]} flex items-center justify-between`}>
      <div className="space-y-1">
        <p className="text-xs uppercase font-bold tracking-wider opacity-60">{label}</p>
        <p className="text-2xl font-bold">{value}</p>
      </div>
      {icon}
    </div>
  );
}
