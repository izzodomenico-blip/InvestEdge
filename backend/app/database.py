from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from backend.app.config import get_settings

# ISIN ufficiali dei titoli noti dell'universo InvestEdge. Servono a identificare
# senza ambiguita' un titolo (es. distinguere VWCE da altri ETF simili).
# Crypto e indici generici (BTP10Y) non hanno un ISIN univoco: restano senza.
ISIN_BY_SYMBOL: dict[str, str] = {
    "AAPL": "US0378331005",
    "MSFT": "US5949181045",
    "NVDA": "US67066G1040",
    "AMZN": "US0231351067",
    "GOOGL": "US02079K3059",
    "META": "US30303M1027",
    "TSLA": "US88160R1014",
    "JPM": "US46625H1005",
    "UNH": "US91324P1021",
    "KO": "US1912161007",
    "SPY": "US78462F1030",
    "QQQ": "US46090E1038",
    "VOO": "US9229083632",
    "VWCE": "IE00BK5BQT80",
    "AGGH": "IE00BDBRDM35",
    "IB01": "IE00BGSF1X88",
    "TLT": "US4642874576",
    "IEF": "US4642874402",
    "SHY": "US4642874329",
}

GOVERNMENT_BOND_TAX_SYMBOLS = {"BTP10Y"}

BASE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    instrument_type TEXT NOT NULL
        CHECK(instrument_type IN (
            'STOCK', 'ETF', 'BOND', 'ETC', 'ETN', 'CRYPTO', 'FX',
            'INDEX', 'RATE', 'MACRO', 'UNKNOWN'
        )),
    asset_class TEXT NOT NULL
        CHECK(asset_class IN (
            'EQUITY', 'FUND', 'FIXED_INCOME', 'COMMODITY', 'CRYPTO',
            'FX', 'REFERENCE', 'UNKNOWN'
        )),
    quality_tier TEXT NOT NULL DEFAULT 'REFERENCE_ONLY'
        CHECK(quality_tier IN ('QUALIFIED', 'OBSERVABLE', 'REFERENCE_ONLY')),
    quality_reason_code TEXT CHECK(
        quality_reason_code IS NULL OR quality_reason_code IN (
            'REFERENCE_INSTRUMENT', 'AMBIGUOUS_IDENTITY', 'MISSING_PRIMARY_ID',
            'MISSING_LISTING_METADATA', 'UNRESOLVED_CRITICAL_REJECTION',
            'NO_VALID_OBSERVATION', 'STALE_OBSERVATION', 'INSUFFICIENT_HISTORY',
            'PROVIDER_DIVERGENCE', 'COMPATIBLE_FALLBACK_IN_USE',
            'VALIDATED_OBSERVABLE', 'QUALIFICATION_RULES_MET'
        )
    ),
    quality_assessed_at TEXT,
    source TEXT NOT NULL,
    source_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS instrument_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    ticker TEXT NOT NULL CHECK(length(trim(ticker)) > 0),
    mic TEXT CHECK(mic IS NULL OR length(trim(mic)) > 0),
    venue_name TEXT,
    currency TEXT NOT NULL CHECK(length(trim(currency)) > 0),
    timezone TEXT,
    listing_status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK(listing_status IN ('ACTIVE', 'INACTIVE', 'DELISTED')),
    trade_republic_status TEXT NOT NULL DEFAULT 'NEVER_SEEN'
        CHECK(trade_republic_status IN ('NEVER_SEEN', 'CATALOGED', 'VERIFIED', 'UNAVAILABLE')),
    trade_republic_cataloged_at TEXT,
    trade_republic_verified_at TEXT,
    source TEXT NOT NULL,
    source_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS instrument_identifiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheme TEXT NOT NULL
        CHECK(scheme IN (
            'ISIN', 'FIGI', 'OPENFIGI_TICKER', 'COINGECKO_ID',
            'FRED_SERIES_ID', 'ECB_SERIES_KEY'
        )),
    normalized_value TEXT NOT NULL CHECK(length(normalized_value) > 0),
    scope TEXT NOT NULL CHECK(scope IN ('INSTRUMENT', 'LISTING')),
    instrument_id INTEGER,
    listing_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(
        (scope = 'INSTRUMENT' AND instrument_id IS NOT NULL AND listing_id IS NULL)
        OR
        (scope = 'LISTING' AND instrument_id IS NULL AND listing_id IS NOT NULL)
    ),
    CHECK(
        scheme NOT IN ('ISIN', 'FIGI')
        OR (
            normalized_value = UPPER(normalized_value)
            AND normalized_value = TRIM(normalized_value)
            AND INSTR(normalized_value, ' ') = 0
            AND INSTR(normalized_value, CHAR(9)) = 0
            AND INSTR(normalized_value, CHAR(10)) = 0
            AND INSTR(normalized_value, CHAR(13)) = 0
        )
    ),
    FOREIGN KEY(instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT,
    FOREIGN KEY(listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS instrument_identifier_attestations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash) = 64),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(identifier_id) REFERENCES instrument_identifiers(id) ON DELETE RESTRICT,
    UNIQUE(identifier_id, source, observed_at, evidence_hash)
);

CREATE TABLE IF NOT EXISTS catalog_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK(length(trim(source)) > 0),
    source_url TEXT NOT NULL CHECK(length(trim(source_url)) > 0),
    content_sha256 TEXT CHECK(content_sha256 IS NULL OR length(content_sha256) = 64),
    retrieved_at TEXT NOT NULL,
    source_date TEXT,
    row_count INTEGER NOT NULL CHECK(row_count >= 0),
    status TEXT NOT NULL CHECK(status IN ('COMPLETE', 'FAILED')),
    parser_version TEXT NOT NULL CHECK(length(trim(parser_version)) > 0),
    failure_reason_code TEXT CHECK(
        failure_reason_code IS NULL OR failure_reason_code IN (
            'DOWNLOAD_FAILED', 'PAYLOAD_TOO_LARGE', 'PARSER_ERROR', 'EMPTY_CATALOG'
        )
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(
        (status = 'COMPLETE' AND content_sha256 IS NOT NULL AND failure_reason_code IS NULL)
        OR
        (status = 'FAILED' AND failure_reason_code IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS catalog_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL CHECK(row_number > 0),
    isin TEXT,
    name TEXT,
    parse_status TEXT NOT NULL CHECK(parse_status IN ('ACCEPTED', 'REJECTED', 'AMBIGUOUS')),
    reason_code TEXT NOT NULL CHECK(reason_code IN (
        'VALID_ISIN', 'INVALID_ISIN', 'MISSING_ISIN', 'MISSING_NAME',
        'DUPLICATE_IN_SNAPSHOT', 'UNSUPPORTED_ROW'
    )),
    raw_row_sha256 TEXT NOT NULL CHECK(length(raw_row_sha256) = 64),
    instrument_id INTEGER,
    listing_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(snapshot_id) REFERENCES catalog_snapshots(id) ON DELETE RESTRICT,
    FOREIGN KEY(instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT,
    FOREIGN KEY(listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT,
    UNIQUE(snapshot_id, row_number)
);

CREATE TABLE IF NOT EXISTS instrument_resolution_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_entry_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK(length(trim(provider)) > 0),
    request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint) = 64),
    status TEXT NOT NULL CHECK(status IN ('RESOLVED', 'AMBIGUOUS', 'UNMATCHED', 'REJECTED')),
    reason_code TEXT NOT NULL CHECK(reason_code IN (
        'EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE',
        'MULTIPLE_COMPATIBLE_CANDIDATES',
        'NO_PROVIDER_MATCH',
        'TYPE_MISMATCH',
        'CURRENCY_MISMATCH',
        'MISSING_CURRENCY',
        'MISSING_VENUE',
        'MISSING_TIMEZONE',
        'INVALID_PROVIDER_PAYLOAD'
    )),
    candidate_count INTEGER NOT NULL CHECK(candidate_count >= 0),
    candidate_hash TEXT NOT NULL CHECK(length(candidate_hash) = 64),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash) = 64),
    selected_instrument_id INTEGER,
    selected_listing_id INTEGER,
    candidate_figi TEXT,
    candidate_ticker TEXT,
    candidate_exchange_code TEXT,
    candidate_market_sector TEXT,
    candidate_security_type TEXT,
    candidate_name TEXT,
    candidate_currency_hint TEXT,
    created_at TEXT NOT NULL,
    CHECK(
        status != 'RESOLVED'
        OR (selected_instrument_id IS NOT NULL AND selected_listing_id IS NOT NULL)
    ),
    CHECK(status != 'RESOLVED' OR candidate_count = 1),
    CHECK(status = 'RESOLVED' OR selected_listing_id IS NULL),
    FOREIGN KEY(catalog_entry_id) REFERENCES catalog_entries(id) ON DELETE RESTRICT,
    FOREIGN KEY(selected_instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT,
    FOREIGN KEY(selected_listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS listing_metadata_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_listing_id INTEGER NOT NULL,
    venue_name TEXT NOT NULL CHECK(length(trim(venue_name)) > 0),
    timezone TEXT NOT NULL CHECK(length(trim(timezone)) > 0),
    instrument_type TEXT NOT NULL CHECK(instrument_type IN (
        'STOCK', 'ETF', 'BOND', 'ETC', 'ETN', 'CRYPTO', 'FX',
        'INDEX', 'RATE', 'MACRO', 'UNKNOWN'
    )),
    source_code TEXT NOT NULL CHECK(source_code IN (
        'OFFICIAL_VENUE', 'ISSUER_FACTSHEET', 'LEGACY_ACTIVE_ASSET'
    )),
    observed_at TEXT NOT NULL,
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash) = 64),
    status TEXT NOT NULL CHECK(status IN ('VERIFIED', 'RETIRED')),
    version INTEGER NOT NULL CHECK(version > 0),
    supersedes_listing_metadata_version_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(instrument_listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT,
    FOREIGN KEY(supersedes_listing_metadata_version_id)
        REFERENCES listing_metadata_versions(id) ON DELETE RESTRICT,
    UNIQUE(instrument_listing_id, version)
);

