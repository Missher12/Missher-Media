"""Private, persistent Xiaohongshu start limits; never schedules retries.

These local conservative budgets are not platform-approved safety thresholds.
The lock covers the whole browser operation, including standalone runtime calls.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import stat
import tempfile
import time
from contextlib import contextmanager, ExitStack
from pathlib import Path
from typing import Callable, Iterator

MAX_BATCH_NOTES = 10
MAX_BATCH_PAGES = 3
PAGE_INTERVAL_MS = 3000
MIN_BATCH_INTERVAL_SECONDS = 600
RISK_CODES = frozenset({"http-403", "http-429", "payload-461", "payload-471", "payload-999", "challenge", "risk-signal"})
BLOCK_CODES = frozenset({"xhs-cooldown", "xhs-risk-latched", "xhs-safety-busy", "xhs-safety-state-invalid"})


class SafetyBlocked(RuntimeError):
    def __init__(self, code: str, remaining_seconds: int = 0) -> None:
        self.code = code
        self.remaining_seconds = remaining_seconds
        super().__init__(code)


def default_state_dir() -> Path:
    from .shared_safety import shared_directory
    return shared_directory() / "state"


def _timestamp(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate state key")
        result[key] = value
    return result


class XhsSafetyGate:
    def __init__(self, state_dir: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.directory = Path(state_dir).expanduser().absolute()
        self.path = self.directory / "xhs-safety.json"
        self.clock = clock
        self._active = False

    @contextmanager
    def _locked(self) -> Iterator[None]:
        descriptor = -1
        try:
            if any(path.is_symlink() for path in (self.directory, *self.directory.parents)):
                raise ValueError("unsafe state directory")
            self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            info = self.directory.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("unsafe state directory")
            descriptor = os.open(self.directory / "xhs-safety.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("unsafe state lock")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise SafetyBlocked("xhs-safety-busy") from error
        except SafetyBlocked:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        except (OSError, ValueError) as error:
            if descriptor >= 0:
                os.close(descriptor)
            raise SafetyBlocked("xhs-safety-state-invalid") from error
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _read(self) -> dict:
        descriptor = -1
        try:
            try:
                descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            except FileNotFoundError:
                return {"version": 1, "last_started_at": None, "risk": None, "acknowledged_at": None}
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096:
                raise ValueError("unsafe state file")
            payload = os.read(descriptor, 4097)
            if len(payload) > 4096:
                raise ValueError("state exceeds bounded size")
            value = json.loads(payload, object_pairs_hook=_unique_object)
            if not isinstance(value, dict) or set(value) != {"version", "last_started_at", "risk", "acknowledged_at"} or type(value["version"]) is not int or value["version"] != 1:
                raise ValueError("invalid state schema")
            if any(value[key] is not None and not _timestamp(value[key]) for key in ("last_started_at", "acknowledged_at")):
                raise ValueError("invalid state timestamp")
            risk = value["risk"]
            if risk is not None and (not isinstance(risk, dict) or set(risk) != {"code", "observed_at"} or not isinstance(risk["code"], str) or risk["code"] not in RISK_CODES or not _timestamp(risk["observed_at"])):
                raise ValueError("invalid risk state")
            return value
        except (OSError, ValueError, TypeError, UnicodeError) as error:
            raise SafetyBlocked("xhs-safety-state-invalid") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _write(self, value: dict) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".xhs-safety-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, allow_nan=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)

    def _now(self) -> float:
        now = self.clock()
        if not _timestamp(now):
            raise SafetyBlocked("xhs-safety-state-invalid")
        return now

    def _remaining(self, state: dict) -> int:
        last = state["last_started_at"]
        return 0 if last is None else max(0, math.ceil(last + MIN_BATCH_INTERVAL_SECONDS - self._now()))

    @contextmanager
    def batch(self) -> Iterator[XhsSafetyGate]:
        with self._locked():
            state = self._read()
            if state["risk"] is not None:
                raise SafetyBlocked("xhs-risk-latched")
            remaining = self._remaining(state)
            if remaining:
                raise SafetyBlocked("xhs-cooldown", remaining)
            state["last_started_at"] = self._now()
            self._write(state)
            self._active = True
            try:
                yield self
            finally:
                self._active = False

    def latch(self, code: str) -> None:
        if not self._active:
            raise RuntimeError("risk latch requires an active batch lease")
        state = self._read()
        state["risk"] = {"code": code if code in RISK_CODES else "risk-signal", "observed_at": self._now()}
        self._write(state)

    def mark_collection_started(self) -> None:
        """Keep prior-platform work from consuming the XHS start interval."""
        if not self._active:
            raise RuntimeError("collection start requires an active batch lease")
        state = self._read()
        state["last_started_at"] = self._now()
        self._write(state)

    def record_risk(self, code: str) -> dict:
        """Controller fallback after its owned engine has fully stopped."""
        with self._locked():
            state = self._read()
            if state["risk"] is None:
                state["risk"] = {"code": code if code in RISK_CODES else "risk-signal", "observed_at": self._now()}
                self._write(state)
            return self._status(state)

    def acknowledge(self) -> dict:
        """Explicit local operator action; never clears the batch interval."""
        with self._locked():
            state = self._read()
            state["risk"] = None
            state["acknowledged_at"] = self._now()
            self._write(state)
            return self._status(state)

    def _status(self, state: dict) -> dict:
        remaining = self._remaining(state)
        return {
            "version": 1,
            "blocked": state["risk"] is not None or remaining > 0,
            "reason": "xhs-risk-latched" if state["risk"] is not None else "xhs-cooldown" if remaining else "ready",
            "remaining_seconds": remaining,
            "risk": state["risk"],
            "last_started_at": state["last_started_at"],
            "max_batch_notes": MAX_BATCH_NOTES,
            "max_batch_pages": MAX_BATCH_PAGES,
            "minimum_batch_interval_seconds": MIN_BATCH_INTERVAL_SECONDS,
        }

    def status(self) -> dict:
        with self._locked():
            return self._status(self._read())


class SharedXhsSafetyGate(XhsSafetyGate):
    """Merge all known old states, and keep them protected and synchronized.

    Caller holds the shared collection lease before using this gate. State
    writes go to the central copy first. A crash during acknowledgement may
    conservatively preserve a pause, but cannot reset a cooldown or lose risk.
    """
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        super().__init__(default_state_dir(), clock=clock)
        self._legacy: list[XhsSafetyGate] = []

    @contextmanager
    def _locked(self) -> Iterator[None]:
        from .shared_safety import registered_homes, SharedSafetyError
        try:
            with ExitStack() as stack:
                stack.enter_context(super()._locked())
                legacy = []
                for home in registered_homes():
                    if home.is_symlink():
                        raise SafetyBlocked("xhs-safety-state-invalid")
                    if home.exists():
                        gate = XhsSafetyGate(home / "state", clock=self.clock)
                        stack.enter_context(gate._locked())
                        legacy.append(gate)
                self._legacy = legacy
                # Validate every source before the first write. Status also
                # performs this idempotent local migration, without browsing.
                self._write(self._read())
                try:
                    yield
                finally:
                    self._legacy = []
        except (SharedSafetyError, OSError) as error:
            raise SafetyBlocked("xhs-safety-state-invalid") from error

    def _read(self) -> dict:
        states = [super()._read(), *(gate._read() for gate in self._legacy)]
        starts = [value["last_started_at"] for value in states if value["last_started_at"] is not None]
        acknowledgements = [value["acknowledged_at"] for value in states if value["acknowledged_at"] is not None]
        risks = [value["risk"] for value in states if value["risk"] is not None]
        return {
            "version": 1,
            "last_started_at": max(starts, default=None),
            "risk": max(risks, key=lambda risk: (risk["observed_at"], risk["code"]), default=None),
            "acknowledged_at": max(acknowledgements, default=None),
        }

    def _write(self, value: dict) -> None:
        super()._write(value)
        for gate in self._legacy:
            gate._write(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the local Xiaohongshu start guard. No browser operations.")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--acknowledge-risk", action="store_true", help="Explicit operator acknowledgement after inspecting the account in the normal browser; does not prove platform safety or start collection")
    actions.add_argument("--record-risk", choices=sorted(RISK_CODES), help="Persist a controller-detected risk after collection has stopped; never clears state or collects")
    args = parser.parse_args(argv)
    from .shared_safety import collection_lease, runtime_home, SharedSafetyError
    try:
        with collection_lease(runtime_home(), inherit=True):
            gate = SharedXhsSafetyGate()
            result = gate.acknowledge() if args.acknowledge_risk else gate.record_risk(args.record_risk) if args.record_risk else gate.status()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except SharedSafetyError as error:
        print(json.dumps({"blocked": True, "reason": "xhs-safety-busy" if str(error) == "collection-busy" else "xhs-safety-state-invalid"}))
        return 78
    except SafetyBlocked as error:
        print(json.dumps({"blocked": True, "reason": error.code}))
        return 78
