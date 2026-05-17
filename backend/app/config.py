from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(ROOT_DIR / "backend" / ".env", override=True)


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
    alpha_vantage_daily_limit: int = 20
    coingecko_daily_limit: int = 100
    fred_daily_limit: int = 100

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @classmethod
    def from_env(cls) -> "Settings":
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
            alpha_vantage_daily_limit=int(os.getenv("ALPHA_VANTAGE_DAILY_LIMIT", "20")),
            coingecko_daily_limit=int(os.getenv("COINGECKO_DAILY_LIMIT", "100")),
            fred_daily_limit=int(os.getenv("FRED_DAILY_LIMIT", "100")),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
