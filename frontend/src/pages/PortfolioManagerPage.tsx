import React, { useState, useEffect } from "react";
import { api, Portfolio, ConsolidatedSummary, PortfolioPerformanceComparison, PortfolioType, TransferType, RiskProfile, StrategyProfile } from "../lib/api";
import { 
  Wallet, Plus, Copy, Archive, TrendingUp, TrendingDown, 
  ArrowRightLeft, BarChart3, PieChart, Activity, Info,
  Search, Shield, Zap, Coins, Users, Settings2, CheckCircle2,
  XCircle
} from "lucide-react";
import { Panel } from "../components/Panel";
import { formatCurrency, formatPercent } from "../lib/format";

export default function PortfolioManagerPage() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [consolidated, setConsolidated] = useState<ConsolidatedSummary | null>(null);
  const [comparison, setComparison] = useState<PortfolioPerformanceComparison | null>(null);
  const [riskProfiles, setRiskProfiles] = useState<RiskProfile[]>([]);
  const [strategyProfiles, setStrategyProfiles] = useState<StrategyProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Tabs: 'list', 'consolidated', 'comparison', 'transfers'
  const [activeTab, setActiveTab] = useState('list');
  const [showNewForm, setShowNewForm] = useState(false);
  
  // New Portfolio Form
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newType, setNewType] = useState<PortfolioType>("CORE");
  const [newInitialCash, setNewInitialCash] = useState(100000);
  const [newRiskProfileId, setNewRiskProfileId] = useState<number | undefined>(undefined);
  const [newStrategyProfileId, setNewStrategyProfileId] = useState<number | undefined>(undefined);
  
  // Transfer Form
  const [fromId, setFromId] = useState<number | undefined>(undefined);
  const [toId, setToId] = useState<number | undefined>(undefined);
  const [transferAmount, setTransferAmount] = useState(0);
  const [transferType, setTransferType] = useState<TransferType>("INTERNAL_TRANSFER");
  const [transferNote, setTransferNote] = useState("");

  useEffect(() => {
    fetchData();
    // Check if URL has ?action=new
    const params = new URLSearchParams(window.location.search);
    if (params.get("action") === "new") {
      setShowNewForm(true);
    }
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [pList, cons, comp, rp, sp] = await Promise.all([
        api.listPortfolios(true),
        api.getConsolidatedSummary(),
        api.getPerformanceComparison(),
        api.listRiskProfiles(),
        api.listStrategyProfiles()
      ]);
      setPortfolios(pList);
      setConsolidated(cons);
      setComparison(comp);
      setRiskProfiles(rp);
      setStrategyProfiles(sp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createPortfolio({
        portfolio_name: newName,
        description: newDesc,
        portfolio_type: newType,
        initial_cash: newInitialCash,
        risk_profile_id: newRiskProfileId,
        strategy_profile_id: newStrategyProfileId
      });
      setShowNewForm(false);
      fetchData();
      setNewName("");
      setNewDesc("");
      setNewRiskProfileId(undefined);
      setNewStrategyProfileId(undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create portfolio");
    }
  };

  const handleActivate = async (id: number) => {
    try {
      await api.activatePortfolio(id);
      localStorage.setItem("activePortfolioId", id.toString());
      fetchData();
      window.location.reload(); 
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to activate");
    }
  };

  const handleArchive = async (id: number) => {
    try {
      await api.deletePortfolio(id); 
      fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive");
    }
  };

  const handleClone = async (id: number) => {
    const name = prompt("Nome per il nuovo portafoglio:");
    if (!name) return;
    try {
      await api.clonePortfolio(id, { 
        new_name: name, 
        include_positions: true, 
        include_orders: false 
      });
      fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clone");
    }
  };

  const handleTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.transferCash({
        from_portfolio_id: transferType === "DEPOSIT" ? undefined : fromId,
        to_portfolio_id: transferType === "WITHDRAWAL" ? undefined : toId,
        amount: transferAmount,
        transfer_type: transferType,
        note: transferNote
      });
      setTransferAmount(0);
      setTransferNote("");
      setActiveTab('list');
      fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Transfer failed");
    }
  };

  if (loading && portfolios.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-20">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <Shield className="text-blue-400" /> Gestione Multi-Portafoglio
          </h1>
          <p className="text-slate-400 mt-1">Simula strategie diverse in portafogli indipendenti.</p>
        </div>
        <button
          onClick={() => setShowNewForm(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors shadow-lg shadow-blue-900/20"
        >
          <Plus size={20} /> Nuovo Portafoglio
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-900/30 border border-red-800 rounded-lg text-red-200 flex items-center gap-3">
          <Info size={20} /> {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-800 overflow-x-auto no-scrollbar">
        {[
          { id: 'list', label: 'I miei Portafogli', icon: Wallet },
          { id: 'consolidated', label: 'Vista Consolidata', icon: PieChart },
          { id: 'comparison', label: 'Confronto Performance', icon: BarChart3 },
          { id: 'transfers', label: 'Trasferimenti Cash', icon: ArrowRightLeft },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-6 py-3 text-sm font-medium transition-colors whitespace-nowrap border-b-2 ${
              activeTab === tab.id 
                ? "border-blue-500 text-blue-400 bg-blue-400/5" 
                : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
            }`}
          >
            <tab.icon size={18} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab: List */}
      {activeTab === 'list' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {portfolios.map((p) => (
            <Panel key={p.id} className={`relative overflow-hidden ${p.is_active ? "ring-2 ring-blue-500/50" : ""}`}>
              {p.is_active && (
                <div className="absolute top-0 right-0 p-2">
                  <span className="flex items-center gap-1 text-[10px] font-bold uppercase bg-blue-500 text-white px-2 py-0.5 rounded-bl-lg">
                    Attivo
                  </span>
                </div>
              )}
              {p.is_archived && (
                <div className="absolute top-0 right-0 p-2">
                  <span className="flex items-center gap-1 text-[10px] font-bold uppercase bg-slate-700 text-slate-300 px-2 py-0.5 rounded-bl-lg">
                    Archiviato
                  </span>
                </div>
              )}
              
              <div className="flex flex-col h-full">
                <div className="flex items-start gap-3 mb-4">
                  <div className={`p-3 rounded-lg ${p.is_active ? "bg-blue-500/20 text-blue-400" : "bg-slate-800 text-slate-400"}`}>
                    {p.portfolio_type === 'CRYPTO' ? <Coins size={24} /> : 
                     p.portfolio_type === 'GROWTH' ? <Zap size={24} /> :
                     p.portfolio_type === 'FAMILY' ? <Users size={24} /> :
                     <Wallet size={24} />}
                  </div>
                  <div>
                    <h3 className="font-bold text-lg text-white leading-tight">{p.portfolio_name}</h3>
                    <p className="text-xs text-slate-500 uppercase font-semibold">{p.portfolio_type} • {p.base_currency}</p>
                  </div>
                </div>
                
                <p className="text-sm text-slate-400 mb-6 line-clamp-2 min-h-[40px]">
                  {p.description || "Nessuna descrizione fornita."}
                </p>

                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase block mb-1">Cash Corrente</span>
                    <span className="text-lg font-mono text-white">{formatCurrency(p.current_cash, p.base_currency)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase block mb-1">Iniziale</span>
                    <span className="text-sm font-mono text-slate-400">{formatCurrency(p.initial_cash, p.base_currency)}</span>
                  </div>
                </div>

                <div className="space-y-2 mb-6">
                   {p.risk_profile_id && (
                     <div className="flex items-center gap-2">
                        <Shield size={12} className="text-blue-400" />
                        <span className="text-[10px] text-slate-300">Rischio: {riskProfiles.find(rp => rp.id === p.risk_profile_id)?.profile_name}</span>
                     </div>
                   )}
                   {p.strategy_profile_id && (
                     <div className="flex items-center gap-2">
                        <Zap size={12} className="text-indigo-400" />
                        <span className="text-[10px] text-slate-300">Strategia: {strategyProfiles.find(sp => sp.id === p.strategy_profile_id)?.profile_name}</span>
                     </div>
                   )}
                </div>

                <div className="mt-auto flex items-center gap-2 pt-4 border-t border-slate-800">
                  {!p.is_active && !p.is_archived && (
                    <button 
                      onClick={() => handleActivate(p.id)}
                      className="flex-1 py-2 text-xs font-bold bg-slate-800 hover:bg-blue-600 text-slate-300 hover:text-white rounded transition-colors"
                    >
                      ATTIVA
                    </button>
                  )}
                  <button 
                    onClick={() => handleClone(p.id)}
                    className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-colors"
                    title="Clona"
                  >
                    <Copy size={16} />
                  </button>
                  {!p.is_archived && (
                    <button 
                      onClick={() => handleArchive(p.id)}
                      className="p-2 text-slate-400 hover:text-red-400 hover:bg-slate-800 rounded transition-colors"
                      title="Archivia"
                    >
                      <Archive size={16} />
                    </button>
                  )}
                  <a 
                    href="/settings"
                    className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-colors"
                    title="Impostazioni"
                  >
                    <Settings2 size={16} />
                  </a>
                </div>
              </div>
            </Panel>
          ))}
        </div>
      )}

      {/* Tab: Consolidated */}
      {activeTab === 'consolidated' && consolidated && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <Panel className="bg-gradient-to-br from-slate-900 to-slate-900 border-l-4 border-l-blue-500">
              <span className="text-xs text-slate-500 uppercase font-bold">Valore Totale</span>
              <div className="text-2xl font-mono text-white mt-1">{formatCurrency(consolidated.total_value)}</div>
              <div className={`text-xs mt-2 flex items-center gap-1 ${consolidated.total_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {consolidated.total_pnl >= 0 ? <TrendingUp size={12}/> : <TrendingDown size={12}/>}
                {formatPercent(consolidated.total_pnl_percent)} complessivo
              </div>
            </Panel>
            <Panel className="bg-slate-900/50">
              <span className="text-xs text-slate-500 uppercase font-bold">Cash Totale</span>
              <div className="text-2xl font-mono text-white mt-1">{formatCurrency(consolidated.total_cash)}</div>
              <div className="text-xs text-slate-400 mt-2">
                {((consolidated.total_cash / consolidated.total_value) * 100).toFixed(1)}% liquidità media
              </div>
            </Panel>
            <Panel className="bg-slate-900/50">
              <span className="text-xs text-slate-500 uppercase font-bold">P/L Realizzato</span>
              <div className="text-2xl font-mono text-emerald-400 mt-1">{formatCurrency(consolidated.total_realized_pnl)}</div>
              <div className="text-xs text-slate-400 mt-2">Tutti i portafogli</div>
            </Panel>
            <Panel className="bg-slate-900/50">
              <span className="text-xs text-slate-500 uppercase font-bold">Portafogli</span>
              <div className="text-2xl font-mono text-white mt-1">{consolidated.portfolios_count}</div>
              <div className="text-xs text-slate-400 mt-2">{consolidated.active_portfolios_count} attivi</div>
            </Panel>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Panel title="Allocazione Asset Class">
              <div className="space-y-4">
                {Object.entries(consolidated.allocation_by_asset_type).sort((a,b) => b[1] - a[1]).map(([type, value]) => (
                  <div key={type}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-slate-300 uppercase font-medium">{type}</span>
                      <span className="text-slate-400 font-mono">{formatCurrency(value)}</span>
                    </div>
                    <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-blue-500" 
                        style={{ width: `${(value / consolidated.total_value) * 100}%` }}
                      ></div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
            <Panel title="Dettaglio Portafogli">
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="text-xs text-slate-500 uppercase border-b border-slate-800">
                      <th className="pb-3 px-2">Portafoglio</th>
                      <th className="pb-3 px-2">Valore</th>
                      <th className="pb-3 px-2">P/L</th>
                      <th className="pb-3 px-2 text-right">%</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {consolidated.portfolio_summaries.map((p) => (
                      <tr key={p.id} className="text-sm">
                        <td className="py-3 px-2 text-white font-medium">{p.name}</td>
                        <td className="py-3 px-2 text-slate-300 font-mono">{formatCurrency(p.total_value)}</td>
                        <td className={`py-3 px-2 font-mono ${p.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {p.pnl >= 0 ? "+" : ""}{formatCurrency(p.pnl)}
                        </td>
                        <td className={`py-3 px-2 text-right font-mono ${p.pnl_percent >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {p.pnl_percent.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        </div>
      )}

      {/* Tab: Comparison */}
      {activeTab === 'comparison' && comparison && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Panel className="bg-emerald-900/10 border-l-4 border-l-emerald-500">
              <div className="flex items-center gap-3 text-emerald-400 mb-2">
                <TrendingUp size={20} />
                <span className="text-xs font-bold uppercase">Best Performer</span>
              </div>
              <h3 className="text-xl font-bold text-white">{comparison.best_performer?.name}</h3>
              <div className="text-2xl font-mono text-emerald-400 mt-1">
                {comparison.best_performer?.pnl_percent.toFixed(2)}%
              </div>
              <p className="text-xs text-slate-400 mt-2">P/L totale relativo al capitale iniziale.</p>
            </Panel>
            <Panel className="bg-rose-900/10 border-l-4 border-l-rose-500">
              <div className="flex items-center gap-3 text-rose-400 mb-2">
                <TrendingDown size={20} />
                <span className="text-xs font-bold uppercase">Worst Performer</span>
              </div>
              <h3 className="text-xl font-bold text-white">{comparison.worst_performer?.name}</h3>
              <div className="text-2xl font-mono text-rose-400 mt-1">
                {comparison.worst_performer?.pnl_percent.toFixed(2)}%
              </div>
              <p className="text-xs text-slate-400 mt-2">P/L totale relativo al capitale iniziale.</p>
            </Panel>
          </div>

          <Panel title="Analisi Comparativa Rischio/Rendimento">
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="text-xs text-slate-500 uppercase border-b border-slate-800">
                    <th className="pb-3 px-2">Portafoglio</th>
                    <th className="pb-3 px-2">Profilo Rischio</th>
                    <th className="pb-3 px-2">Rendimento %</th>
                    <th className="pb-3 px-2">Stato</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {comparison.risk_comparison.map((p) => (
                    <tr key={p.id} className="text-sm">
                      <td className="py-4 px-2 text-white font-medium">{p.name}</td>
                      <td className="py-4 px-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                          p.risk_level === 'High' ? "bg-rose-500/20 text-rose-400" :
                          p.risk_level === 'Low' ? "bg-emerald-500/20 text-emerald-400" :
                          "bg-blue-500/20 text-blue-400"
                        }`}>
                          {p.risk_level}
                        </span>
                      </td>
                      <td className={`py-4 px-2 font-mono font-bold ${p.pnl_percent >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {p.pnl_percent.toFixed(2)}%
                      </td>
                      <td className="py-4 px-2">
                        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden max-w-[100px]">
                           <div 
                            className={`h-full ${p.pnl_percent >= 0 ? "bg-emerald-500" : "bg-rose-500"}`}
                            style={{ width: `${Math.min(100, Math.abs(p.pnl_percent) * 5)}%` }}
                           ></div>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}

      {/* Tab: Transfers */}
      {activeTab === 'transfers' && (
        <div className="max-w-2xl mx-auto">
          <Panel title="Trasferimento Capitale">
            <form onSubmit={handleTransfer} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-bold text-slate-500 uppercase px-1">Tipo Trasferimento</label>
                  <select
                    value={transferType}
                    onChange={(e) => setTransferType(e.target.value as TransferType)}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="INTERNAL_TRANSFER">Trasferimento Interno</option>
                    <option value="DEPOSIT">Deposito Esterno</option>
                    <option value="WITHDRAWAL">Prelievo Esterno</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold text-slate-500 uppercase px-1">Importo</label>
                  <input
                    type="number"
                    value={transferAmount}
                    onChange={(e) => setTransferAmount(Number(e.target.value))}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                    required
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {transferType !== "DEPOSIT" && (
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-500 uppercase px-1">Da Portafoglio</label>
                    <select
                      value={fromId}
                      onChange={(e) => setFromId(Number(e.target.value))}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      required
                    >
                      <option value="">Seleziona...</option>
                      {portfolios.filter(p => !p.is_archived).map(p => (
                        <option key={p.id} value={p.id}>{p.portfolio_name} ({formatCurrency(p.current_cash)})</option>
                      ))}
                    </select>
                  </div>
                )}
                {transferType !== "WITHDRAWAL" && (
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-slate-500 uppercase px-1">A Portafoglio</label>
                    <select
                      value={toId}
                      onChange={(e) => setToId(Number(e.target.value))}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      required
                    >
                      <option value="">Seleziona...</option>
                      {portfolios.filter(p => !p.is_archived).map(p => (
                        <option key={p.id} value={p.id}>{p.portfolio_name}</option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-xs font-bold text-slate-500 uppercase px-1">Nota</label>
                <textarea
                  value={transferNote}
                  onChange={(e) => setTransferNote(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 h-24"
                  placeholder="Es: Allocazione mensile, Ribilanciamento manuale..."
                />
              </div>

              <button
                type="submit"
                className="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg transition-colors flex items-center justify-center gap-2"
              >
                <CheckCircle2 size={20} /> Esegui Trasferimento
              </button>
            </form>
          </Panel>
        </div>
      )}

      {/* New Portfolio Modal */}
      {showNewForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="p-6 border-b border-slate-800 flex items-center justify-between">
              <h2 className="text-xl font-bold text-white">Crea Nuovo Portafoglio</h2>
              <button onClick={() => setShowNewForm(false)} className="text-slate-400 hover:text-white">
                <XCircle size={24} />
              </button>
            </div>
            <form onSubmit={handleCreate} className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-bold text-slate-500 uppercase">Nome Portafoglio</label>
                  <input
                    type="text"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="Es: Core ETF..."
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold text-slate-500 uppercase">Tipo</label>
                  <select
                    value={newType}
                    onChange={(e) => setNewType(e.target.value as PortfolioType)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="CORE">CORE (Standard)</option>
                    <option value="GROWTH">GROWTH</option>
                    <option value="CRYPTO">CRYPTO</option>
                    <option value="DIVIDEND">DIVIDEND</option>
                    <option value="SPECULATIVE">SPECULATIVE</option>
                    <option value="FAMILY">FAMILY</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-bold text-slate-500 uppercase">Capitale Iniziale ($)</label>
                  <input
                    type="number"
                    value={newInitialCash}
                    onChange={(e) => setNewInitialCash(Number(e.target.value))}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold text-slate-500 uppercase">Profilo Rischio</label>
                  <select
                    value={newRiskProfileId}
                    onChange={(e) => setNewRiskProfileId(e.target.value ? Number(e.target.value) : undefined)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">Nessuno (Default)</option>
                    {riskProfiles.map(rp => <option key={rp.id} value={rp.id}>{rp.profile_name}</option>)}
                  </select>
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-bold text-slate-500 uppercase">Profilo Strategia</label>
                <select
                  value={newStrategyProfileId}
                  onChange={(e) => setNewStrategyProfileId(e.target.value ? Number(e.target.value) : undefined)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Nessuno (Default)</option>
                  {strategyProfiles.map(sp => <option key={sp.id} value={sp.id}>{sp.profile_name}</option>)}
                </select>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-bold text-slate-500 uppercase">Descrizione</label>
                <textarea
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 h-24"
                  placeholder="Opzionale..."
                />
              </div>
              <div className="pt-4 flex gap-3">
                <button
                  type="button"
                  onClick={() => setShowNewForm(false)}
                  className="flex-1 py-2 text-slate-400 font-bold hover:bg-slate-800 rounded-lg transition-colors"
                >
                  ANNULLA
                </button>
                <button
                  type="submit"
                  className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg transition-colors"
                >
                  CREA
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
