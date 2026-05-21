import { useEffect, useState } from "react";
import { 
  Zap, 
  History, 
  Trash2, 
  AlertTriangle, 
  CheckCircle2, 
  TrendingDown, 
  TrendingUp, 
  BarChart3, 
  PieChart as PieIcon,
  ChevronDown,
  ChevronRight,
  Filter,
  RefreshCw,
  Settings,
  ShieldAlert,
  ArrowRight,
  Info
} from "lucide-react";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  Tooltip as RechartsTooltip, 
  ResponsiveContainer, 
  Cell,
  Legend,
  PieChart,
  Pie
} from "recharts";
import { Panel } from "../components/Panel";
import { 
  api, 
  type ScenarioConfig, 
  type ScenarioRunFull, 
  type ScenarioRunSummary 
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#3b82f6', '#ec4899', '#8b5cf6', '#06b6d4', '#f43f5e'];

export function ScenarioAnalysisPage() {
  const [runs, setRuns] = useState<ScenarioRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<ScenarioRunFull | null>(null);
  const [config, setConfig] = useState<ScenarioConfig | null>(null);
  const [presets, setPresets] = useState<{ id: string, label: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(true);

  async function loadInitialData() {
    setLoading(true);
    try {
      const [runsData, defaultConfig, presetsData] = await Promise.all([
        api.listScenarioRuns(),
        api.getDefaultScenarioConfig(),
        api.getScenarioPresets()
      ]);
      setRuns(runsData);
      setConfig(defaultConfig);
      setPresets(presetsData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento dati.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadInitialData();
  }, []);

  async function handleRun() {
    if (!config) return;
    setRunning(true);
    setError(null);
    try {
      const result = await api.runScenarioAnalysis(config);
      setSelectedRun(result);
      setRuns(await api.listScenarioRuns());
      setShowConfig(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante lo stress test.");
    } finally {
      setRunning(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Eliminare questa simulazione?")) return;
    try {
      await api.deleteScenarioRun(id);
      setRuns(runs.filter(r => r.id !== id));
      if (selectedRun?.summary.id === id) setSelectedRun(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'eliminazione.");
    }
  }

  async function handleSelectRun(id: number) {
    setLoading(true);
    try {
      setSelectedRun(await api.getScenarioRun(id));
      setShowConfig(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento dettaglio.");
    } finally {
      setLoading(false);
    }
  }

  const lossData = selectedRun?.asset_impacts
    .sort((a, b) => a.absolute_impact - b.absolute_impact)
    .slice(0, 10)
    .map(i => ({ name: i.symbol, value: Math.abs(i.absolute_impact) })) || [];

  if (loading && runs.length === 0) return <div className="p-8 text-center">Caricamento Scenario Analysis...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <ShieldAlert className="w-6 h-6 text-indigo-500" />
          Scenario Analysis & Stress Test
        </h1>
        <div className="flex gap-2">
          <button 
            onClick={() => setShowConfig(!showConfig)}
            className="px-4 py-2 border border-slate-700 rounded-lg hover:bg-slate-800 transition-colors text-sm font-medium flex items-center gap-2"
          >
            {showConfig ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            Configura Scenario
          </button>
          <button
            onClick={handleRun}
            disabled={running || !config}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors text-sm font-medium flex items-center gap-2"
          >
            {running ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            Esegui Stress Test
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-lg text-rose-400 text-sm flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 flex-shrink-0" />
          {error}
        </div>
      )}

      {showConfig && config && (
        <Panel title="Configurazione Scenario" icon={<Zap className="w-5 h-5 text-amber-400" />}>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="space-y-4">
               <div className="space-y-1">
                <label className="text-xs text-slate-500">Nome Scenario</label>
                <input 
                  type="text" 
                  value={config.scenario_name} 
                  onChange={e => setConfig({...config, scenario_name: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-slate-500">Preset Shock</label>
                <select 
                  value={config.scenario_type} 
                  onChange={e => setConfig({...config, scenario_type: e.target.value as any})}
                  className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
                >
                  {presets.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-slate-500">Portafoglio Sorgente</label>
                <select 
                  value={config.portfolio_source} 
                  onChange={e => setConfig({...config, portfolio_source: e.target.value as any})}
                  className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
                >
                  <option value="CURRENT_PORTFOLIO">Portafoglio Attuale</option>
                  <option value="LATEST_OPTIMIZED_PORTFOLIO">Ultimo Ottimizzato</option>
                </select>
              </div>
            </div>

            <div className="space-y-3">
              <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Shock Asset Class (%)</p>
              <div className="grid grid-cols-2 gap-2">
                {['STOCK', 'ETF', 'CRYPTO', 'BOND', 'CASH'].map(cls => (
                  <div key={cls} className="space-y-1">
                    <label className="text-[10px] text-slate-500">{cls}</label>
                    <input 
                      type="number" 
                      value={config.asset_class_shocks[cls] || 0} 
                      onChange={e => setConfig({
                        ...config, 
                        asset_class_shocks: { ...config.asset_class_shocks, [cls]: parseFloat(e.target.value) }
                      })}
                      className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white"
                    />
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-3">
               <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Opzioni Rischio</p>
               <ConfigToggle label="Includi ML Risk" checked={config.include_ml_risk} onChange={v => setConfig({...config, include_ml_risk: v})} />
               <ConfigToggle label="Includi News Risk" checked={config.include_news_risk} onChange={v => setConfig({...config, include_news_risk: v})} />
               <div className="space-y-1 mt-2">
                  <label className="text-xs text-slate-500">Confidence Level</label>
                  <select 
                    value={config.confidence_level} 
                    onChange={e => setConfig({...config, confidence_level: parseInt(e.target.value) as any})}
                    className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
                  >
                    <option value={95}>95%</option>
                    <option value={99}>99%</option>
                  </select>
                </div>
            </div>
          </div>
        </Panel>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <Panel title="Storico Scenari" icon={<History className="w-5 h-5 text-slate-400" />}>
            <div className="space-y-2 max-h-[600px] overflow-y-auto">
              {runs.map(r => (
                <div 
                  key={r.id}
                  onClick={() => handleSelectRun(r.id)}
                  className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                    selectedRun?.summary.id === r.id 
                    ? 'bg-indigo-500/10 border-indigo-500/40' 
                    : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-slate-200 truncate">{r.scenario_name}</span>
                    <button 
                      onClick={(e) => { e.stopPropagation(); handleDelete(r.id); }}
                      className="text-slate-600 hover:text-rose-500 transition-colors"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="flex items-center justify-between mt-2 text-[10px] text-slate-500">
                    <span className={`px-1 rounded ${
                      r.risk_level === 'EXTREME' ? 'bg-rose-500/20 text-rose-400' :
                      r.risk_level === 'HIGH' ? 'bg-orange-500/20 text-orange-400' :
                      'bg-slate-800 text-slate-400'
                    }`}>{r.risk_level}</span>
                    <span>{new Date(r.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="lg:col-span-3 space-y-6">
          {selectedRun ? (
            <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <ImpactStat label="Perdita Stimata" value={formatPercent(selectedRun.summary.percentage_loss / 100)} color={selectedRun.summary.percentage_loss < 0 ? "text-rose-400" : "text-emerald-400"} />
                <ImpactStat label="Perdita Assoluta" value={formatCurrency(selectedRun.summary.absolute_loss)} />
                <ImpactStat label="Valore Stressato" value={formatCurrency(selectedRun.summary.stressed_portfolio_value)} />
                <ImpactStat label="Risk Level" value={selectedRun.summary.risk_level} color={selectedRun.summary.risk_level === 'EXTREME' ? 'text-rose-500' : 'text-orange-400'} />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                 <Panel title="Loss Contribution by Asset" icon={<BarChart3 className="w-4 h-4" />}>
                   <div className="h-[250px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={lossData}>
                        <XAxis dataKey="name" stroke="#64748B" fontSize={10} />
                        <YAxis stroke="#64748B" fontSize={10} />
                        <RechartsTooltip />
                        <Bar dataKey="value" fill="#f43f5e" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                   </div>
                 </Panel>
                 <Panel title="Suggerimenti Mitigazione" icon={<CheckCircle2 className="w-4 h-4 text-emerald-400" />}>
                    <div className="space-y-3">
                       {selectedRun.mitigation_suggestions.map((s, i) => (
                         <div key={i} className="flex gap-2 p-2 rounded bg-slate-900/60 border border-slate-800 text-xs text-slate-300">
                            <Info className="w-4 h-4 text-indigo-400 flex-shrink-0" />
                            {s}
                         </div>
                       ))}
                    </div>
                 </Panel>
              </div>

              <Panel title="Dettaglio Impatto per Asset">
                 <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-500 text-[10px] uppercase">
                          <th className="pb-3 font-medium">Symbol</th>
                          <th className="pb-3 text-right font-medium">Valore Attuale</th>
                          <th className="pb-3 text-right font-medium">Shock</th>
                          <th className="pb-3 text-right font-medium">Valore Stressato</th>
                          <th className="pb-3 text-right font-medium">Impatto Assoluto</th>
                          <th className="pb-3 text-right font-medium">Contrib. Perdita</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {selectedRun.asset_impacts.map(ai => (
                          <tr key={ai.symbol} className="hover:bg-slate-800/20">
                            <td className="py-3 font-bold text-white">{ai.symbol}</td>
                            <td className="py-3 text-right text-xs text-slate-400">{formatCurrency(ai.current_value)}</td>
                            <td className="py-3 text-right text-xs font-medium text-rose-400">{ai.shock_percent.toFixed(1)}%</td>
                            <td className="py-3 text-right text-xs text-white">{formatCurrency(ai.stressed_value)}</td>
                            <td className="py-3 text-right text-xs font-bold text-rose-400">{formatCurrency(ai.absolute_impact)}</td>
                            <td className="py-3 text-right">
                               <div className="flex items-center justify-end gap-2">
                                  <div className="w-12 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                                     <div className="h-full bg-rose-500" style={{ width: `${ai.loss_contribution_percent}%` }} />
                                  </div>
                                  <span className="text-[10px] text-slate-500">{ai.loss_contribution_percent.toFixed(1)}%</span>
                               </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                 </div>
              </Panel>
            </>
          ) : (
            <div className="h-[400px] flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-xl bg-slate-900/20 text-slate-500">
              <ShieldAlert className="w-12 h-12 mb-4 text-slate-700" />
              <p className="text-lg font-medium">Nessuno Stress Test selezionato</p>
              <p className="text-sm">Configura lo scenario e clicca "Esegui Stress Test"</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ConfigToggle({ label, checked, onChange }: { label: string, checked: boolean, onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between p-2 rounded bg-slate-900/60 border border-slate-800">
      <span className="text-xs text-slate-400">{label}</span>
      <button 
        onClick={() => onChange(!checked)}
        className={`w-8 h-4 rounded-full transition-colors relative ${checked ? 'bg-indigo-600' : 'bg-slate-700'}`}
      >
        <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${checked ? 'left-4.5' : 'left-0.5'}`} />
      </button>
    </div>
  );
}

function ImpactStat({ label, value, color = "text-white" }: { label: string, value: string | number, color?: string }) {
  return (
    <div className="bg-slate-900/40 border border-slate-800 p-4 rounded-xl">
      <p className="text-[10px] uppercase font-bold tracking-wider text-slate-500">{label}</p>
      <p className={`text-xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}
