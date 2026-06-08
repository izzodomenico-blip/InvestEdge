import { useEffect, useState } from "react";
import { Receipt, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { apiGet, type TaxReport } from "../lib/api";
import { formatCurrency } from "../lib/format";

export function TaxCenterPage() {
  const [report, setReport] = useState<TaxReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setReport(await apiGet<TaxReport>("/tax/report"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il calcolo fiscale.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (loading) {
    return (
      <Panel title="Centro fiscale">
        <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  const hasData = report && (report.events.length > 0 || report.open_lots.length > 0);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Fisco / Italia"
        index="11"
        title="Centro fiscale"
        subtitle="Plusvalenze e minusvalenze realizzate dai tuoi ordini, con metodo FIFO, compensazione perdite e imposta stimata."
        meta={
          report ? (
            <>
              <span>Metodo <span className="text-cyan-300/80">{report.lot_method}</span></span>
              <span>Aliquote <span className="text-cyan-300/80">{report.standard_rate}% / {report.bond_rate}%</span></span>
            </>
          ) : undefined
        }
        actions={
          <PageHeaderAction icon={<RefreshCw className="h-4 w-4" aria-hidden="true" />} onClick={() => void load()}>
            Ricalcola
          </PageHeaderAction>
        }
      />

      {error && (
        <div className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      {report && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Tile label="Imposta totale stimata" value={formatCurrency(report.total_tax_due, "EUR")} tone="text-rose-300" />
          <Tile label="Plus/minus netta realizzata" value={formatCurrency(report.total_realized_net, "EUR")} tone={report.total_realized_net >= 0 ? "text-emerald-300" : "text-rose-300"} />
          <Tile label="Perdite riportabili (zainetto)" value={formatCurrency(report.loss_carryforward, "EUR")} tone="text-amber-200" />
          <Tile label="Eventi realizzati" value={String(report.events.length)} tone="text-white" />
        </div>
      )}

      {report && report.years.length > 0 && (
        <Panel eyebrow="Per anno fiscale" title="Riepilogo annuale">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="px-3 pb-3 pl-0 font-medium">Anno</th>
                  <th className="px-3 pb-3 text-right font-medium">Plusvalenze</th>
                  <th className="px-3 pb-3 text-right font-medium">Minusvalenze</th>
                  <th className="px-3 pb-3 text-right font-medium">Netto</th>
                  <th className="px-3 pb-3 text-right font-medium">Perdite usate</th>
                  <th className="px-3 pb-3 text-right font-medium">Riporto</th>
                  <th className="px-3 pb-3 pr-0 text-right font-medium">Imposta</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {report.years.map((year) => (
                  <tr key={year.tax_year}>
                    <td className="px-3 py-3 pl-0 font-semibold text-white">{year.tax_year}</td>
                    <td className="num px-3 py-3 text-right text-emerald-300">{formatCurrency(year.total_gains, "EUR")}</td>
                    <td className="num px-3 py-3 text-right text-rose-300">{formatCurrency(year.total_losses, "EUR")}</td>
                    <td className={`num px-3 py-3 text-right font-semibold ${year.net_realized >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{formatCurrency(year.net_realized, "EUR")}</td>
                    <td className="num px-3 py-3 text-right text-slate-400">{formatCurrency(year.carryforward_used, "EUR")}</td>
                    <td className="num px-3 py-3 text-right text-amber-200">{formatCurrency(year.carryforward_remaining, "EUR")}</td>
                    <td className="num px-3 py-3 pr-0 text-right font-semibold text-white">{formatCurrency(year.tax_due, "EUR")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {report && report.events.length > 0 && (
        <Panel eyebrow="Operazioni chiuse" title="Eventi realizzati">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {report.events.map((event, index) => (
              <div key={`${event.symbol}-${event.sell_date}-${index}`} className="rounded-xl border border-slate-800/60 bg-slate-950/55 p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-semibold text-white">{event.symbol}</span>
                  <span className={`inline-flex items-center gap-1 text-xs font-semibold ${event.gain >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    {event.gain >= 0 ? <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" /> : <TrendingDown className="h-3.5 w-3.5" aria-hidden="true" />}
                    {formatCurrency(event.gain, "EUR")}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{event.sell_date} · {event.quantity} quote · {event.rate}%</p>
                <p className="num mt-1 text-xs text-slate-400">costo {formatCurrency(event.cost_basis, "EUR")} → ricavo {formatCurrency(event.proceeds, "EUR")}</p>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {report && report.open_lots.length > 0 && (
        <Panel eyebrow="Posizioni aperte" title="Plus/minus latenti (non tassate)">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {report.open_lots.map((lot) => (
              <div key={lot.symbol} className="rounded-xl border border-slate-800/60 bg-slate-950/55 p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-semibold text-white">{lot.symbol}</span>
                  {lot.unrealized_gain != null && (
                    <span className={`num text-xs font-semibold ${lot.unrealized_gain >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{formatCurrency(lot.unrealized_gain, "EUR")}</span>
                  )}
                </div>
                <p className="num mt-1 text-xs text-slate-400">{lot.quantity} quote · costo {formatCurrency(lot.cost_basis, "EUR")}</p>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {!hasData && !error && (
        <Panel title="Nessun dato fiscale">
          <p className="text-sm text-slate-400">
            Non ci sono ancora operazioni di vendita da cui calcolare plusvalenze. Le tasse si realizzano alla vendita:
            simula ordini dal Simulatore o crea un portafoglio, poi vendi per vedere il calcolo.
          </p>
        </Panel>
      )}

      {report && <p className="text-center text-xs text-slate-600">{report.disclaimer}</p>}
    </div>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-slate-800/60 bg-slate-950/55 p-4 shadow-panel">
      <p className="eyebrow-muted flex items-center gap-2"><Receipt className="h-3 w-3" aria-hidden="true" />{label}</p>
      <p className={`number-lg mt-2 ${tone}`}>{value}</p>
    </div>
  );
}
