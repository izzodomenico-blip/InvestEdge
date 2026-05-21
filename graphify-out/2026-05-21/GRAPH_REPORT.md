# Graph Report - .  (2026-05-21)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 729 nodes · 1492 edges · 46 communities (37 shown, 9 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 230 edges (avg confidence: 0.75)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `44fe2b27`
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

## God Nodes (most connected - your core abstractions)
1. `db_session()` - 58 edges
2. `Backtest Engine` - 38 edges
3. `MLEngine` - 35 edges
4. `Portfolio Engine` - 33 edges
5. `AlphaVantageProvider` - 24 edges
6. `NewsEngine` - 24 edges
7. `BacktestPage()` - 23 edges
8. `BaseMarketDataProvider` - 18 edges
9. `PortfolioPage()` - 18 edges
10. `WatchlistPage()` - 18 edges

## Surprising Connections (you probably didn't know these)
- `test_repeated_refresh_does_not_duplicate_price_history()` --calls--> `db_session()`  [INFERRED]
  tests/test_api.py → backend/app/database.py
- `test_news_dedup_does_not_duplicate()` --calls--> `db_session()`  [INFERRED]
  tests/test_news.py → backend/app/database.py
- `Local backtest engine for simulated strategies only.` --rationale_for--> `Backtest Engine`  [EXTRACTED]
  backend/app/services/backtest_engine.py → README.md
- `Paper-trading portfolio engine. No real broker actions are performed.` --rationale_for--> `Portfolio Engine`  [EXTRACTED]
  backend/app/services/portfolio_engine.py → README.md
- `InvestEdge Project` --references--> `FastAPI Main App`  [INFERRED]
  README.md → backend/app/main.py

## Communities (46 total, 9 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (60): add_universe_watchlist(), asset_data_status(), dashboard(), data_status(), data_usage(), delete_backtest(), get_asset(), get_assets() (+52 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (26): admin_seed(), _database_file(), get_connection(), init_db(), migrate_db(), _table_columns(), create_app(), lifespan() (+18 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (17): BaseNewsProvider, aggregate_news_sentiment(), _clamp(), classify_sentiment(), estimate_impact(), _normalize_text(), Aggregate news sentiment for a symbol across the lookback window., Backwards-compatible engine class that exposes the heuristic functions. (+9 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (20): FastAPI Main App, Python Dependencies, Backend Service, Frontend Service, React Entry Point, TechnicalAnalysis, InvestEdge Project, Machine Learning Module (+12 more)

### Community 4 - "Community 4"
Cohesion: 0.14
Nodes (7): BacktestTrade, Backtest Engine, _date(), _now(), Local backtest engine for simulated strategies only., Precompute rolling indicators and score rows without using future values., _round()

