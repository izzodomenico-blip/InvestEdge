# Graph Report - InvestEdge  (2026-05-21)

## Corpus Check
- 99 files · ~67,567 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1043 nodes · 2565 edges · 63 communities (52 shown, 11 thin omitted)
- Extraction: 79% EXTRACTED · 21% INFERRED · 0% AMBIGUOUS · INFERRED: 532 edges (avg confidence: 0.74)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5848ee86`
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

## God Nodes (most connected - your core abstractions)
1. `db_session()` - 98 edges
2. `PortfolioEngine` - 42 edges
3. `MLEngine` - 38 edges
4. `Backtest Engine` - 38 edges
5. `BacktestEngine` - 34 edges
6. `Portfolio Engine` - 33 edges
7. `UniverseService` - 28 edges
8. `AlphaVantageProvider` - 25 edges
9. `AlertService` - 25 edges
10. `NewsEngine` - 25 edges

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

## Communities (63 total, 11 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (80): acknowledge_alert(), add_universe_watchlist(), apply_strategy_plan(), asset_data_status(), close_alert(), create_optimizer_paper_orders(), data_status(), data_usage() (+72 more)

### Community 1 - "Community 1"
Cohesion: 0.11
Nodes (21): admin_seed(), _database_file(), get_connection(), init_db(), migrate_db(), _table_columns(), create_app(), lifespan() (+13 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (20): MockMarketDataProvider, NewsEngine, _now(), News orchestration engine. Mock/fallback by default, real provider opt-in., Compute optional news_score (-NEWS_SENTIMENT_WEIGHT .. +NEWS_SENTIMENT_WEIGHT)., aggregate_news_sentiment(), _clamp(), classify_sentiment() (+12 more)

### Community 3 - "Community 3"
Cohesion: 0.40
Nodes (5): PricePoint, PriceHistoryOut, PricePointOut, _clean_float(), get_price_history()

### Community 4 - "Community 4"
Cohesion: 0.14
Nodes (16): BacktestEquityPoint, BacktestPosition, BacktestTrade, BacktestEquityPointOut, BacktestPositionOut, BacktestSummaryOut, BacktestTradeOut, Backtest Engine (+8 more)

### Community 5 - "Community 5"
Cohesion: 0.11
Nodes (17): FastAPI Main App, Python Dependencies, Backend Service, Frontend Service, React Entry Point, InvestEdge Project, Machine Learning Module, Portfolio Engine (+9 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (56): dashboard(), BaseModel, DataProviderStatus, NewsDailyUsage, NewsProviderStatus, NewsRefreshResult, PortfolioPosition, PortfolioSettings (+48 more)

### Community 8 - "Community 8"
Cohesion: 0.06
Nodes (21): TechnicalAnalysis, _clamp(), _is_number(), Explainable technical scoring engine., ScoringEngine, Advanced technical analysis engine built with pandas and numpy., _safe_bool(), _safe_divide() (+13 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (31): Alert, AlertRule, AlertSummary, api, ApiUsage, AssetDataStatus, DataQualityCheck, DataRefreshAllResult (+23 more)

### Community 11 - "Community 11"
Cohesion: 0.24
Nodes (5): _asset_type(), _clean(), _now(), _risk_level(), UniverseService

### Community 12 - "Community 12"
Cohesion: 0.29
Nodes (11): SignalBadge(), SignalBadgeProps, styles, PortfolioRecommendation, PortfolioSummary, Signal, assetTypeLabels, colors (+3 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (34): AlertRuleOut, DataQualityCheckOut, OperationalRankingOut, OperationalReportOut, PortfolioActionOut, SchedulerRunOut, SystemHealthOut, ValidatedSignalOut (+26 more)

### Community 14 - "Community 14"
Cohesion: 0.17
Nodes (7): Settings, BaseNewsProvider, NewsMissingApiKey, NewsProviderError, NewsRateLimitExceeded, NewsRealDisabled, utc_now()

### Community 15 - "Community 15"
Cohesion: 0.08
Nodes (23): dependencies, lucide-react, react, react-dom, react-router-dom, recharts, devDependencies, autoprefixer (+15 more)

### Community 16 - "Community 16"
Cohesion: 0.16
Nodes (8): ABC, BaseMarketDataProvider, MissingApiKey, ProviderError, RateLimitExceeded, RealDataDisabled, utc_now(), RuntimeError

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, allowSyntheticDefaultImports, esModuleInterop, forceConsistentCasingInFileNames, isolatedModules, jsx, lib (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.14
Nodes (13): MLTrainInput, MLTrainIn, MLDatasetService, test_build_dataset_without_lookahead(), test_ml_models_endpoint(), test_ml_predict_endpoint(), test_ml_train_endpoint(), test_ml_train_with_too_few_samples() (+5 more)

### Community 19 - "Community 19"
Cohesion: 0.20
Nodes (4): AlphaVantageProvider, AlphaVantageNewsProvider, _parse_time(), _symbol_sentiment()

### Community 20 - "Community 20"
Cohesion: 0.18
Nodes (14): ImpactLevel, NewsItem, NewsStatus, SentimentLabel, Filter, filters, impactTone, NewsPage() (+6 more)

### Community 21 - "Community 21"
Cohesion: 0.24
Nodes (16): apiDelete(), apiGet(), apiPost(), BacktestResult, BacktestRunInput, BacktestStrategy, BacktestSummary, fetchErrorMessage() (+8 more)

### Community 22 - "Community 22"
Cohesion: 0.17
Nodes (11): allocation, AssetType, backtestCurve, equityCurve, newsItems, portfolioPositions, Signal, signals (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.16
Nodes (19): MetricCard(), MetricCardProps, tones, Panel(), PanelProps, DashboardResponse, DataRefreshResult, DataStatus (+11 more)

### Community 26 - "Community 26"
Cohesion: 0.25
Nodes (7): compilerOptions, allowSyntheticDefaultImports, composite, module, moduleResolution, skipLibCheck, include

### Community 27 - "Community 27"
Cohesion: 0.39
Nodes (8): Asset, OrderSimulationResponse, SimulatedOrderInput, assetTypeLabels, FormState, initialForm, OrderSide, SimulatorPage()

### Community 28 - "Community 28"
Cohesion: 0.40
Nodes (4): AppShell(), AppShellProps, navItems, Sidebar()

### Community 46 - "Community 46"
Cohesion: 0.09
Nodes (22): Alert & Scheduler (Step 11), Analisi tecnica, Avvio backend, Avvio frontend, Backtest Engine, code:text (backend/), code:powershell (backend\.venv\Scripts\python.exe scripts\seed_database.py --), code:powershell (backend\.venv\Scripts\python.exe -m uvicorn backend.app.main) (+14 more)

### Community 47 - "Community 47"
Cohesion: 0.16
Nodes (12): OptimizationItemOut, OptimizationRunFullOut, OptimizationRunSummaryOut, OptimizerConfig, RebalanceOrderOut, SimulatedOrderIn, _now(), PortfolioOptimizerService (+4 more)

### Community 48 - "Community 48"
Cohesion: 0.16
Nodes (14): OperationalReport, OptimizationRunFull, OptimizationRunSummary, OptimizerConfig, PriceHistory, formatCurrency(), formatPercent(), AnalysisPage() (+6 more)

### Community 49 - "Community 49"
Cohesion: 0.18
Nodes (12): StrategyPlanConfig, StrategyPlanFullOut, StrategyPlanItemOut, StrategyPlanOrderOut, StrategyPlanSummaryOut, _now(), StrategyControlService, test_apply_plan_creates_simulated_orders() (+4 more)

### Community 50 - "Community 50"
Cohesion: 0.17
Nodes (17): MarketSentiment, _asset_from_base_row(), _asset_from_row(), create_asset(), get_asset_by_symbol(), _latest_price_metadata(), _latest_price_metrics(), list_assets() (+9 more)

### Community 51 - "Community 51"
Cohesion: 0.24
Nodes (10): MLModelType, MLStatus, MLTargetType, MLTrainingRun, MLTrainResult, confidenceTone(), MachineLearningPage(), metricValue() (+2 more)

### Community 52 - "Community 52"
Cohesion: 0.40
Nodes (3): BaseNewsProvider, MockNewsProvider, test_mock_news_provider_returns_items()

### Community 54 - "Community 54"
Cohesion: 0.31
Nodes (7): _csv(), from_env(), get_settings(), _unique(), test_api_cache_save_and_read(), test_api_rate_limit_guard(), test_alpha_vantage_news_normalization()

### Community 55 - "Community 55"
Cohesion: 0.67
Nodes (4): ml_models(), MLModelSummary, MLModelDetailOut, MLModelSummaryOut

### Community 56 - "Community 56"
Cohesion: 0.50
Nodes (4): Enum, AlertSeverity, AlertStatus, OptimizationMethod

### Community 57 - "Community 57"
Cohesion: 0.67
Nodes (3): get_universe_summary(), UniverseSummary, UniverseSummaryOut

### Community 58 - "Community 58"
Cohesion: 0.67
Nodes (3): news_sentiment(), NewsSentimentSummary, NewsSentimentSummaryOut

## Knowledge Gaps
- **101 isolated node(s):** `allow`, `BeforeTool`, `name`, `private`, `version` (+96 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `db_session()` connect `Community 0` to `Community 1`, `Community 2`, `Community 6`, `Community 8`, `Community 18`, `Community 52`, `Community 53`, `Community 54`, `Community 55`, `Community 57`, `Community 58`?**
  _High betweenness centrality (0.180) - this node is a cross-community bridge._
- **Why does `TechnicalAnalysis` connect `Community 8` to `Community 0`, `Community 5`, `Community 6`, `Community 9`, `Community 48`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Why does `NewsEngine` connect `Community 2` to `Community 8`, `Community 14`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 96 inferred relationships involving `db_session()` (e.g. with `get_system_health()` and `get_system_audit()`) actually correct?**
  _`db_session()` has 96 INFERRED edges - model-reasoned connections that need verification._
- **Are the 42 inferred relationships involving `str` (e.g. with `_database_file()` and `get_asset_validated_signal()`) actually correct?**
  _`str` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `PortfolioEngine` (e.g. with `AlertService` and `MarketDataService`) actually correct?**
  _`PortfolioEngine` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `MLEngine` (e.g. with `MLDatasetService` and `UniverseService`) actually correct?**
  _`MLEngine` has 8 INFERRED edges - model-reasoned connections that need verification._