CREATE TABLE IF NOT EXISTS catalog_listing_attestations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_entry_id INTEGER NOT NULL,
    instrument_listing_id INTEGER NOT NULL,
    listing_metadata_version_id INTEGER NOT NULL,
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash) = 64),
    attested_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(catalog_entry_id) REFERENCES catalog_entries(id) ON DELETE RESTRICT,
    FOREIGN KEY(instrument_listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT,
    FOREIGN KEY(listing_metadata_version_id)
        REFERENCES listing_metadata_versions(id) ON DELETE RESTRICT,
    UNIQUE(
        catalog_entry_id,
        instrument_listing_id,
        listing_metadata_version_id,
        evidence_hash
    )
);

CREATE TABLE IF NOT EXISTS provider_symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK(length(trim(provider)) > 0),
    listing_id INTEGER NOT NULL,
    capability TEXT NOT NULL CHECK(length(trim(capability)) > 0),
    provider_symbol TEXT NOT NULL CHECK(length(trim(provider_symbol)) > 0),
    normalized_symbol TEXT NOT NULL CHECK(length(normalized_symbol) > 0),
    status TEXT NOT NULL CHECK(status IN ('CANDIDATE', 'VERIFIED', 'RETIRED')),
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    verified_at TEXT,
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash) = 64),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    supersedes_provider_symbol_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(status != 'VERIFIED' OR verified_at IS NOT NULL),
    FOREIGN KEY(listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT,
    FOREIGN KEY(supersedes_provider_symbol_id) REFERENCES provider_symbols(id) ON DELETE RESTRICT,
    UNIQUE(provider, listing_id, capability, version)
);

-- Conferme manuali e locali dello stato Trade Republic: storia append-only con una
-- sola versione ACTIVE per listing; instrument_listings ne conserva la projection.
CREATE TABLE IF NOT EXISTS trade_republic_attestations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('VERIFIED', 'UNAVAILABLE')),
    record_status TEXT NOT NULL CHECK(record_status IN ('ACTIVE', 'RETIRED')),
    source TEXT NOT NULL CHECK(source IN (
        'MANUAL_OFFICIAL_APP_CHECK', 'OFFICIAL_SUPPORT_NOTICE'
    )),
    observed_at TEXT NOT NULL CHECK(length(trim(observed_at)) > 0),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash) = 64),
    version INTEGER NOT NULL CHECK(version > 0),
    supersedes_attestation_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT,
    FOREIGN KEY(supersedes_attestation_id)
        REFERENCES trade_republic_attestations(id) ON DELETE RESTRICT,
    UNIQUE(listing_id, version)
);

