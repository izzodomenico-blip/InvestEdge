from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from backend.app.models.schemas import ValidatedSignalOut
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.assets_service import get_asset_by_symbol
from backend.app.services.user_settings_service import UserSettingsService


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class SignalValidationService:
    def __init__(self) -> None:
        self.data_quality_service = DataQualityService()
        self.portfolio_engine = PortfolioEngine()
        self.settings_service = UserSettingsService()

    def validate_signal(self, connection: sqlite3.Connection, symbol: str, portfolio_id: int | None = None) -> ValidatedSignalOut:
        from backend.app.services.multi_portfolio_service import MultiPortfolioService
        mps = MultiPortfolioService()
        
        if portfolio_id is None:
            portfolio_id = mps.get_active_portfolio(connection).id

        asset = get_asset_by_symbol(connection, symbol)
        if not asset:
            raise ValueError(f"Asset {symbol} not found")
            
        profile = self.settings_service.get_active_risk_profile(connection)

        asset_id = asset.id
        original_signal = asset.signal or "HOLD"

        # 1. Data Quality Check
        quality = self.data_quality_service.check_asset_quality(connection, symbol)

        # 2. Portfolio Constraints
        portfolio = self.portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=False)
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
        reason = f"Signal maintains original technical assessment (Profile: {profile.profile_name})."
        action = "NO_ACTION"

        # Logic rules from Profile
        if quality.score < profile.min_data_quality_score:
            validated_signal = "HOLD"
            reason = f"Data quality too low ({quality.score:.1f}). Profile minimum is {profile.min_data_quality_score}."
            action = "EXCLUDE"
        elif original_signal in ["BUY", "STRONG_BUY"]:
            # Check constraints from Profile
            if current_weight > profile.max_single_asset_weight:
                validated_signal = "HOLD"
                reason = f"Technical BUY but portfolio weight too high ({current_weight:.1f}%). Profile max is {profile.max_single_asset_weight}%."
                action = "HOLD"
            elif profile.allow_ml_influence and ml_conf == "LOW" and profile.min_operational_confidence == "MEDIUM":
                validated_signal = "HOLD"
                reason = "Technical BUY but ML confidence is LOW. Profile requires higher confidence."
                action = "WATCH"
            elif profile.allow_news_influence and news_sent == "NEGATIVE" and news_impact == "HIGH":
                validated_signal = "HOLD"
                reason = "Technical BUY but high-impact negative news detected. News influence active in Profile."
                action = "WATCH"
            elif profile.require_real_data_for_buy and not asset.is_real_data:
                 validated_signal = "HOLD"
                 reason = "Technical BUY but real data required by Profile. Asset has only seed/demo data."
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

    def validate_all_signals(self, connection: sqlite3.Connection, portfolio_id: int | None = None) -> list[ValidatedSignalOut]:
        assets = connection.execute(
            "SELECT DISTINCT symbol FROM signals"
        ).fetchall()
        return [self.validate_signal(connection, row["symbol"], portfolio_id=portfolio_id) for row in assets]
