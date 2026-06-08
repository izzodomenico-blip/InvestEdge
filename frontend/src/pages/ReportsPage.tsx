import { useEffect, useState } from "react";
import { BriefcaseBusiness, Download, FileText, Receipt, Repeat2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { PageHeader } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { apiGet, apiUrl, type ReportSummary } from "../lib/api";
import { formatCurrency } from "../lib/format";

type ReportFile = {
  title: string;
  desc: string;
  path: string;
  icon: LucideIcon;
  count: (s: ReportSummary) => number;
};

const files: ReportFile[] = [
  {
    title: "Portafoglio",
    desc: "Posizioni, prezzo medio, valore, P/L e peso.",
    path: "/reports/portfolio.csv",
    icon: BriefcaseBusiness,
    count: (s) => s.positions_count,
  },
  {
    title: "Operazioni",
    desc: "Storico ordini simulati: data, tipo, quantità, prezzo, commissioni.",
    path: "/reports/orders.csv",
    icon: Repeat2,
    count: (s) => s.orders_count,
  },
  {
    title: "Fiscale",
    desc: "Plus/minus realizzate (FIFO) con anno fiscale e aliquota.",
    path: "/reports/tax.csv",
    icon: Receipt,
    count: (s) => s.realized_events_count,
  },
];

export function ReportsPage() {
  const [summary, setSummary] = useState<ReportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void apiGet<ReportSummary>("/reports/summary").then(setSummary).catch((err) => {
      setError(err instanceof Error ? err.message : "Errore caricamento report.");
    });
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Esporta"
        index="12"
        title="Reports"
        subtitle="Scarica i tuoi dati in CSV (apribili con Excel o Google Sheets): portafoglio, operazioni e report fiscale."
      />

      {error && <div className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}

      {summary && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Tile label="Valore portafoglio" value={formatCurrency(summary.portfolio_value, "EUR")} tone="text-white" />
          <Tile label="P/L totale" value={formatCurrency(summary.total_pnl, "EUR")} tone={summary.total_pnl >= 0 ? "text-emerald-300" : "text-rose-300"} />
          <Tile label="Operazioni" value={String(summary.orders_count)} tone="text-cyan-200" />
          <Tile label="Imposta stimata" value={formatCurrency(summary.estimated_tax_due, "EUR")} tone="text-amber-200" />
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {files.map((file) => {
          const Icon = file.icon;
          const count = summary ? file.count(summary) : null;
          return (
            <Panel key={file.path}>
              <div className="flex items-start gap-3">
                <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-cyan-300/25 bg-cyan-400/10 text-cyan-200">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <h3 className="font-display text-lg font-medium text-white">{file.title}</h3>
                  <p className="mt-1 text-sm text-slate-400">{file.desc}</p>
                  {count != null && <p className="mt-1 font-mono text-xs text-slate-500">{count} righe</p>}
                </div>
              </div>
              <a
                href={apiUrl(file.path)}
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-cyan-300/30 bg-cyan-400/15 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/25"
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                Scarica CSV
              </a>
            </Panel>
          );
        })}
      </div>

      <p className="flex items-center justify-center gap-2 text-center text-xs text-slate-600">
        <FileText className="h-3.5 w-3.5" aria-hidden="true" />
        I file CSV si aprono con Excel, Numbers o Google Sheets. I dati sono quelli del portafoglio simulato locale.
      </p>
    </div>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-slate-800/60 bg-slate-950/55 p-4 shadow-panel">
      <p className="eyebrow-muted">{label}</p>
      <p className={`number-lg mt-2 ${tone}`}>{value}</p>
    </div>
  );
}
