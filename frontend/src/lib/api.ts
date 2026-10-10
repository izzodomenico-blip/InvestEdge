const API_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (typeof window !== "undefined" && !import.meta.env.DEV
    ? window.location.origin
    : "http://127.0.0.1:8000");

if (import.meta.env.DEV) {
  console.info("[InvestEdge] API_URL", API_URL);
}

export type DataMode = "REAL" | "DEMO";
export type SignalTimeframe = "D" | "W" | "M";

export type Signal = "STRONG_BUY" | "BUY" | "HOLD" | "REDUCE" | "SELL";

export type Reason = {
  type: "positive" | "negative" | "neutral";
  message: string;
};

export type Asset = {
  id: number;
  symbol: string;
  name: string;
  isin: string | null;
  asset_type: string;
  tax_category: TaxCategory;
  exchange: string | null;
  currency: string;
  sector: string | null;
  country: string | null;
  risk_level: string;
  last_price: number | null;
  fx_rate_to_base: number | null;
  last_price_base: number | null;
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
  signal_data_mode: DataMode | null;
  score_unavailable_reason: string | null;
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
  confirmation_token: string;
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
  name: string | null;
  isin: string | null;
  asset_type: string;
  quantity: number;
  average_price: number;
  average_price_base: number;
  invested_amount: number;
  invested_amount_base: number;
  current_price: number;
  current_value: number;
  current_value_base: number;
  realized_pnl: number;
  realized_pnl_base: number;
  unrealized_pnl: number;
  unrealized_pnl_base: number;
  unrealized_pnl_percent: number;
  weight_percent: number;
  currency: string;
  fx_rate_to_base: number;
  base_currency: "EUR";
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
  base_currency: "EUR";
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
  base_currency: "EUR";
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
  fees_base: number;
  gross_amount: number;
  gross_amount_base: number;
  net_amount: number;
  net_amount_base: number;
  currency: string;
  fx_rate_to_base: number;
  base_currency: "EUR";
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
  allow_short?: boolean;
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
  data_mode: DataMode | null;
};

export type BacktestStrategy = "SCORE_THRESHOLD" | "BUY_AND_HOLD" | "TOP_N_SCORE";
export type BacktestCostProfile = {
  commission_eur: number;
  cost_bps_equity: number;
  cost_bps_crypto: number;
  fractional_shares: boolean;
  min_trade_eur: number;
};

export function getLabSignals(signal?: AbortSignal): Promise<string[]> {
  return apiGet<string[]>("/lab/signals", { signal });
}

export type RebalanceFrequency = "DAILY" | "WEEKLY" | "MONTHLY";

export type BacktestSettingsInput = {
  symbols: string[];
  initial_cash?: number;
  start_date: string;
  end_date: string;
  benchmark_symbol?: string;
  buy_threshold?: number;
  sell_threshold?: number;
  max_asset_weight?: number;
  stop_loss_percent?: number | null;
  take_profit_percent?: number | null;
  rebalance_frequency?: RebalanceFrequency;
  top_n?: number | null;
  data_mode?: DataMode;
  signal_name?: string;
  signal_timeframe?: SignalTimeframe;
  commission_eur?: number | null;
  cost_bps_equity?: number | null;
  cost_bps_crypto?: number | null;
  fractional_shares?: boolean | null;
  min_trade_eur?: number | null;
};

export type BacktestRunInput = BacktestSettingsInput & {
  name: string;
  strategy_name: BacktestStrategy;
};

