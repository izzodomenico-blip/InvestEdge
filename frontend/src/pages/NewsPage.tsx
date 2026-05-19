import { useEffect, useMemo, useState } from "react";
import { ExternalLink, Newspaper, RefreshCw, Search } from "lucide-react";

import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
  type Asset,
  type ImpactLevel,
  type NewsItem,
  type NewsRefreshResult,
  type NewsStatus,
  type SentimentLabel,
} from "../lib/api";

type Filter = "ALL" | SentimentLabel | "HIGH_IMPACT";

const sentimentTone: Record<SentimentLabel, string> = {
  POSITIVE: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
  NEGATIVE: "border-rose-300/30 bg-rose-400/10 text-rose-200",
  NEUTRAL: "border-slate-700 bg-slate-900 text-slate-200",
};

const impactTone: Record<ImpactLevel, string> = {
  HIGH: "border-amber-300/40 bg-amber-400/10 text-amber-200",
  MEDIUM: "border-cyan-300/30 bg-cyan-400/10 text-cyan-200",
  LOW: "border-slate-700 bg-slate-900 text-slate-300",
};

const filters: { value: Filter; label: string }[] = [
  { value: "ALL", label: "Tutte" },
  { value: "POSITIVE", label: "Positive" },
  { value: "NEGATIVE", label: "Negative" },
  { value: "NEUTRAL", label: "Neutral" },
  { value: "HIGH_IMPACT", label: "High impact" },
];

function formatDate(value: string | null) {
  if (!value) {
    return "N/D";
  }
  const trimmed = value.replace("T", " ").slice(0, 19);
  return trimmed;
}

