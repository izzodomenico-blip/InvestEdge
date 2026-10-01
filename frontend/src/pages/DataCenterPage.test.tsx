import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type {
  Asset,
  Backup,
  DataCoverage,
  DataProviderStatus,
  DataRefreshAllResult,
  DataStatus,
  FxCoverage,
  ProviderCoverage,
} from "../lib/api";
import { DataCenterPage } from "./DataCenterPage";

// Orari deterministici: vista locale fissata su Europe/Rome, UTC nel tooltip.
vi.stubEnv("TZ", "Europe/Rome");

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    apiGet: vi.fn(),
    apiPost: vi.fn(),
    apiDelete: vi.fn(),
    getDataCoverage: vi.fn(),
    refreshAll: vi.fn(),
  };
});

const mocked = {
  apiGet: vi.mocked(api.apiGet),
  apiPost: vi.mocked(api.apiPost),
  getDataCoverage: vi.mocked(api.getDataCoverage),
  refreshAll: vi.mocked(api.refreshAll),
};

function providerCoverage(overrides: Partial<ProviderCoverage> = {}): ProviderCoverage {
  return {
    provider: "stooq",
    capability: "EOD",
    eligible_listings: 40,
    unmapped_listings: 25,
    mapped_listings: 15,
    fresh_listings: 9,
    stale_listings: 4,
    missing_observation_listings: 2,
    rejected_observations: 3,
    quality_counts: { realtime: 0, delayed: 0, eod: 9, reference: 0, stale: 4 },
    delay_bucket_counts: { "0-5m": 0, "5-30m": 0, "30m-24h": 9, "1-4d": 3, ">4d": 1 },
    latest_provider_observed_at: "2026-09-30T20:00:00Z",
    latest_ingested_at: "2026-09-30T22:15:00Z",
    attribution: null,
    ...overrides,
  };
}

function fxItem(overrides: Partial<FxCoverage> = {}): FxCoverage {
  return {
    from_currency: "USD",
    to_currency: "EUR",
    status: "FRESH",
    direction: "DIRECT",
    provider: "ecb",
    rate_to_eur: "0.923456789",
    observed_at: "2026-09-30T14:00:00Z",
    ingested_at: "2026-09-30T15:00:00Z",
    age_seconds: 64800,
    quality: "reference",
    ...overrides,
  };
}

