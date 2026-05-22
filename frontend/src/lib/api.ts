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
  ml_model_id: number | null;
  ml_probability: number | null;
  ml_confidence: string | null;
  ml_label: string | null;
  ml_target_type: string | null;
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

export type SentimentLabel = "POSITIVE" | "NEGATIVE" | "NEUTRAL";
export type ImpactLevel = "LOW" | "MEDIUM" | "HIGH";

export type NewsItem = {
  id: number;
  asset_id: number | null;
  symbol: string | null;
  provider: string | null;
  title: string;
  summary: string | null;
  url: string | null;
  source: string | null;
  published_at: string | null;
  sentiment_score: number;
  sentiment_label: SentimentLabel;
  impact_level: ImpactLevel;
  relevance_score: number;
  created_at: string | null;
};

export type MarketSentiment = {
  news_count: number;
  average_sentiment_score: number;
  sentiment_label: SentimentLabel;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
};

export type SystemHealth = {
  status: "healthy" | "degraded" | "down";
  database: string;
  providers: Record<string, string>;
  cache: string;
  timestamp: string;
};

export type DataQualityCheck = {
  symbol: string;
  score: number;
  grade: string;
  checks: Record<string, boolean>;
  details: Record<string, string | number | boolean>;
  is_valid: boolean;
  last_check: string;
};

export type ValidatedSignal = {
  symbol: string;
  asset_id: number;
  original_signal: string;
  validated_signal: string;
  reason: string;
  data_quality_score: number;
  ml_confidence: string | null;
  news_sentiment: string | null;
  portfolio_weight: number | null;
  action_suggested: string;
  timestamp: string;
};

export type OperationalRanking = {
  buy_candidates: ValidatedSignal[];
  watch_candidates: ValidatedSignal[];
  reduce_candidates: ValidatedSignal[];
  excluded_candidates: ValidatedSignal[];
  updated_at: string;
};

export type PortfolioAction = {
  symbol: string;
  action: string;
  reason: string;
  current_weight: number;
  target_weight: number | null;
  timestamp: string;
};

export type StrategyPlanConfig = {
  plan_name: string;
  universe_level: string;
  strategy_mode: "CONSERVATIVE" | "BALANCED" | "AGGRESSIVE";
  max_positions: number;
  max_single_asset_weight: number;
  max_asset_class_weight: number;
  min_data_quality_score: number;
  min_confidence: string;
  allow_crypto: boolean;
  max_crypto_weight: number;
  require_real_data: boolean;
  include_ml: boolean;
  include_news: boolean;
  rebalance_threshold_percent: number;
  cash_reserve_percent: number;
  order_generation_mode: "SUGGEST_ONLY" | "PAPER_ORDERS";
};

export type StrategyPlanSummary = {
  id: number;
  plan_name: string;
  strategy_mode: string;
  universe_level: string;
  total_current_value: number;
  target_invested_value: number;
  expected_cash_after_plan: number;
  estimated_orders_count: number;
  status: string;
  created_at: string;
};

export type StrategyPlanItem = {
  id?: number;
  symbol: string;
  current_weight: number;
  target_weight: number;
  current_value: number;
  target_value: number;
  delta_value: number;
  suggested_action: string;
  operational_signal?: string | null;
  confidence?: string | null;
  data_quality_score?: number | null;
  reason?: string | null;
  blocker?: string | null;
};

export type StrategyPlanOrder = {
  id?: number;
  symbol: string;
  order_type: "BUY" | "SELL";
  quantity: number;
  estimated_price: number;
  estimated_gross_amount: number;
  estimated_fees: number;
  estimated_net_amount: number;
  reason?: string | null;
  status: string;
};

export type StrategyPlanFull = {
  summary: StrategyPlanSummary;
  config: StrategyPlanConfig;
  items: StrategyPlanItem[];
  proposed_orders: StrategyPlanOrder[];
  warnings: string[];
  blockers: string[];
};

export type Alert = {
  id: number;
  alert_type: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  symbol?: string | null;
  title: string;
  message: string;
  status: "OPEN" | "ACKNOWLEDGED" | "CLOSED";
  source_module?: string | null;
  payload_json?: string | null;
  created_at: string;
  updated_at: string;
  acknowledged_at?: string | null;
  closed_at?: string | null;
};

export type AlertSummary = {
  open_count: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  latest_alerts: Alert[];
  by_type: Record<string, number>;
};

export type AlertRule = {
  id: number;
  rule_name: string;
  alert_type: string;
  enabled: boolean;
  severity: string;
  universe_level?: string | null;
  symbol?: string | null;
  threshold_value?: number | null;
  config_json?: string | null;
};

export type SchedulerRun = {
  id: number;
  run_type: string;
  status: "SUCCESS" | "WARNING" | "ERROR";
  started_at: string;
  finished_at?: string | null;
  duration_seconds?: number | null;
  summary: Record<string, any>;
  errors: string[];
  created_at: string;
};

export type OperationalReportSummary = {
  system_health: Record<string, any>;
  data_quality_avg: number;
  buy_candidates_count: number;
  watch_candidates_count: number;
  reduce_candidates_count: number;
  portfolio_value: number;
  risk_warnings_count: number;
  open_alerts_count: number;
};