CREATE TABLE IF NOT EXISTS market_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK(length(trim(provider)) > 0),
    capability TEXT NOT NULL CHECK(capability IN (
        'CATALOG', 'IDENTITY', 'EOD', 'QUOTE', 'FX', 'REFERENCE', 'NEWS'
    )),
    operation TEXT NOT NULL CHECK(length(trim(operation)) > 0),
    provider_observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    timezone TEXT NOT NULL CHECK(length(trim(timezone)) > 0),
    session TEXT NOT NULL CHECK(length(trim(session)) > 0),
    currency TEXT NOT NULL CHECK(length(currency) = 3 AND currency = UPPER(currency)),
    delay_seconds INTEGER NOT NULL CHECK(delay_seconds >= 0),
    source_quality TEXT NOT NULL CHECK(source_quality IN (
        'realtime', 'delayed', 'eod', 'reference'
    )),
    effective_quality TEXT NOT NULL CHECK(effective_quality IN (
        'realtime', 'delayed', 'eod', 'reference', 'stale'
    )),
    kind TEXT NOT NULL CHECK(kind IN ('QUOTE', 'BAR')),
    bid TEXT,
    ask TEXT,
    last TEXT,
    open TEXT,
    high TEXT,
    low TEXT,
    close TEXT,
    adjusted_close TEXT,
    volume TEXT,
    observation_hash TEXT NOT NULL CHECK(length(observation_hash) = 64),
    revision INTEGER NOT NULL CHECK(revision > 0),
    supersedes_observation_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT,
    FOREIGN KEY(supersedes_observation_id)
        REFERENCES market_observations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS market_data_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK(length(trim(provider)) > 0),
    capability TEXT NOT NULL CHECK(capability IN (
        'CATALOG', 'IDENTITY', 'EOD', 'QUOTE', 'FX', 'REFERENCE', 'NEWS'
    )),
    operation TEXT NOT NULL CHECK(length(trim(operation)) > 0),
    received_at TEXT NOT NULL,
    reason_code TEXT NOT NULL CHECK(reason_code IN (
        'MISSING_PRICE', 'NON_FINITE', 'NON_POSITIVE', 'CROSSED_QUOTE',
        'INVALID_OHLC', 'NEGATIVE_VOLUME', 'CURRENCY_MISMATCH',
        'INVALID_TIMESTAMP', 'FUTURE_TIMESTAMP', 'INVALID_TIMEZONE',
        'INVALID_DELAY', 'MALFORMED_PAYLOAD', 'PROVIDER_NO_DATA',
        'MISSING_VALUE'
    )),
    raw_payload_sha256 TEXT NOT NULL CHECK(length(raw_payload_sha256) = 64),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS market_data_rejection_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rejection_id INTEGER NOT NULL UNIQUE,
    observation_id INTEGER NOT NULL,
    resolved_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(rejection_id) REFERENCES market_data_rejections(id) ON DELETE RESTRICT,
    FOREIGN KEY(observation_id) REFERENCES market_observations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS market_data_selection_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    selected_observation_id INTEGER NOT NULL,
    requested_provider TEXT NOT NULL CHECK(length(trim(requested_provider)) > 0),
    actual_provider TEXT NOT NULL CHECK(length(trim(actual_provider)) > 0),
    selected_at TEXT NOT NULL,
    fallback_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(selected_observation_id) REFERENCES market_observations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS refresh_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    capability TEXT NOT NULL CHECK(capability IN ('EOD', 'QUOTE')),
    reason TEXT NOT NULL
        CHECK(reason IN (
            'POSITION', 'STRATEGY_CANDIDATE', 'WATCHLIST', 'REQUESTED', 'VIEWED', 'CATALOG_EOD'
        )),
    priority INTEGER NOT NULL CHECK(priority > 0),
    force INTEGER NOT NULL DEFAULT 0 CHECK(force IN (0, 1)),
    state TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(state IN (
            'PENDING', 'RUNNING', 'SUCCEEDED', 'SKIPPED_FRESH', 'BUDGET_DEFERRED', 'FAILED'
        )),
    requested_at TEXT NOT NULL,
    not_before TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    last_reason_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS refresh_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK(state IN ('SUCCEEDED', 'SKIPPED_FRESH', 'BUDGET_DEFERRED', 'FAILED')),
    provider TEXT,
    rows_inserted INTEGER NOT NULL DEFAULT 0 CHECK(rows_inserted >= 0),
    rows_updated INTEGER NOT NULL DEFAULT 0 CHECK(rows_updated >= 0),
    used_cache INTEGER NOT NULL DEFAULT 0 CHECK(used_cache IN (0, 1)),
    reason_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(request_id) REFERENCES refresh_requests(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS quality_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    tier TEXT NOT NULL
        CHECK(tier IN ('QUALIFIED', 'OBSERVABLE', 'REFERENCE_ONLY')),
    reason_codes_json TEXT NOT NULL CHECK(length(trim(reason_codes_json)) > 0),
    assessed_at TEXT NOT NULL,
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash) = 64),
    evidence_scopes_json TEXT NOT NULL CHECK(length(trim(evidence_scopes_json)) > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(instrument_id) REFERENCES instruments(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    tax_category TEXT NOT NULL DEFAULT 'standard'
        CHECK(tax_category IN ('standard', 'government_bond', 'crypto', 'euro_emt')),
    exchange TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    sector TEXT,
    country TEXT,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    instrument_listing_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, asset_type),
    FOREIGN KEY(instrument_listing_id) REFERENCES instrument_listings(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL NOT NULL,
    adjusted_close REAL,
    volume REAL,
    source TEXT NOT NULL DEFAULT 'mock',
    provider TEXT,
    is_real_data INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT,
    observation_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    FOREIGN KEY(observation_id) REFERENCES market_observations(id) ON DELETE RESTRICT,
    UNIQUE(asset_id, date, source)
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    quantity REAL NOT NULL,
    average_price REAL NOT NULL,
    fx_rate_to_base REAL NOT NULL DEFAULT 0,
    average_price_base REAL NOT NULL DEFAULT 0,
    invested_amount REAL NOT NULL DEFAULT 0,
    invested_amount_base REAL NOT NULL DEFAULT 0,
    current_price REAL NOT NULL DEFAULT 0,
    current_value REAL NOT NULL DEFAULT 0,
    current_value_base REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    realized_pnl_base REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl_base REAL NOT NULL DEFAULT 0,
    unrealized_pnl_percent REAL NOT NULL DEFAULT 0,
    weight_percent REAL NOT NULL DEFAULT 0,
    asset_type TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS simulated_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    order_type TEXT CHECK(order_type IN ('BUY', 'SELL')),
    side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'EUR',
    fx_rate_to_base REAL NOT NULL DEFAULT 0,
    gross_amount REAL NOT NULL DEFAULT 0,
    gross_amount_base REAL NOT NULL DEFAULT 0,
    net_amount REAL NOT NULL DEFAULT 0,
    net_amount_base REAL NOT NULL DEFAULT 0,
    fees_base REAL NOT NULL DEFAULT 0,
    order_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note TEXT,
    strategy_tag TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'SIMULATED',
    executed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'EUR',
    total_value REAL NOT NULL DEFAULT 0,
    invested_value REAL NOT NULL DEFAULT 0,
    cash REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    total_pnl REAL NOT NULL DEFAULT 0,
    total_pnl_percent REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    initial_cash REAL NOT NULL DEFAULT 100000,
    current_cash REAL NOT NULL DEFAULT 100000,
    max_single_asset_weight REAL NOT NULL DEFAULT 25,
    max_asset_class_weight REAL NOT NULL DEFAULT 50,
    default_fee_percent REAL NOT NULL DEFAULT 0.1,
    crypto_max_weight REAL NOT NULL DEFAULT 15,
    min_cash_weight REAL NOT NULL DEFAULT 2,
    max_cash_weight REAL NOT NULL DEFAULT 35,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    signal TEXT NOT NULL CHECK(signal IN ('STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL')),
    score REAL NOT NULL,
    technical_score REAL,
    news_score REAL NOT NULL DEFAULT 0,
    final_score REAL,
    news_sentiment_label TEXT,
    news_impact_level TEXT,
    risk_level TEXT,
    confidence TEXT,
    technical_summary TEXT,
    reasons_json TEXT,
    subscores_json TEXT,
    indicators_json TEXT,
    rationale TEXT,
    source TEXT NOT NULL DEFAULT 'scoring_engine',
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data_mode TEXT CHECK(data_mode IS NULL OR data_mode IN ('REAL', 'DEMO')),
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER,
    symbol TEXT,
    provider TEXT NOT NULL DEFAULT 'local',
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    source TEXT,
    published_at TEXT,
    sentiment_score REAL,
    sentiment_label TEXT,
    impact_level TEXT,
    relevance_score REAL,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS api_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    endpoint TEXT,
    symbol TEXT,
    request_url_hash TEXT,
    response_json TEXT,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'OK',
    last_update TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    usage_date TEXT NOT NULL,
    calls_count INTEGER NOT NULL DEFAULT 0,
    daily_limit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, usage_date)
);

CREATE TABLE IF NOT EXISTS provider_usage_windows (
    provider TEXT NOT NULL,
    window_kind TEXT NOT NULL CHECK(window_kind IN ('MINUTE', 'DAY', 'MONTH')),
    window_start TEXT NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0 CHECK(used_count >= 0),
    configured_limit INTEGER CHECK(configured_limit IS NULL OR configured_limit >= 0),
    effective_limit INTEGER CHECK(effective_limit IS NULL OR effective_limit >= 0),
    cooldown_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(provider, window_kind, window_start)
);

