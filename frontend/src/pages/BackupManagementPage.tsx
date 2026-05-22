import { useEffect, useState } from "react";
import { 
  Database, 
  Download, 
  Upload, 
  ShieldCheck, 
  History, 
  Trash2, 
  RefreshCw, 
  AlertTriangle, 
  CheckCircle2, 
  FileJson, 
  FileSpreadsheet,
  Zap,
  Info,
  ChevronRight,
  ShieldAlert,
  Server
} from "lucide-react";
import { Panel } from "../components/Panel";
import { 
  api, 
  type BackupStatus, 
  type AppSnapshot, 
  type AppExport,
  type HardeningReport
} from "../lib/api";
import { formatCurrency } from "../lib/format";

export function BackupManagementPage() {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [backups, setBackups] = useState<AppSnapshot[]>([]);
  const [exports, setExports] = useState<AppExport[]>([]);
  const [hardening, setHardening] = useState<HardeningReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [exportType, setExportType] = useState("ASSETS");
  const [exportFormat, setExportFormat] = useState("JSON");
  
  const [importType, setImportType] = useState("UNIVERSE");
  const [importFileName, setImportFileName] = useState("");
  const [importResult, setImportResult] = useState<any>(null);

  async function loadData() {
    setLoading(true);
    try {
      const [statusData, backupsData, exportsData, hardeningData] = await Promise.all([
        api.getBackupStatus(),
        api.listBackups(),
        api.listExports(),
        api.getHardeningReport()
      ]);
      setStatus(statusData);
      setBackups(backupsData);
      setExports(exportsData);
      setHardening(hardeningData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento dati gestione.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleCreateBackup() {
    setGenerating(true);
    try {
      await api.createBackup();
      await loadData();
    } finally {
      setGenerating(false);
    }
  }

  async function handleRestore(id: number) {
    const confirmation = window.prompt("ATTENZIONE: Il ripristino sovrascriverà il database attuale. Scrivi 'RESTORE' per confermare.");
    if (confirmation !== "RESTORE") return;
    
    setLoading(true);
    try {
      const res = await api.restoreBackup(id, true);
      alert(res.message);
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore ripristino.");
      setLoading(false);
    }
  }

  async function handleCreateExport() {
    try {
      await api.createExport(exportType, exportFormat);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore creazione export.");
    }
  }

  async function handleRunImport() {
    if (!importFileName) return;
    try {
      const res = await api.runImport(importFileName, importType, true);
      setImportResult(res);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore importazione.");
    }
  }

  async function handleRunHardening() {
    setLoading(true);
    try {
      const res = await api.runHardeningChecks();
      setHardening(res);
    } finally {
      setLoading(false);
    }
  }

  if (loading && !status) return <div className="p-8 text-center">Caricamento strumenti gestione dati...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Database className="w-6 h-6 text-indigo-500" />
          Backup & Data Management
        </h1>
        <button 
          onClick={loadData}
          className="p-2 hover:bg-slate-800 rounded-lg transition-colors"
        >
          <RefreshCw className={`w-5 h-5 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Panel title="Stato Database" icon={<Server className="w-4 h-4" />}>
           <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">Dimensione DB</span>
                <span className="font-bold text-white">{(status?.database_size_bytes || 0 / 1024 / 1024).toFixed(2)} MB</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">Backup totali</span>
                <span className="font-bold text-white">{status?.backups_count}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">Integrità</span>
                <span className="text-emerald-400 font-bold flex items-center gap-1">
                   <CheckCircle2 className="w-3 h-3" /> {status?.integrity_status}
                </span>
              </div>
              <button 
                onClick={handleCreateBackup}
                disabled={creating}
                className="w-full mt-2 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 text-xs font-bold flex items-center justify-center gap-2"
              >
                {creating ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
                Crea Backup Immediato
              </button>
           </div>
        </Panel>

        <Panel title="Project Hardening" icon={<ShieldCheck className="w-4 h-4 text-emerald-400" />}>
           <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                 <span className="text-slate-500">Security Score</span>
                 <span className={`font-bold ${hardening?.overall_status === 'OK' ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {hardening?.overall_status}
                 </span>
              </div>
              <p className="text-[10px] text-slate-500 italic">Controlli attivi su .gitignore, API key e integrità.</p>
              <button 
                onClick={handleRunHardening}
                className="w-full py-2 bg-slate-800 text-slate-200 rounded-lg hover:bg-slate-700 text-xs font-bold border border-slate-700"
              >
                Esegui Hardening Checks
              </button>
           </div>
        </Panel>

        <Panel title="Esportazione Rapida" icon={<Download className="w-4 h-4" />}>
           <div className="space-y-3">
              <select 
                value={exportType} 
                onChange={e => setExportType(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1.5 text-xs text-white"
              >
                <option value="ASSETS">Assets</option>
                <option value="PORTFOLIO">Portafoglio</option>
                <option value="UNIVERSE">Universo</option>
                <option value="ALERTS">Alerts</option>
                <option value="REPORTS">Report Operativi</option>
              </select>
              <div className="flex gap-2">
                 <button onClick={() => { setExportFormat('JSON'); handleCreateExport(); }} className="flex-1 py-1.5 bg-slate-800 text-slate-300 rounded text-[10px] font-bold border border-slate-700">JSON</button>
                 <button onClick={() => { setExportFormat('CSV'); handleCreateExport(); }} className="flex-1 py-1.5 bg-slate-800 text-slate-300 rounded text-[10px] font-bold border border-slate-700">CSV</button>
              </div>
           </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
         <Panel title="Cronologia Backup" icon={<History className="w-4 h-4" />}>
            <div className="space-y-3 max-h-[400px] overflow-y-auto pr-2">
               {backups.map(b => (
                 <div key={b.id} className="p-3 rounded-lg bg-slate-900/40 border border-slate-800 flex items-center justify-between group">
                    <div className="min-w-0">
                       <p className="text-xs font-bold text-slate-200 truncate">{b.snapshot_name}</p>
                       <p className="text-[10px] text-slate-500">{new Date(b.created_at).toLocaleString()} · {(b.size_bytes / 1024 / 1024).toFixed(2)} MB</p>
                    </div>
                    <div className="flex gap-2">
                       <button 
                        onClick={() => handleRestore(b.id)}
                        className="p-1.5 bg-amber-600/10 text-amber-500 rounded hover:bg-amber-600/20"
                        title="Ripristina"
                       >
                         <RefreshCw className="w-3.5 h-3.5" />
                       </button>
                       <button 
                        onClick={() => api.deleteBackup(b.id).then(() => loadData())}
                        className="p-1.5 bg-rose-600/10 text-rose-500 rounded hover:bg-rose-600/20"
                       >
                         <Trash2 className="w-3.5 h-3.5" />
                       </button>
                    </div>
                 </div>
               ))}
            </div>
         </Panel>

         <Panel title="Dettaglio Hardening Reports" icon={<ShieldAlert className="w-4 h-4 text-rose-400" />}>
            <div className="space-y-2">
               {hardening?.checks.map((c, i) => (
                 <div key={i} className="flex gap-3 items-start p-2 rounded bg-slate-900/40 border border-slate-800">
                    {c.status === 'OK' ? <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5" /> : 
                     c.status === 'WARNING' ? <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5" /> : 
                     <XCircle className="w-4 h-4 text-rose-500 mt-0.5" />}
                    <div className="min-w-0">
                       <p className="text-[11px] font-bold text-slate-200">{c.check_name}</p>
                       <p className="text-[10px] text-slate-500">{c.message}</p>
                    </div>
                 </div>
               ))}
            </div>
         </Panel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
         <Panel title="Importazione Dati" icon={<Upload className="w-4 h-4" />}>
            <div className="space-y-4">
               <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1">
                     <label className="text-[10px] text-slate-500 uppercase font-bold">Tipo Import</label>
                     <select 
                        value={importType} 
                        onChange={e => setImportType(e.target.value)}
                        className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1.5 text-xs text-white"
                     >
                        <option value="UNIVERSE">Universo Asset</option>
                        <option value="WATCHLIST">Watchlist</option>
                        <option value="PORTFOLIO">Portafoglio</option>
                     </select>
                  </div>
                  <div className="space-y-1">
                     <label className="text-[10px] text-slate-500 uppercase font-bold">Nome File (in data/import)</label>
                     <input 
                        type="text" 
                        placeholder="asset_list.csv"
                        value={importFileName} 
                        onChange={e => setImportFileName(e.target.value)}
                        className="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1.5 text-xs text-white"
                     />
                  </div>
               </div>
               <button 
                  onClick={handleRunImport}
                  disabled={!importFileName}
                  className="w-full py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 text-xs font-bold"
               >
                  Esegui Importazione
               </button>
               {importResult && (
                  <div className="p-3 rounded bg-slate-950/60 border border-slate-800 text-[10px] space-y-1">
                     <p className="text-emerald-400 font-bold">Importazione {importResult.status}!</p>
                     <p>Record elaborati: {importResult.records_processed}</p>
                     <p>Importati con successo: {importResult.records_imported}</p>
                     <p className="text-rose-400">Falliti: {importResult.records_failed}</p>
                  </div>
               )}
            </div>
         </Panel>

         <Panel title="Export Generati" icon={<Download className="w-4 h-4 text-indigo-400" />}>
            <div className="space-y-2 max-h-[300px] overflow-y-auto">
               {exports.map(e => (
                 <div key={e.id} className="p-2.5 rounded-lg bg-slate-900/40 border border-slate-800 flex items-center justify-between">
                    <div className="flex gap-3 items-center min-w-0">
                       {e.file_format === 'JSON' ? <FileJson className="w-4 h-4 text-amber-400" /> : <FileSpreadsheet className="w-4 h-4 text-emerald-400" />}
                       <div className="min-w-0">
                          <p className="text-[11px] font-bold text-slate-200 truncate">{e.export_name}</p>
                          <p className="text-[9px] text-slate-500">{e.export_type} · {(e.size_bytes / 1024).toFixed(1)} KB</p>
                       </div>
                    </div>
                    <span className="text-[9px] text-slate-600">{new Date(e.created_at).toLocaleDateString()}</span>
                 </div>
               ))}
               {exports.length === 0 && <p className="text-xs text-slate-600 italic">Nessun export generato</p>}
            </div>
         </Panel>
      </div>
    </div>
  );
}

import { XCircle } from "lucide-react";
