from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.services.portfolio_engine import PortfolioEngine

portfolio_engine = PortfolioEngine()

# Shock predefiniti in percentuale per asset class. CUSTOM usa quelli passati nella richiesta.
SCENARIO_PRESETS: dict[str, dict[str, float]] = {
    "MARKET_CRASH": {"stock": -25, "etf": -22, "crypto": -45, "bond": -3, "bond_etf": -5},
    "TECH_SELLOFF": {"stock": -18, "etf": -12, "crypto": -25, "bond": 1, "bond_etf": 0},
    "CRYPTO_WINTER": {"stock": -3, "etf": -2, "crypto": -55, "bond": 0, "bond_etf": 0},
    "RATE_HIKE": {"stock": -8, "etf": -7, "crypto": -15, "bond": -12, "bond_etf": -10},
    "INFLATION_SHOCK": {"stock": -10, "etf": -9, "crypto": -20, "bond": -8, "bond_etf": -7},
    "MILD_CORRECTION": {"stock": -7, "etf": -6, "crypto": -12, "bond": -1, "bond_etf": -2},
}

SCENARIO_LABELS: dict[str, str] = {
    "MARKET_CRASH": "Crollo di mercato",
    "TECH_SELLOFF": "Sell-off tecnologico",
    "CRYPTO_WINTER": "Inverno cripto",
    "RATE_HIKE": "Rialzo dei tassi",
    "INFLATION_SHOCK": "Shock inflazione",
    "MILD_CORRECTION": "Correzione moderata",
    "CUSTOM": "Scenario personalizzato",
}


def _risk_level(percentage_loss: float) -> str:
    if percentage_loss <= -25:
        return "EXTREME"
    if percentage_loss <= -15:
        return "HIGH"
    if percentage_loss <= -5:
        return "MEDIUM"
    return "LOW"


def run_scenario(
    connection: sqlite3.Connection,
    *,
    scenario_type: str,
    class_shocks: dict[str, float] | None = None,
    symbol_shocks: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Stress test: applica shock di prezzo al portafoglio attuale e stima la perdita.

    Operazione di sola lettura: non modifica il portafoglio."""
    summary = portfolio_engine.refresh_portfolio(connection, create_snapshot=False)
    if not summary.positions:
        raise ValueError("Portafoglio vuoto: crea o importa un portafoglio prima di simulare uno scenario.")

    if scenario_type == "CUSTOM":
        shocks = {key.lower(): float(value) for key, value in (class_shocks or {}).items()}
    else:
        shocks = SCENARIO_PRESETS.get(scenario_type)
        if shocks is None:
            raise ValueError(f"Scenario non valido: {scenario_type}.")
    symbol_overrides = {key.upper(): float(value) for key, value in (symbol_shocks or {}).items()}

    base_value = summary.total_value
    base_cash = summary.cash

    asset_impacts: list[dict[str, Any]] = []
    class_map: dict[str, dict[str, float]] = {}
    total_loss = 0.0

    for position in summary.positions:
        asset_type = (position.asset_type or "stock").lower()
        current_value = float(position.current_value)
        shock_percent = symbol_overrides.get(position.symbol.upper(), shocks.get(asset_type, 0.0))
        impact = (shock_percent / 100.0) * current_value
        stressed = max(0.0, current_value + impact)
        total_loss += impact

        asset_impacts.append(
            {
                "symbol": position.symbol,
                "asset_type": asset_type,
                "current_value": round(current_value, 2),
                "shock_percent": round(shock_percent, 2),
                "stressed_value": round(stressed, 2),
                "absolute_impact": round(impact, 2),
                "loss_contribution_percent": 0.0,
            }
        )
        bucket = class_map.setdefault(asset_type, {"current": 0.0, "stressed": 0.0})
        bucket["current"] += current_value
        bucket["stressed"] += stressed

    stressed_value = sum(item["stressed_value"] for item in asset_impacts) + base_cash
    absolute_loss = round(stressed_value - base_value, 2)
    percentage_loss = round((absolute_loss / base_value) * 100.0, 2) if base_value > 0 else 0.0

    for item in asset_impacts:
        if total_loss < 0:
            item["loss_contribution_percent"] = round((item["absolute_impact"] / total_loss) * 100.0, 1)

    class_impacts = []
    for asset_class, values in sorted(class_map.items()):
        impact = values["stressed"] - values["current"]
        class_impacts.append(
            {
                "asset_class": asset_class,
                "current_value": round(values["current"], 2),
                "stressed_value": round(values["stressed"], 2),
                "absolute_impact": round(impact, 2),
                "shock_percent": round((impact / values["current"]) * 100.0, 2) if values["current"] > 0 else 0.0,
            }
        )

    asset_impacts.sort(key=lambda item: item["absolute_impact"])
    risk_level = _risk_level(percentage_loss)

    return {
        "scenario_type": scenario_type,
        "scenario_label": SCENARIO_LABELS.get(scenario_type, scenario_type),
        "current_value": round(base_value, 2),
        "stressed_value": round(stressed_value, 2),
        "cash": round(base_cash, 2),
        "absolute_loss": absolute_loss,
        "percentage_loss": percentage_loss,
        "risk_level": risk_level,
        "asset_impacts": asset_impacts,
        "class_impacts": class_impacts,
        "mitigation": _mitigation(percentage_loss, class_impacts, base_value, base_cash, risk_level),
    }


def _mitigation(
    percentage_loss: float,
    class_impacts: list[dict[str, Any]],
    base_value: float,
    base_cash: float,
    risk_level: str,
) -> list[str]:
    tips: list[str] = []
    if risk_level in {"HIGH", "EXTREME"}:
        tips.append(f"Perdita potenziale {percentage_loss:.1f}%: esposizione elevata, valuta di ridurre il rischio.")
    crypto = next((c for c in class_impacts if c["asset_class"] == "crypto"), None)
    if crypto and base_value > 0 and (crypto["current_value"] / base_value) > 0.15:
        tips.append("Le cripto pesano oltre il 15% e amplificano le perdite negli scenari avversi: valuta di alleggerirle.")
    cash_weight = (base_cash / base_value * 100.0) if base_value > 0 else 0.0
    if cash_weight < 5:
        tips.append("Liquidità sotto il 5%: poca riserva per comprare durante i ribassi.")
    worst = min(class_impacts, key=lambda c: c["absolute_impact"], default=None)
    if worst and worst["absolute_impact"] < 0:
        tips.append(f"La classe più colpita è '{worst['asset_class']}': considera maggiore diversificazione.")
    if not tips:
        tips.append("Portafoglio resiliente a questo scenario: nessuna azione urgente.")
    return tips