CREATE TABLE IF NOT EXISTS provider_request_log (
    reservation_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint) = 64),
    outcome TEXT CHECK(outcome IS NULL OR outcome IN (
        'SUCCEEDED', 'CACHE_HIT', 'RATE_LIMITED', 'TIMED_OUT',
        'RETRY_EXHAUSTED', 'REJECTED', 'DISABLED'
    )),
    status_code INTEGER,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    cooldown_until TEXT,
    requested_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS fx_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_currency TEXT NOT NULL,
    to_currency TEXT NOT NULL,
    rate REAL NOT NULL CHECK(rate > 0),
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    provider TEXT NOT NULL,
    quality TEXT NOT NULL,
    UNIQUE(from_currency, to_currency, observed_at, provider)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    benchmark_symbol TEXT,
    buy_threshold REAL NOT NULL DEFAULT 70,
    sell_threshold REAL NOT NULL DEFAULT 40,
    max_asset_weight REAL NOT NULL DEFAULT 0.15,
    fee_percent REAL NOT NULL DEFAULT 0.1,
    stop_loss_percent REAL,
    take_profit_percent REAL,
    rebalance_frequency TEXT NOT NULL DEFAULT 'WEEKLY',
    total_return_percent REAL NOT NULL DEFAULT 0,
    cagr REAL NOT NULL DEFAULT 0,
    max_drawdown REAL NOT NULL DEFAULT 0,
    sharpe_ratio REAL NOT NULL DEFAULT 0,
    win_rate REAL NOT NULL DEFAULT 0,
    profit_factor REAL NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    final_value REAL NOT NULL DEFAULT 0,
    benchmark_return_percent REAL NOT NULL DEFAULT 0,
    alpha_vs_benchmark REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_equity_curve (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    portfolio_value REAL NOT NULL,
    cash REAL NOT NULL,
    invested_value REAL NOT NULL,
    drawdown_percent REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(backtest_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK(order_type IN ('BUY', 'SELL')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    gross_amount REAL NOT NULL DEFAULT 0,
    net_amount REAL NOT NULL DEFAULT 0,
    pnl REAL NOT NULL DEFAULT 0,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(backtest_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backtest_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    average_price REAL NOT NULL,
    final_price REAL NOT NULL,
    final_value REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(backtest_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ml_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    model_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    symbols_scope TEXT,
    features_json TEXT,
    metrics_json TEXT,
    model_path TEXT,
    trained_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ml_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER,
    symbol TEXT NOT NULL,
    prediction_date TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    probability_positive REAL,
    probability_outperform REAL,
    probability_drawdown REAL,
    predicted_label TEXT,
    confidence TEXT,
    features_snapshot_json TEXT,
    explanation_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(model_id) REFERENCES ml_models(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ml_training_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    train_start_date TEXT,
    train_end_date TEXT,
    test_start_date TEXT,
    test_end_date TEXT,
    samples_count INTEGER NOT NULL DEFAULT 0,
    accuracy REAL,
    precision REAL,
    recall REAL,
    f1_score REAL,
    roc_auc REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS features_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    timeframe TEXT NOT NULL CHECK(timeframe IN ('D', 'W', 'M')),
    date TEXT NOT NULL,
    segment_id INTEGER NOT NULL,
    pipeline_version TEXT NOT NULL,
    score_version TEXT NOT NULL,
    data_mode TEXT NOT NULL CHECK(data_mode IN ('REAL', 'DEMO')),
    window_hash TEXT NOT NULL CHECK(length(window_hash) = 64),
    warmup_complete INTEGER NOT NULL CHECK(warmup_complete IN (0, 1)),
    score REAL,
    trend_score REAL,
    momentum_score REAL,
    volatility_score REAL,
    volume_score REAL,
    support_resistance_score REAL,
    risk_penalty REAL,
    features_json TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    UNIQUE(asset_id, timeframe, date, pipeline_version, data_mode)
);

CREATE TABLE IF NOT EXISTS lab_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('BACKTEST', 'COMPARE', 'WALK_FORWARD', 'EVIDENCE',
                                      'FEATURE_REFRESH', 'FX_BACKFILL', 'ML_TRAIN')),
    status TEXT NOT NULL CHECK(status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'INTERRUPTED')),
    params_json TEXT NOT NULL,
    params_hash TEXT NOT NULL CHECK(length(params_hash) = 64),
    progress REAL NOT NULL DEFAULT 0 CHECK(progress >= 0 AND progress <= 1),
    result_ref TEXT,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0, 1)),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS lab_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('BACKTEST', 'COMPARE', 'WF_GRID')),
    config_hash TEXT NOT NULL CHECK(length(config_hash) = 64),
    fingerprint TEXT NOT NULL CHECK(length(fingerprint) = 64),
    sharpe_daily REAL NOT NULL,
    n_obs INTEGER NOT NULL CHECK(n_obs > 1),
    job_id INTEGER,
    created_at TEXT NOT NULL
);

