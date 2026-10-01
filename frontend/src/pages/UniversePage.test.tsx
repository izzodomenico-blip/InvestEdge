import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { Asset, InstrumentDetail, InstrumentListItem, InstrumentSearch } from "../lib/api";
import { UniversePage } from "./UniversePage";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    apiGet: vi.fn(),
    apiPost: vi.fn(),
    apiDelete: vi.fn(),
    getInstruments: vi.fn(),
    getInstrument: vi.fn(),
    activateListing: vi.fn(),
    markListingViewed: vi.fn(),
  };
});

const mocked = {
  apiGet: vi.mocked(api.apiGet),
  apiPost: vi.mocked(api.apiPost),
  getInstruments: vi.mocked(api.getInstruments),
  getInstrument: vi.mocked(api.getInstrument),
  activateListing: vi.mocked(api.activateListing),
  markListingViewed: vi.mocked(api.markListingViewed),
};

function listItem(overrides: Partial<InstrumentListItem> = {}): InstrumentListItem {
  return {
    instrument_id: 1,
    canonical_name: "Zeta Catalog Alpha",
    instrument_type: "STOCK",
    asset_class: "EQUITY",
    quality_tier: "REFERENCE_ONLY",
    quality_reasons: [],
    primary_identifier_scheme: "ISIN",
    primary_identifier: "US9ZETAAAA01",
    listing_id: 11,
    ticker: "ZTAA",
    mic: "XNAS",
    venue_name: "Venue XNAS",
    currency: "USD",
    timezone: "America/New_York",
    trade_republic_status: "CATALOGED",
    trade_republic_cataloged_at: "2026-09-20T08:00:00Z",
    trade_republic_verified_at: null,
    observation_quality: "stale",
    observed_at: "2026-01-02T21:00:00Z",
    ...overrides,
  };
}

function searchResult(items: InstrumentListItem[], overrides: Partial<InstrumentSearch> = {}): InstrumentSearch {
  return { items, total: items.length, limit: 50, offset: 0, catalog_snapshot_id: 7, ...overrides };
}

function detail(overrides: Partial<InstrumentDetail> = {}): InstrumentDetail {
  return {
    ...listItem(),
    identifiers: [
      {
        scheme: "ISIN",
        value: "US9ZETAAAA01",
        sources: ["TRADE_REPUBLIC_IT"],
        first_observed_at: "2026-09-20T08:00:00Z",
        last_observed_at: "2026-09-20T08:00:00Z",
      },
      {
        scheme: "FIGI",
        value: "BBG0ZETA0001",
        sources: ["openfigi"],
        first_observed_at: "2026-09-21T09:00:00Z",
        last_observed_at: "2026-09-21T09:00:00Z",
      },
    ],
    listings: [
      {
        listing_id: 11,
        ticker: "ZTAA",
        mic: "XNAS",
        venue_name: "Venue XNAS",
        currency: "USD",
        timezone: "America/New_York",
        resolution_status: "RESOLVED",
        trade_republic_status: "CATALOGED",
      },
      {
        listing_id: 12,
        ticker: "ZTAA",
        mic: "XETR",
        venue_name: "Venue XETR",
        currency: "EUR",
        timezone: "Europe/Berlin",
        resolution_status: "AMBIGUOUS",
        trade_republic_status: "NEVER_SEEN",
      },
    ],
    ...overrides,
  };
}

const activeAsset = {
  id: 1,
  symbol: "AAPL",
  name: "Apple Inc.",
  asset_type: "stock",
} as Asset;

function lastSearchFilters() {
  const calls = mocked.getInstruments.mock.calls;
  return calls[calls.length - 1][0];
}

async function openCatalog() {
  render(<UniversePage />);
  fireEvent.click(screen.getByRole("tab", { name: /Catalogo/ }));
  await screen.findByRole("list", { name: "Risultati catalogo" });
}

