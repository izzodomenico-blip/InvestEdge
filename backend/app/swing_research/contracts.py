"""Immutable, versioned preregistration. No application services or implicit clock."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

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