function coverage(overrides: Partial<DataCoverage> = {}): DataCoverage {
  return {
    measured_at: "2026-10-01T08:00:00Z",
    latest_catalog_snapshot_id: 7,
    latest_catalog_retrieved_at: "2026-09-30T06:00:00Z",
    latest_catalog_sha256: `ab12cd34${"0".repeat(56)}`,
    parse_accepted_entries: 150,
    parse_ambiguous_entries: 6,
    parse_rejected_entries: 4,
    parse_denominator: 160,
    resolution_resolved_entries: 100,
    resolution_ambiguous_entries: 10,
    resolution_unmatched_entries: 20,
    resolution_rejected_entries: 5,
    resolution_unprocessed_entries: 15,
    resolution_denominator: 150,
    resolved_percent: 66.67,
    tier_denominator: 120,
    tier_counts: { QUALIFIED: 30, OBSERVABLE: 40, REFERENCE_ONLY: 50 },
    tier_percentages: { QUALIFIED: 25, OBSERVABLE: 33.33, REFERENCE_ONLY: 41.67 },
    trade_republic_denominator: 150,
    trade_republic_status_counts: {
      UNRESOLVED_IDENTITY: 50,
      NEVER_SEEN: 0,
      CATALOGED: 80,
      VERIFIED: 15,
      UNAVAILABLE: 5,
    },
    trade_republic_verified_percent: 10,
    by_asset_class: [
      { key: "EQUITY", total: 120, resolved: 90, qualified: 28, observable: 35, reference_only: 57 },
      { key: "UNKNOWN", total: 30, resolved: 10, qualified: 2, observable: 5, reference_only: 23 },
    ],
    by_market: [
      { key: "XNAS", total: 60, resolved: 60, qualified: 20, observable: 25, reference_only: 15 },
      { key: "UNRESOLVED", total: 50, resolved: 0, qualified: 0, observable: 0, reference_only: 50 },
    ],
    rejection_reasons: {
      "PARSE:INVALID_ISIN": 3,
      "PARSE:MISSING_NAME": 1,
      "RESOLUTION:NO_CANDIDATE": 20,
      "RESOLUTION:MULTIPLE_CANDIDATES": 10,
    },
    provider_coverage: [
      providerCoverage(),
      providerCoverage({
        provider: "finnhub",
        capability: "QUOTE",
        eligible_listings: 12,
        unmapped_listings: 12,
        mapped_listings: 0,
        fresh_listings: 0,
        stale_listings: 0,
        missing_observation_listings: 0,
        rejected_observations: 0,
        quality_counts: { realtime: 0, delayed: 0, eod: 0, reference: 0, stale: 0 },
        delay_bucket_counts: { "0-5m": 0, "5-30m": 0, "30m-24h": 0, "1-4d": 0, ">4d": 0 },
        latest_provider_observed_at: null,
        latest_ingested_at: null,
      }),
      providerCoverage({
        provider: "coingecko",
        capability: "QUOTE",
        eligible_listings: 5,
        unmapped_listings: 0,
        mapped_listings: 5,
        fresh_listings: 0,
        stale_listings: 5,
        missing_observation_listings: 0,
        rejected_observations: 0,
        quality_counts: { realtime: 0, delayed: 0, eod: 0, reference: 0, stale: 5 },
        delay_bucket_counts: { "0-5m": 5, "5-30m": 0, "30m-24h": 0, "1-4d": 0, ">4d": 0 },
        latest_provider_observed_at: "2026-09-29T10:00:00Z",
        latest_ingested_at: "2026-09-29T10:00:30Z",
        attribution: "Powered by CoinGecko API",
      }),
    ],
    fx_currency_denominator: 5,
    fx_fresh_currencies: 3,
    fx_stale_currencies: 1,
    fx_missing_currencies: 1,
    fx_coverage: [
      fxItem({ from_currency: "CHF", status: "MISSING", direction: null, provider: null, rate_to_eur: null, observed_at: null, ingested_at: null, age_seconds: null, quality: null }),
      fxItem({ from_currency: "GBP", status: "STALE", rate_to_eur: "1.1834", observed_at: "2026-09-20T14:00:00Z", ingested_at: "2026-09-20T15:00:00Z", age_seconds: 928800, quality: "stale" }),
      fxItem({ from_currency: "JPY", direction: "INVERSE", rate_to_eur: "0.0062" }),
      fxItem({ from_currency: "NOK", rate_to_eur: "1e-3" }),
      fxItem(),
    ],
    pending_refresh: 7,
    budget_deferred: 2,
    ...overrides,
  };
}

function emptyCoverage(): DataCoverage {
  return coverage({
    latest_catalog_snapshot_id: null,
    latest_catalog_retrieved_at: null,
    latest_catalog_sha256: null,
    parse_accepted_entries: 0,
    parse_ambiguous_entries: 0,
    parse_rejected_entries: 0,
    parse_denominator: 0,
    resolution_resolved_entries: 0,
    resolution_ambiguous_entries: 0,
    resolution_unmatched_entries: 0,
    resolution_rejected_entries: 0,
    resolution_unprocessed_entries: 0,
    resolution_denominator: 0,
    resolved_percent: 0,
    tier_denominator: 0,
    tier_counts: { QUALIFIED: 0, OBSERVABLE: 0, REFERENCE_ONLY: 0 },
    tier_percentages: { QUALIFIED: 0, OBSERVABLE: 0, REFERENCE_ONLY: 0 },
    trade_republic_denominator: 0,
    trade_republic_status_counts: { UNRESOLVED_IDENTITY: 0, NEVER_SEEN: 0, CATALOGED: 0, VERIFIED: 0, UNAVAILABLE: 0 },
    trade_republic_verified_percent: 0,
    by_asset_class: [],
    by_market: [],
    rejection_reasons: {},
    provider_coverage: [],
    fx_currency_denominator: 0,
    fx_fresh_currencies: 0,
    fx_stale_currencies: 0,
    fx_missing_currencies: 0,
    fx_coverage: [],
    pending_refresh: 0,
    budget_deferred: 0,
  });
}

