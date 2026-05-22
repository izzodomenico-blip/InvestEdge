import { useEffect, useState } from "react";
import { 
  Play, 
  Settings2, 
  BriefcaseBusiness, 
  TrendingUp, 
  AlertTriangle, 
  CheckCircle2, 
  XCircle, 
  History, 
  Trash2, 
  Info,
  ChevronRight,
  ChevronDown
} from "lucide-react";
import { Panel } from "../components/Panel";
import { 
  api, 
  type StrategyPlanConfig, 
  type StrategyPlanFull, 
  type StrategyPlanSummary 
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

export function StrategyControlPage() {
  const [plans, setPlans] = useState<StrategyPlanSummary[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<StrategyPlanFull | null>(null);
  const [config, setConfig] = useState<StrategyPlanConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(true);

  async function loadInitialData() {
    setLoading(true);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const [plansData, defaultConfig] = await Promise.all([
        api.listStrategyPlans(pId),
        api.getDefaultStrategyConfig(),
      ]);
      setPlans(plansData);
      setConfig(defaultConfig);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadInitialData();
  }, []);

  async function handleGenerate() {
    if (!config) return;
    setGenerating(true);
    setError(null);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const result = await api.generateStrategyPlan(config, pId);
      setSelectedPlan(result);
      setPlans(await api.listStrategyPlans(pId));
      setShowConfig(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante la generazione del piano.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleApply(id: number) {
    if (!window.confirm("Sei sicuro di voler applicare questo piano al Paper Trading? Verranno creati ordini simulati.")) return;
    setApplying(true);
    try {
      await api.applyStrategyPlan(id);
      setSelectedPlan(await api.getStrategyPlan(id));
      alert("Piano applicato con successo!");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'applicazione del piano.");
    } finally {
      setApplying(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Eliminare definitivamente questo piano?")) return;
    try {
      await api.deleteStrategyPlan(id);
      setPlans(plans.filter(p => p.id !== id));
      if (selectedPlan?.summary.id === id) setSelectedPlan(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'eliminazione.");
    }
  }

  async function handleSelectPlan(id: number) {
    setLoading(true);
    try {
      setSelectedPlan(await api.getStrategyPlan(id));
      setShowConfig(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento del piano.");
    } finally {
      setLoading(false);
    }
  }

  if (loading && plans.length === 0) return <div className="p-8 text-center">Caricamento Strategy Control Center...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Settings2 className="w-6 h-6 text-indigo-500" />
          Strategy Control Center
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
            onClick={handleGenerate}
            disabled={generating || !config}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors text-sm font-medium flex items-center gap-2"
          >
            {generating ? "Generazione..." : "Genera Nuovo Piano"}
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
        <Panel title="Configurazione Strategia" icon={<Settings2 className="w-5 h-5 text-indigo-400" />}>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Nome Piano</label>
              <input 
                type="text" 
                value={config.plan_name} 
                onChange={e => setConfig({...config, plan_name: e.target.value})}
                className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Universo Asset</label>
              <select 
                value={config.universe_level} 
                onChange={e => setConfig({...config, universe_level: e.target.value})}
                className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
              >
                <option value="CORE">Core (High Quality)</option>
                <option value="EXTENDED">Extended (All Symbols)</option>
                <option value="WATCHLIST">Watchlist Personale</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Modalità Strategia</label>
              <select 
                value={config.strategy_mode} 
                onChange={e => setConfig({...config, strategy_mode: e.target.value as any})}
                className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
              >
                <option value="CONSERVATIVE">Conservative</option>
                <option value="BALANCED">Balanced</option>
                <option value="AGGRESSIVE">Aggressive</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-slate-500">Ordini</label>
              <select 
                value={config.order_generation_mode} 
                onChange={e => setConfig({...config, order_generation_mode: e.target.value as any})}
                className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
              >
                <option value="SUGGEST_ONLY">Solo Suggerimenti</option>
                <option value="PAPER_ORDERS">Genera Paper Orders</option>
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
            <ConfigToggle label="Allow Crypto" checked={config.allow_crypto} onChange={v => setConfig({...config, allow_crypto: v})} />
            <ConfigToggle label="Require Real Data" checked={config.require_real_data} onChange={v => setConfig({...config, require_real_data: v})} />
            <ConfigToggle label="Include ML" checked={config.include_ml} onChange={v => setConfig({...config, include_ml: v})} />
            <ConfigToggle label="Include News" checked={config.include_news} onChange={v => setConfig({...config, include_news: v})} />
          </div>
        </Panel>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <Panel title="Cronologia Piani" icon={<History className="w-5 h-5 text-slate-400" />}>
            <div className="space-y-2 max-h-[600px] overflow-y-auto">
              {plans.map(p => (
                <div 
                  key={p.id}
                  onClick={() => handleSelectPlan(p.id)}
                  className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                    selectedPlan?.summary.id === p.id 
                    ? 'bg-indigo-500/10 border-indigo-500/40' 
                    : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-slate-200 truncate">{p.plan_name}</span>
                    <button 
                      onClick={(e) => { e.stopPropagation(); handleDelete(p.id); }}
                      className="text-slate-600 hover:text-rose-500 transition-colors"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="flex items-center justify-between mt-2 text-[10px] text-slate-500">
                    <span className={`px-1 rounded ${p.status === 'APPLIED' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-slate-700 text-slate-300'}`}>
                      {p.status}
                    </span>
                    <span>{new Date(p.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
              {plans.length === 0 && <p className="text-xs text-slate-600 italic">Nessun piano generato</p>}
            </div>
          </Panel>
        </div>

        <div className="lg:col-span-3 space-y-6">
          {selectedPlan ? (
            <>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <Panel title="Riepilogo Impatto" icon={<BriefcaseBusiness className="w-5 h-5 text-indigo-400" />}>
                  <div className="space-y-3">
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">Valore Attuale</span>
                      <span className="font-bold text-white">{formatCurrency(selectedPlan.summary.total_current_value)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">Investimento Target</span>
                      <span className="font-bold text-indigo-300">{formatCurrency(selectedPlan.summary.target_invested_value)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">Cash Residuo</span>
                      <span className="font-bold text-emerald-400">{formatCurrency(selectedPlan.summary.expected_cash_after_plan)}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-500">Ordini Previsti</span>
                      <span className="font-bold text-white">{selectedPlan.summary.estimated_orders_count}</span>
                    </div>
                  </div>
                </Panel>

                <Panel title="Warning & Blockers" icon={<AlertTriangle className="w-5 h-5 text-amber-400" />}>
                  <div className="space-y-2">
                    {selectedPlan.blockers.map((b, i) => (
                      <div key={i} className="text-xs text-rose-400 flex items-start gap-2 bg-rose-500/5 p-1 rounded">
                        <XCircle className="w-3 h-3 mt-0.5" /> {b}
                      </div>
                    ))}
                    {selectedPlan.warnings.map((w, i) => (
                      <div key={i} className="text-xs text-amber-400 flex items-start gap-2 bg-amber-500/5 p-1 rounded">
                        <AlertTriangle className="w-3 h-3 mt-0.5" /> {w}
                      </div>
                    ))}
                    {selectedPlan.warnings.length === 0 && selectedPlan.blockers.length === 0 && (
                      <div className="text-xs text-emerald-500 flex items-center gap-2">
                        <CheckCircle2 className="w-3 h-3" /> Piano validato senza errori.
                      </div>
                    )}
                  </div>
                </Panel>

                <div className="flex flex-col gap-3 justify-center">
                  <button 
                    onClick={() => handleApply(selectedPlan.summary.id)}
                    disabled={applying || selectedPlan.summary.status === 'APPLIED'}
                    className="w-full h-14 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-800 text-white rounded-xl font-bold flex items-center justify-center gap-3 transition-all shadow-lg shadow-emerald-900/20"
                  >
                    {applying ? "Applicazione..." : selectedPlan.summary.status === 'APPLIED' ? "Piano Già Applicato" : "Esegui Piano su Paper Trading"}
                    <Play className="w-5 h-5" />
                  </button>
                  <p className="text-[10px] text-slate-500 text-center px-4 italic">
                    L'applicazione creerà ordini di acquisto/vendita simulati nel portafoglio. Nessun broker reale verrà contattato.
                  </p>
                </div>
              </div>

              <Panel title="Dettaglio Allocazione Target">
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-400 text-[11px] uppercase tracking-wider">
                        <th className="pb-3 font-medium">Symbol</th>
                        <th className="pb-3 font-medium">Peso Attuale</th>
                        <th className="pb-3 font-medium">Peso Target</th>
                        <th className="pb-3 font-medium">Delta Valore</th>
                        <th className="pb-3 font-medium">Azione Suggerita</th>
                        <th className="pb-3 font-medium text-center">Quality</th>
                        <th className="pb-3 font-medium">Reason / Blocker</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {selectedPlan.items.map((item) => (
                        <tr key={item.symbol} className="hover:bg-slate-800/30 transition-colors">
                          <td className="py-4 font-bold text-indigo-400">{item.symbol}</td>
                          <td className="py-4 text-sm text-slate-400">{item.current_weight.toFixed(1)}%</td>
                          <td className="py-4 text-sm font-semibold text-white">{item.target_weight.toFixed(1)}%</td>
                          <td className={`py-4 text-sm font-medium ${item.delta_value > 0 ? 'text-emerald-400' : item.delta_value < 0 ? 'text-rose-400' : 'text-slate-500'}`}>
                            {item.delta_value > 0 ? '+' : ''}{formatCurrency(item.delta_value)}
                          </td>
                          <td className="py-4">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              item.suggested_action === 'BUY' ? 'bg-emerald-500/20 text-emerald-400' :
                              item.suggested_action === 'SELL' ? 'bg-rose-500/20 text-rose-400' :
                              'bg-slate-800 text-slate-500'
                            }`}>
                              {item.suggested_action}
                            </span>
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
                            <div className="flex flex-col gap-1 max-w-[200px]">
                              {item.blocker ? (
                                <span className="text-[10px] text-rose-400 font-medium flex items-center gap-1">
                                  <XCircle className="w-2 h-2" /> {item.blocker}
                                </span>
                              ) : (
                                <span className="text-[10px] text-slate-500 italic line-clamp-2">{item.reason}</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>

              {selectedPlan.proposed_orders.length > 0 && (
                <Panel title="Ordini Proposti" icon={<TrendingUp className="w-5 h-5 text-emerald-400" />}>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-500 text-[10px] uppercase">
                          <th className="pb-2 font-medium">Type</th>
                          <th className="pb-2 font-medium">Symbol</th>
                          <th className="pb-2 font-medium text-right">Quantity</th>
                          <th className="pb-2 font-medium text-right">Est. Price</th>
                          <th className="pb-2 font-medium text-right">Total (Net)</th>
                          <th className="pb-2 font-medium">Reason</th>
                          <th className="pb-2 font-medium">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/50">
                        {selectedPlan.proposed_orders.map((order, i) => (
                          <tr key={i} className="text-sm">
                            <td className={`py-3 font-bold ${order.order_type === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>{order.order_type}</td>
                            <td className="py-3 font-semibold text-white">{order.symbol}</td>
                            <td className="py-3 text-right tabular-nums">{order.quantity.toFixed(4)}</td>
                            <td className="py-3 text-right tabular-nums">{formatCurrency(order.estimated_price)}</td>
                            <td className="py-3 text-right tabular-nums font-medium text-white">{formatCurrency(order.estimated_net_amount)}</td>
                            <td className="py-3 text-xs text-slate-500 max-w-[150px] truncate">{order.reason}</td>
                            <td className="py-3">
                              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${order.status === 'EXECUTED' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500'}`}>
                                {order.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              )}
            </>
          ) : (
            <div className="h-[400px] flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-xl bg-slate-900/20 text-slate-500">
              <Settings2 className="w-12 h-12 mb-4 text-slate-700" />
              <p className="text-lg font-medium">Nessun piano selezionato</p>
              <p className="text-sm">Seleziona un piano dalla cronologia o generane uno nuovo</p>
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
        className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-white"
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
