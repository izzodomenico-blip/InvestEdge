import type { EvidenceReport } from "../lib/api";
import { EvidenceBadge } from "./EvidenceBadge";
import { Panel } from "./Panel";

function number(value: unknown, digits = 3) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "N/D";
}
function percent(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? (value * 100).toFixed(2) + "%" : "N/D";
}
function percentPoints(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) + "%" : "N/D";
}
function money(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(value) : "N/D";
}
function Metrics({ items }: { items: [string, string][] }) {
  return <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
    {items.map(([label, value]) => <div key={label} className="min-w-0">
      <dt className="text-sm text-slate-300">{label}</dt>
      <dd className="num mt-1 break-words text-lg font-semibold text-white">{value}</dd>
    </div>)}
  </dl>;
}
function RecordDetails({ title, value }: { title: string; value: unknown }) {
  return <details className="mt-4 border-t border-slate-800 pt-4">
    <summary className="cursor-pointer text-sm text-slate-200 focus:outline-cyan-300">{title}</summary>
    <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs text-slate-300">{JSON.stringify(value, null, 2)}</pre>
  </details>;
}
export function EvidencePanel({ report }: { report: EvidenceReport }) {
  const m = report.metrics, w = report.walk_forward;
  return <Panel title={"Evidenza · " + report.horizon + " sedute"} action={<EvidenceBadge latest={null} report={report} />}>
    <p className="text-sm text-slate-300">REAL · {report.signal_name} · {report.timeframe} · report #{report.id} · {report.created_at}</p>
    <p className="mt-2 text-sm text-slate-300">Verdetto sul segnale nell'universo, non sul singolo titolo.</p>
    <h3 className="mb-4 mt-6 font-medium text-white">Qualità del segnale</h3>
    <Metrics items={[
      ["IC medio", number(m.ic_mean)], ["Deviazione IC", number(m.ic_std)], ["IC IR", number(m.ic_ir)],
      ["t Newey–West", number(m.t_nw)], ["Quota IC > 0", percent(m.ic_positive_share)],
      ["Date IC", String(m.ic_dates)], ["Titoli medi per data", number(m.mean_names, 1)],
      ["Spread lordo", percent(m.spread_gross)], ["Spread netto", percent(m.spread_net)],
      ["Ricambio top per ribilanciamento", percent(m.turnover_top)], ["Autocorrelazione ranghi", number(m.rank_autocorr)],
    ]} />
    <h3 className="mb-3 mt-6 font-medium text-white">Rendimenti dei bucket · {m.bucket_count === 10 ? "decili" : "quintili"}</h3>
    <dl className="flex flex-wrap gap-x-6 gap-y-3">{m.bucket_returns.map((v, i) => <div key={i}>
      <dt className="text-sm text-slate-300">Bucket {i + 1}</dt><dd className="num text-white">{percent(v)}</dd>
    </div>)}</dl>
    <p className="mt-3 text-sm text-slate-300">Lo spread high-low è diagnostico; non rappresenta una strategia short eseguibile.</p>
    <h3 className="mb-4 mt-6 font-medium text-white">Walk-forward fuori campione</h3>
    {w ? <>
      <Metrics items={[
        ["Sedute OOS", String(w.oos_sessions)], ["Osservazioni OOS", String(w.oos_observations)],
        ["Sharpe IS medio giornaliero", number(w.is_sharpe_mean_daily)], ["Sharpe OOS giornaliero", number(w.oos_sharpe_daily)],
        ["Sharpe OOS annualizzato", number(w.oos_metrics.sharpe_ratio)], ["Degrado IS/OOS", number(w.degradation_daily)],
        ["DSR", number(w.dsr?.dsr)], ["Tentativi N", String(w.n_trials)],
        ["Rendimento OOS", percentPoints(w.oos_metrics.total_return_percent)],
        ["CAGR OOS", percentPoints(w.oos_metrics.cagr)], ["Drawdown OOS", percentPoints(w.oos_metrics.max_drawdown)],
        ["Valore finale OOS", money(w.oos_metrics.final_value_eur)], ["Commissioni OOS", money(w.costs.commission_eur)],
        ["Spread/slippage OOS", money(w.costs.spread_cost_eur)], ["Turnover OOS cumulativo", number(w.turnover, 2) + "×"],
        ["Esposizione OOS media", percent(w.exposure)],
      ]} />
      <details className="mt-5">
        <summary className="cursor-pointer font-medium text-slate-200">Finestre walk-forward · {w.windows.length}</summary>
        <div className="mt-4 space-y-4">{w.windows.map(window => <div key={window.index} className="border-t border-slate-800 pt-3 text-sm text-slate-300">
          <p className="font-medium text-white">Finestra {window.index + 1}</p>
          <p>IS: {window.is_start} → {window.is_end}</p><p>OOS: {window.oos_start} → {window.oos_end}</p>
          <p>Sharpe IS giornaliero: {number(window.is_sharpe)}</p>
          <p>Scelta IS: {window.chosen.name}; top {window.chosen.top_n}; peso {percent(window.chosen.max_asset_weight)};
            buy {window.chosen.buy_threshold}; sell {window.chosen.sell_threshold}; {window.chosen.rebalance_frequency}</p>
        </div>)}</div>
      </details>
      <RecordDetails title="Metriche OOS e statistica DSR complete" value={{ metrics: w.oos_metrics, dsr: w.dsr, grid_size: w.grid_size, units: w.units }} />
    </> : <p className="text-sm text-slate-300">N/D · Campione insufficiente per il walk-forward; consulta il verdetto e i limiti.</p>}
    <h3 className="mb-3 mt-6 font-medium text-white">Universo valutato · {report.universe.assets.length} asset</h3>
    <p className="break-words text-sm text-slate-300">{report.universe.assets.map(a => a.symbol + " (" + a.asset_type + ")").join(", ") || "Nessun asset ammissibile"}</p>
    {Object.keys(report.universe.excluded).length > 0 && <><h4 className="mt-4 font-medium text-white">Asset esclusi</h4>
      <dl className="mt-2 space-y-2 text-sm">{Object.entries(report.universe.excluded).map(([symbol, reason]) => <div key={symbol}>
        <dt className="font-semibold text-slate-200">{symbol}</dt><dd className="break-words text-slate-300">{reason}</dd>
      </div>)}</dl></>}
    <h3 className="mb-3 mt-6 font-medium text-white">Limiti della validazione</h3>
    <ul className="list-disc space-y-2 pl-5 text-sm text-slate-300">
      {Object.entries(report.limits).filter(([,v]) => typeof v === "string" && v).map(([key,v]) => <li key={key}>{String(v)}</li>)}
    </ul>
    <RecordDetails title="Limiti completi e rettifiche" value={report.limits} />
    <RecordDetails title="Configurazione salvata, soglie e impronta" value={{ fingerprint: report.fingerprint, inputs_hash: report.universe.inputs_hash, config: report.config }} />
  </Panel>;
}
