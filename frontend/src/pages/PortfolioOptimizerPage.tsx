import { useEffect, useState } from "react";
import { 
  Settings2, 
  BarChart3, 
  Play, 
  RefreshCw, 
  AlertTriangle, 
  CheckCircle2, 
  History, 
  Trash2, 
  TrendingUp, 
  ArrowRight,
  PieChart as PieIcon,
  ChevronDown,
  ChevronRight,
  Scale
} from "lucide-react";
import { 
  PieChart, 
  Pie, 
  Cell, 
  ResponsiveContainer, 
  Tooltip as RechartsTooltip, 
  Legend 
} from "recharts";
import { Panel } from "../components/Panel";
import { 
  api, 
  type OptimizerConfig, 
  type OptimizationRunFull, 
  type OptimizationRunSummary 
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const CHART_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#3b82f6', '#ec4899', '#8b5cf6', '#06b6d4', '#f43f5e'];

export function PortfolioOptimizerPage() {
  const [runs, setRuns] = useState<OptimizationRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<OptimizationRunFull | null>(null);
  const [config, setConfig] = useState<OptimizerConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [optimizing, setOptimizing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(true);

  async function loadInitialData() {
    setLoading(true);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const [runsData, defaultConfig] = await Promise.all([
        api.listOptimizationRuns(pId),
        api.getDefaultOptimizerConfig(),
      ]);
      setRuns(runsData);
      setConfig(defaultConfig);
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
    setOptimizing(true);
    setError(null);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const result = await api.runOptimization(config, pId);
      setSelectedRun(result);
      setRuns(await api.listOptimizationRuns(pId));
      setShowConfig(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'ottimizzazione.");
    } finally {
      setOptimizing(false);
    }
  }

  async function handleApply(id: number) {
    if (!window.confirm("Confermi la creazione degli ordini paper nel portafoglio simulato?")) return;
    setApplying(true);
    try {
      await api.applyRebalanceOrders(id);
      setSelectedRun(await api.getOptimizationRun(id));
      alert("Ordini paper creati con successo!");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'applicazione degli ordini.");
    } finally {
      setApplying(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Eliminare questa ottimizzazione?")) return;
    try {
      await api.deleteOptimizationRun(id);
      setRuns(runs.filter(r => r.id !== id));
      if (selectedRun?.summary.id === id) setSelectedRun(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'eliminazione.");
    }
  }

  async function handleSelectRun(id: number) {
    setLoading(true);
    try {
      setSelectedRun(await api.getOptimizationRun(id));
      setShowConfig(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento dettaglio.");
    } finally {
      setLoading(false);
    }
  }

  const currentAllocationData = selectedRun?.items
    .filter(i => i.current_weight > 0)
    .map(i => ({ name: i.symbol, value: i.current_weight })) || [];

  const targetAllocationData = selectedRun?.items
    .filter(i => i.target_weight > 0)
    .map(i => ({ name: i.symbol, value: i.target_weight })) || [];

  if (loading && runs.length === 0) return <div className="p-8 text-center">Caricamento Portfolio Optimizer...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Scale className="w-6 h-6 text-indigo-500" />
          Portfolio Optimizer
        </h1>
        <div className="flex gap-2">
          <button 
            onClick={() => setShowConfig(!showConfig)}
            className="px-4 py-2 border border-slate-700 rounded-lg hover:bg-slate-800 transition-colors text-sm font-medium flex items-center gap-2"
          >
            {showConfig ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            Configurazione
          </button>
          <button
            onClick={handleRun}
            disabled={optimizing || !config}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors text-sm font-medium flex items-center gap-2"
          >
            {optimizing ? "Ottimizzazione..." : "Esegui Ottimizzazione"}
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
        <Panel title="Parametri Ottimizzatore" icon={<Settings2 className="w-5 h-5 text-indigo-400" />}>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Nome Run</label>
              <input 
                type="text" 
                value={config.run_name} 
                onChange={e => setConfig({...config, run_name: e.target.value})}
                className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Universo Asset</label>
              <select 
                value={config.universe_source} 
                onChange={e => setConfig({...config, universe_source: e.target.value as any})}
                className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
              >
                <option value="CORE">Core (High Quality)</option>
                <option value="EXTENDED">Extended (Tutti)</option>
                <option value="WATCHLIST">Watchlist</option>
                <option value="OPERATIONAL_BUY_CANDIDATES">Solo Buy Candidates</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Metodo Ottimizzazione</label>
              <select 
                value={config.optimization_method} 
                onChange={e => setConfig({...config, optimization_method: e.target.value as any})}
                className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
              >
                <option value="EQUAL_WEIGHT">Equal Weight</option>
                <option value="SCORE_WEIGHTED">Score Weighted</option>
                <option value="RISK_ADJUSTED">Risk Adjusted</option>
                <option value="CONSERVATIVE_ALLOCATION">Conservative</option>
                <option value="AGGRESSIVE_ALLOCATION">Aggressive</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Capitale Iniziale</label>
              <select 
                value={config.initial_capital_mode} 
                onChange={e => setConfig({...config, initial_capital_mode: e.target.value as any})}
                className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
              >
                <option value="CURRENT_PORTFOLIO">Portafoglio Attuale</option>
                <option value="CUSTOM_CAPITAL">Capitale Custom</option>
              </select>
            </div>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-6">
             <ConfigInput label="Max Posizioni" value={config.max_positions} onChange={v => setConfig({...config, max_positions: parseInt(v)})} />
             <ConfigInput label="Peso Max Asset (%)" value={config.max_single_asset_weight} onChange={v => setConfig({...config, max_single_asset_weight: parseFloat(v)})} />
             <ConfigInput label="Cash Reserve (%)" value={config.cash_reserve_percent} onChange={v => setConfig({...config, cash_reserve_percent: parseFloat(v)})} />
             <ConfigInput label="Min Data Quality" value={config.min_data_quality_score} onChange={v => setConfig({...config, min_data_quality_score: parseFloat(v)})} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-6">
            <ConfigToggle label="Require Real Data" checked={config.require_real_data} onChange={v => setConfig({...config, require_real_data: v})} />
            <ConfigToggle label="Allow Buy" checked={config.allow_buy} onChange={v => setConfig({...config, allow_buy: v})} />
            <ConfigToggle label="Allow Sell" checked={config.allow_sell} onChange={v => setConfig({...config, allow_sell: v})} />
            <ConfigInput label="Commissioni (%)" value={config.fee_percent} onChange={v => setConfig({...config, fee_percent: parseFloat(v)})} />
          </div>
        </Panel>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <Panel title="Storico Ottimizzazioni" icon={<History className="w-5 h-5 text-slate-400" />}>
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
                    <span className="text-sm font-bold text-slate-200 truncate">{r.run_name}</span>
                    <button 
                      onClick={(e) => { e.stopPropagation(); handleDelete(r.id); }}
                      className="text-slate-600 hover:text-rose-500 transition-colors"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="flex items-center justify-between mt-2 text-[10px] text-slate-500">
                    <span className="px-1 bg-slate-800 rounded">{r.optimization_method}</span>
                    <span>{new Date(r.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
              {runs.length === 0 && <p className="text-xs text-slate-600 italic">Nessuna run salvata</p>}
            </div>
          </Panel>
        </div>

        <div className="lg:col-span-3 space-y-6">
          {selectedRun ? (
            <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <SummaryStat label="Valore Attuale" value={formatCurrency(selectedRun.summary.current_total_value)} />
                <SummaryStat label="Target Investito" value={formatCurrency(selectedRun.summary.target_invested_value)} color="text-indigo-400" />
                <SummaryStat label="Ordini" value={selectedRun.summary.estimated_orders_count} />
                <SummaryStat label="Turnover" value={formatPercent(selectedRun.summary.estimated_turnover_percent / 100)} />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Panel title="Current Allocation" icon={<PieIcon className="w-4 h-4" />}>
                   <div className="h-[250px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={currentAllocationData}
                          innerRadius={60}
                          outerRadius={80}
                          paddingAngle={5}
                          dataKey="value"
                        >
                          {currentAllocationData.map((_, index) => (
                            <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <RechartsTooltip />
                        <Legend />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>
                <Panel title="Target Allocation" icon={<TrendingUp className="w-4 h-4" />}>
                   <div className="h-[250px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={targetAllocationData}
                          innerRadius={60}
                          outerRadius={80}
                          paddingAngle={5}
                          dataKey="value"
                        >
                          {targetAllocationData.map((_, index) => (
                            <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <RechartsTooltip />
                        <Legend />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>
              </div>

              <Panel title="Dettaglio Asset & Pesi Target">
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-500 text-[10px] uppercase tracking-wider">
                        <th className="pb-3 font-medium">Symbol</th>
                        <th className="pb-3 font-medium text-right">Peso Attuale</th>
                        <th className="pb-3 font-medium text-center"><ArrowRight className="w-3 h-3 inline" /></th>
                        <th className="pb-3 font-medium text-right">Peso Target</th>
                        <th className="pb-3 font-medium text-right">Delta Valore</th>
                        <th className="pb-3 font-medium text-center">Quality</th>
                        <th className="pb-3 font-medium">Signal</th>
                        <th className="pb-3 font-medium">Risk</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {selectedRun.items.map((item) => (
                        <tr key={item.symbol} className="hover:bg-slate-800/30 transition-colors">
                          <td className="py-4 font-bold text-white">{item.symbol}</td>
                          <td className="py-4 text-right text-sm text-slate-400">{item.current_weight.toFixed(1)}%</td>
                          <td className="py-4 text-center text-slate-600"><ChevronRight className="w-3 h-3 inline" /></td>
                          <td className="py-4 text-right text-sm font-semibold text-indigo-300">{item.target_weight.toFixed(1)}%</td>
                          <td className={`py-4 text-right text-sm font-medium ${item.delta_value > 0 ? 'text-emerald-400' : item.delta_value < 0 ? 'text-rose-400' : 'text-slate-500'}`}>
                            {item.delta_value > 0 ? '+' : ''}{formatCurrency(item.delta_value)}
                          </td>
                          <td className="py-4 text-center">
                            <span className={`text-xs font-bold ${
                              (item.data_quality_score || 0) >= 80 ? 'text-emerald-500' : 
                              (item.data_quality_score || 0) >= 50 ? 'text-amber-500' : 'text-rose-500'
                            }`}>
                              {item.data_quality_score?.toFixed(0)}%
                            </span>
                          </td>
                          <td className="py-4">
                            <span className="text-[10px] px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded">
                              {item.operational_signal || 'HOLD'}
                            </span>
                          </td>
                          <td className="py-4">
                            <span className={`text-[10px] capitalize font-medium ${
                              item.risk_level === 'low' ? 'text-emerald-400' : 
                              item.risk_level === 'medium' ? 'text-blue-400' : 
                              item.risk_level === 'high' ? 'text-amber-400' : 'text-rose-400'
                            }`}>
                              {item.risk_level}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>

              {selectedRun.proposed_orders.length > 0 && (
                <Panel title="Ordini di Ribilanciamento Proposti" icon={<TrendingUp className="w-5 h-5 text-emerald-400" />}>
                   <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-500 text-[10px] uppercase">
                          <th className="pb-2 font-medium">Tipo</th>
                          <th className="pb-2 font-medium">Symbol</th>
                          <th className="pb-2 font-medium text-right">Quantità</th>
                          <th className="pb-2 font-medium text-right">Prezzo Est.</th>
                          <th className="pb-2 font-medium text-right">Totale (Net)</th>
                          <th className="pb-2 font-medium">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/50">
                        {selectedRun.proposed_orders.map((order, i) => (
                          <tr key={i} className="text-sm">
                            <td className={`py-3 font-bold ${order.order_type === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>{order.order_type}</td>
                            <td className="py-3 font-semibold text-white">{order.symbol}</td>
                            <td className="py-3 text-right tabular-nums">{order.quantity.toFixed(4)}</td>
                            <td className="py-3 text-right tabular-nums">{formatCurrency(order.estimated_price)}</td>
                            <td className="py-3 text-right tabular-nums font-medium text-white">{formatCurrency(order.estimated_net_amount)}</td>
                            <td className="py-3">
                              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                                order.status === 'PAPER_CREATED' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500'
                              }`}>
                                {order.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="mt-6 flex flex-col gap-3">
                    <button 
                      onClick={() => handleApply(selectedRun.summary.id)}
                      disabled={applying || selectedRun.proposed_orders.every(o => o.status === 'PAPER_CREATED')}
                      className="w-full h-12 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-800 text-white rounded-xl font-bold flex items-center justify-center gap-2 transition-all shadow-lg"
                    >
                      {applying ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                      Applica Ribilanciamento a Paper Trading
                    </button>
                    <p className="text-[10px] text-slate-500 text-center italic">
                      L'applicazione creerà ordini simulati per allineare il portafoglio ai pesi target.
                    </p>
                  </div>
                </Panel>
              )}
            </>
          ) : (
            <div className="h-[400px] flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-xl bg-slate-900/20 text-slate-500">
              <Scale className="w-12 h-12 mb-4 text-slate-700" />
              <p className="text-lg font-medium">Nessuna Ottimizzazione selezionata</p>
              <p className="text-sm">Configura i parametri e clicca "Esegui Ottimizzazione"</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ConfigInput({ label, value, onChange }: { label: string, value: number, onChange: (v: string) => void }) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-slate-500">{label}</label>
      <input 
        type="number" 
        value={value} 
        onChange={e => onChange(e.target.value)}
        className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white focus:border-indigo-500 outline-none"
      />
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

function SummaryStat({ label, value, color = "text-white" }: { label: string, value: string | number, color?: string }) {
  return (
    <div className="bg-slate-900/40 border border-slate-800 p-4 rounded-xl">
      <p className="text-[10px] uppercase font-bold tracking-wider text-slate-500">{label}</p>
      <p className={`text-xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}
