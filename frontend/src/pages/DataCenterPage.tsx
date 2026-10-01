import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Database, DatabaseBackup, HardDriveDownload, KeyRound, RefreshCw, Server, ShieldCheck } from "lucide-react";

import { MetricCard } from "../components/MetricCard";
import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  ApiError,
  apiGet,
  apiPost,
  apiReasonCode,
  formatRateToEur,
  getDataCoverage,
  refreshAll,
  type Asset,
  type AvailabilityReason,
  type AvailabilityState,
  type Backup,
  type BudgetWindow,
  type CoverageCount,
  type DataCoverage,
  type DataProviderStatus,
  type DataRefreshResult,
  type DataStatus,
  type FxCoverageStatus,
  type FxRateDirection,
  type QualityTier,
  type RequestOutcome,
} from "../lib/api";

/** Batch prioritario a limite fisso: nessun refresh bulk indiscriminato. */
const PRIORITY_BATCH_LIMIT = 10;

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function modeTone(mode: string) {
  if (mode === "REAL") {
    return "text-emerald-300";
  }
  if (mode === "MIXED") {
    return "text-cyan-300";
  }
  return "text-amber-300";
}

function sourceBadge(source: string | null, isReal: boolean) {
  if (isReal) {
    return "border-emerald-300/20 bg-emerald-400/10 text-emerald-200";
  }
  if (source === "seed") {
    return "border-amber-300/20 bg-amber-400/10 text-amber-200";
  }
  return "border-slate-700 bg-slate-900 text-slate-300";
}

