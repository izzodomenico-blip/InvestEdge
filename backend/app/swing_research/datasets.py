"""Read-only local packets, preflight and individually revalidated bounded batches.

Only explicitly listed public partitions are opened. The holdout reference has no
path or read capability. File hashes prove consistency with the caller's pinned
manifest, not publisher authenticity or the future custodian's attestation.
Complete each iterator before publishing derived evidence. There is no output
writer, implicit provider, database, dotenv or clock. This is not an OS sandbox.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .calendar import FxFix, Session, TradingCalendar, utc_datetime
from .contracts import (
    DATA_KINDS,
    MAX_DOCUMENT_BYTES,
    DataRecord,
    DatasetManifest,
    ResourceLimits,
    SwingError,
    canonical_json,
    decimal_value,
    digest,
    integer,
    parse_object,
    payload_fields,
    resident_bytes,
    supersedes,
)
from .events import CorporateAction
from .registry import _regular, _safe_path
from .universe import ListingFact, RawBar


def current_rss() -> int:
    return resident_bytes()


def _validate_record(record):
    if record.kind in ("DAILY", "MINUTE"):
        RawBar.from_record(record)
    elif record.kind == "IDENTITY":
        ListingFact.from_record(record)
    elif record.kind == "ACTION":
        CorporateAction.from_record(record)
    elif record.kind == "FX":
        FxFix.from_record(record)
    elif record.kind == "SESSION":
        Session.from_record(record)
    elif record.kind == "BENCHMARK":
        data = record.data
        payload_fields(data, {"return_usd", "basis", "source_hash"})
        digest(data["source_hash"])
        if data["basis"] != "TOTAL_RETURN_USD" or decimal_value(data["return_usd"]) < -1:
            raise SwingError("INVALID_CONTRACT")
    elif record.kind == "GAP":
        data = record.data
        payload_fields(data, {"end_ns", "state", "source_hash"})
        integer(data["end_ns"])
        digest(data["source_hash"])
        if data["state"] not in ("MISSING", "NO_TRADES", "HALT") or data["end_ns"] < record.event_ns:
            raise SwingError("INVALID_CONTRACT")


@dataclass(frozen=True)
class Batch:
    records: tuple[DataRecord, ...]
    decoded_bytes: int
    wire_bytes: int
    sha256: str

    @property
    def seal(self):
        return len(self.records), self.decoded_bytes, self.wire_bytes, self.sha256


@dataclass(frozen=True)
class QualityReport:
    dataset_hash: str
    state: str
    issues: tuple[str, ...]
    rows: int
    daily_observed: int
    daily_expected: int
    declared_bytes: int
    economic_gate: str = "NOT_EVALUATED"


def _decoded_charge(record, raw):
    fields = vars(record)
    # A split instance dictionary shrinks as more instances are allocated. Use a
    # conservative ordinary-dict charge so preflight/read batch seals stay stable.
    # Shared keys/values are deliberately charged again, plus container reserve.
    return max(
        len(raw),
        sys.getsizeof(record)
        + 2 * sys.getsizeof(dict(fields))
        + sum(sys.getsizeof(key) + sys.getsizeof(value) for key, value in fields.items())
        + 64,
    )


def _fence(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


@dataclass(frozen=True, init=False)
class Dataset:
    root: Path
    manifest: DatasetManifest
    resources: ResourceLimits

    def __init__(self, root: Path, manifest: DatasetManifest, *, expected_hash: str, resources: ResourceLimits):
        digest(expected_hash)
        if type(manifest) is not DatasetManifest or type(resources) is not ResourceLimits:
            raise SwingError("INVALID_CONTRACT")
        if manifest.dataset_hash != expected_hash:
            raise SwingError("MANIFEST_MISMATCH")
        path = _safe_path(root)
        if not path.is_dir():
            raise SwingError("INVALID_PATH")
        object.__setattr__(self, "root", path)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "resources", resources)
        if self._declared_bytes() > resources.max_disk_bytes:
            raise SwingError("RESOURCE_LIMIT")

    def _declared_bytes(self):
        return (
            len(canonical_json(self.manifest.to_dict()).encode("utf-8"))
            + sum(part.bytes for part in self.manifest.partitions)
            + self.manifest.holdout.bytes
        )

    def _budget(self):
        if current_rss() > self.resources.max_rss_bytes:
            raise SwingError("RESOURCE_LIMIT")

    def _path(self, part):
        root = _safe_path(self.root)
        path = _safe_path(root / part.path)
        if not path.is_relative_to(root):
            raise SwingError("INVALID_PATH")
        info = _regular(path)
        if info.st_size != part.bytes:
            raise SwingError("DATASET_CHANGED")
        return path, _fence(info)

    def _decode(self, raw, part):
        try:
            if len(raw) > MAX_DOCUMENT_BYTES or not raw.endswith(b"\n"):
                raise SwingError("DATASET_INTEGRITY")
            text = raw[:-1].decode("utf-8")
            value = parse_object(text)
            if (canonical_json(value) + "\n").encode("utf-8") != raw:
                raise SwingError("DATASET_INTEGRITY")
            record = DataRecord.from_dict(value)
            if utc_datetime(record.event_ns).date().isoformat() != record.session:
                raise SwingError("DATASET_INTEGRITY")
            if (
                record.kind != part.kind
                or not part.first_session <= record.session <= part.last_session
                or record.acquired_ns > self.manifest.acquired_ns
            ):
                raise SwingError("DATASET_INTEGRITY")
            if record.kind != "SESSION" and record.session >= self.manifest.holdout.first_session:
                raise SwingError("HOLDOUT_SEALED")
            if self.manifest.context.provenance == "CAPTURED" and (
                record.availability != "PROVEN" or record.available_ns < record.acquired_ns
            ):
                raise SwingError("NON_IDONEO")
            _validate_record(record)
            if record.kind in ("DAILY", "MINUTE", "FX", "BENCHMARK") and record.available_ns < record.event_ns:
                raise SwingError("DATASET_INTEGRITY")
            return record
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise SwingError("DATASET_INTEGRITY") from None

    def _batches(self, part):
        self._budget()
        path, fence = self._path(part)
        file_hash = hashlib.sha256()
        chunk_hash = hashlib.sha256()
        rows = []
        charge = wire = total = count = 0
        previous = first_session = last_session = None
        try:
            with path.open("rb") as stream:
                if _fence(os.fstat(stream.fileno())) != fence:
                    raise SwingError("DATASET_CHANGED")
                while raw := stream.readline(MAX_DOCUMENT_BYTES + 1):
                    self._budget()
                    record = self._decode(raw, part)
                    if previous is not None and record.grain <= previous:
                        raise SwingError("DATASET_INTEGRITY")
                    previous = record.grain
                    if first_session is None:
                        first_session = record.session
                    last_session = record.session
                    count += 1
                    total += len(raw)
                    if count > part.rows or total > part.bytes:
                        raise SwingError("DATASET_INTEGRITY")
                    file_hash.update(raw)
                    item_charge = _decoded_charge(record, raw)
                    if item_charge > self.resources.max_batch_bytes:
                        raise SwingError("RESOURCE_LIMIT")
                    if rows and (
                        len(rows) >= self.resources.max_batch_rows
                        or charge + item_charge > self.resources.max_batch_bytes
                    ):
                        if _fence(os.fstat(stream.fileno())) != fence or _fence(_regular(path)) != fence:
                            raise SwingError("DATASET_CHANGED")
                        yield Batch(tuple(rows), charge, wire, chunk_hash.hexdigest())
                        rows = []
                        charge = wire = 0
                        chunk_hash = hashlib.sha256()
                    rows.append(record)
                    charge += item_charge
                    wire += len(raw)
                    chunk_hash.update(raw)
                if (
                    count != part.rows
                    or total != part.bytes
                    or file_hash.hexdigest() != part.sha256
                    or (first_session, last_session) != (part.first_session, part.last_session)
                ):
                    raise SwingError("DATASET_INTEGRITY")
                if _fence(os.fstat(stream.fileno())) != fence or _fence(_regular(path)) != fence:
                    raise SwingError("DATASET_CHANGED")
                if rows:
                    yield Batch(tuple(rows), charge, wire, chunk_hash.hexdigest())
        except OSError:
            raise SwingError("DATASET_INTEGRITY") from None

    def _preflight(self):
        self._budget()
        if self.manifest.rights == "INCOMPATIBLE":
            raise SwingError("NON_IDONEO")
        seals = []
        issues = set()
        rows = daily = metadata = 0
        previous_kind = previous_grain = previous_daily = None
        for part in self.manifest.partitions:
            part_seals = []
            for batch in self._batches(part):
                if (
                    previous_kind == part.kind
                    and previous_grain is not None
                    and batch.records[0].grain <= previous_grain
                ):
                    raise SwingError("DATASET_INTEGRITY")
                previous_kind, previous_grain = part.kind, batch.records[-1].grain
                rows += len(batch.records)
                for record in batch.records:
                    if record.kind == "DAILY" and record.logical_key != previous_daily:
                        daily += 1
                        previous_daily = record.logical_key
                    if record.kind in ("DAILY", "MINUTE"):
                        basis = record.data["basis"]
                        if basis != "RAW":
                            issues.add("UNKNOWN_ADJUSTMENT" if basis == "UNKNOWN" else "RAW_BASIS_REQUIRED")
                if any(record.availability == "MODELED" for record in batch.records):
                    issues.add("MODELED_AVAILABILITY")
                if any(record.kind == "GAP" and record.data["state"] == "MISSING" for record in batch.records):
                    issues.add("DECLARED_DATA_GAP")
                seal = batch.seal
                metadata += sys.getsizeof(seal) + sum(sys.getsizeof(value) for value in seal) + 16
                if metadata > self.resources.max_batch_bytes:
                    raise SwingError("RESOURCE_LIMIT")
                part_seals.append(seal)
            seals.append(tuple(part_seals))
        manifest = self.manifest
        if manifest.price_basis != "RAW":
            issues.add("UNKNOWN_ADJUSTMENT" if manifest.price_basis == "UNKNOWN" else "RAW_BASIS_REQUIRED")
        if manifest.universe_basis != "ASOF":
            issues.add("UNIVERSE_NOT_ASOF")
        if manifest.rights == "UNKNOWN" or manifest.rights_hash is None:
            issues.add("RIGHTS_UNATTESTED")
        if manifest.coverage_hash is None or manifest.expected_daily_rows == 0:
            issues.add("COVERAGE_UNATTESTED")
        if manifest.expected_daily_rows != daily:
            issues.add("DAILY_COUNT_MISMATCH")
        if manifest.gaps and any(gap.state == "MISSING" for gap in manifest.gaps):
            issues.add("DECLARED_DATA_GAP")
        if manifest.availability == "MODELED":
            issues.add("MODELED_AVAILABILITY")
        if manifest.context.data_mode == "SYNTHETIC":
            issues.discard("MODELED_AVAILABILITY")
        else:
            if manifest.context.provenance != "CAPTURED":
                issues.add("HISTORICAL_CURRENT")
            if manifest.context.feed != "SIP":
                issues.add("NON_SIP_FEED")
        state = (
            "INSUFFICIENTE"
            if issues
            else "SYNTHETIC_ONLY"
            if manifest.context.data_mode == "SYNTHETIC"
            else "LOCAL_INPUTS_VERIFIED"
        )
        report = QualityReport(
            manifest.dataset_hash,
            state,
            tuple(sorted(issues)),
            rows,
            daily,
            manifest.expected_daily_rows,
            self._declared_bytes(),
        )
        return tuple(seals), report

    def verify(self) -> QualityReport:
        return self._preflight()[1]

    def iter_batches(self, kind: str):
        if kind == "HOLDOUT":
            raise SwingError("HOLDOUT_SEALED")
        if type(kind) is not str or kind not in DATA_KINDS:
            raise SwingError("INVALID_CONTRACT")
        seals, _ = self._preflight()
        for part, expected in zip(self.manifest.partitions, seals, strict=True):
            if part.kind == kind:
                count = 0
                for batch in self._batches(part):
                    if count >= len(expected) or batch.seal != expected[count]:
                        raise SwingError("DATASET_CHANGED")
                    count += 1
                    yield batch
                if count != len(expected):
                    raise SwingError("DATASET_CHANGED")

    def as_of(self, kind: str, cutoff_ns: int):
        integer(cutoff_ns)
        group = selected = None
        for batch in self.iter_batches(kind):
            for record in batch.records:
                if record.logical_key != group:
                    if selected is not None:
                        yield selected
                    group, selected = record.logical_key, None
                if (
                    record.available_ns <= cutoff_ns
                    and (kind not in ("DAILY", "MINUTE", "FX", "BENCHMARK") or record.event_ns <= cutoff_ns)
                    and supersedes(record, selected)
                ):
                    selected = record
        if selected is not None:
            yield selected

    def calendar(self, *, settlement_days: tuple[str, ...], source_hash: str, cutoff_ns: int) -> TradingCalendar:
        digest(source_hash)
        sessions = []
        for record in self.as_of("SESSION", cutoff_ns):
            self._budget()
            if record.data["source_hash"] != source_hash:
                raise SwingError("MANIFEST_MISMATCH")
            sessions.append(Session.from_record(record))
            if len(sessions) > 10000:
                raise SwingError("RESOURCE_LIMIT")
        if not sessions:
            raise SwingError("INSUFFICIENT_DATA")
        calendar = TradingCalendar(tuple(sessions), settlement_days, source_hash)
        if calendar.calendar_hash != self.manifest.calendar_hash:
            raise SwingError("MANIFEST_MISMATCH")
        return calendar