beforeEach(() => {
  mocked.apiGet.mockImplementation(async (path: string) => {
    if (path === "/assets") return [activeAsset];
    throw new Error(`unexpected GET ${path}`);
  });
  mocked.apiPost.mockRejectedValue(new Error("unexpected POST"));
  mocked.getInstruments.mockResolvedValue(searchResult([listItem()]));
  mocked.getInstrument.mockResolvedValue(detail());
  mocked.markListingViewed.mockResolvedValue({ refresh_request_id: 99 });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("UniversePage tabs", () => {
  it("keeps active assets as default tab and loads the catalog only on demand", async () => {
    render(<UniversePage />);

    expect(screen.getByRole("tab", { name: /Attivi/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(mocked.apiGet).toHaveBeenCalledWith("/assets");
    expect(mocked.getInstruments).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("tab", { name: /Catalogo/ }));

    expect(await screen.findByText("Zeta Catalog Alpha")).toBeInTheDocument();
    expect(mocked.getInstruments).toHaveBeenCalledTimes(1);
    expect(lastSearchFilters()).toEqual({ limit: 50, offset: 0 });
    expect(mocked.markListingViewed).not.toHaveBeenCalled();
    expect(mocked.apiPost).not.toHaveBeenCalled();
  });
});

describe("Universe catalog", () => {
  it("shows loading, then identity and quality badges without suggesting tradability", async () => {
    let resolveSearch: (value: InstrumentSearch) => void = () => undefined;
    mocked.getInstruments.mockReturnValueOnce(
      new Promise<InstrumentSearch>((resolve) => {
        resolveSearch = resolve;
      }),
    );
    render(<UniversePage />);
    fireEvent.click(screen.getByRole("tab", { name: /Catalogo/ }));

    expect(await screen.findByRole("status")).toHaveTextContent("Caricamento catalogo");
    resolveSearch(
      searchResult([
        listItem(),
        listItem({
          instrument_id: 2,
          canonical_name: "Zeta Catalog Beta",
          quality_tier: "QUALIFIED",
          listing_id: null,
          ticker: null,
          mic: null,
          venue_name: null,
          currency: null,
          timezone: null,
          observation_quality: null,
          observed_at: null,
          primary_identifier_scheme: "FIGI",
          primary_identifier: "BBG0ZETA0002",
        }),
      ]),
    );

    const results = await screen.findByRole("list", { name: "Risultati catalogo" });
    const [alpha, beta] = within(results).getAllByRole("listitem");
    expect(within(alpha).getByText("US9ZETAAAA01")).toBeInTheDocument();
    expect(within(alpha).getByText("XNAS")).toBeInTheDocument();
    expect(within(alpha).getByText("USD")).toBeInTheDocument();
    expect(within(alpha).getByText("Reference only")).toBeInTheDocument();
    expect(within(alpha).getByText("Dato non aggiornato")).toBeInTheDocument();
    expect(within(alpha).getByText("TR: nel catalogo, non verificato")).toBeInTheDocument();
    expect(within(beta).getByText("BBG0ZETA0002")).toBeInTheDocument();
    expect(within(beta).getByText("Qualified")).toBeInTheDocument();
    expect(within(beta).getByText("Nessuna osservazione")).toBeInTheDocument();
    expect(within(beta).getByText("Listing non risolto")).toBeInTheDocument();
    expect(results).not.toHaveTextContent(/negoziabile|acquistabile/i);
    expect(screen.getByText("2 strumenti")).toBeInTheDocument();
  });

  it("shows empty and error states", async () => {
    mocked.getInstruments.mockResolvedValueOnce(searchResult([]));
    await openCatalog();
    expect(screen.getByText("Nessuno strumento del catalogo corrisponde alla ricerca.")).toBeInTheDocument();

    mocked.getInstruments.mockRejectedValueOnce(new api.ApiError("API request failed: 503", 503));
    fireEvent.change(screen.getByLabelText("Tier qualità"), { target: { value: "QUALIFIED" } });

    expect(await screen.findByRole("alert")).toHaveTextContent("Catalogo non disponibile");
  });

  it("debounces the query and aborts the previous request", async () => {
    const signals: AbortSignal[] = [];
    mocked.getInstruments.mockImplementation((_filters, signal) => {
      if (signal) signals.push(signal);
      return signals.length === 1
        ? Promise.resolve(searchResult([listItem()]))
        : new Promise<InstrumentSearch>(() => undefined);
    });
    await openCatalog();
    const input = screen.getByLabelText("Cerca nel catalogo");

    fireEvent.change(input, { target: { value: "z" } });
    fireEvent.change(input, { target: { value: "ze" } });
    fireEvent.change(input, { target: { value: "zeta" } });
    expect(mocked.getInstruments).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(mocked.getInstruments).toHaveBeenCalledTimes(2));
    expect(lastSearchFilters()).toEqual({ q: "zeta", limit: 50, offset: 0 });

    fireEvent.change(input, { target: { value: "zeta beta" } });
    await waitFor(() => expect(mocked.getInstruments).toHaveBeenCalledTimes(3));
    expect(signals[1].aborted).toBe(true);
    expect(signals[2].aborted).toBe(false);
  });

  it("sends filters and replaces pages without concatenating them", async () => {
    mocked.getInstruments.mockImplementation(async (filters) =>
      searchResult(
        [listItem({ instrument_id: (filters.offset ?? 0) + 1, canonical_name: `Pagina ${filters.offset ?? 0}` })],
        { total: 120, offset: filters.offset ?? 0 },
      ),
    );
    await openCatalog();
    expect(await screen.findByText("Pagina 1 di 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pagina precedente" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Pagina successiva" }));

    expect(await screen.findByText("Pagina 50")).toBeInTheDocument();
    expect(screen.queryByText("Pagina 0")).not.toBeInTheDocument();
    expect(screen.getByText("Pagina 2 di 3")).toBeInTheDocument();
    expect(lastSearchFilters()).toEqual({ limit: 50, offset: 50 });

    fireEvent.change(screen.getByLabelText("Tier qualità"), { target: { value: "QUALIFIED" } });
    await waitFor(() =>
      expect(lastSearchFilters()).toEqual({ quality_tier: "QUALIFIED", limit: 50, offset: 0 }),
    );
    fireEvent.change(screen.getByLabelText("Stato Trade Republic"), { target: { value: "VERIFIED" } });
    fireEvent.change(screen.getByLabelText("Classe"), { target: { value: "FUND" } });
    fireEvent.change(screen.getByLabelText("Valuta listing"), { target: { value: "eu" } });
    fireEvent.change(screen.getByLabelText("MIC"), { target: { value: "xetr" } });
    await waitFor(() =>
      expect(lastSearchFilters()).toEqual({
        quality_tier: "QUALIFIED",
        trade_republic_status: "VERIFIED",
        asset_class: "FUND",
        mic: "XETR",
        limit: 50,
        offset: 0,
      }),
    );
    fireEvent.change(screen.getByLabelText("Valuta listing"), { target: { value: "eur" } });
    await waitFor(() => expect(lastSearchFilters()).toMatchObject({ currency: "EUR", offset: 0 }));
  });

  it("marks the opened listing as viewed once and blocks ambiguous mappings", async () => {
    await openCatalog();

    fireEvent.click(screen.getByRole("button", { name: "Apri dettaglio Zeta Catalog Alpha ZTAA XNAS" }));
    const panel = await screen.findByRole("region", { name: "Dettaglio Zeta Catalog Alpha" });

    expect(within(panel).getByText("BBG0ZETA0001")).toBeInTheDocument();
    expect(within(panel).getByText("XETR")).toBeInTheDocument();
    expect(within(panel).getByText("EUR")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Attiva ZTAA su XNAS" })).toBeEnabled();
    expect(within(panel).queryByRole("button", { name: "Attiva ZTAA su XETR" })).not.toBeInTheDocument();
    expect(within(panel).getByText("Mapping ambiguo: non attivabile")).toBeInTheDocument();
    expect(mocked.getInstrument).toHaveBeenCalledWith(1, expect.any(AbortSignal));
    expect(mocked.markListingViewed).toHaveBeenCalledTimes(1);
    expect(mocked.markListingViewed).toHaveBeenCalledWith(11);

    fireEvent.click(within(panel).getByRole("button", { name: "Chiudi dettaglio" }));
    fireEvent.click(screen.getByRole("button", { name: "Apri dettaglio Zeta Catalog Alpha ZTAA XNAS" }));
    await screen.findByRole("region", { name: "Dettaglio Zeta Catalog Alpha" });
    expect(mocked.markListingViewed).toHaveBeenCalledTimes(1);
    expect(mocked.apiPost).not.toHaveBeenCalled();
  });

  it("does not offer activation when the instrument identity is ambiguous", async () => {
    mocked.getInstrument.mockResolvedValueOnce(detail({ quality_reasons: ["AMBIGUOUS_IDENTITY"] }));
    await openCatalog();

    fireEvent.click(screen.getByRole("button", { name: "Apri dettaglio Zeta Catalog Alpha ZTAA XNAS" }));
    const panel = await screen.findByRole("region", { name: "Dettaglio Zeta Catalog Alpha" });

    expect(within(panel).queryByRole("button", { name: /^Attiva/ })).not.toBeInTheDocument();
    expect(within(panel).getAllByText("Mapping ambiguo: non attivabile")).toHaveLength(2);
  });

  it("activates explicitly, refreshes active assets and explains conflicts", async () => {
    mocked.activateListing.mockResolvedValueOnce({ ...activeAsset, id: 2, symbol: "ZTAA" });
    await openCatalog();
    fireEvent.click(screen.getByRole("button", { name: "Apri dettaglio Zeta Catalog Alpha ZTAA XNAS" }));
    const panel = await screen.findByRole("region", { name: "Dettaglio Zeta Catalog Alpha" });
    const assetLoads = mocked.apiGet.mock.calls.filter(([path]) => path === "/assets").length;

    fireEvent.click(within(panel).getByRole("button", { name: "Attiva ZTAA su XNAS" }));

    expect(await screen.findByText("ZTAA attivato nell'universe.")).toBeInTheDocument();
    expect(mocked.activateListing).toHaveBeenCalledWith(11);
    expect(mocked.apiGet.mock.calls.filter(([path]) => path === "/assets").length).toBe(assetLoads + 1);

    mocked.activateListing.mockRejectedValueOnce(
      new api.ApiError("API request failed: 409", 409, { reason_code: "LEGACY_SYMBOL_CONFLICT" }),
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Attiva ZTAA su XNAS" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Simbolo già attivo su un altro listing: attivazione bloccata.",
    );
  });
});

describe("catalog API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("encodes filters with URLSearchParams and sanitizes DEV fetch errors", async () => {
    const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(searchResult([])), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await actual.getInstruments({ q: "a&b c", quality_tier: undefined, limit: 50, offset: 0 });

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/instruments\?q=a%26b\+c&limit=50&offset=0$/);

    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const failure = await actual.getInstruments({ q: "secret-query" }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toContain("GET /instruments");
    expect((failure as Error).message).not.toContain("secret-query");
    expect((failure as Error).message).not.toContain("?");

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: { reason_code: "LISTING_NOT_RESOLVED" } }), { status: 409 }),
    );
    const conflict = await actual.activateListing(5).catch((error: unknown) => error);
    expect(conflict).toBeInstanceOf(actual.ApiError);
    expect((conflict as api.ApiError).status).toBe(409);
    expect((conflict as api.ApiError).detail).toEqual({ reason_code: "LISTING_NOT_RESOLVED" });
    expect(String(fetchMock.mock.calls[2][0])).toMatch(/\/assets\/from-listing\/5$/);
  });

  it("keeps the Phase 1 guidance for stale import and allocation conflicts", async () => {
    const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
    const fetchMock = vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify({ detail: { reason_code: "RESOLUTION_CHANGED" } }), { status: 409 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const importConflict = await actual
      .apiPost("/import/google-sheets/apply", { confirmation_token: "a".repeat(64) })
      .catch((error: unknown) => error);
    const allocationConflict = await actual
      .apiPost("/allocation/apply", { confirmation_token: "b".repeat(64) })
      .catch((error: unknown) => error);

    for (const conflict of [importConflict, allocationConflict]) {
      expect(conflict).toBeInstanceOf(actual.ApiError);
      expect((conflict as api.ApiError).message).not.toContain("API request failed");
      expect((conflict as api.ApiError).message).toContain("nuova anteprima");
      expect((conflict as api.ApiError).message).toContain("ricalcola");
      expect(actual.apiReasonCode(conflict)).toBe("RESOLUTION_CHANGED");
    }
  });
});
