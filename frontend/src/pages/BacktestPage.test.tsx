import { Component, type ReactNode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
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
  vi.stubEnv("TZ", "Europe/Rome");
  fetchMock.mockReset();
  handler = (path) => {
    if (path === "/assets") return response([{ id: 1, symbol: "AAPL", name: "Apple", asset_type: "stock" }]);
    if (path === "/lab/signals") return response(["score", "rsi_14"]);
    if (path === "/backtests") return response([]);
    if (path === "/backtests/7") return response(detail);
    throw new Error("UNEXPECTED_OFFLINE_REQUEST " + path);
  };
  fetchMock.mockImplementation(async (input, init) => handler(new URL(String(input)).pathname, init));
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "error").mockImplementation(() => undefined); // Boundary rende visibile ogni crash.
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
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

describe("Backtest: laboratorio, costi ed evidenza delle finestre", () => {
  it("invia REAL e i default configurati senza inventare il profilo costi", async () => {
    route(() => response(job("SUCCEEDED", { result_ref: "7" }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    const sent = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")![1]!.body));
    expect(sent).toMatchObject({ data_mode: "REAL", signal_name: "score", signal_timeframe: "D",
      commission_eur: null, cost_bps_equity: null, cost_bps_crypto: null,
      min_trade_eur: null, fractional_shares: null });
    expect(screen.getByText("Esecuzione all'apertura della barra successiva")).toBeInTheDocument();
    expect(screen.getByText(/11.234,00.*€/)).toBeInTheDocument();
  });

  it.each([
    ["Singolo", "Esegui backtest", "BACKTEST", null],
    ["Confronto", "Confronta strategie", "COMPARE", comparison],
    ["Robustezza", "Valida robustezza", "WALK_FORWARD", walk],
  ])("invia lo stesso profilo esplicito e segnale del catalogo in %s", async (tab, action, kind, inline) => {
    route(() => response(job("SUCCEEDED", { kind, result_ref: inline ? null : "7", result: inline }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: String(tab) }));
    fireEvent.change(screen.getByLabelText("Modalità dati"), { target: { value: "DEMO" } });
    fireEvent.change(screen.getByLabelText("Segnale"), { target: { value: "rsi_14" } });
    fireEvent.change(screen.getByLabelText("Timeframe del segnale"), { target: { value: tab === "Robustezza" ? "M" : "W" } });
    for (const [label, value] of [["Commissione per ordine (€)", "0"], ["Costo azioni / ETF (bps per lato)", "12"],
      ["Costo crypto (bps per lato)", "60"], ["Ordine minimo (€)", "25"]]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.change(screen.getByLabelText("Quote azioni / ETF"), { target: { value: tab === "Confronto" ? "false" : "true" } });
    fireEvent.click(screen.getByRole("button", { name: String(action) }));
    await flush();
    const sent = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === "POST")![1]!.body));
    expect(sent).toMatchObject({ data_mode: "DEMO", signal_name: "rsi_14", signal_timeframe: tab === "Robustezza" ? "M" : "W",
      commission_eur: 0, cost_bps_equity: 12, cost_bps_crypto: 60, min_trade_eur: 25, fractional_shares: tab !== "Confronto" });
    expect(sent).not.toHaveProperty("fee_percent");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/lab/signals"))).toHaveLength(1);
    expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
  });

  it.each([["Commissione per ordine (€)", "-1"], ["Commissione per ordine (€)", "101"],
    ["Costo crypto (bps per lato)", "1001"], ["Ordine minimo (€)", "1000001"]])(
    "blocca %s fuori contratto (%s) anche se il form viene inviato direttamente", async (label, value) => {
      await mount();
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
      fireEvent.submit(screen.getByRole("button", { name: "Esegui backtest" }).closest("form")!);
      await flush();
      expect(screen.getByRole("alert")).toHaveTextContent(/Profilo costi non valido/);
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    });

  it("rende storico e errori visibili se il catalogo segnali è indisponibile", async () => {
    const base = handler;
    handler = (path, init) => path === "/lab/signals" ? response({ detail: "Catalogo non disponibile" }, 503)
      : path === "/backtests" ? response([summary]) : base(path, init);
    await mount();
    expect(screen.getByRole("alert")).toHaveTextContent(/Catalogo non disponibile/);
    expect(screen.getByRole("button", { name: "Esegui backtest" })).toBeDisabled();
    expect(screen.getByText("Run salvato")).toBeInTheDocument();
    expect(screen.getByText(/11.234,00.*€/)).toBeInTheDocument();
  });

  it("mostra costi registrati, profilo, turnover, esclusi e DEMO dal risultato salvato", async () => {
    const recorded = { ...detail, summary: { ...summary, data_mode: "DEMO", signal_name: "rsi_14",
      signal_timeframe: "M", commission_eur: 2, spread_cost_eur: 13.5, turnover: 1.25,
      warnings: ["Cambio mancante: barra esclusa."], excluded: { XYZ: "NO_FEATURES" },
      cost_profile: { commission_eur: 1, cost_bps_equity: 10, cost_bps_crypto: 50,
        min_trade_eur: 25, fractional_shares: false } },
      trades: [{ id: 1, date: "2025-01-02", symbol: "AAPL", order_type: "BUY", quantity: 1,
        price: 100, gross_amount: 100, fees: 1, net_amount: 101, pnl: 0, reason: "SIGNAL",
        commission: 1, spread_cost: 0.1 }] };
    const base = handler;
    handler = (path, init) => path === "/backtests/7" ? response(recorded) : base(path, init);
    route(() => response(job("SUCCEEDED", { result_ref: "7" }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    expect(within(screen.getByText("Costi ed esclusioni").closest("section")!).getByText("DEMO · simulazione")).toBeInTheDocument();
    expect(screen.getByText("rsi_14 · M")).toBeInTheDocument();
    expect(screen.getByText("1,25×")).toBeInTheDocument();
    expect(screen.getByText(/13,50.*€/)).toBeInTheDocument();
    expect(screen.getByText(/0,10.*€/)).toBeInTheDocument();
    expect(screen.getByText("Cambio mancante: barra esclusa.")).toBeInTheDocument();
    expect(screen.getByText("XYZ")).toBeInTheDocument();
    expect(screen.getByText("NO_FEATURES")).toBeInTheDocument();
    expect(screen.getByText(/10 bps.*50 bps/)).toBeInTheDocument();
  });

  it("distingue le deduzioni fiscali dai costi di esecuzione v1 già inclusi", async () => {
    const taxed = { ...detail, net_analysis: { gross_return_percent: 12.34, gross_profit: 1234,
      commission_costs: 2, slippage_costs: 13.5, realized_gains_taxable: 100,
      capital_gains_tax: 26, stamp_duty: 20, total_costs_and_taxes: 46, net_final_value: 11188,
      net_return_percent: 11.88, effective_tax_rate_percent: 26, notes: [] } };
    const base = handler;
    handler = (path, init) => path === "/backtests/7" ? response(taxed) : base(path, init);
    route(() => response(job("SUCCEEDED", { result_ref: "7" }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    const spreadRow = screen.getByText("Spread / slippage (già incluso)").closest("tr")!;
    expect(spreadRow).toHaveTextContent(/13,50.*€/);
    expect(spreadRow).not.toHaveTextContent("- ");
    expect(screen.getByText("Totale imposte stimate").closest("tr")).toHaveTextContent(/46,00.*€/);
    expect(screen.getByText("Rendimento prima delle imposte")).toBeInTheDocument();
  });

  it("etichetta lo storico v0 e non presenta costi assenti come zero", async () => {
    const legacy = { ...summary, engine_version: "v0", data_mode: null, cost_profile: null,
      commission_eur: null, spread_cost_eur: null, turnover: null };
    const base = handler;
    handler = (path, init) => path === "/backtests" ? response([legacy])
      : path === "/backtests/7" ? response({ ...detail, summary: legacy }) : base(path, init);
    await mount();
    expect(screen.getAllByText("motore precedente").length).toBeGreaterThan(0);
    expect(screen.getByText("Costi per voce non registrati dal motore precedente.")).toBeInTheDocument();
    expect(screen.queryByText("0,00 €")).not.toBeInTheDocument();
  });

  it("mostra costi e limiti separati per strategia nel confronto", async () => {
    const compared = { ...comparison, entries: [{ ...comparison.entries[0], summary: { ...summary,
      warnings: ["Benchmark non disponibile."], excluded: { XYZ: "NO_FX" } } }] };
    route(() => response(job("SUCCEEDED", { kind: "COMPARE", result: compared }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Confronto" }));
    fireEvent.click(screen.getByRole("button", { name: "Confronta strategie" }));
    await flush();
    expect(screen.getByText("Confronto senza correzione per i tentativi: per l'evidenza usa il walk-forward")).toBeInTheDocument();
    expect(screen.getByText("Benchmark non disponibile.")).toBeInTheDocument();
    expect(screen.getByText("NO_FX")).toBeInTheDocument();
    expect(screen.getByText("Costi ed esclusioni · Buy & hold")).toBeInTheDocument();
  });

  it("completa WFO con peso scelto, DSR/N, costi OOS e asset esclusi", async () => {
    const real = { ...walk, data_mode: "REAL", is_sharpe_mean: 1.5, oos_sharpe: 1.1,
      degradation: 0.4, dsr: { dsr: 0.956, n_trials: 4 }, n_trials: 4,
      windows: [{ ...walk.windows[0], is_sharpe: 1.75,
        chosen: { ...walk.windows[0].chosen, max_asset_weight: 0.25 } }],
      excluded: { ABC: "SEGMENT_TOO_SHORT" }, warnings: ["Calendari misti."],
      oos_metrics: { ...walk.oos_metrics, commission_eur: 12, spread_cost_eur: 3.5, turnover: 2.5 } };
    route(() => response(job("SUCCEEDED", { kind: "WALK_FORWARD", result: real }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Robustezza" }));
    fireEvent.click(screen.getByRole("button", { name: "Valida robustezza" }));
    await flush();
    expect(screen.getByText(/peso max \+25/)).toBeInTheDocument();
    expect(screen.getByText("95.6%")).toBeInTheDocument();
    expect(screen.getByText("1.75")).toBeInTheDocument();
    expect(screen.getByText("N configurazioni").nextElementSibling).toHaveTextContent("4");
    expect(screen.getByText(/12,00.*€/)).toBeInTheDocument();
    expect(screen.getByText("2,50×")).toBeInTheDocument();
    expect(screen.getByText("SEGMENT_TOO_SHORT")).toBeInTheDocument();
    expect(screen.getByText("Calendari misti.")).toBeInTheDocument();
  });

  it.each(["precheck", "job"])("guida LAB_NO_REAL_SERIES da %s conservando il messaggio", async (source) => {
    route(() => source === "precheck"
      ? response({ detail: { reason_code: "LAB_NO_REAL_SERIES", message: "Nessuna serie REAL." } }, 409)
      : response(job("FAILED", { error_code: "LAB_NO_REAL_SERIES", error_message: "Nessuna serie REAL." }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent(/Nessuna serie REAL/);
    expect(screen.getByRole("alert")).toHaveTextContent(/dati reali.*DEMO/i);
  });

  it("guida l'estensione del periodo per LAB_PERIOD_TOO_SHORT", async () => {
    route(() => response({ detail: { reason_code: "LAB_PERIOD_TOO_SHORT", message: "Periodo corto." } }, 409));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Robustezza" }));
    fireEvent.click(screen.getByRole("button", { name: "Valida robustezza" }));
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent(/Estendi il periodo.*finestre/i);
  });
});

describe("Backtest: unità e disponibilità delle misure", () => {
  it("mostra exposure come percentuale e costo zero distinto da N/D", async () => {
    const base = handler;
    handler = (path, init) => path === "/backtests/7" ? response({ ...detail,
      summary: { ...summary, exposure: 0.4, commission_eur: 0, spread_cost_eur: null } }) : base(path, init);
    route(() => response(job("SUCCEEDED", { result_ref: "7" }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    expect(screen.getByText("Esposizione media").nextElementSibling).toHaveTextContent("+40.00%");
    expect(screen.getByText("Commissioni eseguite").nextElementSibling).toHaveTextContent(/0,00.*€/);
    expect(screen.getByText("Spread / slippage eseguito").nextElementSibling).toHaveTextContent("N/D");
  });

  it.each([0, 27])("mantiene N=%s disponibile anche senza DSR, indipendente dalla griglia", async (n) => {
    const real = { ...walk, data_mode: "REAL", dsr: null, n_trials: n, grid_size: 6,
      is_sharpe_mean: 1.1, oos_sharpe: 1.5, degradation: -0.4, windows: [walk.windows[0], { ...walk.windows[0], index: 1,
        is_start: "2025-02-03", is_sharpe: 1.23, chosen: { ...walk.windows[0].chosen, top_n: 8 } }] };
    route(() => response(job("SUCCEEDED", { kind: "WALK_FORWARD", result: real }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Robustezza" }));
    fireEvent.click(screen.getByRole("button", { name: "Valida robustezza" }));
    await flush();
    expect(screen.getByText("DSR").nextElementSibling).toHaveTextContent("N/D");
    expect(screen.getByText("N configurazioni").nextElementSibling).toHaveTextContent(String(n));
    expect(screen.getByText("Degrado IS − OOS").nextElementSibling).toHaveTextContent(/^-0\.40$/);
    expect(screen.getByText(/Top N 8/)).toBeInTheDocument();
    expect(screen.getByText("1.23")).toBeInTheDocument();
  });

  it("non spaccia l'alpha di fallback per misura quando manca il benchmark", async () => {
    const unavailable = { ...summary, benchmark_snapshot_status: "UNAVAILABLE", alpha_vs_benchmark: 0,
      warnings: ["Benchmark non disponibile."] };
    const base = handler;
    handler = (path, init) => path === "/backtests/7" ? response({ ...detail, summary: unavailable,
      benchmark_comparison: { ...detail.benchmark_comparison, alpha_vs_benchmark: 0 } }) : base(path, init);
    route(() => response(job("SUCCEEDED", { result_ref: "7" }), 202));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
    await flush();
    expect(screen.getByText("Alpha benchmark").closest("div")!.parentElement).toHaveTextContent("N/D");
    expect(screen.getByText("Benchmark non disponibile.")).toBeInTheDocument();
  });
});

it("non conserva la guida REAL/DEMO quando fallisce una successiva apertura dello storico", async () => {
  let reads = 0;
  const base = handler;
  handler = (path, init) => path === "/backtests" ? response([summary])
    : path === "/backtests/7" ? ++reads === 1 ? response(detail) : response({ detail: "Storico non disponibile." }, 500)
      : path === "/backtests/run" ? response(job("FAILED", { error_code: "LAB_NO_REAL_SERIES", error_message: "Nessuna serie REAL." }), 202)
        : base(path, init);
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "Esegui backtest" }));
  await flush();
  expect(screen.getByRole("alert")).toHaveTextContent(/Carica dati reali/);
  fireEvent.click(screen.getByRole("button", { name: "Run salvato" }));
  await flush();
  expect(screen.getByRole("alert")).toHaveTextContent("Storico non disponibile.");
  expect(screen.getByRole("alert")).not.toHaveTextContent(/Carica dati reali/);
});

const evidenceReport = {"id":21,"job_id":11,"signal_name":"score","timeframe":"D","horizon":5,"verdict":"NON_VALIDATO","fingerprint":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff","created_at":"2026-10-10T10:00:00Z","metrics":{"horizon":5,"ic_dates":300,"ic_mean":0.02,"ic_std":0.1,"ic_ir":0.2,"ic_positive_share":0.6,"t_nw":1.1,"mean_names":12,"bucket_count":5,"bucket_returns":[-0.02,0,0.01,0.02,0.03],"spread_gross":0.05,"spread_net":0.04,"turnover_top":0.25,"rank_autocorr":0.8},"walk_forward":{"oos_sessions":260,"oos_observations":259,"windows":[{"index":0,"is_start":"2024-01-01","is_end":"2024-12-31","oos_start":"2025-01-02","oos_end":"2025-06-30","chosen":{"name":"TOP_N_SCORE","buy_threshold":70,"sell_threshold":40,"max_asset_weight":0.15,"top_n":5,"rebalance_frequency":"WEEKLY"},"is_sharpe":0.08}],"grid_size":3,"oos_sharpe_daily":0.04,"is_sharpe_mean_daily":0.08,"degradation_daily":0.04,"oos_metrics":{"total_return_percent":5,"cagr":5,"max_drawdown":-2,"sharpe_ratio":0.635,"profit_factor":1.2,"win_rate":50,"total_trades":4,"final_value_eur":10500.12},"units":{"sharpe":"daily"},"dsr":{"dsr":0.3,"sr":0.04,"sr0":0.05,"n_trials":7,"n_obs":259,"skew":0,"kurtosis":3},"n_trials":7,"trial_sharpes":[0.02,0.04],"costs":{"commission_eur":4,"spread_cost_eur":2.35},"turnover":0.4,"exposure":0.7},"config":{"data_mode":"REAL","versions":{"pipeline":"features-v1","evidence":"v1"},"thresholds":{"min_ic_dates":252,"min_dsr":0.95},"costs":{"commission_eur":1,"cost_bps_equity":5,"cost_bps_crypto":15,"min_trade_eur":10,"fractional_shares":true},"request":{"start_date":"2024-01-01","end_date":"2026-01-01"}},"universe":{"assets":[{"asset_id":1,"symbol":"AAPL","asset_type":"stock"}],"excluded":{"MISSING":"FX mancanti"},"inputs_hash":"hash"},"limits":{"survivorship_bias":"Universo corrente, survivorship bias.","validation_scope":"D/W/M e orizzonti in sedute; non valida intraday 15-30 minuti.","diagnostic_spread":"Spread diagnostico; non eseguibile short.","fx_excluded_bars":{"AAPL":2}}};
describe("Backtest modalità Evidenza offline", () => {
 function evidenceRoute(extra: typeof handler) {
   const base=handler; handler=(p,i)=>p.startsWith("/lab/evidence")||p.startsWith("/lab/jobs")?extra(p,i):base(p,i);
 }
 async function submitEvidence() { await mount();fireEvent.click(screen.getByRole("button",{name:"Evidenza"})); }
 it("accoda, polla, carica report_ids e rende verdetto, unità e limiti",async()=>{
  let polls=0;evidenceRoute(p=>p==="/lab/evidence"?response(job("QUEUED",{kind:"EVIDENCE"}),202):
   p==="/lab/evidence/21"?response(evidenceReport):response(++polls===1?job("RUNNING",{kind:"EVIDENCE",progress:.4}):job("SUCCEEDED",{kind:"EVIDENCE",result:{report_ids:[21]}})));
  await submitEvidence();vi.useFakeTimers();fireEvent.click(screen.getByRole("button",{name:"Valuta evidenza"}));await flush();
  expect(screen.getByText(/Accodato/)).toBeInTheDocument();await tick();expect(screen.getByText(/40%/)).toBeInTheDocument();await tick();
  expect(screen.getByText("NON VALIDATO · 5g")).toBeInTheDocument();
  expect(screen.getAllByText(/non valida intraday 15-30 minuti/).length).toBeGreaterThan(0);
  expect(screen.getByText("MISSING")).toBeInTheDocument();expect(screen.getByText("FX mancanti")).toBeInTheDocument();
  const metric=(label:string)=>within(screen.getByText(label).parentElement!);
  expect(metric("Sharpe OOS giornaliero").getByText("0.040")).toBeInTheDocument();
  expect(metric("Sharpe OOS annualizzato").getByText("0.635")).toBeInTheDocument();
  expect(metric("Degrado IS/OOS").getByText("0.040")).toBeInTheDocument();
  expect(metric("Quota IC > 0").getByText("60.00%")).toBeInTheDocument();
  expect(metric("Spread netto").getByText("4.00%")).toBeInTheDocument();
  expect(metric("DSR").getByText("0.300")).toBeInTheDocument();expect(metric("Tentativi N").getByText("7")).toBeInTheDocument();
  const payload=JSON.parse(String(fetchMock.mock.calls.find(([url])=>String(url).endsWith("/lab/evidence"))![1]!.body));
  expect(Object.keys(payload).sort()).toEqual(["end_date","horizons","signal_name","start_date","timeframe"]);
  expect(payload.horizons).toEqual([1,5,21]);expect(payload.timeframe).toBe("D");
  expect(screen.queryByText("PAGE_CRASHED")).not.toBeInTheDocument();
 });
 it("invia simboli opzionali, timeframe e orizzonti, senza dati DEMO o costi",async()=>{
  evidenceRoute(p=>p==="/lab/evidence"?response(job("SUCCEEDED",{kind:"EVIDENCE",result:{report_ids:[21]}}),202):response(evidenceReport));
  await submitEvidence();fireEvent.change(screen.getByLabelText("Simboli opzionali"),{target:{value:" aapl, MSFT, aapl "}});
  fireEvent.change(screen.getByLabelText("Timeframe del segnale"),{target:{value:"W"}});
  fireEvent.click(screen.getByLabelText("1 seduta"));fireEvent.click(screen.getByLabelText("21 sedute"));
  fireEvent.click(screen.getByRole("button",{name:"Valuta evidenza"}));await flush();
  const payload=JSON.parse(String(fetchMock.mock.calls.find(([url])=>String(url).endsWith("/lab/evidence"))![1]!.body));
  expect(payload).toMatchObject({symbols:["AAPL","MSFT"],timeframe:"W",horizons:[5]});
  expect(payload).not.toHaveProperty("data_mode");expect(payload).not.toHaveProperty("commission_eur");
  expect(screen.queryByLabelText("Modalità dati")).not.toBeInTheDocument();
 });
 it("carica tutti i report, incluso WFO nullo e metriche mancanti",async()=>{
  evidenceRoute(p=>p==="/lab/evidence"?response(job("SUCCEEDED",{kind:"EVIDENCE",result:{report_ids:[21,22]}}),202):
   response(p.endsWith("/22")?{...evidenceReport,id:22,horizon:21,verdict:"INSUFFICIENTE",walk_forward:null,
    metrics:{...evidenceReport.metrics,ic_mean:null,t_nw:null,spread_net:null}}:evidenceReport));
  await submitEvidence();fireEvent.click(screen.getByRole("button",{name:"Valuta evidenza"}));await flush();
  expect(screen.getByText("INSUFFICIENTE · 21g")).toBeInTheDocument();
  expect(screen.getByText("NON VALIDATO · 5g").title).not.toContain("21g: NON MISURATO");
  expect(screen.getAllByText("N/D").length).toBeGreaterThanOrEqual(3);
  expect(fetchMock.mock.calls.filter(([url])=>/evidence\/(21|22)$/.test(String(url)))).toHaveLength(2);
 });
 it.each([[],["../secret"],[0],[21.5]].map(ids => ({ ids })))("rifiuta riferimenti report non validi $ids",async({ ids })=>{
  evidenceRoute(()=>response(job("SUCCEEDED",{kind:"EVIDENCE",result:{report_ids:ids}}),202));
  await submitEvidence();fireEvent.click(screen.getByRole("button",{name:"Valuta evidenza"}));await flush();
  expect(screen.getByRole("alert")).toHaveTextContent("Riferimenti report non validi");
  expect(fetchMock.mock.calls.filter(([url])=>/evidence\//.test(String(url)))).toHaveLength(0);
 });
 it("non avvia senza orizzonti",async()=>{
  await submitEvidence();for(const label of ["1 seduta","5 sedute","21 sedute"])fireEvent.click(screen.getByLabelText(label));
  fireEvent.click(screen.getByRole("button",{name:"Valuta evidenza"}));await flush();
  expect(screen.getByRole("alert")).toHaveTextContent("Seleziona almeno un orizzonte");
  expect(fetchMock.mock.calls.filter(([,i])=>i?.method==="POST")).toHaveLength(0);
 });
});