function providerStatus(overrides: Partial<DataProviderStatus> = {}): DataProviderStatus {
  return {
    provider: "finnhub",
    enabled: true,
    api_key_configured: false,
    daily_limit: 1000,
    calls_today: 3,
    supports: ["quote"],
    capabilities: ["QUOTE"],
    budget_windows: [
      { window: "MINUTE", limit: 55, used: 3, remaining: 52, reset_at: "2026-10-01T08:01:00Z" },
      { window: "DAY", limit: 1000, used: 3, remaining: 997, reset_at: "2026-10-02T00:00:00Z" },
      { window: "MONTH", limit: null, used: 40, remaining: null, reset_at: "2026-11-01T00:00:00Z" },
    ],
    cooldown_until: "2026-10-01T08:05:00Z",
    availability_state: "COOLDOWN",
    availability_reason: "RATE_LIMITED",
    last_outcome: "RATE_LIMITED",
    last_outcome_at: "2026-10-01T07:59:00Z",
    ...overrides,
  };
}

function dataStatus(overrides: Partial<DataStatus> = {}): DataStatus {
  return {
    enable_real_data: true,
    provider_status: [
      providerStatus(),
      providerStatus({
        provider: "alpha_vantage",
        enabled: false,
        daily_limit: 20,
        calls_today: 0,
        supports: ["eod"],
        capabilities: ["EOD"],
        budget_windows: [],
        cooldown_until: null,
        availability_state: "DISABLED",
        availability_reason: "SECRET_IN_QUERY_POLICY",
        last_outcome: null,
        last_outcome_at: null,
      }),
      providerStatus({
        provider: "fred",
        enabled: false,
        daily_limit: 100,
        calls_today: 0,
        supports: ["macro", "bond_proxy", "Fonte: FRED®, Federal Reserve Bank of St. Louis"],
        capabilities: ["REFERENCE"],
        budget_windows: [],
        cooldown_until: null,
        availability_state: "DISABLED",
        availability_reason: "MISSING_CREDENTIAL",
        last_outcome: null,
        last_outcome_at: null,
      }),
    ],
    api_usage: [{ provider: "finnhub", usage_date: "2026-10-01", calls_count: 3, daily_limit: 1000, updated_at: null }],
    cache_stats: { entries: 4, valid: 2 },
    global_last_update: "2026-09-30 22:15:00",
    data_mode: "MIXED",
    coverage_summary: null,
    ...overrides,
  };
}

const activeAsset = {
  id: 1,
  symbol: "AAPL",
  name: "Apple Inc.",
  asset_type: "stock",
  is_real_data: false,
  last_source: "seed",
  provider: null,
  last_price_date: "2026-09-30",
  last_fetch_at: null,
} as Asset;

const backups: Backup[] = [
  { file: "investedge-20261001-080000.db", size_bytes: 2 * 1024 * 1024, created_at: "2026-10-01T08:00:00" },
];

const batchResult: DataRefreshAllResult = {
  summary: { requested: 2, updated: 1, fallback: 1, rows_inserted: 5, rows_updated: 1 },
  results: [
    { symbol: "AAPL", provider: "stooq", rows_inserted: 5, rows_updated: 1, used_cache: false, used_fallback: false, message: "ok" },
    { symbol: "BTC", provider: null, rows_inserted: 0, rows_updated: 0, used_cache: true, used_fallback: true, message: "fallback" },
  ],
};

