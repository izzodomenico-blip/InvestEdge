from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.app.lab.features import compute_features
from backend.app.lab.score_v1 import explain, score_frame

_BAR_COLUMNS = ["date", "open", "high", "low", "close", "adjusted_close", "volume"]


@dataclass
class ScoringEngine:
    """Adattatore dello score unico `score-v1` (spec SP1 §4.2): feature `features-v1` e `explain` dell'ultima riga."""

    def score_prices(
        self,
        prices: pd.DataFrame,
        asset_id: int,
        symbol: str,
        risk_level: str,
    ) -> dict[str, object]:
        """Score dell'ultima barra di `prices`: un solo segmento, ordinato per data, una riga per data.

        Chiavi di sempre (indicatori con i nomi `features-v1`) piu `warmup_complete`.
        """
        features = compute_features(prices[_BAR_COLUMNS].reset_index(drop=True), "D")
        latest = features.tail(1)
        return {
            "asset_id": asset_id,
            "symbol": symbol,
            **explain(latest.iloc[0].to_dict(), risk_level),
            "warmup_complete": bool(score_frame(latest, risk_level)["warmup_complete"].iloc[0]),
        }

    def score_asset(self, asset_id: int) -> dict[str, object]:
        return {
            "asset_id": asset_id,
            "signal": "HOLD",
            "score": 50.0,
            "risk_level": "MEDIUM",
            "confidence": "LOW",
            "technical_summary": "Scoring engine requires price data.",
            "reasons": [{"type": "neutral", "message": "Dati prezzo non disponibili"}],
            "subscores": {},
            "indicators": {},
        }