export type OperationalReport = {
  id: number;
  report_type: string;
  report_date: string;
  title: string;
  summary: OperationalReportSummary;
  markdown_text?: string | null;
  created_at: string;
};

export type OptimizationMethod = "EQUAL_WEIGHT" | "SCORE_WEIGHTED" | "RISK_ADJUSTED" | "CONSERVATIVE_ALLOCATION" | "AGGRESSIVE_ALLOCATION";

export type OptimizerConfig = {
  run_name: string;
  universe_source: "WATCHLIST" | "CORE" | "EXTENDED" | "OPERATIONAL_BUY_CANDIDATES";
  optimization_method: OptimizationMethod;
  initial_capital_mode: "CURRENT_PORTFOLIO" | "CUSTOM_CAPITAL";
  custom_capital?: number | null;
  max_positions: number;
  min_position_weight: number;
  max_single_asset_weight: number;
  max_asset_class_weight: number;
  max_crypto_weight: number;
  cash_reserve_percent: number;
  min_data_quality_score: number;
  min_operational_confidence: string;
  require_real_data: boolean;
  include_ml: boolean;
  include_news: boolean;
  rebalance_threshold_percent: number;
  allow_sell: boolean;
  allow_buy: boolean;
  fee_percent: number;
};

export type OptimizationItem = {
  id?: number;
  symbol: string;
  current_weight: number;
  target_weight: number;
  current_value: number;
  target_value: number;
  delta_value: number;
  operational_signal?: string | null;
  data_quality_score?: number | null;
  ml_probability?: number | null;
  news_sentiment?: string | null;
  risk_level?: string | null;
  reason?: string | null;
};

export type RebalanceOrder = {
  id?: number;
  symbol: string;
  order_type: "BUY" | "SELL";
  quantity: number;
  estimated_price: number;
  estimated_gross_amount: number;
  estimated_fees: number;
  estimated_net_amount: number;
  reason?: string | null;
  status: string;
};

export type OptimizationRunSummary = {
  id: number;
  run_name: string;
  optimization_method: string;
  universe_source: string;
  current_total_value: number;
  target_invested_value: number;
  target_cash: number;
  expected_cash_after_rebalance: number;
  estimated_orders_count: number;
  estimated_fees: number;
  estimated_turnover_percent: number;
  created_at: string;
};

export type OptimizationRunFull = {
  summary: OptimizationRunSummary;
  config: OptimizerConfig;
  items: OptimizationItem[];
  proposed_orders: RebalanceOrder[];
  risk_summary: Record<string, any>;
  warnings: string[];
  blockers: string[];
};

export type ScenarioType = "CUSTOM" | "MARKET_CRASH" | "TECH_SELL_OFF" | "CRYPTO_CRASH" | "BOND_SHOCK" | "RATE_HIKE" | "RECESSION" | "INFLATION_SHOCK" | "BULL_RALLY";

export type ScenarioConfig = {
  scenario_name: string;
  scenario_type: ScenarioType;
  portfolio_source: "CURRENT_PORTFOLIO" | "LATEST_OPTIMIZED_PORTFOLIO" | "CUSTOM_TARGET";    
  asset_class_shocks: Record<string, number>;
  symbol_shocks: Record<string, number>;
  include_correlations: boolean;
  include_ml_risk: boolean;
  include_news_risk: boolean;
  include_liquidity_buffer: boolean;
  confidence_level: 95 | 99;
};

export type ScenarioAssetImpact = {
  id?: number;
  symbol: string;
  asset_type: string;
  current_value: number;
  shock_percent: number;
  stressed_value: number;
  absolute_impact: number;
  percentage_impact: number;
  loss_contribution_percent: number;
};

export type ScenarioClassImpact = {
  id?: number;
  asset_class: string;
  current_value: number;
  shock_percent: number;
  stressed_value: number;
  absolute_impact: number;
  percentage_impact: number;
};

export type ScenarioRunSummary = {
  id: number;
  scenario_name: string;
  scenario_type: string;
  portfolio_source: string;
  current_portfolio_value: number;
  stressed_portfolio_value: number;
  absolute_loss: number;
  percentage_loss: number;
  risk_level: string;
  created_at: string;
};

export type ScenarioRunFull = {
  summary: ScenarioRunSummary;
  config: ScenarioConfig;
  asset_impacts: ScenarioAssetImpact[];
  class_impacts: ScenarioClassImpact[];
  loss_contribution: Record<string, number>;
  mitigation_suggestions: string[];
  warnings: string[];
};

export type AppSnapshot = {
  id: number;
  snapshot_name: string;
  snapshot_type: string;
  file_path: string;
  checksum: string;
  size_bytes: number;
  tables_summary_json?: string | null;
  note?: string | null;
  created_at: string;
};

export type AppExport = {
  id: number;
  export_name: string;
  export_type: string;
  file_format: string;
  file_path: string;
  checksum: string;
  size_bytes: number;
  created_at: string;
};

export type AppImport = {
  id: number;
  import_name: string;
  import_type: string;
  file_name: string;
  status: string;
  records_processed: number;
  records_imported: number;
  records_failed: number;
  errors_json?: string | null;
  created_at: string;
};

