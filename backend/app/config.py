from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env", override=False)
load_dotenv(ROOT_DIR / "backend" / ".env", override=False)


def _csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    api_version: str
    database_path: Path
    cors_origins: list[str]
    cors_origin_regex: str | None = None
    enable_real_data: bool = False
    alpha_vantage_api_key: str | None = None
    coingecko_api_key: str | None = None
    fred_api_key: str | None = None
    api_cache_ttl_hours: int = 24
    provider_http_connect_timeout_seconds: float = 5.0
    provider_http_read_timeout_seconds: float = 20.0
    provider_retry_after_cap_seconds: int = 60
    provider_default_max_attempts: int = 3
    trade_republic_catalog_cache_ttl_hours: int = 24
    trade_republic_catalog_minute_limit: int = 2
    trade_republic_catalog_daily_limit: int = 4
    trade_republic_catalog_monthly_limit: int = 31
    openfigi_api_key: str | None = None
    openfigi_cache_ttl_hours: int = 168
    openfigi_minute_limit: int = 5
    openfigi_daily_limit: int = 100
    openfigi_monthly_limit: int = 1000
    ecb_fx_max_age_days: int = 7
    alpha_vantage_daily_limit: int = 20
    coingecko_daily_limit: int = 100
    fred_daily_limit: int = 100
    yahoo_daily_limit: int = 0
    yahoo_history_range: str = "5y"
    enable_real_news: bool = False
    finnhub_api_key: str | None = None
    enable_yahoo_news: bool = True
    yahoo_news_daily_limit: int = 0
    news_cache_ttl_hours: int = 6
    news_daily_limit: int = 20
    news_sentiment_weight: float = 5.0
    enable_alerts: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    enable_google_sheets_import: bool = False
    google_sheets_csv_url: str | None = None
    google_sheets_import_max_bytes: int = 5 * 1024 * 1024

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @classmethod
    def from_env(cls) -> Settings:
        db_path = Path(os.getenv("INVESTEDGE_DB_PATH", ROOT_DIR / "data" / "investedge.db"))
        if not db_path.is_absolute():
            db_path = ROOT_DIR / db_path
        app_env = os.getenv("INVESTEDGE_ENV", "local")
        local_dev_origins = [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ]
        configured_origins = _csv(os.getenv("INVESTEDGE_CORS_ORIGINS"), [])
        return cls(
            app_name=os.getenv("INVESTEDGE_APP_NAME", "InvestEdge API"),
            app_env=app_env,
            api_version=os.getenv("INVESTEDGE_API_VERSION", "0.1.0"),
            database_path=db_path,
            cors_origins=_unique([*local_dev_origins, *configured_origins]),
            cors_origin_regex=os.getenv("INVESTEDGE_CORS_ORIGIN_REGEX")
            or (r"^http://(localhost|127\.0\.0\.1):517\d+$" if app_env == "local" else None),
            enable_real_data=os.getenv("ENABLE_REAL_DATA", "false").lower() == "true",
            alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY") or None,
            coingecko_api_key=os.getenv("COINGECKO_API_KEY") or None,
            fred_api_key=os.getenv("FRED_API_KEY") or None,
            api_cache_ttl_hours=int(os.getenv("API_CACHE_TTL_HOURS", "24")),
            provider_http_connect_timeout_seconds=float(
                os.getenv("PROVIDER_HTTP_CONNECT_TIMEOUT_SECONDS", "5")
            ),
            provider_http_read_timeout_seconds=float(
                os.getenv("PROVIDER_HTTP_READ_TIMEOUT_SECONDS", "20")
            ),
            provider_retry_after_cap_seconds=int(
                os.getenv("PROVIDER_RETRY_AFTER_CAP_SECONDS", "60")
            ),
            provider_default_max_attempts=int(
                os.getenv("PROVIDER_DEFAULT_MAX_ATTEMPTS", "3")
            ),
            trade_republic_catalog_cache_ttl_hours=int(
                os.getenv("TRADE_REPUBLIC_CATALOG_CACHE_TTL_HOURS", "24")
            ),
            trade_republic_catalog_minute_limit=int(
                os.getenv("TRADE_REPUBLIC_CATALOG_MINUTE_LIMIT", "2")
            ),
            trade_republic_catalog_daily_limit=int(
                os.getenv("TRADE_REPUBLIC_CATALOG_DAILY_LIMIT", "4")
            ),
            trade_republic_catalog_monthly_limit=int(
                os.getenv("TRADE_REPUBLIC_CATALOG_MONTHLY_LIMIT", "31")
            ),
            openfigi_api_key=os.getenv("OPENFIGI_API_KEY") or None,
            openfigi_cache_ttl_hours=int(os.getenv("OPENFIGI_CACHE_TTL_HOURS", "168")),
            openfigi_minute_limit=int(os.getenv("OPENFIGI_MINUTE_LIMIT", "5")),
            openfigi_daily_limit=int(os.getenv("OPENFIGI_DAILY_LIMIT", "100")),
            openfigi_monthly_limit=int(os.getenv("OPENFIGI_MONTHLY_LIMIT", "1000")),
            ecb_fx_max_age_days=int(os.getenv("ECB_FX_MAX_AGE_DAYS", "7")),
            alpha_vantage_daily_limit=int(os.getenv("ALPHA_VANTAGE_DAILY_LIMIT", "20")),
            coingecko_daily_limit=int(os.getenv("COINGECKO_DAILY_LIMIT", "100")),
            fred_daily_limit=int(os.getenv("FRED_DAILY_LIMIT", "100")),
            yahoo_daily_limit=int(os.getenv("YAHOO_DAILY_LIMIT", "0")),
            yahoo_history_range=os.getenv("YAHOO_HISTORY_RANGE", "5y"),
            enable_real_news=os.getenv("ENABLE_REAL_NEWS", "false").lower() == "true",
            finnhub_api_key=os.getenv("FINNHUB_API_KEY") or None,
            enable_yahoo_news=os.getenv("ENABLE_YAHOO_NEWS", "true").lower() == "true",
            yahoo_news_daily_limit=int(os.getenv("YAHOO_NEWS_DAILY_LIMIT", "0")),
            news_cache_ttl_hours=int(os.getenv("NEWS_CACHE_TTL_HOURS", "6")),
            news_daily_limit=int(os.getenv("NEWS_DAILY_LIMIT", "20")),
            news_sentiment_weight=float(os.getenv("NEWS_SENTIMENT_WEIGHT", "5")),
            enable_alerts=os.getenv("ENABLE_ALERTS", "false").lower() == "true",
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            enable_google_sheets_import=os.getenv("ENABLE_GOOGLE_SHEETS_IMPORT", "false").lower() == "true",
            google_sheets_csv_url=os.getenv("GOOGLE_SHEETS_CSV_URL") or None,
            google_sheets_import_max_bytes=int(os.getenv("GOOGLE_SHEETS_IMPORT_MAX_BYTES", "5242880")),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
