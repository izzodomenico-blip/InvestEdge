const API_URL =
  import.meta.env.VITE_API_BASE_URL ??
  "http://127.0.0.1:8001";

if (import.meta.env.DEV) {
  console.info("[InvestEdge] API_URL", API_URL);
}

export type Signal = "STRONG_BUY" | "BUY" | "HOLD" | "REDUCE" | "SELL";

export type Reason = {
  type: "positive" | "negative" | "neutral";
  message: string;
};

export type Asset = {
  id: number;
  symbol: string;
  name: string;
  asset_type: string;
  exchange: string | null;
  currency: string;
  sector: string | null;
  country: string | null;
  risk_level: string;
  last_price: number | null;
  daily_change_pct: number | null;
  last_source: string | null;
  provider: string | null;
  is_real_data: boolean;
  last_price_date: string | null;
  last_fetch_at: string | null;
  score: number | null;
  signal: Signal | null;
  confidence: string | null;
  technical_summary: string | null;
  updated_at: string | null;
};

export type SignalRecord = {
  id: number;
  asset_id: number;
  symbol: string;
  signal: Signal;
  score: number;
  risk_level: string | null;
  confidence: string | null;
  technical_summary: string | null;
  reasons: Reason[];
  subscores: Record<string, number>;
  created_at: string;
};

export type DashboardResponse = {
  initialized: boolean;
  message: string | null;
  assets_count: number;
  positions_count: number;
  portfolio_value: number;
  cash: number;
  total_pnl: number;
  total_pnl_percent: number;
  risk_warnings_count: number;
  top_position: PortfolioPosition | null;
  portfolio_snapshots: Array<Pick<PortfolioSnapshot, "snapshot_date" | "total_value" | "cash" | "total_pnl" | "total_pnl_percent">>;
  signals_count: number;
  price_points_count: number;
  average_score: number | null;
  asset_type_breakdown: Record<string, number>;
  risk_breakdown: Record<string, number>;
  signal_breakdown: Record<string, number>;
  latest_signals: SignalRecord[];
  top_assets: Asset[];
  weakest_assets: Asset[];
  risky_assets: Asset[];
  latest_backtest: BacktestSummary | null;
  data_status: DataStatus;
};

export type PortfolioPosition = {
  id: number;
  asset_id: number;
  symbol: string;
  asset_type: string;
  quantity: number;
  average_price: number;
  invested_amount: number;
  current_price: number;
  current_value: number;
  realized_pnl: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  weight_percent: number;
  currency: string;
  technical_signal: Signal | null;
  recommendation: string | null;
};

export type RiskWarning = {
  level: string;
  code: string;
  message: string;
  symbol: string | null;
};

export type PortfolioSettings = {
  initial_cash: number;
  current_cash: number;
  max_single_asset_weight: number;
  max_asset_class_weight: number;
  default_fee_percent: number;
  crypto_max_weight: number;
  min_cash_weight: number;
  max_cash_weight: number;
};

export type PortfolioSummary = {
  cash: number;
  total_value: number;
  invested_value: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_pnl_percent: number;
  positions: PortfolioPosition[];
  allocation_by_asset_type: Record<string, number>;
  allocation_by_currency: Record<string, number>;
  risk_warnings: RiskWarning[];
  settings: PortfolioSettings;
};

export type PortfolioSnapshot = {
  id: number;
  snapshot_date: string;
  total_value: number;
  invested_value: number;
  cash: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_pnl_percent: number;
  created_at: string;
};

export type PortfolioRecommendation = {
  symbol: string;
  technical_signal: Signal | null;
  technical_score: number | null;
  portfolio_weight: number;
  final_recommendation: string;
  reason: string;
};

export type SimulatedOrder = {
  id: number;
  asset_id: number;
  symbol: string;
  order_type: "BUY" | "SELL";
  quantity: number;
  price: number;
  fees: number;
  gross_amount: number;
  net_amount: number;
  order_date: string;
  note: string | null;
  strategy_tag: string | null;
};

export type SimulatedOrderInput = {
  symbol: string;
  order_type: "BUY" | "SELL";
  quantity: number;
  price?: number;
  fees?: number;
  note?: string;
  strategy_tag?: string;
};

export type OrderSimulationResponse = {
  order: SimulatedOrder;
  updated_position: PortfolioPosition | null;
  updated_portfolio_summary: PortfolioSummary;
  warnings: RiskWarning[];
};

export type PricePoint = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adjusted_close: number;
  volume: number;
  source: string;
  provider: string | null;
  is_real_data: boolean;
  fetched_at: string | null;
  sma_20: number | null;
  sma_50: number | null;
  sma_200: number | null;
  ema_12: number | null;
  ema_26: number | null;
  ema_50: number | null;
  ema_200: number | null;
  rsi_14: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  bollinger_upper: number | null;
  bollinger_lower: number | null;
};

export type PriceHistory = {
  symbol: string;
  name: string;
  asset_type: string;
  currency: string;
  prices: PricePoint[];
};