"""


INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_assets_symbol ON assets(symbol);
CREATE INDEX IF NOT EXISTS idx_assets_instrument_listing ON assets(instrument_listing_id);
CREATE INDEX IF NOT EXISTS idx_instrument_listings_instrument ON instrument_listings(instrument_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_instrument_identifiers_global_primary
ON instrument_identifiers(scheme, normalized_value)
WHERE scheme IN ('ISIN', 'FIGI');
CREATE UNIQUE INDEX IF NOT EXISTS uq_instrument_identifiers_instrument_owner
ON instrument_identifiers(scheme, normalized_value, instrument_id)
WHERE scope = 'INSTRUMENT' AND scheme NOT IN ('ISIN', 'FIGI');
CREATE UNIQUE INDEX IF NOT EXISTS uq_instrument_identifiers_listing_owner
ON instrument_identifiers(scheme, normalized_value, listing_id)
WHERE scope = 'LISTING' AND scheme NOT IN ('ISIN', 'FIGI');
CREATE UNIQUE INDEX IF NOT EXISTS uq_instrument_listings_market_identity
ON instrument_listings(instrument_id, UPPER(ticker), UPPER(mic), UPPER(currency));
CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_snapshots_complete_source_sha
ON catalog_snapshots(source, content_sha256)
WHERE status = 'COMPLETE';
CREATE INDEX IF NOT EXISTS idx_catalog_snapshots_source_retrieved
ON catalog_snapshots(source, retrieved_at, id);
CREATE INDEX IF NOT EXISTS idx_catalog_entries_snapshot_row
ON catalog_entries(snapshot_id, row_number);
CREATE INDEX IF NOT EXISTS idx_catalog_entries_isin
ON catalog_entries(isin);
CREATE INDEX IF NOT EXISTS idx_instrument_resolution_cases_entry_latest
ON instrument_resolution_cases(catalog_entry_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_instrument_resolution_cases_fingerprint
ON instrument_resolution_cases(request_fingerprint, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_listing_metadata_versions_verified_current
ON listing_metadata_versions(instrument_listing_id)
WHERE status = 'VERIFIED';
CREATE INDEX IF NOT EXISTS idx_catalog_listing_attestations_entry
ON catalog_listing_attestations(catalog_entry_id, instrument_listing_id);
CREATE TRIGGER IF NOT EXISTS trg_instrument_resolution_cases_no_update
BEFORE UPDATE ON instrument_resolution_cases
BEGIN
    SELECT RAISE(ABORT, 'instrument resolution cases are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_instrument_resolution_cases_no_delete
BEFORE DELETE ON instrument_resolution_cases
BEGIN
    SELECT RAISE(ABORT, 'instrument resolution cases are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_listing_metadata_versions_retirement_only
BEFORE UPDATE ON listing_metadata_versions
WHEN OLD.status != 'VERIFIED'
OR NEW.status != 'RETIRED'
OR NEW.id IS NOT OLD.id
OR NEW.instrument_listing_id IS NOT OLD.instrument_listing_id
OR NEW.venue_name IS NOT OLD.venue_name
OR NEW.timezone IS NOT OLD.timezone
OR NEW.instrument_type IS NOT OLD.instrument_type
OR NEW.source_code IS NOT OLD.source_code
OR NEW.observed_at IS NOT OLD.observed_at
OR NEW.evidence_hash IS NOT OLD.evidence_hash
OR NEW.version IS NOT OLD.version
OR NEW.supersedes_listing_metadata_version_id IS NOT OLD.supersedes_listing_metadata_version_id
OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'verified listing metadata may only be retired');
END;
CREATE TRIGGER IF NOT EXISTS trg_listing_metadata_versions_no_delete
BEFORE DELETE ON listing_metadata_versions
BEGIN
    SELECT RAISE(ABORT, 'listing metadata versions are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_catalog_listing_attestations_no_update
BEFORE UPDATE ON catalog_listing_attestations
BEGIN
    SELECT RAISE(ABORT, 'catalog listing attestations are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_catalog_listing_attestations_no_delete
BEFORE DELETE ON catalog_listing_attestations
BEGIN
    SELECT RAISE(ABORT, 'catalog listing attestations are append-only');
END;
CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_symbols_verified_listing_capability
ON provider_symbols(UPPER(provider), listing_id, UPPER(capability))
WHERE status = 'VERIFIED';
CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_symbols_verified_symbol_capability
ON provider_symbols(UPPER(provider), UPPER(capability), UPPER(normalized_symbol))
WHERE status = 'VERIFIED';
CREATE TRIGGER IF NOT EXISTS trg_provider_symbols_verified_retirement_only
BEFORE UPDATE ON provider_symbols
WHEN OLD.status = 'VERIFIED'
AND (
    NEW.status != 'RETIRED'
    OR NEW.id IS NOT OLD.id
    OR NEW.provider IS NOT OLD.provider
    OR NEW.listing_id IS NOT OLD.listing_id
    OR NEW.capability IS NOT OLD.capability
    OR NEW.provider_symbol IS NOT OLD.provider_symbol
    OR NEW.normalized_symbol IS NOT OLD.normalized_symbol
    OR NEW.source IS NOT OLD.source
    OR NEW.observed_at IS NOT OLD.observed_at
    OR NEW.verified_at IS NOT OLD.verified_at
    OR NEW.evidence_hash IS NOT OLD.evidence_hash
    OR NEW.version IS NOT OLD.version
    OR NEW.supersedes_provider_symbol_id IS NOT OLD.supersedes_provider_symbol_id
    OR NEW.created_at IS NOT OLD.created_at
)
BEGIN
    SELECT RAISE(ABORT, 'verified provider symbol must be retired explicitly');
END;
CREATE TRIGGER IF NOT EXISTS trg_provider_symbols_retired_immutable
BEFORE UPDATE ON provider_symbols
WHEN OLD.status = 'RETIRED'
BEGIN
    SELECT RAISE(ABORT, 'retired provider symbol history is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_provider_symbols_history_no_delete
BEFORE DELETE ON provider_symbols
WHEN OLD.status IN ('VERIFIED', 'RETIRED')
BEGIN
    SELECT RAISE(ABORT, 'verified provider symbol history cannot be deleted');
END;
CREATE TRIGGER IF NOT EXISTS trg_provider_symbols_history_no_replace_insert
BEFORE INSERT ON provider_symbols
WHEN EXISTS (
    SELECT 1
    FROM provider_symbols historical
    WHERE historical.status IN ('VERIFIED', 'RETIRED')
      AND (
          historical.id = NEW.id
          OR (
              UPPER(historical.provider) = UPPER(NEW.provider)
              AND historical.listing_id = NEW.listing_id
              AND UPPER(historical.capability) = UPPER(NEW.capability)
              AND historical.version = NEW.version
          )
          OR (
              NEW.status = 'VERIFIED'
              AND historical.status = 'VERIFIED'
              AND UPPER(historical.provider) = UPPER(NEW.provider)
              AND UPPER(historical.capability) = UPPER(NEW.capability)
              AND (
                  historical.listing_id = NEW.listing_id
                  OR UPPER(historical.normalized_symbol) = UPPER(NEW.normalized_symbol)
              )
          )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'provider symbol history cannot be replaced');
END;
CREATE TRIGGER IF NOT EXISTS trg_provider_symbols_history_no_replace_update
BEFORE UPDATE ON provider_symbols
WHEN EXISTS (
    SELECT 1
    FROM provider_symbols historical
    WHERE historical.id != OLD.id
      AND historical.status IN ('VERIFIED', 'RETIRED')
      AND (
          historical.id = NEW.id
          OR (
              UPPER(historical.provider) = UPPER(NEW.provider)
              AND historical.listing_id = NEW.listing_id
              AND UPPER(historical.capability) = UPPER(NEW.capability)
              AND historical.version = NEW.version
          )
          OR (
              NEW.status = 'VERIFIED'
              AND historical.status = 'VERIFIED'
              AND UPPER(historical.provider) = UPPER(NEW.provider)
              AND UPPER(historical.capability) = UPPER(NEW.capability)
              AND (
                  historical.listing_id = NEW.listing_id
                  OR UPPER(historical.normalized_symbol) = UPPER(NEW.normalized_symbol)
              )
          )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'provider symbol history cannot be replaced');
END;
CREATE TRIGGER IF NOT EXISTS trg_provider_symbols_supersedes_insert
BEFORE INSERT ON provider_symbols
WHEN NEW.supersedes_provider_symbol_id IS NOT NULL
AND NOT EXISTS (
    SELECT 1
    FROM provider_symbols previous
    WHERE previous.id = NEW.supersedes_provider_symbol_id
      AND previous.status = 'RETIRED'
      AND UPPER(previous.provider) = UPPER(NEW.provider)
      AND UPPER(previous.capability) = UPPER(NEW.capability)
      AND (
          UPPER(previous.normalized_symbol) = UPPER(NEW.normalized_symbol)
          OR previous.listing_id = NEW.listing_id
      )
)
BEGIN
    SELECT RAISE(ABORT, 'superseded provider symbol must be related and retired');
END;
CREATE TRIGGER IF NOT EXISTS trg_provider_symbols_supersedes_update
BEFORE UPDATE ON provider_symbols
WHEN NEW.supersedes_provider_symbol_id IS NOT NULL
AND NOT EXISTS (
    SELECT 1
    FROM provider_symbols previous
    WHERE previous.id = NEW.supersedes_provider_symbol_id
      AND previous.status = 'RETIRED'
      AND UPPER(previous.provider) = UPPER(NEW.provider)
      AND UPPER(previous.capability) = UPPER(NEW.capability)
      AND (
          UPPER(previous.normalized_symbol) = UPPER(NEW.normalized_symbol)
          OR previous.listing_id = NEW.listing_id
      )
)
BEGIN
    SELECT RAISE(ABORT, 'superseded provider symbol must be related and retired');
END;
CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_republic_attestations_active
ON trade_republic_attestations(listing_id)
WHERE record_status = 'ACTIVE';
CREATE TRIGGER IF NOT EXISTS trg_trade_republic_attestations_retirement_only
BEFORE UPDATE ON trade_republic_attestations
WHEN OLD.record_status != 'ACTIVE'
OR NEW.record_status != 'RETIRED'
OR NEW.id IS NOT OLD.id
OR NEW.listing_id IS NOT OLD.listing_id
OR NEW.status IS NOT OLD.status
OR NEW.source IS NOT OLD.source
OR NEW.observed_at IS NOT OLD.observed_at
OR NEW.evidence_hash IS NOT OLD.evidence_hash
OR NEW.version IS NOT OLD.version
OR NEW.supersedes_attestation_id IS NOT OLD.supersedes_attestation_id
OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'trade republic attestations may only be retired');
END;
CREATE TRIGGER IF NOT EXISTS trg_trade_republic_attestations_no_delete
BEFORE DELETE ON trade_republic_attestations
BEGIN
    SELECT RAISE(ABORT, 'trade republic attestations are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_trade_republic_attestations_insert_guard
BEFORE INSERT ON trade_republic_attestations
WHEN NEW.record_status != 'ACTIVE'
OR EXISTS (
    SELECT 1
    FROM trade_republic_attestations historical
    WHERE historical.id = NEW.id
       OR (historical.listing_id = NEW.listing_id AND historical.version = NEW.version)
)
OR (
    NEW.supersedes_attestation_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM trade_republic_attestations previous
        WHERE previous.id = NEW.supersedes_attestation_id
          AND previous.listing_id = NEW.listing_id
          AND previous.record_status = 'RETIRED'
          AND previous.version < NEW.version
    )
)
BEGIN
    SELECT RAISE(ABORT, 'trade republic attestation history cannot be replaced');
END;
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_observations_logical_revision
ON market_observations(
    listing_id, provider, capability, operation, kind,
    provider_observed_at, session, revision
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_observations_logical_hash
ON market_observations(
    listing_id, provider, capability, operation, kind,
    provider_observed_at, session, observation_hash
);
CREATE INDEX IF NOT EXISTS idx_market_observations_latest
ON market_observations(listing_id, capability, provider_observed_at DESC, revision DESC);
CREATE INDEX IF NOT EXISTS idx_market_data_rejections_scope
ON market_data_rejections(listing_id, provider, capability, operation, received_at);
CREATE INDEX IF NOT EXISTS idx_market_data_selection_observation
ON market_data_selection_events(selected_observation_id, selected_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_assessments_instrument_latest
ON quality_assessments(instrument_id, assessed_at DESC, id DESC);
CREATE TRIGGER IF NOT EXISTS trg_market_observations_no_update
BEFORE UPDATE ON market_observations
BEGIN
    SELECT RAISE(ABORT, 'market observations are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_market_observations_no_delete
BEFORE DELETE ON market_observations
BEGIN
    SELECT RAISE(ABORT, 'market observations are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_market_data_rejections_no_update
BEFORE UPDATE ON market_data_rejections
BEGIN
    SELECT RAISE(ABORT, 'market data rejections are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_market_data_rejections_no_delete
BEFORE DELETE ON market_data_rejections
BEGIN
    SELECT RAISE(ABORT, 'market data rejections are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_market_data_rejection_resolutions_no_update
BEFORE UPDATE ON market_data_rejection_resolutions
BEGIN
    SELECT RAISE(ABORT, 'market data rejection resolutions are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_market_data_rejection_resolutions_no_delete
BEFORE DELETE ON market_data_rejection_resolutions
BEGIN
    SELECT RAISE(ABORT, 'market data rejection resolutions are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_market_data_selection_events_no_update
BEFORE UPDATE ON market_data_selection_events
BEGIN
    SELECT RAISE(ABORT, 'market data selection events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_market_data_selection_events_no_delete
BEFORE DELETE ON market_data_selection_events
BEGIN
    SELECT RAISE(ABORT, 'market data selection events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_quality_assessments_no_update
BEFORE UPDATE ON quality_assessments
BEGIN
    SELECT RAISE(ABORT, 'quality assessments are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_quality_assessments_no_delete
BEFORE DELETE ON quality_assessments
BEGIN
    SELECT RAISE(ABORT, 'quality assessments are append-only');
END;
-- Una sola unita aperta (in attesa o rinviata) per listing/capability.
CREATE UNIQUE INDEX IF NOT EXISTS uq_refresh_requests_open_unit
ON refresh_requests(listing_id, capability)
WHERE state IN ('PENDING', 'BUDGET_DEFERRED');
CREATE INDEX IF NOT EXISTS idx_refresh_requests_queue
ON refresh_requests(state, priority, requested_at, listing_id);
CREATE INDEX IF NOT EXISTS idx_refresh_runs_request ON refresh_runs(request_id);
CREATE INDEX IF NOT EXISTS idx_price_history_asset_date ON price_history(asset_id, date);
CREATE INDEX IF NOT EXISTS idx_portfolio_positions_asset ON portfolio_positions(asset_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date ON portfolio_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_signals_asset_generated ON signals(asset_id, generated_at);
CREATE INDEX IF NOT EXISTS idx_signals_asset_created ON signals(asset_id, created_at);
CREATE INDEX IF NOT EXISTS idx_simulated_orders_asset_date ON simulated_orders(asset_id, order_date);
CREATE INDEX IF NOT EXISTS idx_news_items_published ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_items_symbol_published ON news_items(symbol, published_at);
CREATE INDEX IF NOT EXISTS idx_news_items_url ON news_items(url);
CREATE INDEX IF NOT EXISTS idx_api_cache_key ON api_cache(cache_key);
CREATE INDEX IF NOT EXISTS idx_api_cache_provider_symbol ON api_cache(provider, symbol);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider_date ON api_usage(provider, usage_date);
CREATE INDEX IF NOT EXISTS idx_provider_usage_windows_provider
ON provider_usage_windows(provider, window_kind, window_start);
CREATE INDEX IF NOT EXISTS idx_provider_request_log_provider_requested
ON provider_request_log(provider, requested_at);
CREATE INDEX IF NOT EXISTS idx_provider_request_log_fingerprint
ON provider_request_log(request_fingerprint, requested_at);
CREATE INDEX IF NOT EXISTS idx_fx_rates_pair_observed ON fx_rates(from_currency, to_currency, observed_at);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_backtest_equity_backtest_date ON backtest_equity_curve(backtest_id, date);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_backtest_date ON backtest_trades(backtest_id, date);
CREATE INDEX IF NOT EXISTS idx_backtest_positions_backtest ON backtest_positions(backtest_id);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_symbol ON ml_predictions(symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_features_daily_lookup
ON features_daily(asset_id, data_mode, timeframe, pipeline_version, date);
CREATE INDEX IF NOT EXISTS idx_lab_jobs_status_created ON lab_jobs(status, created_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_jobs_open
ON lab_jobs(kind, params_hash)
WHERE status IN ('QUEUED', 'RUNNING');
CREATE INDEX IF NOT EXISTS idx_lab_trials_family ON lab_trials(family_key, config_hash, created_at);
CREATE TRIGGER IF NOT EXISTS trg_lab_trials_no_update
BEFORE UPDATE ON lab_trials
BEGIN
    SELECT RAISE(ABORT, 'lab trials are append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_lab_trials_no_delete
BEFORE DELETE ON lab_trials
BEGIN
    SELECT RAISE(ABORT, 'lab trials are append-only');
END;
"""


