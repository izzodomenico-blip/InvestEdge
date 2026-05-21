from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from backend.app.models.schemas import OperationalRankingOut, PortfolioActionOut
from backend.app.services.signal_validation_service import SignalValidationService


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class OperationalRankingService:
    def __init__(self) -> None:
        self.validation_service = SignalValidationService()

    def get_operational_ranking(self, connection: sqlite3.Connection) -> OperationalRankingOut:
        validated_signals = self.validation_service.validate_all_signals(connection)

        buy = [s for s in validated_signals if s.action_suggested == "BUY"]
        watch = [s for s in validated_signals if s.action_suggested == "WATCH"]
        reduce = [s for s in validated_signals if s.action_suggested == "REDUCE"]
        excluded = [s for s in validated_signals if s.action_suggested == "EXCLUDE"]

        # Sort candidates
        buy.sort(key=lambda x: x.data_quality_score, reverse=True)
        watch.sort(key=lambda x: x.data_quality_score, reverse=True)

        return OperationalRankingOut(
            buy_candidates=buy,
            watch_candidates=watch,
            reduce_candidates=reduce,
            excluded_candidates=excluded,
            updated_at=_now(),
        )

    def get_portfolio_actions(self, connection: sqlite3.Connection) -> list[PortfolioActionOut]:
        validated_signals = self.validation_service.validate_all_signals(connection)
        actions: list[PortfolioActionOut] = []

        for s in validated_signals:
            if s.action_suggested in ["BUY", "REDUCE", "EXCLUDE"]:
                target_weight = 0.0
                if s.action_suggested == "BUY":
                    target_weight = 10.0  # Example target weight
                elif s.action_suggested == "REDUCE":
                    target_weight = s.portfolio_weight * 0.5
                elif s.action_suggested == "EXCLUDE":
                    target_weight = 0.0

                actions.append(
                    PortfolioActionOut(
                        symbol=s.symbol,
                        action=s.action_suggested,
                        reason=s.reason,
                        current_weight=s.portfolio_weight,
                        target_weight=target_weight,
                        timestamp=_now(),
                    )
                )

        return actions