export type TechnicalAnalysis = {
  asset: Asset;
  latest_price: number | null;
  indicators: Record<string, number>;
  conditions: Record<string, boolean>;
  support_resistance: Record<string, number | null>;
  subscores: Record<string, number>;
  score: number;
  signal: Signal;
  risk_level: string;
  confidence: string;
  reasons: Reason[];
  summaries: Record<string, string>;
  technical_summary: string;
};

export type BacktestStrategy = "SCORE_THRESHOLD" | "BUY_AND_HOLD" | "TOP_N_SCORE";
export type RebalanceFrequency = "DAILY" | "WEEKLY" | "MONTHLY";

export type BacktestRunInput = {
  name: string;
  strategy_name: BacktestStrategy;
  symbols: string[];
  initial_cash: number;
  start_date: string;
  end_date: string;
  benchmark_symbol: string;
  buy_threshold: number;
  sell_threshold: number;
  max_asset_weight: number;
  fee_percent: number;
  stop_loss_percent?: number;
  take_profit_percent?: number;
  rebalance_frequency: RebalanceFrequency;
  top_n?: number;
};

export type BacktestSummary = {
  id: number | null;
  name: string;
  strategy_name: string;
  initial_cash: number;
  start_date: string;
  end_date: string;
  benchmark_symbol: string | null;
  buy_threshold: number;
  sell_threshold: number;
  max_asset_weight: number;
  fee_percent: number;
  stop_loss_percent: number | null;
  take_profit_percent: number | null;
  rebalance_frequency: string;
  total_return_percent: number;
  cagr: number;
  max_drawdown: number;
  sharpe_ratio: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  final_value: number;
  benchmark_return_percent: number;
  alpha_vs_benchmark: number;
  created_at: string | null;
};

export type BacktestEquityPoint = {
  id: number | null;
  date: string;
  portfolio_value: number;
  cash: number;
  invested_value: number;
  drawdown_percent: number;
  benchmark_value: number | null;
  benchmark_return_percent: number | null;
};

export type BacktestTrade = {
  id: number | null;
  date: string;
  symbol: string;
  order_type: "BUY" | "SELL";
  quantity: number;
  price: number;
  fees: number;
  gross_amount: number;
  net_amount: number;
  pnl: number;
  reason: string | null;
};

export type BacktestPosition = {
  id: number | null;
  symbol: string;
  quantity: number;
  average_price: number;
  final_price: number;
  final_value: number;
  realized_pnl: number;
  unrealized_pnl: number;
};

export type BacktestResult = {
  backtest_id: number;
  summary: BacktestSummary;
  equity_curve: BacktestEquityPoint[];
  trades: BacktestTrade[];
  final_positions: BacktestPosition[];
  benchmark_comparison: {
    benchmark_symbol: string | null;
    benchmark_return_percent: number;
    alpha_vs_benchmark: number;
    benchmark_final_value: number;
  };
};

export type DataProviderStatus = {
  provider: string;
  enabled: boolean;
  api_key_configured: boolean;
  daily_limit: number;
  calls_today: number;
  supports: string[];
};

export type ApiUsage = {
  provider: string;
  usage_date: string;
  calls_count: number;
  daily_limit: number;
  updated_at: string | null;
};

export type DataStatus = {
  enable_real_data: boolean;
  provider_status: DataProviderStatus[];
  api_usage: ApiUsage[];
  cache_stats: Record<string, number>;
  global_last_update: string | null;
  data_mode: "SEED" | "MIXED" | "REAL";
};

export type AssetDataStatus = {
  symbol: string;
  last_price_date: string | null;
  last_source: string | null;
  provider: string | null;
  is_real_data: boolean;
  last_fetch_at: string | null;
  cache_status: string;
  message: string;
};

export type DataRefreshResult = {
  symbol: string;
  provider: string | null;
  rows_inserted: number;
  rows_updated: number;
  used_cache: boolean;
  used_fallback: boolean;
  message: string;
};

export type DataRefreshAllResult = {
  summary: Record<string, number>;
  results: DataRefreshResult[];
};

async function parseError(response: Response) {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    return `API request failed: ${response.status}`;
  }
  return `API request failed: ${response.status}`;
}

function fetchErrorMessage(path: string, error: unknown) {
  const targetUrl = `${API_URL}${path}`;
  const base = error instanceof Error ? error.message : "Failed to fetch";
  if (import.meta.env.DEV) {
    return `${base}. API_URL=${API_URL}; request=${targetUrl}; origin=${window.location.origin}`;
  }
  return base;
}

export async function apiGet<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`);
  } catch (error) {
    throw new Error(fetchErrorMessage(path, error));
  }

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new Error(fetchErrorMessage(path, error));
  }

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<T>;
}

export async function apiDelete<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "DELETE",
    });
  } catch (error) {
    throw new Error(fetchErrorMessage(path, error));
  }

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<T>;
}
