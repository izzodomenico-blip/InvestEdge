import { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Filter, Newspaper, RefreshCw, Search } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { IntradayArchiveSelect, IntradayField, utcInput } from '../components/IntradayDataStatus';
import {
  apiGet,
  apiPost,
  formatIntradayNs,
  intradayDateNs,
  intradayErrorMessage,
  intradayNamespace,
  type IntradayArchive,
  type IntradayNewsPage,
  type IntradayStatus,
  type Asset,
  type NewsItem,
  type NewsRefreshAllResult,
  type NewsRefreshResult,
  type NewsStatus,
} from "../lib/api";

const sentimentTone: Record<string, string> = {
  POSITIVE: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
  NEUTRAL: "border-cyan-300/30 bg-cyan-400/10 text-cyan-200",
  NEGATIVE: "border-rose-300/30 bg-rose-400/10 text-rose-200",
};

const intradayInput = 'w-full min-w-0 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300';
const intradayButton = 'rounded-md border border-slate-700 px-3 py-2 text-sm text-cyan-100 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50';
function publicNewsUrl(value: string | null | undefined): string | null {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}

function IntradayNewsSection() {
  const [initialTime] = useState(() => Date.now());
  const [profiles, setProfiles] = useState<IntradayStatus['profiles']>([]);
  const [profile, setProfile] = useState('');
  const [archive, setArchive] = useState<IntradayArchive>('REAL');
  const [listing, setListing] = useState('');
  const [cutoff, setCutoff] = useState(() => utcInput(initialTime));
  const [start, setStart] = useState(() => utcInput(initialTime - 86400000));
  const [end, setEnd] = useState(() => utcInput(initialTime));
  const [revisions, setRevisions] = useState(false);
  const [page, setPage] = useState<IntradayNewsPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [profileLoading, setProfileLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const active = useRef<AbortController | null>(null);
  const scope = useRef('');
  scope.current = JSON.stringify([profile, archive, listing, cutoff, start, end, revisions]);
  useEffect(() => {
    const controller = new AbortController(); setProfileLoading(true); setProfileError(null);
    void apiGet<IntradayStatus>('/intraday/status', { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      setProfiles(value.profiles); setProfile(previous => value.profiles.some(row => row.profile_id === previous) ? previous : value.profiles[0]?.profile_id ?? '');
    }).catch(reason => { if (!controller.signal.aborted) setProfileError(intradayErrorMessage(reason)); })
      .finally(() => { if (!controller.signal.aborted) setProfileLoading(false); });
    return () => controller.abort();
  }, [reload]);
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => { invalidate(); }, [profile]);
  function invalidate() { active.current?.abort(); setPage(null); setLoading(false); setError(null); }
  async function read(offset = 0) {
    if (profileLoading) return;
    const requestedScope = scope.current;
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    setPage(null); setLoading(true); setError(null);
    try {
      if (!/^[a-f0-9]{64}$/.test(profile)) throw new Error('Profilo non valido.');
      const namespace = intradayNamespace(archive, profile);
      const start_at_ns = intradayDateNs(start), end_at_ns = intradayDateNs(end), cutoff_ns = intradayDateNs(cutoff);
      if (BigInt(start_at_ns) > BigInt(end_at_ns) || BigInt(end_at_ns) > BigInt(cutoff_ns) || BigInt(end_at_ns) - BigInt(start_at_ns) > 366n * 86400n * 1000000000n) throw new Error('Periodo non valido.');
      if (listing && (!/^[1-9]\d*$/.test(listing) || !Number.isSafeInteger(Number(listing)))) throw new Error('Listing non valido.');
      const params = new URLSearchParams({ ...namespace, cutoff_ns, start_at_ns, end_at_ns, revisions: String(revisions), offset: String(offset), limit: '50', ...(listing ? { listing_id: listing } : {}) });
      const value = await apiGet<IntradayNewsPage>('/intraday/news?' + params, { signal: controller.signal });
      if (controller.signal.aborted || active.current !== controller || scope.current !== requestedScope) return;
      if (JSON.stringify(value.namespace) !== JSON.stringify([profile, namespace.data_mode, namespace.provenance, namespace.replay_grade])) throw new Error('Archivio non compatibile.');
      setPage(value);
    } catch (reason) { if (!controller.signal.aborted && active.current === controller) setError(intradayErrorMessage(reason)); }
    finally { if (!controller.signal.aborted && active.current === controller) setLoading(false); }
  }
  return <Panel title="News intraday versionate">
    <div className="min-w-0 space-y-4">
      <p className="text-sm text-slate-300">Archivio distinto dalle news daily. Articoli disponibili al cutoff; il periodo scelto verifica la copertura e non restringe l’elenco as-of. Le news non sono segnali validati.</p>
      {profileLoading && <p aria-live="polite" className="text-sm text-slate-300">Caricamento profili intraday…</p>}
      {profileError && <p role="alert" className="text-sm text-rose-200">{profileError}</p>}
      {!profileLoading && !profiles.length && !profileError && <p className="text-sm text-slate-300">Nessun profilo intraday. Configura metadata e calendario nel Data Center.</p>}
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <IntradayField label="Profilo news intraday"><select className={intradayInput} value={profile} onChange={event => { invalidate(); setProfile(event.target.value); }}><option value="">Seleziona profilo</option>{profiles.map(row => <option key={row.profile_id} value={row.profile_id}>{row.profile.feed} · {row.profile_id.slice(0, 12)}</option>)}</select></IntradayField>
        <IntradayArchiveSelect value={archive} label="Archivio news intraday" onChange={value => { invalidate(); setArchive(value); }} />
        <IntradayField label="Listing news (ID, facoltativo)"><input className={intradayInput} value={listing} onChange={event => { invalidate(); setListing(event.target.value); }} /></IntradayField>
        {([['Cutoff news UTC', cutoff, setCutoff], ['Copertura news da UTC', start, setStart], ['Copertura news a UTC', end, setEnd]] as const).map(([label, value, setter]) => <IntradayField key={label} label={label}><input type="datetime-local" step="0.001" className={intradayInput} value={value} onChange={event => { invalidate(); setter(event.target.value); }} /></IntradayField>)}
      </div>
      <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={revisions} onChange={event => { invalidate(); setRevisions(event.target.checked); }} />Mostra tutte le versioni note al cutoff</label>
      <p className="text-sm text-slate-300">Orari di ricerca UTC al millisecondo; timestamp delle versioni conservati al nanosecondo. {archive === 'REAL' ? 'REAL / CAPTURED / STRICT_PIT' : archive === 'RESEARCH' ? 'REAL / HISTORICAL_CURRENT / RESEARCH_ONLY' : 'DEMO / SYNTHETIC / RESEARCH_ONLY'}</p>
      <div className="flex flex-wrap gap-3"><button className={intradayButton} disabled={!profile || loading || profileLoading} onClick={() => void read()}>Consulta news intraday</button>
        <button className={intradayButton} onClick={() => { invalidate(); setProfileLoading(true); setReload(value => value + 1); }}>Rileggi profili intraday</button></div>
      {loading && <p role="status" className="text-sm text-slate-300">Caricamento news intraday…</p>}
      {error && <p role="alert" className="text-sm text-rose-200">{error}</p>}
      {page && <div className="min-w-0 space-y-4">
        <p className="break-words text-sm text-slate-300">Archivio consultato: {page.namespace.join(' / ')} · Cutoff {formatIntradayNs(page.cutoff_ns)}</p>
        <p className="text-sm text-amber-200">{page.coverage.state === 'MISSING' ? 'Copertura news mancante' : page.coverage.state === 'COVERED_ZERO' ? 'Periodo coperto: nessun articolo' : page.coverage.state === 'STALE' ? 'Copertura news obsoleta' : page.coverage.state === 'DISABLED' ? 'Copertura news disabilitata' : 'Copertura news presente'}</p>
        <p className="text-sm text-slate-300">Continuità attestata: {page.coverage.continuity_attested ? 'sì, nel periodo richiesto' : 'no'}{page.coverage.reason_code ? ' · ' + page.coverage.reason_code : ''}</p>
        {page.items.map(item => {
          const url = publicNewsUrl(item.payload.url);
          return <article key={String(item.id)} className="min-w-0 space-y-2 border-b border-slate-800 pb-4">
            <h3 className="break-words font-semibold text-white">{item.payload.headline}</h3>
            <p className="break-words text-sm text-slate-300">Fonte {item.payload.source ?? 'non dichiarata'}{item.payload.wire_source ? ' · ' + item.payload.wire_source : ''} · Articolo {item.article_id} · Versione {item.id}{item.payload.version ? ' / ' + item.payload.version : ''}</p>
            {item.supersedes_id != null && <p className="text-sm text-slate-300">Sostituisce versione {item.supersedes_id}</p>}
            <p className="break-words text-sm text-slate-300">Pubblicazione: {formatIntradayNs(item.payload.published_at_ns)}</p>
            <p className="break-words text-sm text-slate-300">Aggiornamento editoriale: {formatIntradayNs(item.payload.updated_at_ns)}</p>
            <p className="break-words text-sm text-cyan-100">Disponibile dal: {formatIntradayNs(item.available_at_ns)}</p>
            {item.payload.summary && <p className="break-words text-sm leading-6 text-slate-300">{item.payload.summary}</p>}
            {item.payload.content ? <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-300">{item.payload.content}</p> : <p className="text-sm text-slate-300">Testo escluso dall’archivio per diritti o contenuto non attestati ({item.payload.content_state ?? 'non dichiarati'}).</p>}
            {item.links.length ? <ul className="space-y-1 text-sm text-slate-300">{item.links.map((link, index) => <li key={index} className="break-words">{link.category} · {link.payload.target ?? (link.listing_id == null ? 'UNMAPPED' : 'LISTING')} · Listing {link.listing_id ?? 'non associato'} · Instrument {link.instrument_id ?? 'non associato'} · Regola {link.rule_version}{link.payload.reason_code ? ' · ' + link.payload.reason_code : ''}</li>)}</ul> : <p className="text-sm text-slate-300">Nessun mapping attestato per questa versione.</p>}
            {url && <a className="inline-block py-2 text-sm text-cyan-200 underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300" href={url} target="_blank" rel="noopener noreferrer">Apri fonte di {item.payload.headline}</a>}
          </article>;
        })}
        {!page.items.length && page.coverage.state !== 'COVERED_ZERO' && <p className="text-sm text-slate-300">Nessun articolo nella pagina as-of. Questo elenco vuoto non prova l’assenza di eventi.</p>}
        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300"><p>{page.items.length ? page.offset + 1 : 0}–{page.offset + page.items.length} di {page.total} versioni al cutoff</p>
          <button className={intradayButton} disabled={loading || page.next_offset == null} onClick={() => void read(page.next_offset ?? 0)}>Pagina successiva news intraday</button></div>
      </div>}
    </div>
  </Panel>;
}

const impactTone: Record<string, string> = {
  HIGH: "border-rose-300/30 bg-rose-400/10 text-rose-200",
  MEDIUM: "border-amber-300/30 bg-amber-400/10 text-amber-200",
  LOW: "border-slate-700 bg-slate-900 text-slate-300",
};

type FilterValue = "all" | "positive" | "negative" | "neutral" | "high";

function formatDate(value: string | null) {
  if (!value) {
    return "N/D";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("it-IT", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function scoreText(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "0.00";
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

export function NewsPage() {
  return <div className="space-y-6"><DailyNewsPage /><IntradayNewsSection /></div>;
}

function DailyNewsPage() {
  const [status, setStatus] = useState<NewsStatus | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterValue>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadNews(symbol = selectedSymbol) {
    const params = new URLSearchParams({ limit: "100" });
    if (symbol) {
      params.set("symbol", symbol);
    }
    setNews(await apiGet<NewsItem[]>(`/news?${params.toString()}`));
  }

  async function loadPage() {
    setLoading(true);
    setError(null);
    try {
      const [statusResponse, assetResponse] = await Promise.all([
        apiGet<NewsStatus>("/news/status"),
        apiGet<Asset[]>("/assets"),
      ]);
      const initialSymbol = selectedSymbol || assetResponse[0]?.symbol || "";
      setStatus(statusResponse);
      setAssets(assetResponse);
      setSelectedSymbol(initialSymbol);
      await loadNews(initialSymbol);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento delle news.");
      setNews([]);
    } finally {
      setLoading(false);
    }
  }

  async function refreshSelectedSymbol(force = false) {
    if (!selectedSymbol) {
      return;
    }
    setRefreshing(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiPost<NewsRefreshResult>(`/news/refresh/${selectedSymbol}?force=${force ? "true" : "false"}`);
      setMessage(`${result.symbol}: ${result.message}`);
      const [statusResponse] = await Promise.all([apiGet<NewsStatus>("/news/status"), loadNews(selectedSymbol)]);
      setStatus(statusResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh news non riuscito.");
    } finally {
      setRefreshing(false);
    }
  }

  async function refreshAllNews() {
    setRefreshingAll(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiPost<NewsRefreshAllResult>("/news/refresh-all");
      const s = result.summary;
      setMessage(
        `News aggiornate: ${s.updated}/${s.requested} reali, ${s.fallback} locali, ${s.items_inserted} nuove, ${s.items_updated} aggiornate.`,
      );
      const [statusResponse] = await Promise.all([apiGet<NewsStatus>("/news/status"), loadNews(selectedSymbol)]);
      setStatus(statusResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh news batch non riuscito.");
    } finally {
      setRefreshingAll(false);
    }
  }

  useEffect(() => {
    void loadPage();
  }, []);

  useEffect(() => {
    if (!loading) {
      void loadNews(selectedSymbol).catch((err) => {
        setError(err instanceof Error ? err.message : "Errore durante il caricamento delle news.");
        setNews([]);
      });
    }
  }, [selectedSymbol]);

  const realProvider = status?.provider_status.find((provider) => provider.provider === "alpha_vantage_news");
  const rateLimitReached = Boolean(
    status?.daily_usage.daily_limit &&
      status.daily_usage.daily_limit > 0 &&
      status.daily_usage.calls_count >= status.daily_usage.daily_limit,
  );

  const filteredNews = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return news.filter((item) => {
      if (filter === "positive" && item.sentiment_label !== "POSITIVE") {
        return false;
      }
      if (filter === "negative" && item.sentiment_label !== "NEGATIVE") {
        return false;
      }
      if (filter === "neutral" && item.sentiment_label !== "NEUTRAL") {
        return false;
      }
      if (filter === "high" && item.impact_level !== "HIGH") {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      return [item.title, item.summary, item.source, item.symbol]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery));
    });
  }, [filter, news, query]);

  if (loading) {
    return (
      <Panel title="News">
        <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="News e sentiment"
        index="06"
        title="News"
        subtitle="Notizie per asset con sentiment euristico keyword-based. Le news sono supporto decisionale, non previsione."
        meta={
          <>
            <span>
              Provider <span className="text-cyan-300/80">{status?.enable_real_news ? "REAL" : "MOCK"}</span>
            </span>
            <span>
              In coda <span className="text-cyan-300/80">{news.length}</span>
            </span>
          </>
        }
        actions={
          <>
            <PageHeaderAction
              onClick={() => void refreshSelectedSymbol(false)}
              disabled={!selectedSymbol || refreshing || refreshingAll}
              icon={<RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />}
            >
              Aggiorna asset
            </PageHeaderAction>
            <PageHeaderAction
              variant="primary"
              onClick={() => void refreshAllNews()}
              disabled={refreshingAll || assets.length === 0}
              icon={<RefreshCw className={`h-4 w-4 ${refreshingAll ? "animate-spin" : ""}`} aria-hidden="true" />}
            >
              {refreshingAll ? "Aggiornamento..." : "Aggiorna tutte"}
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

      {status && !status.enable_real_news && (
        <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          News reali disattivate. Stai usando news demo/locali.
        </div>
      )}

      {status?.enable_real_news && realProvider && !realProvider.api_key_configured && (
        <div className="rounded-lg border border-rose-300/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          Provider news non configurato.
        </div>
      )}

      {rateLimitReached && (
        <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          Limite news giornaliero raggiunto, uso news locali.
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
          <p className="text-xs uppercase text-slate-500">Real news</p>
          <p className={status?.enable_real_news ? "mt-2 text-2xl font-semibold text-emerald-300" : "mt-2 text-2xl font-semibold text-amber-300"}>
            {status?.enable_real_news ? "true" : "false"}
          </p>
        </article>
        <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
          <p className="text-xs uppercase text-slate-500">Provider news</p>
          <p className="mt-2 text-lg font-semibold text-white">
            {status?.provider_status.map((provider) => provider.provider).join(", ") ?? "N/D"}
          </p>
        </article>
        <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
          <p className="text-xs uppercase text-slate-500">Uso API news</p>
          <p className="mt-2 text-2xl font-semibold text-cyan-200">
            {status ? `${status.daily_usage.calls_count}/${status.daily_usage.daily_limit}` : "0/0"}
          </p>
        </article>
      </div>

      <Panel>
        <div className="grid gap-3 xl:grid-cols-[0.7fr_1fr_1fr]">
          <label className="block">
            <span className="mb-2 block text-xs uppercase text-slate-500">Symbol</span>
            <select
              value={selectedSymbol}
              onChange={(event) => setSelectedSymbol(event.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
            >
              {assets.map((asset) => (
                <option key={asset.symbol} value={asset.symbol}>
                  {asset.symbol} - {asset.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-2 block text-xs uppercase text-slate-500">Cerca</span>
            <span className="flex items-center gap-3 rounded-md border border-slate-700 bg-slate-900 px-3 py-2">
              <Search className="h-4 w-4 text-slate-500" aria-hidden="true" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
                placeholder="Titolo, fonte, sintesi"
              />
            </span>
          </label>

          <label className="block">
            <span className="mb-2 block text-xs uppercase text-slate-500">Filtro</span>
            <span className="flex items-center gap-3 rounded-md border border-slate-700 bg-slate-900 px-3 py-2">
              <Filter className="h-4 w-4 text-slate-500" aria-hidden="true" />
              <select
                value={filter}
                onChange={(event) => setFilter(event.target.value as FilterValue)}
                className="w-full bg-transparent text-sm text-white outline-none"
              >
                <option value="all">Tutte</option>
                <option value="positive">Positive</option>
                <option value="negative">Negative</option>
                <option value="neutral">Neutral</option>
                <option value="high">High impact</option>
              </select>
            </span>
          </label>
        </div>
      </Panel>

      <Panel title="Lista news">
        <div className="space-y-4">
          {filteredNews.map((item) => (
            <article key={`${item.id}-${item.title}`} className="rounded-lg border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="flex gap-3">
                  <span className="mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-700 bg-slate-950 text-slate-300">
                    <Newspaper className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <div>
                    <p className="text-xs uppercase text-slate-500">
                      {item.symbol ?? selectedSymbol} - {item.source ?? "N/D"} - {formatDate(item.published_at)}
                    </p>
                    <h2 className="mt-2 text-base font-semibold text-white">{item.title}</h2>
                    {item.summary && <p className="mt-3 text-sm leading-6 text-slate-400">{item.summary}</p>}
                    {item.url && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200 transition hover:text-cyan-100"
                      >
                        Apri link
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      </a>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap gap-2 xl:justify-end">
                  <span className={`inline-flex rounded-md border px-2.5 py-1 text-xs font-semibold ${sentimentTone[item.sentiment_label ?? "NEUTRAL"] ?? sentimentTone.NEUTRAL}`}>
                    {item.sentiment_label ?? "NEUTRAL"} {scoreText(item.sentiment_score)}
                  </span>
                  <span className={`inline-flex rounded-md border px-2.5 py-1 text-xs font-semibold ${impactTone[item.impact_level ?? "LOW"] ?? impactTone.LOW}`}>
                    {item.impact_level ?? "LOW"}
                  </span>
                  <span className="inline-flex rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs font-semibold text-slate-300">
                    Rel {item.relevance_score == null ? "N/D" : item.relevance_score.toFixed(0)}
                  </span>
                </div>
              </div>
            </article>
          ))}

          {filteredNews.length === 0 && (
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-5 text-sm text-slate-400">
              Nessuna news locale per il filtro corrente.
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}