export function NewsPage() {
  const [status, setStatus] = useState<NewsStatus | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [news, setNews] = useState<NewsItem[]>([]);
  const [filter, setFilter] = useState<Filter>("ALL");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function loadStatusAndAssets() {
    try {
      const [statusResponse, assetResponse] = await Promise.all([
        apiGet<NewsStatus>("/news/status"),
        apiGet<Asset[]>("/assets"),
      ]);
      setStatus(statusResponse);
      setAssets(assetResponse);
      if (!selectedSymbol && assetResponse[0]) {
        setSelectedSymbol(assetResponse[0].symbol);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento dello stato news.");
    }
  }

  async function loadNews(symbol: string | null) {
    setLoading(true);
    setError(null);
    try {
      const path = symbol ? `/news/${symbol}?limit=80` : "/news?limit=80";
      const items = await apiGet<NewsItem[]>(path);
      setNews(items);
    } catch (err) {
      setNews([]);
      setError(err instanceof Error ? err.message : "Errore durante il caricamento delle news.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshSelected() {
    if (!selectedSymbol) {
      return;
    }
    setRefreshing(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiPost<NewsRefreshResult>(`/news/refresh/${selectedSymbol}`);
      setMessage(`${result.symbol}: ${result.message}`);
      await Promise.all([loadStatusAndAssets(), loadNews(selectedSymbol)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh news non riuscito.");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadStatusAndAssets();
  }, []);

  useEffect(() => {
    void loadNews(selectedSymbol || null);
  }, [selectedSymbol]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return news.filter((item) => {
      if (filter === "HIGH_IMPACT" && item.impact_level !== "HIGH") {
        return false;
      }
      if (filter === "POSITIVE" && item.sentiment_label !== "POSITIVE") {
        return false;
      }
      if (filter === "NEGATIVE" && item.sentiment_label !== "NEGATIVE") {
        return false;
      }
      if (filter === "NEUTRAL" && item.sentiment_label !== "NEUTRAL") {
        return false;
      }
      if (!normalized) {
        return true;
      }
      return [item.title, item.summary, item.symbol, item.source]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized));
    });
  }, [news, filter, query]);

  const realDisabled = status && !status.enable_real_news;
  const realProvider = status?.provider_status.find((item) => item.provider !== "mock_news");
  const missingKey = realProvider && !realProvider.api_key_configured;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">News e sentiment</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">News</h1>
        </div>
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <select
            value={selectedSymbol}
            onChange={(event) => setSelectedSymbol(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
          >
            <option value="">Tutto il mercato</option>
            {assets.map((asset) => (
              <option key={asset.symbol} value={asset.symbol}>
                {asset.symbol} - {asset.name}
              </option>
            ))}
          </select>
          <button
            onClick={() => void refreshSelected()}
            disabled={refreshing || !selectedSymbol}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" />
            Aggiorna news
          </button>
        </div>
      </header>

      {realDisabled && (
        <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          News reali disattivate. Stai usando news demo/locali.
        </div>
      )}

      {!realDisabled && missingKey && (
        <div className="rounded-lg border border-rose-300/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          Provider news non configurato.
        </div>
      )}

      {message && (
        <div className="rounded-lg border border-cyan-300/20 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">
          {message}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rose-300/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          {error}
        </div>
      )}

      {status && (
        <Panel title="Stato provider news">
          <div className="grid gap-3 md:grid-cols-4">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-xs uppercase text-slate-500">Real news</p>
              <p className={status.enable_real_news ? "mt-1 font-semibold text-emerald-300" : "mt-1 font-semibold text-amber-300"}>
                {status.enable_real_news ? "Abilitate" : "Disattivate"}
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-xs uppercase text-slate-500">Provider</p>
              <p className="mt-1 font-semibold text-white">
                {realProvider?.provider ?? "mock_news"}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {realProvider?.api_key_configured ? "API key configurata" : "API key mancante"}
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-xs uppercase text-slate-500">Uso API news</p>
              <p className="mt-1 font-semibold text-white">
                {status.daily_usage.calls_count}/{status.daily_usage.daily_limit}
              </p>
              <p className="mt-1 text-xs text-slate-500">{status.daily_usage.usage_date}</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-xs uppercase text-slate-500">Cache news</p>
              <p className="mt-1 font-semibold text-white">
                {status.cache_status.valid ?? 0}/{status.cache_status.entries ?? 0}
              </p>
              <p className="mt-1 text-xs text-slate-500">Ultimo refresh {status.last_refresh ?? "N/D"}</p>
            </div>
          </div>
        </Panel>
      )}

      <Panel title={selectedSymbol ? `News ${selectedSymbol}` : "News mercato"}>
        <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 md:flex-1">
            <Search className="h-4 w-4 text-slate-500" aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
              placeholder="Cerca titolo, fonte, symbol"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {filters.map((item) => (
              <button
                key={item.value}
                onClick={() => setFilter(item.value)}
                className={`rounded-md border px-3 py-1.5 text-xs font-semibold transition ${
                  filter === item.value
                    ? "border-cyan-300/40 bg-cyan-400/15 text-cyan-100"
                    : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {loading && <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />}

        {!loading && filtered.length === 0 && (
          <p className="text-sm text-slate-400">Nessuna news disponibile per i filtri selezionati.</p>
        )}

        {!loading && filtered.length > 0 && (
          <div className="space-y-4">
            {filtered.map((item) => (
              <article key={item.id} className="rounded-lg border border-slate-800 bg-slate-900/60 p-5">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="flex gap-3">
                    <span className="mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-700 bg-slate-950 text-slate-300">
                      <Newspaper className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div>
                      <p className="text-xs uppercase text-slate-500">
                        {item.source ?? "fonte sconosciuta"} · {formatDate(item.published_at)} · {item.symbol ?? "mercato"}
                      </p>
                      <h2 className="mt-2 text-base font-semibold text-white">{item.title}</h2>
                      {item.summary && <p className="mt-2 text-sm text-slate-300">{item.summary}</p>}
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-cyan-200 hover:text-cyan-100"
                        >
                          Apri fonte
                          <ExternalLink className="h-3 w-3" aria-hidden="true" />
                        </a>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <span className={`inline-flex w-fit rounded-md border px-2.5 py-1 text-xs font-semibold ${sentimentTone[item.sentiment_label]}`}>
                      {item.sentiment_label} {item.sentiment_score >= 0 ? "+" : ""}
                      {item.sentiment_score.toFixed(2)}
                    </span>
                    <span className={`inline-flex w-fit rounded-md border px-2.5 py-1 text-xs font-semibold ${impactTone[item.impact_level]}`}>
                      Impact {item.impact_level}
                    </span>
                    <span className="text-xs text-slate-500">Relevance {item.relevance_score.toFixed(0)}/100</span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
