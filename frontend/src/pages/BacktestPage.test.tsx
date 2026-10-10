import { Component, type ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BacktestPage } from "./BacktestPage";

vi.mock("recharts", () => {
  const Chart = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return Object.fromEntries(["Area", "AreaChart", "CartesianGrid", "Legend", "Line", "LineChart",
    "ResponsiveContainer", "Tooltip", "XAxis", "YAxis"].map((name) => [name, Chart]));
});

class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p>PAGE_CRASHED</p> : this.props.children; }
}

const summary = {
  id: 7, name: "Run salvato", strategy_name: "BUY_AND_HOLD", initial_cash: 10000,
  start_date: "2025-01-01", end_date: "2026-05-15", benchmark_symbol: "SPY",
  buy_threshold: 70, sell_threshold: 40, max_asset_weight: 0.15, fee_percent: null,
  stop_loss_percent: null, take_profit_percent: null, rebalance_frequency: "WEEKLY",
  total_return_percent: 12.34, cagr: 10, max_drawdown: -4, sharpe_ratio: 1.2, win_rate: 50,
  profit_factor: 1.5, total_trades: 2, final_value: 11234, benchmark_return_percent: 3,
  alpha_vs_benchmark: 9.34, created_at: "2026-10-10T10:00:00", engine_version: "v1",
  data_mode: "REAL", signal_name: "score", signal_timeframe: "D", cost_profile: null,
  warnings: [], excluded: {}, commission_eur: 2, spread_cost_eur: 1, turnover: 0.5,
  exposure: 0.5, fingerprint: "f".repeat(64), benchmark_snapshot_status: "FROZEN",
};
const detail = {
  backtest_id: 7, summary, equity_curve: [], trades: [], final_positions: [],
  benchmark_comparison: { benchmark_symbol: "SPY", benchmark_return_percent: 3,
    alpha_vs_benchmark: 9.34, benchmark_final_value: 10300 }, net_analysis: null,
};
const comparison = {
  name: "Confronto", start_date: summary.start_date, end_date: summary.end_date,
  benchmark_symbol: "SPY", benchmark_return_percent: 3, best_strategy: "BUY_AND_HOLD",
  entries: [{ strategy_name: "BUY_AND_HOLD", label: "Buy & hold", rank: 1, summary, equity_curve: [] }],
};
const walk = {
  strategy_name: "BUY_AND_HOLD", data_mode: "DEMO", window_is_sessions: 40, window_oos_sessions: 20,
  windows: [{ index: 0, is_start: "2025-01-01", is_end: "2025-02-28",
    oos_start: "2025-03-03", oos_end: "2025-03-28",
    chosen: { name: "BUY_AND_HOLD", buy_threshold: 70, sell_threshold: 40,
      max_asset_weight: 0.15, top_n: 5, rebalance_frequency: "WEEKLY" }, is_sharpe: null }],
  grid_size: 1, is_sharpe_mean: null, oos_sharpe: null, degradation: null,
  oos_metrics: { ...summary, start_date: "2025-03-03", end_date: "2025-03-28" },
  oos_sessions: 20, dsr: null, n_trials: null, excluded: {}, warnings: ["Run DEMO: nessun DSR."],
};
function job(status: string, overrides: Record<string, unknown> = {}) {
  return { id: 11, kind: "BACKTEST", status, params: {}, progress: 0,
    result_ref: null, result: null, error_code: null, error_message: null, cancel_requested: false,
    created_at: "2026-10-10T10:00:00Z", started_at: null, finished_at: null, ...overrides };
}
function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}
const fetchMock = vi.fn<typeof fetch>();
let handler: (path: string, init?: RequestInit) => Response | Promise<Response>;
beforeEach(() => {
  fetchMock.mockReset();
  handler = (path) => {
    if (path === "/assets") return response([{ id: 1, symbol: "AAPL", name: "Apple", asset_type: "stock" }]);
    if (path === "/backtests") return response([]);
    if (path === "/backtests/7") return response(detail);
    throw new Error("UNEXPECTED_OFFLINE_REQUEST " + path);
  };
  fetchMock.mockImplementation(async (input, init) => handler(new URL(String(input)).pathname, init));
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "error").mockImplementation(() => undefined); // Boundary rende visibile ogni crash.
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
async function mount() {
  const view = render(<Boundary><BacktestPage /></Boundary>);
  await screen.findByRole("button", { name: "Esegui backtest" });
  return view;
}
async function flush() { await act(async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); }); }
async function tick() { await act(async () => { await vi.advanceTimersByTimeAsync(1000); }); }
function route(extra: typeof handler) {
  const base = handler;
  handler = (path, init) => path.startsWith("/lab/jobs") || init?.method === "POST"
    ? extra(path, init) : base(path, init);
}