export type JobKind = "BACKTEST" | "COMPARE" | "WALK_FORWARD" | "EVIDENCE" | "FEATURE_REFRESH" | "FX_BACKFILL" | "ML_TRAIN";
export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export type JobOut = {
  id: number;
  kind: JobKind;
  status: JobStatus;
  params: Record<string, unknown>;
  progress: number;
  result_ref: string | null;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
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
  fee_percent: number | null;
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
  engine_version: string;
  data_mode: DataMode | null;
  signal_name: string | null;
  signal_timeframe: SignalTimeframe | null;
  cost_profile: BacktestCostProfile | null;
  warnings: string[];
  excluded: Record<string, string>;
  commission_eur: number | null;
  spread_cost_eur: number | null;
  turnover: number | null;
  exposure: number | null;
  fingerprint: string | null;
  benchmark_snapshot_status: "FROZEN" | "UNAVAILABLE" | "NOT_RECORDED";
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
  commission: number | null;
  spread_cost: number | null;
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

export type BacktestCompareInput = BacktestSettingsInput & {
  name?: string;
  strategy_names: BacktestStrategy[];
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
  is_sessions?: number | null;
  oos_sessions?: number | null;
};

export type WalkForwardWindow = {
  index: number;
  is_start: string;
  is_end: string;
  oos_start: string;
  oos_end: string;
  chosen: {
    name: string;
    buy_threshold: number;
    sell_threshold: number;
    max_asset_weight: number;
    top_n: number;
    rebalance_frequency: string;
  };
  is_sharpe: number | null;
};

export type WalkForwardMetrics = {
  start_date: string;
  end_date: string;
  total_return_percent: number;
  cagr: number;
  max_drawdown: number;
  sharpe_ratio: number;
  profit_factor: number;
  win_rate: number;
  total_trades: number;
  turnover: number;
  exposure: number;
  commission_eur: number;
  spread_cost_eur: number;
  final_value: number;
  benchmark_return_percent: number;
  alpha_vs_benchmark: number;
};

export type DeflatedSharpe = {
  dsr: number;
  sr: number;
  sr0: number;
  n_trials: number;
  n_obs: number;
  skew: number;
  kurtosis: number;
};

export type WalkForwardResult = {
  strategy_name: string;
  data_mode: DataMode;
  window_is_sessions: number;
  window_oos_sessions: number;
  windows: WalkForwardWindow[];
  grid_size: number;
  is_sharpe_mean: number | null;
  oos_sharpe: number | null;
  degradation: number | null;
  oos_metrics: WalkForwardMetrics;
  oos_sessions: number;
  dsr: DeflatedSharpe | null;
  n_trials: number | null;
  excluded: Record<string, string>;
  warnings: string[];
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
  outcome: "LOSS" | "GAIN" | "UNCHANGED";
};

export type ScenarioClassImpact = {
  asset_class: string;
  current_value: number;
  stressed_value: number;
  absolute_impact: number;
  shock_percent: number;
  outcome: "LOSS" | "GAIN" | "UNCHANGED";
};

export type ScenarioResult = {
  base_currency: "EUR";
  scenario_type: string;
  scenario_label: string;
  current_value: number;
  stressed_value: number;
  cash: number;
  absolute_impact: number;
  percentage_impact: number;
  outcome: "LOSS" | "GAIN" | "UNCHANGED";
  impact_label: string;
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

export type TaxCategory = "standard" | "government_bond" | "crypto" | "euro_emt";

export type TaxRealizedEvent = {
  symbol: string;
  asset_type: string | null;
  tax_category: TaxCategory;
  category: string;
  open_side: "BUY" | "SELL";
  close_side: "BUY" | "SELL";
  open_date: string;
  realization_date: string;
  sell_date: string | null;
  tax_year: number;
  quantity: number;
  currency: string;
  base_currency: "EUR";
  open_value_native: number;
  close_value_native: number;
  gain_native: number;
  open_value_base: number;
  close_value_base: number;
  gain_base: number;
  proceeds: number;
  cost_basis: number;
  gain: number;
  applied_rate: number;
  rate: number;
  holding_days: number;
};

export type TaxLossBucket = {
  tax_category: TaxCategory;
  origin_year: number;
  expires_after_year: number;
  remaining: number;
};

export type TaxYearSummary = {
  tax_year: number;
  total_gains: number;
  total_losses: number;
  net_realized: number;
  current_year_losses_used: number;
  carryforward_used: number;
  carryforward_expired: number;
  carryforward_remaining: number;
  carryforward_buckets: TaxLossBucket[];
  tax_due: number;
};

export type TaxOpenLot = {
  symbol: string;
  asset_type: string | null;
  tax_category: TaxCategory;
  open_side: "BUY" | "SELL";
  currency: string;
  base_currency: "EUR";
  quantity: number;
  open_value_native: number;
  open_value_base: number;
  current_value_native: number | null;
  current_value_base: number | null;
  unrealized_gain_native: number | null;
  unrealized_gain_base: number | null;
  cost_basis: number | null;
  current_value: number | null;
  unrealized_gain: number | null;
};

export type TaxRule = {
  tax_category: TaxCategory;
  from_year: number;
  rate: number;
  source_id: string;
};

export type TaxSource = {
  id: string;
  title: string;
  url: string;
};

export type TaxReport = {
  base_currency: string;
  standard_rate: number;
  bond_rate: number;
  lot_method: string;
  total_tax_due: number;
  total_realized_net: number;
  loss_carryforward: number;
  loss_carryforward_buckets: TaxLossBucket[];
  carryforward_note: string;
  tax_rules: TaxRule[];
  sources: TaxSource[];
  classification_warnings: string[];
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
  confirmation_token?: string;
};

export type AllocationItem = {
  symbol: string;
  name: string;
  weight_percent: number;
  capital: number;
  price: number | null;
  price_base: number | null;
  actual_cost_base: number;
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
  confirmation_token: string;
};

export type ProviderCapability = "CATALOG" | "IDENTITY" | "EOD" | "QUOTE" | "FX" | "REFERENCE" | "NEWS";
export type BudgetWindow = "MINUTE" | "DAY" | "MONTH";
export type RequestOutcome =
  | "SUCCEEDED"
  | "CACHE_HIT"
  | "RATE_LIMITED"
  | "TIMED_OUT"
  | "RETRY_EXHAUSTED"
  | "REJECTED"
  | "DISABLED";
export type AvailabilityState = "AVAILABLE" | "DISABLED" | "COOLDOWN";
export type AvailabilityReason =
  | "MISSING_CREDENTIAL"
  | "SECRET_IN_QUERY_POLICY"
  | "BULK_ONLY_POLICY"
  | "NOT_PRIMARY_POLICY"
  | "OPT_IN_DISABLED"
  | "RATE_LIMITED"
  | "BUDGET_EXHAUSTED"
  | "UNSUPPORTED_CAPABILITY";

export type ProviderBudgetWindow = {
  window: BudgetWindow;
  limit: number | null;
  used: number;
  remaining: number | null;
  reset_at: string;
};

export type DataProviderStatus = {
  provider: string;
  enabled: boolean;
  api_key_configured: boolean;
  daily_limit: number;
  calls_today: number;
  supports: string[];
  // Estensioni additive (Task 16): nessuna key, URL, endpoint o fingerprint.
  capabilities: ProviderCapability[];
  budget_windows: ProviderBudgetWindow[];
  cooldown_until: string | null;
  availability_state: AvailabilityState | null;
  availability_reason: AvailabilityReason | null;
  last_outcome: RequestOutcome | null;
  last_outcome_at: string | null;
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
  coverage_summary: DataCoverageSummary | null;
};

export type CoverageCount = {
  key: string;
  total: number;
  resolved: number;
  qualified: number;
  observable: number;
  reference_only: number;
};

export type ProviderCoverage = {
  provider: string;
  capability: ProviderCapability;
  eligible_listings: number;
  unmapped_listings: number;
  mapped_listings: number;
  fresh_listings: number;
  stale_listings: number;
  missing_observation_listings: number;
  rejected_observations: number;
  quality_counts: Record<string, number>;
  delay_bucket_counts: Record<string, number>;
  latest_provider_observed_at: string | null;
  latest_ingested_at: string | null;
  attribution: string | null;
};

export type FxCoverageStatus = "FRESH" | "STALE" | "MISSING";
export type FxRateDirection = "DIRECT" | "INVERSE";

export type FxCoverage = {
  from_currency: string;
  to_currency: "EUR";
  status: FxCoverageStatus;
  direction: FxRateDirection | null;
  provider: string | null;
  /** Decimal serializzato da Pydantic come stringa (mai binary float): solo presentazione. */
  rate_to_eur: string | null;
  observed_at: string | null;
  ingested_at: string | null;
  age_seconds: number | null;
  quality: string | null;
};

export type DataCoverage = {
  measured_at: string;
  latest_catalog_snapshot_id: number | null;
  latest_catalog_retrieved_at: string | null;
  latest_catalog_sha256: string | null;
  parse_accepted_entries: number;
  parse_ambiguous_entries: number;
  parse_rejected_entries: number;
  parse_denominator: number;
  resolution_resolved_entries: number;
  resolution_ambiguous_entries: number;
  resolution_unmatched_entries: number;
  resolution_rejected_entries: number;
  resolution_unprocessed_entries: number;
  resolution_denominator: number;
  resolved_percent: number;
  tier_denominator: number;
  tier_counts: Record<QualityTier, number>;
  tier_percentages: Record<QualityTier, number>;
  trade_republic_denominator: number;
  trade_republic_status_counts: Record<string, number>;
  trade_republic_verified_percent: number;
  by_asset_class: CoverageCount[];
  by_market: CoverageCount[];
  rejection_reasons: Record<string, number>;
  provider_coverage: ProviderCoverage[];
  fx_currency_denominator: number;
  fx_fresh_currencies: number;
  fx_stale_currencies: number;
  fx_missing_currencies: number;
  fx_coverage: FxCoverage[];
  pending_refresh: number;
  budget_deferred: number;
};

export type DataCoverageSummary = {
  measured_at: string;
  latest_catalog_snapshot_id: number | null;
  latest_catalog_retrieved_at: string | null;
  resolution_denominator: number;
  resolved_percent: number;
  tier_denominator: number;
  tier_percentages: Record<QualityTier, number>;
  trade_republic_denominator: number;
  trade_republic_verified_percent: number;
  fx_currency_denominator: number;
  fx_fresh_currencies: number;
  fx_stale_currencies: number;
  fx_missing_currencies: number;
  pending_refresh: number;
  budget_deferred: number;
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

// I 409 di import/allocation apply espongono un reason_code (Fase 2): il messaggio
// guida della Fase 1 resta visibile nelle pagine che mostrano `error.message`.
const STALE_PREVIEW_MESSAGE =
  "I dati sono cambiati dopo l'anteprima: genera una nuova anteprima dell'import o ricalcola l'allocazione prima di applicarla.";
const REASON_CODE_MESSAGES: Record<string, string> = {
  RESOLUTION_CHANGED: STALE_PREVIEW_MESSAGE,
  LISTING_METADATA_CHANGED: STALE_PREVIEW_MESSAGE,
};

async function parseError(response: Response): Promise<ApiError> {
  const fallback = `API request failed: ${response.status}`;
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return new ApiError(payload.detail, response.status, payload.detail);
    }
    const reason = payload.detail?.reason_code;
    const message = typeof reason === "string" ? REASON_CODE_MESSAGES[reason] : undefined;
    const serverMessage = typeof payload.detail?.message === "string" ? payload.detail.message : undefined;
    return new ApiError(message ?? serverMessage ?? fallback, response.status, payload.detail ?? null);
  } catch {
    return new ApiError(fallback, response.status);
  }
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

function fetchErrorMessage(method: string, path: string, error: unknown) {
  const base = error instanceof Error ? error.message : "Failed to fetch";
  if (import.meta.env.DEV) {
    // Solo metodo e pathname: la query string (ricerche, filtri) non finisce nei messaggi.
    const pathname = path.split(/[?#]/, 1)[0];
    return `${base}. API_URL=${API_URL}; request=${method} ${pathname}; origin=${window.location.origin}`;
  }
  return base;
}

export function apiUrl(path: string): string {
  return `${API_URL}${path}`;
}

export type Backup = {
  file: string | null;
  size_bytes: number | null;
  created_at: string | null;
  created?: boolean;
  reason?: string | null;
};

export type ReportSummary = {
  positions_count: number;
  orders_count: number;
  realized_events_count: number;
  portfolio_value: number;
  total_pnl: number;
  estimated_tax_due: number;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** `reason_code` stabile di un errore API (`{"detail": {"reason_code": ...}}`), se presente. */
export function apiReasonCode(error: unknown): string | null {
  if (!(error instanceof ApiError) || typeof error.detail !== "object" || error.detail === null) {
    return null;
  }
  const reason = (error.detail as { reason_code?: unknown }).reason_code;
  return typeof reason === "string" ? reason : null;
}

export async function apiGet<T>(path: string, init: { signal?: AbortSignal } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init.signal ? { signal: init.signal } : undefined);
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new Error(fetchErrorMessage("GET", path, error));
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  const payload = await response.json();
  init.signal?.throwIfAborted();
  return payload as T;
}

export async function apiPost<T>(
  path: string, body?: unknown, init: { signal?: AbortSignal } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      signal: init.signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new Error(fetchErrorMessage("POST", path, error));
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  const payload = await response.json();
  init.signal?.throwIfAborted();
  return payload as T;
}

export async function apiDelete<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "DELETE",
    });
  } catch (error) {
    throw new Error(fetchErrorMessage("DELETE", path, error));
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json() as Promise<T>;
}

export type EffectiveObservationQuality = "realtime" | "delayed" | "eod" | "reference" | "stale";
export type QualityTier = "QUALIFIED" | "OBSERVABLE" | "REFERENCE_ONLY";
export type TradeRepublicStatus = "NEVER_SEEN" | "CATALOGED" | "VERIFIED" | "UNAVAILABLE";
export type ResolutionStatus = "RESOLVED" | "AMBIGUOUS" | "UNMATCHED" | "REJECTED";
export type InstrumentType =
  | "STOCK"
  | "ETF"
  | "BOND"
  | "ETC"
  | "ETN"
  | "CRYPTO"
  | "FX"
  | "INDEX"
  | "RATE"
  | "MACRO"
  | "UNKNOWN";
export type AssetClass =
  | "EQUITY"
  | "FUND"
  | "FIXED_INCOME"
  | "COMMODITY"
  | "CRYPTO"
  | "FX"
  | "REFERENCE"
  | "UNKNOWN";
export type IdentifierScheme =
  | "ISIN"
  | "FIGI"
  | "OPENFIGI_TICKER"
  | "COINGECKO_ID"
  | "FRED_SERIES_ID"
  | "ECB_SERIES_KEY";

export type InstrumentListItem = {
  instrument_id: number;
  canonical_name: string;
  instrument_type: InstrumentType;
  asset_class: AssetClass;
  quality_tier: QualityTier;
  quality_reasons: string[];
  primary_identifier_scheme: IdentifierScheme | null;
  primary_identifier: string | null;
  listing_id: number | null;
  ticker: string | null;
  mic: string | null;
  venue_name: string | null;
  currency: string | null;
  timezone: string | null;
  trade_republic_status: TradeRepublicStatus;
  trade_republic_cataloged_at: string | null;
  trade_republic_verified_at: string | null;
  observation_quality: EffectiveObservationQuality | null;
  observed_at: string | null;
};

export type InstrumentSearch = {
  items: InstrumentListItem[];
  total: number;
  limit: number;
  offset: number;
  catalog_snapshot_id: number | null;
};

export type InstrumentIdentifier = {
  scheme: IdentifierScheme;
  value: string;
  sources: string[];
  first_observed_at: string;
  last_observed_at: string;
};

export type InstrumentListing = {
  listing_id: number;
  ticker: string;
  mic: string | null;
  venue_name: string | null;
  currency: string;
  timezone: string | null;
  resolution_status: ResolutionStatus;
  trade_republic_status: TradeRepublicStatus;
};

export type InstrumentDetail = InstrumentListItem & {
  identifiers: InstrumentIdentifier[];
  listings: InstrumentListing[];
};

export type InstrumentFilters = {
  q?: string;
  asset_class?: AssetClass;
  instrument_type?: InstrumentType;
  currency?: string;
  mic?: string;
  quality_tier?: QualityTier;
  trade_republic_status?: TradeRepublicStatus;
  limit?: number;
  offset?: number;
};

export function getInstruments(filters: InstrumentFilters, signal?: AbortSignal): Promise<InstrumentSearch> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return apiGet<InstrumentSearch>(`/instruments${query ? `?${query}` : ""}`, { signal });
}