function valueOf(container: HTMLElement, label: string): string | null {
  const term = within(container).getByText(label, { selector: "dt" });
  return term.nextElementSibling?.textContent ?? null;
}

function rowOf(table: HTMLElement, label: string): HTMLElement {
  const cell = within(table).getByText(label, { selector: "th" });
  return cell.closest("tr") as HTMLElement;
}

function statusCalls() {
  return mocked.apiGet.mock.calls.filter(([path]) => path === "/data/status").length;
}

async function renderLoaded() {
  render(<DataCenterPage />);
  await screen.findByRole("table", { name: "Copertura provider" });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-01T08:30:00Z"));
  mocked.apiGet.mockImplementation(async (path: string) => {
    if (path === "/data/status") return dataStatus();
    if (path === "/assets") return [activeAsset];
    if (path === "/backups") return backups;
    throw new Error(`unexpected GET ${path}`);
  });
  mocked.apiPost.mockRejectedValue(new Error("unexpected POST"));
  mocked.getDataCoverage.mockResolvedValue(coverage());
  mocked.refreshAll.mockResolvedValue(batchResult);
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("Data Center coverage", () => {
  it("shows coverage loading, then catalog parsing, resolution, tier and Trade Republic denominators", async () => {
    let resolveCoverage: (value: DataCoverage) => void = () => undefined;
    mocked.getDataCoverage.mockReturnValueOnce(
      new Promise<DataCoverage>((resolve) => {
        resolveCoverage = resolve;
      }),
    );
    render(<DataCenterPage />);

    expect(await screen.findByRole("status")).toHaveTextContent("Caricamento copertura dati");
    resolveCoverage(coverage());

    const parsing = await screen.findByRole("group", { name: "Parsing catalogo" });
    expect(valueOf(parsing, "Accettate")).toBe("150");
    expect(valueOf(parsing, "Ambigue")).toBe("6");
    expect(valueOf(parsing, "Rifiutate")).toBe("4");
    expect(valueOf(parsing, "Denominatore")).toBe("160 entry");

    const resolution = screen.getByRole("group", { name: "Risoluzione identità" });
    expect(valueOf(resolution, "Risolte")).toBe("100");
    expect(valueOf(resolution, "Ambigue")).toBe("10");
    expect(valueOf(resolution, "Non trovate")).toBe("20");
    expect(valueOf(resolution, "Rifiutate")).toBe("5");
    expect(valueOf(resolution, "Non processate")).toBe("15");
    expect(valueOf(resolution, "Denominatore")).toBe("150 entry accettate");
    expect(within(resolution).getByText("66,67% risolte su 150")).toBeInTheDocument();

    const tiers = screen.getByRole("group", { name: "Tier di qualità" });
    expect(valueOf(tiers, "Qualified")).toBe("30 · 25%");
    expect(valueOf(tiers, "Observable")).toBe("40 · 33,33%");
    expect(valueOf(tiers, "Reference only")).toBe("50 · 41,67%");
    expect(valueOf(tiers, "Denominatore")).toBe("120 strumenti");

    const tradeRepublic = screen.getByRole("group", { name: "Stato Trade Republic" });
    expect(valueOf(tradeRepublic, "Identità non risolta")).toBe("50");
    expect(valueOf(tradeRepublic, "Mai visto")).toBe("0");
    expect(valueOf(tradeRepublic, "Nel catalogo")).toBe("80");
    expect(valueOf(tradeRepublic, "Verificato")).toBe("15");
    expect(valueOf(tradeRepublic, "Non disponibile")).toBe("5");
    expect(valueOf(tradeRepublic, "Denominatore")).toBe("150 entry accettate");
    expect(within(tradeRepublic).getByText("10% verificati su 150")).toBeInTheDocument();

    const measured = screen.getByText("01/10/26, 10:00:00");
    expect(measured.tagName).toBe("TIME");
    expect(measured).toHaveAttribute("title", "2026-10-01 08:00:00 UTC");
    expect(screen.getByText("Snapshot #7")).toBeInTheDocument();
    expect(screen.getByText("SHA-256 ab12cd34…")).toBeInTheDocument();

    const byClass = screen.getByRole("table", { name: "Copertura per classe" });
    expect(within(rowOf(byClass, "EQUITY")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "120",
      "90",
      "28",
      "35",
      "57",
    ]);
    const byMarket = screen.getByRole("table", { name: "Copertura per mercato" });
    expect(within(rowOf(byMarket, "UNRESOLVED")).getAllByRole("cell")[0]).toHaveTextContent("50");
    expect(mocked.getDataCoverage).toHaveBeenCalledTimes(1);
  });

  it("shows the API percentages verbatim instead of recomputing them", async () => {
    mocked.getDataCoverage.mockResolvedValueOnce(
      coverage({
        resolved_percent: 12.34,
        tier_percentages: { QUALIFIED: 1.5, OBSERVABLE: 2.5, REFERENCE_ONLY: 96 },
        trade_republic_verified_percent: 99.99,
      }),
    );
    await renderLoaded();

    expect(screen.getByText("12,34% risolte su 150")).toBeInTheDocument();
    expect(valueOf(screen.getByRole("group", { name: "Tier di qualità" }), "Qualified")).toBe("30 · 1,5%");
    expect(screen.getByText("99,99% verificati su 150")).toBeInTheDocument();
  });

  it("shows provider partitions, quality, delay buckets, timestamps and attribution", async () => {
    await renderLoaded();
    const table = screen.getByRole("table", { name: "Copertura provider" });

    const stooq = rowOf(table, "stooq · EOD");
    expect(within(stooq).getAllByRole("cell").slice(0, 7).map((cell) => cell.textContent)).toEqual([
      "40",
      "25",
      "15",
      "9",
      "4",
      "2",
      "3",
    ]);
    expect(within(stooq).getByText("Fine giornata 9")).toBeInTheDocument();
    expect(within(stooq).getByText("Dato non aggiornato 4")).toBeInTheDocument();
    expect(within(stooq).getByText("30m-24h 9")).toBeInTheDocument();
    expect(within(stooq).getByText("1-4d 3")).toBeInTheDocument();
    expect(within(stooq).getByText(">4d 1")).toBeInTheDocument();
    expect(within(stooq).queryByText(/0-5m/)).not.toBeInTheDocument();
    const observed = within(stooq).getByText("30/09/26, 22:00:00");
    expect(observed).toHaveAttribute("title", "2026-09-30 20:00:00 UTC");
    expect(within(stooq).getByText("01/10/26, 00:15:00")).toHaveAttribute("title", "2026-09-30 22:15:00 UTC");

    const finnhub = rowOf(table, "finnhub · QUOTE");
    expect(within(finnhub).getAllByRole("cell").slice(0, 3).map((cell) => cell.textContent)).toEqual(["12", "12", "0"]);
    expect(within(finnhub).getAllByText("—").length).toBeGreaterThanOrEqual(4);

    const coingecko = rowOf(table, "coingecko · QUOTE");
    expect(within(coingecko).getByText("Dato non aggiornato 5")).toBeInTheDocument();
    expect(within(coingecko).queryByText(/Tempo reale|realtime/i)).not.toBeInTheDocument();
    expect(within(coingecko).getByText("Powered by CoinGecko API")).toBeInTheDocument();
  });

  it("shows budget windows, cooldown, readable reason codes and last outcome per provider", async () => {
    await renderLoaded();

    const finnhub = screen.getByRole("article", { name: "Provider finnhub" });
    expect(within(finnhub).getByText("QUOTE")).toBeInTheDocument();
    expect(within(finnhub).getByText("In cooldown: Limite di richieste raggiunto (RATE_LIMITED)")).toBeInTheDocument();
    expect(within(finnhub).getByText("01/10/26, 10:05:00")).toHaveAttribute("title", "2026-10-01 08:05:00 UTC");
    expect(within(finnhub).getByText("Limitata (429)")).toBeInTheDocument();
    expect(within(finnhub).getByText("01/10/26, 09:59:00")).toHaveAttribute("title", "2026-10-01 07:59:00 UTC");

    const budget = within(finnhub).getByRole("table", { name: "Budget finnhub" });
    expect(within(rowOf(budget, "Minuto")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "3 / 55",
      "52",
      "01/10/26, 10:01:00",
    ]);
    expect(within(rowOf(budget, "Mese")).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "40 / senza limite",
      "—",
      "01/11/26, 01:00:00",
    ]);
    // Campi legacy invariati.
    expect(within(finnhub).getByText("3/1000")).toBeInTheDocument();

    const alpha = screen.getByRole("article", { name: "Provider alpha_vantage" });
    expect(
      within(alpha).getByText("Disattivato: Bloccato: la chiave finirebbe nell'URL (SECRET_IN_QUERY_POLICY)"),
    ).toBeInTheDocument();
    expect(within(alpha).getByText("Nessuna finestra di budget registrata.")).toBeInTheDocument();
    expect(within(alpha).getByText("Nessun esito registrato")).toBeInTheDocument();

    // Provider disattivato: motivo leggibile e attribuzione obbligatoria visibili.
    const fred = screen.getByRole("article", { name: "Provider fred" });
    expect(within(fred).getByText("Disattivato: Chiave API non configurata (MISSING_CREDENTIAL)")).toBeInTheDocument();
    expect(within(fred).getByText(/Fonte: FRED®, Federal Reserve Bank of St\. Louis/)).toBeInTheDocument();
    expect(within(fred).getByText("REFERENCE")).toBeInTheDocument();
  });

  it("shows EUR FX coverage separately with direct/inverse rates and safe decimal formatting", async () => {
    await renderLoaded();

    const counts = screen.getByRole("group", { name: "Copertura cambi" });
    expect(valueOf(counts, "Freschi")).toBe("3");
    expect(valueOf(counts, "Non aggiornati")).toBe("1");
    expect(valueOf(counts, "Mancanti")).toBe("1");
    expect(valueOf(counts, "Denominatore")).toBe("5 valute non-EUR");

    const table = screen.getByRole("table", { name: "Cambi verso EUR" });
    const usd = rowOf(table, "USD/EUR");
    expect(within(usd).getByText("Fresco")).toBeInTheDocument();
    expect(within(usd).getByText("Diretto")).toBeInTheDocument();
    const rate = within(usd).getByText("0,923457");
    expect(rate).toHaveAttribute("title", "0.923456789");
    expect(within(usd).getByText("ecb")).toBeInTheDocument();
    expect(within(usd).getByText("30/09/26, 16:00:00")).toHaveAttribute("title", "2026-09-30 14:00:00 UTC");
    expect(within(usd).getByText("30/09/26, 17:00:00")).toHaveAttribute("title", "2026-09-30 15:00:00 UTC");
    expect(within(usd).getByText("18 h")).toBeInTheDocument();

    const jpy = rowOf(table, "JPY/EUR");
    expect(within(jpy).getByText("Inverso")).toBeInTheDocument();
    expect(within(jpy).getByText("0,0062")).toBeInTheDocument();

    const gbp = rowOf(table, "GBP/EUR");
    expect(within(gbp).getByText("Non aggiornato")).toBeInTheDocument();
    expect(within(gbp).getByText("10 g")).toBeInTheDocument();

    const chf = rowOf(table, "CHF/EUR");
    expect(within(chf).getByText("Mancante")).toBeInTheDocument();
    expect(within(chf).getAllByText("—").length).toBeGreaterThanOrEqual(5);

    const nok = rowOf(table, "NOK/EUR");
    expect(within(nok).queryByText(/1e-3|0,001/)).not.toBeInTheDocument();
    expect(within(nok).getAllByRole("cell")[2]).toHaveTextContent("—");

    // FX non compare tra le coppie provider/listing.
    const providers = screen.getByRole("table", { name: "Copertura provider" });
    expect(within(providers).queryByText(/ecb|FX/)).not.toBeInTheDocument();
  });

  it("shows parser and resolution rejections separately and the refresh queue", async () => {
    await renderLoaded();

    const rejections = screen.getByRole("table", { name: "Motivi di rejection" });
    const rows = within(rejections).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "RisoluzioneNO_CANDIDATE20",
      "RisoluzioneMULTIPLE_CANDIDATES10",
      "ParserINVALID_ISIN3",
      "ParserMISSING_NAME1",
    ]);

    const queue = screen.getByRole("group", { name: "Coda refresh" });
    expect(valueOf(queue, "In attesa")).toBe("7");
    expect(valueOf(queue, "Rinviate per budget")).toBe("2");
  });

  it("shows explicit empty states without inventing coverage", async () => {
    mocked.getDataCoverage.mockResolvedValueOnce(emptyCoverage());
    render(<DataCenterPage />);

    expect(await screen.findByText("Nessuno snapshot completo del catalogo: denominatori a zero.")).toBeInTheDocument();
    expect(valueOf(screen.getByRole("group", { name: "Risoluzione identità" }), "Denominatore")).toBe(
      "0 entry accettate",
    );
    expect(screen.getByText("0% risolte su 0")).toBeInTheDocument();
    expect(screen.getByText("Nessuna coppia provider/capability misurabile.")).toBeInTheDocument();
    expect(screen.getByText("Nessuna valuta non-EUR da coprire.")).toBeInTheDocument();
    expect(screen.getByText("Nessuna rejection registrata.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Copertura provider" })).not.toBeInTheDocument();
  });

  it("keeps legacy status and backups visible when coverage fails", async () => {
    mocked.getDataCoverage.mockRejectedValueOnce(
      new api.ApiError("API request failed: 500", 500, { reason_code: "COVERAGE_INVARIANT_FAILED" }),
    );
    render(<DataCenterPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Copertura non disponibile: le partizioni non sommano al proprio denominatore (COVERAGE_INVARIANT_FAILED).",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent(/http|\/data\/coverage/i);
    expect(screen.getByText("Backup del database")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Provider finnhub" })).toBeInTheDocument();
    expect(screen.getByText("Modalita dati")).toBeInTheDocument();
  });
});

