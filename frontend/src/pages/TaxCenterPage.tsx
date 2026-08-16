import { useEffect, useState } from "react";
import { AlertTriangle, ExternalLink, Receipt, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { apiGet, type TaxReport } from "../lib/api";
import { formatCurrency } from "../lib/format";

const categoryLabels = {
  standard: "Standard",
  government_bond: "Titolo governativo",
  crypto: "Cripto",
  euro_emt: "Titolo estero white-list",
};

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
        title="Stima fiscale semplificata, non dichiarazione"
        subtitle="Plusvalenze e minusvalenze stimate dagli ordini paper, con lotti firmati, cambi di esecuzione congelati e regole versionate per anno."
        meta={
          report ? (
            <>
              <span>Metodo <span className="text-cyan-300/80">{report.lot_method}</span></span>
              <span>Valuta base <span className="text-cyan-300/80">{report.base_currency}</span></span>
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
        <div className="rounded-2xl border border-amber-300/25 bg-amber-400/[0.08] px-4 py-3 text-sm text-amber-100">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div>
              <p className="font-semibold">Classificazione fiscale prudenziale</p>
              <p className="mt-1 text-xs leading-5 text-amber-100/75">
                Gli strumenti senza una categoria governativa verificata restano “standard” al 26%; in particolare, un ETF obbligazionario non riceve automaticamente l’aliquota agevolata.
              </p>
              {report.classification_warnings.map((warning) => (
                <p key={warning} className="mt-1 text-xs leading-5 text-amber-100/90">{warning}</p>
              ))}
            </div>
          </div>
        </div>
      )}

      {report && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Tile label="Imposta totale stimata" value={formatCurrency(report.total_tax_due, "EUR")} tone="text-rose-300" />
          <Tile label="Plus/minus netta realizzata" value={formatCurrency(report.total_realized_net, "EUR")} tone={report.total_realized_net >= 0 ? "text-emerald-300" : "text-rose-300"} />
          <Tile label="Perdite riportabili (zainetto)" value={formatCurrency(report.loss_carryforward, "EUR")} tone="text-amber-200" />
          <Tile label="Eventi realizzati" value={String(report.events.length)} tone="text-white" />
        </div>
      )}

      {report && (
        <Panel eyebrow="Metodo e fonti" title="Regole applicate per categoria e anno">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {report.tax_rules.map((rule) => (
              <div key={`${rule.tax_category}-${rule.from_year}`} className="rounded-xl border border-slate-800/60 bg-slate-950/55 p-3">
                <p className="text-sm font-semibold text-white">{categoryLabels[rule.tax_category]}</p>
                <p className="mt-1 text-xs text-slate-400">
                  {rule.rate}% · {rule.from_year === 0 ? "regola base" : `dal ${rule.from_year}`}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs leading-5 text-slate-400">{report.carryforward_note}</p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs">
            {report.sources.map((source) => (
              <a key={source.id} href={source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200">
                {source.title}<ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            ))}
          </div>
        </Panel>
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
                  <th className="px-3 pb-3 text-right font-medium">Minus anno usate</th>
                  <th className="px-3 pb-3 text-right font-medium">Riporto usato</th>
                  <th className="px-3 pb-3 text-right font-medium">Scadute</th>
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
                    <td className="num px-3 py-3 text-right text-slate-400">{formatCurrency(year.current_year_losses_used, "EUR")}</td>
                    <td className="num px-3 py-3 text-right text-slate-400">{formatCurrency(year.carryforward_used, "EUR")}</td>
                    <td className="num px-3 py-3 text-right text-slate-500">{formatCurrency(year.carryforward_expired, "EUR")}</td>
                    <td className="num px-3 py-3 text-right text-amber-200">{formatCurrency(year.carryforward_remaining, "EUR")}</td>
                    <td className="num px-3 py-3 pr-0 text-right font-semibold text-white">{formatCurrency(year.tax_due, "EUR")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {report && report.loss_carryforward_buckets.length > 0 && (
        <Panel eyebrow="Minusvalenze" title="Bucket ancora utilizzabili">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {report.loss_carryforward_buckets.map((bucket) => (
              <div key={`${bucket.tax_category}-${bucket.origin_year}`} className="rounded-xl border border-slate-800/60 bg-slate-950/55 p-3">
                <p className="text-sm font-semibold text-white">{categoryLabels[bucket.tax_category]}</p>
                <p className="mt-1 text-xs text-slate-400">Origine {bucket.origin_year} · utilizzabile fino al {bucket.expires_after_year}</p>
                <p className="num mt-2 text-sm font-semibold text-amber-200">{formatCurrency(bucket.remaining, "EUR")}</p>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {report && report.events.length > 0 && (
        <Panel eyebrow="Operazioni chiuse" title="Eventi realizzati">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {report.events.map((event, index) => (
              <div key={`${event.symbol}-${event.realization_date}-${index}`} className="rounded-xl border border-slate-800/60 bg-slate-950/55 p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-semibold text-white">{event.symbol}</span>
                  <span className={`inline-flex items-center gap-1 text-xs font-semibold ${event.gain >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    {event.gain >= 0 ? <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" /> : <TrendingDown className="h-3.5 w-3.5" aria-hidden="true" />}
                    {formatCurrency(event.gain_base, "EUR")}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {event.realization_date} · {event.open_side} → {event.close_side} · {event.quantity} quote
                </p>
                <p className="mt-1 text-xs text-slate-500">{categoryLabels[event.tax_category]} · aliquota {event.applied_rate}%</p>
                <p className="num mt-1 text-xs text-slate-400">
                  Base EUR {formatCurrency(event.open_value_base, "EUR")} → {formatCurrency(event.close_value_base, "EUR")}
                </p>
                {event.currency !== "EUR" && (
                  <p className="num mt-1 text-xs text-slate-500">
                    Nativo {event.open_value_native.toFixed(2)} → {event.close_value_native.toFixed(2)} {event.currency}
                  </p>
                )}
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
                  {lot.unrealized_gain_base != null && (
                    <span className={`num text-xs font-semibold ${lot.unrealized_gain_base >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{formatCurrency(lot.unrealized_gain_base, "EUR")}</span>
                  )}
                </div>
                <p className="mt-1 text-xs text-slate-500">{lot.open_side} · {categoryLabels[lot.tax_category]}</p>
                <p className="num mt-1 text-xs text-slate-400">{lot.quantity} quote · apertura {formatCurrency(lot.open_value_base, "EUR")}</p>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {!hasData && !error && (
        <Panel title="Nessun dato fiscale">
          <p className="text-sm text-slate-400">
            Non ci sono ancora lotti aperti o operazioni di chiusura da cui stimare plusvalenze e minusvalenze.
            Un SELL può chiudere un long; un BUY può ricoprire uno short.
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