export type HardeningCheck = {
  id?: number;
  check_name: string;
  status: "OK" | "WARNING" | "ERROR";
  message: string;
  details_json?: string | null;
  created_at?: string | null;
};

export type BackupStatus = {
  backup_directory: string;
  backups_count: number;
  latest_backup: AppSnapshot | null;
  database_size_bytes: number;
  integrity_status: string;
};

export type HardeningReport = {
  checks: HardeningCheck[];
  overall_status: string;
  timestamp: string;
};

export type AppSetting = {
  id: number;
  setting_key: string;
  setting_value_json: string;
  category: string;
  description?: string | null;
  updated_at: string;
  created_at: string;
};

export type RiskProfile = {
  id: number;
  profile_name: string;
  profile_type: string;
  is_active: boolean;
  max_single_asset_weight: number;
  max_asset_class_weight: number;
  max_crypto_weight: number;
  min_cash_reserve_percent: number;
  max_portfolio_drawdown_percent: number;
  min_data_quality_score: number;
  min_operational_confidence: string;
  require_real_data_for_buy: boolean;
  allow_crypto: boolean;
  allow_single_stocks: boolean;
  allow_bonds: boolean;
  allow_etf: boolean;
  allow_ml_influence: boolean;
  allow_news_influence: boolean;
  technical_weight: number;
  ml_weight: number;
  news_weight: number;
  risk_weight: number;
  created_at: string;
  updated_at: string;
};

export type StrategyProfile = {
  id: number;
  profile_name: string;
  description?: string | null;
  is_active: boolean;
  universe_level: string;
  max_positions: number;
  rebalance_frequency: string;
  buy_threshold: number;
  sell_threshold: number;
  watch_threshold: number;
  min_score_for_buy: number;
  min_confidence_for_buy: string;
  stop_loss_percent: number;
  take_profit_percent: number;
  trailing_stop_percent?: number | null;
  fee_percent: number;
  cash_reserve_percent: number;
  use_ml: boolean;
  use_news: boolean;
  use_scenario_risk: boolean;
  use_optimizer: boolean;
  config_json?: string | null;
  created_at: string;
  updated_at: string;
};

export type NotificationPreference = {
  id: number;
  alert_type: string;
  enabled: boolean;
  min_severity: string;
  show_in_dashboard: boolean;
  include_in_report: boolean;
  updated_at: string;
};

export type UIPreferences = {
  theme: string;
  default_landing_page: string;
  compact_mode: boolean;
  show_advanced_metrics: boolean;
  default_universe_level: string;
  default_benchmark: string;
  default_currency: string;
  updated_at: string;
};

export type MLTrainResult = {
  model_id: number;
  training_run: MLTrainingRun;
  metrics: Record<string, unknown>;
  features_used: string[];
  warnings: string[];
};

export type TaxDashboardSnapshot = {
  tax_year: number;
  realized_pnl_ytd: number;
  estimated_tax_due: number;
  unrealized_pnl: number;
};

export type TaxSettings = {
  id: number;
  country_code: string;
  tax_regime: string;
  capital_gain_tax_rate: number;
  crypto_tax_rate: number | null;
  dividend_tax_rate: number | null;
  lot_matching_method: string;
  include_fees_in_cost_basis: boolean;
  base_currency: string;
  loss_carryforward_balance: number;
  created_at: string;
  updated_at: string;
};

export type TaxLot = {
  id: number;
  portfolio_id: number;
  symbol: string;
  buy_order_id: number;
  buy_date: string;
  quantity_initial: number;
  quantity_remaining: number;
  buy_price: number;
  fees_allocated: number;
  cost_basis: number;
  created_at: string;
  updated_at: string;
};

export type TaxRealizedEvent = {
  id: number;
  portfolio_id: number;
  symbol: string;
  sell_order_id: number;
  buy_order_id: number | null;
  sell_date: string;
  quantity: number;
  buy_price: number;
  sell_price: number;
  cost_basis: number;
  proceeds: number;
  fees: number;
  realized_pnl: number;
  tax_year: number;
  tax_category: string;
  created_at: string;
};

export type TaxSummary = {
  portfolio_id: number;
  tax_year: number;
  country_code: string;
  tax_regime: string;
  total_realized_gains: number;
  total_realized_losses: number;
  net_realized_pnl: number;
  estimated_tax_due: number;
  unrealized_pnl: number;
  loss_carryforward: number;
  breakdown_by_asset_class: Record<string, number>;
  breakdown_by_symbol: Record<string, number>;
  warnings: string[];
  disclaimer: string;
};

export type TaxSummaryGlobal = {
  tax_year: number;
  country_code: string;
  tax_regime: string;
  total_realized_gains: number;
  total_realized_losses: number;
  net_realized_pnl: number;
  estimated_tax_due: number;
  unrealized_pnl: number;
  loss_carryforward: number;
  portfolio_summaries: TaxSummary[];
  warnings: string[];
  disclaimer: string;
};

