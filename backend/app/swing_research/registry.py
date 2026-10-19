"""Local append-only transactions, atomic publication, OS lock and explicit clocks.

The lock coordinates cooperating writers and is released by the OS on process exit.
This is not a filesystem sandbox against hostile concurrent filesystem changes.
Pin root_hash outside this directory to detect removal of an otherwise valid tail.
Publication is atomic with file fsync, without a power-loss durability guarantee.
SEALED is metadata here, not a capability to read or authorize any holdout data.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from .contracts import (
    MAX_DOCUMENT_BYTES,
    ResearchManifest,
    SwingError,
    TrialConfig,
    canonical_hash,
    canonical_json,
    digest,
    integer,
    parse_object,
)

MAX_TRANSACTIONS = 10_000
_TRANSITIONS = {
    "REGISTERED": {"STARTED", "REJECTED", "CANCELLED"},
    "STARTED": {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"},
    "FAILED": {"STARTED"},
    "CANCELLED": {"STARTED"},
    "INTERRUPTED": {"STARTED"},
    "COMPLETED": set(),
    "REJECTED": set(),
}
_REASONS = {
    "COMPLETED": {"FINISHED", "NO_TRADES"},
    "REJECTED": {"INPUT_NOT_ELIGIBLE"},
    "FAILED": {"INTERNAL_ERROR"},
    "CANCELLED": {"USER_CANCELLED"},
    "INTERRUPTED": {"EXECUTOR_INTERRUPTED"},
}


@dataclass(frozen=True)
class TrialState:
    config: TrialConfig
    state: str
    reason: str
    attempt: int


@dataclass(frozen=True)
class RegistryEvent:
    trial_id: str | None
    state: str
    reason: str
    now_ns: int


@dataclass(frozen=True)
class RegistrySnapshot:
    manifest: ResearchManifest
    trials: tuple[TrialState, ...]
    events: tuple[RegistryEvent, ...]
    holdout_state: str
    transaction_count: int
    root_hash: str

    @property
    def n_trials(self) -> int:
        return self.manifest.n_trials


def _safe_path(value) -> Path:
    try:
        if not isinstance(value, (str, Path)):
            raise SwingError("INVALID_PATH")
        path = Path(value)
        if not path.is_absolute() or ".." in path.parts or path.anchor.startswith(("\\\\", "//")):
            raise SwingError("INVALID_PATH")
        parts = [x.casefold() for x in path.parts]
        if any(x in {".git", ".env"} or x.rstrip(". ") != x or ":" in x for x in parts[1:]) or any(
            parts[i : i + 2] == ["data", "investedge.db"] for i in range(len(parts) - 1)
        ):
            raise SwingError("INVALID_PATH")
        for item in (path, *path.parents):
            if item.is_symlink() or item.is_junction():
                raise SwingError("INVALID_PATH")
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        raise SwingError("INVALID_PATH") from None


def _regular(path: Path) -> os.stat_result:
    try:
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink() or path.is_junction():
            raise SwingError("REGISTRY_INTEGRITY")
        return info
    except OSError:
        raise SwingError("REGISTRY_INTEGRITY") from None


class Registry:
    def __init__(self, *, input_root: Path, output_root: Path):
        self.input_root = _safe_path(input_root)
        self.output_root = _safe_path(output_root)
        if (
            not self.input_root.is_dir()
            or self.output_root == self.input_root
            or self.output_root.is_relative_to(self.input_root)
            or self.input_root.is_relative_to(self.output_root)
        ):
            raise SwingError("INVALID_PATH")
        try:
            self.output_root.mkdir(exist_ok=True)
        except OSError:
            raise SwingError("INVALID_PATH") from None

    @contextmanager
    def _lock(self):
        _safe_path(self.input_root)
        _safe_path(self.output_root)
        path = self.output_root / ".writer.lock"
        if (path.exists() or path.is_symlink()) and _regular(path).st_size > 1:
            raise SwingError("REGISTRY_INTEGRITY")
        fd = None
        locked = False
        try:
            fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                raise SwingError("REGISTRY_INTEGRITY")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise SwingError("REGISTRY_BUSY") from None
            locked = True
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            yield
        except OSError:
            raise SwingError("REGISTRY_WRITE_FAILED") from None
        finally:
            if fd is not None:
                if locked:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _files(self):
        records = []
        total = 0
        count = 0
        for path in self.output_root.iterdir():
            count += 1
            if count > MAX_TRANSACTIONS + 100:
                raise SwingError("RESOURCE_LIMIT")
            info = _regular(path)
            if path.name == ".writer.lock":
                continue
            total += info.st_size
            if path.name.startswith(".pending-"):
                if info.st_size > MAX_DOCUMENT_BYTES:
                    raise SwingError("RESOURCE_LIMIT")
                continue
            if re.fullmatch(r"\d{10}\.json", path.name) is None or info.st_size > MAX_DOCUMENT_BYTES:
                raise SwingError("REGISTRY_INTEGRITY")
            records.append(path)
        return sorted(records), total

    def _apply(self, state, record):
        op = record["operation"]
        payload = record["payload"]
        now = record["now_ns"]
        if type(payload) is not dict:
            raise SwingError("REGISTRY_INTEGRITY")
        if op == "REGISTER":
            if state is not None or set(payload) != {"manifest", "experiment_hash"}:
                raise SwingError("INVALID_TRANSITION")
            manifest = ResearchManifest.from_dict(payload["manifest"])
            if payload["experiment_hash"] != manifest.experiment_hash:
                raise SwingError("MANIFEST_MISMATCH")
            trials = {c.config_hash: TrialState(c, "REGISTERED", "PREREGISTERED", 0) for c in manifest.grid}
            state = {
                "manifest": manifest,
                "trials": trials,
                "events": [RegistryEvent(k, "REGISTERED", "PREREGISTERED", now) for k in trials],
                "holdout": "SEALED",
                "requests": {},
                "now": now,
                "count": 0,
                "hash": "0" * 64,
            }
        else:
            if state is None:
                raise SwingError("NOT_PREREGISTERED")
            if now < state["now"]:
                raise SwingError("INVALID_TRANSITION")
            if op == "TRANSITION":
                if set(payload) != {"trial_id", "state", "reason"}:
                    raise SwingError("INVALID_TRANSITION")
                trial_id = payload["trial_id"]
                target = payload["state"]
                reason = payload["reason"]
                if any(type(x) is not str for x in (trial_id, target, reason)) or trial_id not in state["trials"]:
                    raise SwingError("INVALID_TRANSITION")
                previous = state["trials"][trial_id]
                allowed_reason = (
                    ({"EXECUTION_STARTED"} if previous.state == "REGISTERED" else {"RETRY_STARTED"})
                    if target == "STARTED"
                    else _REASONS.get(target, set())
                )
                if (
                    target not in _TRANSITIONS[previous.state]
                    or reason not in allowed_reason
                    or target == "STARTED"
                    and state["holdout"] != "SEALED"
                ):
                    raise SwingError("INVALID_TRANSITION")
                state["trials"][trial_id] = TrialState(
                    previous.config, target, reason, previous.attempt + int(target == "STARTED")
                )
                state["events"].append(RegistryEvent(trial_id, target, reason, now))
            elif op == "CONTAMINATE":
                if payload or state["holdout"] != "SEALED":
                    raise SwingError("INVALID_TRANSITION")
                state["holdout"] = "CONTAMINATED"
                state["events"].append(RegistryEvent(None, "CONTAMINATED", "HOLDOUT_CONTAMINATED", now))
            else:
                raise SwingError("INVALID_TRANSITION")
        state["now"] = now
        state["count"] += 1
        state["hash"] = record["hash"]
        state["requests"][record["request_id"]] = canonical_hash(
            {k: record[k] for k in ("operation", "payload", "now_ns")}
        )
        return state

    def _load(self):
        records, total = self._files()
        state = None
        for seq, path in enumerate(records):
            try:
                if path.name != f"{seq:010d}.json":
                    raise SwingError("REGISTRY_INTEGRITY")
                with path.open("rb") as stream:
                    raw = stream.read(MAX_DOCUMENT_BYTES + 1)
                if len(raw) > MAX_DOCUMENT_BYTES:
                    raise SwingError("REGISTRY_INTEGRITY")
                text = raw.decode("utf-8")
                record = parse_object(text)
                if set(record) != {"seq", "previous", "request_id", "now_ns", "operation", "payload", "hash"}:
                    raise SwingError("REGISTRY_INTEGRITY")
                integer(record["seq"])
                integer(record["now_ns"])
                digest(record["request_id"])
                digest(record["hash"])
                body = {k: v for k, v in record.items() if k != "hash"}
                if (
                    record["seq"] != seq
                    or record["previous"] != ("0" * 64 if state is None else state["hash"])
                    or canonical_hash(body) != record["hash"]
                    or canonical_json(record) + "\n" != text
                    or state is not None
                    and record["request_id"] in state["requests"]
                ):
                    raise SwingError("REGISTRY_INTEGRITY")
                state = self._apply(state, record)
            except (ValueError, TypeError, KeyError, OSError):
                raise SwingError("REGISTRY_INTEGRITY") from None
        if state is not None and total > state["manifest"].resources.max_disk_bytes:
            raise SwingError("RESOURCE_LIMIT")
        return state, total

    @staticmethod
    def _snapshot(state):
        if state is None:
            raise SwingError("NOT_PREREGISTERED")
        return RegistrySnapshot(
            state["manifest"],
            tuple(state["trials"].values()),
            tuple(state["events"]),
            state["holdout"],
            state["count"],
            state["hash"],
        )

    def snapshot(self) -> RegistrySnapshot:
        with self._lock():
            state, _ = self._load()
            return self._snapshot(state)

    def _publish(self, record, *, total, budget):
        raw = (canonical_json(record) + "\n").encode("utf-8")
        if len(raw) > MAX_DOCUMENT_BYTES or total + len(raw) > budget or record["seq"] >= MAX_TRANSACTIONS:
            raise SwingError("RESOURCE_LIMIT")
        temp = None
        try:
            fd, name = tempfile.mkstemp(prefix=".pending-", dir=self.output_root)
            temp = Path(name)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            target = self.output_root / f"{record['seq']:010d}.json"
            if target.exists():
                raise SwingError("REGISTRY_INTEGRITY")
            os.replace(temp, target)
        except OSError:
            raise SwingError("REGISTRY_WRITE_FAILED") from None
        finally:
            if temp is not None:
                with suppress(OSError):
                    temp.unlink(missing_ok=True)

    def _change(self, operation, payload, *, request_id, now_ns):
        digest(request_id)
        integer(now_ns)
        command = {"operation": operation, "payload": payload, "now_ns": now_ns}
        command_hash = canonical_hash(command)
        with self._lock():
            state, total = self._load()
            if state is not None and request_id in state["requests"]:
                if state["requests"][request_id] != command_hash:
                    raise SwingError("INVALID_TRANSITION")
                return self._snapshot(state)
            record = command | {
                "seq": 0 if state is None else state["count"],
                "previous": "0" * 64 if state is None else state["hash"],
                "request_id": request_id,
            }
            record["hash"] = canonical_hash(record)
            state = self._apply(state, record)
            self._publish(record, total=total, budget=state["manifest"].resources.max_disk_bytes)
            return self._snapshot(state)

    def register(self, manifest: ResearchManifest, *, request_id: str, now_ns: int) -> RegistrySnapshot:
        if type(manifest) is not ResearchManifest:
            raise SwingError("INVALID_CONTRACT")
        return self._change(
            "REGISTER",
            {"manifest": manifest.to_dict(), "experiment_hash": manifest.experiment_hash},
            request_id=request_id,
            now_ns=now_ns,
        )

    def transition(self, trial_id: str, state: str, reason: str, *, request_id: str, now_ns: int) -> RegistrySnapshot:
        return self._change(
            "TRANSITION", {"trial_id": trial_id, "state": state, "reason": reason}, request_id=request_id, now_ns=now_ns
        )

    def contaminate_holdout(self, *, request_id: str, now_ns: int) -> RegistrySnapshot:
        return self._change("CONTAMINATE", {}, request_id=request_id, now_ns=now_ns)
