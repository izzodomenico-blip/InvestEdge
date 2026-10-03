from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from backend.app.lab.series import (
    EurConverter,
    SplitEvent,
    available_data_modes,
    load_series,
    preferred_data_mode,
    split_into_segments,
)
from backend.app.services.fx_service import FXService
from tests.lab_fixtures import insert_asset, insert_bars, insert_fx, synthetic_bars

MAX_GAP_SESSIONS = 5
SPLIT_TOLERANCE = 0.03
PRICE_COLUMNS = ["open", "high", "low", "close"]


def _segments(bars: pd.DataFrame, *, asset_type: str = "stock", basis: str = "UNKNOWN"):
    return split_into_segments(
        bars, asset_type=asset_type, basis=basis, max_gap_sessions=MAX_GAP_SESSIONS, split_tolerance=SPLIT_TOLERANCE
    )


def _without(bars: pd.DataFrame, start: int, count: int) -> pd.DataFrame:
    """Toglie `count` barre consecutive da `start`."""
    return bars.drop(index=range(start, start + count)).reset_index(drop=True)


def _with_split(bars: pd.DataFrame, index: int, factor: float) -> pd.DataFrame:
    """Evento societario alla barra `index`: prezzi da li in poi x `factor` (0.5 = split 2:1, 10 = 1:10).

    Open e close della barra restano vicini al close precedente prima del fattore.
    """
    result = bars.copy()
    previous_close = result.loc[index - 1, "close"]
    result.loc[index, PRICE_COLUMNS] = [
        previous_close * 0.998, previous_close * 1.008, previous_close * 0.995, previous_close * 1.005,
    ]
    result.loc[index:, PRICE_COLUMNS] = result.loc[index:, PRICE_COLUMNS] * factor
    result["adjusted_close"] = result["close"]
    return result


def _dates(series) -> list[str]:
    return [day for segment in series.segments for day in segment.bars["date"]]


