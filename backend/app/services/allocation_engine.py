from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any

TRADING_DAYS = 252
DEFAULT_TARGET_VOL = 0.15


@dataclass
class AllocationEngine:
    """Pianificatore di allocazione capitale per portafoglio simulato.

    Suggerisce pesi target e quantita per un insieme di asset. Non esegue ordini:
    l'output e un piano che l'utente puo applicare manualmente dal simulatore.
    """

    lookback_days: int = 120

    def plan(
        self,
        connection: sqlite3.Connection,
        *,
        symbols: list[str],
        method: str,
        total_capital: float,
        target_volatility: float | None = None,
        max_weight: float | None = None,
        lookback_days: int | None = None,
    ) -> dict[str, Any]:
        clean_symbols: list[str] = []
        for symbol in symbols:
            upper = symbol.strip().upper()
            if upper and upper not in clean_symbols:
                clean_symbols.append(upper)
        if not clean_symbols:
            raise ValueError("Seleziona almeno un asset.")
        if total_capital <= 0:
            raise ValueError("Il capitale totale deve essere positivo.")

        lookback = lookback_days or self.lookback_days
        assets = self._load_assets(connection, clean_symbols, lookback)

        notes: list[str] = []
        weights = self._raw_weights(assets, method, notes)
        weights = self._apply_cap(weights, max_weight, notes)

        estimated_vol = self._portfolio_vol(assets, weights)
        invested_fraction = 1.0
        if method == "VOL_TARGET":
            target = target_volatility if target_volatility and target_volatility > 0 else DEFAULT_TARGET_VOL
            if estimated_vol > 0:
                invested_fraction = min(1.0, target / estimated_vol)
            notes.append(
                f"Volatility targeting: vol stimata {estimated_vol * 100:.1f}%, "
                f"target {target * 100:.1f}%, capitale investito {invested_fraction * 100:.0f}%."
            )

        invested_capital = total_capital * invested_fraction
        allocations: list[dict[str, Any]] = []
        for asset, weight in zip(assets, weights, strict=True):
            capital = invested_capital * weight
            price = asset["price"]
            quantity = math.floor(capital / price) if price and price > 0 else 0
            allocations.append(
                {
                    "symbol": asset["symbol"],
                    "name": asset["name"],
                    "weight_percent": round(weight * invested_fraction * 100, 2),
                    "capital": round(capital, 2),
                    "price": round(price, 4) if price else None,
                    "suggested_quantity": quantity,
                    "volatility": round(asset["volatility"], 4),
                    "score": asset["score"],
                }
            )

        return {
            "method": method,
            "total_capital": round(total_capital, 2),
            "invested_capital": round(invested_capital, 2),
            "cash_buffer": round(total_capital - invested_capital, 2),
            "target_volatility": target_volatility if method == "VOL_TARGET" else None,
            "estimated_volatility": round(estimated_vol, 4),
            "allocations": allocations,
            "notes": notes,
        }

    # ------------------------------------------------------------------ helpers

    def _load_assets(
        self,
        connection: sqlite3.Connection,
        symbols: list[str],
        lookback: int,
    ) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        missing: list[str] = []
        for symbol in symbols:
            row = connection.execute(
                "SELECT id, symbol, name, currency, risk_level FROM assets WHERE UPPER(symbol) = UPPER(?) LIMIT 1",
                (symbol,),
            ).fetchone()
            if row is None:
                missing.append(symbol)
                continue
            closes = connection.execute(
                """
                SELECT close
                FROM price_history
                WHERE asset_id = ?
                ORDER BY date DESC, is_real_data DESC, id DESC
                LIMIT ?
                """,
                (row["id"], lookback),
            ).fetchall()
            series = [float(item["close"]) for item in reversed(closes) if item["close"] is not None]
            if len(series) < 2:
                missing.append(symbol)
                continue
            score_row = connection.execute(
                """
                SELECT COALESCE(final_score, score) AS score
                FROM signals
                WHERE asset_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (row["id"],),
            ).fetchone()
            score = float(score_row["score"]) if score_row and score_row["score"] is not None else None
            assets.append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "currency": row["currency"],
                    "price": series[-1],
                    "volatility": self._annualized_vol(series),
                    "score": score,
                }
            )
        if missing:
            raise ValueError(f"Storico insufficiente o asset non trovato: {', '.join(missing)}.")
        return assets

    def _annualized_vol(self, closes: list[float]) -> float:
        returns: list[float] = []
        for prev, curr in zip(closes, closes[1:], strict=False):
            if prev and prev > 0:
                returns.append(curr / prev - 1.0)
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        return math.sqrt(variance) * math.sqrt(TRADING_DAYS)

    def _raw_weights(self, assets: list[dict[str, Any]], method: str, notes: list[str]) -> list[float]:
        count = len(assets)
        equal = [1.0 / count] * count

        if method == "EQUAL_WEIGHT":
            return equal

        if method in {"RISK_PARITY", "VOL_TARGET"}:
            inverse = [1.0 / asset["volatility"] if asset["volatility"] > 1e-6 else 0.0 for asset in assets]
            total = sum(inverse)
            if total <= 0:
                notes.append("Volatilita non disponibile, fallback a equal weight.")
                return equal
            return [value / total for value in inverse]

        if method == "SCORE_WEIGHTED":
            raw = [max((asset["score"] or 0.0) - 50.0, 0.0) for asset in assets]
            total = sum(raw)
            if total <= 0:
                notes.append("Nessuno score sopra 50, fallback a equal weight.")
                return equal
            return [value / total for value in raw]

        raise ValueError(f"Metodo allocazione non valido: {method}.")

    def _apply_cap(self, weights: list[float], max_weight: float | None, notes: list[str]) -> list[float]:
        if not max_weight or max_weight <= 0 or max_weight >= 1:
            return weights
        if max_weight * len(weights) < 1.0 - 1e-9:
            notes.append("Peso massimo troppo basso per coprire tutti gli asset, ignorato.")
            return weights

        capped = list(weights)
        for _ in range(len(capped) * 2):
            over = [index for index, value in enumerate(capped) if value > max_weight + 1e-9]
            if not over:
                break
            excess = sum(capped[index] - max_weight for index in over)
            for index in over:
                capped[index] = max_weight
            receivers = [index for index, value in enumerate(capped) if value < max_weight - 1e-9]
            room = sum(max_weight - capped[index] for index in receivers)
            if not receivers or room <= 0:
                break
            for index in receivers:
                capped[index] += excess * (max_weight - capped[index]) / room

        total = sum(capped)
        if total > 0:
            capped = [value / total for value in capped]
        notes.append(f"Peso massimo per asset limitato al {max_weight * 100:.0f}%.")
        return capped

    def _portfolio_vol(self, assets: list[dict[str, Any]], weights: list[float]) -> float:
        # Stima conservativa: media pesata delle volatilita (assume correlazione 1).
        return sum(weight * asset["volatility"] for asset, weight in zip(assets, weights, strict=True))
