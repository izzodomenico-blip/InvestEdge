# Graph Report - InvestEdge  (2026-05-22)

## Corpus Check
- 114 files · ~84,435 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1285 nodes · 3111 edges · 80 communities (67 shown, 13 thin omitted)
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 671 edges (avg confidence: 0.74)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `22cd96ef`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]

## God Nodes (most connected - your core abstractions)
1. `db_session()` - 138 edges
2. `PortfolioEngine` - 46 edges
3. `MLEngine` - 38 edges
4. `Backtest Engine` - 38 edges
5. `UserSettingsService` - 35 edges
6. `BacktestEngine` - 34 edges
7. `Portfolio Engine` - 33 edges
8. `MultiPortfolioService` - 30 edges
9. `Panel()` - 29 edges
10. `UniverseService` - 28 edges

## Surprising Connections (you probably didn't know these)
- `test_repeated_refresh_does_not_duplicate_price_history()` --calls--> `db_session()`  [INFERRED]
  tests/test_api.py → backend/app/database.py
- `test_news_dedup_does_not_duplicate()` --calls--> `db_session()`  [INFERRED]
  tests/test_news.py → backend/app/database.py
- `Local backtest engine for simulated strategies only.` --rationale_for--> `Backtest Engine`  [EXTRACTED]
  backend/app/services/backtest_engine.py → README.md
- `Paper-trading portfolio engine. No real broker actions are performed.` --rationale_for--> `Portfolio Engine`  [EXTRACTED]
  backend/app/services/portfolio_engine.py → README.md
- `InvestEdge Project` --references--> `TechnicalAnalysis`  [EXTRACTED]
  README.md → frontend/src/lib/api.ts

## Communities (80 total, 13 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (57): acknowledge_alert(), activate_portfolio(), activate_risk_profile(), activate_strategy_profile(), clone_portfolio(), close_alert(), create_backup(), create_portfolio() (+49 more)

