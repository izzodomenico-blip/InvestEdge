import { type ReactNode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnalysisPage } from "./AnalysisPage";

vi.mock("recharts", () => {
  const Chart = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return Object.fromEntries(["Line", "LineChart", "ResponsiveContainer", "Tooltip", "XAxis", "YAxis"]
    .map((name) => [name, Chart]));
});
vi.mock("../components/TradeButton", () => ({ TradeButton: () => null }));
const assets = [{ id: 1, symbol: "AAPL", name: "Apple", currency: "USD", asset_type: "stock" },
  { id: 2, symbol: "MSFT", name: "Microsoft", currency: "USD", asset_type: "stock" }];
function analysis(symbol = "AAPL", overrides: Record<string, unknown> = {}) {
  return { asset: assets.find((asset) => asset.symbol === symbol), latest_price: 100,
    indicators: { rsi_14: 55, macd_line: 1.23, atr_14: 2.34, adx_14: 25,
      volatility_30d: 0.235, max_drawdown_252: -0.184 },
    conditions: {}, support_resistance: { nearest_support: null, nearest_resistance: null,
      support_distance_percent: null, resistance_distance_percent: 2.5 },
    subscores: { trend_score: 65 }, score: 65, technical_score: 65, news_score: 3,
    final_score: 65, news_sentiment_label: "POSITIVE", news_impact_level: "LOW", signal: "HOLD",
    risk_level: "medium", confidence: "media", reasons: [], summaries: {},
    technical_summary: "Analisi di " + symbol, data_mode: "REAL", ...overrides };
}
function prices(symbol = "AAPL") {
  return { symbol, name: symbol, currency: "USD", asset_type: "stock",
    prices: [{ date: "2026-10-09", close: 100, is_real_data: false, source: "mock", provider: null }] };
}
function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}
const fetchMock = vi.fn<typeof fetch>();
let handler: (path: string, init?: RequestInit) => Response | Promise<Response>;
beforeEach(() => {
  fetchMock.mockReset();
  handler = (path) => {
    if (path === "/assets") return response(assets);
    if (path.startsWith("/prices/")) return response(prices(path.split("/").slice(-1)[0]));
    if (path.startsWith("/technical-analysis/")) return response(analysis(path.split("/").slice(-1)[0]));
    if (path === "/news/status") return response({ enable_real_news: false });
    if (path.startsWith("/news/sentiment/")) return response({ latest_news: [] });
    throw new Error("UNEXPECTED_OFFLINE_REQUEST " + path);
  };
  fetchMock.mockImplementation(async (input, init) => handler(new URL(String(input)).pathname, init));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
function mount() {
  return render(<MemoryRouter initialEntries={["/analysis?symbol=AAPL"]}><AnalysisPage /></MemoryRouter>);
}
function card(label: string) { return within(screen.getByText(label).parentElement!); }

describe("Analisi: indicatori features-v1 offline", () => {
  it("usa nomi, finestre e unità correnti, senza trasformare i null in N/D%", async () => {
    mount();
    await screen.findByText("Analisi di AAPL");
    expect(card("Volatilità annualizzata · 30 barre").getByText("23.5%")).toBeInTheDocument();
    expect(card("Max drawdown · 252 barre").getByText("-18.4%")).toBeInTheDocument();
    expect(card("MACD (USD)").getByText("1.23")).toBeInTheDocument();
    expect(card("ATR 14 (USD)").getByText("2.34")).toBeInTheDocument();
    expect(card("Distanza supporto").getByText("N/D")).toBeInTheDocument();
    expect(card("Distanza resistenza").getByText("2.50%")).toBeInTheDocument();
    expect(screen.queryByText("N/D%")).not.toBeInTheDocument();
  });

  it("distingue modalità REAL del calcolo dallo storico prezzi DEMO e dichiara news informative", async () => {
    mount();
    await screen.findByText("Analisi di AAPL");
    expect(screen.getByText("Calcolo tecnico: REAL")).toBeInTheDocument();
    expect(screen.queryByText(/Stai usando dati seed\/demo per questo asset/)).not.toBeInTheDocument();
    expect(screen.getByText("News informative: non modificano lo score tecnico.")).toBeInTheDocument();
    expect(screen.queryByText("Score tecnico + news")).not.toBeInTheDocument();
  });

  it("spiega INSUFFICIENT_REAL_HISTORY con barre disponibili/richieste e non inventa score", async () => {
    const base = handler;
    handler = (path, init) => path.startsWith("/technical-analysis/")
      ? response({ detail: { reason_code: "INSUFFICIENT_REAL_HISTORY",
        message: "Storico reale insufficiente (120 barre, servono 252)." } }, 409) : base(path, init);
    mount();
    expect(await screen.findByText("Storico reale insufficiente (120 barre, servono 252).")).toBeInTheDocument();
    expect(screen.queryByText("65.0/100")).not.toBeInTheDocument();
  });

  it("non usa la risposta ritardata del simbolo precedente", async () => {
    let resolve!: (value: Response) => void;
    const base = handler;
    handler = (path, init) => path === "/technical-analysis/AAPL"
      ? new Promise<Response>((done) => { resolve = done; }) : base(path, init);
    mount();
    await screen.findByRole("combobox");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "MSFT" } });
    await screen.findByText("Analisi di MSFT");
    await act(async () => { resolve(response(analysis("AAPL"))); });
    expect(screen.queryByText("Analisi di AAPL")).not.toBeInTheDocument();
    expect(screen.getByText("Analisi di MSFT")).toBeInTheDocument();
    const oldSignal = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/technical-analysis/AAPL"))![1]?.signal;
    expect(oldSignal?.aborted).toBe(true);
  });

  it("interrompe le richieste allo smontaggio", async () => {
    const base = handler;
    handler = (path, init) => path.startsWith("/technical-analysis/")
      ? new Promise<Response>(() => undefined) : base(path, init);
    const view = mount();
    await screen.findByRole("combobox");
    const signal = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/technical-analysis/AAPL"))![1]?.signal;
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