describe("Backtest: contratti asincroni offline", () => {
  it("attende QUEUED e RUNNING, poi carica il riferimento BACKTEST senza doppio invio", async () => {
    let polls = 0;
    route((path) => path === "/backtests/run"
      ? response(job("QUEUED"), 202)
      : response(++polls === 1 ? job("RUNNING", { progress: 0.25 })
        : job("SUCCEEDED", { progress: 1, result_ref: "7", result: { backtest_id: 7 } })));
    await mount();
    vi.useFakeTimers();
    const submit = screen.getByRole("button", { name: "Esegui backtest" });
    fireEvent.click(submit);
    fireEvent.submit(submit.closest("form")!);
    await flush();
    expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
    expect(screen.getByText(/Accodato/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Esecuzione..." })).toBeDisabled();
    await tick();
    expect(screen.getByText(/25%/)).toBeInTheDocument();
    await tick();
    expect(screen.getByText("+12.34%")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    const sent = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")![1]!.body));
    expect(sent).not.toHaveProperty("fee_percent");
  });

  it("legge COMPARE dal risultato inline anche se il POST è già SUCCEEDED", async () => {
    route(() => response(job("SUCCEEDED", { kind: "COMPARE", progress: 1, result: comparison }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Confronto" }));
    fireEvent.click(screen.getByRole("button", { name: "Confronta strategie" }));
    await flush();
    expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
    expect(screen.getAllByText("Buy & hold").length).toBeGreaterThan(0);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/lab/jobs"))).toHaveLength(0);
  });

  it("legge finestre e metriche WFO con Sharpe, DSR e N nulli", async () => {
    route(() => response(job("SUCCEEDED", { kind: "WALK_FORWARD", progress: 1, result: walk }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Robustezza" }));
    fireEvent.click(screen.getByRole("button", { name: "Valida robustezza" }));
    await flush();
    expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
    expect(screen.getByText("Finestre walk-forward")).toBeInTheDocument();
    expect(screen.getByText("2025-03-03 → 2025-03-28")).toBeInTheDocument();
    expect(screen.getAllByText("N/D").length).toBeGreaterThanOrEqual(3);
    const sent = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")![1]!.body));
    expect(sent).not.toHaveProperty("folds");
    expect(sent.is_sessions).toBe(504);
    expect(sent.oos_sessions).toBe(126);
  });

  it.each([
    ["FAILED", "Universo vuoto.", { error_code: "LAB_EMPTY_UNIVERSE", error_message: "Universo vuoto." }],
    ["CANCELLED", "Elaborazione annullata.", {}],
    ["INTERRUPTED", "Elaborazione interrotta", {}],
  ])("gestisce il terminale %s e rende nuovamente disponibile il form", async (status, text, extras) => {
    route(() => response(job(status, extras), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
    expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Esegui backtest" })).toBeEnabled();
  });

  it("spiega il 409 del controllo preventivo e non avvia polling", async () => {
    route(() => response({ detail: { reason_code: "LAB_NO_REAL_SERIES",
      message: "Nessun asset selezionato ha una serie reale." } }, 409));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    expect(screen.getByText("Nessun asset selezionato ha una serie reale.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/lab/jobs"))).toHaveLength(0);
  });

  it("attende la conferma CANCELLED dopo una richiesta cooperativa", async () => {
    route((path) => path === "/backtests/run" ? response(job("RUNNING"), 202)
      : path.endsWith("/cancel") ? response(job("RUNNING", { cancel_requested: true }))
        : response(job("CANCELLED")));
    await mount();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Annulla elaborazione" }));
    await flush();
    expect(screen.getByText(/Annullamento richiesto/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Esecuzione..." })).toBeDisabled();
    await tick();
    expect(screen.getByText("Elaborazione annullata.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Esegui backtest" })).toBeEnabled();
  });

  it("interrompe POST pendente allo smontaggio senza inviare cancel al backend", async () => {
    let resolve!: (value: Response) => void;
    route(() => new Promise<Response>((done) => { resolve = done; }));
    const view = await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    const signal = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")![1]?.signal;
    view.unmount();
    resolve(response(job("QUEUED"), 202));
    await flush();
    expect(signal?.aborted).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/cancel"))).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/lab/jobs"))).toBe(false);
  });

  it.each([
    ["Confronto", "Confronta strategie", "COMPARE", comparison, "Buy & hold"],
    ["Robustezza", "Valida robustezza", "WALK_FORWARD", walk, "Finestre walk-forward"],
  ])("attende il job accodato anche per %s", async (tab, action, kind, inline, label) => {
    route((path) => path.startsWith("/backtests/")
      ? response(job("QUEUED", { kind }), 202)
      : response(job("SUCCEEDED", { kind, result: inline, progress: 1 })));
    await mount();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: String(tab) }));
    fireEvent.click(screen.getByRole("button", { name: String(action) }));
    await flush();
    expect(screen.getByText(/Accodato/)).toBeInTheDocument();
    await tick();
    expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
    expect(screen.getAllByText(String(label)).length).toBeGreaterThan(0);
  });

  it("mostra un errore del polling e sblocca il form", async () => {
    route((path) => {
      if (path === "/backtests/run") return response(job("QUEUED"), 202);
      throw new Error("Connessione interrotta");
    });
    await mount();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    await tick();
    expect(screen.getByText(/Connessione interrotta/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Esegui backtest" })).toBeEnabled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("interrompe il GET pendente allo smontaggio e ignora il terminale tardivo", async () => {
    let resolve!: (value: Response) => void;
    route((path) => path === "/backtests/run" ? response(job("QUEUED"), 202)
      : new Promise<Response>((done) => { resolve = done; }));
    const view = await mount();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    await tick();
    const signal = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/lab/jobs/11"))![1]?.signal;
    view.unmount();
    resolve(response(job("SUCCEEDED", { result_ref: "7" })));
    await flush();
    expect(signal?.aborted).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/backtests/7"))).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/cancel"))).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("mostra DSR REAL come probabilita percentuale e invia stop/target vuoti come null", async () => {
    const real = { ...walk, data_mode: "REAL", is_sharpe_mean: 1.5, oos_sharpe: 1.1, degradation: 0.4,
      dsr: { dsr: 0.956, n_trials: 4 }, n_trials: 4, warnings: [] };
    route(() => response(job("SUCCEEDED", { kind: "WALK_FORWARD", result: real }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Robustezza" }));
    fireEvent.change(screen.getByLabelText("Stop loss %"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Take profit %"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Valida robustezza" }));
    await flush();
    expect(screen.getByText("95.6%")).toBeInTheDocument();
    expect(screen.getByText("1.50")).toBeInTheDocument();
    const sent = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")![1]!.body));
    expect(sent.stop_loss_percent).toBeNull();
    expect(sent.take_profit_percent).toBeNull();
  });

  it("non applica il cancel tardivo di un run gia concluso a un nuovo job", async () => {
    let resolveCancel!: (value: Response) => void;
    let posts = 0;
    route((path) => {
      if (path === "/backtests/run") return response(job("RUNNING", { id: ++posts === 1 ? 11 : 12 }), 202);
      if (path.endsWith("/cancel")) return new Promise<Response>((done) => { resolveCancel = done; });
      if (path.endsWith("/11")) return response(job("SUCCEEDED", { result_ref: "7" }));
      return response(job("RUNNING", { id: 12 }));
    });
    await mount();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Annulla elaborazione" }));
    await flush();
    await tick();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    resolveCancel(response(job("CANCELLED")));
    await flush();
    expect(screen.getByText(/In esecuzione/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Annulla elaborazione" })).toBeEnabled();
  });

  it.each(["v0", "v1"])("rispetta le unita monetarie del dettaglio %s senza conversioni implicite", async (version) => {
    const monetary = { ...detail, summary: { ...summary, engine_version: version },
      trades: [{ date: "2025-01-02", symbol: "AAPL", order_type: "BUY", quantity: 1,
        price: 100, gross_amount: 100, fee_amount: 1, net_amount: 101, pnl: 10, reason: "test",
        commission: null, spread_cost: null }],
      final_positions: [{ symbol: "AAPL", quantity: 1, average_price: 100, final_price: 110,
        final_value: 110, unrealized_pnl: 10, realized_pnl: 0 }] };
    const base = handler;
    handler = (path, init) => path === "/backtests/7" ? response(monetary) : base(path, init);
    route(() => response(job("SUCCEEDED", { result_ref: "7" }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    if (version === "v0") {
      expect(screen.getByText(/Run storico v0: unita monetaria non dichiarata/)).toBeInTheDocument();
      expect(screen.getAllByText("100,00 (unita legacy)").length).toBe(2);
      expect(screen.queryByText(/100.*€/)).not.toBeInTheDocument();
    } else {
      expect(screen.queryByText(/Run storico v0:/)).not.toBeInTheDocument();
      expect(screen.getAllByText(/100.*€/).length).toBe(2);
    }
  });
});
