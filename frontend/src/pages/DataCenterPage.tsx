import { useEffect, useMemo, useState } from "react";
import { Database, DatabaseBackup, HardDriveDownload, KeyRound, RefreshCw, Server, ShieldCheck } from "lucide-react";

import { MetricCard } from "../components/MetricCard";
import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
  type Asset,
  type Backup,
  type DataRefreshAllResult,
  type DataRefreshResult,
  type DataStatus,
} from "../lib/api";

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
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [backingUp, setBackingUp] = useState(false);

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

  async function loadDataCenter() {
    setLoading(true);
    setError(null);
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

  async function refreshAllPrices() {
    setRefreshingAll(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiPost<DataRefreshAllResult>("/data/refresh-all");
      const s = result.summary;
      setMessage(
        `Aggiornamento completato: ${s.updated}/${s.requested} reali, ${s.fallback} fallback, ${s.rows_inserted} righe nuove, ${s.rows_updated} aggiornate.`,
      );
      await loadDataCenter();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh batch non riuscito.");
    } finally {
      setRefreshingAll(false);
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
              onClick={() => void refreshAllPrices()}
              disabled={refreshingAll || assets.length === 0}
              icon={<RefreshCw className={`h-4 w-4 ${refreshingAll ? "animate-spin" : ""}`} aria-hidden="true" />}
            >
              {refreshingAll ? "Aggiornamento..." : "Aggiorna tutti i dati"}
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
                <article key={provider.provider} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
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
