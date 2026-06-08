const API_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (typeof window !== "undefined" && !import.meta.env.DEV
    ? window.location.origin
    : "http://127.0.0.1:8001");

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
  technical_score: number | null;
  news_score: number | null;
  final_score: number | null;
  news_sentiment_label: string | null;
  news_impact_level: string | null;
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
  technical_score: number | null;
  news_score: number;
  final_score: number | null;
  news_sentiment_label: string | null;
  news_impact_level: string | null;
  risk_level: string | null;
  confidence: string | null;
  technical_summary: string | null;
  reasons: Reason[];
  subscores: Record<string, number>;
  created_at: string;
};

export type ActionType = "BUY" | "REDUCE" | "SELL" | "WATCH" | "RISK" | "OK";
export type ActionPriority = "HIGH" | "MEDIUM" | "LOW";

export type ActionItem = {
  type: ActionType;
  priority: ActionPriority;
  symbol: string | null;
  title: string;
  reason: string;
  signal: string | null;
  score: number | null;
  weight_percent: number | null;
};

export type ActionBoard = {
  generated_at: string;
  data_mode: "SEED" | "MIXED" | "REAL";
  enable_real_data: boolean;
  headline: string;
  counts: Record<string, number>;
  actions: ActionItem[];
};

export type AlertStatus = {
  enabled: boolean;
  configured: boolean;
  channel: string;
};

export type MLModelType = "LOGISTIC_REGRESSION" | "RANDOM_FOREST" | "HIST_GRADIENT_BOOSTING";
export type MLTargetType = "POSITIVE_RETURN" | "OUTPERFORM_BENCHMARK" | "DRAWDOWN_RISK";

export type MLTrainInput = {
  model_name: string;
  model_type: MLModelType;
  target_type: MLTargetType;
  horizon_days: number;
  symbols: string[];
  benchmark_symbol?: string;
  test_size_time_percent?: number;
  min_samples?: number;
  cv_folds?: number;
};

export type MLStatus = {
  models_count: number;
  latest_model: Record<string, unknown> | null;
  latest_training_run: Record<string, unknown> | null;
  available_targets: string[];
  available_model_types: string[];
  ml_ready: boolean;
  message: string;
};

export type MLTrainResult = {
  model_id: number;
  training_run: Record<string, unknown> | null;
  metrics: Record<string, unknown>;
  features_used: string[];
  warnings: string[];
};

export type MLPrediction = {
  id: number | null;
  symbol: string;
  model_id: number;
  horizon_days: number;
  target_type: string;
  prediction_date: string;
  probability_positive: number | null;
  probability_outperform: number | null;
  probability_drawdown: number | null;
  predicted_label: string;
  confidence: string;
  explanation: Record<string, unknown>;
  warnings: string[];
};

export type MLModelSummary = {
  id: number;
  model_name: string;
  model_type: string;
  target_type: string;
  horizon_days: number;
  metrics: Record<string, unknown>;
  trained_at: string | null;
};

export type ImportHolding = {
  symbol: string;
  name: string;
  asset_type: string;
  quantity: number;
  average_price: number;
  currency: string;
};

export type ImportPreview = {
  rows_total: number;
  rows_valid: number;
  rows_invalid: number;
  holdings: ImportHolding[];
  errors: string[];
};

export type ImportStatus = {
  enabled: boolean;
  configured: boolean;
  csv_url_set: boolean;
};

export type ImportApplyResult = {
  imported: number;
  created_assets: number;
  rows_invalid: number;
  errors: string[];
  portfolio_value: number;
};

