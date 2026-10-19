"""Immutable, versioned preregistration. No application services or implicit clock."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import PurePosixPath

VERSION = "swing-research-v1"
MAX_DOCUMENT_BYTES = 1_048_576
MAX_INT = 2**63 - 1
INPUT_KINDS = (
    "DATASET",
    "CALENDAR",
    "UNIVERSE",
    "CORPORATE_ACTIONS",
    "FX",
    "BENCHMARK",
    "COST_PROFILE",
    "RISK_PROFILE",
    "HOLDOUT",
)


class SwingError(ValueError):
    """Only fixed public codes; never include payloads, paths or exception text."""

    def __init__(self, code: str):
        codes = {
            "INVALID_CONTRACT",
            "INVALID_JSON",
            "INVALID_NAMESPACE",
            "INVALID_PATH",
            "REGISTRY_INTEGRITY",
            "REGISTRY_BUSY",
            "REGISTRY_WRITE_FAILED",
            "INVALID_TRANSITION",
            "RESOURCE_LIMIT",
            "NOT_PREREGISTERED",
            "MANIFEST_MISMATCH",
            "DATASET_INTEGRITY",
            "DATASET_CHANGED",
            "INSUFFICIENT_DATA",
            "NON_IDONEO",
            "HOLDOUT_SEALED",
        }
        self.code = code if code in codes else "INVALID_CONTRACT"
        super().__init__(self.code)


def integer(value: object, *, positive: bool = False) -> None:
    if type(value) is not int or not int(positive) <= value <= MAX_INT:
        raise SwingError("INVALID_CONTRACT")


def digest(value: object) -> None:
    if type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None:
        raise SwingError("INVALID_CONTRACT")


def canonical_json(value: object) -> str:
    nodes = 0

    def convert(item, depth):
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 50_000:
            raise SwingError("INVALID_JSON")
        if item is None or type(item) is bool:
            return item
        if type(item) is int and -MAX_INT <= item <= MAX_INT:
            return item
        if type(item) is str and len(item) <= 65_536:
            item.encode("utf-8")
            return item
        if type(item) is Decimal:
            if not item.is_finite() or len(item.as_tuple().digits) > 1000 or abs(item.as_tuple().exponent) > 1000:
                raise SwingError("INVALID_JSON")
            text = format(item, "f")
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return "0" if item == 0 else text
        if type(item) in (list, tuple):
            return [convert(x, depth + 1) for x in item]
        if type(item) is dict and all(type(k) is str for k in item):
            return {convert(k, depth + 1): convert(v, depth + 1) for k, v in item.items()}
        raise SwingError("INVALID_JSON")

    try:
        result = json.dumps(
            convert(value, 0), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        if len(result.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise SwingError("INVALID_JSON")
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise SwingError("INVALID_JSON") from None


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_object(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SwingError("INVALID_JSON")
            result[key] = value
        return result

    try:
        if type(text) is not str or len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise SwingError("INVALID_JSON")
        value = json.loads(text, object_pairs_hook=pairs)
        if type(value) is not dict:
            raise SwingError("INVALID_JSON")
        canonical_json(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise SwingError("INVALID_JSON") from None


@dataclass(frozen=True)
class DataContext:
    data_mode: str
    provenance: str
    feed: str

    def __post_init__(self):
        if any(type(v) is not str for v in (self.data_mode, self.provenance, self.feed)):
            raise SwingError("INVALID_NAMESPACE")
        synthetic = self.data_mode == "SYNTHETIC"
        if (
            self.data_mode not in {"REAL", "SYNTHETIC", "RESEARCH_ONLY"}
            or synthetic
            and (self.provenance, self.feed) != ("SYNTHETIC", "SYNTHETIC")
            or not synthetic
            and (
                self.provenance not in {"CAPTURED", "HISTORICAL_CURRENT"} or self.feed not in {"SIP", "IEX", "UNKNOWN"}
            )
        ):
            raise SwingError("INVALID_NAMESPACE")


@dataclass(frozen=True)
class InputRef:
    kind: str
    sha256: str

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in INPUT_KINDS:
            raise SwingError("INVALID_CONTRACT")
        digest(self.sha256)


@dataclass(frozen=True)
class ResourceLimits:
    max_disk_bytes: int
    max_batch_rows: int = 10_000
    max_batch_bytes: int = 8_388_608
    max_rss_bytes: int = 2_147_483_648

    def __post_init__(self):
        for name, value in asdict(self).items():
            integer(value, positive=True)
            cap = {"max_batch_rows": 10_000, "max_batch_bytes": 8_388_608, "max_rss_bytes": 2_147_483_648}.get(
                name, MAX_INT
            )
            if value > cap:
                raise SwingError("INVALID_CONTRACT")


@dataclass(frozen=True)
class Policy:
    version: str = "swing-policy-v1"

    def __post_init__(self):
        if type(self.version) is not str or self.version != "swing-policy-v1":
            raise SwingError("INVALID_CONTRACT")

    def to_dict(self) -> dict:
        costs = {
            name: {"fee_best_eur": best, "fee_direct_eur": direct, "bps_side": bps, "delay_minutes": delay}
            for name, best, direct, bps, delay in [
                ("BASE", "1", "2", 10, 5),
                ("STRESS", "2", "4", 25, 10),
                ("SEVERE", "2", "4", 50, 15),
            ]
        }
        costs["SEVERE"]["fx_rule"] = "ZERO_ONLY_EUR_NO_CONVERSION_OTHERWISE_ATTESTED_OR_INSUFFICIENT"
        return {
            "version": self.version,
            "capital_eur": "10000",
            "research_n": 14,
            "holding_research": [5, 21],
            "holding_diagnostic": [1],
            "risk_per_position_eur": "100",
            "risk_per_position_fraction": "0.01",
            "aggregate_risk_eur": "1000",
            "aggregate_risk_fraction": "0.10",
            "max_positions": 10,
            "issuer_notional_fraction": "0.10",
            "min_buy_eur": "100",
            "whole_shares": True,
            "long_only": True,
            "leverage": False,
            "stop_atr": "2",
            "max_drawdown_eur": "2000",
            "fx_max_age_days": 7,
            "settlement": "USA_T_PLUS_1_COUNTERFACTUAL_2026",
            "universe": {
                "monthly_asof": True,
                "domicile": "USA",
                "price_min_usd": "5",
                "warmup": 252,
                "adv_sessions": 20,
                "adv_min_usd": "20000000",
                "max_names": 500,
                "min_names": 100,
                "daily_coverage": "0.99",
            },
            "features": {
                "atr": 14,
                "roc": 63,
                "sma": [20, 50, 200],
                "pullback_sessions": 5,
                "breakout_sessions": 20,
                "breakout_volume_ratio": "1.5",
                "entry_max_atr": "0.5",
            },
            "execution": {
                "decision_before_close_minutes": 40,
                "cutoff_before_close_minutes": 55,
                "stale_minutes": 5,
                "last_slot_before_close_minutes": 10,
                "sell_slot_minutes": 1,
                "buy_stop_slots": 2,
                "volume_fraction": "0.001",
                "buy_bar": "HIGH",
                "sell_bar": "LOW",
                "timer": "FIRST_FILL",
            },
            "sample": {
                "warmup": ["2016-01-04", "2016-12-30"],
                "initial_is": ["2017-01-03", "2019-12-31"],
                "oos": ["2020-01-02", "2023-12-29"],
                "holdout": ["2024-01-02", "2026-09-30"],
                "is_sessions": 504,
                "oos_sessions": 126,
                "purge_embargo_sessions": 21,
                "no_new_entry_last_sessions": 21,
            },
            "bootstrap": {"replicas": 10000, "seed": 20261015, "mean_blocks": [63, 21], "alpha_family": "0.05"},
            "gates": {
                "dsr_min": "0.95",
                "oos_sessions": 1000,
                "oos_roundtrips": 200,
                "oos_exposed_days": 252,
                "holdout_sessions": 630,
                "holdout_roundtrips": 100,
                "holdout_exposed_days": 126,
                "oos_positive_blocks": 6,
                "oos_blocks_min": 8,
                "holdout_positive_years": 2,
                "issuer_positive_pnl_max_fraction": "0.25",
                "stress_severe_required": True,
                "benchmark": "EW_ASOF_MONTHLY_PREVIOUS_EXPOSURE",
                "excess_mean_lb_positive": True,
                "usd_local_mean_lb_positive": True,
                "data_feasibility_before_strategies": True,
            },
            "diagnostics": {
                "n": 6,
                "after_research_verdict": True,
                "holdout_allowed": False,
                "selection_allowed": False,
                "dsr_variance_allowed": False,
            },
            "costs": costs,
        }

    @property
    def policy_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class TrialConfig:
    family: str
    holding_sessions: int
    execution_mode: str
    role: str
    kind: str

    def __post_init__(self):
        if (
            any(type(v) is not str for v in (self.family, self.execution_mode, self.role, self.kind))
            or type(self.holding_sessions) is not int
            or self.execution_mode not in {"BEST", "DIRECT"}
            or self.role not in {"RESEARCH", "DIAGNOSTIC_ONLY"}
        ):
            raise SwingError("INVALID_CONTRACT")
        candidate = (
            self.kind == "CANDIDATE"
            and self.family in {"MOM", "PULLBACK", "BREAKOUT"}
            and (
                (self.role == "RESEARCH" and self.holding_sessions in {5, 21})
                or (self.role == "DIAGNOSTIC_ONLY" and self.holding_sessions == 1)
            )
        )
        selector = (
            self.kind == "SELECTOR" and self.family == "WFO" and self.role == "RESEARCH" and self.holding_sessions == 0
        )
        if not (candidate or selector):
            raise SwingError("INVALID_CONTRACT")

    def to_dict(self) -> dict:
        return asdict(self) | {"policy_hash": Policy().policy_hash}

    @property
    def config_hash(self) -> str:
        return canonical_hash(self.to_dict())


def research_grid() -> tuple[TrialConfig, ...]:
    return tuple(
        TrialConfig(f, h, m, "RESEARCH", "CANDIDATE")
        for f in ("MOM", "PULLBACK", "BREAKOUT")
        for h in (5, 21)
        for m in ("BEST", "DIRECT")
    ) + tuple(TrialConfig("WFO", 0, m, "RESEARCH", "SELECTOR") for m in ("BEST", "DIRECT"))


def diagnostic_grid() -> tuple[TrialConfig, ...]:
    return tuple(
        TrialConfig(f, 1, m, "DIAGNOSTIC_ONLY", "CANDIDATE")
        for f in ("MOM", "PULLBACK", "BREAKOUT")
        for m in ("BEST", "DIRECT")
    )


def trial_grid() -> tuple[TrialConfig, ...]:
    return research_grid() + diagnostic_grid()


@dataclass(frozen=True)
class ResearchManifest:
    context: DataContext
    inputs: tuple[InputRef, ...]
    software_hash: str
    resources: ResourceLimits
    policy: Policy = field(default_factory=Policy)
    grid: tuple[TrialConfig, ...] = field(default_factory=trial_grid)

    def __post_init__(self):
        digest(self.software_hash)
        if (
            type(self.context) is not DataContext
            or type(self.resources) is not ResourceLimits
            or type(self.policy) is not Policy
            or type(self.inputs) is not tuple
            or any(type(x) is not InputRef for x in self.inputs)
            or tuple(x.kind for x in self.inputs) != INPUT_KINDS
            or type(self.grid) is not tuple
            or self.grid != trial_grid()
            or any(type(x) is not TrialConfig for x in self.grid)
        ):
            raise SwingError("INVALID_CONTRACT")

    @property
    def n_trials(self) -> int:
        return len(research_grid())

    def to_dict(self) -> dict:
        return {
            "version": VERSION,
            "context": asdict(self.context),
            "inputs": [asdict(x) for x in self.inputs],
            "software_hash": self.software_hash,
            "resources": asdict(self.resources),
            "policy": self.policy.to_dict(),
            "grid": [x.to_dict() for x in self.grid],
            "n_trials": self.n_trials,
        }

    @property
    def experiment_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict) -> ResearchManifest:
        try:
            if type(value) is not dict:
                raise SwingError("INVALID_CONTRACT")
            result = cls(
                context=DataContext(**value["context"]),
                inputs=tuple(InputRef(**x) for x in value["inputs"]),
                software_hash=value["software_hash"],
                resources=ResourceLimits(**value["resources"]),
            )
            if canonical_json(value) != canonical_json(result.to_dict()):
                raise SwingError("INVALID_CONTRACT")
            return result
        except (KeyError, TypeError, ValueError, AttributeError):
            raise SwingError("INVALID_CONTRACT") from None


# Additive local packet types. The published Task1 policy and hashes are unchanged.
DATA_KINDS = ("ACTION", "BENCHMARK", "DAILY", "FX", "GAP", "IDENTITY", "MINUTE", "SESSION")


def session_day(value: object) -> date:
    try:
        if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise SwingError("INVALID_CONTRACT") from None


def identifier(value: object) -> None:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None:
        raise SwingError("INVALID_CONTRACT")


def decimal_value(value: object, *, positive=False, nonnegative=False) -> Decimal:
    if type(value) is not str or len(value) > 128 or re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value) is None:
        raise SwingError("INVALID_CONTRACT")
    result = Decimal(value)
    if positive and result <= 0 or nonnegative and result < 0:
        raise SwingError("INVALID_CONTRACT")
    return result


def payload_fields(data: dict, expected: set[str]) -> None:
    if type(data) is not dict or set(data) != expected:
        raise SwingError("INVALID_CONTRACT")


@dataclass(frozen=True)
class DataRecord:
    """Effective session/grain and monotonic source revision, with explicit availability.

    For CAPTURED records acquired_ns is first receipt; HISTORICAL_CURRENT exports
    cannot use the modeled past availability to claim capture or STRICT_PIT.
    """

    kind: str
    key: str
    session: str
    event_ns: int
    available_ns: int
    acquired_ns: int
    version: int
    availability: str
    data_json: str

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in DATA_KINDS:
            raise SwingError("INVALID_CONTRACT")
        identifier(self.key)
        session_day(self.session)
        for value in (self.event_ns, self.available_ns, self.acquired_ns):
            integer(value)
        integer(self.version, positive=True)
        if self.availability not in ("PROVEN", "MODELED") or type(self.availability) is not str:
            raise SwingError("INVALID_CONTRACT")
        if canonical_json(parse_object(self.data_json)) != self.data_json:
            raise SwingError("INVALID_CONTRACT")

    @property
    def data(self) -> dict:
        return parse_object(self.data_json)

    @property
    def grain(self) -> tuple:
        return (*self.logical_key, self.version)

    @property
    def logical_key(self) -> tuple:
        return self.session, self.key, self.event_ns if self.kind in ("MINUTE", "FX", "GAP") else 0

    def to_dict(self) -> dict:
        return {name: value for name, value in asdict(self).items() if name != "data_json"} | {"data": self.data}

    @property
    def record_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict) -> DataRecord:
        try:
            expected = {
                "kind",
                "key",
                "session",
                "event_ns",
                "available_ns",
                "acquired_ns",
                "version",
                "availability",
                "data",
            }
            payload_fields(value, expected)
            return cls(
                **{key: item for key, item in value.items() if key != "data"}, data_json=canonical_json(value["data"])
            )
        except (ValueError, TypeError, KeyError):
            raise SwingError("INVALID_CONTRACT") from None


@dataclass(frozen=True)
class Partition:
    kind: str
    path: str
    sha256: str
    rows: int
    bytes: int
    first_session: str
    last_session: str

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in DATA_KINDS or type(self.path) is not str:
            raise SwingError("INVALID_CONTRACT")
        path = PurePosixPath(self.path)
        forbidden = {"con", "prn", "aux", "nul"} | {f"{prefix}{i}" for prefix in ("com", "lpt") for i in range(1, 10)}
        if (
            path.is_absolute()
            or path.as_posix() != self.path
            or not self.path.endswith(".ndjson")
            or "\\" in self.path
            or any(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part) is None
                or part.rstrip(". ") != part
                or part.split(".")[0].casefold() in forbidden
                for part in path.parts
            )
            or any(part.casefold() in {".git", ".env", "investedge.db"} for part in path.parts)
        ):
            raise SwingError("INVALID_PATH")
        digest(self.sha256)
        integer(self.rows, positive=True)
        integer(self.bytes, positive=True)
        if session_day(self.first_session) > session_day(self.last_session):
            raise SwingError("INVALID_CONTRACT")


def supersedes(candidate: DataRecord, previous: DataRecord | None) -> bool:
    """Call only after availability filtering; a delayed old version never wins."""
    if previous is None:
        return True
    if candidate.version == previous.version and candidate.record_hash != previous.record_hash:
        raise SwingError("DATASET_INTEGRITY")
    return candidate.version > previous.version


@dataclass(frozen=True)
class OpaqueHoldout:
    sha256: str
    rows: int
    bytes: int
    first_session: str
    last_session: str

    def __post_init__(self):
        digest(self.sha256)
        integer(self.rows, positive=True)
        integer(self.bytes, positive=True)
        if (self.first_session, self.last_session) != ("2024-01-02", "2026-09-30"):
            raise SwingError("INVALID_CONTRACT")


@dataclass(frozen=True)
class DataGap:
    kind: str
    key: str
    first_session: str
    last_session: str
    state: str

    def __post_init__(self):
        identifier(self.key)
        if self.kind not in DATA_KINDS or self.state not in ("MISSING", "NO_TRADES", "HALT"):
            raise SwingError("INVALID_CONTRACT")
        if session_day(self.first_session) > session_day(self.last_session):
            raise SwingError("INVALID_CONTRACT")


@dataclass(frozen=True)
class DatasetManifest:
    context: DataContext
    source_id: str
    rights: str
    rights_hash: str | None
    currency: str
    calendar_hash: str
    universe_basis: str
    price_basis: str
    availability: str
    acquired_ns: int
    partitions: tuple[Partition, ...]
    gaps: tuple[DataGap, ...]
    expected_daily_rows: int
    coverage_hash: str | None
    holdout: OpaqueHoldout

    def __post_init__(self):
        if type(self.context) is not DataContext or type(self.holdout) is not OpaqueHoldout:
            raise SwingError("INVALID_CONTRACT")
        identifier(self.source_id)
        digest(self.calendar_hash)
        for value in (self.rights_hash, self.coverage_hash):
            if value is not None:
                digest(value)
        integer(self.acquired_ns)
        integer(self.expected_daily_rows)
        if (
            self.rights not in ("ALLOWED", "UNKNOWN", "INCOMPATIBLE", "SYNTHETIC")
            or self.currency != "USD"
            or self.universe_basis not in ("ASOF", "CURRENT", "SURVIVORS", "UNKNOWN")
            or self.price_basis not in ("RAW", "SPLIT_ADJUSTED", "TOTAL_RETURN", "UNKNOWN")
            or self.availability not in ("PROVEN", "MODELED")
            or type(self.partitions) is not tuple
            or not self.partitions
            or any(type(p) is not Partition for p in self.partitions)
            or type(self.gaps) is not tuple
            or any(type(g) is not DataGap for g in self.gaps)
        ):
            raise SwingError("INVALID_CONTRACT")
        if self.rights == "SYNTHETIC" and self.context.data_mode != "SYNTHETIC":
            raise SwingError("INVALID_NAMESPACE")
        if len({part.path for part in self.partitions}) != len(self.partitions) or self.partitions != tuple(
            sorted(self.partitions, key=lambda p: (p.kind, p.first_session, p.path))
        ):
            raise SwingError("INVALID_CONTRACT")
        if any(part.kind != "SESSION" and part.last_session >= self.holdout.first_session for part in self.partitions):
            raise SwingError("HOLDOUT_SEALED")
        if any(gap.kind != "SESSION" and gap.last_session >= self.holdout.first_session for gap in self.gaps):
            raise SwingError("HOLDOUT_SEALED")
        canonical_json(self.to_dict())

    def to_dict(self) -> dict:
        return {"version": "swing-dataset-v1"} | asdict(self)

    @property
    def dataset_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict) -> DatasetManifest:
        try:
            result = cls(
                **{
                    key: item
                    for key, item in value.items()
                    if key not in {"version", "context", "partitions", "gaps", "holdout"}
                },
                context=DataContext(**value["context"]),
                partitions=tuple(Partition(**part) for part in value["partitions"]),
                gaps=tuple(DataGap(**gap) for gap in value["gaps"]),
                holdout=OpaqueHoldout(**value["holdout"]),
            )
            if canonical_json(value) != canonical_json(result.to_dict()):
                raise SwingError("INVALID_CONTRACT")
            return result
        except (ValueError, TypeError, KeyError, AttributeError):
            raise SwingError("INVALID_CONTRACT") from None


def resident_bytes() -> int:
    """Observable process RSS, no implicit clock or application services."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak",
                    "working",
                    "paged_peak",
                    "paged",
                    "nonpaged_peak",
                    "nonpaged",
                    "pagefile",
                    "pagefile_peak",
                )
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        try:
            function = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
            function.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
            function.restype = wintypes.BOOL
            if not function(wintypes.HANDLE(-1), ctypes.byref(counters), counters.cb):
                raise OSError
            return counters.working
        except OSError:
            raise SwingError("RESOURCE_LIMIT") from None
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)


def working_budget(resources: ResourceLimits, retained_bytes: int = 0) -> None:
    if type(resources) is not ResourceLimits:
        raise SwingError("INVALID_CONTRACT")
    if retained_bytes > resources.max_rss_bytes or resident_bytes() > resources.max_rss_bytes:
        raise SwingError("RESOURCE_LIMIT")