export type TaxReport = {
  id: number;
  portfolio_id: number | null;
  tax_year: number;
  report_type: string;
  country_code: string;
  tax_regime: string;
  total_realized_gains: number;
  total_realized_losses: number;
  net_realized_pnl: number;
  estimated_tax_due: number;
  unrealized_pnl: number;
  loss_carryforward: number;
  summary_json: Record<string, unknown>;
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
  universe_summary: UniverseSummary;
  ml_status: MLStatus;
  latest_ml_prediction: MLPrediction | null;
  high_impact_news: NewsItem[];
  market_sentiment: MarketSentiment;
  system_health: SystemHealth | null;
  top_buy_candidates: ValidatedSignal[];
  data_quality_warnings: string[];
  latest_strategy_plan: StrategyPlanSummary | null;
  open_alerts_summary: AlertSummary | null;
  latest_scheduler_run: SchedulerRun | null;
  latest_operational_report: OperationalReport | null;
  latest_optimization_run: OptimizationRunSummary | null;
  latest_scenario_run: ScenarioRunSummary | null;
  backup_status: BackupStatus | null;
  hardening_report: HardeningReport | null;
  active_risk_profile: RiskProfile | null;
  active_strategy_profile: StrategyProfile | null;
  tax_snapshot: TaxDashboardSnapshot | null;
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
  portfolio_type: string | null;
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
  technical_score: number | null;
  news_score: number;
  final_score: number | null;
  news_sentiment_label: SentimentLabel | null;
  news_impact_level: ImpactLevel | null;
  news_count: number;
  latest_ml_prediction: MLPrediction | null;
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

export type MLModelType = "LOGISTIC_REGRESSION" | "RANDOM_FOREST";
export type MLTargetType = "POSITIVE_RETURN" | "OUTPERFORM_BENCHMARK" | "DRAWDOWN_RISK";

export type MLTrainingRun = {
  id: number | null;
  model_name: string;
  target_type: string;
  horizon_days: number;
  train_start_date: string | null;
  train_end_date: string | null;
  test_start_date: string | null;
  test_end_date: string | null;
  samples_count: number;
  accuracy: number | null;
  precision: number | null;
  recall: number | null;
  f1_score: number | null;
  roc_auc: number | null;
  created_at: string | null;
};

export type MLModelSummary = {
  id: number;
  model_name: string;
  model_type: string;
  target_type: string;
  horizon_days: number;
  symbols_scope: string[];
  features: string[];
  metrics: Record<string, unknown>;
  model_path: string | null;
  trained_at: string | null;
  created_at: string | null;
  training_run?: MLTrainingRun | null;
};

export type MLPrediction = {
  id: number | null;
  symbol: string;
  model_id: number;
  horizon_days: number;
  target_type: string;
  prediction_date: string;
  probabilities: Record<string, number | null>;
  probability_positive: number | null;
  probability_outperform: number | null;
  probability_drawdown: number | null;
  predicted_label: string;
  confidence: string;
  features_snapshot: Record<string, number>;
  explanation: {
    top_features_positive?: Array<{ feature: string; importance: number }>;
    top_features_negative?: Array<{ feature: string; importance: number }>;
    feature_values?: Record<string, number>;
    message?: string;
    warnings?: string[];
    [key: string]: unknown;
  };
  warnings: string[];
  created_at: string | null;
};

export type MLStatus = {
  models_count: number;
  latest_model: MLModelSummary | null;
  latest_training_run: MLTrainingRun | null;
  available_targets: string[];
  available_model_types: string[];
  ml_ready: boolean;
  message: string;
};

export type MLTrainInput = {
  model_name: string;
  model_type: MLModelType;
  target_type: MLTargetType;
  horizon_days: number;
  symbols: string[];
  benchmark_symbol: string;
  test_size_time_percent: number;
  min_samples: number;
};

export type UniverseLevel = "CORE" | "EXTENDED" | "CANDIDATE";

export type UniverseAsset = Asset & {
  asset_id: number | null;
  industry: string | null;
  universe_level: UniverseLevel;
  is_active: boolean;
  is_watchlisted: boolean;
  is_portfolio_asset: boolean;
  refresh_priority: number;
  refresh_frequency_days: number;
  last_price_refresh_at: string | null;
  last_signal_refresh_at: string | null;
  last_news_refresh_at: string | null;
  data_provider: string | null;
  notes: string | null;
  created_at: string | null;
};

export type UniverseSummary = {
  total_assets: number;
  core_count: number;
  extended_count: number;
  candidate_count: number;
  active_count: number;
  watchlist_count: number;
  portfolio_count: number;
  priced_assets_count: number;
  refresh_candidates_count: number;
  by_asset_type: Record<string, number>;
  by_country: Record<string, number>;
  by_exchange: Record<string, number>;
};

export type UniverseImportInput = {
  file_name: string;
  universe_level: UniverseLevel;
};

export type UniverseImportResult = UniverseImportInput & {
  inserted: number;
  updated: number;
  skipped: number;
  total_rows: number;
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

export type NewsRefreshResult = {
  symbol: string;
  provider: string | null;
  rows_inserted: number;
  rows_updated: number;
  used_cache: boolean;
  used_fallback: boolean;
  message: string;
};

export type NewsStatus = {
  enable_real_news: boolean;
  provider_status: NewsProviderStatus[];
  daily_usage: NewsDailyUsage;
  cache_status: Record<string, number>;
  last_refresh: string | null;
  news_sentiment_weight: number;
  news_cache_ttl_hours: number;
};

export type NewsSentimentSummary = {
  symbol: string;
  lookback_days: number;
  news_count: number;
  average_sentiment_score: number;
  sentiment_label: SentimentLabel;
  impact_level: ImpactLevel;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  latest_news: NewsLatest[];
};

export type NewsSentimentSummaryOut = NewsSentimentSummary;

export type NewsProviderStatus = {
  provider: string;
  enabled: boolean;
  api_key_configured: boolean;
  daily_limit: number;
  calls_today: number;
  supports: string[];
};

export type NewsDailyUsage = {
  provider: string;
  usage_date: string;
  calls_count: number;
  daily_limit: number;
};

export type NewsLatest = {
  id: number;
  title: string;
  summary: string | null;
  url: string | null;
  source: string | null;
  published_at: string | null;
  sentiment_label: SentimentLabel;
  sentiment_score: number;
  impact_level: ImpactLevel;
  relevance_score: number;
};

export type OptimizationRunFullOut = OptimizationRunFull;
export type ScenarioRunFullOut = ScenarioRunFull;
export type AppSnapshotOut = AppSnapshot;
export type AppExportOut = AppExport;
export type AppImportOut = AppImport;
export type HardeningCheckOut = HardeningCheck;
export type BackupStatusOut = BackupStatus;
export type HardeningReportOut = HardeningReport;
export type AppSettingOut = AppSetting;
export type RiskProfileOut = RiskProfile;
export type StrategyProfileOut = StrategyProfile;
export type NotificationPreferenceOut = NotificationPreference;
export type UIPreferencesOut = UIPreferences;

export type PortfolioType = "CORE" | "GROWTH" | "CRYPTO" | "DIVIDEND" | "SPECULATIVE" | "FAMILY" | "CUSTOM" | "EXTERNAL_TRACKER";
export type TransferType = "DEPOSIT" | "WITHDRAWAL" | "INTERNAL_TRANSFER";

export type Portfolio = {
  id: number;
  portfolio_name: string;
  description: string | null;
  portfolio_type: string;
  base_currency: string;
  initial_cash: number;
  current_cash: number;
  risk_profile_id: number | null;
  strategy_profile_id: number | null;
  is_active: boolean;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
};

export type PortfolioCreateIn = {
  portfolio_name: string;
  description?: string | null;
  portfolio_type?: PortfolioType;
  base_currency?: string;
  initial_cash?: number;
  risk_profile_id?: number | null;
  strategy_profile_id?: number | null;
};

export type PortfolioUpdateIn = {
  portfolio_name?: string | null;
  description?: string | null;
  portfolio_type?: PortfolioType | null;
  risk_profile_id?: number | null;
  strategy_profile_id?: number | null;
  is_archived?: boolean | null;
};

export type PortfolioCloneIn = {
  new_name: string;
  include_positions: boolean;
  include_orders: boolean;
};

export type CashTransferIn = {
  from_portfolio_id?: number | null;
  to_portfolio_id?: number | null;
  amount: number;
  transfer_type: TransferType;
  note?: string | null;
};

export type CashTransfer = {
  id: number;
  from_portfolio_id: number | null;
  to_portfolio_id: number | null;
  amount: number;
  currency: string;
  transfer_type: string;
  note: string | null;
  created_at: string;
};

export type ConsolidatedSummary = {
  total_value: number;
  total_cash: number;
  total_invested: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_pnl: number;
  total_pnl_percent: number;
  portfolios_count: number;
  active_portfolios_count: number;
  allocation_by_asset_type: Record<string, number>;
  allocation_by_currency: Record<string, number>;
  portfolio_summaries: any[];
};

export type PortfolioPerformanceComparison = {
  portfolios: any[];
  best_performer: any | null;
  worst_performer: any | null;
  risk_comparison: any[];
};

export type GoogleSheetsStatus = {
  enabled: boolean;
  auth_mode: string;
  credentials_configured: boolean;
  token_exists: boolean;
  spreadsheet_configured: boolean;
  connection_ok: boolean;
  available_ranges: string[];
  message: string | null;
};

export type GoogleSheetsPreviewIn = {
  import_type: "PORTFOLIO" | "TRANSACTIONS" | "CASH" | "WATCHLIST" | "MIXED";
};

export type GoogleSheetsPreviewOut = {
  import_id: number;
  rows_total: number;
  rows_valid: number;
  rows_invalid: number;
  warnings: string[];
  errors: string[];
  preview_rows: any[];
};

export type GoogleSheetsImportConfirmIn = {
  confirm: boolean;
  mode: "PREVIEW_ONLY" | "CREATE_READONLY_PORTFOLIO" | "UPDATE_WATCHLIST";
};

export type ExternalImport = {
  id: number;
  import_name: string;
  source_type: string;
  import_type: string;
  status: string;
  import_mode: string;
  rows_total: number;
  rows_valid: number;
  rows_invalid: number;
  created_at: string;
  updated_at: string;
};

export type ExternalImportDetail = ExternalImport & {
  spreadsheet_id_hash?: string | null;
  sheet_range?: string | null;
  warnings: string[];
  errors: string[];
  positions: any[];
  transactions: any[];
  cash: any[];
  watchlist: any[];
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

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: "PUT",
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

export const api = {
  getSystemHealth: () => apiGet<SystemHealth>("/system/health"),
  getSystemAudit: () => apiGet<SystemHealth>("/system/audit"),
  getAllDataQuality: () => apiGet<DataQualityCheck[]>("/quality/data"),
  getAssetDataQuality: (symbol: string) => apiGet<DataQualityCheck>(`/quality/data/${symbol}`),
  getAllValidatedSignals: () => apiGet<ValidatedSignal[]>("/signals/validated"),
  getAssetValidatedSignal: (symbol: string) => apiGet<ValidatedSignal>(`/signals/validated/${symbol}`),
  getOperationalRanking: (portfolio_id?: number) => apiGet<OperationalRanking>(`/ranking/operational${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  getPortfolioActions: (portfolio_id?: number) => apiGet<PortfolioAction[]>(`/portfolio/actions${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  generateStrategyPlan: (config: StrategyPlanConfig, portfolio_id?: number) => apiPost<StrategyPlanFull>(`/strategy/plans/generate${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`, config),
  listStrategyPlans: (portfolio_id?: number) => apiGet<StrategyPlanSummary[]>(`/strategy/plans${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  getStrategyPlan: (id: number) => apiGet<StrategyPlanFull>(`/strategy/plans/${id}`),
  applyStrategyPlan: (id: number) => apiPost<{ orders_created: number }>(`/strategy/plans/${id}/apply-paper`),
  deleteStrategyPlan: (id: number) => apiDelete<{ success: boolean }>(`/strategy/plans/${id}`),
  getDefaultStrategyConfig: () => apiGet<StrategyPlanConfig>("/strategy/default-config"),
  
  // PORTFOLIOS
  listPortfolios: (include_archived: boolean = false) => apiGet<Portfolio[]>(`/portfolios?include_archived=${include_archived}`),
  createPortfolio: (payload: PortfolioCreateIn) => apiPost<Portfolio>("/portfolios", payload),
  getActivePortfolio: () => apiGet<Portfolio>("/portfolios/active"),
  activatePortfolio: (id: number) => apiPost<{ success: boolean }>(`/portfolios/${id}/activate`, {}),
  getPortfolioDetail: (id: number) => apiGet<Portfolio>(`/portfolios/${id}`),
  updatePortfolio: (id: number, payload: PortfolioUpdateIn) => apiPut<Portfolio>(`/portfolios/${id}`, payload),
  deletePortfolio: (id: number) => apiDelete<{ success: boolean }>(`/portfolios/${id}`),
  clonePortfolio: (id: number, payload: PortfolioCloneIn) => apiPost<Portfolio>(`/portfolios/${id}/clone`, payload),
  transferCash: (payload: CashTransferIn) => apiPost<CashTransfer>("/portfolios/transfer-cash", payload),
  getConsolidatedSummary: () => apiGet<ConsolidatedSummary>("/portfolios/consolidated-summary"),
  getPerformanceComparison: () => apiGet<PortfolioPerformanceComparison>("/portfolios/performance-comparison"),

  // ALERTS
  listAlerts: (status?: string, severity?: string, symbol?: string, portfolio_id?: number) => {
    let url = "/alerts?";
    if (portfolio_id) url += `portfolio_id=${portfolio_id}&`;
    if (status) url += `status=${status}&`;
    if (severity) url += `severity=${severity}&`;
    if (symbol) url += `symbol=${symbol}&`;
    return apiGet<Alert[]>(url);
  },
  getAlertSummary: (portfolio_id?: number) => apiGet<AlertSummary>(`/alerts/summary${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  acknowledgeAlert: (id: number) => apiPost<{ success: boolean }>(`/alerts/${id}/acknowledge`, {}),
  closeAlert: (id: number) => apiPost<{ success: boolean }>(`/alerts/${id}/close`, {}),
  getAlertRules: () => apiGet<AlertRule[]>("/alerts/rules"),
  toggleAlertRule: (id: number, enabled: boolean) => apiPost<{ success: boolean }>(`/alerts/rules/${id}/toggle`, { enabled }),
  evaluateAlerts: () => apiPost<{ success: boolean }>("/alerts/evaluate", {}),

  // SCHEDULER
  listSchedulerRuns: () => apiGet<SchedulerRun[]>("/scheduler/runs"),
  runScheduler: (payload: { run_type: string, limit?: number, force?: boolean, generate_report?: boolean }) => 
    apiPost<SchedulerRun>("/scheduler/run", payload),

  // REPORTS
  listReports: (portfolio_id?: number) => apiGet<OperationalReport[]>(`/reports${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  getLatestReport: () => apiGet<OperationalReport | null>("/reports/latest"),
  getReport: (id: number) => apiGet<OperationalReport>(`/reports/${id}`),
  generateReport: (report_type: string = "MANUAL", portfolio_id?: number) => apiPost<OperationalReport>(`/reports/generate?report_type=${report_type}${portfolio_id ? `&portfolio_id=${portfolio_id}` : ""}`, {}),

  // OPTIMIZER
  getDefaultOptimizerConfig: () => apiGet<OptimizerConfig>("/optimizer/default-config"),
  runOptimization: (config: OptimizerConfig, portfolio_id?: number) => apiPost<OptimizationRunFull>(`/optimizer/run${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`, config),
  listOptimizationRuns: (portfolio_id?: number) => apiGet<OptimizationRunSummary[]>(`/optimizer/runs${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  getOptimizationRun: (id: number) => apiGet<OptimizationRunFull>(`/optimizer/runs/${id}`),
  applyRebalanceOrders: (id: number) => apiPost<{ orders_created: number }>(`/optimizer/runs/${id}/create-paper-orders`, {}),
  deleteOptimizationRun: (id: number) => apiDelete<{ success: boolean }>(`/optimizer/runs/${id}`),

  // SCENARIOS
  getDefaultScenarioConfig: () => apiGet<ScenarioConfig>("/scenarios/default-config"),
  getScenarioPresets: () => apiGet<{ id: string, label: string }[]>("/scenarios/presets"),
  runScenarioAnalysis: (config: ScenarioConfig, portfolio_id?: number) => apiPost<ScenarioRunFull>(`/scenarios/run${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`, config),
  listScenarioRuns: (portfolio_id?: number) => apiGet<ScenarioRunSummary[]>(`/scenarios/runs${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  getScenarioRun: (id: number) => apiGet<ScenarioRunFull>(`/scenarios/runs/${id}`),
  deleteScenarioRun: (id: number) => apiDelete<{ success: boolean }>(`/scenarios/runs/${id}`),

  // PORTFOLIO CORE
  getPortfolio: (portfolio_id?: number) => apiGet<PortfolioSummary>(`/portfolio${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  initPortfolio: (payload: any, portfolio_id?: number) => apiPost<PortfolioSummary>(`/portfolio/init${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`, payload),
  simulateOrder: (payload: SimulatedOrderInput, portfolio_id?: number) => apiPost<OrderSimulationResponse>(`/orders/simulate${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`, payload),
  listOrders: (portfolio_id?: number) => apiGet<SimulatedOrder[]>(`/orders${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  getPortfolioSnapshots: (portfolio_id?: number) => apiGet<PortfolioSnapshot[]>(`/portfolio/snapshots${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),
  refreshPortfolio: (portfolio_id?: number) => apiPost<PortfolioSummary>(`/portfolio/refresh${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`, {}),
  getPortfolioRecommendations: (portfolio_id?: number) => apiGet<PortfolioRecommendation[]>(`/portfolio/recommendations${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),

  // SETTINGS
  getAppSettings: () => apiGet<AppSetting[]>("/settings"),
  updateAppSetting: (key: string, value_json: string, description?: string) => apiPut<{ success: boolean }>(`/settings/${key}`, { setting_value_json: value_json, description }),
  listRiskProfiles: () => apiGet<RiskProfile[]>("/settings/risk-profiles"),
  getActiveRiskProfile: () => apiGet<RiskProfile>("/settings/risk-profiles/active"),
  createRiskProfile: (p: any) => apiPost<RiskProfile>("/settings/risk-profiles", p),
  updateRiskProfile: (id: number, p: any) => apiPut<RiskProfile>(`/settings/risk-profiles/${id}`, p),
  activateRiskProfile: (id: number) => apiPost<{ success: boolean }>(`/settings/risk-profiles/${id}/activate`, {}),
  deleteRiskProfile: (id: number) => apiDelete<{ success: boolean }>(`/settings/risk-profiles/${id}`),
  listStrategyProfiles: () => apiGet<StrategyProfile[]>("/settings/strategy-profiles"),
  getActiveStrategyProfile: () => apiGet<StrategyProfile>("/settings/strategy-profiles/active"),
  activateStrategyProfile: (id: number) => apiPost<{ success: boolean }>(`/settings/strategy-profiles/${id}/activate`, {}),
  listNotifications: () => apiGet<NotificationPreference[]>("/settings/notifications"),
  updateNotification: (alert_type: string, p: any) => apiPut<{ success: boolean }>("/settings/notifications", { alert_type, ...p }),
  getUiPreferences: () => apiGet<UIPreferences>("/settings/ui"),
  updateUiPreferences: (p: any) => apiPut<{ success: boolean }>("/settings/ui", p),
  dashboard: (portfolio_id?: number) => apiGet<DashboardResponse>(`/dashboard${portfolio_id ? `?portfolio_id=${portfolio_id}` : ""}`),

  // GOOGLE SHEETS
  getGoogleSheetsStatus: () => apiGet<GoogleSheetsStatus>("/google-sheets/status"),
  authorizeGoogleSheets: () => apiPost<{ success: boolean; message: string }>("/google-sheets/authorize", {}),
  testGoogleSheetsConnection: () => apiPost<{ success: boolean; message: string }>("/google-sheets/test-connection", {}),
  previewGoogleSheetsImport: (payload: GoogleSheetsPreviewIn) => apiPost<GoogleSheetsPreviewOut>("/google-sheets/preview", payload),
  confirmGoogleSheetsImport: (import_id: number, payload: GoogleSheetsImportConfirmIn) => apiPost<any>(`/google-sheets/import/${import_id}/confirm`, payload),
  listGoogleSheetsImports: () => apiGet<ExternalImport[]>("/google-sheets/imports"),
  getGoogleSheetsImportDetail: (import_id: number) => apiGet<ExternalImportDetail>(`/google-sheets/imports/${import_id}`),
  getGoogleSheetsTemplates: () => apiGet<Record<string, string[]>>("/google-sheets/templates"),

  // BACKUP
  getBackupStatus: () => apiGet<BackupStatus>("/backup/status"),
  createBackup: (snapshot_name?: string, note?: string) => apiPost<AppSnapshot>("/backup/create", { snapshot_name, note }),
  listBackups: () => apiGet<AppSnapshot[]>("/backup/list"),
  getBackupDetail: (id: number) => apiGet<AppSnapshot>(`/backup/${id}`),
  restoreBackup: (id: number, confirm: boolean) => apiPost<{ success: boolean, message: string }>(`/backup/${id}/restore`, { confirm }),
  deleteBackup: (id: number) => apiDelete<{ success: boolean }>(`/backup/${id}`),

  // EXPORT
  getExportTypes: () => apiGet<string[]>("/export/types"),
  createExport: (export_type: string, file_format: string) => apiPost<AppExport>("/export/create", { export_type, file_format }),
  listExports: () => apiGet<AppExport[]>("/export/list"),

  // IMPORT
  getImportTypes: () => apiGet<string[]>("/import/types"),
  validateImport: (file_name: string, import_type: string) => apiPost<any>("/import/validate", { file_name, import_type }),
  runImport: (file_name: string, import_type: string, confirm: boolean) => apiPost<AppImport>("/import/run", { file_name, import_type, confirm }),

  // HARDENING
  getHardeningReport: () => apiGet<HardeningReport>("/hardening/report"),
  runHardeningChecks: () => apiPost<HardeningReport>("/hardening/run", {}),

  // TAX
  getTaxSettings: () => apiGet<TaxSettings>("/tax/settings"),
  updateTaxSettings: (payload: Partial<TaxSettings>) => apiPut<TaxSettings>("/tax/settings", payload),
  getTaxSummary: (portfolio_id?: number, tax_year?: number) => {
    const params = new URLSearchParams();
    if (portfolio_id) params.set("portfolio_id", String(portfolio_id));
    if (tax_year) params.set("tax_year", String(tax_year));
    const q = params.toString();
    return apiGet<TaxSummary>(`/tax/summary${q ? `?${q}` : ""}`);
  },
  getTaxSummaryGlobal: (tax_year?: number) =>
    apiGet<TaxSummaryGlobal>(`/tax/summary/global${tax_year ? `?tax_year=${tax_year}` : ""}`),
  getTaxLots: (portfolio_id?: number, symbol?: string) => {
    const params = new URLSearchParams();
    if (portfolio_id) params.set("portfolio_id", String(portfolio_id));
    if (symbol) params.set("symbol", symbol);
    const q = params.toString();
    return apiGet<TaxLot[]>(`/tax/lots${q ? `?${q}` : ""}`);
  },
  getTaxRealizedEvents: (portfolio_id?: number, tax_year?: number, symbol?: string) => {
    const params = new URLSearchParams();
    if (portfolio_id) params.set("portfolio_id", String(portfolio_id));
    if (tax_year) params.set("tax_year", String(tax_year));
    if (symbol) params.set("symbol", symbol);
    const q = params.toString();
    return apiGet<TaxRealizedEvent[]>(`/tax/realized-events${q ? `?${q}` : ""}`);
  },
  recalculateTax: (payload: { portfolio_id?: number; tax_year?: number; method?: string }) =>
    apiPost<{ portfolios_processed: number; method: string }>("/tax/recalculate", payload),
  generateTaxReport: (payload: { tax_year: number; portfolio_id?: number; report_type?: string }) =>
    apiPost<TaxReport>("/tax/report/generate", payload),
  listTaxReports: (portfolio_id?: number, tax_year?: number) => {
    const params = new URLSearchParams();
    if (portfolio_id) params.set("portfolio_id", String(portfolio_id));
    if (tax_year) params.set("tax_year", String(tax_year));
    const q = params.toString();
    return apiGet<TaxReport[]>(`/tax/reports${q ? `?${q}` : ""}`);
  },
  getTaxReport: (id: number) => apiGet<TaxReport>(`/tax/reports/${id}`),
  exportTaxReport: (payload: { tax_year: number; portfolio_id?: number; format: string }) =>
    apiPost<{ file_path: string; file_format: string; disclaimer: string }>("/tax/export", payload),

  // MARKET DATA
  getAssets: () => apiGet<Asset[]>("/assets"),
  getAsset: (symbol: string) => apiGet<Asset>(`/assets/${symbol}`),
  getPriceHistory: (symbol: string) => apiGet<PriceHistory>(`/prices/${symbol}`),
  getTechnicalAnalysis: (symbol: string) => apiGet<TechnicalAnalysis>(`/analysis/${symbol}`),
  getUniverse: (level?: string) => apiGet<UniverseAsset[]>(`/universe${level ? `?level=${level}` : ""}`),
  getUniverseSummary: () => apiGet<UniverseSummary>("/universe/summary"),
};
