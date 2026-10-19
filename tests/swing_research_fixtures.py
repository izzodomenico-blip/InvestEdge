"""Synthetic metadata only; no market observations, secrets or provider IDs."""

from backend.app.swing_research.contracts import (
    INPUT_KINDS,
    DataContext,
    InputRef,
    ResearchManifest,
    ResourceLimits,
    canonical_hash,
)


def manifest(**changes):
    values = {
        "context": DataContext("SYNTHETIC", "SYNTHETIC", "SYNTHETIC"),
        "inputs": tuple(InputRef(kind, canonical_hash({"fixture": kind})) for kind in INPUT_KINDS),
        "software_hash": "a" * 64,
        "resources": ResourceLimits(max_disk_bytes=8_388_608),
    }
    return ResearchManifest(**(values | changes))


def request(name):
    return canonical_hash({"synthetic_request": name})


def registry(tmp_path):
    from backend.app.swing_research.registry import Registry

    inputs = tmp_path / "input"
    inputs.mkdir(exist_ok=True)
    return Registry(input_root=inputs, output_root=tmp_path / "registry")


def utc_ns(value):
    from datetime import datetime

    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    delta = moment - datetime.fromisoformat("1970-01-01T00:00:00+00:00")
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def data_record(kind="DAILY", key="L000", session="2020-01-02", **changes):
    from backend.app.swing_research.contracts import DataRecord

    event = utc_ns(session + "T21:00:00Z")
    values = {
        "kind": kind,
        "key": key,
        "session": session,
        "event_ns": event,
        "available_ns": event,
        "acquired_ns": utc_ns("2026-10-01T00:00:00Z"),
        "version": 1,
        "availability": "MODELED",
        "data": {
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10",
            "volume": "2000000",
            "currency": "USD",
            "basis": "RAW",
            "status": "TRADED",
        },
    }
    return DataRecord.from_dict(values | changes)


def local_packet(tmp_path, records, **changes):
    import hashlib

    from backend.app.swing_research.contracts import DatasetManifest, OpaqueHoldout, Partition, canonical_json

    root = tmp_path / "input"
    root.mkdir(exist_ok=True)
    grouped = {}
    for record in records:
        grouped.setdefault(record.kind, []).append(record)
    parts = []
    for kind, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row.grain)
        raw = b"".join((canonical_json(row.to_dict()) + "\n").encode("utf-8") for row in rows)
        name = kind.lower() + ".ndjson"
        (root / name).write_bytes(raw)
        parts.append(
            Partition(
                kind, name, hashlib.sha256(raw).hexdigest(), len(rows), len(raw), rows[0].session, rows[-1].session
            )
        )
    values = {
        "context": DataContext("SYNTHETIC", "SYNTHETIC", "SYNTHETIC"),
        "source_id": "SYNTHETIC_FIXTURE",
        "rights": "SYNTHETIC",
        "rights_hash": "a" * 64,
        "currency": "USD",
        "calendar_hash": "c" * 64,
        "universe_basis": "ASOF",
        "price_basis": "RAW",
        "availability": "MODELED",
        "acquired_ns": utc_ns("2026-10-01T00:00:00Z"),
        "partitions": tuple(parts),
        "gaps": (),
        "expected_daily_rows": len({(row.session, row.key) for row in grouped.get("DAILY", [])}),
        "coverage_hash": "b" * 64,
        "holdout": OpaqueHoldout("d" * 64, 100, 50000, "2024-01-02", "2026-09-30"),
    }
    packet = DatasetManifest(**(values | changes))
    return root, packet


def synthetic_calendar():
    from datetime import date, timedelta

    from backend.app.swing_research.calendar import Session, TradingCalendar

    on = date(2020, 2, 3)
    previous = []
    day = on - timedelta(days=1)
    while len(previous) < 252:
        if day.weekday() < 5:
            previous.append(day)
        day -= timedelta(days=1)
    days = sorted(previous) + [on]
    sessions = tuple(
        Session(
            d.isoformat(),
            utc_ns(d.isoformat() + "T14:30:00Z"),
            utc_ns(d.isoformat() + "T21:00:00Z"),
            utc_ns("2018-01-01T00:00:00Z"),
        )
        for d in days
    )
    return TradingCalendar(sessions, tuple(d.isoformat() for d in days), "c" * 64), on.isoformat()


def listing_record(key="L000", **changes):
    data = {
        "issuer_id": "I" + key,
        "class_id": "C" + key,
        "listing_id": key,
        "ticker": "T" + key,
        "valid_from": "2010-01-01",
        "valid_to": None,
        "listed_session": "2010-01-01",
        "delisted_session": None,
        "domicile": "USA",
        "security_type": "COMMON_STOCK",
        "primary": True,
        "venue": "NASDAQ",
        "currency": "USD",
        "source_hash": "e" * 64,
    }
    return data_record(
        "IDENTITY",
        key,
        data["valid_from"],
        event_ns=utc_ns(data["valid_from"] + "T00:00:00Z"),
        available_ns=utc_ns("2019-01-02T00:00:00Z"),
        data=data | changes,
    )


def daily_history(calendar, names=100, **overrides):
    for session in calendar.sessions[:-1]:
        for number in range(names):
            key = f"L{number:03d}"
            values = {
                "open": "10",
                "high": "11",
                "low": "9",
                "close": "10",
                "volume": "2000000",
                "currency": "USD",
                "basis": "RAW",
                "status": "TRADED",
            }
            values.update(overrides.get(key, {}))
            yield data_record(
                key=key, session=session.day, event_ns=session.close_ns, available_ns=session.close_ns, data=values
            )


def action_record(kind="SPLIT", **changes):
    data = {"action": kind, "listing_id": "L000", "ex_session": "2020-01-03", "source_hash": "f" * 64}
    if kind == "SPLIT":
        data["ratio"] = "2"
    elif kind == "DIVIDEND":
        data.update(
            {
                "pay_session": "2020-01-10",
                "cash_per_share": "1",
                "currency": "USD",
                "withholding_rate": "0.15",
                "cost_per_share": "0",
            }
        )
    elif kind in {"DELISTING", "MERGER", "SPINOFF"}:
        data.update({"cash_per_share": None, "currency": "USD", "new_listing_id": None, "share_ratio": None})
    elif kind == "RENAME":
        data.update({"old_ticker": "OLD", "new_ticker": "NEW"})
    return data_record(
        "ACTION",
        "ACTION1",
        "2020-01-03",
        event_ns=utc_ns("2020-01-03T14:30:00Z"),
        available_ns=utc_ns("2020-01-02T14:00:00Z"),
        data=data | changes,
    )

LEGACY_POLICY_HASH = "f7a17fb800577f7bb32b25d4e8384e17acdeb6fb4bbedcb36754b617ae8ee57a"
LEGACY_EXPERIMENT_HASH = "f2ca727c96449b2a6ae395bad89cf220c60028049537d9856a167316be9b4be8"


def legacy_manifest():
    """Reconstruct the synthetic Task1 policy, preserving its published fingerprint."""
    value = manifest().to_dict()
    policy = value["policy"]
    policy["version"] = "swing-policy-v1"
    policy["universe"] = {
        key: item
        for key, item in policy["universe"].items()
        if key not in {"security_type", "primary", "venues", "currency"}
    } | {"domicile": "USA"}
    old_hash = canonical_hash(policy)
    for config in value["grid"]:
        config["policy_hash"] = old_hash
    return value


def listing_record_without_domicile(key="L000", **changes):
    record = listing_record(key, **changes)
    data = record.data
    del data["domicile"]
    return type(record).from_dict(record.to_dict() | {"data": data})
