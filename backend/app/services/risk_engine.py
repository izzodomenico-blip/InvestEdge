from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RiskEngine:
    """Portfolio-level risk checks for simulated trading only."""

    crypto_max_weight: float = 15.0
    min_cash_weight: float = 2.0
    max_cash_weight: float = 35.0
    top_three_max_weight: float = 70.0
    weak_signal_max_weight: float = 12.0

    def evaluate_portfolio(
        self,
        *,
        cash: float,
        total_value: float,
        positions: list[dict[str, Any]],
        allocation_by_asset_type: dict[str, float],
        settings: dict[str, float],
    ) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        if total_value <= 0:
            return warnings

        max_single_asset_weight = settings.get("max_single_asset_weight", 25.0)
        max_asset_class_weight = settings.get("max_asset_class_weight", 50.0)
        crypto_max_weight = settings.get("crypto_max_weight", self.crypto_max_weight)
        min_cash_weight = settings.get("min_cash_weight", self.min_cash_weight)
        max_cash_weight = settings.get("max_cash_weight", self.max_cash_weight)

        for position in positions:
            weight = float(position.get("weight_percent", 0))
            symbol = str(position.get("symbol", ""))
            if weight > max_single_asset_weight:
                warnings.append(
                    {
                        "level": "WARNING",
                        "code": "SINGLE_ASSET_CONCENTRATION",
                        "symbol": symbol,
                        "message": f"{symbol} pesa {weight:.1f}%, oltre il limite {max_single_asset_weight:.1f}%.",
                    }
                )

            signal = position.get("technical_signal")
            if signal in {"SELL", "REDUCE"} and weight > self.weak_signal_max_weight:
                warnings.append(
                    {
                        "level": "WARNING",
                        "code": "WEAK_SIGNAL_OVERWEIGHT",
                        "symbol": symbol,
                        "message": f"{symbol} ha segnale {signal} e pesa {weight:.1f}%.",
                    }
                )

        for asset_type, weight in allocation_by_asset_type.items():
            if weight > max_asset_class_weight:
                warnings.append(
                    {
                        "level": "WARNING",
                        "code": "ASSET_CLASS_CONCENTRATION",
                        "symbol": None,
                        "message": f"La classe {asset_type} pesa {weight:.1f}%, oltre il limite {max_asset_class_weight:.1f}%.",
                    }
                )

        crypto_weight = allocation_by_asset_type.get("crypto", 0.0)
        if crypto_weight > crypto_max_weight:
            warnings.append(
                {
                    "level": "WARNING",
                    "code": "CRYPTO_OVERWEIGHT",
                    "symbol": None,
                    "message": f"Cripto al {crypto_weight:.1f}%, oltre la soglia {crypto_max_weight:.1f}%.",
                }
            )

        cash_weight = (cash / total_value) * 100
        if cash_weight > max_cash_weight:
            warnings.append(
                {
                    "level": "INFO",
                    "code": "HIGH_CASH",
                    "symbol": None,
                    "message": f"Liquidita al {cash_weight:.1f}%, possibile capitale non investito.",
                }
            )
        if cash_weight < min_cash_weight:
            warnings.append(
                {
                    "level": "WARNING",
                    "code": "LOW_CASH",
                    "symbol": None,
                    "message": f"Liquidita al {cash_weight:.1f}%, sotto la soglia operativa.",
                }
            )

        top_three_weight = sum(
            float(position.get("weight_percent", 0))
            for position in sorted(positions, key=lambda item: float(item.get("weight_percent", 0)), reverse=True)[:3]
        )
        if top_three_weight > self.top_three_max_weight:
            warnings.append(
                {
                    "level": "WARNING",
                    "code": "TOP_THREE_CONCENTRATION",
                    "symbol": None,
                    "message": f"I primi 3 asset pesano {top_three_weight:.1f}%, portafoglio concentrato.",
                }
            )

        return warnings

    def final_recommendation(
        self,
        *,
        technical_signal: str | None,
        technical_score: float | None,
        portfolio_weight: float,
        asset_type: str,
        risk_level: str,
        settings: dict[str, float],
        asset_class_weight: float,
    ) -> tuple[str, str]:
        max_single = settings.get("max_single_asset_weight", 25.0)
        max_class = settings.get("max_asset_class_weight", 50.0)
        crypto_max = settings.get("crypto_max_weight", self.crypto_max_weight)

        if portfolio_weight >= max_single:
            return "BLOCK_BUY_TOO_CONCENTRATED", f"Peso {portfolio_weight:.1f}% oltre il limite per singolo asset."

        if asset_class_weight >= max_class:
            return "BLOCK_BUY_TOO_CONCENTRATED", f"Classe {asset_type} gia al {asset_class_weight:.1f}%."

        if asset_type == "crypto" and asset_class_weight >= crypto_max:
            return "BLOCK_BUY_HIGH_RISK", f"Esposizione crypto gia al {asset_class_weight:.1f}%."

        if risk_level.lower() in {"high", "very_high"} and technical_signal not in {"STRONG_BUY", "BUY"}:
            return "BLOCK_BUY_HIGH_RISK", "Asset ad alto rischio senza segnale tecnico forte."

        if technical_signal == "SELL":
            return "SELL", "Segnale tecnico SELL."
        if technical_signal == "REDUCE":
            return "REDUCE", "Segnale tecnico REDUCE."
        if technical_signal in {"STRONG_BUY", "BUY"} and portfolio_weight < max_single * 0.8:
            return "BUY_ALLOWED", "Segnale tecnico positivo e peso ancora sotto i limiti."
        return "HOLD", "Segnale o peso suggeriscono mantenimento."