SCHEMA = BASE_SCHEMA + INDEX_SCHEMA


MIGRATIONS = {
    "instruments": [
        (
            "quality_reason_code",
            "ALTER TABLE instruments ADD COLUMN quality_reason_code TEXT "
            "CHECK(quality_reason_code IS NULL OR quality_reason_code IN ("
            "'REFERENCE_INSTRUMENT', 'AMBIGUOUS_IDENTITY', 'MISSING_PRIMARY_ID', "
            "'MISSING_LISTING_METADATA', 'UNRESOLVED_CRITICAL_REJECTION', "
            "'NO_VALID_OBSERVATION', 'STALE_OBSERVATION', 'INSUFFICIENT_HISTORY', "
            "'PROVIDER_DIVERGENCE', 'COMPATIBLE_FALLBACK_IN_USE', "
            "'VALIDATED_OBSERVABLE', 'QUALIFICATION_RULES_MET'))",
        ),
        (
            "quality_assessed_at",
            "ALTER TABLE instruments ADD COLUMN quality_assessed_at TEXT",
        ),
    ],
    "assets": [
        ("sector", "ALTER TABLE assets ADD COLUMN sector TEXT"),
        ("country", "ALTER TABLE assets ADD COLUMN country TEXT"),
        ("risk_level", "ALTER TABLE assets ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'medium'"),
        ("isin", "ALTER TABLE assets ADD COLUMN isin TEXT"),
        (
            "instrument_listing_id",
            "ALTER TABLE assets ADD COLUMN instrument_listing_id INTEGER "
            "REFERENCES instrument_listings(id) ON DELETE RESTRICT",
        ),
        (
            "tax_category",
            "ALTER TABLE assets ADD COLUMN tax_category TEXT NOT NULL DEFAULT 'standard' "
            "CHECK(tax_category IN ('standard', 'government_bond', 'crypto', 'euro_emt'))",
        ),
    ],
    "signals": [
        ("symbol", "ALTER TABLE signals ADD COLUMN symbol TEXT"),
        ("technical_score", "ALTER TABLE signals ADD COLUMN technical_score REAL"),
        ("news_score", "ALTER TABLE signals ADD COLUMN news_score REAL NOT NULL DEFAULT 0"),
        ("final_score", "ALTER TABLE signals ADD COLUMN final_score REAL"),
        ("news_sentiment_label", "ALTER TABLE signals ADD COLUMN news_sentiment_label TEXT"),
        ("news_impact_level", "ALTER TABLE signals ADD COLUMN news_impact_level TEXT"),
        ("risk_level", "ALTER TABLE signals ADD COLUMN risk_level TEXT"),
        ("confidence", "ALTER TABLE signals ADD COLUMN confidence TEXT"),
        ("technical_summary", "ALTER TABLE signals ADD COLUMN technical_summary TEXT"),
        ("reasons_json", "ALTER TABLE signals ADD COLUMN reasons_json TEXT"),
        ("subscores_json", "ALTER TABLE signals ADD COLUMN subscores_json TEXT"),
        ("indicators_json", "ALTER TABLE signals ADD COLUMN indicators_json TEXT"),
        ("created_at", "ALTER TABLE signals ADD COLUMN created_at TEXT"),
        ("updated_at", "ALTER TABLE signals ADD COLUMN updated_at TEXT"),
        (
            "data_mode",
            "ALTER TABLE signals ADD COLUMN data_mode TEXT "
            "CHECK(data_mode IS NULL OR data_mode IN ('REAL', 'DEMO'))",
        ),
    ],
    "portfolio_positions": [
        ("symbol", "ALTER TABLE portfolio_positions ADD COLUMN symbol TEXT"),
        ("fx_rate_to_base", "ALTER TABLE portfolio_positions ADD COLUMN fx_rate_to_base REAL NOT NULL DEFAULT 0"),
        ("average_price_base", "ALTER TABLE portfolio_positions ADD COLUMN average_price_base REAL NOT NULL DEFAULT 0"),
        ("invested_amount", "ALTER TABLE portfolio_positions ADD COLUMN invested_amount REAL NOT NULL DEFAULT 0"),
        ("invested_amount_base", "ALTER TABLE portfolio_positions ADD COLUMN invested_amount_base REAL NOT NULL DEFAULT 0"),
        ("current_price", "ALTER TABLE portfolio_positions ADD COLUMN current_price REAL NOT NULL DEFAULT 0"),
        ("current_value", "ALTER TABLE portfolio_positions ADD COLUMN current_value REAL NOT NULL DEFAULT 0"),
        ("current_value_base", "ALTER TABLE portfolio_positions ADD COLUMN current_value_base REAL NOT NULL DEFAULT 0"),
        ("realized_pnl", "ALTER TABLE portfolio_positions ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0"),
        ("realized_pnl_base", "ALTER TABLE portfolio_positions ADD COLUMN realized_pnl_base REAL NOT NULL DEFAULT 0"),
        ("unrealized_pnl", "ALTER TABLE portfolio_positions ADD COLUMN unrealized_pnl REAL NOT NULL DEFAULT 0"),
        ("unrealized_pnl_base", "ALTER TABLE portfolio_positions ADD COLUMN unrealized_pnl_base REAL NOT NULL DEFAULT 0"),
        ("unrealized_pnl_percent", "ALTER TABLE portfolio_positions ADD COLUMN unrealized_pnl_percent REAL NOT NULL DEFAULT 0"),
        ("weight_percent", "ALTER TABLE portfolio_positions ADD COLUMN weight_percent REAL NOT NULL DEFAULT 0"),
        ("asset_type", "ALTER TABLE portfolio_positions ADD COLUMN asset_type TEXT"),
        ("updated_at", "ALTER TABLE portfolio_positions ADD COLUMN updated_at TEXT"),
    ],
    "simulated_orders": [
        ("symbol", "ALTER TABLE simulated_orders ADD COLUMN symbol TEXT"),
        ("order_type", "ALTER TABLE simulated_orders ADD COLUMN order_type TEXT"),
        ("currency", "ALTER TABLE simulated_orders ADD COLUMN currency TEXT NOT NULL DEFAULT 'EUR'"),
        ("fx_rate_to_base", "ALTER TABLE simulated_orders ADD COLUMN fx_rate_to_base REAL NOT NULL DEFAULT 0"),
        ("gross_amount", "ALTER TABLE simulated_orders ADD COLUMN gross_amount REAL NOT NULL DEFAULT 0"),
        ("gross_amount_base", "ALTER TABLE simulated_orders ADD COLUMN gross_amount_base REAL NOT NULL DEFAULT 0"),
        ("net_amount", "ALTER TABLE simulated_orders ADD COLUMN net_amount REAL NOT NULL DEFAULT 0"),
        ("net_amount_base", "ALTER TABLE simulated_orders ADD COLUMN net_amount_base REAL NOT NULL DEFAULT 0"),
        ("fees_base", "ALTER TABLE simulated_orders ADD COLUMN fees_base REAL NOT NULL DEFAULT 0"),
        ("order_date", "ALTER TABLE simulated_orders ADD COLUMN order_date TEXT"),
        ("note", "ALTER TABLE simulated_orders ADD COLUMN note TEXT"),
        ("strategy_tag", "ALTER TABLE simulated_orders ADD COLUMN strategy_tag TEXT"),
        ("created_at", "ALTER TABLE simulated_orders ADD COLUMN created_at TEXT"),
    ],
    "portfolio_snapshots": [
        ("base_currency", "ALTER TABLE portfolio_snapshots ADD COLUMN base_currency TEXT"),
    ],
    "price_history": [
        ("provider", "ALTER TABLE price_history ADD COLUMN provider TEXT"),
        ("is_real_data", "ALTER TABLE price_history ADD COLUMN is_real_data INTEGER NOT NULL DEFAULT 0"),
        ("fetched_at", "ALTER TABLE price_history ADD COLUMN fetched_at TEXT"),
        (
            "observation_id",
            "ALTER TABLE price_history ADD COLUMN observation_id INTEGER "
            "REFERENCES market_observations(id) ON DELETE RESTRICT",
        ),
    ],
    "news_items": [
        ("symbol", "ALTER TABLE news_items ADD COLUMN symbol TEXT"),
        ("provider", "ALTER TABLE news_items ADD COLUMN provider TEXT NOT NULL DEFAULT 'local'"),
        ("sentiment_label", "ALTER TABLE news_items ADD COLUMN sentiment_label TEXT"),
        ("impact_level", "ALTER TABLE news_items ADD COLUMN impact_level TEXT"),
        ("relevance_score", "ALTER TABLE news_items ADD COLUMN relevance_score REAL"),
        ("raw_json", "ALTER TABLE news_items ADD COLUMN raw_json TEXT"),
        ("updated_at", "ALTER TABLE news_items ADD COLUMN updated_at TEXT"),
    ],
    "api_cache": [
        ("endpoint", "ALTER TABLE api_cache ADD COLUMN endpoint TEXT"),
        ("symbol", "ALTER TABLE api_cache ADD COLUMN symbol TEXT"),
        ("request_url_hash", "ALTER TABLE api_cache ADD COLUMN request_url_hash TEXT"),
        ("response_json", "ALTER TABLE api_cache ADD COLUMN response_json TEXT"),
        ("status", "ALTER TABLE api_cache ADD COLUMN status TEXT NOT NULL DEFAULT 'OK'"),
        ("last_update", "ALTER TABLE api_cache ADD COLUMN last_update TEXT"),
    ],
    "backtest_runs": [
        ("benchmark_return_percent", "ALTER TABLE backtest_runs ADD COLUMN benchmark_return_percent REAL NOT NULL DEFAULT 0"),
        ("alpha_vs_benchmark", "ALTER TABLE backtest_runs ADD COLUMN alpha_vs_benchmark REAL NOT NULL DEFAULT 0"),
        # SP1 Task 10: i run esistenti diventano `v0` ("motore precedente"), i nuovi sono `v1`.
        ("engine_version", "ALTER TABLE backtest_runs ADD COLUMN engine_version TEXT NOT NULL DEFAULT 'v0'"),
        ("data_mode", "ALTER TABLE backtest_runs ADD COLUMN data_mode TEXT"),
        ("signal_name", "ALTER TABLE backtest_runs ADD COLUMN signal_name TEXT"),
        ("signal_timeframe", "ALTER TABLE backtest_runs ADD COLUMN signal_timeframe TEXT"),
        ("cost_profile_json", "ALTER TABLE backtest_runs ADD COLUMN cost_profile_json TEXT"),
        ("fingerprint", "ALTER TABLE backtest_runs ADD COLUMN fingerprint TEXT"),
        ("warnings_json", "ALTER TABLE backtest_runs ADD COLUMN warnings_json TEXT"),
        ("excluded_json", "ALTER TABLE backtest_runs ADD COLUMN excluded_json TEXT"),
        ("commission_eur", "ALTER TABLE backtest_runs ADD COLUMN commission_eur REAL"),
        ("spread_cost_eur", "ALTER TABLE backtest_runs ADD COLUMN spread_cost_eur REAL"),
        ("turnover", "ALTER TABLE backtest_runs ADD COLUMN turnover REAL"),
        ("exposure", "ALTER TABLE backtest_runs ADD COLUMN exposure REAL"),
    ],
    "backtest_trades": [
        ("commission", "ALTER TABLE backtest_trades ADD COLUMN commission REAL"),
        ("spread_cost", "ALTER TABLE backtest_trades ADD COLUMN spread_cost REAL"),
    ],
}