### Community 1 - "Community 1"
Cohesion: 0.10
Nodes (24): admin_seed(), _database_file(), get_connection(), init_db(), migrate_db(), _table_columns(), create_app(), lifespan() (+16 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (20): MockMarketDataProvider, NewsEngine, _now(), News orchestration engine. Mock/fallback by default, real provider opt-in., Compute optional news_score (-NEWS_SENTIMENT_WEIGHT .. +NEWS_SENTIMENT_WEIGHT)., aggregate_news_sentiment(), _clamp(), classify_sentiment() (+12 more)

### Community 3 - "Community 3"
Cohesion: 0.40
Nodes (5): PricePoint, PriceHistoryOut, PricePointOut, _clean_float(), get_price_history()

### Community 4 - "Community 4"
Cohesion: 0.14
Nodes (15): BacktestEquityPoint, BacktestPosition, BacktestTrade, BacktestEquityPointOut, BacktestPositionOut, BacktestSummaryOut, BacktestTradeOut, Backtest Engine (+7 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (22): PortfolioPosition, allocation, AssetType, backtestCurve, equityCurve, newsItems, portfolioPositions, Signal (+14 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (65): data_status(), data_usage(), get_universe_summary(), import_universe(), ml_status(), ml_training_runs(), news_sentiment(), news_status() (+57 more)

### Community 7 - "Community 7"
Cohesion: 0.05
Nodes (49): ApiUsage, AppExportOut, AppImport, AppImportOut, AppSetting, AppSettingOut, AppSnapshotOut, AssetDataStatus (+41 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (10): _backtest_payload(), _price_frame(), test_backtest_history_and_detail_endpoints(), test_repeated_refresh_does_not_duplicate_price_history(), test_run_backtest_buy_and_hold(), test_run_backtest_score_threshold(), test_run_backtest_top_n_score(), test_technical_analysis_decreasing_series() (+2 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (25): AppShell(), AppShellProps, PortfolioSelector(), PortfolioSelectorProps, navItems, Sidebar(), Alert, AlertRule (+17 more)

### Community 10 - "Community 10"
Cohesion: 0.32
Nodes (3): refresh_portfolio(), MarketDataService, _now()

### Community 11 - "Community 11"
Cohesion: 0.24
Nodes (5): _asset_type(), _clean(), _now(), _risk_level(), UniverseService

### Community 12 - "Community 12"
Cohesion: 0.29
Nodes (11): SignalBadge(), SignalBadgeProps, styles, PortfolioRecommendation, PortfolioSnapshot, Signal, assetTypeLabels, colors (+3 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (33): AlertOut, AlertRuleOut, AlertSummaryOut, DataQualityCheckOut, OperationalRankingOut, OperationalReportOut, PortfolioActionOut, SchedulerRunIn (+25 more)

### Community 14 - "Community 14"
Cohesion: 0.16
Nodes (7): BaseNewsProvider, NewsMissingApiKey, NewsProviderError, NewsRateLimitExceeded, NewsRealDisabled, utc_now(), RuntimeError

### Community 15 - "Community 15"
Cohesion: 0.22
Nodes (9): devDependencies, autoprefixer, postcss, tailwindcss, @types/react, @types/react-dom, typescript, vite (+1 more)

### Community 16 - "Community 16"
Cohesion: 0.18
Nodes (8): ABC, Settings, BaseMarketDataProvider, MissingApiKey, ProviderError, RateLimitExceeded, RealDataDisabled, utc_now()

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, allowSyntheticDefaultImports, esModuleInterop, forceConsistentCasingInFileNames, isolatedModules, jsx, lib (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.07
Nodes (15): MLTrainInput, MLTrainIn, MLDatasetService, MLEngine, _now(), test_build_dataset_without_lookahead(), test_ml_models_endpoint(), test_ml_predict_endpoint() (+7 more)

### Community 19 - "Community 19"
Cohesion: 0.19
Nodes (5): AlphaVantageProvider, AlphaVantageNewsProvider, _parse_time(), _symbol_sentiment(), test_alpha_vantage_news_normalization()

### Community 20 - "Community 20"
Cohesion: 0.18
Nodes (14): ImpactLevel, NewsItem, NewsStatus, SentimentLabel, Filter, filters, impactTone, NewsPage() (+6 more)

### Community 21 - "Community 21"
Cohesion: 0.23
Nodes (17): apiDelete(), apiGet(), apiPost(), apiPut(), BacktestResult, BacktestRunInput, BacktestStrategy, BacktestSummary (+9 more)

### Community 22 - "Community 22"
Cohesion: 0.12
Nodes (11): RiskProfileCreateIn, UIPerferencesOut, _now(), UserSettingsService, mock_db(), test_activate_profile(), test_active_risk_profile(), test_create_custom_profile() (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.18
Nodes (15): MetricCard(), MetricCardProps, tones, Panel(), PanelProps, DataRefreshResult, DataStatus, UniverseImportResult (+7 more)

### Community 26 - "Community 26"
Cohesion: 0.25
Nodes (7): compilerOptions, allowSyntheticDefaultImports, composite, module, moduleResolution, skipLibCheck, include

### Community 27 - "Community 27"
Cohesion: 0.36
Nodes (9): OrderSimulationResponse, PortfolioSummary, SimulatedOrder, SimulatedOrderInput, assetTypeLabels, FormState, initialForm, OrderSide (+1 more)

### Community 28 - "Community 28"
Cohesion: 0.08
Nodes (25): apply_strategy_plan(), asset_data_status(), create_export(), create_optimizer_paper_orders(), delete_risk_profile(), get_asset_validated_signal(), get_backtest(), get_backup_detail() (+17 more)

### Community 46 - "Community 46"
Cohesion: 0.08
Nodes (26): Alert & Scheduler (Step 11), Analisi tecnica, Avvio backend, Avvio frontend, Backtest Engine, Backup & Data Management (Step 15), code:text (backend/), code:powershell (backend\.venv\Scripts\python.exe scripts\seed_database.py --) (+18 more)

### Community 47 - "Community 47"
Cohesion: 0.16
Nodes (12): OptimizationItemOut, OptimizationRunFullOut, OptimizationRunSummaryOut, OptimizerConfig, RebalanceOrderOut, SimulatedOrderIn, _now(), PortfolioOptimizerService (+4 more)

### Community 48 - "Community 48"
Cohesion: 0.09
Nodes (22): DashboardResponse, OperationalReport, OptimizationRunFull, OptimizationRunSummary, OptimizerConfig, ScenarioConfig, ScenarioRunFull, ScenarioRunSummary (+14 more)

### Community 49 - "Community 49"
Cohesion: 0.18
Nodes (12): StrategyPlanConfig, StrategyPlanFullOut, StrategyPlanItemOut, StrategyPlanOrderOut, StrategyPlanSummaryOut, _now(), StrategyControlService, test_apply_plan_creates_simulated_orders() (+4 more)

### Community 50 - "Community 50"
Cohesion: 0.27
Nodes (10): get_asset(), get_assets(), post_asset(), _asset_from_base_row(), create_asset(), get_asset_by_symbol(), _latest_price_metadata(), _latest_price_metrics() (+2 more)

### Community 51 - "Community 51"
Cohesion: 0.24
Nodes (10): MLModelType, MLStatus, MLTargetType, MLTrainingRun, MLTrainResult, confidenceTone(), MachineLearningPage(), metricValue() (+2 more)

### Community 52 - "Community 52"
Cohesion: 0.40
Nodes (3): BaseNewsProvider, MockNewsProvider, test_mock_news_provider_returns_items()

### Community 53 - "Community 53"
Cohesion: 0.24
Nodes (6): ProviderRegistry, SystemHealthOut, _now(), SystemHealthService, test_provider_registry(), test_system_health()

### Community 54 - "Community 54"
Cohesion: 0.36
Nodes (6): _csv(), from_env(), get_settings(), _unique(), test_api_cache_save_and_read(), test_api_rate_limit_guard()

### Community 55 - "Community 55"
Cohesion: 0.50
Nodes (5): ml_model_detail(), ml_models(), MLModelSummary, MLModelDetailOut, MLModelSummaryOut

### Community 56 - "Community 56"
Cohesion: 0.21
Nodes (8): Enum, AlertSeverity, AlertStatus, AssetCreate, AssetOut, OptimizationMethod, ScenarioType, _asset_from_row()

### Community 57 - "Community 57"
Cohesion: 0.14
Nodes (11): CashTransferIn, CashTransferOut, ConsolidatedSummaryOut, PortfolioCloneIn, PortfolioCreateIn, PortfolioOut, PortfolioPerformanceComparisonOut, PortfolioUpdateIn (+3 more)

### Community 58 - "Community 58"
Cohesion: 0.46
Nodes (7): Asset, NewsSentimentSummary, PriceHistory, AnalysisPage(), formatIndicator(), indicatorLabels, subscoreLabels

### Community 63 - "Community 63"
Cohesion: 0.20
Nodes (9): ScenarioAssetImpactOut, ScenarioClassImpactOut, ScenarioRunSummaryOut, _now(), ScenarioService, test_custom_symbol_shock(), test_market_crash_scenario(), test_mitigation_suggestions() (+1 more)

### Community 64 - "Community 64"
Cohesion: 0.17
Nodes (15): generate_strategy_plan(), get_active_portfolio(), get_buy_candidates(), get_excluded_candidates(), get_operational_ranking(), get_portfolio(), get_portfolio_actions(), get_portfolio_detail() (+7 more)

### Community 67 - "Community 67"
Cohesion: 0.33
Nodes (4): _clamp(), _is_number(), Explainable technical scoring engine., ScoringEngine

### Community 68 - "Community 68"
Cohesion: 0.27
Nodes (9): dashboard(), list_news(), news_for_symbol(), MarketSentiment, DashboardOut, NewsItemOut, get_dashboard(), _high_impact_news() (+1 more)

### Community 70 - "Community 70"
Cohesion: 0.33
Nodes (8): get_signal(), get_signals(), SignalOut, get_signal_by_symbol(), _json_dict(), _json_list(), list_signals(), _signal_from_row()

### Community 71 - "Community 71"
Cohesion: 0.32
Nodes (7): technical_analysis(), TechnicalAnalysis, TechnicalAnalysisOut, _safe_bool(), _safe_divide(), _safe_float(), get_technical_analysis()

### Community 74 - "Community 74"
Cohesion: 0.29
Nodes (8): FastAPI Main App, Python Dependencies, Backend Service, Frontend Service, React Entry Point, InvestEdge Project, Machine Learning Module, Universe Manager

### Community 75 - "Community 75"
Cohesion: 0.25
Nodes (7): name, private, scripts, build, dev, preview, version

### Community 76 - "Community 76"
Cohesion: 0.48
Nodes (7): add_universe_watchlist(), get_universe(), get_universe_refresh_candidates(), promote_universe(), remove_universe_watchlist(), UniverseAsset, UniverseAssetOut

### Community 77 - "Community 77"
Cohesion: 0.43
Nodes (5): type, test_create_backup(), test_export_json(), test_hardening_report(), test_restore_requires_confirm()

### Community 78 - "Community 78"
Cohesion: 0.33
Nodes (6): dependencies, lucide-react, react, react-dom, react-router-dom, recharts

### Community 79 - "Community 79"
Cohesion: 0.50
Nodes (4): ml_predict(), ml_predictions(), MLPrediction, MLPredictionOut

## Knowledge Gaps
- **129 isolated node(s):** `allow`, `BeforeTool`, `name`, `private`, `version` (+124 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `db_session()` connect `Community 0` to `Community 1`, `Community 2`, `Community 6`, `Community 8`, `Community 10`, `Community 18`, `Community 19`, `Community 28`, `Community 50`, `Community 52`, `Community 53`, `Community 54`, `Community 55`, `Community 64`, `Community 68`, `Community 70`, `Community 71`, `Community 76`, `Community 79`?**
  _High betweenness centrality (0.141) - this node is a cross-community bridge._
- **Why does `TechnicalAnalysis` connect `Community 71` to `Community 0`, `Community 65`, `Community 6`, `Community 7`, `Community 74`, `Community 58`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `UserSettingsService` connect `Community 22` to `Community 49`, `Community 13`, `Community 6`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Are the 136 inferred relationships involving `db_session()` (e.g. with `get_system_health()` and `get_system_audit()`) actually correct?**
  _`db_session()` has 136 INFERRED edges - model-reasoned connections that need verification._
- **Are the 61 inferred relationships involving `str` (e.g. with `_database_file()` and `get_asset_validated_signal()`) actually correct?**
  _`str` has 61 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `PortfolioEngine` (e.g. with `AlertService` and `MarketDataService`) actually correct?**
  _`PortfolioEngine` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `MLEngine` (e.g. with `MLDatasetService` and `UniverseService`) actually correct?**
  _`MLEngine` has 8 INFERRED edges - model-reasoned connections that need verification._