export type AlertSendResult = {
  ok: boolean;
  message_id: number | null;
  actions_sent: number | null;
  headline: string | null;
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
  latest_high_impact_news: NewsItem[];
  market_news_summary: MarketNewsSummary;
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
  technical_score: number | null;
  news_score: number;
  final_score: number | null;
  news_sentiment_label: string | null;
  news_impact_level: string | null;
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

export type BacktestNetAnalysis = {
  gross_return_percent: number;
  gross_profit: number;
  commission_costs: number;
  slippage_costs: number;
  realized_gains_taxable: number;
  capital_gains_tax: number;
  stamp_duty: number;
  total_costs_and_taxes: number;
  net_final_value: number;
  net_return_percent: number;
  effective_tax_rate_percent: number;
  notes: string[];
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
  net_analysis: BacktestNetAnalysis | null;
};

export type BacktestCompareInput = {
  name?: string;
  strategy_names: BacktestStrategy[];
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

export type BacktestCompareEntry = {
  strategy_name: string;
  label: string;
  rank: number;
  summary: BacktestSummary;
  equity_curve: BacktestEquityPoint[];
};

export type BacktestCompareResult = {
  name: string;
  start_date: string;
  end_date: string;
  benchmark_symbol: string | null;
  benchmark_return_percent: number;
  best_strategy: string;
  entries: BacktestCompareEntry[];
};

export type WalkForwardInput = BacktestRunInput & {
  folds: number;
};

export type WalkForwardFold = {
  fold: number;
  start_date: string;
  end_date: string;
  total_return_percent: number;
  cagr: number;
  max_drawdown: number;
  sharpe_ratio: number;
  alpha_vs_benchmark: number;
  total_trades: number;
  final_value: number;
};

export type WalkForwardResult = {
  strategy_name: string;
  folds: number;
  full_period_return_percent: number;
  mean_return_percent: number;
  median_return_percent: number;
  std_return_percent: number;
  positive_folds: number;
  folds_beating_benchmark: number;
  worst_fold_return_percent: number;
  best_fold_return_percent: number;
  mean_alpha_vs_benchmark: number;
  consistency: "ROBUSTA" | "INCERTA" | "FRAGILE";
  verdict: string;
  fold_results: WalkForwardFold[];
};

export type ScenarioType =
  | "MARKET_CRASH"
  | "TECH_SELLOFF"
  | "CRYPTO_WINTER"
  | "RATE_HIKE"
  | "INFLATION_SHOCK"
  | "MILD_CORRECTION"
  | "CUSTOM";

export type ScenarioAssetImpact = {
  symbol: string;
  asset_type: string;
  current_value: number;
  shock_percent: number;
  stressed_value: number;
  absolute_impact: number;
  loss_contribution_percent: number;
};

export type ScenarioClassImpact = {
  asset_class: string;
  current_value: number;
  stressed_value: number;
  absolute_impact: number;
  shock_percent: number;
};

export type ScenarioResult = {
  scenario_type: string;
  scenario_label: string;
  current_value: number;
  stressed_value: number;
  cash: number;
  absolute_loss: number;
  percentage_loss: number;
  risk_level: string;
  asset_impacts: ScenarioAssetImpact[];
  class_impacts: ScenarioClassImpact[];
  mitigation: string[];
};

export type RebalanceTrade = {
  symbol: string;
  action: "BUY" | "SELL" | "HOLD";
  current_weight: number;
  target_weight: number;
  current_value: number;
  target_value: number;
  delta_value: number;
  delta_quantity: number;
  price: number | null;
};

export type RebalanceResult = {
  method: string;
  total_value: number;
  estimated_volatility: number;
  trades: RebalanceTrade[];
  notes: string[];
};

export type TaxRealizedEvent = {
  symbol: string;
  asset_type: string | null;
  category: string;
  sell_date: string;
  tax_year: number;
  quantity: number;
  proceeds: number;
  cost_basis: number;
  gain: number;
  rate: number;
  holding_days: number;
};

export type TaxYearSummary = {
  tax_year: number;
  total_gains: number;
  total_losses: number;
  net_realized: number;
  carryforward_used: number;
  carryforward_remaining: number;
  tax_due: number;
};

export type TaxOpenLot = {
  symbol: string;
  asset_type: string | null;
  quantity: number;
  cost_basis: number;
  current_value: number | null;
  unrealized_gain: number | null;
};

export type TaxReport = {
  base_currency: string;
  standard_rate: number;
  bond_rate: number;
  lot_method: string;
  total_tax_due: number;
  total_realized_net: number;
  loss_carryforward: number;
  years: TaxYearSummary[];
  events: TaxRealizedEvent[];
  open_lots: TaxOpenLot[];
  disclaimer: string;
};

export type AllocationMethod = "EQUAL_WEIGHT" | "RISK_PARITY" | "SCORE_WEIGHTED" | "VOL_TARGET";

export type AllocationPlanInput = {
  symbols: string[];
  method: AllocationMethod;
  total_capital: number;
  target_volatility?: number | null;
  max_weight?: number | null;
  lookback_days?: number;
};

export type AllocationItem = {
  symbol: string;
  name: string;
  weight_percent: number;
  capital: number;
  price: number | null;
  suggested_quantity: number;
  volatility: number;
  score: number | null;
};

export type AllocationPlan = {
  method: string;
  total_capital: number;
  invested_capital: number;
  cash_buffer: number;
  target_volatility: number | null;
  estimated_volatility: number;
  allocations: AllocationItem[];
  notes: string[];
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

export type NewsSentimentLabel = "POSITIVE" | "NEGATIVE" | "NEUTRAL";
export type NewsImpactLevel = "LOW" | "MEDIUM" | "HIGH";

export type NewsItem = {
  id: number | null;
  symbol: string | null;
  provider: string;
  title: string;
  summary: string | null;
  url: string | null;
  source: string | null;
  published_at: string | null;
  sentiment_score: number | null;
  sentiment_label: NewsSentimentLabel | string | null;
  impact_level: NewsImpactLevel | string | null;
  relevance_score: number | null;
  raw_json: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
};

export type NewsRefreshResult = {
  symbol: string;
  provider: string | null;
  items_inserted: number;
  items_updated: number;
  used_cache: boolean;
  used_fallback: boolean;
  message: string;
};

export type NewsRefreshAllResult = {
  summary: Record<string, number>;
  results: NewsRefreshResult[];
};

export type NewsProviderStatus = {
  provider: string;
  enabled: boolean;
  api_key_configured: boolean;
  daily_limit: number;
  calls_today: number;
  supports: string[];
};

export type NewsStatus = {
  enable_real_news: boolean;
  provider_status: NewsProviderStatus[];
  daily_usage: {
    provider: string;
    usage_date: string;
    calls_count: number;
    daily_limit: number;
    updated_at: string | null;
  };
  cache_status: Record<string, number>;
  last_refresh: string | null;
};

export type NewsSentimentSummary = {
  symbol: string;
  lookback_days: number;
  news_count: number;
  average_sentiment_score: number;
  sentiment_label: NewsSentimentLabel | string;
  impact_level: NewsImpactLevel | string;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  latest_news: NewsItem[];
};

export type MarketNewsSummary = Omit<NewsSentimentSummary, "symbol" | "latest_news">;

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