SIGNALS_REBUILD_SQL = """
DROP TABLE IF EXISTS signals_new;

CREATE TABLE signals_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    signal TEXT NOT NULL CHECK(signal IN ('STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL')),
    score REAL NOT NULL,
    technical_score REAL,
    news_score REAL NOT NULL DEFAULT 0,
    final_score REAL,
    news_sentiment_label TEXT,
    news_impact_level TEXT,
    risk_level TEXT,
    confidence TEXT,
    technical_summary TEXT,
    reasons_json TEXT,
    subscores_json TEXT,
    indicators_json TEXT,
    rationale TEXT,
    source TEXT NOT NULL DEFAULT 'scoring_engine',
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data_mode TEXT CHECK(data_mode IS NULL OR data_mode IN ('REAL', 'DEMO')),
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

INSERT INTO signals_new (
    id, asset_id, symbol, signal, score, technical_score, news_score, final_score,
    news_sentiment_label, news_impact_level, risk_level, confidence, technical_summary,
    reasons_json, subscores_json, indicators_json, rationale, source, generated_at, created_at, updated_at,
    data_mode
)
SELECT
    id,
    asset_id,
    symbol,
    signal,
    score,
    COALESCE(technical_score, score),
    COALESCE(news_score, 0),
    COALESCE(final_score, score),
    news_sentiment_label,
    news_impact_level,
    risk_level,
    confidence,
    technical_summary,
    reasons_json,
    subscores_json,
    indicators_json,
    rationale,
    source,
    COALESCE(generated_at, CURRENT_TIMESTAMP),
    COALESCE(created_at, generated_at, CURRENT_TIMESTAMP),
    COALESCE(updated_at, created_at, generated_at, CURRENT_TIMESTAMP),
    data_mode
FROM signals;

DROP TABLE signals;
ALTER TABLE signals_new RENAME TO signals;
"""