describe("Data Center legacy panels", () => {
  it("keeps data mode, backup list and manual backup unchanged", async () => {
    mocked.apiPost.mockImplementation(async (path: string) => {
      if (path === "/backups/create") return { ...backups[0], created: true };
      throw new Error(`unexpected POST ${path}`);
    });
    await renderLoaded();

    expect(screen.getAllByText("MIXED").length).toBeGreaterThan(0);
    expect(screen.getByText("investedge-20261001-080000.db")).toBeInTheDocument();
    expect(screen.getByText("2.0 MB")).toBeInTheDocument();
    const backupLoads = mocked.apiGet.mock.calls.filter(([path]) => path === "/backups").length;

    fireEvent.click(screen.getByRole("button", { name: "Backup ora" }));

    expect(await screen.findByText("Backup creato: investedge-20261001-080000.db")).toBeInTheDocument();
    expect(mocked.apiPost).toHaveBeenCalledWith("/backups/create");
    expect(mocked.apiGet.mock.calls.filter(([path]) => path === "/backups").length).toBe(backupLoads + 1);
  });
});

describe("Data Center priority batch", () => {
  it("replaces the bulk action with a bounded batch of 10 and reloads status and coverage", async () => {
    let resolveBatch: (value: DataRefreshAllResult) => void = () => undefined;
    mocked.refreshAll.mockReturnValueOnce(
      new Promise<DataRefreshAllResult>((resolve) => {
        resolveBatch = resolve;
      }),
    );
    await renderLoaded();

    expect(screen.queryByText(/Aggiorna tutti i dati/)).not.toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Esegui batch prioritario (10)" });
    const statusLoads = statusCalls();

    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: /Batch prioritario in corso/ }));

    expect(mocked.refreshAll).toHaveBeenCalledTimes(1);
    expect(mocked.refreshAll).toHaveBeenCalledWith(10);
    expect(screen.getByRole("button", { name: /Batch prioritario in corso/ })).toBeDisabled();
    // Il batch ha un loading separato: il pannello backup resta utilizzabile.
    expect(screen.getByRole("button", { name: "Backup ora" })).toBeEnabled();

    resolveBatch(batchResult);

    expect(
      await screen.findByText(
        "Batch prioritario completato: 2 unità eseguite, 1 senza fallback, 1 con fallback, 5 righe nuove, 1 aggiornate.",
      ),
    ).toBeInTheDocument();
    await waitFor(() => expect(mocked.getDataCoverage).toHaveBeenCalledTimes(2));
    expect(statusCalls()).toBe(statusLoads + 1);
    expect(mocked.apiPost).not.toHaveBeenCalled();
  });

  it("shows batch errors without hiding the rest of the page", async () => {
    mocked.refreshAll.mockRejectedValueOnce(new api.ApiError("API request failed: 409", 409));
    await renderLoaded();

    fireEvent.click(screen.getByRole("button", { name: "Esegui batch prioritario (10)" }));

    expect(await screen.findByText("API request failed: 409")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Copertura provider" })).toBeInTheDocument();
    expect(mocked.getDataCoverage).toHaveBeenCalledTimes(1);
  });
});

