from __future__ import annotations

import sqlite3
from typing import Literal

from backend.app.models import AssetCreate, AssetOut
from backend.app.services.fx_service import FXRateUnavailable, FXService
from backend.app.services.instrument_service import InstrumentService

fx_service = FXService()


def _latest_price_metrics(connection: sqlite3.Connection, asset_id: int) -> tuple[float | None, float | None]:
    rows = connection.execute(
        """
        SELECT close
        FROM price_history
        WHERE asset_id = ?
        ORDER BY date DESC, is_real_data DESC, id DESC
        LIMIT 2
        """,
        (asset_id,),
    ).fetchall()

    if not rows:
        return None, None

    latest = float(rows[0]["close"])
    if len(rows) < 2 or rows[1]["close"] in (None, 0):
        return latest, None

    previous = float(rows[1]["close"])
    return latest, ((latest - previous) / previous) * 100


def _latest_price_metadata(connection: sqlite3.Connection, asset_id: int) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT date, source, provider, is_real_data, fetched_at
        FROM price_history
        WHERE asset_id = ?
        ORDER BY date DESC, is_real_data DESC, id DESC
        LIMIT 1
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        return {
            "last_source": None,
            "provider": None,
            "is_real_data": False,
            "last_price_date": None,
            "last_fetch_at": None,
        }
    return {
        "last_source": row["source"],
        "provider": row["provider"],
        "is_real_data": bool(row["is_real_data"]),
        "last_price_date": row["date"],
        "last_fetch_at": row["fetched_at"],
    }


def _base_price_metrics(
    connection: sqlite3.Connection,
    currency: str,
    last_price: float | None,
) -> tuple[float | None, float | None]:
    try:
        fx_rate_to_base = fx_service.get_rate(connection, currency).rate
    except FXRateUnavailable:
        return None, None
    last_price_base = float(last_price) * fx_rate_to_base if last_price is not None else None
    return fx_rate_to_base, last_price_base


def _asset_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> AssetOut:
    fx_rate_to_base, last_price_base = _base_price_metrics(connection, row["currency"], row["last_price"])
    return AssetOut(
        id=row["id"],
        symbol=row["symbol"],
        name=row["name"],
        asset_type=row["asset_type"],
        tax_category=row["tax_category"],
        exchange=row["exchange"],
        currency=row["currency"],
        sector=row["sector"],
        country=row["country"],
        risk_level=row["risk_level"],
        isin=row["isin"],
        last_price=row["last_price"],
        fx_rate_to_base=fx_rate_to_base,
        last_price_base=last_price_base,
        daily_change_pct=row["daily_change_pct"],
        last_source=row["last_source"],
        provider=row["provider"],
        is_real_data=bool(row["is_real_data"]) if row["is_real_data"] is not None else False,
        last_price_date=row["last_price_date"],
        last_fetch_at=row["last_fetch_at"],
        score=row["score"],
        technical_score=row["technical_score"],
        news_score=row["news_score"] or 0,
        final_score=row["final_score"],
        news_sentiment_label=row["news_sentiment_label"],
        news_impact_level=row["news_impact_level"],
        signal=row["signal"],
        confidence=row["confidence"],
        technical_summary=row["technical_summary"],
        updated_at=row["updated_at"],
    )


