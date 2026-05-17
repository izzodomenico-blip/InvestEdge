from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    api_version: str
    database_path: Path
    cors_origins: list[str]

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @classmethod
    def from_env(cls) -> "Settings":
        db_path = Path(os.getenv("INVESTEDGE_DB_PATH", ROOT_DIR / "data" / "investedge.db"))
        if not db_path.is_absolute():
            db_path = ROOT_DIR / db_path
        return cls(
            app_name=os.getenv("INVESTEDGE_APP_NAME", "InvestEdge API"),
            app_env=os.getenv("INVESTEDGE_ENV", "local"),
            api_version=os.getenv("INVESTEDGE_API_VERSION", "0.1.0"),
            database_path=db_path,
            cors_origins=_csv(
                os.getenv("INVESTEDGE_CORS_ORIGINS"),
                ["http://localhost:5173", "http://127.0.0.1:5173"],
            ),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