describe("coverage API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the bounded batch with an encoded limit and no body, preserving DataRefreshAllOut", async () => {
    const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(batchResult), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await actual.refreshAll(10);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/data\/refresh-all\?limit=10$/);
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
    expect(init.headers).toBeUndefined();
    expect(result).toEqual(batchResult);
    expect(result.results[1]).toEqual({
      symbol: "BTC",
      provider: null,
      rows_inserted: 0,
      rows_updated: 0,
      used_cache: true,
      used_fallback: true,
      message: "fallback",
    });

    for (const invalid of [0, 26, 2.5, Number.NaN, -1]) {
      await expect(actual.refreshAll(invalid)).rejects.toBeInstanceOf(RangeError);
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const failure = await actual.refreshAll(25).catch((error: unknown) => error);
    expect((failure as Error).message).toContain("POST /data/refresh-all");
    expect((failure as Error).message).not.toContain("limit=");
  });

  it("reads coverage with a single GET and keeps rate_to_eur as a decimal string", async () => {
    const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
    const payload = coverage();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await actual.getDataCoverage();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/data\/coverage$/);
    expect(fetchMock.mock.calls[0][1]?.method ?? "GET").toBe("GET");
    expect(result.fx_coverage[4].rate_to_eur).toBe("0.923456789");
    expect(result.fx_coverage[0].rate_to_eur).toBeNull();

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: { reason_code: "COVERAGE_INVARIANT_FAILED" } }), { status: 500 }),
    );
    const failure = await actual.getDataCoverage().catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(actual.ApiError);
    expect(actual.apiReasonCode(failure)).toBe("COVERAGE_INVARIANT_FAILED");
  });

  it("formats rate_to_eur only from complete finite decimal strings", async () => {
    const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");

    expect(actual.formatRateToEur("0.923456789")).toBe("0,923457");
    expect(actual.formatRateToEur("1")).toBe("1");
    for (const invalid of [null, "", " 0.9", "1e-3", "0.9.1", "NaN", "Infinity", "-0.5", "0,92", "9".repeat(400)]) {
      expect(actual.formatRateToEur(invalid)).toBe("—");
    }
  });
});
