import { useEffect, useState } from "react";
import { 
  Settings2, 
  ShieldCheck, 
  TrendingUp, 
  Bell, 
  Monitor, 
  Save, 
  RefreshCw, 
  CheckCircle2, 
  AlertTriangle,
  ChevronRight,
  Plus,
  Trash2
} from "lucide-react";
import { Panel } from "../components/Panel";
import { 
  api, 
  type RiskProfile, 
  type StrategyProfile, 
  type NotificationPreference,
  type UIPreferences
} from "../lib/api";

export function SettingsPage() {
  const [riskProfiles, setRiskProfiles] = useState<RiskProfile[]>([]);
  const [strategyProfiles, setStrategyProfiles] = useState<StrategyProfile[]>([]);
  const [notifications, setNotifications] = useState<NotificationPreference[]>([]);
  const [uiPrefs, setUiPrefs] = useState<UIPreferences | null>(null);
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    try {
      const [rp, sp, nt, ui] = await Promise.all([
        api.listRiskProfiles(),
        api.listStrategyProfiles(),
        api.listNotifications(),
        api.getUiPreferences()
      ]);
      setRiskProfiles(rp);
      setStrategyProfiles(sp);
      setNotifications(nt);
      setUiPrefs(ui);
    } catch (err) {
      setError("Errore caricamento impostazioni.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleActivateRisk(id: number) {
    setSaving(true);
    try {
      await api.activateRiskProfile(id);
      setSuccess("Profilo rischio attivato!");
      await loadData();
    } finally {
      setSaving(false);
    }
  }

  async function handleActivateStrategy(id: number) {
    setSaving(true);
    try {
      await api.activateStrategyProfile(id);
      setSuccess("Profilo strategia attivato!");
      await loadData();
    } finally {
      setSaving(false);
    }
  }

  if (loading && riskProfiles.length === 0) return <div className="p-8 text-center">Caricamento impostazioni...</div>;

  const activeRisk = riskProfiles.find(p => p.is_active);
  const activeStrategy = strategyProfiles.find(p => p.is_active);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Settings2 className="w-6 h-6 text-indigo-500" />
          Settings & Profiles
        </h1>
        {success && (
          <div className="px-4 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-400 text-xs font-bold flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4" /> {success}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Panel title="Profili di Rischio" icon={<ShieldCheck className="w-5 h-5 text-emerald-500" />}>
             <div className="space-y-4">
                {riskProfiles.map(p => (
                  <div key={p.id} className={`p-4 rounded-xl border transition-all ${p.is_active ? 'bg-indigo-500/5 border-indigo-500/40' : 'bg-slate-900/40 border-slate-800'}`}>
                     <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-3">
                           <h3 className="font-bold text-slate-100">{p.profile_name}</h3>
                           <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                              p.profile_type === 'CONSERVATIVE' ? 'bg-blue-500/20 text-blue-400' :
                              p.profile_type === 'BALANCED' ? 'bg-emerald-500/20 text-emerald-400' :
                              p.profile_type === 'AGGRESSIVE' ? 'bg-rose-500/20 text-rose-400' :
                              'bg-indigo-500/20 text-indigo-400'
                           }`}>{p.profile_type}</span>
                           {p.is_active && <span className="text-[10px] bg-indigo-600 text-white px-2 py-0.5 rounded font-bold uppercase">Active</span>}
                        </div>
                        {!p.is_active && (
                           <button 
                            onClick={() => handleActivateRisk(p.id)}
                            className="px-3 py-1 bg-indigo-600 text-white rounded text-xs font-bold hover:bg-indigo-700 transition-colors"
                           >
                             Attiva
                           </button>
                        )}
                     </div>
                     <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-[11px]">
                        <div className="space-y-1">
                           <p className="text-slate-500">Max Asset Weight</p>
                           <p className="text-slate-200 font-bold">{p.max_single_asset_weight}%</p>
                        </div>
                        <div className="space-y-1">
                           <p className="text-slate-500">Max Crypto</p>
                           <p className="text-slate-200 font-bold">{p.max_crypto_weight}%</p>
                        </div>
                        <div className="space-y-1">
                           <p className="text-slate-500">Min Data Quality</p>
                           <p className="text-slate-200 font-bold">{p.min_data_quality_score}%</p>
                        </div>
                        <div className="space-y-1">
                           <p className="text-slate-500">ML influence</p>
                           <p className={p.allow_ml_influence ? "text-emerald-400 font-bold" : "text-slate-500 font-bold"}>{p.allow_ml_influence ? "YES" : "NO"}</p>
                        </div>
                     </div>
                  </div>
                ))}
             </div>
          </Panel>

          <Panel title="Profili Strategia" icon={<TrendingUp className="w-5 h-5 text-indigo-500" />}>
             <div className="space-y-4">
                {strategyProfiles.map(p => (
                  <div key={p.id} className={`p-4 rounded-xl border transition-all ${p.is_active ? 'bg-emerald-500/5 border-emerald-500/40' : 'bg-slate-900/40 border-slate-800'}`}>
                     <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-3">
                           <h3 className="font-bold text-slate-100">{p.profile_name}</h3>
                           <span className="text-[10px] text-slate-500">{p.universe_level} · {p.rebalance_frequency}</span>
                           {p.is_active && <span className="text-[10px] bg-emerald-600 text-white px-2 py-0.5 rounded font-bold uppercase">Active</span>}
                        </div>
                        {!p.is_active && (
                           <button 
                            onClick={() => handleActivateStrategy(p.id)}
                            className="px-3 py-1 bg-emerald-600 text-white rounded text-xs font-bold hover:bg-emerald-700 transition-colors"
                           >
                             Attiva
                           </button>
                        )}
                     </div>
                     <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-[11px]">
                        <div className="space-y-1">
                           <p className="text-slate-500">Buy Threshold</p>
                           <p className="text-emerald-400 font-bold">{p.buy_threshold}</p>
                        </div>
                        <div className="space-y-1">
                           <p className="text-slate-500">Max Positions</p>
                           <p className="text-slate-200 font-bold">{p.max_positions}</p>
                        </div>
                        <div className="space-y-1">
                           <p className="text-slate-500">Stop Loss</p>
                           <p className="text-rose-400 font-bold">{p.stop_loss_percent}%</p>
                        </div>
                        <div className="space-y-1">
                           <p className="text-slate-500">Optimizer</p>
                           <p className={p.use_optimizer ? "text-emerald-400 font-bold" : "text-slate-500 font-bold"}>{p.use_optimizer ? "YES" : "NO"}</p>
                        </div>
                     </div>
                  </div>
                ))}
             </div>
          </Panel>
        </div>

        <div className="space-y-6">
           <Panel title="Profilo Attivo" icon={<CheckCircle2 className="w-5 h-5 text-indigo-400" />}>
              <div className="space-y-4">
                 <div className="p-4 rounded-xl bg-indigo-600 text-white">
                    <p className="text-[10px] uppercase font-bold opacity-70">Risk Profile</p>
                    <p className="text-xl font-bold">{activeRisk?.profile_name}</p>
                 </div>
                 <div className="p-4 rounded-xl bg-slate-800 text-white">
                    <p className="text-[10px] uppercase font-bold opacity-70">Strategy Profile</p>
                    <p className="text-xl font-bold">{activeStrategy?.profile_name}</p>
                 </div>
                 <p className="text-xs text-slate-500 italic">Questi profili controllano i filtri di ranking, le soglie di acquisto e i vincoli di rischio dell'intera applicazione.</p>
              </div>
           </Panel>

           <Panel title="Preferenze Notifiche" icon={<Bell className="w-5 h-5 text-amber-500" />}>
              <div className="space-y-3">
                 {notifications.map(n => (
                    <div key={n.id} className="flex items-center justify-between text-xs">
                       <span className="text-slate-300">{n.alert_type.replace(/_/g, ' ')}</span>
                       <div className={`w-7 h-4 rounded-full transition-colors relative ${n.enabled ? 'bg-indigo-600' : 'bg-slate-700'}`}>
                          <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${n.enabled ? 'left-3.5' : 'left-0.5'}`} />
                       </div>
                    </div>
                 ))}
              </div>
           </Panel>

           <Panel title="UI Preferences" icon={<Monitor className="w-5 h-5 text-blue-500" />}>
              <div className="space-y-4 text-xs">
                 <div className="flex justify-between">
                    <span className="text-slate-500">Benchmark</span>
                    <span className="text-slate-200 font-bold">{uiPrefs?.default_benchmark}</span>
                 </div>
                 <div className="flex justify-between">
                    <span className="text-slate-500">Valuta</span>
                    <span className="text-slate-200 font-bold">{uiPrefs?.default_currency}</span>
                 </div>
                 <div className="flex justify-between">
                    <span className="text-slate-500">Advanced Metrics</span>
                    <span className="text-emerald-400 font-bold">{uiPrefs?.show_advanced_metrics ? "ON" : "OFF"}</span>
                 </div>
              </div>
           </Panel>
        </div>
      </div>
    </div>
  );
}