### Community 5 - "Community 5"
Cohesion: 0.14
Nodes (9): Portfolio Engine, _Position, _now(), Paper-trading portfolio engine. No real broker actions are performed., _round(), list_portfolio(), portfolio_value(), Portfolio-level risk checks for simulated trading only. (+1 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (31): BaseModel, BacktestEquityPoint, BacktestPosition, MLModelSummary, NewsDailyUsage, NewsProviderStatus, PortfolioPosition, PortfolioSettings (+23 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (10): _backtest_payload(), _price_frame(), test_backtest_history_and_detail_endpoints(), test_backtest_no_lookahead_on_future_jump(), test_repeated_refresh_does_not_duplicate_price_history(), test_run_backtest_buy_and_hold(), test_run_backtest_score_threshold(), test_run_backtest_top_n_score() (+2 more)

### Community 9 - "Community 9"
Cohesion: 0.12
Nodes (23): apiDelete(), apiGet(), apiPost(), ApiUsage, Asset, AssetDataStatus, DataProviderStatus, DataRefreshAllResult (+15 more)

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (6): _csv(), from_env(), get_settings(), _unique(), _now(), test_provider_registry()

### Community 11 - "Community 11"
Cohesion: 0.20
Nodes (4): _asset_type(), _clean(), _now(), _risk_level()

### Community 12 - "Community 12"
Cohesion: 0.11
Nodes (22): Panel(), PanelProps, SignalBadge(), SignalBadgeProps, styles, DashboardResponse, NewsSentimentSummary, PortfolioRecommendation (+14 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (5): MockMarketDataProvider, NewsEngine, _now(), News orchestration engine. Mock/fallback by default, real provider opt-in., Compute optional news_score (-NEWS_SENTIMENT_WEIGHT .. +NEWS_SENTIMENT_WEIGHT).

### Community 14 - "Community 14"
Cohesion: 0.17
Nodes (8): ABC, Settings, BaseNewsProvider, NewsMissingApiKey, NewsProviderError, NewsRateLimitExceeded, NewsRealDisabled, utc_now()

### Community 15 - "Community 15"
Cohesion: 0.09
Nodes (22): dependencies, lucide-react, react, react-dom, react-router-dom, recharts, devDependencies, autoprefixer (+14 more)

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (7): BaseMarketDataProvider, MissingApiKey, ProviderError, RateLimitExceeded, RealDataDisabled, utc_now(), RuntimeError

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, allowSyntheticDefaultImports, esModuleInterop, forceConsistentCasingInFileNames, isolatedModules, jsx, lib (+10 more)

### Community 19 - "Community 19"
Cohesion: 0.16
Nodes (4): AlphaVantageProvider, _parse_time(), _symbol_sentiment(), test_api_cache_save_and_read()

### Community 20 - "Community 20"
Cohesion: 0.13
Nodes (13): ImpactLevel, NewsItem, NewsRefreshResult, NewsStatus, SentimentLabel, Filter, filters, impactTone (+5 more)

### Community 21 - "Community 21"
Cohesion: 0.14
Nodes (12): MetricCard(), MetricCardProps, tones, BacktestResult, BacktestRunInput, BacktestStrategy, BacktestSummary, RebalanceFrequency (+4 more)

### Community 22 - "Community 22"
Cohesion: 0.18
Nodes (10): allocation, AssetType, backtestCurve, equityCurve, newsItems, Signal, signals, technicalSeries (+2 more)

### Community 25 - "Community 25"
Cohesion: 0.22
Nodes (5): UniverseImportResult, UniverseSummary, csvOptions, levelTone, UniversePage()

### Community 26 - "Community 26"
Cohesion: 0.25
Nodes (7): compilerOptions, allowSyntheticDefaultImports, composite, module, moduleResolution, skipLibCheck, include

### Community 27 - "Community 27"
Cohesion: 0.25
Nodes (8): OrderSimulationResponse, PortfolioSummary, SimulatedOrder, assetTypeLabels, FormState, initialForm, OrderSide, SimulatorPage()

### Community 28 - "Community 28"
Cohesion: 0.40
Nodes (4): AppShell(), AppShellProps, navItems, Sidebar()

## Knowledge Gaps
- **94 isolated node(s):** `allow`, `BeforeTool`, `name`, `private`, `version` (+89 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `db_session()` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 8`, `Community 10`, `Community 18`, `Community 19`, `Community 23`?**
  _High betweenness centrality (0.226) - this node is a cross-community bridge._
- **Why does `TechnicalAnalysis` connect `Community 3` to `Community 0`, `Community 9`, `Community 12`, `Community 6`?**
  _High betweenness centrality (0.126) - this node is a cross-community bridge._
- **Why does `get_technical_analysis()` connect `Community 3` to `Community 0`, `Community 13`, `Community 7`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Are the 56 inferred relationships involving `db_session()` (e.g. with `get_assets()` and `get_asset()`) actually correct?**
  _`db_session()` has 56 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `Backtest Engine` (e.g. with `technical_analysis_service.py` and `test_backtest_no_lookahead_on_future_jump()`) actually correct?**
  _`Backtest Engine` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `MLEngine` (e.g. with `ml_dataset_service.py` and `universe_service.py`) actually correct?**
  _`MLEngine` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `Portfolio Engine` (e.g. with `market_data_service.py` and `.__init__()`) actually correct?**
  _`Portfolio Engine` has 6 INFERRED edges - model-reasoned connections that need verification._