def _asset_from_base_row(connection: sqlite3.Connection, row: sqlite3.Row) -> AssetOut:
    latest_price, daily_change_pct = _latest_price_metrics(connection, row["id"])
    fx_rate_to_base, last_price_base = _base_price_metrics(connection, row["currency"], latest_price)
    price_metadata = _latest_price_metadata(connection, row["id"])
    signal_row = connection.execute(
        """
        SELECT score, technical_score, news_score, final_score, news_sentiment_label, news_impact_level,
            signal, confidence, technical_summary
        FROM signals
        WHERE asset_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (row["id"],),
    ).fetchone()

    return AssetOut(
        id=row["id"],
        symbol=row["symbol"],
        name=row["name"],
        asset_type=row["asset_type"],
        tax_category=row["tax_category"],
        exchange=row["exchange"],
        currency=row["currency"],
        sector=row["sector"],
        country=row["country"],
        risk_level=row["risk_level"],
        isin=row["isin"],
        last_price=latest_price,
        fx_rate_to_base=fx_rate_to_base,
        last_price_base=last_price_base,
        daily_change_pct=daily_change_pct,
        last_source=price_metadata["last_source"],
        provider=price_metadata["provider"],
        is_real_data=bool(price_metadata["is_real_data"]),
        last_price_date=price_metadata["last_price_date"],
        last_fetch_at=price_metadata["last_fetch_at"],
        score=signal_row["score"] if signal_row else None,
        technical_score=signal_row["technical_score"] if signal_row else None,
        news_score=signal_row["news_score"] if signal_row else 0,
        final_score=signal_row["final_score"] if signal_row else None,
        news_sentiment_label=signal_row["news_sentiment_label"] if signal_row else None,
        news_impact_level=signal_row["news_impact_level"] if signal_row else None,
        signal=signal_row["signal"] if signal_row else None,
        confidence=signal_row["confidence"] if signal_row else None,
        technical_summary=signal_row["technical_summary"] if signal_row else None,
        updated_at=row["updated_at"],
    )


def list_assets(connection: sqlite3.Connection) -> list[AssetOut]:
    rows = connection.execute(
        """
        SELECT
            a.id,
            a.symbol,
            a.name,
            a.asset_type,
            a.tax_category,
            a.exchange,
            a.currency,
            a.sector,
            a.country,
            a.risk_level,
            a.isin,
            a.updated_at,
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
            COALESCE(sig.final_score, sig.score) AS score,
            COALESCE(sig.technical_score, sig.score) AS technical_score,
            COALESCE(sig.news_score, 0) AS news_score,
            COALESCE(sig.final_score, sig.score) AS final_score,
            sig.news_sentiment_label,
            sig.news_impact_level,
            sig.signal,
            sig.confidence,
            sig.technical_summary
        FROM assets a
        LEFT JOIN price_history latest
            ON latest.id = (
                SELECT ph.id
                FROM price_history ph
                WHERE ph.asset_id = a.id
                ORDER BY ph.date DESC
                LIMIT 1
            )
        LEFT JOIN price_history previous
            ON previous.id = (
                SELECT ph.id
                FROM price_history ph
                WHERE ph.asset_id = a.id
                ORDER BY ph.date DESC
                LIMIT 1 OFFSET 1
            )
        LEFT JOIN signals sig
            ON sig.id = (
                SELECT s.id
                FROM signals s
                WHERE s.asset_id = a.id
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT 1
            )
        ORDER BY a.asset_type, a.symbol
        """
    ).fetchall()
    return [_asset_from_row(connection, row) for row in rows]


def get_asset_by_symbol(connection: sqlite3.Connection, symbol: str) -> AssetOut | None:
    row = InstrumentService.require_unique_active_asset(connection, symbol)
    if row is None:
        return None
    return _asset_from_base_row(connection, row)


def asset_symbol_match_count(connection: sqlite3.Connection, symbol: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM assets WHERE UPPER(symbol) = UPPER(?)",
        (symbol,),
    ).fetchone()
    return int(row["count"])


def asset_dependency_counts(connection: sqlite3.Connection, asset_id: int) -> dict[str, int]:
    row = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM price_history WHERE asset_id = ?) AS price_history,
            (SELECT COUNT(*) FROM portfolio_positions WHERE asset_id = ?) AS portfolio_positions,
            (SELECT COUNT(*) FROM simulated_orders WHERE asset_id = ?) AS simulated_orders,
            (SELECT COUNT(*) FROM signals WHERE asset_id = ?) AS signals,
            (
                SELECT COUNT(*)
                FROM news_items
                WHERE asset_id = ?
                    OR (
                        asset_id IS NULL
                        AND UPPER(symbol) = (SELECT UPPER(symbol) FROM assets WHERE id = ?)
                    )
            ) AS news_items
        """,
        (asset_id, asset_id, asset_id, asset_id, asset_id, asset_id),
    ).fetchone()
    return {
        "price_history": int(row["price_history"]),
        "portfolio_positions": int(row["portfolio_positions"]),
        "simulated_orders": int(row["simulated_orders"]),
        "signals": int(row["signals"]),
        "news_items": int(row["news_items"]),
    }


def delete_asset(
    connection: sqlite3.Connection,
    asset_id: int,
    *,
    symbol: str,
    purge: bool = False,
) -> bool:
    if purge:
        connection.execute("DELETE FROM price_history WHERE asset_id = ?", (asset_id,))
        connection.execute("DELETE FROM portfolio_positions WHERE asset_id = ?", (asset_id,))
        connection.execute("DELETE FROM simulated_orders WHERE asset_id = ?", (asset_id,))
        connection.execute("DELETE FROM signals WHERE asset_id = ?", (asset_id,))
        connection.execute(
            "DELETE FROM news_items WHERE asset_id = ? OR (asset_id IS NULL AND UPPER(symbol) = UPPER(?))",
            (asset_id, symbol),
        )

    cursor = connection.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    return cursor.rowcount > 0


