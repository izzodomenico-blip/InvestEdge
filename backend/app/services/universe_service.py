from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
UNIVERSE_DIR = ROOT_DIR / "data" / "universe"
LEVEL_RANK = {"CORE": 3, "EXTENDED": 2, "CANDIDATE": 1}
DEFAULT_FREQUENCY = {"CORE": 1, "EXTENDED": 7, "CANDIDATE": 30}
DEFAULT_PROVIDER = {
    "stock": "alpha_vantage",
    "etf": "alpha_vantage",
    "bond_etf": "alpha_vantage",
    "crypto": "coingecko",
    "macro": "fred",
    "bond_proxy": "fred",
    "bond": "fred",
}


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _asset_type(value: str | None) -> str:
    normalized = (value or "stock").strip().lower().replace(" ", "_")
    aliases = {
        "stocks": "stock",
        "equity": "stock",
        "equities": "stock",
        "cryptoasset": "crypto",
        "cryptocurrency": "crypto",
        "bond_etfs": "bond_etf",
        "bond_proxy": "bond_proxy",
    }
    return aliases.get(normalized, normalized)


def _risk_level(asset_type: str) -> str:
    if asset_type == "crypto":
        return "very_high"
    if asset_type in {"bond", "bond_etf", "macro", "bond_proxy"}:
        return "low"
    return "medium"


