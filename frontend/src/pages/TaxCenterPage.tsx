import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Calculator,
  Download,
  FileSpreadsheet,
  Globe,
  RefreshCw,
  Save,
  Settings2,
} from "lucide-react";
import { Panel } from "../components/Panel";
import { PortfolioSelector } from "../components/PortfolioSelector";
import {
  api,
  type TaxLot,
  type TaxRealizedEvent,
  type TaxReport,
  type TaxSettings,
  type TaxSummary,
  type TaxSummaryGlobal,
} from "../lib/api";
import { formatCurrency } from "../lib/format";

const TABS = ["settings", "summary", "lots", "events", "reports", "global"] as const;
type TabId = (typeof TABS)[number];

export function TaxCenterPage() {
  const [tab, setTab] = useState<TabId>("summary");
  const [portfolioId, setPortfolioId] = useState<number | undefined>(() => {
    const raw = localStorage.getItem("activePortfolioId");
    return raw ? parseInt(raw, 10) : undefined;
  });
  const [taxYear, setTaxYear] = useState(new Date().getFullYear());
  const [settings, setSettings] = useState<TaxSettings | null>(null);
  const [summary, setSummary] = useState<TaxSummary | null>(null);
  const [globalSummary, setGlobalSummary] = useState<TaxSummaryGlobal | null>(null);
  const [lots, setLots] = useState<TaxLot[]>([]);
  const [events, setEvents] = useState<TaxRealizedEvent[]>([]);
  const [reports, setReports] = useState<TaxReport[]>([]);
  const [selectedReport, setSelectedReport] = useState<TaxReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function loadTabData() {
    setLoading(true);
    setError(null);
    try {
      if (tab === "settings") {
        setSettings(await api.getTaxSettings());
      } else if (tab === "summary") {
        setSummary(await api.getTaxSummary(portfolioId, taxYear));
      } else if (tab === "lots") {
        setLots(await api.getTaxLots(portfolioId));
      } else if (tab === "events") {
        setEvents(await api.getTaxRealizedEvents(portfolioId, taxYear));
      } else if (tab === "reports") {
        const list = await api.listTaxReports(portfolioId, taxYear);
        setReports(list);
        if (list.length > 0) {
          setSelectedReport(await api.getTaxReport(list[0].id));
        } else {
          setSelectedReport(null);
        }
      } else if (tab === "global") {
        setGlobalSummary(await api.getTaxSummaryGlobal(taxYear));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento dati fiscali.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTabData();
  }, [tab, portfolioId, taxYear]);

  async function handleSaveSettings() {
    if (!settings) return;
    setBusy(true);
    try {
      const updated = await api.updateTaxSettings({
        country_code: settings.country_code,
        tax_regime: settings.tax_regime,
        capital_gain_tax_rate: settings.capital_gain_tax_rate,
        crypto_tax_rate: settings.crypto_tax_rate,
        dividend_tax_rate: settings.dividend_tax_rate,
        lot_matching_method: settings.lot_matching_method,
        include_fees_in_cost_basis: settings.include_fees_in_cost_basis,
        base_currency: settings.base_currency,
      });
      setSettings(updated);
      setMessage("Impostazioni fiscali salvate.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore salvataggio.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRecalculate() {
    setBusy(true);
    try {
      await api.recalculateTax({ portfolio_id: portfolioId, tax_year: taxYear, method: "FIFO" });
      setMessage("Ricalcolo FIFO completato.");
      await loadTabData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore ricalcolo.");
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerateReport(type: "PORTFOLIO" | "GLOBAL") {
    setBusy(true);
    try {
      const report = await api.generateTaxReport({
        tax_year: taxYear,
        portfolio_id: type === "PORTFOLIO" ? portfolioId : undefined,
        report_type: type,
      });
      setReports((prev) => [report, ...prev]);
      setSelectedReport(report);
      setMessage(`Report ${type} generato.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore generazione report.");
    } finally {
      setBusy(false);
    }
  }

  async function handleExport(fmt: "json" | "csv") {
    setBusy(true);
    try {
      const result = await api.exportTaxReport({
        tax_year: taxYear,
        portfolio_id: portfolioId,
        format: fmt,
      });
      setMessage(`Export ${result.file_format}: ${result.file_path}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore export.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Calculator className="h-7 w-7 text-amber-300" />
            Tax Center / Fiscal Simulator
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Simulazione fiscale indicativa su paper trading. Non sostituisce commercialista o normativa ufficiale.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <PortfolioSelector
            onPortfolioChange={(p) => {
              setPortfolioId(p.id);
              localStorage.setItem("activePortfolioId", String(p.id));
            }}
          />
          <label className="text-xs text-slate-500">
            Anno fiscale
            <input
              type="number"
              className="ml-2 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white"
              value={taxYear}
              onChange={(e) => setTaxYear(parseInt(e.target.value, 10) || new Date().getFullYear())}
            />
          </label>
          <button
            type="button"
            onClick={() => void handleRecalculate()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-100 hover:bg-amber-400/20"
          >
            <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
            Ricalcola FIFO
          </button>
        </div>
      </div>

      <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-100/90 flex gap-2">
        <AlertTriangle className="h-5 w-5 shrink-0 text-amber-400" />
        <span>
          Simulazione fiscale indicativa. Non sostituisce commercialista o normativa fiscale ufficiale.
          Cripto, obbligazioni e dividendi sono placeholder o semplificati.
        </span>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">{error}</div>
      )}
      {message && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-200">{message}</div>
      )}

      <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-2">
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`rounded-md px-3 py-1.5 text-sm capitalize ${
              tab === id ? "bg-amber-400/15 text-amber-100 border border-amber-400/30" : "text-slate-400 hover:text-white"
            }`}
          >
            {id === "global" ? "Multi-portfolio" : id}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="h-48 animate-pulse rounded-xl border border-slate-800 bg-slate-900/50" />
      ) : (
        <>
          {tab === "settings" && settings && (
            <Panel title="Impostazioni fiscali" icon={<Settings2 className="h-4 w-4" />}>
              <div className="grid gap-4 md:grid-cols-2">
                <label className="text-sm text-slate-400">
                  Paese
                  <input
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-white"
                    value={settings.country_code}
                    onChange={(e) => setSettings({ ...settings, country_code: e.target.value })}
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Regime
                  <select
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-white"
                    value={settings.tax_regime}
                    onChange={(e) => setSettings({ ...settings, tax_regime: e.target.value })}
                  >
                    <option value="ITALY_SIMPLIFIED">ITALY_SIMPLIFIED</option>
                  </select>
                </label>
                <label className="text-sm text-slate-400">
                  Capital gain tax %
                  <input
                    type="number"
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-white"
                    value={settings.capital_gain_tax_rate}
                    onChange={(e) =>
                      setSettings({ ...settings, capital_gain_tax_rate: parseFloat(e.target.value) || 26 })
                    }
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Crypto tax % (placeholder)
                  <input
                    type="number"
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-white"
                    value={settings.crypto_tax_rate ?? ""}
                    placeholder="—"
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        crypto_tax_rate: e.target.value ? parseFloat(e.target.value) : null,
                      })
                    }
                  />
                </label>
                <label className="text-sm text-slate-400">
                  Lot method
                  <select
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-white"
                    value={settings.lot_matching_method}
                    onChange={(e) => setSettings({ ...settings, lot_matching_method: e.target.value })}
                  >
                    <option value="FIFO">FIFO</option>
                    <option value="LIFO">LIFO</option>
                    <option value="AVG_COST">AVG_COST</option>
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-300 mt-6">
                  <input
                    type="checkbox"
                    checked={settings.include_fees_in_cost_basis}
                    onChange={(e) =>
                      setSettings({ ...settings, include_fees_in_cost_basis: e.target.checked })
                    }
                  />
                  Include fees in cost basis
                </label>
                <label className="text-sm text-slate-400">
                  Base currency
                  <input
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-white"
                    value={settings.base_currency}
                    onChange={(e) => setSettings({ ...settings, base_currency: e.target.value })}
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={() => void handleSaveSettings()}
                disabled={busy}
                className="mt-4 inline-flex items-center gap-2 rounded-md bg-cyan-500/20 px-4 py-2 text-sm text-cyan-100 border border-cyan-400/30"
              >
                <Save className="h-4 w-4" /> Salva
              </button>
            </Panel>
          )}

          {tab === "summary" && summary && (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              <Panel title="Plusvalenze">
                <p className="text-2xl font-bold text-emerald-300">{formatCurrency(summary.total_realized_gains)}</p>
              </Panel>
              <Panel title="Minusvalenze">
                <p className="text-2xl font-bold text-rose-300">{formatCurrency(summary.total_realized_losses)}</p>
              </Panel>
              <Panel title="P/L netto realizzato">
                <p className="text-2xl font-bold text-white">{formatCurrency(summary.net_realized_pnl)}</p>
              </Panel>
              <Panel title="Imposta teorica stimata">
                <p className="text-2xl font-bold text-amber-200">{formatCurrency(summary.estimated_tax_due)}</p>
              </Panel>
              <Panel title="P/L non realizzato">
                <p className="text-2xl font-bold text-slate-200">{formatCurrency(summary.unrealized_pnl)}</p>
              </Panel>
              <Panel title="Compensazione carryforward">
                <p className="text-2xl font-bold text-slate-200">{formatCurrency(summary.loss_carryforward)}</p>
              </Panel>
              {summary.warnings.length > 0 && (
                <div className="md:col-span-2 lg:col-span-3 text-xs text-slate-400 space-y-1">
                  {summary.warnings.map((w) => (
                    <p key={w}>• {w}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === "lots" && (
            <Panel title="Tax lots (FIFO)" icon={<FileSpreadsheet className="h-4 w-4" />}>
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="text-slate-500 border-b border-slate-800">
                    <tr>
                      <th className="py-2">Symbol</th>
                      <th>Buy date</th>
                      <th>Qty init</th>
                      <th>Qty rem</th>
                      <th>Buy price</th>
                      <th>Cost basis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lots.map((lot) => (
                      <tr key={lot.id} className="border-b border-slate-800/50 text-slate-200">
                        <td className="py-2 font-medium">{lot.symbol}</td>
                        <td>{lot.buy_date.slice(0, 10)}</td>
                        <td>{lot.quantity_initial}</td>
                        <td>{lot.quantity_remaining}</td>
                        <td>{formatCurrency(lot.buy_price)}</td>
                        <td>{formatCurrency(lot.cost_basis)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          {tab === "events" && (
            <Panel title="Realized events">
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="text-slate-500 border-b border-slate-800">
                    <tr>
                      <th className="py-2">Sell date</th>
                      <th>Symbol</th>
                      <th>Qty</th>
                      <th>P/L</th>
                      <th>Year</th>
                      <th>Category</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((ev) => (
                      <tr key={ev.id} className="border-b border-slate-800/50 text-slate-200">
                        <td className="py-2">{ev.sell_date.slice(0, 10)}</td>
                        <td>{ev.symbol}</td>
                        <td>{ev.quantity}</td>
                        <td className={ev.realized_pnl >= 0 ? "text-emerald-300" : "text-rose-300"}>
                          {formatCurrency(ev.realized_pnl)}
                        </td>
                        <td>{ev.tax_year}</td>
                        <td>{ev.tax_category}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          {tab === "reports" && (
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel title="Report fiscali" className="lg:col-span-1">
                <div className="flex flex-wrap gap-2 mb-4">
                  <button
                    type="button"
                    onClick={() => void handleGenerateReport("PORTFOLIO")}
                    className="text-xs rounded border border-slate-700 px-2 py-1 text-slate-200 hover:bg-slate-800"
                  >
                    Genera portfolio
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleExport("json")}
                    className="text-xs inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-slate-200"
                  >
                    <Download className="h-3 w-3" /> JSON
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleExport("csv")}
                    className="text-xs inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-1 text-slate-200"
                  >
                    <Download className="h-3 w-3" /> CSV
                  </button>
                </div>
                <ul className="space-y-2 max-h-96 overflow-y-auto">
                  {reports.map((r) => (
                    <li key={r.id}>
                      <button
                        type="button"
                        onClick={() => void api.getTaxReport(r.id).then(setSelectedReport)}
                        className="w-full text-left rounded border border-slate-800 px-3 py-2 text-sm hover:bg-slate-900"
                      >
                        {r.report_type} {r.tax_year} — {formatCurrency(r.net_realized_pnl)}
                      </button>
                    </li>
                  ))}
                </ul>
              </Panel>
              {selectedReport && (
                <Panel title="Dettaglio report" className="lg:col-span-2">
                  <pre className="text-xs text-slate-300 overflow-auto max-h-[28rem]">
                    {JSON.stringify(selectedReport.summary_json, null, 2)}
                  </pre>
                </Panel>
              )}
            </div>
          )}

          {tab === "global" && globalSummary && (
            <div className="space-y-4">
              <Panel title="Summary globale" icon={<Globe className="h-4 w-4" />}>
                <div className="grid gap-4 sm:grid-cols-3">
                  <div>
                    <p className="text-xs text-slate-500">Net realized</p>
                    <p className="text-xl font-bold">{formatCurrency(globalSummary.net_realized_pnl)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Tax due</p>
                    <p className="text-xl font-bold text-amber-200">{formatCurrency(globalSummary.estimated_tax_due)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Unrealized</p>
                    <p className="text-xl font-bold">{formatCurrency(globalSummary.unrealized_pnl)}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void handleGenerateReport("GLOBAL")}
                  className="mt-4 text-sm rounded border border-slate-700 px-3 py-1.5 text-slate-200"
                >
                  Genera report GLOBAL
                </button>
              </Panel>
              <Panel title="Breakdown per portfolio">
                <div className="space-y-3">
                  {globalSummary.portfolio_summaries.map((ps) => (
                    <div
                      key={ps.portfolio_id}
                      className="flex justify-between rounded border border-slate-800 px-3 py-2 text-sm"
                    >
                      <span>Portfolio #{ps.portfolio_id}</span>
                      <span>
                        {formatCurrency(ps.net_realized_pnl)} — tax {formatCurrency(ps.estimated_tax_due)}
                      </span>
                    </div>
                  ))}
                </div>
              </Panel>
            </div>
          )}
        </>
      )}
    </div>
  );
}