def _freeze_fx_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    """Blocca `datetime.now` di FXService: "oggi" non dipende dal calendario reale."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return now.replace(tzinfo=None) if tz is None else now.astimezone(tz)

    monkeypatch.setattr("backend.app.services.fx_service.datetime", FrozenDatetime)


def test_real_series_never_contains_seed_rows(lab_connection) -> None:
    asset_id = insert_asset(lab_connection, "MIX")
    seed = synthetic_bars(520, 1, start="2018-01-01")
    real = synthetic_bars(200, 2, start="2019-06-03")
    insert_bars(lab_connection, asset_id, seed, real=False, provider=None)
    insert_bars(lab_connection, asset_id, real, real=True, provider="stooq")
    # Seconda riga reale nella stessa data (id maggiore): vince lei.
    revised = real.iloc[[10]].copy()
    revised[[*PRICE_COLUMNS, "adjusted_close"]] *= 1.01
    insert_bars(lab_connection, asset_id, revised, real=True, provider=None)

    real_series = load_series(lab_connection, asset_id, "REAL")
    demo_series = load_series(lab_connection, asset_id, "DEMO")

    assert real_series.data_mode == "REAL"
    assert _dates(real_series) == list(real["date"])
    assert real_series.bar_count() == 200
    loaded = pd.concat([segment.bars for segment in real_series.segments]).set_index("date")
    assert loaded.loc[real.loc[10, "date"], "close"] == revised["close"].iloc[0]
    assert loaded.loc[real.loc[11, "date"], "close"] == real.loc[11, "close"]
    assert demo_series.data_mode == "DEMO"
    assert _dates(demo_series) == list(seed["date"])
    assert available_data_modes(lab_connection, asset_id) == frozenset({"REAL", "DEMO"})
    assert preferred_data_mode(lab_connection, asset_id) == "REAL"

    seed_only = insert_asset(lab_connection, "SEED")
    insert_bars(lab_connection, seed_only, seed, real=False, provider=None)
    assert preferred_data_mode(lab_connection, seed_only) == "DEMO"
    assert load_series(lab_connection, seed_only, "REAL") is None


def test_business_day_gap_over_limit_opens_new_segment() -> None:
    bars = synthetic_bars(120, 3)

    segments, events, gap_starts = _segments(_without(bars, 50, 6))
    assert len(segments) == 2
    assert gap_starts == [bars.loc[56, "date"]]
    assert segments[1]["date"].iloc[0] == bars.loc[56, "date"]
    assert events == []

    segments, _, gap_starts = _segments(_without(bars, 50, 5))
    assert len(segments) == 1
    assert gap_starts == []


def test_crypto_gap_counts_calendar_days() -> None:
    bars = synthetic_bars(120, 4, start="2024-01-01", freq="D")
    holed = _without(bars, 50, 6)  # 2024-02-20 (martedi) .. 2024-02-25: 6 giorni, 4 lavorativi

    crypto, _, crypto_gaps = _segments(holed, asset_type="crypto", basis="NOT_APPLICABLE")
    assert len(crypto) == 2
    assert crypto_gaps == [bars.loc[56, "date"]]
    assert len(_segments(holed, asset_type="stock")[0]) == 1
    assert len(_segments(_without(bars, 50, 5), asset_type="crypto", basis="NOT_APPLICABLE")[0]) == 1


def test_unknown_basis_split_opens_segment(lab_connection) -> None:
    asset_id = insert_asset(lab_connection, "SPLT")
    bars = _with_split(synthetic_bars(120, 5), 60, 0.5)
    insert_bars(lab_connection, asset_id, bars, real=True, provider="stooq")

    series = load_series(lab_connection, asset_id, "REAL")

    assert series.adjustment_basis == "UNKNOWN"
    assert series.split_events == (SplitEvent(date=bars.loc[60, "date"], ratio=2.0, direction="FORWARD"),)
    assert [segment.segment_id for segment in series.segments] == [0, 1]
    assert [len(segment.bars) for segment in series.segments] == [60, 60]
    assert series.segments[1].bars["date"].iloc[0] == bars.loc[60, "date"]
    assert series.gap_starts == ()

    reverse = _with_split(synthetic_bars(120, 6), 40, 10.0)
    segments, events, _ = _segments(reverse)
    assert events == [SplitEvent(date=reverse.loc[40, "date"], ratio=10.0, direction="REVERSE")]
    assert len(segments) == 2


def test_intraday_crash_is_not_a_split() -> None:
    crashed = synthetic_bars(120, 7)
    crashed.loc[60:, PRICE_COLUMNS] = crashed.loc[60:, PRICE_COLUMNS] * 0.5
    previous_close = crashed.loc[59, "close"]
    # Open normale, close a meta: il rapporto dei close vale 2 ma l'open non lo conferma.
    crashed.loc[60, PRICE_COLUMNS] = [
        previous_close * 1.001, previous_close * 1.003, previous_close * 0.5, previous_close * 0.5,
    ]
    crashed["adjusted_close"] = crashed["close"]

    segments, events, _ = _segments(crashed)

    assert events == []
    assert len(segments) == 1


def test_coingecko_basis_skips_split_guard(lab_connection) -> None:
    asset_id = insert_asset(lab_connection, "COIN", asset_type="crypto", currency="USD")
    bars = _with_split(synthetic_bars(120, 8, start="2024-01-01", freq="D"), 60, 0.5)
    insert_bars(lab_connection, asset_id, bars, real=True, provider="coingecko")

    series = load_series(lab_connection, asset_id, "REAL")

    assert series.adjustment_basis == "NOT_APPLICABLE"
    assert series.split_events == ()
    assert len(series.segments) == 1
    assert len(_segments(bars, asset_type="crypto", basis="UNKNOWN")[1]) == 1


def test_unknown_basis_ignores_unverified_adjusted_close(lab_connection) -> None:
    asset_id = insert_asset(lab_connection, "ADJ")
    bars = synthetic_bars(30, 9)
    bars["adjusted_close"] = (bars["close"] * 0.9).astype(object)
    bars.loc[5, "adjusted_close"] = None
    insert_bars(lab_connection, asset_id, bars, real=True, provider="stooq")

    series = load_series(lab_connection, asset_id, "REAL")

    # Spec §5.1: con base UNKNOWN il fattore di rettifica vale 1.
    assert series.segments[0].bars["adjusted_close"].tolist() == bars["close"].tolist()


def test_eur_converter_uses_latest_rate_within_max_age(lab_connection) -> None:
    insert_fx(lab_connection, "USD", [("2024-01-04", 0.91), ("2024-01-05", 0.9)])  # giovedi, venerdi
    converter = EurConverter(lab_connection, max_age_days=7)

    assert converter.rate_on("USD", "2024-01-08") == 0.9  # lunedi: cambio di venerdi
    assert converter.rate_on("USD", "2024-01-04") == 0.91
    assert converter.rate_on("USD", "2024-01-03") is None
    assert converter.rate_on("EUR", "2024-01-03") == 1.0

    bars = pd.DataFrame(
        {
            "date": ["2024-01-05", "2024-01-08", "2024-01-12", "2024-01-13"],
            "open": [10.0, 11.0, 12.0, 13.0],
            "high": [12.0, 13.0, 14.0, 15.0],
            "low": [9.0, 10.0, 11.0, 12.0],
            "close": [10.0, 12.0, 13.0, 14.0],
            "adjusted_close": [5.0, 6.0, 6.5, 7.0],
            "volume": [1.0, 1.0, 1.0, 1.0],
        }
    )
    converted, excluded = converter.convert_bars(bars, "USD")

    assert excluded == 1  # 2024-01-13: ultimo cambio a 8 giorni
    assert list(converted["date"]) == list(bars["date"])
    assert converted["close_eur"].iloc[:3].tolist() == pytest.approx([5.0 * 0.9, 6.0 * 0.9, 6.5 * 0.9])
    assert converted.loc[1, "open_eur"] == pytest.approx(11.0 * 0.5 * 0.9)
    assert converted.loc[1, "high_eur"] == pytest.approx(13.0 * 0.5 * 0.9)
    assert converted.loc[1, "low_eur"] == pytest.approx(10.0 * 0.5 * 0.9)
    assert converted.loc[3, ["open_eur", "high_eur", "low_eur", "close_eur"]].isna().all()

    in_eur, excluded_eur = converter.convert_bars(bars, "EUR")
    assert excluded_eur == 0
    assert in_eur["close_eur"].tolist() == bars["adjusted_close"].tolist()


def test_eur_converter_matches_fx_service_direction(lab_connection, monkeypatch) -> None:
    _freeze_fx_clock(monkeypatch, datetime(2024, 1, 8, 12, tzinfo=UTC))
    today = "2024-01-08"
    insert_fx(lab_connection, "USD", [("2024-01-04", 0.91), ("2024-01-05", 0.9)])  # riga diretta USD -> EUR
    lab_connection.executemany(  # riga inversa EUR -> GBP
        """
        INSERT INTO fx_rates (from_currency, to_currency, rate, observed_at, provider, quality)
        VALUES ('EUR', 'GBP', ?, ?, 'ecb', 'reference')
        """,
        [(1.16, "2024-01-04"), (1.17, "2024-01-05")],
    )
    converter = EurConverter(lab_connection, max_age_days=7)

    for currency in ("USD", "GBP"):
        quote = FXService().get_rate(lab_connection, currency)
        assert quote.quality == "reference"
        assert converter.rate_on(currency, today) == quote.rate
    assert converter.rate_on("GBP", today) == 1.0 / 1.17


def test_eur_converter_ignores_seed_rates(lab_connection) -> None:
    insert_fx(lab_connection, "USD", [("2024-01-05", 0.9)])
    insert_fx(lab_connection, "USD", [("2024-01-08", 0.5)], provider="seed")
    insert_fx(lab_connection, "GBP", [("2024-01-08", 0.8)], provider="seed")
    converter = EurConverter(lab_connection, max_age_days=7)

    # Il cambio seed e' un dato demo: mai nella conversione (vincolo REAL/DEMO).
    assert converter.rate_on("USD", "2024-01-08") == 0.9
    assert converter.rate_on("GBP", "2024-01-08") is None
