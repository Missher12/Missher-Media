"""One conservative collection scope per OS user, independent of CDP/runtime.

Only standard-library imports: the installed adapter loads this exact module
under its runtime installation lease. No environment option changes the scope.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

LEASE_ENV = "MEDIA_MISSHER_LEASE_FDS"
MAX_HOMES = 64


class SharedSafetyError(RuntimeError):
    pass


class CollectionLease:
    def __init__(self, descriptors):
        self.pass_fds = tuple(descriptors)
        self.environment = {LEASE_ENV: ",".join(str(fd) for fd in descriptors)}


def shared_directory() -> Path:
    return Path.home() / ".local" / "share" / "media-missher-shared"


def runtime_home() -> Path:
    configured = os.environ.get("MEDIA_MISSHER_HOME", "").strip()
    return Path(configured).expanduser().absolute() if configured else Path.home() / ".local/share/media-missher"


def _no_links(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise SharedSafetyError("shared-state-invalid")


def _canonical_home(path: Path) -> Path:
    path = Path(path).expanduser().absolute()
    # Check before resolving: normalization must not hide a symlink component.
    _no_links(path)
    return path.resolve(strict=False)


def _same_directory(left: Path, right: Path) -> bool:
    return left.exists() and right.exists() and os.path.samestat(left.stat(), right.stat())


def _reject_shared_overlap(home: Path) -> None:
    shared = shared_directory()
    # Directory identity also handles case aliases on the default macOS volume.
    if any(_same_directory(parent, shared) for parent in (home, *home.parents)) or any(_same_directory(parent, home) for parent in (shared, *shared.parents)):
        raise SharedSafetyError("shared-state-invalid")


def _private_directory(path: Path, *, create=False) -> None:
    _no_links(path)
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise SharedSafetyError("shared-state-invalid")


def _private_file(info) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise SharedSafetyError("shared-state-invalid")


def _open_lock(path: Path) -> int:
    _no_links(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
    try:
        _private_file(os.fstat(fd))
        if not os.path.samestat(os.fstat(fd), path.stat(follow_symlinks=False)):
            raise SharedSafetyError("shared-state-invalid")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def registered_homes() -> tuple[Path, ...]:
    path = shared_directory() / "runtime-homes.json"
    _no_links(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return ()
    try:
        _private_file(os.fstat(fd))
        payload = os.read(fd, 65537)
        if len(payload) > 65536:
            raise ValueError("registry too large")
        value = json.loads(payload, object_pairs_hook=_unique)
        if not isinstance(value, dict) or set(value) != {"schema", "homes"} or type(value["schema"]) is not int or value["schema"] != 1:
            raise ValueError("registry schema")
        homes = value["homes"]
        if not isinstance(homes, list) or len(homes) > MAX_HOMES or any(not isinstance(item, str) or len(item) > 4096 or "\0" in item or not Path(item).is_absolute() or str(Path(item)) != item or ".." in Path(item).parts for item in homes) or len(set(homes)) != len(homes):
            raise ValueError("registry homes")
        return tuple(Path(item) for item in homes)
    except (ValueError, TypeError, UnicodeError) as error:
        raise SharedSafetyError("shared-state-invalid") from error
    finally:
        os.close(fd)


def _register(home: Path) -> tuple[Path, ...]:
    before = registered_homes()
    candidates = set(before) | {_canonical_home(home), _canonical_home(Path.home() / ".local/share/media-missher")}
    homes = []
    identities = set()
    # Prefer existing spelling so adding a case alias does not rewrite sources.
    for candidate in [*before, *sorted(candidates - set(before))]:
        _no_links(candidate)
        if candidate.exists():
            _private_directory(candidate)
            _reject_shared_overlap(candidate)
            info = candidate.stat()
            identity = (info.st_dev, info.st_ino)
            if identity in identities:
                continue
            identities.add(identity)
            homes.append(candidate)
        elif candidate in before:
            homes.append(candidate)  # Never forget an old source after deletion.
    if len(homes) > MAX_HOMES:
        raise SharedSafetyError("shared-state-invalid")
    result = tuple(sorted(homes))
    if result != before:
        payload = json.dumps({"schema": 1, "homes": [str(item) for item in result]}, separators=(",", ":")).encode()
        if len(payload) > 65536:
            raise SharedSafetyError("shared-state-invalid")
        fd, name = tempfile.mkstemp(prefix=".runtime-homes-", dir=shared_directory())
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, shared_directory() / "runtime-homes.json")
            directory_fd = os.open(shared_directory(), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.lexists(name):
                os.unlink(name)
    return result


def _legacy_locks(homes):
    result = []
    for home in homes:
        _no_links(home)
        if home.exists():
            _private_directory(home)
            result.append(home / ".media-missher-collection.lock")
    return result


def record_platform_risk(platform: str, code: str) -> None:
    """Persist while the caller holds collection_lease (including state_only).
    Lease release, expiry and backend switches never clear this marker.
    """
    import time
    from .batch_journal import atomic_json
    if platform not in {"bilibili", "xhs", "douyin", "weibo", "x"}:
        raise SharedSafetyError("shared-state-invalid")
    path = shared_directory() / "platform-risk.json"
    value = platform_risk_status()
    safe = code if code in {"challenge", "http-403", "http-429", "payload-461", "payload-471", "payload-999", "risk-signal"} else "risk-signal"
    value["platforms"].setdefault(platform, {"code": safe, "observed_at": time.time()})
    atomic_json(path, value)


def _read_marker(path):
    """Standalone adapter loads this file without a Python package context."""
    _no_links(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        _private_file(os.fstat(fd))
        data = os.read(fd, 65537)
        if len(data) > 65536:
            raise ValueError("shared marker too large")
        return json.loads(data, object_pairs_hook=_unique)
    finally:
        os.close(fd)


def _check_platform_risk():
    if platform_risk_status()["platforms"]:
        raise SharedSafetyError("platform-risk-latched")


def platform_risk_status():
    """Read validated state under collection_lease(state_only=True)."""
    import math
    path = shared_directory() / "platform-risk.json"
    if not os.path.lexists(path):
        return {"schema_version": 1, "platforms": {}}
    try:
        value = _read_marker(path)
        if not isinstance(value, dict) or set(value) != {"schema_version", "platforms"} or type(value["schema_version"]) is not int or value["schema_version"] != 1 or not isinstance(value["platforms"], dict):
            raise ValueError("risk schema")
        for platform, risk in value["platforms"].items():
            if platform not in {"bilibili", "xhs", "douyin", "weibo", "x"} or not isinstance(risk, dict) or set(risk) != {"code", "observed_at"}:
                raise ValueError("risk entry")
            if not isinstance(risk["code"], str) or risk["code"] not in {"challenge", "http-403", "http-429", "payload-461", "payload-471", "payload-999", "risk-signal"} or type(risk["observed_at"]) not in {int, float} or not math.isfinite(risk["observed_at"]) or risk["observed_at"] < 0:
                raise ValueError("risk value")
        return value
    except (ValueError, OSError) as error:
        raise SharedSafetyError("shared-state-invalid") from error


def acknowledge_platform_risk(platform):
    """Explicit operator action under the state-only collection lease.

    Validate first, record the acknowledgement before removing the marker, and
    never clear another platform or a normal collection cooldown. A failed
    write conservatively leaves a pause. No collector calls this function.
    """
    import time
    from .batch_journal import atomic_json
    if platform not in {"bilibili", "xhs", "douyin", "weibo", "x"}:
        raise SharedSafetyError("shared-state-invalid")
    value = platform_risk_status()
    result = None
    if platform == "xhs":
        from .xhs_policy import SharedXhsSafetyGate
        result = SharedXhsSafetyGate().acknowledge()
    prior = value["platforms"].get(platform)
    if prior is not None:
        # One bounded last-acknowledgement receipt per platform, no account data.
        atomic_json(shared_directory() / f"{platform}-risk-ack.json", {
            "schema_version": 1, "platform": platform,
            "risk": prior, "acknowledged_at": time.time(),
        })
        del value["platforms"][platform]
        atomic_json(shared_directory() / "platform-risk.json", value)
    return result if result is not None else value


def _check_legacy_host_lease():
    """Respect a still-active older runtime; this build never creates host leases."""
    import math
    import time
    marker = shared_directory() / "computer-use-lease.json"
    if not os.path.lexists(marker):
        return
    try:
        value = _read_marker(marker)
        if not isinstance(value, dict) or set(value) != {"owner", "expires_at"} or not isinstance(value["owner"], str) or type(value["expires_at"]) not in {float, int} or not math.isfinite(value["expires_at"]):
            raise ValueError("host lease invalid")
        if value["expires_at"] > time.time():
            raise SharedSafetyError("collection-busy")
    except (ValueError, OSError) as error:
        raise SharedSafetyError("shared-state-invalid") from error


@contextmanager
def collection_lease(home: Path, *, inherit: bool = False, state_only: bool = False):
    """Hold new and known legacy leases. An inherited lease is never unlocked.

    `inherit` is used only at the runtime child boundary. A string switch or a
    guessed FD does not bypass locking: every FD must match a current lock inode
    and its open-file description must successfully hold the exclusive flock.
    """
    owned = []
    inherited = []
    entered = False
    try:
        home = _canonical_home(home)
        _private_directory(shared_directory(), create=True)
        lock = shared_directory() / "collection.lock"
        raw = os.environ.get(LEASE_ENV) if inherit else None
        if raw is not None:
            if not raw or len(raw) > 1024 or any(not part.isascii() or not part.isdecimal() for part in raw.split(",")):
                raise SharedSafetyError("shared-lease-invalid")
            descriptors = tuple(int(part) for part in raw.split(","))
            if len(descriptors) > MAX_HOMES + 1 or len(set(descriptors)) != len(descriptors) or any(fd < 3 or fd > 2**31 - 1 for fd in descriptors):
                raise SharedSafetyError("shared-lease-invalid")
            homes = registered_homes()
            if home.exists() and not any(_same_directory(home, candidate) for candidate in homes):
                raise SharedSafetyError("shared-lease-invalid")
            paths = [lock, *_legacy_locks(homes)]
            if len(paths) != len(descriptors):
                raise SharedSafetyError("shared-lease-invalid")
            for path, fd in zip(paths, descriptors):
                _no_links(path)
                info = os.fstat(fd)
                _private_file(info)
                if not os.path.samestat(info, path.stat(follow_symlinks=False)):
                    raise SharedSafetyError("shared-lease-invalid")
                # A different open-file description fails if another owner holds
                # the lock. Reapplying EX to the inherited description is safe.
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                inherited.append(os.dup(fd))
            if not state_only:
                _check_platform_risk()
                _check_legacy_host_lease()
            entered = True
            yield CollectionLease(inherited)
        else:
            fd = _open_lock(lock)
            owned.append(fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise SharedSafetyError("collection-busy") from error
            homes = _register(Path(home).expanduser().absolute())
            for path in _legacy_locks(homes):
                fd = _open_lock(path)
                owned.append(fd)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise SharedSafetyError("collection-busy") from error
            if not state_only:
                _check_platform_risk()
                _check_legacy_host_lease()
            entered = True
            yield CollectionLease(owned)
    except OSError as error:
        if entered:
            raise
        raise SharedSafetyError("shared-lease-invalid" if inherit and os.environ.get(LEASE_ENV) is not None else "shared-state-invalid") from error
    finally:
        # close rather than LOCK_UN: a child may still own the inherited open
        # description if its parent terminates unexpectedly.
        for fd in reversed([*owned, *inherited]):
            os.close(fd)