export function getInstrument(instrumentId: number, signal?: AbortSignal): Promise<InstrumentDetail> {
  return apiGet<InstrumentDetail>(`/instruments/${encodeURIComponent(String(instrumentId))}`, { signal });
}

/** Attivazione esplicita di un listing RESOLVED (201 alla creazione, 200 se gia attivo). */
export function activateListing(listingId: number): Promise<Asset> {
  return apiPost<Asset>(`/assets/from-listing/${encodeURIComponent(String(listingId))}`);
}

/** Copertura misurata sul database locale (`GET /data/coverage`): una sola richiesta. */
export function getDataCoverage(): Promise<DataCoverage> {
  return apiGet<DataCoverage>("/data/coverage");
}

export const REFRESH_BATCH_MAX_LIMIT = 25;

/** Batch prioritario limitato (`POST /data/refresh-all?limit=N`, senza body), N intero 1..25. */
export async function refreshAll(limit: number): Promise<DataRefreshAllResult> {
  if (!Number.isInteger(limit) || limit < 1 || limit > REFRESH_BATCH_MAX_LIMIT) {
    throw new RangeError(`limit deve essere un intero da 1 a ${REFRESH_BATCH_MAX_LIMIT}`);
  }
  const params = new URLSearchParams({ limit: String(limit) });
  return apiPost<DataRefreshAllResult>(`/data/refresh-all?${params.toString()}`);
}

const DECIMAL_STRING = /^\d+(?:\.\d+)?$/;
const rateFormatter = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 6 });

/**
 * Presentazione di `rate_to_eur`: accetta solo una stringa decimale completa e finita,
 * altrimenti `—`. La conversione numerica serve esclusivamente a formattare, mai a calcolare.
 */
export function formatRateToEur(value: string | null): string {
  if (value === null || !DECIMAL_STRING.test(value)) return "—";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? rateFormatter.format(numeric) : "—";
}

/** Accoda un refresh `VIEWED` non forzato: nessuna chiamata provider immediata. */
export function markListingViewed(listingId: number): Promise<{ refresh_request_id: number }> {
  return apiPost<{ refresh_request_id: number }>(
    `/data/refresh/viewed/${encodeURIComponent(String(listingId))}`,
  );
}
