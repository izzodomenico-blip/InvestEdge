import { useEffect, useState } from "react";
import { 
  FileText, 
  ChevronRight, 
  Calendar, 
  CheckCircle2, 
  AlertTriangle,
  History,
  Download,
  Zap,
  RefreshCw
} from "lucide-react";
import { Panel } from "../components/Panel";
import { api, type OperationalReport } from "../lib/api";
import { formatCurrency } from "../lib/format";

export function ReportsPage() {
  const [reports, setReports] = useState<OperationalReport[]>([]);
  const [selectedReport, setSelectedReport] = useState<OperationalReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadInitialData() {
    setLoading(true);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const data = await api.listReports(pId);
      setReports(data);
      if (data.length > 0) {
        setSelectedReport(await api.getReport(data[0].id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento report.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadInitialData();
  }, []);

  async function handleGenerate(type: string = "MANUAL") {
    setGenerating(true);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const report = await api.generateReport(type, pId);
      setReports([report, ...reports]);
      setSelectedReport(report);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore generazione report.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleSelect(id: number) {
    setLoading(true);
    try {
      setSelectedReport(await api.getReport(id));
    } finally {
      setLoading(false);
    }
  }

  if (loading && reports.length === 0) return <div className="p-8 text-center">Caricamento report...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FileText className="w-6 h-6 text-indigo-500" />
          Operational Reports
        </h1>
        <button
          onClick={() => handleGenerate()}
          disabled={generating}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors text-sm font-medium flex items-center gap-2"
        >
          {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          Genera Report Manuale
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <Panel title="Cronologia Report" icon={<History className="w-4 h-4" />}>
            <div className="space-y-2 max-h-[600px] overflow-y-auto">
              {reports.map(r => (
                <div 
                  key={r.id}
                  onClick={() => handleSelect(r.id)}
                  className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                    selectedReport?.id === r.id 
                    ? 'bg-indigo-500/10 border-indigo-500/40' 
                    : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-bold text-slate-300">
                    <span>{r.report_type}</span>
                    <ChevronRight className="w-3 h-3" />
                  </div>
                  <div className="text-[10px] text-slate-500 mt-1 flex items-center gap-1">
                    <Calendar className="w-3 h-3" /> {new Date(r.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
              {reports.length === 0 && <p className="text-xs text-slate-600 italic">Nessun report generato</p>}
            </div>
          </Panel>
        </div>

        <div className="lg:col-span-3 space-y-6">
          {selectedReport ? (
            <>
              {selectedReport.markdown_text?.includes("Riepilogo Fiscale") && (
                <p className="text-xs text-amber-200/80 rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2">
                  Include riepilogo fiscale simulato (non consulenza ufficiale).
                </p>
              )}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <ReportSummaryTile label="Qualità Dati" value={`${selectedReport.summary.data_quality_avg}%`} />
                <ReportSummaryTile label="Asset BUY" value={selectedReport.summary.buy_candidates_count} />
                <ReportSummaryTile label="Alert Aperti" value={selectedReport.summary.open_alerts_count} tone={selectedReport.summary.open_alerts_count > 0 ? "rose" : "emerald"} />
                <ReportSummaryTile label="Valore Port." value={formatCurrency(selectedReport.summary.portfolio_value)} />
              </div>

              <Panel title={selectedReport.title} action={
                <button className="p-2 hover:bg-slate-800 rounded-lg transition-colors text-slate-400" title="Esporta Markdown">
                  <Download className="w-4 h-4" />
                </button>
              }>
                <div className="prose prose-invert prose-sm max-w-none">
                  {selectedReport.markdown_text?.split('\n').map((line, i) => (
                    <p key={i} className={line.startsWith('#') ? 'font-bold text-slate-100 border-b border-slate-800 pb-2 mt-6 mb-4' : 'text-slate-300 my-1'}>
                      {line.startsWith('#') ? line.replace(/#/g, '').trim() : line}
                    </p>
                  ))}
                </div>
              </Panel>
            </>
          ) : (
            <div className="h-[400px] flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-xl bg-slate-900/20 text-slate-500">
              <FileText className="w-12 h-12 mb-4 text-slate-700" />
              <p className="text-lg font-medium">Nessun report selezionato</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ReportSummaryTile({ label, value, tone = "indigo" }: { label: string, value: string | number, tone?: string }) {
  const colors: Record<string, string> = {
    indigo: "text-indigo-400 bg-indigo-500/5 border-indigo-500/10",
    rose: "text-rose-400 bg-rose-500/5 border-rose-500/10",
    emerald: "text-emerald-400 bg-emerald-500/5 border-emerald-500/10",
  };
  return (
    <div className={`p-4 rounded-xl border ${colors[tone]} flex flex-col gap-1`}>
      <span className="text-[10px] uppercase font-bold tracking-wider opacity-60">{label}</span>
      <span className="text-xl font-bold">{value}</span>
    </div>
  );
}
