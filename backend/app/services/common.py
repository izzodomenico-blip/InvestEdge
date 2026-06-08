from __future__ import annotations

import math
from datetime import UTC, datetime

# --- Soglie di scoring: unica fonte di verita condivisa tra scoring/news/backtest ---
SCORE_STRONG_BUY = 80.0
SCORE_BUY = 70.0
SCORE_HOLD = 55.0
SCORE_REDUCE = 40.0


def now_utc() -> str:
    """Timestamp UTC senza tzinfo, precisione al secondo."""
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def now_local() -> str:
    """Timestamp ora locale, precisione al secondo."""
    return datetime.now().isoformat(timespec="seconds")


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Vincola value nell'intervallo [minimum, maximum]."""
    return max(minimum, min(maximum, value))


def round_safe(value: float | int | None, digits: int = 6) -> float:
    """Arrotonda gestendo None e valori non finiti come 0.0."""
    if value is None:
        return 0.0
    number = float(value)
    if not math.isfinite(number):
        return 0.0
    return round(number, digits)


def signal_from_score(score: float) -> str:
    """Mappa uno score 0-100 sul segnale corrispondente."""
    if score >= SCORE_STRONG_BUY:
        return "STRONG_BUY"
    if score >= SCORE_BUY:
        return "BUY"
    if score >= SCORE_HOLD:
        return "HOLD"
    if score >= SCORE_REDUCE:
        return "REDUCE"
    return "SELL"
