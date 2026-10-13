"""Immutable research metadata. No database, clock, provider or execution."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from backend.app.intraday.contracts import MAX_NS, canonical_json

VERSION = "intraday-research-v1"
STATES = frozenset({"REGISTERED", "STARTED", "COMPLETED", "REJECTED", "FAILED", "CANCELLED", "INTERRUPTED"})
REASONS = frozenset({"PREREGISTERED", "EXECUTION_STARTED", "FINISHED", "NO_TRADES",
                     "INPUT_NOT_ELIGIBLE", "INTERNAL_ERROR", "USER_CANCELLED", "EXECUTOR_INTERRUPTED"})
TRANSITIONS = {
    "REGISTERED": frozenset({"STARTED", "REJECTED", "CANCELLED"}),
    "STARTED": frozenset({"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}),
    "FAILED": frozenset({"STARTED"}), "CANCELLED": frozenset({"STARTED"}),
    "INTERRUPTED": frozenset({"STARTED"}), "REJECTED": frozenset(), "COMPLETED": frozenset(),
}


class ResearchError(ValueError):
    """Fixed codes; never interpolate inputs or configuration in exceptions."""
    def __init__(self, code: str):
        allowed = {"INVALID_CONTRACT", "INVALID_JSON", "NAMESPACE_MISMATCH", "INPUT_MISSING",
                   "PUBLIC_METADATA_INVALID", "REGISTRY_INTEGRITY", "INVALID_TRANSITION",
                   "INVALID_TIMESTAMP", "TRANSACTION_ALREADY_OPEN", "REGISTRY_WRITE_FAILED"}
        self.code = code if code in allowed else "INVALID_CONTRACT"
        super().__init__(self.code)


def integer(value: object, *, positive: bool = False) -> None:
    if type(value) is not int or not int(positive) <= value <= MAX_NS:
        raise ResearchError("INVALID_TIMESTAMP")


def digest(value: object, length: int = 64) -> None:
    if type(value) is not str or re.fullmatch(f"[a-f0-9]{{{length}}}", value) is None:
        raise ResearchError("INVALID_CONTRACT")


def canonical_hash(value: dict) -> str:
    try:
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    except ValueError:
        raise ResearchError("INVALID_JSON") from None


def parse_object(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ResearchError("INVALID_JSON")
            result[key] = value
        return result
    try:
        if type(text) is not str or len(text.encode("utf-8")) > 1_048_576:
            raise ResearchError("INVALID_JSON")
        result = json.loads(text, object_pairs_hook=pairs)
        canonical_json(result)
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ResearchError("INVALID_JSON") from None


@dataclass(frozen=True)
class ResearchNamespace:
    profile_id: str
    feed: str
    data_mode: str
    provenance: str
    replay_grade: str

    def __post_init__(self):
        digest(self.profile_id)
        if (any(type(value) is not str for value in self.key)
            or self.feed not in {"iex", "sip", "delayed_sip"}
            or self.data_mode not in {"REAL", "DEMO"}
            or self.provenance not in {"CAPTURED", "HISTORICAL_CURRENT", "SYNTHETIC"}
            or self.replay_grade not in {"STRICT_PIT", "RESEARCH_ONLY"}
            or self.data_mode == "DEMO" and self.provenance != "SYNTHETIC"
            or self.provenance != "CAPTURED" and self.replay_grade != "RESEARCH_ONLY"):
            raise ResearchError("NAMESPACE_MISMATCH")

    @property
    def key(self) -> tuple:
        return self.profile_id, self.feed, self.data_mode, self.provenance, self.replay_grade


@dataclass(frozen=True)
class ResourceLimits:
    max_disk_bytes: int
    min_free_bytes: int
    max_listings: int = 30
    max_chunk_occurrences: int = 10_000
    max_chunk_bytes: int = 8_388_608
    max_cache_bytes: int = 67_108_864
    max_rss_bytes: int = 2_147_483_648
    window_sessions: int = 5
    history_sessions: int = 30

    def __post_init__(self):
        ceilings = {"max_listings": 30, "max_chunk_occurrences": 10_000,
                    "max_chunk_bytes": 8_388_608, "max_cache_bytes": 67_108_864,
                    "max_rss_bytes": 2_147_483_648, "window_sessions": 5, "history_sessions": 30}
        for name, value in asdict(self).items():
            integer(value, positive=True)
            if name in ceilings and value > ceilings[name]:
                raise ResearchError("INVALID_CONTRACT")


@dataclass(frozen=True)
class CandidateConfig:
    family: str
    holding_minutes: int
    arm: str
    risk_id: str

    def __post_init__(self):
        if (any(type(value) is not str for value in (self.family, self.arm, self.risk_id))
            or self.family not in {"TREND_PULLBACK", "BREAKOUT_CONTINUATION", "NEWS_ONLY"}
            or type(self.holding_minutes) is not int or self.holding_minutes not in {15, 30}
            or self.arm not in {"TECH_ONLY", "TECH_NEWS", "NEWS_ONLY"}
            or (self.family == "NEWS_ONLY") != (self.arm == "NEWS_ONLY")
            or self.risk_id not in {"R0", "R1"}):
            raise ResearchError("INVALID_CONTRACT")

    def to_dict(self) -> dict:
        return asdict(self) | {"setup_version": "intraday-candidates-v1",
                              "risk": {"k": "1" if self.risk_id == "R0" else "1.5",
                                       "g": "1.5" if self.risk_id == "R0" else "2"}}

    @property
    def config_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @property
    def policy_key(self) -> str:
        return f"{self.family}|{self.holding_minutes}|{self.arm}"


def trial_grid() -> tuple[CandidateConfig, ...]:
    technical = tuple(CandidateConfig(family, holding, arm, risk)
        for family in ("TREND_PULLBACK", "BREAKOUT_CONTINUATION") for holding in (15, 30)
        for arm in ("TECH_ONLY", "TECH_NEWS") for risk in ("R0", "R1"))
    return technical + tuple(CandidateConfig("NEWS_ONLY", holding, "NEWS_ONLY", risk)
                              for holding in (15, 30) for risk in ("R0", "R1"))


@dataclass(frozen=True)
class DatasetRef:
    snapshot_id: int
    digest: str

    def __post_init__(self):
        integer(self.snapshot_id, positive=True)
        digest(self.digest)


@dataclass(frozen=True)
class ResearchManifest:
    namespace: ResearchNamespace
    resources: ResourceLimits
    datasets: tuple[DatasetRef, ...]
    start_at_ns: int
    end_at_ns: int
    cutoff_ns: int
    code_revision: str
    cost_profile_hash: str | None = None
    seed: int = 137

    def __post_init__(self):
        if type(self.namespace) is not ResearchNamespace or type(self.resources) is not ResourceLimits:
            raise ResearchError("INVALID_CONTRACT")
        if (type(self.datasets) is not tuple or not 1 <= len(self.datasets) <= 1_000
            or any(type(ref) is not DatasetRef for ref in self.datasets)
            or len({ref.snapshot_id for ref in self.datasets}) != len(self.datasets)):
            raise ResearchError("INVALID_CONTRACT")
        for stamp in (self.start_at_ns, self.end_at_ns, self.cutoff_ns):
            integer(stamp)
        if not self.start_at_ns < self.end_at_ns <= self.cutoff_ns:
            raise ResearchError("INVALID_TIMESTAMP")
        digest(self.code_revision, 40)
        if self.cost_profile_hash is not None:
            digest(self.cost_profile_hash)
        integer(self.seed)
        if self.seed != 137:
            raise ResearchError("INVALID_CONTRACT")
        canonical_json(self.to_dict())

    @property
    def grid(self) -> tuple[CandidateConfig, ...]:
        return trial_grid()

    def to_dict(self) -> dict:
        return {
            "version": VERSION, "namespace": asdict(self.namespace), "resources": asdict(self.resources),
            "datasets": [asdict(ref) for ref in self.datasets], "start_at_ns": self.start_at_ns,
            "end_at_ns": self.end_at_ns, "cutoff_ns": self.cutoff_ns, "code_revision": self.code_revision,
            "grid": [candidate.to_dict() for candidate in self.grid],
            "split": {"is_sessions": 126, "oos_sessions": 63, "oos_blocks": 4,
                      "holdout_sessions": 63, "embargo_sessions": 1, "warmup_sessions": 20},
            "statistics": {"seed": self.seed, "bootstrap_blocks": [1, 5, 10], "minimum_bootstrap_replicates": 10_000,
                           "replicates_rule": "max(10000,ceil(minimum_tail_replicates*M/alpha))",
                           "alpha": "0.05", "minimum_hypotheses": 20, "minimum_tail_replicates": 20},
            "capital": {"currency": "USD", "initial": "10000", "risk_fraction": "0.0025",
                        "max_listing_weight": "0.1", "max_positions": 5, "max_exposure": "1"},
            "costs": {"profile": "ALPACA_PERSONAL_US_EQUITIES", "profile_hash": self.cost_profile_hash,
                      "status": "UNVERIFIED", "recurring_status": "UNVERIFIED"},
            "execution": {"holding_origin": "FIRST_FILL", "latency_ms": 500, "slippage_bps": 2,
                          "entry_timeout_seconds": 30, "max_quote_participation": "0.1",
                          "stress_latency_ms": 2000, "stress_slippage_bps": 10,
                          "stress_spread_multiple": 2, "stress_additional_fee_bps": 5,
                          "stress_available_size": "0.5", "stress_quote_participation": "0.05",
                          "stress_nonfill_fraction": "0.05"},
            "gate": {"economic_status": "NOT_EVALUATED", "mean_trade_bps": 5,
                     "max_drawdown": "0.1", "worst_session": "-0.02",
                     "minimum_is_trades": 200, "minimum_is_active_sessions": 40,
                     "minimum_oos_trades": 400, "minimum_oos_active_sessions": 100,
                     "minimum_fold_trades": 50, "minimum_fold_active_sessions": 15,
                     "minimum_holdout_trades": 100, "minimum_holdout_active_sessions": 30,
                     "max_positive_contribution": "0.25", "joint_positive_confidence_bounds": True,
                     "required_positive_oos_folds": 3},
            "holdout": {"state": "SEALED", "scope": "RESEARCH_WORKFLOW", "external_access_contaminates": True},
        }

    @property
    def config_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def experiment_hash(self) -> str:
        return canonical_hash(self.to_dict())