export function DataCenterPage() {
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshingSymbol, setRefreshingSymbol] = useState<string | null>(null);
  const [runningBatch, setRunningBatch] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [backingUp, setBackingUp] = useState(false);
  const [coverage, setCoverage] = useState<DataCoverage | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [coverageError, setCoverageError] = useState<string | null>(null);

  async function loadBackups() {
    try {
      setBackups(await apiGet<Backup[]>("/backups"));
    } catch {
      // best-effort
    }
  }

  async function createBackupNow() {
    setBackingUp(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiPost<Backup>("/backups/create");
      setMessage(result.created ? `Backup creato: ${result.file}` : "Backup non creato (database vuoto).");
      await loadBackups();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backup non riuscito.");
    } finally {
      setBackingUp(false);
    }
  }

  async function loadCoverage() {
    setCoverageLoading(true);
    setCoverageError(null);
    try {
      setCoverage(await getDataCoverage());
    } catch (err) {
      setCoverage(null);
      setCoverageError(coverageErrorMessage(err));
    } finally {
      setCoverageLoading(false);
    }
  }

  async function loadDataCenter() {
    setLoading(true);
    setError(null);
    // La copertura ha stato ed errori propri: un suo fallimento non nasconde lo status legacy.
    const coverageRequest = loadCoverage();
    try {
      const [statusResponse, assetResponse] = await Promise.all([
        apiGet<DataStatus>("/data/status"),
        apiGet<Asset[]>("/assets"),
      ]);
      setStatus(statusResponse);
      setAssets(assetResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento del Data Center.");
    } finally {
      setLoading(false);
    }
    await coverageRequest;
  }

  async function refreshSymbol(symbol: string) {
    setRefreshingSymbol(symbol);
    setMessage(null);
    setError(null);
    try {
      const result = await apiPost<DataRefreshResult>(`/data/refresh/${symbol}`);
      setMessage(`${result.symbol}: ${result.message}`);
      await loadDataCenter();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh non riuscito.");
    } finally {
      setRefreshingSymbol(null);
    }
  }

  async function runPriorityBatch() {
    setRunningBatch(true);
    setMessage(null);
    setError(null);
    try {
      const result = await refreshAll(PRIORITY_BATCH_LIMIT);
      const s = result.summary;
      setMessage(
        `Batch prioritario completato: ${s.requested ?? 0} unità eseguite, ${s.updated ?? 0} senza fallback, ${s.fallback ?? 0} con fallback, ${s.rows_inserted ?? 0} righe nuove, ${s.rows_updated ?? 0} aggiornate.`,
      );
      await loadDataCenter();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Batch prioritario non riuscito.");
    } finally {
      setRunningBatch(false);
    }
  }

  useEffect(() => {
    void loadDataCenter();
    void loadBackups();
  }, []);

  const apiUsage = useMemo(() => status?.api_usage ?? [], [status]);
  const missingKeys = status?.provider_status.filter((item) => !item.api_key_configured).length ?? 0;

  if (loading) {
    return (
      <Panel title="Data Center">
        <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Data layer / control"
        index="08"
        title="Data Center"
        subtitle="Stato dei provider, uso API, cache e refresh manuale. Le chiamate esterne partono solo da qui, mai automaticamente."
        meta={
          status
            ? (
              <>
                <span>
                  Modo <span className="text-cyan-300/80">{status.data_mode}</span>
                </span>
                <span>
                  Real data <span className="text-cyan-300/80">{status.enable_real_data ? "ON" : "OFF"}</span>
                </span>
                <span>
                  Asset <span className="text-cyan-300/80">{assets.length}</span>
                </span>
              </>
            )
            : undefined
        }
        actions={
          <>
            <PageHeaderAction
              onClick={() => void loadDataCenter()}
              icon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
            >
              Aggiorna stato
            </PageHeaderAction>
            <PageHeaderAction
              variant="primary"
              onClick={() => void runPriorityBatch()}
              disabled={runningBatch || assets.length === 0}
              icon={<RefreshCw className={`h-4 w-4 ${runningBatch ? "animate-spin" : ""}`} aria-hidden="true" />}
            >
              {runningBatch ? "Batch prioritario in corso..." : `Esegui batch prioritario (${PRIORITY_BATCH_LIMIT})`}
            </PageHeaderAction>
          </>
        }
      />

      {error && (
        <Panel title="Errore">
          <p className="text-sm text-rose-300">{error}</p>
        </Panel>
      )}

      {message && (
        <div className="rounded-lg border border-cyan-300/20 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">
          {message}
        </div>
      )}

      <Panel
        eyebrow="Archivio sicuro"
        title="Backup del database"
        action={
          <PageHeaderAction
            onClick={() => void createBackupNow()}
            disabled={backingUp}
            icon={<HardDriveDownload className={`h-4 w-4 ${backingUp ? "animate-pulse" : ""}`} aria-hidden="true" />}
          >
            {backingUp ? "Backup..." : "Backup ora"}
          </PageHeaderAction>
        }
      >
        <p className="text-sm text-slate-400">
          Una copia di sicurezza del tuo portafoglio e di tutti i dati viene salvata <b>automaticamente a ogni avvio</b> dell'app
          in <code className="text-slate-300">data/backups/</code>. Vengono conservate le ultime 10 copie. Puoi crearne una anche ora.
        </p>

        <div className="mt-4 space-y-2">
          {backups.length === 0 ? (
            <p className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-sm text-slate-500">
              Nessun backup ancora. Riavvia l'app o premi "Backup ora".
            </p>
          ) : (
            backups.map((backup) => (
              <div
                key={backup.file ?? Math.random()}
                className="flex items-center justify-between rounded-lg border border-slate-800/70 bg-slate-950/55 px-3 py-2.5"
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <DatabaseBackup className="h-4 w-4 shrink-0 text-cyan-300" aria-hidden="true" />
                  <span className="truncate font-mono text-xs text-slate-200">{backup.file}</span>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-xs text-slate-500">
                  <span>{backup.created_at?.replace("T", " ") ?? "—"}</span>
                  <span className="num">{formatSize(backup.size_bytes)}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </Panel>

      {status && !status.enable_real_data && (
        <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          Dati reali disattivati. Stai usando dati seed/demo.
        </div>
      )}

      {status && status.enable_real_data && missingKeys > 0 && (
        <div className="rounded-lg border border-rose-300/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          API key non configurata per {missingKeys} provider.
        </div>
      )}

      {status && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Modalita dati" value={status.data_mode} delta={status.enable_real_data ? "Real data abilitati" : "Seed/demo attivo"} tone={status.data_mode === "SEED" ? "amber" : "green"} icon={Database} />
            <MetricCard label="Ultimo update" value={status.global_last_update ?? "N/D"} delta="Dal database locale" tone="cyan" icon={Server} />
            <MetricCard label="Cache valida" value={`${status.cache_stats.valid ?? 0}`} delta={`${status.cache_stats.entries ?? 0} entry totali`} tone="green" icon={ShieldCheck} />
            <MetricCard label="Provider senza key" value={`${missingKeys}`} delta="Nessuna chiave esposta al frontend" tone={missingKeys > 0 ? "rose" : "green"} icon={KeyRound} />
          </div>

          <Panel title="Provider">
            <div className="grid gap-3 xl:grid-cols-3">
              {status.provider_status.map((provider) => (
                <article
                  key={provider.provider}
                  aria-label={`Provider ${provider.provider}`}
                  className="rounded-lg border border-slate-800 bg-slate-900/60 p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-semibold text-white">{provider.provider}</p>
                    <span className={provider.enabled && provider.api_key_configured ? "text-xs font-semibold text-emerald-300" : "text-xs font-semibold text-amber-300"}>
                      {provider.enabled && provider.api_key_configured ? "READY" : "FALLBACK"}
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <p className="text-slate-500">Chiamate oggi</p>
                      <p className="mt-1 font-semibold text-white">
                        {provider.calls_today}/{provider.daily_limit}
                      </p>
                    </div>
                    <div>
                      <p className="text-slate-500">API key</p>
                      <p className={provider.api_key_configured ? "mt-1 font-semibold text-emerald-300" : "mt-1 font-semibold text-rose-300"}>
                        {provider.api_key_configured ? "Configurata" : "Mancante"}
                      </p>
                    </div>
                  </div>
                  <p className="mt-4 text-xs text-slate-500">{provider.supports.join(", ")}</p>
                  <ProviderGovernance provider={provider} />
                </article>
              ))}
            </div>
          </Panel>

          <Panel title="Uso API">
            <div className="grid gap-3 md:grid-cols-3">
              {apiUsage.map((usage) => (
                <div key={usage.provider} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <p className="font-semibold text-white">{usage.provider}</p>
                  <p className="mt-2 text-sm text-slate-400">{usage.usage_date}</p>
                  <div className="mt-4 h-2 rounded-full bg-slate-800">
                    <div
                      className="h-2 rounded-full bg-cyan-300"
                      style={{ width: `${Math.min(100, (usage.calls_count / Math.max(1, usage.daily_limit)) * 100)}%` }}
                    />
                  </div>
                  <p className="mt-2 text-right text-xs text-slate-500">
                    {usage.calls_count}/{usage.daily_limit}
                  </p>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}

      <CoverageSections coverage={coverage} loading={coverageLoading} error={coverageError} />

      <Panel title="Asset data status">
        {assets.length === 0 ? (
          <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 p-5">
            <h2 className="font-semibold text-amber-100">Database non inizializzato</h2>
            <p className="mt-2 text-sm text-slate-300">Esegui `backend\.venv\Scripts\python.exe scripts\seed_database.py --reset` e ricarica la pagina.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1040px] border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="px-3 pb-3 pl-0 font-medium">Asset</th>
                  <th className="px-3 pb-3 font-medium">Source</th>
                  <th className="px-3 pb-3 font-medium">Provider</th>
                  <th className="px-3 pb-3 font-medium">Ultima data prezzo</th>
                  <th className="px-3 pb-3 font-medium">Last fetch</th>
                  <th className="px-3 pb-3 text-right font-medium">Azione</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {assets.map((asset) => (
                  <tr key={asset.symbol} className="text-sm">
                    <td className="px-3 py-4 pl-0">
                      <p className="font-semibold text-white">{asset.symbol}</p>
                      <p className="mt-1 text-slate-500">{asset.name}</p>
                    </td>
                    <td className="px-3 py-4">
                      <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${sourceBadge(asset.last_source, asset.is_real_data)}`}>
                        {asset.is_real_data ? "real" : asset.last_source ?? "N/D"}
                      </span>
                    </td>
                    <td className="px-3 py-4 text-slate-300">{asset.provider ?? "Locale"}</td>
                    <td className="px-3 py-4 text-slate-300">{asset.last_price_date ?? "N/D"}</td>
                    <td className="px-3 py-4 text-slate-400">{asset.last_fetch_at ?? "N/D"}</td>
                    <td className="px-3 py-4 pr-0 text-right">
                      <button
                        onClick={() => void refreshSymbol(asset.symbol)}
                        disabled={refreshingSymbol === asset.symbol}
                        className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-3 py-2 text-xs font-semibold text-cyan-100 transition hover:bg-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <RefreshCw className={`h-3.5 w-3.5 ${refreshingSymbol === asset.symbol ? "animate-spin" : ""}`} aria-hidden="true" />
                        Refresh
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {status && (
        <p className={`text-xs ${modeTone(status.data_mode)}`}>
          Cache e provider sono usati solo su refresh manuale. Dashboard e watchlist non avviano chiamate esterne.
        </p>
      )}
    </div>
  );
}

// --- Copertura, qualità e budget ---------------------------------------------
// Percentuali e denominatori arrivano calcolati dal backend: qui si formattano soltanto.

const tierOrder: QualityTier[] = ["QUALIFIED", "OBSERVABLE", "REFERENCE_ONLY"];
const tierLabels: Record<QualityTier, string> = {
  QUALIFIED: "Qualified",
  OBSERVABLE: "Observable",
  REFERENCE_ONLY: "Reference only",
};
const tradeRepublicOrder = ["UNRESOLVED_IDENTITY", "NEVER_SEEN", "CATALOGED", "VERIFIED", "UNAVAILABLE"];
const tradeRepublicLabels: Record<string, string> = {
  UNRESOLVED_IDENTITY: "Identità non risolta",
  NEVER_SEEN: "Mai visto",
  CATALOGED: "Nel catalogo",
  VERIFIED: "Verificato",
  UNAVAILABLE: "Non disponibile",
};
const qualityOrder = ["realtime", "delayed", "eod", "reference", "stale"];
const qualityLabels: Record<string, string> = {
  realtime: "Tempo reale",
  delayed: "Ritardato",
  eod: "Fine giornata",
  reference: "Riferimento",
  stale: "Dato non aggiornato",
};
const delayBucketOrder = ["0-5m", "5-30m", "30m-24h", "1-4d", ">4d"];
const windowLabels: Record<BudgetWindow, string> = { MINUTE: "Minuto", DAY: "Giorno", MONTH: "Mese" };
const availabilityStateLabels: Record<AvailabilityState, string> = {
  AVAILABLE: "Disponibile",
  DISABLED: "Disattivato",
  COOLDOWN: "In cooldown",
};
const availabilityReasonLabels: Record<AvailabilityReason, string> = {
  MISSING_CREDENTIAL: "Chiave API non configurata",
  SECRET_IN_QUERY_POLICY: "Bloccato: la chiave finirebbe nell'URL",
  BULK_ONLY_POLICY: "Bloccato: solo download massivo",
  NOT_PRIMARY_POLICY: "Non usato come fonte primaria",
  OPT_IN_DISABLED: "Disattivato finché non viene abilitato (opt-in)",
  RATE_LIMITED: "Limite di richieste raggiunto",
  BUDGET_EXHAUSTED: "Budget esaurito",
  UNSUPPORTED_CAPABILITY: "Capability non supportata",
};
const outcomeLabels: Record<RequestOutcome, string> = {
  SUCCEEDED: "Riuscita",
  CACHE_HIT: "Servita dalla cache",
  RATE_LIMITED: "Limitata (429)",
  TIMED_OUT: "Timeout",
  RETRY_EXHAUSTED: "Tentativi esauriti",
  REJECTED: "Rifiutata",
  DISABLED: "Provider disattivato",
};
const fxStatusStyles: Record<FxCoverageStatus, { label: string; className: string }> = {
  FRESH: { label: "Fresco", className: "text-emerald-300" },
  STALE: { label: "Non aggiornato", className: "text-amber-300" },
  MISSING: { label: "Mancante", className: "text-rose-300" },
};
const fxDirectionLabels: Record<FxRateDirection, string> = { DIRECT: "Diretto", INVERSE: "Inverso" };
const percentFormatter = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 2 });

function formatPercentValue(value: number): string {
  return `${percentFormatter.format(value)}%`;
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} g`;
}

/** Chiavi note nell'ordine dichiarato, poi eventuali chiavi nuove in ordine alfabetico. */
function orderedEntries(counts: Record<string, number>, order: readonly string[]): Array<[string, number]> {
  const extra = Object.keys(counts)
    .filter((key) => !order.includes(key))
    .sort();
  return [...order, ...extra].filter((key) => key in counts).map((key) => [key, counts[key]]);
}

function coverageErrorMessage(error: unknown): string {
  const reason = apiReasonCode(error);
  if (reason === "COVERAGE_INVARIANT_FAILED") {
    return "Copertura non disponibile: le partizioni non sommano al proprio denominatore (COVERAGE_INVARIANT_FAILED).";
  }
  if (reason) return `Copertura non disponibile (${reason}).`;
  if (error instanceof ApiError) return `Copertura non disponibile (HTTP ${error.status}).`;
  // Nessun messaggio grezzo: in sviluppo conterrebbe l'indirizzo dell'API.
  return "Copertura non disponibile: backend non raggiungibile.";
}

function availabilityText(state: AvailabilityState | null, reason: AvailabilityReason | null): string {
  if (!state) return "Disponibilità non registrata";
  const stateLabel = availabilityStateLabels[state] ?? state;
  return reason ? `${stateLabel}: ${availabilityReasonLabels[reason] ?? reason} (${reason})` : stateLabel;
}

/** Orario nel fuso locale, con l'equivalente UTC nel tooltip; `—` se assente o non valido. */
function Timestamp({ value }: { value: string | null }) {
  const date = value ? new Date(value) : null;
  if (!value || !date || Number.isNaN(date.getTime())) {
    return <span className="text-slate-500">—</span>;
  }
  // Formatter creato a ogni render: segue il fuso corrente del browser.
  const local = new Intl.DateTimeFormat("it-IT", { dateStyle: "short", timeStyle: "medium" }).format(date);
  return (
    <time dateTime={value} title={`${date.toISOString().slice(0, 19).replace("T", " ")} UTC`}>
      {local}
    </time>
  );
}

function RateToEur({ value }: { value: string | null }) {
  const formatted = formatRateToEur(value);
  return <span title={formatted === "—" || value === null ? undefined : value}>{formatted}</span>;
}

function ProviderGovernance({ provider }: { provider: DataProviderStatus }) {
  return (
    <div className="mt-4 space-y-3 border-t border-slate-800 pt-4 text-xs">
      {provider.capabilities.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-slate-500">Capability</span>
          {provider.capabilities.map((capability) => (
            <span key={capability} className="rounded border border-slate-700 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">
              {capability}
            </span>
          ))}
        </div>
      )}
      <p className={provider.availability_state === "AVAILABLE" ? "text-emerald-300" : "text-amber-300"}>
        {availabilityText(provider.availability_state, provider.availability_reason)}
      </p>
      {provider.cooldown_until && (
        <p className="text-slate-400">
          Cooldown fino a <Timestamp value={provider.cooldown_until} />
        </p>
      )}
      {provider.budget_windows.length === 0 ? (
        <p className="text-slate-500">Nessuna finestra di budget registrata.</p>
      ) : (
        <table aria-label={`Budget ${provider.provider}`} className="w-full border-collapse">
          <thead>
            <tr className="text-left text-[10px] uppercase text-slate-500">
              <th className="pb-1 font-medium">Finestra</th>
              <th className="pb-1 font-medium">Usate / limite</th>
              <th className="pb-1 font-medium">Residue</th>
              <th className="pb-1 font-medium">Reset</th>
            </tr>
          </thead>
          <tbody>
            {provider.budget_windows.map((window) => (
              <tr key={window.window}>
                <th scope="row" className="py-1 pr-2 text-left font-normal text-slate-400">
                  {windowLabels[window.window] ?? window.window}
                </th>
                <td className="num py-1 pr-2 text-slate-200">{`${window.used} / ${window.limit ?? "senza limite"}`}</td>
                <td className="num py-1 pr-2 text-slate-200">{window.remaining ?? "—"}</td>
                <td className="py-1 text-slate-400">
                  <Timestamp value={window.reset_at} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-slate-400">
        Ultimo esito:{" "}
        {provider.last_outcome ? (
          <>
            <span className="font-semibold text-slate-200">{outcomeLabels[provider.last_outcome] ?? provider.last_outcome}</span>
            {" · "}
            <Timestamp value={provider.last_outcome_at} />
          </>
        ) : (
          <span>Nessun esito registrato</span>
        )}
      </p>
    </div>
  );
}

function CoverageGroup({ label, children, footer }: { label: string; children: ReactNode; footer?: string }) {
  return (
    <div role="group" aria-label={label} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="text-sm font-semibold text-white">{label}</h3>
      <dl className="mt-3 space-y-1.5 text-sm">{children}</dl>
      {footer && <p className="mt-3 text-xs text-cyan-200">{footer}</p>}
    </div>
  );
}

function Stat({ label, value, total = false }: { label: string; value: ReactNode; total?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${total ? "border-t border-slate-800 pt-1.5" : ""}`}>
      <dt className="text-slate-500">{label}</dt>
      <dd className="num font-semibold text-slate-100">{value}</dd>
    </div>
  );
}

function CountChips({
  counts,
  order,
  labels = {},
}: {
  counts: Record<string, number>;
  order: readonly string[];
  labels?: Record<string, string>;
}) {
  const entries = orderedEntries(counts, order).filter(([, count]) => count > 0);
  if (entries.length === 0) return <span className="text-slate-500">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([key, count]) => (
        <span key={key} className="rounded border border-slate-700 px-1.5 py-0.5 text-[11px] text-slate-300">
          {`${labels[key] ?? key} ${count}`}
        </span>
      ))}
    </span>
  );
}

function CoverageCountTable({ label, keyLabel, rows }: { label: string; keyLabel: string; rows: CoverageCount[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">{`${label}: nessun gruppo.`}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full min-w-[480px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
            <th className="pb-2 pr-3 font-medium">{keyLabel}</th>
            <th className="pb-2 pr-3 text-right font-medium">Totale</th>
            <th className="pb-2 pr-3 text-right font-medium">Risolti</th>
            <th className="pb-2 pr-3 text-right font-medium">Qualified</th>
            <th className="pb-2 pr-3 text-right font-medium">Observable</th>
            <th className="pb-2 text-right font-medium">Reference only</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/80">
          {rows.map((row) => (
            <tr key={row.key}>
              <th scope="row" className="py-2 pr-3 text-left font-mono text-xs font-normal text-slate-200">
                {row.key}
              </th>
              <td className="num py-2 pr-3 text-right text-slate-300">{row.total}</td>
              <td className="num py-2 pr-3 text-right text-slate-300">{row.resolved}</td>
              <td className="num py-2 pr-3 text-right text-slate-300">{row.qualified}</td>
              <td className="num py-2 pr-3 text-right text-slate-300">{row.observable}</td>
              <td className="num py-2 text-right text-slate-300">{row.reference_only}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CatalogCoveragePanel({ coverage }: { coverage: DataCoverage }) {
  return (
    <Panel eyebrow="Copertura misurata" title="Copertura catalogo">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
        <span>
          Misurata il <Timestamp value={coverage.measured_at} />
        </span>
        {coverage.latest_catalog_snapshot_id !== null ? (
          <>
            <span>Snapshot #{coverage.latest_catalog_snapshot_id}</span>
            <span>
              Acquisito il <Timestamp value={coverage.latest_catalog_retrieved_at} />
            </span>
            {coverage.latest_catalog_sha256 && (
              <span title={coverage.latest_catalog_sha256} className="font-mono">
                {`SHA-256 ${coverage.latest_catalog_sha256.slice(0, 8)}…`}
              </span>
            )}
          </>
        ) : (
          <span className="text-amber-200">Nessuno snapshot completo del catalogo: denominatori a zero.</span>
        )}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <CoverageGroup label="Parsing catalogo">
          <Stat label="Accettate" value={coverage.parse_accepted_entries} />
          <Stat label="Ambigue" value={coverage.parse_ambiguous_entries} />
          <Stat label="Rifiutate" value={coverage.parse_rejected_entries} />
          <Stat label="Denominatore" value={`${coverage.parse_denominator} entry`} total />
        </CoverageGroup>
        <CoverageGroup
          label="Risoluzione identità"
          footer={`${formatPercentValue(coverage.resolved_percent)} risolte su ${coverage.resolution_denominator}`}
        >
          <Stat label="Risolte" value={coverage.resolution_resolved_entries} />
          <Stat label="Ambigue" value={coverage.resolution_ambiguous_entries} />
          <Stat label="Non trovate" value={coverage.resolution_unmatched_entries} />
          <Stat label="Rifiutate" value={coverage.resolution_rejected_entries} />
          <Stat label="Non processate" value={coverage.resolution_unprocessed_entries} />
          <Stat label="Denominatore" value={`${coverage.resolution_denominator} entry accettate`} total />
        </CoverageGroup>
        <CoverageGroup label="Tier di qualità">
          {tierOrder.map((tier) => (
            <Stat
              key={tier}
              label={tierLabels[tier]}
              value={`${coverage.tier_counts[tier] ?? 0} · ${formatPercentValue(coverage.tier_percentages[tier] ?? 0)}`}
            />
          ))}
          <Stat label="Denominatore" value={`${coverage.tier_denominator} strumenti`} total />
        </CoverageGroup>
        <CoverageGroup
          label="Stato Trade Republic"
          footer={`${formatPercentValue(coverage.trade_republic_verified_percent)} verificati su ${coverage.trade_republic_denominator}`}
        >
          {orderedEntries(coverage.trade_republic_status_counts, tradeRepublicOrder).map(([key, count]) => (
            <Stat key={key} label={tradeRepublicLabels[key] ?? key} value={count} />
          ))}
          <Stat label="Denominatore" value={`${coverage.trade_republic_denominator} entry accettate`} total />
        </CoverageGroup>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <CoverageCountTable label="Copertura per classe" keyLabel="Classe" rows={coverage.by_asset_class} />
        <CoverageCountTable label="Copertura per mercato" keyLabel="MIC" rows={coverage.by_market} />
      </div>
      <p className="mt-4 text-xs text-slate-500">
        Ultimo snapshot completo del catalogo ufficiale. Gli strumenti senza listing risolto restano nel denominatore Trade
        Republic come “Identità non risolta”; lo stato Trade Republic indica la fonte della conferma, non la negoziabilità.
        Nessuna percentuale obiettivo è promessa.
      </p>
    </Panel>
  );
}

function ProviderCoveragePanel({ items }: { items: DataCoverage["provider_coverage"] }) {
  return (
    <Panel eyebrow="Provider e capability" title="Copertura, freschezza e ritardo per provider">
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">Nessuna coppia provider/capability misurabile.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table aria-label="Copertura provider" className="w-full min-w-[1180px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="pb-2 pr-3 font-medium">Provider</th>
                  <th className="pb-2 pr-3 text-right font-medium">Idonei</th>
                  <th className="pb-2 pr-3 text-right font-medium">Non mappati</th>
                  <th className="pb-2 pr-3 text-right font-medium">Mappati</th>
                  <th className="pb-2 pr-3 text-right font-medium">Freschi</th>
                  <th className="pb-2 pr-3 text-right font-medium">Non aggiornati</th>
                  <th className="pb-2 pr-3 text-right font-medium">Senza osservazione</th>
                  <th className="pb-2 pr-3 text-right font-medium">Rejection aperte</th>
                  <th className="pb-2 pr-3 font-medium">Qualità effettiva</th>
                  <th className="pb-2 pr-3 font-medium">Ritardo all'ingestione</th>
                  <th className="pb-2 pr-3 font-medium">Ultima osservazione</th>
                  <th className="pb-2 font-medium">Ultima ingestione</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {items.map((item) => (
                  <tr key={`${item.provider}:${item.capability}`} className="align-top">
                    <th scope="row" className="py-3 pr-3 text-left font-semibold text-white">
                      {`${item.provider} · ${item.capability}`}
                      {item.attribution && (
                        <span className="mt-1 block text-[11px] font-normal text-slate-400">{item.attribution}</span>
                      )}
                    </th>
                    <td className="num py-3 pr-3 text-right text-slate-200">{item.eligible_listings}</td>
                    <td className="num py-3 pr-3 text-right text-slate-300">{item.unmapped_listings}</td>
                    <td className="num py-3 pr-3 text-right text-slate-300">{item.mapped_listings}</td>
                    <td className="num py-3 pr-3 text-right text-emerald-300">{item.fresh_listings}</td>
                    <td className="num py-3 pr-3 text-right text-amber-300">{item.stale_listings}</td>
                    <td className="num py-3 pr-3 text-right text-slate-300">{item.missing_observation_listings}</td>
                    <td className="num py-3 pr-3 text-right text-rose-300">{item.rejected_observations}</td>
                    <td className="py-3 pr-3">
                      <CountChips counts={item.quality_counts} order={qualityOrder} labels={qualityLabels} />
                    </td>
                    <td className="py-3 pr-3">
                      <CountChips counts={item.delay_bucket_counts} order={delayBucketOrder} />
                    </td>
                    <td className="py-3 pr-3 text-slate-400">
                      <Timestamp value={item.latest_provider_observed_at} />
                    </td>
                    <td className="py-3 text-slate-400">
                      <Timestamp value={item.latest_ingested_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Idonei = listing risolti compatibili con la capability, divisi in non mappati e mappati; i mappati sono freschi, non
            aggiornati o senza osservazione secondo la policy al momento della misura. La qualità è quella effettiva: un dato non
            aggiornato non viene mai etichettato come tempo reale. Il ritardo è misurato all'ingestione dell'ultima revisione.
          </p>
        </>
      )}
    </Panel>
  );
}

function FxCoveragePanel({ coverage }: { coverage: DataCoverage }) {
  return (
    <Panel eyebrow="Cambi verso EUR" title="Copertura FX per valuta">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
        <CoverageGroup label="Copertura cambi">
          <Stat label="Freschi" value={coverage.fx_fresh_currencies} />
          <Stat label="Non aggiornati" value={coverage.fx_stale_currencies} />
          <Stat label="Mancanti" value={coverage.fx_missing_currencies} />
          <Stat label="Denominatore" value={`${coverage.fx_currency_denominator} valute non-EUR`} total />
        </CoverageGroup>
        {coverage.fx_coverage.length === 0 ? (
          <p className="text-sm text-slate-500">Nessuna valuta non-EUR da coprire.</p>
        ) : (
          <div className="overflow-x-auto">
            <table aria-label="Cambi verso EUR" className="w-full min-w-[820px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="pb-2 pr-3 font-medium">Coppia</th>
                  <th className="pb-2 pr-3 font-medium">Stato</th>
                  <th className="pb-2 pr-3 font-medium">Direzione</th>
                  <th className="pb-2 pr-3 text-right font-medium">Cambio verso EUR</th>
                  <th className="pb-2 pr-3 font-medium">Provider</th>
                  <th className="pb-2 pr-3 font-medium">Osservato</th>
                  <th className="pb-2 pr-3 font-medium">Ingerito</th>
                  <th className="pb-2 text-right font-medium">Età</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {coverage.fx_coverage.map((item) => (
                  <tr key={item.from_currency}>
                    <th scope="row" className="py-2 pr-3 text-left font-mono text-xs font-normal text-slate-200">
                      {`${item.from_currency}/${item.to_currency}`}
                    </th>
                    <td className={`py-2 pr-3 font-semibold ${fxStatusStyles[item.status].className}`}>
                      {fxStatusStyles[item.status].label}
                    </td>
                    <td className="py-2 pr-3 text-slate-300">{item.direction ? fxDirectionLabels[item.direction] : "—"}</td>
                    <td className="num py-2 pr-3 text-right text-slate-200">
                      <RateToEur value={item.rate_to_eur} />
                    </td>
                    <td className="py-2 pr-3 text-slate-300">{item.provider ?? "—"}</td>
                    <td className="py-2 pr-3 text-slate-400">
                      <Timestamp value={item.observed_at} />
                    </td>
                    <td className="py-2 pr-3 text-slate-400">
                      <Timestamp value={item.ingested_at} />
                    </td>
                    <td className="num py-2 text-right text-slate-400">{formatAge(item.age_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Fonte: cambi registrati in locale (BCE), separati dai listing provider; “Inverso” indica un cambio EUR/valuta letto al
        reciproco. EUR è l'identità e resta fuori dal denominatore. I cambi congelati di posizioni e ordini non vengono
        modificati.
      </p>
    </Panel>
  );
}

function splitRejectionReason(key: string): [string, string] {
  const separator = key.indexOf(":");
  if (separator < 0) return ["Altro", key];
  const prefix = key.slice(0, separator);
  const phase = prefix === "PARSE" ? "Parser" : prefix === "RESOLUTION" ? "Risoluzione" : prefix;
  return [phase, key.slice(separator + 1)];
}

function RejectionsAndQueuePanel({ coverage }: { coverage: DataCoverage }) {
  const reasons = Object.entries(coverage.rejection_reasons).sort(
    ([leftKey, left], [rightKey, right]) => right - left || leftKey.localeCompare(rightKey),
  );
  return (
    <Panel eyebrow="Scarti e coda" title="Rejection e coda refresh">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,16rem)]">
        {reasons.length === 0 ? (
          <p className="text-sm text-slate-500">Nessuna rejection registrata.</p>
        ) : (
          <div className="overflow-x-auto">
            <table aria-label="Motivi di rejection" className="w-full min-w-[420px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="pb-2 pr-3 font-medium">Fase</th>
                  <th className="pb-2 pr-3 font-medium">Codice</th>
                  <th className="pb-2 text-right font-medium">Entry</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {reasons.map(([key, count]) => {
                  const [phase, code] = splitRejectionReason(key);
                  return (
                    <tr key={key}>
                      <td className="py-2 pr-3 text-slate-400">{phase}</td>
                      <td className="py-2 pr-3 font-mono text-xs text-slate-200">{code}</td>
                      <td className="num py-2 text-right text-slate-200">{count}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <CoverageGroup label="Coda refresh">
          <Stat label="In attesa" value={coverage.pending_refresh} />
          <Stat label="Rinviate per budget" value={coverage.budget_deferred} />
        </CoverageGroup>
      </div>
    </Panel>
  );
}

function CoverageSections({
  coverage,
  loading,
  error,
}: {
  coverage: DataCoverage | null;
  loading: boolean;
  error: string | null;
}) {
  if (!coverage) {
    return (
      <Panel eyebrow="Copertura misurata" title="Copertura catalogo">
        {loading ? (
          <p role="status" className="text-sm text-slate-400">
            Caricamento copertura dati…
          </p>
        ) : error ? (
          <p role="alert" className="text-sm text-rose-300">
            {error}
          </p>
        ) : (
          <p className="text-sm text-slate-500">Copertura non ancora misurata.</p>
        )}
      </Panel>
    );
  }
  return (
    <>
      <CatalogCoveragePanel coverage={coverage} />
      <ProviderCoveragePanel items={coverage.provider_coverage} />
      <FxCoveragePanel coverage={coverage} />
      <RejectionsAndQueuePanel coverage={coverage} />
    </>
  );
}
