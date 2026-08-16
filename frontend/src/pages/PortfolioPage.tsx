import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, ChevronRight, RefreshCw, RotateCcw } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AllocationPlanner } from "../components/AllocationPlanner";
import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { Tabs } from "../components/Tabs";
import { TradeButton } from "../components/TradeButton";
import {
  apiGet,
  apiPost,
  type PortfolioRecommendation,
  type PortfolioSnapshot,
  type PortfolioSummary,
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const colors = ["#22D3EE", "#34D399", "#60A5FA", "#F59E0B", "#FB7185", "#A78BFA"];
const baseCurrency = "EUR";

const assetTypeLabels: Record<string, string> = {
  stock: "Azioni",
  etf: "ETF",
  crypto: "Cripto",
  bond: "Bond",
  bond_etf: "ETF bond",
};

type TabId = "positions" | "allocation" | "trend" | "risk";

function pnlClass(value: number) {
  return value >= 0 ? "text-emerald-300" : "text-rose-300";
}

function recommendationTone(value: string | null) {
  if (value?.includes("BLOCK") || value === "SELL") {
    return "border-rose-300/20 bg-rose-400/10 text-rose-200";
  }
  if (value === "REDUCE") {
    return "border-amber-300/20 bg-amber-400/10 text-amber-200";
  }
  if (value === "BUY_ALLOWED") {
    return "border-emerald-300/20 bg-emerald-400/10 text-emerald-200";
  }
  return "border-slate-700 bg-slate-900 text-slate-300";
}

export function PortfolioPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [snapshots, setSnapshots] = useState<PortfolioSnapshot[]>([]);
  const [recommendations, setRecommendations] = useState<PortfolioRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showReset, setShowReset] = useState(false);
  const [resetCash, setResetCash] = useState("10000");
  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("positions");
  const portfolioOperationInFlight = useRef(false);
  const portfolioBusy = refreshing || resetting;

  async function loadPortfolio() {
    setLoading(true);
    setError(null);
    try {
      const [portfolio, snapshotData, recommendationData] = await Promise.all([
        apiGet<PortfolioSummary>("/portfolio"),
        apiGet<PortfolioSnapshot[]>("/portfolio/snapshots"),
        apiGet<PortfolioRecommendation[]>("/portfolio/recommendations"),
      ]);
      setSummary(portfolio);
      setSnapshots(snapshotData);
      setRecommendations(recommendationData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento del portafoglio.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshPortfolio() {
    if (portfolioOperationInFlight.current) {
      return;
    }
    portfolioOperationInFlight.current = true;
    setRefreshing(true);
    setError(null);
    try {
      const portfolio = await apiPost<PortfolioSummary>("/portfolio/refresh");
      const [snapshotData, recommendationData] = await Promise.all([
        apiGet<PortfolioSnapshot[]>("/portfolio/snapshots"),
        apiGet<PortfolioRecommendation[]>("/portfolio/recommendations"),
      ]);
      setSummary(portfolio);
      setSnapshots(snapshotData);
      setRecommendations(recommendationData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante l'aggiornamento del portafoglio.");
    } finally {
      portfolioOperationInFlight.current = false;
      setRefreshing(false);
    }
  }

  async function resetPortfolio() {
    if (portfolioOperationInFlight.current) {
      return;
    }
    const cash = Number(resetCash);
    if (!(cash > 0)) {
      setResetMsg("Inserisci un capitale maggiore di zero.");
      return;
    }
    portfolioOperationInFlight.current = true;
    setResetting(true);
    setResetMsg(null);
    try {
      const portfolio = await apiPost<PortfolioSummary>("/portfolio/init", {
        initial_cash: cash,
        confirm_reset: "RESET_PORTFOLIO",
      });
      setSummary(portfolio);
      setSnapshots([]);
      setRecommendations([]);
      setShowReset(false);
      setResetMsg("Portafoglio azzerato: posizioni, ordini simulati e snapshot cancellati; liquidità reimpostata.");
      try {
        const [snapshotData, recommendationData] = await Promise.all([
          apiGet<PortfolioSnapshot[]>("/portfolio/snapshots"),
          apiGet<PortfolioRecommendation[]>("/portfolio/recommendations"),
        ]);
        setSnapshots(snapshotData);
        setRecommendations(recommendationData);
      } catch (err) {
        const detail = err instanceof Error ? err.message : "refresh non riuscito";
        setError(`Portafoglio azzerato, ma i dati secondari non sono stati aggiornati: ${detail}`);
      }
    } catch (err) {
      setResetMsg(err instanceof Error ? err.message : "Azzeramento non riuscito.");
    } finally {
      portfolioOperationInFlight.current = false;
      setResetting(false);
    }
  }

  useEffect(() => {
    void loadPortfolio();
  }, []);

  const allocationByType = useMemo(() => {
    if (!summary) {
      return [];
    }
    return Object.entries(summary.allocation_by_asset_type).map(([name, value], index) => ({
      name: assetTypeLabels[name] ?? name,
      value,
      color: colors[index % colors.length],
    }));
  }, [summary]);

  const allocationByCurrency = useMemo(() => {
    if (!summary) {
      return [];
    }
    return Object.entries(summary.allocation_by_currency).map(([name, value], index) => ({
      name,
      value,
      color: colors[(index + 2) % colors.length],
    }));
  }, [summary]);

  const recommendationBySymbol = useMemo(
    () => new Map(recommendations.map((item) => [item.symbol, item])),
    [recommendations],
  );

  if (loading) {
    return (
      <Panel title="Portafoglio">
        <div className="h-56 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel title="Errore">
        <p className="text-sm text-rose-300">{error}</p>
      </Panel>
    );
  }

  if (!summary) {
    return (
      <Panel title="Database non inizializzato">
        <p className="text-slate-300">Database non inizializzato.</p>
        <p className="mt-2 text-sm text-slate-500">Esegui `backend\.venv\Scripts\python.exe scripts\seed_database.py --reset` e ricarica.</p>
      </Panel>
    );
  }

  const openAsset = (symbol: string) => navigate(`/analysis?symbol=${encodeURIComponent(symbol)}`);

  // Esposizione long/short separata: con gli short "Investito" (somma firmata) va
  // negativo ed e' fuorviante. Mostriamo invece patrimonio + esposizioni distinte.
  const longPositions = summary.positions.filter((p) => p.quantity > 0);
  const shortPositions = summary.positions.filter((p) => p.quantity < 0);
  const longExposure = longPositions.reduce((sum, p) => sum + p.current_value_base, 0);
  const shortExposure = shortPositions.reduce((sum, p) => sum + Math.abs(p.current_value_base), 0);
  const hasShorts = shortExposure > 1e-9;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Paper trading"
        index="03"
        title="Portafoglio"
        subtitle="Posizioni simulate, allocation, P/L e warning di rischio. Nessun ordine reale viene inviato."
        actions={
          <>
            <button
              onClick={() => setShowReset((v) => !v)}
              disabled={portfolioBusy}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-slate-800/80 bg-slate-950/60 px-4 py-2.5 text-sm font-medium tracking-tight text-slate-200 transition-all duration-200 hover:border-slate-700 hover:bg-slate-900 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Ricomincia
            </button>
            <PageHeaderAction
              variant="primary"
              onClick={() => void refreshPortfolio()}
              disabled={portfolioBusy}
              icon={<RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />}
            >
              Aggiorna prezzi
            </PageHeaderAction>
          </>
        }
      />

      {resetMsg && (
        <div className="rounded-2xl border border-cyan-300/20 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">{resetMsg}</div>
      )}

      {showReset && (
        <Panel eyebrow="Reset" title="Ricomincia il portafoglio da capo">
          <p className="text-sm text-slate-400">
            Cancella definitivamente <span className="text-rose-200">tutte le posizioni, gli ordini simulati e gli snapshot storici</span>,
            poi reimposta la liquidità al capitale virtuale indicato. Nessun ordine reale viene toccato.
          </p>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="space-y-1">
              <span className="text-xs text-slate-400">Capitale virtuale di partenza (€)</span>
              <input
                type="number"
                value={resetCash}
                onChange={(e) => setResetCash(e.target.value)}
                disabled={portfolioBusy}
                className="block min-h-11 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60 sm:w-56"
              />
            </label>
            <button
              onClick={() => void resetPortfolio()}
              disabled={portfolioBusy}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-rose-300/30 bg-rose-400/15 px-4 py-2 text-sm font-semibold text-rose-100 transition hover:bg-rose-400/25 disabled:opacity-60"
            >
              <RotateCcw className={`h-4 w-4 ${resetting ? "animate-spin" : ""}`} aria-hidden="true" />
              {resetting ? "Azzero..." : "Cancella posizioni, ordini e snapshot e riparti"}
            </button>
            <button
              onClick={() => setShowReset(false)}
              disabled={portfolioBusy}
              className="inline-flex min-h-11 items-center justify-center rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-800"
            >
              Annulla
            </button>
          </div>
        </Panel>
      )}

      {/* Riga riassuntiva compatta. Con posizioni short mostra esposizione long/short
          separata invece di "Investito" (somma firmata, andrebbe in negativo). */}
      <Panel bare className="px-1">
        <div className={`grid grid-cols-2 divide-slate-800/60 sm:divide-x ${hasShorts ? "sm:grid-cols-3 xl:grid-cols-5" : "sm:grid-cols-4"}`}>
          <SummaryStat
            label={hasShorts ? "Patrimonio" : "Valore totale"}
            value={formatCurrency(summary.total_value, baseCurrency)}
            hint={hasShorts ? "il tuo valore reale" : "Cash + posizioni"}
          />
          <SummaryStat
            label="P/L totale"
            value={formatCurrency(summary.total_pnl, baseCurrency)}
            hint={formatPercent(summary.total_pnl_percent)}
            tone={summary.total_pnl >= 0 ? "pos" : "neg"}
          />
          <SummaryStat
            label="Liquidità"
            value={formatCurrency(summary.cash, baseCurrency)}
            hint={hasShorts ? "include i proventi degli short" : `${formatPercent((summary.cash / Math.max(summary.total_value, 1)) * 100)} del totale`}
          />
          <SummaryStat
            label={hasShorts ? "Esposizione long" : "Investito"}
            value={formatCurrency(longExposure, baseCurrency)}
            hint={`${longPositions.length} ${longPositions.length === 1 ? "titolo" : "titoli"}`}
          />
          {hasShorts && (
            <SummaryStat
              label="Esposizione short"
              value={formatCurrency(shortExposure, baseCurrency)}
              hint={`${shortPositions.length} short · da ricoprire`}
              tone="warn"
            />
          )}
        </div>
      </Panel>

      <Tabs
        active={tab}
        onChange={(id) => setTab(id as TabId)}
        tabs={[
          { id: "positions", label: "Posizioni", badge: summary.positions.length },
          { id: "allocation", label: "Allocazione" },
          { id: "trend", label: "Andamento" },
          {
            id: "risk",
            label: "Rischio",
            badge: summary.risk_warnings.length || undefined,
          },
        ]}
      />

      {tab === "positions" && (
        <Panel
          title="Posizioni"
          eyebrow="Clicca una posizione per aprirne la scheda completa"
        >
          {summary.positions.length === 0 ? (
            <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 p-5">
              <h2 className="font-semibold text-amber-100">Nessuna posizione aperta</h2>
              <p className="mt-2 text-sm text-slate-300">
                Compra un titolo dalla Watchlist o dall'Analisi, oppure usa il pianificatore di allocazione.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {summary.positions.map((position) => {
                const recommendation = recommendationBySymbol.get(position.symbol);
                const reco = recommendation?.final_recommendation ?? position.recommendation ?? "HOLD";
                const isShort = position.quantity < 0;
                return (
                  <article
                    key={position.symbol}
                    role="button"
                    tabIndex={0}
                    onClick={() => openAsset(position.symbol)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        openAsset(position.symbol);
                      }
                    }}
                    className="group cursor-pointer rounded-2xl border border-slate-800/60 bg-slate-950/55 p-4 shadow-panel transition hover:border-cyan-300/40 hover:bg-slate-900/55 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/50"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="truncate text-base font-semibold text-white">
                            {position.name ?? position.symbol}
                          </p>
                          {isShort && (
                            <span className="shrink-0 rounded-md border border-amber-300/40 bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-200">
                              Short
                            </span>
                          )}
                          {position.technical_signal ? <SignalBadge signal={position.technical_signal} size="sm" /> : null}
                        </div>
                        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
                          <span className="font-mono text-slate-400">{position.symbol}</span>
                          {position.isin ? <span className="font-mono text-slate-600">· {position.isin}</span> : null}
                          <span>· {assetTypeLabels[position.asset_type] ?? position.asset_type}</span>
                          <span>· {Math.abs(position.quantity).toLocaleString("it-IT", { maximumFractionDigits: 6 })} quote{isShort ? " (short)" : ""}</span>
                          <span>· peso {Math.abs(position.weight_percent).toFixed(0)}%</span>
                        </p>
                      </div>
                      <span className={`inline-flex shrink-0 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${recommendationTone(reco)}`}>
                        {reco}
                      </span>
                    </div>

                    <div className="mt-3 grid grid-cols-3 gap-2">
                      <div className="rounded-lg border border-slate-800/70 bg-slate-900/50 p-2.5">
                        <p className="eyebrow-muted">Valore</p>
                        <p className="num mt-1 text-sm font-semibold text-white">{formatCurrency(position.current_value, position.currency)}</p>
                      </div>
                      <div className="rounded-lg border border-slate-800/70 bg-slate-900/50 p-2.5">
                        <p className="eyebrow-muted">P/L</p>
                        <p className={`num mt-1 text-sm font-semibold ${pnlClass(position.unrealized_pnl)}`}>{formatCurrency(position.unrealized_pnl, position.currency)}</p>
                      </div>
                      <div className="rounded-lg border border-slate-800/70 bg-slate-900/50 p-2.5">
                        <p className="eyebrow-muted">P/L %</p>
                        <p className={`num mt-1 text-sm font-semibold ${pnlClass(position.unrealized_pnl_percent)}`}>{formatPercent(position.unrealized_pnl_percent)}</p>
                      </div>
                    </div>

                    <p className="mt-3 text-xs text-slate-500">
                      Medio {formatCurrency(position.average_price, position.currency)} → attuale {formatCurrency(position.current_price, position.currency)}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      Equivalente EUR {formatCurrency(position.current_value_base, position.base_currency)} · P/L EUR{" "}
                      <span className={pnlClass(position.unrealized_pnl_base)}>
                        {formatCurrency(position.unrealized_pnl_base, position.base_currency)}
                      </span>
                    </p>
                    {recommendation?.reason && <p className="mt-1 text-xs text-slate-500">{recommendation.reason}</p>}

                    <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-800/60 pt-3">
                      <div className="flex items-center gap-2">
                        {isShort ? (
                          <>
                            <TradeButton symbol={position.symbol} price={position.current_price} currency={position.currency} side="COVER" maxQuantity={Math.abs(position.quantity)} label="Ricopri" onDone={() => void loadPortfolio()} />
                            <TradeButton symbol={position.symbol} price={position.current_price} currency={position.currency} side="SHORT" label="Aumenta short" onDone={() => void loadPortfolio()} />
                          </>
                        ) : (
                          <>
                            <TradeButton symbol={position.symbol} price={position.current_price} currency={position.currency} assetType={position.asset_type} side="BUY" label="Compra ancora" onDone={() => void loadPortfolio()} />
                            <TradeButton symbol={position.symbol} price={position.current_price} currency={position.currency} side="SELL" maxQuantity={position.quantity} onDone={() => void loadPortfolio()} />
                          </>
                        )}
                      </div>
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-cyan-300/70 transition group-hover:text-cyan-200">
                        Apri scheda
                        <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                      </span>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </Panel>
      )}

      {tab === "allocation" && (
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-2">
            <Panel title="Allocation asset class">
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={allocationByType} layout="vertical" margin={{ left: 18, right: 12, top: 8, bottom: 8 }}>
                    <XAxis type="number" stroke="#64748B" axisLine={false} tickLine={false} unit="%" />
                    <YAxis dataKey="name" type="category" stroke="#94A3B8" axisLine={false} tickLine={false} width={82} />
                    <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [`${Number(value).toFixed(2)}%`, "Peso"]} />
                    <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                      {allocationByType.map((item) => (
                        <Cell key={item.name} fill={item.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel title="Allocation valuta">
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={allocationByCurrency} dataKey="value" nameKey="name" innerRadius={58} outerRadius={92} paddingAngle={3}>
                      {allocationByCurrency.map((item) => (
                        <Cell key={item.name} fill={item.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [`${Number(value).toFixed(2)}%`, "Peso"]} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          </div>
          <AllocationPlanner />
        </div>
      )}

      {tab === "trend" && (
        <Panel title="Andamento portafoglio">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={snapshots} margin={{ left: 0, right: 12, top: 8, bottom: 8 }}>
                <XAxis dataKey="snapshot_date" hide />
                <YAxis stroke="#64748B" axisLine={false} tickLine={false} width={78} />
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(value) => [formatCurrency(Number(value), baseCurrency), "Valore"]} />
                <Area type="monotone" dataKey="total_value" stroke="#22D3EE" fill="#22D3EE" fillOpacity={0.16} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      )}

      {tab === "risk" && (
        <Panel title="Warning di rischio">
          {summary.risk_warnings.length === 0 ? (
            <p className="flex items-center gap-2 text-sm text-emerald-300">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              Nessun warning attivo sui limiti configurati.
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {summary.risk_warnings.map((warning) => (
                <div key={`${warning.code}-${warning.symbol ?? "portfolio"}`} className="rounded-lg border border-amber-300/20 bg-amber-400/10 p-4">
                  <p className="text-sm font-semibold text-amber-100">{warning.code}</p>
                  <p className="mt-2 text-sm text-slate-300">{warning.message}</p>
                  {warning.symbol && (
                    <button
                      onClick={() => openAsset(warning.symbol as string)}
                      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-cyan-300 hover:text-cyan-200"
                    >
                      Apri {warning.symbol}
                      <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

function SummaryStat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "pos" | "neg" | "warn";
}) {
  const hintClass =
    tone === "pos" ? "text-emerald-300" : tone === "neg" ? "text-rose-300" : tone === "warn" ? "text-amber-300" : "text-slate-500";
  return (
    <div className="px-5 py-4">
      <p className="eyebrow-muted">{label}</p>
      <p className="num mt-1 text-xl font-semibold text-white">{value}</p>
      {hint && <p className={`mt-0.5 text-xs ${hintClass}`}>{hint}</p>}
    </div>
  );
}