def _database_file() -> str:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return str(settings.database_path)


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(_database_file(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def migrate_db(connection: sqlite3.Connection) -> None:
    asset_columns_before = _table_columns(connection, "assets")
    position_columns_before = _table_columns(connection, "portfolio_positions")
    order_columns_before = _table_columns(connection, "simulated_orders")
    position_base_columns_added = "fx_rate_to_base" not in position_columns_before
    order_currency_added = "currency" not in order_columns_before
    order_base_columns_added = "fx_rate_to_base" not in order_columns_before
    tax_category_added = "tax_category" not in asset_columns_before

    listing_identity_index = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'index' AND name = 'uq_instrument_listings_market_identity'
        """
    ).fetchone()
    if (
        listing_identity_index is not None
        and "instrument_id" not in str(listing_identity_index["sql"])
    ):
        connection.execute("DROP INDEX uq_instrument_listings_market_identity")

    # Task 14: una versione del provider symbol puo sostituire la versione ritirata
    # dello stesso listing anche con simbolo diverso. I trigger legacy vengono
    # rimossi qui e ricreati da INDEX_SCHEMA con la nuova condizione.
    for trigger_name in (
        "trg_provider_symbols_supersedes_insert",
        "trg_provider_symbols_supersedes_update",
    ):
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            (trigger_name,),
        ).fetchone()
        if trigger is not None and "previous.listing_id = NEW.listing_id" not in str(trigger["sql"]):
            connection.execute(f"DROP TRIGGER {trigger_name}")

    for table_name, migrations in MIGRATIONS.items():
        columns = _table_columns(connection, table_name)
        for column_name, statement in migrations:
            if column_name not in columns:
                connection.execute(statement)
                columns.add(column_name)

    signal_schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'signals'"
    ).fetchone()
    if signal_schema and "STRONG_BUY" not in signal_schema["sql"]:
        connection.executescript(SIGNALS_REBUILD_SQL)
    if tax_category_added:
        connection.execute(
            "UPDATE assets SET tax_category = 'crypto' WHERE LOWER(asset_type) = 'crypto'"
        )
        for symbol in GOVERNMENT_BOND_TAX_SYMBOLS:
            connection.execute(
                "UPDATE assets SET tax_category = 'government_bond' WHERE UPPER(symbol) = ?",
                (symbol,),
            )

    if order_currency_added:
        connection.execute(
            """
            UPDATE simulated_orders
            SET currency = COALESCE(
                (SELECT assets.currency FROM assets WHERE assets.id = simulated_orders.asset_id),
                currency,
                'EUR'
            )
            """
        )
    if position_base_columns_added:
        connection.execute(
            """
            UPDATE portfolio_positions
            SET fx_rate_to_base = 1,
                average_price_base = average_price,
                invested_amount_base = invested_amount,
                current_value_base = current_value,
                realized_pnl_base = realized_pnl,
                unrealized_pnl_base = unrealized_pnl
            WHERE UPPER(currency) = 'EUR' AND fx_rate_to_base = 0
            """
        )
    if order_base_columns_added:
        connection.execute(
            """
            UPDATE simulated_orders
            SET fx_rate_to_base = 1,
                gross_amount_base = gross_amount,
                net_amount_base = net_amount,
                fees_base = fees
            WHERE UPPER(currency) = 'EUR' AND fx_rate_to_base = 0
            """
        )

    # Pulizia residui: posizioni quasi-azzerate da vendite precedenti (es. 3e-7 quote)
    # vengono portate a 0 cosi' spariscono dal portafoglio. Il P/L realizzato resta.
    connection.execute(
        """
        UPDATE portfolio_positions
        SET quantity = 0, current_value = 0, unrealized_pnl = 0, unrealized_pnl_percent = 0
        WHERE quantity > 0 AND quantity < 1e-6
        """
    )

    connection.execute("UPDATE signals SET technical_score = score WHERE technical_score IS NULL")
    connection.execute("UPDATE signals SET final_score = score WHERE final_score IS NULL")
    connection.execute("UPDATE signals SET news_score = 0 WHERE news_score IS NULL")
    connection.execute("UPDATE news_items SET symbol = UPPER(symbol) WHERE symbol IS NOT NULL")
    connection.execute(
        """
        UPDATE news_items
        SET symbol = (
            SELECT assets.symbol
            FROM assets
            WHERE assets.id = news_items.asset_id
        )
        WHERE symbol IS NULL AND asset_id IS NOT NULL
        """
    )
    connection.execute("UPDATE news_items SET updated_at = created_at WHERE updated_at IS NULL")

    # Il backfill dell'identita' e' serializzato separatamente: il rebuild legacy
    # di signals usa executescript(), che in SQLite delimita implicitamente la
    # propria transazione.
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        from backend.app.services.instrument_service import InstrumentService

        InstrumentService.backfill_active_assets(connection)
        InstrumentService.backfill_curated_crypto_ids(connection, datetime.now(UTC))
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()

    # Mantiene l'arricchimento legacy di Fase 1, ma soltanto dopo il backfill
    # del master: un ISIN dedotto dal ticker non diventa evidenza di identita'.
    for symbol, isin in ISIN_BY_SYMBOL.items():
        connection.execute(
            "UPDATE assets SET isin = ? WHERE UPPER(symbol) = ? AND (isin IS NULL OR isin = '')",
            (isin, symbol),
        )
    connection.commit()


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(BASE_SCHEMA)
        migrate_db(connection)
        connection.executescript(INDEX_SCHEMA)