@dataclass
class UniverseService:
    def import_universe_from_csv(
        self,
        connection: sqlite3.Connection,
        file_path: str | Path,
        universe_level: str,
    ) -> dict[str, int | str]:
        level = self._normalize_level(universe_level)
        path = self._resolve_csv_path(file_path)
        inserted = 0
        updated = 0
        skipped = 0
        total_rows = 0

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                total_rows += 1
                payload = self._row_payload(row, level)
                if payload is None:
                    skipped += 1
                    continue
                was_inserted = self._upsert_universe_row(connection, payload, preserve_stronger_level=True)
                if was_inserted:
                    inserted += 1
                else:
                    updated += 1

        self.sync_assets(connection)
        self.update_refresh_priority(connection)
        return {
            "file_name": path.name,
            "universe_level": level,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "total_rows": total_rows,
        }

    def get_universe(
        self,
        connection: sqlite3.Connection,
        level: str | None = None,
        asset_type: str | None = None,
        active_only: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.sync_assets(connection)
        params: list[Any] = []
        where: list[str] = []
        if level:
            where.append("au.universe_level = ?")
            params.append(self._normalize_level(level))
        if asset_type:
            where.append("au.asset_type = ?")
            params.append(_asset_type(asset_type))
        if active_only:
            where.append("au.is_active = 1")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(max(1, min(int(limit), 1000)))

        rows = connection.execute(
            f"""
            SELECT
                au.*,
                COALESCE(
                    a.risk_level,
                    CASE
                        WHEN au.asset_type = 'crypto' THEN 'very_high'
                        WHEN au.asset_type IN ('bond', 'bond_etf', 'macro', 'bond_proxy') THEN 'low'
                        ELSE 'medium'
                    END
                ) AS risk_level,
                latest.close AS last_price,
                latest.date AS last_price_date,
                latest.source AS last_source,
                latest.provider AS provider,
                latest.is_real_data AS is_real_data,
                latest.fetched_at AS last_fetch_at,
                CASE
                    WHEN previous.close IS NULL OR previous.close = 0 THEN NULL
                    ELSE ((latest.close - previous.close) / previous.close) * 100
                END AS daily_change_pct,
                sig.score,
                sig.signal,
                sig.confidence,
                sig.technical_summary,
                ml.model_id AS ml_model_id,
                ml.target_type AS ml_target_type,
                CASE
                    WHEN ml.target_type = 'POSITIVE_RETURN' THEN ml.probability_positive
                    WHEN ml.target_type = 'OUTPERFORM_BENCHMARK' THEN ml.probability_outperform
                    WHEN ml.target_type = 'DRAWDOWN_RISK' THEN ml.probability_drawdown
                    ELSE COALESCE(ml.probability_positive, ml.probability_outperform, ml.probability_drawdown)
                END AS ml_probability,
                ml.confidence AS ml_confidence,
                ml.predicted_label AS ml_label
            FROM asset_universe au
            LEFT JOIN assets a ON a.id = au.asset_id
            LEFT JOIN price_history latest
                ON latest.id = (
                    SELECT ph.id
                    FROM price_history ph
                    WHERE ph.asset_id = au.asset_id
                    ORDER BY ph.date DESC, ph.is_real_data DESC, ph.id DESC
                    LIMIT 1
                )
            LEFT JOIN price_history previous
                ON previous.id = (
                    SELECT ph.id
                    FROM price_history ph
                    WHERE ph.asset_id = au.asset_id
                    ORDER BY ph.date DESC, ph.is_real_data DESC, ph.id DESC
                    LIMIT 1 OFFSET 1
                )
            LEFT JOIN signals sig
                ON sig.id = (
                    SELECT s.id
                    FROM signals s
                    WHERE s.asset_id = au.asset_id
                    ORDER BY s.created_at DESC, s.id DESC
                    LIMIT 1
                )
            LEFT JOIN ml_predictions ml
                ON ml.id = (
                    SELECT mp.id
                    FROM ml_predictions mp
                    WHERE UPPER(mp.symbol) = UPPER(au.symbol)
                    ORDER BY mp.created_at DESC, mp.id DESC
                    LIMIT 1
                )
            {where_sql}
            ORDER BY
                CASE au.universe_level WHEN 'CORE' THEN 1 WHEN 'EXTENDED' THEN 2 ELSE 3 END,
                au.refresh_priority DESC,
                au.symbol ASC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [self._universe_row_to_dict(row) for row in rows]

    def get_summary(self, connection: sqlite3.Connection) -> dict[str, Any]:
        self.sync_assets(connection)
        base = connection.execute(
            """
            SELECT
                COUNT(*) AS total_assets,
                SUM(CASE WHEN universe_level = 'CORE' THEN 1 ELSE 0 END) AS core_count,
                SUM(CASE WHEN universe_level = 'EXTENDED' THEN 1 ELSE 0 END) AS extended_count,
                SUM(CASE WHEN universe_level = 'CANDIDATE' THEN 1 ELSE 0 END) AS candidate_count,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_count,
                SUM(CASE WHEN is_watchlisted = 1 THEN 1 ELSE 0 END) AS watchlist_count,
                SUM(CASE WHEN is_portfolio_asset = 1 THEN 1 ELSE 0 END) AS portfolio_count,
                SUM(CASE WHEN asset_id IS NOT NULL THEN 1 ELSE 0 END) AS priced_assets_count
            FROM asset_universe
            """
        ).fetchone()
        return {
            "total_assets": int(base["total_assets"] or 0),
            "core_count": int(base["core_count"] or 0),
            "extended_count": int(base["extended_count"] or 0),
            "candidate_count": int(base["candidate_count"] or 0),
            "active_count": int(base["active_count"] or 0),
            "watchlist_count": int(base["watchlist_count"] or 0),
            "portfolio_count": int(base["portfolio_count"] or 0),
            "priced_assets_count": int(base["priced_assets_count"] or 0),
            "refresh_candidates_count": int(base["active_count"] or 0),
            "by_asset_type": self._count_by(connection, "asset_type"),
            "by_country": self._count_by(connection, "country"),
            "by_exchange": self._count_by(connection, "exchange"),
        }

    def promote_to_core(self, connection: sqlite3.Connection, symbol: str) -> dict[str, Any]:
        return self.promote(connection, symbol, "CORE")

    def demote_to_extended(self, connection: sqlite3.Connection, symbol: str) -> dict[str, Any]:
        return self.promote(connection, symbol, "EXTENDED")

    def promote(self, connection: sqlite3.Connection, symbol: str, universe_level: str) -> dict[str, Any]:
        level = self._normalize_level(universe_level)
        row = self._universe_row(connection, symbol)
        if row is None:
            raise ValueError(f"Asset {symbol.upper()} non presente nell'universo.")
        now = _now()
        connection.execute(
            """
            UPDATE asset_universe
            SET universe_level = ?, refresh_frequency_days = ?, updated_at = ?
            WHERE UPPER(symbol) = UPPER(?)
            """,
            (level, DEFAULT_FREQUENCY[level], now, symbol),
        )
        self.update_refresh_priority(connection)
        return self._single_universe_asset(connection, symbol)

    def add_to_watchlist(self, connection: sqlite3.Connection, symbol: str) -> dict[str, Any]:
        if self._universe_row(connection, symbol) is None:
            self._create_from_asset_if_possible(connection, symbol)
        if self._universe_row(connection, symbol) is None:
            raise ValueError(f"Asset {symbol.upper()} non presente nell'universo.")
        connection.execute(
            "UPDATE asset_universe SET is_watchlisted = 1, updated_at = ? WHERE UPPER(symbol) = UPPER(?)",
            (_now(), symbol),
        )
        self.update_refresh_priority(connection)
        return self._single_universe_asset(connection, symbol)

    def remove_from_watchlist(self, connection: sqlite3.Connection, symbol: str) -> dict[str, Any]:
        if self._universe_row(connection, symbol) is None:
            raise ValueError(f"Asset {symbol.upper()} non presente nell'universo.")
        connection.execute(
            "UPDATE asset_universe SET is_watchlisted = 0, updated_at = ? WHERE UPPER(symbol) = UPPER(?)",
            (_now(), symbol),
        )
        self.update_refresh_priority(connection)
        return self._single_universe_asset(connection, symbol)

    def get_refresh_candidates(self, connection: sqlite3.Connection, limit: int | None = 10) -> list[dict[str, Any]]:
        self.update_refresh_priority(connection)
        limit_value = max(1, min(int(limit or 10), 100))
        rows = connection.execute(
            """
            SELECT *
            FROM asset_universe
            WHERE is_active = 1
            ORDER BY
                refresh_priority DESC,
                CASE WHEN last_price_refresh_at IS NULL THEN 0 ELSE 1 END ASC,
                COALESCE(last_price_refresh_at, '1900-01-01') ASC,
                symbol ASC
            LIMIT ?
            """,
            (limit_value,),
        ).fetchall()
        return [self._universe_row_to_dict(row) for row in rows]

    def update_refresh_priority(self, connection: sqlite3.Connection) -> None:
        self.sync_assets(connection)
        latest_by_asset = connection.execute(
            """
            SELECT asset_id, MAX(COALESCE(fetched_at, created_at)) AS last_refresh
            FROM price_history
            GROUP BY asset_id
            """
        ).fetchall()
        for row in latest_by_asset:
            connection.execute(
                "UPDATE asset_universe SET last_price_refresh_at = COALESCE(?, last_price_refresh_at) WHERE asset_id = ?",
                (row["last_refresh"], row["asset_id"]),
            )

        latest_signals = connection.execute(
            """
            SELECT asset_id, MAX(COALESCE(updated_at, created_at, generated_at)) AS last_signal
            FROM signals
            GROUP BY asset_id
            """
        ).fetchall()
        for row in latest_signals:
            connection.execute(
                "UPDATE asset_universe SET last_signal_refresh_at = COALESCE(?, last_signal_refresh_at) WHERE asset_id = ?",
                (row["last_signal"], row["asset_id"]),
            )

        latest_news = connection.execute(
            """
            SELECT symbol, MAX(COALESCE(updated_at, created_at, published_at)) AS last_news
            FROM news_items
            WHERE symbol IS NOT NULL
            GROUP BY UPPER(symbol)
            """
        ).fetchall()
        for row in latest_news:
            connection.execute(
                "UPDATE asset_universe SET last_news_refresh_at = COALESCE(?, last_news_refresh_at) WHERE UPPER(symbol) = UPPER(?)",
                (row["last_news"], row["symbol"]),
            )

        rows = connection.execute(
            """
            SELECT au.id, au.symbol, au.universe_level, au.is_watchlisted, au.is_portfolio_asset,
                   sig.signal, news.high_impact_count
            FROM asset_universe au
            LEFT JOIN signals sig
                ON sig.id = (
                    SELECT s.id
                    FROM signals s
                    WHERE s.asset_id = au.asset_id
                    ORDER BY s.created_at DESC, s.id DESC
                    LIMIT 1
                )
            LEFT JOIN (
                SELECT UPPER(symbol) AS symbol, COUNT(*) AS high_impact_count
                FROM news_items
                WHERE impact_level = 'HIGH'
                GROUP BY UPPER(symbol)
            ) news ON news.symbol = UPPER(au.symbol)
            """
        ).fetchall()
        for row in rows:
            priority = {"CORE": 60, "EXTENDED": 30, "CANDIDATE": 10}.get(row["universe_level"], 0)
            if row["is_portfolio_asset"]:
                priority += 100
            if row["is_watchlisted"]:
                priority += 80
            if row["signal"] in {"STRONG_BUY", "BUY", "SELL", "REDUCE"}:
                priority += 15
            if int(row["high_impact_count"] or 0) > 0:
                priority += 10
            connection.execute(
                "UPDATE asset_universe SET refresh_priority = ?, updated_at = ? WHERE id = ?",
                (priority, _now(), row["id"]),
            )

    def get_screening_universe(self, connection: sqlite3.Connection, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return self.get_universe(
            connection,
            level=filters.get("level"),
            asset_type=filters.get("asset_type"),
            active_only=bool(filters.get("active_only", True)),
            limit=filters.get("limit"),
        )

    def ensure_asset_record(self, connection: sqlite3.Connection, symbol: str) -> int | None:
        asset = connection.execute(
            "SELECT id FROM assets WHERE UPPER(symbol) = UPPER(?) LIMIT 1",
            (symbol,),
        ).fetchone()
        if asset:
            return int(asset["id"])
        row = self._universe_row(connection, symbol)
        if row is None:
            return None
        now = _now()
        cursor = connection.execute(
            """
            INSERT INTO assets (
                symbol, name, asset_type, exchange, currency, sector, country, risk_level, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["symbol"],
                row["name"],
                row["asset_type"],
                row["exchange"],
                row["currency"],
                row["sector"],
                row["country"],
                _risk_level(row["asset_type"]),
                now,
                now,
            ),
        )
        asset_id = int(cursor.lastrowid)
        connection.execute(
            "UPDATE asset_universe SET asset_id = ?, updated_at = ? WHERE id = ?",
            (asset_id, now, row["id"]),
        )
        return asset_id

    def sync_assets(self, connection: sqlite3.Connection, watchlist_symbols: set[str] | None = None) -> None:
        now = _now()
        asset_rows = connection.execute(
            """
            SELECT id, symbol, name, asset_type, exchange, currency, sector, country
            FROM assets
            """
        ).fetchall()
        for asset in asset_rows:
            existing = self._universe_row(connection, asset["symbol"])
            level = existing["universe_level"] if existing else "CORE"
            payload = {
                "asset_id": asset["id"],
                "symbol": asset["symbol"],
                "name": asset["name"],
                "asset_type": asset["asset_type"],
                "exchange": asset["exchange"],
                "currency": asset["currency"],
                "country": asset["country"],
                "sector": asset["sector"],
                "industry": None,
                "universe_level": level,
                "is_active": 1,
                "is_watchlisted": 1 if watchlist_symbols and asset["symbol"] in watchlist_symbols else None,
                "refresh_frequency_days": DEFAULT_FREQUENCY[level],
                "data_provider": DEFAULT_PROVIDER.get(asset["asset_type"]),
                "notes": "Seed/demo asset prezzato localmente.",
            }
            self._upsert_universe_row(connection, payload, preserve_stronger_level=True)
            connection.execute(
                "UPDATE asset_universe SET asset_id = ?, updated_at = ? WHERE UPPER(symbol) = UPPER(?)",
                (asset["id"], now, asset["symbol"]),
            )
            if watchlist_symbols and asset["symbol"] in watchlist_symbols:
                connection.execute(
                    "UPDATE asset_universe SET is_watchlisted = 1, updated_at = ? WHERE UPPER(symbol) = UPPER(?)",
                    (now, asset["symbol"]),
                )

        connection.execute("UPDATE asset_universe SET is_portfolio_asset = 0")
        connection.execute(
            """
            UPDATE asset_universe
            SET is_portfolio_asset = 1, updated_at = ?
            WHERE UPPER(symbol) IN (
                SELECT UPPER(symbol)
                FROM portfolio_positions
                WHERE quantity > 0
            )
            """,
            (now,),
        )

    def priced_symbols_for_level(
        self,
        connection: sqlite3.Connection,
        level: str = "CORE",
        limit: int | None = None,
    ) -> list[str]:
        self.sync_assets(connection)
        params: list[Any] = [self._normalize_level(level)]
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(max(1, min(int(limit), 500)))
        rows = connection.execute(
            f"""
            SELECT DISTINCT au.symbol
            FROM asset_universe au
            JOIN price_history ph ON ph.asset_id = au.asset_id
            WHERE au.universe_level = ? AND au.is_active = 1
            ORDER BY au.refresh_priority DESC, au.symbol ASC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [row["symbol"] for row in rows]

    def _single_universe_asset(self, connection: sqlite3.Connection, symbol: str) -> dict[str, Any]:
        rows = self.get_universe(connection, active_only=False, limit=1000)
        for row in rows:
            if row["symbol"].upper() == symbol.upper():
                return row
        raise ValueError(f"Asset {symbol.upper()} non presente nell'universo.")

    def _create_from_asset_if_possible(self, connection: sqlite3.Connection, symbol: str) -> None:
        asset = connection.execute(
            """
            SELECT id, symbol, name, asset_type, exchange, currency, sector, country
            FROM assets
            WHERE UPPER(symbol) = UPPER(?)
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        if not asset:
            return
        payload = {
            "asset_id": asset["id"],
            "symbol": asset["symbol"],
            "name": asset["name"],
            "asset_type": asset["asset_type"],
            "exchange": asset["exchange"],
            "currency": asset["currency"],
            "country": asset["country"],
            "sector": asset["sector"],
            "industry": None,
            "universe_level": "CANDIDATE",
            "is_active": 1,
            "is_watchlisted": 0,
            "refresh_frequency_days": DEFAULT_FREQUENCY["CANDIDATE"],
            "data_provider": DEFAULT_PROVIDER.get(asset["asset_type"]),
            "notes": "Creato da asset esistente.",
        }
        self._upsert_universe_row(connection, payload, preserve_stronger_level=True)

    def _upsert_universe_row(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        preserve_stronger_level: bool,
    ) -> bool:
        now = _now()
        existing = self._universe_row(connection, payload["symbol"])
        asset_id = payload.get("asset_id")
        if asset_id is None:
            asset = connection.execute(
                "SELECT id FROM assets WHERE UPPER(symbol) = UPPER(?) LIMIT 1",
                (payload["symbol"],),
            ).fetchone()
            asset_id = asset["id"] if asset else None

        if existing is None:
            connection.execute(
                """
                INSERT INTO asset_universe (
                    asset_id, symbol, name, asset_type, exchange, currency, country, sector, industry,
                    universe_level, is_active, is_watchlisted, refresh_frequency_days, data_provider,
                    notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    payload["symbol"],
                    payload["name"],
                    payload["asset_type"],
                    payload.get("exchange"),
                    payload["currency"],
                    payload.get("country"),
                    payload.get("sector"),
                    payload.get("industry"),
                    payload["universe_level"],
                    int(payload.get("is_active", 1)),
                    int(payload.get("is_watchlisted") or 0),
                    int(payload.get("refresh_frequency_days") or DEFAULT_FREQUENCY[payload["universe_level"]]),
                    payload.get("data_provider"),
                    payload.get("notes"),
                    now,
                    now,
                ),
            )
            return True

        next_level = payload["universe_level"]
        if preserve_stronger_level and LEVEL_RANK[existing["universe_level"]] > LEVEL_RANK[next_level]:
            next_level = existing["universe_level"]
        is_watchlisted = existing["is_watchlisted"] if payload.get("is_watchlisted") is None else int(payload["is_watchlisted"])
        connection.execute(
            """
            UPDATE asset_universe
            SET asset_id = COALESCE(?, asset_id),
                name = ?,
                asset_type = ?,
                exchange = ?,
                currency = ?,
                country = ?,
                sector = ?,
                industry = COALESCE(?, industry),
                universe_level = ?,
                is_active = ?,
                is_watchlisted = ?,
                refresh_frequency_days = ?,
                data_provider = COALESCE(?, data_provider),
                notes = COALESCE(?, notes),
                updated_at = ?
            WHERE id = ?
            """,
            (
                asset_id,
                payload["name"],
                payload["asset_type"],
                payload.get("exchange"),
                payload["currency"],
                payload.get("country"),
                payload.get("sector"),
                payload.get("industry"),
                next_level,
                int(payload.get("is_active", existing["is_active"])),
                int(is_watchlisted),
                int(payload.get("refresh_frequency_days") or DEFAULT_FREQUENCY[next_level]),
                payload.get("data_provider"),
                payload.get("notes"),
                now,
                existing["id"],
            ),
        )
        return False

    def _row_payload(self, row: dict[str, str], universe_level: str) -> dict[str, Any] | None:
        normalized = {key.strip().lower(): value for key, value in row.items() if key}
        symbol = _clean(normalized.get("symbol"))
        if not symbol:
            return None
        asset_type = _asset_type(_clean(normalized.get("asset_type")))
        return {
            "symbol": symbol.upper(),
            "name": _clean(normalized.get("name")) or symbol.upper(),
            "asset_type": asset_type,
            "exchange": _clean(normalized.get("exchange")),
            "currency": (_clean(normalized.get("currency")) or "USD").upper(),
            "country": _clean(normalized.get("country")),
            "sector": _clean(normalized.get("sector")),
            "industry": _clean(normalized.get("industry")),
            "universe_level": universe_level,
            "is_active": 1,
            "is_watchlisted": None,
            "refresh_frequency_days": DEFAULT_FREQUENCY[universe_level],
            "data_provider": _clean(normalized.get("data_provider")) or DEFAULT_PROVIDER.get(asset_type),
            "notes": _clean(normalized.get("notes")),
        }

    def _resolve_csv_path(self, file_path: str | Path) -> Path:
        raw = Path(file_path)
        candidate = raw if raw.is_absolute() else UNIVERSE_DIR / raw
        resolved = candidate.resolve()
        base = UNIVERSE_DIR.resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise ValueError("I CSV universe devono trovarsi in data/universe/.") from exc
        if not resolved.exists():
            raise ValueError(f"CSV universe non trovato: {resolved.name}.")
        return resolved

    def _normalize_level(self, level: str) -> str:
        normalized = level.strip().upper().replace("_UNIVERSE", "")
        if normalized not in LEVEL_RANK:
            raise ValueError("Universe level non valido. Usa CORE, EXTENDED o CANDIDATE.")
        return normalized

    def _universe_row(self, connection: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM asset_universe WHERE UPPER(symbol) = UPPER(?) LIMIT 1",
            (symbol,),
        ).fetchone()

    def _count_by(self, connection: sqlite3.Connection, column: str) -> dict[str, int]:
        if column not in {"asset_type", "country", "exchange"}:
            return {}
        rows = connection.execute(
            f"""
            SELECT COALESCE({column}, 'N/D') AS label, COUNT(*) AS count
            FROM asset_universe
            GROUP BY COALESCE({column}, 'N/D')
            ORDER BY count DESC, label ASC
            """
        ).fetchall()
        return {row["label"]: int(row["count"]) for row in rows}

    def _universe_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "asset_id": int(row["asset_id"]) if row["asset_id"] is not None else None,
            "symbol": row["symbol"],
            "name": row["name"],
            "asset_type": row["asset_type"],
            "exchange": row["exchange"],
            "currency": row["currency"],
            "country": row["country"],
            "sector": row["sector"],
            "industry": row["industry"],
            "risk_level": row["risk_level"] if "risk_level" in row.keys() else _risk_level(row["asset_type"]),
            "universe_level": row["universe_level"],
            "is_active": bool(row["is_active"]),
            "is_watchlisted": bool(row["is_watchlisted"]),
            "is_portfolio_asset": bool(row["is_portfolio_asset"]),
            "refresh_priority": int(row["refresh_priority"] or 0),
            "refresh_frequency_days": int(row["refresh_frequency_days"] or DEFAULT_FREQUENCY[row["universe_level"]]),
            "last_price_refresh_at": row["last_price_refresh_at"],
            "last_signal_refresh_at": row["last_signal_refresh_at"],
            "last_news_refresh_at": row["last_news_refresh_at"],
            "data_provider": row["data_provider"],
            "notes": row["notes"],
            "last_price": row["last_price"] if "last_price" in row.keys() else None,
            "daily_change_pct": row["daily_change_pct"] if "daily_change_pct" in row.keys() else None,
            "last_source": row["last_source"] if "last_source" in row.keys() else None,
            "provider": row["provider"] if "provider" in row.keys() else row["data_provider"],
            "is_real_data": bool(row["is_real_data"]) if "is_real_data" in row.keys() and row["is_real_data"] is not None else False,
            "last_price_date": row["last_price_date"] if "last_price_date" in row.keys() else None,
            "last_fetch_at": row["last_fetch_at"] if "last_fetch_at" in row.keys() else None,
            "score": row["score"] if "score" in row.keys() else None,
            "signal": row["signal"] if "signal" in row.keys() else None,
            "confidence": row["confidence"] if "confidence" in row.keys() else None,
            "technical_summary": row["technical_summary"] if "technical_summary" in row.keys() else None,
            "ml_model_id": row["ml_model_id"] if "ml_model_id" in row.keys() else None,
            "ml_probability": row["ml_probability"] if "ml_probability" in row.keys() else None,
            "ml_confidence": row["ml_confidence"] if "ml_confidence" in row.keys() else None,
            "ml_label": row["ml_label"] if "ml_label" in row.keys() else None,
            "ml_target_type": row["ml_target_type"] if "ml_target_type" in row.keys() else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