def create_asset(connection: sqlite3.Connection, payload: AssetCreate) -> AssetOut:
    tax_category = payload.tax_category or ("crypto" if payload.asset_type == "crypto" else "standard")
    cursor = connection.execute(
        """
        INSERT INTO assets (
            symbol, name, asset_type, tax_category, exchange, currency, sector, country, risk_level, isin
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.symbol.upper(),
            payload.name,
            payload.asset_type,
            tax_category,
            payload.exchange,
            payload.currency.upper(),
            payload.sector,
            payload.country,
            payload.risk_level,
            payload.isin,
        ),
    )
    InstrumentService.backfill_active_assets(connection)
    row = connection.execute(
        """
        SELECT id, symbol, name, asset_type, tax_category, exchange, currency, sector, country,
            risk_level, isin, updated_at
        FROM assets
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return _asset_from_base_row(connection, row)


_ASSET_TYPE_BY_INSTRUMENT_TYPE = {
    "STOCK": "stock",
    "ETF": "etf",
    "BOND": "bond",
    "CRYPTO": "crypto",
    "MACRO": "macro",
    "RATE": "bond_proxy",
}
_ACTIVE_ASSET_COLUMNS = """
    SELECT id, symbol, name, asset_type, tax_category, exchange, currency, sector, country,
        risk_level, isin, updated_at
    FROM assets
"""


class ListingActivationError(ValueError):
    def __init__(self, reason_code: str, kind: Literal["not_found", "conflict"]) -> None:
        self.reason_code = reason_code
        self.kind = kind
        super().__init__(reason_code)


def activate_listing(connection: sqlite3.Connection, listing_id: int) -> tuple[AssetOut, bool]:
    """Attiva esplicitamente un listing RESOLVED nell'universo `assets` (nessuna rete).

    Restituisce `(asset, created)`: lo stesso listing gia attivo e idempotente. Il
    simbolo legacy non diventa mai ambiguo: un asset con lo stesso simbolo su un altro
    listing (o senza listing) blocca l'attivazione.
    """
    if connection.in_transaction:
        raise RuntimeError("L'attivazione richiede una connessione senza transazione aperta.")
    connection.execute("BEGIN IMMEDIATE")
    try:
        listing = connection.execute(
            "SELECT id FROM instrument_listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
        if listing is None:
            raise ListingActivationError("LISTING_NOT_FOUND", "not_found")
        row = connection.execute(
            f"{_ACTIVE_ASSET_COLUMNS} WHERE instrument_listing_id = ? ORDER BY id LIMIT 1",
            (listing_id,),
        ).fetchone()
        created = row is None
        if row is None:
            row = _insert_listing_asset(connection, listing_id)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return _asset_from_base_row(connection, row), created


def _insert_listing_asset(connection: sqlite3.Connection, listing_id: int) -> sqlite3.Row:
    resolved = InstrumentService.resolved_listing(connection, listing_id)
    if resolved is None or resolved["listing_status"] != "ACTIVE":
        raise ListingActivationError("LISTING_NOT_RESOLVED", "conflict")
    instrument_id = int(resolved["instrument_id"])
    if InstrumentService.has_ambiguous_identity(connection, instrument_id):
        raise ListingActivationError("AMBIGUOUS_IDENTITY", "conflict")
    verified_type = str(resolved["verified_instrument_type"])
    asset_type = _ASSET_TYPE_BY_INSTRUMENT_TYPE.get(verified_type)
    if asset_type is None:
        raise ListingActivationError("UNSUPPORTED_INSTRUMENT_TYPE", "conflict")
    symbol = str(resolved["ticker"]).strip().upper()
    if len(symbol) > 24:
        raise ListingActivationError("UNSUPPORTED_TICKER", "conflict")
    if connection.execute(
        "SELECT 1 FROM assets WHERE UPPER(symbol) = ? LIMIT 1",
        (symbol,),
    ).fetchone() is not None:
        raise ListingActivationError("LEGACY_SYMBOL_CONFLICT", "conflict")
    primary = InstrumentService.verified_primary_identifier(connection, instrument_id, verified_type)
    isin = primary["normalized_value"] if primary is not None and primary["scheme"] == "ISIN" else None
    cursor = connection.execute(
        """
        INSERT INTO assets (
            symbol, name, asset_type, tax_category, exchange, currency, risk_level, isin,
            instrument_listing_id
        )
        VALUES (?, ?, ?, ?, ?, ?, 'medium', ?, ?)
        """,
        (
            symbol,
            " ".join(str(resolved["canonical_name"]).split())[:160],
            asset_type,
            "crypto" if asset_type == "crypto" else "standard",
            resolved["mic"],
            str(resolved["currency"]).strip().upper(),
            isin,
            listing_id,
        ),
    )
    return connection.execute(
        f"{_ACTIVE_ASSET_COLUMNS} WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
