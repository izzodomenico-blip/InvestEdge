from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from backend.app.models.schemas import ValidatedSignalOut
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.assets_service import get_asset_by_symbol


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class SignalValidationService:
    def __init__(self) -> None:
        self.data_quality_service = DataQualityService()
        self.portfolio_engine = PortfolioEngine()

    def validate_signal(self, connection: sqlite3.Connection, symbol: str) -> ValidatedSignalOut:
        asset = get_asset_by_symbol(connection, symbol)
        if not asset:
            raise ValueError(f"Asset {symbol} not found")

        asset_id = asset.id
        original_signal = asset.signal or "HOLD"

        # 1. Data Quality Check
        quality = self.data_quality_service.check_asset_quality(connection, symbol)

        # 2. Portfolio Constraints
        portfolio = self.portfolio_engine.refresh_portfolio(connection, create_snapshot=False)
        position = next((p for p in portfolio.positions if p.symbol == symbol.upper()), None)
        current_weight = position.weight_percent if position else 0.0

        # 3. ML Confidence
        ml_conf = asset.ml_confidence

        # 4. News Sentiment
        news_row = connection.execute(
            """
            SELECT sentiment_label, impact_level 
            FROM news_items 
            WHERE asset_id = ? 
            ORDER BY COALESCE(published_at, created_at) DESC, id DESC 
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        news_sent = news_row["sentiment_label"] if news_row else None
        news_impact = news_row["impact_level"] if news_row else "LOW"

        validated_signal = original_signal
        reason = "Signal maintains original technical assessment."
        action = "NO_ACTION"

        # Logic rules
        if quality.score < 50:
            validated_signal = "HOLD"
            reason = f"Data quality too low ({quality.score:.1f}). Exclusion required."
            action = "EXCLUDE"
        elif original_signal in ["BUY", "STRONG_BUY"]:
            if current_weight > 20.0:
                validated_signal = "HOLD"
                reason = f"Technical BUY but portfolio weight too high ({current_weight:.1f}%). Limit risk."
                action = "HOLD"
            elif ml_conf == "LOW":
                validated_signal = "HOLD"
                reason = "Technical BUY but ML confidence is LOW. Waiting for confirmation."
                action = "WATCH"
            elif news_sent == "NEGATIVE" and news_impact == "HIGH":
                validated_signal = "HOLD"
                reason = "Technical BUY but high-impact negative news detected."
                action = "WATCH"
            else:
                action = "BUY"
        elif original_signal == "SELL" and current_weight > 5.0:
            action = "REDUCE"
            reason = "Technical SELL and asset has significant weight in portfolio."
        elif original_signal == "REDUCE" and current_weight > 0:
            action = "REDUCE"
            reason = "Technical REDUCE signal and asset is in portfolio."

        return ValidatedSignalOut(
            symbol=symbol.upper(),
            asset_id=asset_id,
            original_signal=original_signal,
            validated_signal=validated_signal,
            reason=reason,
            data_quality_score=quality.score,
            ml_confidence=ml_conf,
            news_sentiment=news_sent,
            portfolio_weight=current_weight,
            action_suggested=action,
            timestamp=_now(),
        )

    def validate_all_signals(self, connection: sqlite3.Connection) -> list[ValidatedSignalOut]:
        assets = connection.execute(
            "SELECT DISTINCT symbol FROM signals"
        ).fetchall()
        return [self.validate_signal(connection, row["symbol"]) for row in assets]
