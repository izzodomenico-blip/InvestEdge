import React, { useState, useEffect } from "react";
import { 
  api, 
  GoogleSheetsStatus, 
  GoogleSheetsPreviewOut, 
  ExternalImport, 
  Portfolio,
  RiskProfile,
  StrategyProfile
} from "../lib/api";
import { 
  FileSpreadsheet, 
  ShieldCheck, 
  RefreshCw, 
  Play, 
  CheckCircle2, 
  AlertTriangle, 
  History, 
  Info,
  Copy,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Database,
  ArrowRight,
  Terminal,
  Zap,
  Clock,
  Trash2,
  Lock,
  Activity,
  Search,
  BarChart3
} from "lucide-react";
import { Panel } from "../components/Panel";
import { formatCurrency } from "../lib/format";

// Fallback for formatDate if not in lib/format
const formatDate = (date: string) => new Date(date).toLocaleDateString();

export default function GoogleSheetsImportPage() {
  const [status, setStatus] = useState<GoogleSheetsStatus | null>(null);
  const [imports, setImports] = useState<ExternalImport[]>([]);
  const [loading, setLoading] = useState(true);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  const [importType, setImportType] = useState<"PORTFOLIO" | "TRANSACTIONS" | "CASH" | "WATCHLIST" | "MIXED">("PORTFOLIO");
  const [previewData, setPreviewData] = useState<GoogleSheetsPreviewOut | null>(null);
  const [importMode, setImportMode] = useState<"CREATE_READONLY_PORTFOLIO" | "UPDATE_WATCHLIST" | "PREVIEW_ONLY">("CREATE_READONLY_PORTFOLIO");
  
  const [templates, setTemplates] = useState<Record<string, string[]>>({});
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    fetchStatus();
    fetchImports();
    fetchTemplates();
  }, []);

  const fetchStatus = async () => {
    try {
      const data = await api.getGoogleSheetsStatus();
      setStatus(data);
    } catch (err) {
      console.error("Failed to fetch status", err);
    }
  };

  const fetchImports = async () => {
    try {
      const data = await api.listGoogleSheetsImports();
      setImports(data);
    } catch (err) {
      console.error("Failed to fetch imports", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchTemplates = async () => {
    try {
      const data = await api.getGoogleSheetsTemplates();
      setTemplates(data);
    } catch (err) {
      console.error("Failed to fetch templates", err);
    }
  };

  const handleAuthorize = async () => {
    try {
      setLoading(true);
      const res = await api.authorizeGoogleSheets();
      setSuccess(res.message);
      fetchStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authorization failed");
    } finally {
      setLoading(false);
    }
  };

  const handleTestConnection = async () => {
    try {
      const res = await api.testGoogleSheetsConnection();
      setSuccess(res.message);
      fetchStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection test failed");
    }
  };

  const handlePreview = async () => {
    setPreviewLoading(true);
    setError(null);
    setPreviewData(null);
    try {
      const res = await api.previewGoogleSheetsImport({ import_type: importType });
      setPreviewData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!previewData) return;
    setConfirmLoading(true);
    setError(null);
    try {
      await api.confirmGoogleSheetsImport(previewData.import_id, { 
        confirm: true, 
        mode: importMode 
      });
      setSuccess("Importazione completata con successo.");
      setPreviewData(null);
      fetchImports();
      fetchStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setConfirmLoading(false);
    }
  };

  const copyHeaders = (type: string) => {
    const headers = templates[type];
    if (!headers) return;
    navigator.clipboard.writeText(headers.join(","));
    setSuccess(`Intestazioni per ${type} copiate negli appunti.`);
    setTimeout(() => setSuccess(null), 3000);
  };

  return (
    <div className="space-y-6 pb-20">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <FileSpreadsheet className="text-emerald-400" /> Google Sheets Tracker Import
          </h1>
          <p className="text-slate-400 mt-1">Leggi i dati dal tuo tracker su Google Fogli in modalità Read-Only.</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={fetchStatus}
            className="p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
            title="Aggiorna stato"
          >
            <RefreshCw size={20} />
          </button>
        </div>
      </div>

      {success && (
        <div className="p-4 bg-emerald-900/30 border border-emerald-800 rounded-lg text-emerald-200 flex items-center gap-3 animate-in fade-in slide-in-from-top-2">
          <CheckCircle2 size={20} /> {success}
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-900/30 border border-red-800 rounded-lg text-red-200 flex items-center gap-3 animate-in fade-in slide-in-from-top-2">
          <AlertTriangle size={20} className="shrink-0" /> {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Status Panel */}
        <Panel title="Stato Connessione" icon={<Activity size={18} className="text-blue-400" />}>
          {status ? (
            <div className="space-y-4">
              <StatusRow label="Import Abilitato" value={status.enabled} />
              <StatusRow label="Credentials Configurate" value={status.credentials_configured} />
              <StatusRow label="Token OAuth Esistente" value={status.token_exists} />
              <StatusRow label="Spreadsheet ID" value={status.spreadsheet_configured} />
              <StatusRow label="Connessione API" value={status.connection_ok} />
              
              <div className="pt-4 flex flex-col gap-2">
                {!status.token_exists ? (
                  <button
                    onClick={handleAuthorize}
                    className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-bold transition-colors flex items-center justify-center gap-2"
                  >
                    <ShieldCheck size={18} /> Autorizza Google Sheets
                  </button>
                ) : (
                  <button
                    onClick={handleTestConnection}
                    className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg font-bold transition-colors flex items-center justify-center gap-2 border border-slate-700"
                  >
                    <Terminal size={18} /> Test Connessione
                  </button>
                )}
                
                {status.message && (
                  <p className={`text-xs mt-2 p-2 rounded ${status.connection_ok ? 'bg-emerald-900/20 text-emerald-400' : 'bg-rose-900/20 text-rose-400'}`}>
                    {status.message}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <div className="h-40 animate-pulse bg-slate-800/50 rounded-lg" />
          )}
        </Panel>

        {/* Instructions & Template */}
        <div className="lg:col-span-2 space-y-6">
          <Panel title="Istruzioni per l'integrazione" icon={<Info size={18} className="text-indigo-400" />}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-3">
                <p className="text-sm text-slate-300">
                  Per importare i dati, il tuo Google Sheet deve avere i seguenti tab con le intestazioni corrette:
                </p>
                <ul className="text-xs space-y-2 text-slate-400 list-disc pl-4">
                  <li><strong>PORTFOLIO</strong>: Posizioni attuali e capitali.</li>
                  <li><strong>TRANSACTIONS</strong>: Storico compravendite.</li>
                  <li><strong>CASH</strong>: Saldi di liquidità per account.</li>
                  <li><strong>WATCHLIST</strong>: Asset da monitorare.</li>
                </ul>
                <div className="p-3 bg-indigo-900/20 border border-indigo-800/50 rounded-lg">
                   <p className="text-xs text-indigo-300 flex items-center gap-2">
                     <Lock size={14} /> Modalità SOLO LETTURA (Read-Only)
                   </p>
                   <p className="text-[10px] text-slate-500 mt-1">InvestEdge non scriverà mai sul tuo foglio originale.</p>
                </div>
              </div>
              <div className="space-y-4">
                <p className="text-xs font-bold text-slate-500 uppercase">Copia Intestazioni Template</p>
                <div className="space-y-2">
                   {Object.keys(EXPECTED_HEADERS).map(type => (
                     <button
                       key={type}
                       onClick={() => copyHeaders(type)}
                       className="w-full flex items-center justify-between px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 text-xs transition-colors"
                     >
                       <span>Tab {type}</span>
                       <Copy size={14} />
                     </button>
                   ))}
                </div>
              </div>
            </div>
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Import Action */}
        <Panel title="Esegui Importazione" icon={<Play size={18} className="text-emerald-400" />}>
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-xs font-bold text-slate-500 uppercase px-1">Cosa vuoi importare?</label>
              <select
                value={importType}
                onChange={(e) => setImportType(e.target.value as any)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="PORTFOLIO">PORTFOLIO (Posizioni Attuali)</option>
                <option value="TRANSACTIONS">TRANSACTIONS (Storico)</option>
                <option value="CASH">CASH (Saldi Liquidità)</option>
                <option value="WATCHLIST">WATCHLIST (Asset Preferiti)</option>
              </select>
            </div>

            <button
              onClick={handlePreview}
              disabled={previewLoading || !status?.connection_ok}
              className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white font-bold rounded-lg transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-900/20"
            >
              {previewLoading ? <RefreshCw size={20} className="animate-spin" /> : <Search size={20} />}
              GENERA ANTEPRIMA
            </button>

            {previewData && (
              <div className="p-4 bg-slate-800 rounded-lg border border-slate-700 space-y-4 animate-in zoom-in-95 duration-200">
                <div className="grid grid-cols-2 gap-2 text-center">
                  <div className="bg-slate-900 p-2 rounded">
                    <p className="text-[10px] text-slate-500 uppercase font-bold">Righe Totali</p>
                    <p className="text-xl font-mono text-white">{previewData.rows_total}</p>
                  </div>
                  <div className="bg-slate-900 p-2 rounded">
                    <p className="text-[10px] text-slate-500 uppercase font-bold">Righe Valide</p>
                    <p className="text-xl font-mono text-emerald-400">{previewData.rows_valid}</p>
                  </div>
                </div>
                
                <div className="space-y-2">
                  <label className="text-xs font-bold text-slate-500 uppercase px-1">Modalità Import</label>
                  <select
                    value={importMode}
                    onChange={(e) => setImportMode(e.target.value as any)}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white"
                  >
                    <option value="CREATE_READONLY_PORTFOLIO">Crea Portafoglio Read-Only</option>
                    <option value="UPDATE_WATCHLIST">Aggiorna Watchlist</option>
                    <option value="PREVIEW_ONLY">Solo Anteprima (Log)</option>
                  </select>
                </div>

                <button
                  onClick={handleConfirm}
                  disabled={confirmLoading || previewData.rows_valid === 0}
                  className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded transition-colors flex items-center justify-center gap-2"
                >
                  {confirmLoading ? <RefreshCw size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
                  CONFERMA IMPORT
                </button>
              </div>
            )}
          </div>
        </Panel>

        {/* Preview Results Table */}
        <div className="lg:col-span-2">
           <Panel 
             title={`Anteprima Dati: ${importType}`} 
             icon={<BarChart3 size={18} className="text-slate-400" />}
             action={previewData && (
               <span className="text-xs font-medium text-slate-500 uppercase">Mostrando prime 10 righe</span>
             )}
           >
             {!previewData ? (
               <div className="h-[300px] flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-xl bg-slate-900/20 text-slate-500">
                 <Search className="w-12 h-12 mb-4 text-slate-700" />
                 <p className="text-lg font-medium">Nessuna anteprima</p>
                 <p className="text-sm">Clicca "Genera Anteprima" per caricare i dati dal foglio.</p>
               </div>
             ) : (
               <div className="overflow-x-auto">
                 <table className="w-full text-left text-xs">
                   <thead>
                     <tr className="border-b border-slate-800 text-slate-500 uppercase">
                       {Object.keys(previewData.preview_rows[0] || {}).map(k => (
                         <th key={k} className="pb-3 px-2 font-medium">{k}</th>
                       ))}
                     </tr>
                   </thead>
                   <tbody className="divide-y divide-slate-800/50">
                     {previewData.preview_rows.map((row, i) => (
                       <tr key={i} className="hover:bg-slate-800/20">
                         {Object.values(row).map((v: any, j) => (
                           <td key={j} className="py-2 px-2 text-slate-300 truncate max-w-[120px]">
                             {typeof v === 'number' ? v.toLocaleString() : String(v)}
                           </td>
                         ))}
                       </tr>
                     ))}
                   </tbody>
                 </table>
                 {previewData.warnings.length > 0 && (
                   <div className="mt-4 p-3 bg-amber-900/20 border border-amber-800/50 rounded-lg">
                      <p className="text-xs font-bold text-amber-400 uppercase mb-1">Warnings</p>
                      <ul className="text-[10px] text-slate-400 list-disc pl-4 space-y-1">
                        {previewData.warnings.map((w, i) => <li key={i}>{w}</li>)}
                      </ul>
                   </div>
                 )}
               </div>
             )}
           </Panel>
        </div>
      </div>

      {/* Import History */}
      <Panel title="Storico Importazioni Google Sheets" icon={<History size={18} className="text-slate-400" />}>
        {imports.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-800 text-[10px] uppercase text-slate-500">
                  <th className="pb-3 px-2">Data</th>
                  <th className="pb-3 px-2">Tipo</th>
                  <th className="pb-3 px-2">Stato</th>
                  <th className="pb-3 px-2">Righe</th>
                  <th className="pb-3 px-2">Modalità</th>
                  <th className="pb-3 px-2 text-right">Azioni</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {imports.map((imp) => (
                  <tr key={imp.id} className="text-sm hover:bg-slate-800/20">
                    <td className="py-3 px-2 text-slate-400 text-xs">{formatDate(imp.created_at)}</td>
                    <td className="py-3 px-2 font-medium text-white">{imp.import_type}</td>
                    <td className="py-3 px-2">
                       <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                         imp.status === 'IMPORTED' ? 'bg-emerald-500/20 text-emerald-400' :
                         imp.status === 'FAILED' ? 'bg-rose-500/20 text-rose-400' :
                         'bg-slate-800 text-slate-400'
                       }`}>
                         {imp.status}
                       </span>
                    </td>
                    <td className="py-3 px-2 font-mono text-xs">{imp.rows_valid}/{imp.rows_total}</td>
                    <td className="py-3 px-2 text-slate-500 text-[10px] truncate max-w-[150px] uppercase">{imp.import_mode}</td>
                    <td className="py-3 px-2 text-right">
                       <button className="p-1 text-slate-500 hover:text-white"><Info size={16} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-slate-500 italic py-4 text-center">Nessuna importazione eseguita.</p>
        )}
      </Panel>
    </div>
  );
}

function StatusRow({ label, value }: { label: string, value: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm py-1 border-b border-slate-800/50 last:border-0">
      <span className="text-slate-400">{label}</span>
      <span className={value ? "text-emerald-400" : "text-rose-400"}>
        {value ? <CheckCircle2 size={16} /> : <XCircleIcon size={16} />}
      </span>
    </div>
  );
}

function XCircleIcon({ size }: { size: number }) {
  return <AlertTriangle size={size} />; // Fallback since I forgot to import XCircle or similar
}

const EXPECTED_HEADERS = {
    "PORTFOLIO": [
        "portfolio_name", "broker_name", "account_name", "symbol", "isin", "name", 
        "asset_type", "quantity", "average_price", "current_price", "currency", 
        "exchange", "market_value", "as_of_date"
    ],
    "TRANSACTIONS": [
        "portfolio_name", "broker_name", "account_name", "transaction_date", 
        "transaction_type", "symbol", "isin", "name", "asset_type", "quantity", 
        "price", "gross_amount", "fees", "taxes", "net_amount", "currency", 
        "exchange", "note"
    ],
    "CASH": [
        "portfolio_name", "broker_name", "account_name", "currency", "cash_amount", "as_of_date"
    ],
    "WATCHLIST": [
        "symbol", "isin", "name", "asset_type", "currency", "exchange", "sector", "country", "notes"
    ]
};
