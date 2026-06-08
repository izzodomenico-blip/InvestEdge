import { useEffect, useMemo, useState } from "react";
import { ExternalLink, Filter, Newspaper, RefreshCw, Search } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
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
