#!/usr/bin/env python3
"""Standard-library adapter primitives for the shared Media@Missher runtime."""

from __future__ import annotations

import csv
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import re
import secrets
import signal
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")
_BROWSER_ASSIST_MODES = frozenset({"off", "browserskill"})
_SCREENSHOT_MODES = frozenset({"off", "opened", "all"})
MAX_SCREENSHOT_BYTES = 50 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SAFE_SCREENSHOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SCREENSHOT_COMPLETE_FIELDS = frozenset(
    {
        "screenshot_path",
        "screenshot_mode",
        "screenshot_capture_kind",
        "screenshot_observed_at",
        "screenshot_sha256",
        "screenshot_status",
    }
)
_SCREENSHOT_FIELDS = _SCREENSHOT_COMPLETE_FIELDS | {"screenshot_error_code"}
_SAFE_PRECONDITION_CODES = frozenset(
    {
        "precondition-failed",
        "bsk-missing",
        "bsk-unhealthy",
        "bsk-incompatible",
        "bsk-busy",
        "bsk-transport",
        "bsk-timeout",
        "bsk-target-ambiguous",
        "bsk-session-start",
        "bsk-tab-list",
        "bsk-tab-borrow",
        "bsk-snapshot",
        "bsk-click",
        "bsk-tab-return",
        "bsk-session-stop",
        "bsk-navigate",
        "bsk-observe",
        "bsk-get-html",
        "bsk-extract",
        "bsk-stale-reference",
        "bsk-risk-signal",
        "bsk-navigation-not-authorized",
        "browser-assist-replaced",
        "platform-collector-missing",
        "topic-collector-unavailable",
        "topic-unsupported-platform",
        "topic-container-unsupported",
        "topic-input-invalid",
        "topic-kind-mismatch",
        "target-identity-missing",
        "target-keyword-missing",
        "target-topic-missing",
        "plan-request-invalid",
        "plan-executor-missing",
        "plan-manifest-invalid",
        "exclude-file-plan-unsupported",
        "platform-cooldown",
            "platform-risk-latched",
            "xhs-cooldown",
        "xhs-risk-latched",
        "xhs-safety-busy",
        "xhs-safety-state-invalid",
        "collection-busy",
        "shared-state-invalid",
    }
)
RUNTIME_ENTRYPOINTS = (
    "scrape_all.py",
    "scrape_bilibili.py",
    "scrape_xhs.py",
    "scrape_douyin.py",
    "scrape_weibo.py",
)
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
REQUIRED_RUNTIME_VERSION = "17.0.2"
SKILL_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_OWNER_MARKER = ".media-missher-owner.json"
RUNTIME_OWNER_PAYLOAD = {"name": "media-missher-runtime-home", "schema": 1}
RELEASE_MARKER = ".media-missher-release"
INSTALL_LOCK = ".media-missher-install.lock"
COLLECTION_LOCK = ".media-missher-collection.lock"
SOURCE_TREE_MARKER = ".media-missher-source-tree"
SOURCE_TREE_IDENTITY = b"media-missher-source-v1\n"
MAX_RELEASE_ID_BYTES = 128
_RELEASE_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
_MANIFEST_KEYS = frozenset(
    {"counts", "paths", "platforms", "status", "diagnostics"}
)
_DIAGNOSTIC_CODES = {
    "ok": frozenset({"ok"}),
    "result": frozenset(
        {"count-shortfall", "incomplete-record", "screenshot-shortfall", "required-fields-missing"}
    ),
    "not-run": frozenset({"preflight-aborted", "prior-risk-stop"}),
    "dependency": frozenset({"module-not-found"}),
    "precondition": _SAFE_PRECONDITION_CODES,
    "source-response": frozenset({"source-response-failed"}),
    "risk-stop": frozenset(
        {
            "http-403",
            "http-429",
            "payload-461",
            "payload-471",
            "payload-999",
            "challenge",
            "risk-signal",
        }
    ),
    "timeout": frozenset(
        {"platform-timeout", "creator-capture-timeout", "detail-capture-timeout"}
    ),
    "collector-contract": frozenset({"invalid-records"}),
    "internal": frozenset({"unexpected"}),
}
_STATUS_KINDS = {
    "complete": frozenset({"ok"}),
    "shortfall": frozenset({"result"}),
    "incomplete": frozenset({"result"}),
    "failed": frozenset(
        {
            "dependency",
            "precondition",
            "source-response",
            "timeout",
            "collector-contract",
            "internal",
        }
    ),
    "risk-stopped": frozenset({"risk-stop"}),
    "not-run": frozenset({"not-run"}),
}


def ensure_runtime_on_path() -> None:
    """Make the shared runtime package importable from a checkout or a payload.

    The installed layout keeps the runtime beside the skill, so the adjacency
    check is the same in both places. Appending (not inserting) preserves the
    priority of an already-installed runtime.
    """

    import sys

    candidate = Path(__file__).resolve().parents[2] / "runtime"
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.append(str(candidate))


ensure_runtime_on_path()


class ConfigurationError(ValueError):
    """Raised when a request cannot be validated before engine execution."""


class _RuntimeLeaseError(ConfigurationError):
    """Raised when the installed runtime cannot be leased as one release."""

    def __init__(self, message: str, *, lease_acquired: bool = False) -> None:
        super().__init__(message)
        self.lease_acquired = lease_acquired


class _CollectionLeaseError(ConfigurationError):
    """Raised when another collection owns the dedicated browser profile."""


def _validated_manifest_diagnostics(manifest: object) -> dict[str, dict[str, str]]:
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise ConfigurationError("invalid runtime manifest diagnostic contract")
    counts = manifest.get("counts")
    platforms = manifest.get("platforms")
    diagnostics = manifest.get("diagnostics")
    if not all(isinstance(value, dict) for value in (counts, platforms, diagnostics)):
        raise ConfigurationError("invalid runtime manifest diagnostic contract")
    selected = set(platforms)
    if (
        not selected
        or set(counts) != selected
        or set(diagnostics) != selected
        or any(platform not in PLATFORMS for platform in selected)
    ):
        raise ConfigurationError("invalid runtime manifest diagnostic platform keys")
    sanitized: dict[str, dict[str, str]] = {}
    for platform in platforms:
        platform_status = platforms[platform]
        value = diagnostics[platform]
        if (
            not isinstance(platform_status, str)
            or platform_status not in _STATUS_KINDS
            or not isinstance(value, dict)
            or set(value) != {"kind", "code"}
        ):
            raise ConfigurationError("invalid runtime manifest diagnostic schema")
        kind, code = value.get("kind"), value.get("code")
        if (
            not isinstance(kind, str)
            or not isinstance(code, str)
            or kind not in _DIAGNOSTIC_CODES
            or code not in _DIAGNOSTIC_CODES[kind]
            or kind not in _STATUS_KINDS[platform_status]
        ):
            raise ConfigurationError("invalid runtime manifest diagnostic value")
        expected = {
            "complete": ("ok", "ok"),
            "shortfall": ("result", "count-shortfall"),
        }.get(platform_status)
        if expected is not None and (kind, code) != expected:
            raise ConfigurationError("runtime manifest status and diagnostic differ")
        if platform_status == "incomplete" and (kind, code) not in {
            ("result", "incomplete-record"),
            ("result", "screenshot-shortfall"),
            ("result", "required-fields-missing"),
        }:
            raise ConfigurationError("runtime manifest status and diagnostic differ")
        sanitized[platform] = {"kind": kind, "code": code}
    overall = manifest.get("status")
    expected_overall = (
        "risk-stopped"
        if any(value == "risk-stopped" for value in platforms.values())
        else "complete"
        if all(value == "complete" for value in platforms.values())
        else "failed"
    )
    if overall != expected_overall:
        raise ConfigurationError("runtime manifest overall diagnostic is inconsistent")
    return sanitized


@dataclass(frozen=True)
class RuntimeLayout:
    home: Path
    current: Path
    python: Path
    state: Path


@dataclass(frozen=True)
class CollectionRequest:
    platforms: tuple[str, ...]
    count: int = 15
    platform_counts: Mapping[str, int] = field(default_factory=dict)
    platform_uids: Mapping[str, str] = field(default_factory=dict)
    search: str | None = None
    complete: bool = False
    bilibili_complete: bool = False
    xhs_complete: bool = False
    xhs_comments: int = 0
    platform_timeout: float = 300.0
    output_format: str = "json"
    collect_as_much_as_safe: bool = False
    allow_navigation: bool = False
    browser_assist: str = "off"
    screenshot_mode: str = "off"

    def __post_init__(self):
        requested = tuple(dict.fromkeys(str(item).strip().lower() for item in self.platforms))
        if not requested or any(not item for item in requested):
            raise ConfigurationError("at least one platform is required")
        unknown = sorted(set(requested) - set(PLATFORMS))
        if unknown:
            raise ConfigurationError(f"unknown platform: {', '.join(unknown)}")
        object.__setattr__(self, "platforms", requested)

        count = parse_non_negative_int(self.count)
        object.__setattr__(self, "count", count)
        normalized_counts: dict[str, int] = {}
        for platform, value in self.platform_counts.items():
            key = str(platform).strip().lower()
            if key not in requested:
                raise ConfigurationError(f"platform count requires a selected platform: {key}")
            normalized_counts[key] = parse_non_negative_int(value)
        object.__setattr__(self, "platform_counts", normalized_counts)

        effective_counts = {
            platform: normalized_counts.get(platform, count)
            for platform in requested
        }
        zero_effective_count = any(value == 0 for value in effective_counts.values())
        if zero_effective_count and not self.collect_as_much_as_safe:
            raise ConfigurationError(
                "count zero requires explicit collect-as-much-as-safe intent"
            )

        normalized_uids: dict[str, str] = {}
        for platform, value in self.platform_uids.items():
            key = str(platform).strip().lower()
            if key not in requested:
                raise ConfigurationError(f"platform UID requires a selected platform: {key}")
            uid = str(value).strip()
            if not uid:
                raise ConfigurationError(f"platform UID cannot be empty: {key}")
            normalized_uids[key] = uid
        object.__setattr__(self, "platform_uids", normalized_uids)

        search = self.search.strip() if isinstance(self.search, str) else self.search
        if search == "":
            raise ConfigurationError("search keyword cannot be empty")
        object.__setattr__(self, "search", search)
        if search and len(requested) != 1:
            raise ConfigurationError("search requires exactly one platform")
        if search and (self.complete or self.bilibili_complete or self.xhs_complete):
            raise ConfigurationError("search cannot be combined with complete mode")
        if self.complete and not set(requested).intersection({"bilibili", "xhs"}):
            raise ConfigurationError("complete mode requires bilibili or xhs")
        if self.bilibili_complete and "bilibili" not in requested:
            raise ConfigurationError("bilibili complete mode requires bilibili")
        if self.xhs_complete and "xhs" not in requested:
            raise ConfigurationError("xhs complete mode requires xhs")

        comments = parse_non_negative_int(self.xhs_comments)
        object.__setattr__(self, "xhs_comments", comments)
        if comments and "xhs" not in requested:
            raise ConfigurationError("xhs comments require the xhs platform")
        if comments and search and self.screenshot_mode != "all":
            raise ConfigurationError("search comments require xhs and screenshot mode all")

        if isinstance(self.platform_timeout, bool):
            raise ConfigurationError("platform timeout must be a non-negative number")
        try:
            timeout = float(self.platform_timeout)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("platform timeout must be a non-negative number") from exc
        if not math.isfinite(timeout) or timeout < 0:
            raise ConfigurationError("platform timeout must be a non-negative number")
        object.__setattr__(self, "platform_timeout", timeout)

        if self.output_format not in {"json", "csv", "jsonl", "sqlite"}:
            raise ConfigurationError("output format must be json, csv, jsonl, or sqlite")
        if not isinstance(self.allow_navigation, bool):
            raise ConfigurationError("navigation authorization must be an explicit boolean")
        if self.browser_assist not in _BROWSER_ASSIST_MODES:
            raise ConfigurationError("unsupported browser assist mode")
        # ``browser_assist="browserskill"`` is the deprecated mixed-control
        # bridge, not a backend. It stays a well-defined legacy shape here; the
        # collection CLI refuses a new run with ``browser-assist-replaced`` and
        # never reinterprets it as a supported backend.
        if self.screenshot_mode not in _SCREENSHOT_MODES:
            raise ConfigurationError("unsupported screenshot mode")
        if self.screenshot_mode == "all" and zero_effective_count:
            raise ConfigurationError("screenshot mode all requires a positive count")
        assisted = self.browser_assist != "off" or self.screenshot_mode != "off"
        if assisted and not self.allow_navigation:
            raise ConfigurationError("browser assist and screenshots require navigation authorization")
        if assisted and any(platform not in {"bilibili", "xhs"} for platform in requested):
            raise ConfigurationError("browser assist and screenshots support only bilibili and xhs")
        if assisted and search and requested == ("bilibili",):
            raise ConfigurationError("Bilibili search advanced modes are not supported")


@dataclass(frozen=True)
class EngineCommand:
    script: Path
    argv: tuple[str, ...]
    environment: Mapping[str, str] = field(default_factory=dict)
    pass_fds: tuple[int, ...] = ()

    def with_environment(self, values: Mapping[str, str]) -> "EngineCommand":
        merged = {**self.environment, **{str(key): str(value) for key, value in values.items()}}
        return EngineCommand(self.script, self.argv, merged, self.pass_fds)


@dataclass(frozen=True)
class CompletedRun:
    returncode: int | None
    stdout_path: Path
    stderr_path: Path
    timed_out: bool
    risk_detected: bool
    duration_seconds: float


def parse_non_negative_int(value: str | int) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ConfigurationError("value must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("value must be a non-negative integer") from exc
    if parsed < 0:
        raise ConfigurationError("value must be a non-negative integer")
    return parsed


def parse_platforms(value: str | None) -> tuple[str, ...]:
    if value is None:
        return PLATFORMS
    requested = tuple(
        dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip())
    )
    if not requested:
        raise ConfigurationError("at least one platform is required")
    unknown = sorted(set(requested) - set(PLATFORMS))
    if unknown:
        raise ConfigurationError(f"unknown platform: {', '.join(unknown)}")
    return requested


def read_profile(path: Path | None) -> dict:
    if path is None:
        return {}
    profile_path = Path(path).expanduser().resolve(strict=False)
    forbidden_roots = [SKILL_ROOT]
    development_root = SKILL_ROOT.parent
    if (development_root / ".git").exists() or (development_root / "tests").is_dir():
        forbidden_roots.append(development_root)
    if any(profile_path.is_relative_to(root) for root in forbidden_roots):
        raise ConfigurationError("profile must live outside the repository and installed skill")
    try:
        mode = stat.S_IMODE(profile_path.stat().st_mode)
    except OSError as exc:
        raise ConfigurationError(f"cannot read profile: {exc}") from exc
    if mode != 0o600:
        raise ConfigurationError("profile must use exact mode 0600")
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid profile JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("profile must contain a JSON object")
    return payload


def _configured_path(
    cli_value: Path | None,
    *,
    environment_name: str,
    profile_name: str,
    environ: Mapping[str, str],
    profile: Mapping | None,
) -> Path | None:
    raw = cli_value
    if raw is None:
        raw = environ.get(environment_name)
    if raw is None and profile:
        raw = profile.get(profile_name)
    if raw is None or not str(raw).strip():
        return None
    return Path(raw).expanduser().resolve()


def resolve_runtime_layout(*, environ: Mapping[str, str]) -> RuntimeLayout:
    configured_home = environ.get("MEDIA_MISSHER_HOME")
    if configured_home is not None and configured_home.strip():
        home = Path(configured_home).expanduser().absolute()
    else:
        home = (Path.home() / ".local" / "share" / "media-missher").absolute()
    return RuntimeLayout(
        home=home,
        current=(home / "current").absolute(),
        python=(home / "venv" / "bin" / "python").absolute(),
        state=(home / "state").absolute(),
    )


def _reject_symlink_components(path: Path, label: str) -> None:
    absolute = Path(path).expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise _RuntimeLeaseError(f"{label} contains a symlink")


def _owned_private_stat(path: Path, label: str) -> os.stat_result:
    try:
        file_stat = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise _RuntimeLeaseError(f"{label} is unavailable: {type(exc).__name__}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise _RuntimeLeaseError(f"{label} is not a regular file")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise _RuntimeLeaseError(f"{label} must use exact mode 0600")
    if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
        raise _RuntimeLeaseError(f"{label} must be owned by the current user")
    return file_stat


def _read_owned_private_file(
    path: Path,
    label: str,
    *,
    limit: int,
    lease_acquired: bool = False,
) -> bytes:
    try:
        _reject_symlink_components(path, label)
        expected = _owned_private_stat(path, label)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not os.path.samestat(expected, opened):
                raise _RuntimeLeaseError(f"{label} changed while being opened")
            if opened.st_size > limit:
                raise _RuntimeLeaseError(f"{label} exceeds its size limit")
            payload = os.read(descriptor, limit + 1)
            if len(payload) > limit:
                raise _RuntimeLeaseError(f"{label} exceeds its size limit")
            return payload
        finally:
            os.close(descriptor)
    except _RuntimeLeaseError as exc:
        if lease_acquired and not exc.lease_acquired:
            raise _RuntimeLeaseError(str(exc), lease_acquired=True) from exc
        raise
    except OSError as exc:
        raise _RuntimeLeaseError(
            f"{label} is unavailable: {type(exc).__name__}",
            lease_acquired=lease_acquired,
        ) from exc


def _development_skill_root() -> bool:
    if SKILL_ROOT.name != "media-missher" or os.path.lexists(SKILL_ROOT / RELEASE_MARKER):
        return False
    marker = SKILL_ROOT.parent / SOURCE_TREE_MARKER
    descriptor: int | None = None
    try:
        descriptor = os.open(marker, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        marker_stat = os.fstat(descriptor)
        if not stat.S_ISREG(marker_stat.st_mode):
            return False
        payload = os.read(descriptor, len(SOURCE_TREE_IDENTITY) + 1)
        return payload == SOURCE_TREE_IDENTITY
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_runtime_owner(home: Path) -> None:
    _reject_symlink_components(home, "runtime home")
    try:
        home_stat = os.stat(home, follow_symlinks=False)
    except OSError as exc:
        raise _RuntimeLeaseError(
            f"runtime home is unavailable: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISDIR(home_stat.st_mode):
        raise _RuntimeLeaseError("runtime home is not a directory")
    if stat.S_IMODE(home_stat.st_mode) != 0o700:
        raise _RuntimeLeaseError("runtime home must use exact mode 0700")
    if hasattr(os, "getuid") and home_stat.st_uid != os.getuid():
        raise _RuntimeLeaseError("runtime home must be owned by the current user")
    marker = home / RUNTIME_OWNER_MARKER
    try:
        payload = json.loads(
            _read_owned_private_file(marker, "runtime ownership marker", limit=512).decode(
                "utf-8"
            )
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _RuntimeLeaseError("runtime ownership marker is invalid") from exc
    if payload != RUNTIME_OWNER_PAYLOAD:
        raise _RuntimeLeaseError("runtime ownership marker is invalid")


def _read_release_marker(root: Path, label: str) -> str:
    marker = root / RELEASE_MARKER
    try:
        raw = _read_owned_private_file(
            marker,
            f"{label} release marker",
            limit=MAX_RELEASE_ID_BYTES + 1,
            lease_acquired=True,
        )
        text = raw.decode("ascii")
    except UnicodeError as exc:
        raise _RuntimeLeaseError(
            f"{label} release marker must be ASCII", lease_acquired=True
        ) from exc
    release = text[:-1] if text.endswith("\n") else text
    if text not in {release, release + "\n"} or not _RELEASE_ID_PATTERN.fullmatch(release):
        raise _RuntimeLeaseError(
            f"{label} release marker is invalid", lease_acquired=True
        )
    return release


def _validate_release_set(layout: RuntimeLayout) -> str:
    markers = [
        (layout.current, "current runtime"),
        (layout.home / "venv", "runtime venv"),
    ]
    if not _development_skill_root():
        markers.append((SKILL_ROOT, "installed Codex skill"))
    releases = [(label, _read_release_marker(root, label)) for root, label in markers]
    release_ids = {release for _label, release in releases}
    if len(release_ids) != 1:
        raise _RuntimeLeaseError(
            "runtime release markers do not match", lease_acquired=True
        )
    return releases[0][1]


@contextmanager
def _runtime_lease(layout: RuntimeLayout, *, timeout: float):
    if not isinstance(layout, RuntimeLayout):
        raise ConfigurationError("runtime layout is required")
    home = layout.home.expanduser().absolute()
    if not (
        layout.current.expanduser().absolute() == (home / "current").absolute()
        and layout.python.expanduser().absolute()
        == (home / "venv" / "bin" / "python").absolute()
        and layout.state.expanduser().absolute() == (home / "state").absolute()
    ):
        raise _RuntimeLeaseError("runtime layout paths do not match the shared-home contract")
    _validate_runtime_owner(home)
    lock = home / INSTALL_LOCK
    _reject_symlink_components(lock, "installation lock")
    expected = _owned_private_stat(lock, "installation lock")
    descriptor: int | None = None
    acquired = False
    try:
        try:
            descriptor = os.open(lock, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            opened = os.fstat(descriptor)
            if not os.path.samestat(expected, opened):
                raise _RuntimeLeaseError("installation lock changed while being opened")
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError as exc:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise _RuntimeLeaseError(
                            "installation lock remained exclusive until the lease timeout"
                        ) from exc
                    time.sleep(min(0.01, remaining))
            release = _validate_release_set(layout)
        except _RuntimeLeaseError:
            raise
        except OSError as exc:
            raise _RuntimeLeaseError(
                f"installation lock is unavailable: {type(exc).__name__}"
            ) from exc
        yield release
    finally:
        if descriptor is not None:
            try:
                if acquired:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _load_shared_safety(layout: RuntimeLayout):
    """Load only the verified installed core while its installation lease is held."""
    path = layout.current / "media_missher_runtime" / "shared_safety.py"
    _reject_symlink_components(path, "shared safety module")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise _CollectionLeaseError("shared-state-invalid")
    spec = importlib.util.spec_from_file_location("_media_missher_shared_safety", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _collection_lease(layout: RuntimeLayout):
    entered = False
    try:
        module = _load_shared_safety(layout)
        with module.collection_lease(layout.home) as lease:
            entered = True
            yield lease
    except (OSError, _RuntimeLeaseError) as error:
        if entered:
            raise
        raise _CollectionLeaseError("shared-state-invalid") from error
    except RuntimeError as error:
        if type(error).__name__ == "SharedSafetyError":
            message = (
                "another Media@Missher collection is already running" if str(error) == "collection-busy"
                else "platform-risk-latched" if str(error) == "platform-risk-latched"
                else "shared-state-invalid"
            )
            raise _CollectionLeaseError(message) from error
        raise


def resolve_data_root(
    cli_value: Path | None,
    *,
    environ: Mapping[str, str],
    profile: Mapping | None = None,
) -> Path:
    resolved = _configured_path(
        cli_value,
        environment_name="MEDIA_MISSHER_DATA_ROOT",
        profile_name="data_root",
        environ=environ,
        profile=profile,
    )
    if resolved is not None:
        return resolved
    return (resolve_runtime_layout(environ=environ).state / "runs").resolve()


def _number_text(value: float | int) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def build_engine_command(
    request: CollectionRequest,
    staging_dir: Path,
    *,
    layout: RuntimeLayout,
    cdp_url: str = DEFAULT_CDP_URL,
    exclude_file: Path | None = None,
) -> EngineCommand:
    staging = Path(staging_dir).expanduser().resolve()
    if request.search:
        script = layout.current / "scripts" / f"scrape_{request.platforms[0]}.py"
    else:
        script = layout.current / "scripts" / "scrape_all.py"
    script = script.resolve()
    interpreter = layout.python.expanduser().absolute()
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ConfigurationError(f"runtime python is missing or not executable: {interpreter}")
    if not script.is_file():
        raise ConfigurationError(f"runtime entrypoint is missing: {script}")

    argv = [str(interpreter), str(script)]
    if request.search:
        platform = request.platforms[0]
        search_count = request.platform_counts.get(platform, request.count)
        argv.extend(("--search", request.search, "--count", str(search_count)))
        argv.extend(("--platform-timeout", _number_text(request.platform_timeout)))
        if platform in request.platform_uids:
            argv.extend(("--uid", request.platform_uids[platform]))
        if platform == "xhs" and request.xhs_comments:
            argv.extend(("--comments", str(request.xhs_comments)))
    else:
        argv.extend(("--platform", ",".join(request.platforms), "--count", str(request.count)))
        argv.extend(("--platform-timeout", _number_text(request.platform_timeout)))
        for platform in request.platforms:
            if platform in request.platform_counts:
                argv.extend((f"--{platform}-count", str(request.platform_counts[platform])))
            if platform in request.platform_uids:
                argv.extend((f"--{platform}-uid", request.platform_uids[platform]))
        if request.complete:
            argv.append("--complete")
        if request.bilibili_complete:
            argv.append("--bilibili-complete")
        if request.xhs_complete:
            argv.append("--xhs-complete")
        if request.xhs_comments:
            argv.extend(("--xhs-comments", str(request.xhs_comments)))
        argv.append("--no-feishu")
    argv.extend(("--cdp-url", str(cdp_url)))
    if exclude_file is not None:
        argv.extend(("--exclude-file", str(exclude_file)))
    if request.allow_navigation:
        argv.append("--allow-navigation")
    if request.browser_assist != "off":
        argv.extend(("--browser-assist", request.browser_assist))
    if request.screenshot_mode != "off":
        argv.extend(("--screenshot-mode", request.screenshot_mode))
    argv.extend(("--format", "json", "--output", str(staging)))
    environment = {
        "MEDIA_MISSHER_HOME": str(layout.home),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    if "xhs" in request.platforms:
        environment["MEDIA_MISSHER_XHS_REPORT_DIR"] = str(staging)
    return EngineCommand(script=script, argv=tuple(argv), environment=environment)


def create_run_directory(data_root: Path, *, now: datetime | None = None) -> Path:
    root = Path(data_root).expanduser().resolve()
    root_existed = root.exists()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not root_existed:
        root.chmod(0o700)
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(tempfile.mkdtemp(prefix=f"run-{timestamp}-", dir=root))
    run_dir.chmod(0o700)
    return run_dir.resolve()


def _open_private_binary(path: Path):
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        return os.fdopen(descriptor, "wb")
    except Exception:
        os.close(descriptor)
        raise


def execute_engine(
    command: EngineCommand,
    *,
    timeout: float,
    run_dir: Path,
    progress_module=None,
    reporter=None,
) -> CompletedRun:
    if not math.isfinite(float(timeout)) or timeout <= 0:
        raise ConfigurationError("execution timeout must be greater than zero")
    evidence_dir = Path(run_dir).expanduser().resolve()
    if not evidence_dir.is_dir():
        raise ConfigurationError(f"run directory does not exist: {evidence_dir}")
    stdout_path = evidence_dir / "stdout.log"
    stderr_path = evidence_dir / "stderr.log"
    environment = os.environ.copy()
    environment.update({str(key): str(value) for key, value in command.environment.items()})
    # Ambient/override strings cannot waive the shared lock. The explicit
    # descriptors are owned by this invocation and validated again by the core.
    environment.pop("MEDIA_MISSHER_LEASE_FDS", None)
    if command.pass_fds:
        environment["MEDIA_MISSHER_LEASE_FDS"] = ",".join(str(fd) for fd in command.pass_fds)
    started = time.monotonic()
    engine_phase = reporter.start("engine") if reporter is not None else None
    timed_out = False
    risk_detected = threading.Event()
    interrupted_signal: int | None = None
    previous_signal_handlers: dict[int, object] = {}

    def process_group_exists(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def wait_for_process_group(process: subprocess.Popen, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while process_group_exists(process.pid):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            process.poll()
            time.sleep(min(0.02, remaining))
        process.poll()
        return True

    def terminate_process_group(process: subprocess.Popen, grace_seconds: float = 1.0):
        if process_group_exists(process.pid):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if not wait_for_process_group(process, grace_seconds):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                wait_for_process_group(process, grace_seconds)
        if process.poll() is None:
            process.wait(timeout=grace_seconds)

    def handle_shutdown_signal(signum, _frame):
        nonlocal interrupted_signal
        if interrupted_signal is None:
            interrupted_signal = signum

    def install_signal_handlers() -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous = signal.getsignal(signum)
            signal.signal(signum, handle_shutdown_signal)
            previous_signal_handlers[signum] = previous

    def restore_signal_handlers() -> None:
        for signum, previous in previous_signal_handlers.items():
            signal.signal(signum, previous)

    def copy_and_monitor(stream, destination, parse_progress=False):
        tail = ""
        def ordinary(chunk):
            nonlocal tail
            destination.write(chunk)
            destination.flush()
            tail = (tail + chunk.decode("utf-8", errors="replace"))[-1024:]
            if _has_risk_signal(tail):
                risk_detected.set()
        parser = progress_module.ProgressStream(reporter.relay, ordinary) if parse_progress and progress_module is not None and reporter is not None else None
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            if parser is None:
                ordinary(chunk)
            else:
                parser.feed(chunk)
        if parser is not None:
            parser.finish()

    with _open_private_binary(stdout_path) as stdout, _open_private_binary(
        stderr_path
    ) as stderr:
        process: subprocess.Popen | None = None
        readers: tuple[threading.Thread, ...] = ()
        try:
            install_signal_handlers()
            process = subprocess.Popen(
                list(command.argv),
                cwd=command.script.parent.parent,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
                pass_fds=command.pass_fds,
                bufsize=0,
            )
            readers = (
                threading.Thread(
                    target=copy_and_monitor,
                    args=(process.stdout, stdout),
                    daemon=True,
                ),
                threading.Thread(
                    target=copy_and_monitor,
                    args=(process.stderr, stderr, True),
                    daemon=True,
                ),
            )
            for reader in readers:
                reader.start()
            deadline = started + timeout
            while process.poll() is None:
                if interrupted_signal is not None or risk_detected.is_set():
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(0.02)
        finally:
            if process is not None:
                terminate_process_group(process)
            for reader in readers:
                reader.join(timeout=1)
            try:
                if reporter is not None:
                    state = "cancelled" if interrupted_signal is not None else "failed" if process is None or process.returncode != 0 or timed_out or risk_detected.is_set() else "completed"
                    try:
                        reporter.finish(engine_phase, state)
                    except Exception:
                        pass
            finally:
                restore_signal_handlers()
                if interrupted_signal is not None:
                    signal.raise_signal(interrupted_signal)
    assert process is not None
    return CompletedRun(
        returncode=process.returncode,
        stdout_path=stdout_path.resolve(),
        stderr_path=stderr_path.resolve(),
        timed_out=timed_out,
        risk_detected=risk_detected.is_set(),
        duration_seconds=time.monotonic() - started,
    )


def discover_current_json(run_dir: Path, *, started_ns: int) -> tuple[Path, ...]:
    root = Path(run_dir).expanduser().resolve()
    candidates: list[tuple[Path, Path]] = []
    for inner in root.glob("run-*"):
        if inner.is_symlink() or not inner.is_dir():
            continue
        resolved_inner = inner.resolve()
        if resolved_inner.parent != root or inner.stat().st_mtime_ns < started_ns:
            continue
        manifest = inner / "manifest.json"
        if manifest.is_symlink() or not manifest.is_file():
            continue
        resolved_manifest = manifest.resolve()
        if (
            resolved_manifest.parent != resolved_inner
            or manifest.stat().st_mtime_ns < started_ns
        ):
            continue
        candidates.append((resolved_inner, resolved_manifest))
    if len(candidates) != 1:
        raise ConfigurationError(
            f"expected exactly one fresh runtime run, found {len(candidates)}"
        )

    inner, manifest_path = candidates[0]

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ConfigurationError(
                    f"invalid runtime manifest: duplicate key: {key}"
                )
            value[key] = item
        return value

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid runtime manifest: {type(exc).__name__}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ConfigurationError("invalid runtime manifest: expected a JSON object")
    _validated_manifest_diagnostics(manifest)
    paths = manifest.get("paths")
    if not isinstance(paths, dict):
        raise ConfigurationError("invalid runtime manifest: paths must be a JSON object")
    platforms = manifest.get("platforms")
    if (
        not isinstance(platforms, dict)
        or any(platform not in PLATFORMS for platform in platforms)
    ):
        raise ConfigurationError("invalid runtime manifest: unexpected platform")
    allowed_artifacts = set(platforms)
    if "xhs" in platforms:
        allowed_artifacts.update(("xhs_report", "xhs_checkpoint"))
    unexpected_keys = set(paths) - allowed_artifacts
    if unexpected_keys:
        raise ConfigurationError(
            f"unexpected manifest path key: {', '.join(sorted(unexpected_keys))}"
        )
    for key, raw_name in paths.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ConfigurationError(f"invalid runtime manifest path for {key}")
        name = Path(raw_name)
        if name.is_absolute() or name.name != raw_name:
            raise ConfigurationError(f"unsafe runtime manifest path for {key}")
        if raw_name != f"{key}.json":
            raise ConfigurationError(
                f"unexpected runtime artifact name for {key}: {raw_name}"
            )
    if len(set(paths.values())) != len(paths):
        raise ConfigurationError("invalid runtime manifest: duplicate artifact path")
    for platform, status in platforms.items():
        if status == "complete" and platform not in paths:
            raise ConfigurationError(
                f"runtime manifest is missing a completed platform path: {platform}"
            )

    discovered = [manifest_path]
    for key, raw_name in paths.items():
        name = Path(raw_name)
        path = inner / name
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError(f"runtime artifact is missing or unsafe: {key}")
        resolved = path.resolve()
        if resolved.parent != inner or path.stat().st_mtime_ns < started_ns:
            raise ConfigurationError(f"runtime artifact is stale or unsafe: {key}")
        if key == "xhs_checkpoint":
            try:
                checkpoint = json.loads(
                    path.read_text(encoding="utf-8"),
                    object_pairs_hook=unique_object,
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ConfigurationError(
                    f"invalid XHS checkpoint: {type(exc).__name__}: {exc}"
                ) from exc
            if not isinstance(checkpoint, dict) or set(checkpoint) != {"items"}:
                raise ConfigurationError("invalid XHS checkpoint schema")
            checkpoint_items = checkpoint.get("items")
            if not isinstance(checkpoint_items, list) or any(
                not isinstance(item, dict)
                or set(item) != {"note_id", "observed_at"}
                or not isinstance(item.get("note_id"), str)
                or not item["note_id"].strip()
                or not (
                    item.get("observed_at") is None
                    or isinstance(item.get("observed_at"), str)
                )
                for item in checkpoint_items
            ):
                raise ConfigurationError("invalid XHS checkpoint items")
            continue
        discovered.append(resolved)
    return tuple(discovered)


def _normalize_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("records cannot contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    raise ValueError(f"record value is not JSON-compatible: {type(value).__name__}")


def normalize_records(records) -> list[dict]:
    if not isinstance(records, (list, tuple)):
        raise ValueError("records must be a list of JSON objects")
    normalized_source = []
    columns: list[str] = []
    seen = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"record {index} must be a JSON object")
        normalized = {str(key): _normalize_value(value) for key, value in record.items()}
        normalized_source.append(normalized)
        for key in normalized:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return [{key: record.get(key) for key in columns} for record in normalized_source]


_FORMAT_SUFFIX = {
    "json": ".json",
    "csv": ".csv",
    "jsonl": ".jsonl",
    "sqlite": ".sqlite",
}


def _output_path(output_base: Path, format_name: str) -> Path:
    if format_name not in _FORMAT_SUFFIX:
        raise ValueError(f"unsupported output format: {format_name}")
    base = Path(output_base).expanduser().resolve()
    suffix = _FORMAT_SUFFIX[format_name]
    return base if base.suffix == suffix else Path(f"{base}{suffix}")


def _prepare_private_parent(path: Path):
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not parent_existed:
        path.parent.chmod(0o700)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _open_private_text(path: Path, *, newline=None):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        return os.fdopen(descriptor, "w", encoding="utf-8", newline=newline)
    except Exception:
        os.close(descriptor)
        raise


def _create_private_file(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)


def write_output(records, format_name: str, output_base: Path) -> Path:
    normalized = normalize_records(records)
    path = _output_path(output_base, format_name)
    _prepare_private_parent(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        if format_name == "json":
            with _open_private_text(temporary) as handle:
                handle.write(json.dumps(normalized, ensure_ascii=False, indent=2))
        elif format_name == "jsonl":
            with _open_private_text(temporary) as handle:
                for record in normalized:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                    handle.write("\n")
        elif format_name == "csv":
            columns = list(normalized[0]) if normalized else []
            with _open_private_text(temporary, newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for record in normalized:
                    writer.writerow(
                        {
                            key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                            for key, value in record.items()
                        }
                    )
        else:
            columns = list(normalized[0]) if normalized else []
            _create_private_file(temporary)
            connection = sqlite3.connect(temporary)
            try:
                definitions = ", ".join(
                    f"{_quote_identifier(column)} TEXT" for column in columns
                )
                schema = '"_position" INTEGER PRIMARY KEY'
                if definitions:
                    schema = f"{schema}, {definitions}"
                connection.execute(f'CREATE TABLE "records" ({schema})')
                if columns:
                    names = ", ".join(_quote_identifier(column) for column in columns)
                    placeholders = ", ".join("?" for _ in columns)
                    for position, record in enumerate(normalized):
                        values = [
                            json.dumps(record[column], ensure_ascii=False, separators=(",", ":"))
                            for column in columns
                        ]
                        connection.execute(
                            f'INSERT INTO "records" ("_position", {names}) VALUES (?, {placeholders})',
                            [position, *values],
                        )
                connection.commit()
            finally:
                connection.close()
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path.resolve()


def read_output(path: Path, format_name: str) -> list[dict]:
    source = Path(path).expanduser().resolve()
    if format_name == "json":
        records = json.loads(source.read_text(encoding="utf-8"))
    elif format_name == "jsonl":
        records = [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif format_name == "csv":
        with source.open(encoding="utf-8", newline="") as handle:
            records = [
                {key: json.loads(value) for key, value in row.items()}
                for row in csv.DictReader(handle)
            ]
    elif format_name == "sqlite":
        connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            columns = [
                row[1]
                for row in connection.execute('PRAGMA table_info("records")')
                if row[1] != "_position"
            ]
            names = ", ".join(_quote_identifier(column) for column in columns)
            rows = connection.execute(
                f'SELECT {names} FROM "records" ORDER BY "_position"'
                if names
                else 'SELECT "_position" FROM "records" ORDER BY "_position"'
            ).fetchall()
            records = [
                {column: json.loads(value) for column, value in zip(columns, row)}
                for row in rows
            ]
        finally:
            connection.close()
    else:
        raise ValueError(f"unsupported output format: {format_name}")
    return normalize_records(records)


_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "environment",
    "env",
    "password",
    "proxy",
    "secret",
    "token",
    "xsec_token",
    "author_id",
    "author_sec_uid",
    "user_id",
    "open_id",
    "uid",
    "sec_uid",
    "account_id",
}
_SENSITIVE_CANONICAL_KEYS = {
    re.sub(r"[^a-z0-9]", "", alias) for alias in _SENSITIVE_KEYS
}
_SENSITIVE_MARKERS = (
    "token",
    "cookie",
    "password",
    "passwd",
    "secret",
    "credential",
    "authorization",
    "apikey",
    "sessionid",
    "sessionkey",
    "bearer",
    "csrf",
    "proxy",
)


def redact_for_summary(value, *, secrets: set[str] | None = None):
    configured_secrets = {item for item in (secrets or set()) if item}

    def redact(item):
        if isinstance(item, Mapping):
            cleaned = {}
            for key, child in item.items():
                normalized_key = str(key).strip().lower()
                canonical_key = re.sub(r"[^a-z0-9]", "", normalized_key)
                if canonical_key in _SENSITIVE_CANONICAL_KEYS or any(
                    marker in canonical_key for marker in _SENSITIVE_MARKERS
                ):
                    continue
                cleaned[str(key)] = redact(child)
            return cleaned
        if isinstance(item, (list, tuple)):
            return [redact(child) for child in item]
        if isinstance(item, str):
            cleaned = item
            for secret in configured_secrets:
                cleaned = cleaned.replace(secret, "[redacted]")
            parsed = urlsplit(cleaned)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                cleaned = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            return cleaned
        return item

    return redact(value)


def _platform_from_record(record: Mapping, path: Path) -> str | None:
    explicit = str(record.get("platform", "")).strip().lower()
    if explicit in PLATFORMS:
        return explicit
    name = path.name.lower()
    for platform in PLATFORMS:
        if name.startswith(f"{platform}_"):
            return platform
    key_platforms = (
        ("bvid", "bilibili"),
        ("dynamic_id", "bilibili"),
        ("note_id", "xhs"),
        ("aweme_id", "douyin"),
        ("mblog_id", "weibo"),
        ("tweet_id", "x"),
    )
    for key, platform in key_platforms:
        if record.get(key) is not None:
            return platform
    return None


#: Native identity keys per platform. ``native_id`` is the shared projection every
#: collector writes, so it is accepted as the last resort instead of silently
#: making a valid record look identity-less.
_NATIVE_ID_KEYS = {
    "bilibili": ("dynamic_id", "bvid", "native_id"),
    "xhs": ("note_id", "native_id"),
    "douyin": ("aweme_id", "native_id"),
    "weibo": ("mblog_id", "uid", "native_id"),
    "x": ("tweet_id", "native_id"),
}


def _record_identity(record: Mapping, platform: str) -> str | None:
    keys = _NATIVE_ID_KEYS[platform]
    for key in keys:
        if record.get(key) not in (None, ""):
            return f"{platform}:{key}:{record[key]}"
    return None


def _has_minimum_content(record: Mapping, platform: str) -> bool:
    link = record.get("link")
    return _record_identity(record, platform) is not None and bool(
        isinstance(link, str) and link.strip()
    )


def _parse_observed_ns(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)) and value > 0:
        numeric = float(value)
        if numeric < 10_000_000_000:
            return int(numeric * 1_000_000_000)
        if numeric < 10_000_000_000_000:
            return int(numeric * 1_000_000)
        if numeric < 10_000_000_000_000_000:
            return int(numeric * 1_000)
        return int(numeric)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1_000_000_000)


def _bilibili_complete(record: Mapping) -> bool:
    title = str(record.get("title") or "").strip()
    if title in {"", "无标题", "(无标题)", "动态"}:
        return False
    return bool(
        record.get("complete") is True
        and record.get("date")
        and all(record.get(key) is not None for key in ("liked", "comments", "shares", "collected"))
    )


_XHS_DETAIL_SOURCES = frozenset({"detail_api", "detail_html", "detail_cdp"})
_XHS_COMMENT_FIELDS = frozenset({"author", "text", "date", "liked"})


def _xhs_exact_detail_link(record: Mapping) -> bool:
    note_id = record.get("note_id")
    link = record.get("link")
    if not isinstance(note_id, str) or not note_id or not isinstance(link, str):
        return False
    parsed = urlsplit(link)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == "www.xiaohongshu.com"
        and parsed.path == f"/explore/{note_id}"
        and not parsed.query
        and not parsed.fragment
    )


def _xhs_metrics_are_current(record: Mapping, started_ns: int) -> bool:
    sources = record.get("metric_sources")
    observations = record.get("metric_observed_at")
    if not isinstance(sources, Mapping) or not isinstance(observations, Mapping):
        return False
    for field in ("liked", "comments", "collected", "shares"):
        value = record.get(field)
        if not (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            and sources.get(field) in _XHS_DETAIL_SOURCES
        ):
            return False
        observation_key = "raw_share_count" if field == "shares" else field
        observed_ns = _parse_observed_ns(
            observations.get(observation_key)
            if observation_key in observations
            else observations.get(field)
        )
        if observed_ns is None or observed_ns < started_ns:
            return False
    return True


def _xhs_comments_complete(record: Mapping, requested_comments: int) -> bool:
    if requested_comments <= 0:
        return True
    reported_requested = record.get("comments_requested")
    total_comments = record.get("comments")
    fetched_comments = record.get("comments_fetched")
    comments_data = record.get("comments_data")
    if not (
        isinstance(reported_requested, int)
        and not isinstance(reported_requested, bool)
        and reported_requested == requested_comments
        and isinstance(total_comments, int)
        and not isinstance(total_comments, bool)
        and total_comments >= 0
        and isinstance(fetched_comments, int)
        and not isinstance(fetched_comments, bool)
        and isinstance(comments_data, list)
    ):
        return False
    expected = min(requested_comments, total_comments)
    if fetched_comments != expected or len(comments_data) != expected:
        return False
    for comment in comments_data:
        if not isinstance(comment, Mapping) or set(comment) != _XHS_COMMENT_FIELDS:
            return False
        author = comment.get("author")
        body = comment.get("text")
        date = comment.get("date")
        liked = comment.get("liked")
        if not (
            (author is None or isinstance(author, str))
            and (body is None or isinstance(body, str))
            and (date is None or isinstance(date, str))
            and (
                liked is None
                or (isinstance(liked, int) and not isinstance(liked, bool) and liked >= 0)
            )
            and (
                isinstance(author, str) and bool(author.strip())
                or isinstance(body, str) and bool(body.strip())
            )
        ):
            return False
    return True


def _xhs_complete(
    record: Mapping,
    started_ns: int,
    requested_comments: int = 0,
) -> bool:
    observed_ns = _parse_observed_ns(
        record.get("engagement_observed_at") or record.get("metric_observed_at")
    )
    source = str(record.get("engagement_source") or "").lower()
    precision = str(record.get("date_precision") or "").lower()
    raw_detail_business_fields = record.get("detail_business_fields")
    detail_business_fields = {
        str(field)
        for field in (
            raw_detail_business_fields
            if isinstance(raw_detail_business_fields, (list, tuple, set))
            else ()
        )
        if isinstance(field, str)
    }
    has_detail_media = bool(
        record.get("images") or record.get("video_urls") or record.get("cover")
    )
    return bool(
        record.get("complete") is True
        and record.get("detail_attempted") is True
        and record.get("detail_completed") is True
        and isinstance(record.get("missing_fields"), list)
        and not record["missing_fields"]
        and _xhs_exact_detail_link(record)
        and record.get("date")
        and precision not in {"", "unknown", "estimated", "estimated_day"}
        and record.get("date_estimated") is False
        and record.get("date_source") == "detail_api"
        and record.get("engagement_fresh") is True
        and source in _XHS_DETAIL_SOURCES
        and observed_ns is not None
        and observed_ns >= started_ns
        and _xhs_metrics_are_current(record, started_ns)
        and all(
            record.get(key) is not None
            for key in ("liked", "comments", "collected", "shares")
        )
        and str(record.get("desc") or "").strip()
        and str(record.get("author") or "").strip()
        and {"desc", "author", "media"}.issubset(detail_business_fields)
        and has_detail_media
        and _xhs_comments_complete(record, requested_comments)
    )


def _screenshot_native_id(record: Mapping, platform: str) -> str | None:
    keys = (
        ("bvid", "dynamic_id")
        if platform == "bilibili"
        else _NATIVE_ID_KEYS[platform]
    )
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and _SAFE_SCREENSHOT_ID.fullmatch(value):
            return value
    return None


def _validate_screenshot_record(
    record: dict,
    *,
    platform: str,
    source_json: Path,
    request_mode: str,
    started_ns: int,
) -> str | None:
    present = {
        field for field in _SCREENSHOT_FIELDS if record.get(field) is not None
    }
    required = request_mode == "all" or (
        request_mode == "opened" and record.get("detail_attempted") is True
    )
    if not present:
        return "screenshot evidence is missing" if required else None

    status = record.get("screenshot_status")
    if status == "failed":
        if present != {"screenshot_status", "screenshot_error_code"} or record.get(
            "screenshot_error_code"
        ) != "capture-failed":
            return "screenshot failure metadata is invalid"
        return "screenshot capture failed"
    if status != "complete" or present != _SCREENSHOT_COMPLETE_FIELDS:
        return "screenshot metadata group is incomplete"
    if request_mode == "off" or record.get("screenshot_mode") != request_mode:
        return "screenshot request mode does not match"
    if record.get("screenshot_capture_kind") not in {
        "article",
        "full_page_fallback",
    }:
        return "screenshot capture kind is invalid"

    observed_at = record.get("screenshot_observed_at")
    if not isinstance(observed_at, str):
        return "screenshot observation time is invalid"
    try:
        parsed_observed_at = datetime.fromisoformat(
            observed_at.replace("Z", "+00:00")
        )
    except ValueError:
        return "screenshot observation time is invalid"
    offset = parsed_observed_at.utcoffset()
    if (
        parsed_observed_at.tzinfo is None
        or offset is None
        or offset.total_seconds() != 0
        or int(parsed_observed_at.timestamp() * 1_000_000_000) < started_ns
    ):
        return "screenshot observation time is invalid"

    native_id = _screenshot_native_id(record, platform)
    raw_path = record.get("screenshot_path")
    expected_path = (
        f"screenshots/{platform}-{native_id}.png" if native_id is not None else None
    )
    if (
        not isinstance(raw_path, str)
        or expected_path is None
        or raw_path != expected_path
    ):
        return "screenshot path is invalid"
    relative = Path(raw_path)
    if relative.is_absolute() or len(relative.parts) != 2:
        return "screenshot path is invalid"

    source_root = source_json.parent.resolve()
    screenshot_dir = source_json.parent / "screenshots"
    screenshot = source_json.parent / relative
    if (
        not source_json.parent.name.startswith("run-")
        or screenshot_dir.is_symlink()
        or screenshot.is_symlink()
    ):
        return "screenshot path is unsafe"
    try:
        resolved = screenshot.resolve(strict=True)
        resolved.relative_to(source_root)
    except (OSError, ValueError):
        return "screenshot path is unsafe"
    if resolved.parent != (source_root / "screenshots"):
        return "screenshot path is unsafe"

    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(screenshot, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_mtime_ns < started_ns
            or metadata.st_size > MAX_SCREENSHOT_BYTES
        ):
            return "screenshot file is stale or unsafe"
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            payload = handle.read(MAX_SCREENSHOT_BYTES + 1)
    except OSError:
        return "screenshot file cannot be read safely"
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > MAX_SCREENSHOT_BYTES or not payload.startswith(
        _PNG_SIGNATURE
    ):
        return "screenshot file is not a bounded PNG"

    expected_digest = record.get("screenshot_sha256")
    if (
        not isinstance(expected_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        or hashlib.sha256(payload).hexdigest() != expected_digest
    ):
        return "screenshot digest does not match"

    record["screenshot_path"] = f"{source_json.parent.name}/{raw_path}"
    return None


def validate_run(paths, request: CollectionRequest, started_ns: int) -> dict:
    errors: list[str] = []
    evidence: list[str] = []
    diagnostics: list[dict[str, object]] = []
    collected: dict[str, list[dict]] = {platform: [] for platform in request.platforms}
    risk_stopped = False
    for raw_path in paths:
        unresolved = Path(raw_path).expanduser()
        if unresolved.is_symlink():
            path = unresolved.absolute()
            errors.append(f"stale or unsafe evidence: {path}")
            continue
        path = unresolved.resolve()
        try:
            stat_result = path.stat()
        except OSError as exc:
            errors.append(f"evidence cannot be read: {path}: {exc}")
            continue
        if path.is_symlink() or stat_result.st_mtime_ns < started_ns:
            errors.append(f"stale or unsafe evidence: {path}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON evidence: {path}: {exc}")
            continue
        if isinstance(payload, dict):
            status = str(payload.get("status", "")).lower().replace("_", "-")
            if path.name == "manifest.json":
                try:
                    safe_diagnostics = _validated_manifest_diagnostics(payload)
                except ConfigurationError:
                    errors.append(
                        f"runtime manifest has an invalid diagnostic contract: {path}"
                    )
                    continue
                diagnostics.append(
                    {
                        "path": str(path),
                        "status": status or "unknown",
                        "platforms": safe_diagnostics,
                    }
                )
                counts_payload = payload.get("counts")
                paths_payload = payload.get("paths")
                platforms_payload = payload.get("platforms")
                selected = set(request.platforms)
                if not isinstance(counts_payload, dict) or set(counts_payload) != selected:
                    errors.append(f"runtime manifest has invalid counts: {path}")
                elif any(
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                    for value in counts_payload.values()
                ):
                    errors.append(f"runtime manifest has invalid counts: {path}")
                if not isinstance(paths_payload, dict) or any(
                    not isinstance(key, str)
                    or not isinstance(value, str)
                    or not value
                    or Path(value).is_absolute()
                    or Path(value).name != value
                    for key, value in (
                        paths_payload.items() if isinstance(paths_payload, dict) else ()
                    )
                ):
                    errors.append(f"runtime manifest has invalid paths: {path}")
                allowed_platform_statuses = {
                    "complete",
                    "shortfall",
                    "incomplete",
                    "failed",
                    "risk-stopped",
                    "not-run",
                }
                if (
                    not isinstance(platforms_payload, dict)
                    or set(platforms_payload) != selected
                    or any(
                        not isinstance(value, str)
                        or value not in allowed_platform_statuses
                        for value in platforms_payload.values()
                    )
                ):
                    errors.append(f"runtime manifest has invalid platform statuses: {path}")
                elif any(value == "risk-stopped" for value in platforms_payload.values()):
                    risk_stopped = True
                elif any(
                    value in {"shortfall", "incomplete", "failed", "not-run"}
                    for value in platforms_payload.values()
                ):
                    errors.append(f"runtime manifest reports incomplete collection: {path}")
                if status == "risk-stopped":
                    risk_stopped = True
                elif status not in {"complete", "failed"}:
                    errors.append(f"runtime manifest has invalid status: {path}: {status}")
                elif status == "failed":
                    errors.append(f"runtime manifest reports failure: {path}")
                continue
            if status in {"risk", "risk-stopped", "locked", "blocked", "cooldown"}:
                risk_stopped = True
                diagnostics.append({"path": str(path), "status": status})
                continue
            if {"status", "started_at", "finished_at", "final_items"}.issubset(payload):
                diagnostics.append({"path": str(path), "status": status or "unknown"})
                if status not in {"complete", "completed", "success", "ok"}:
                    errors.append(f"diagnostic report has non-success status: {path}: {status}")
                continue
            errors.append(f"unexpected top-level JSON object: {path}")
            continue
        if not isinstance(payload, list):
            errors.append(f"unexpected top-level JSON type: {path}")
            continue
        try:
            records = normalize_records(payload)
        except ValueError as exc:
            errors.append(f"invalid records in {path}: {exc}")
            continue
        accepted_record = False
        for record in records:
            platform = _platform_from_record(record, path)
            if platform not in request.platforms:
                errors.append(f"unexpected or unknown platform record in {path}")
                continue
            if not _has_minimum_content(record, platform):
                errors.append(f"record lacks a native content identity or link in {path}")
                continue
            screenshot_error = _validate_screenshot_record(
                record,
                platform=platform,
                source_json=path,
                request_mode=request.screenshot_mode,
                started_ns=started_ns,
            )
            if screenshot_error is not None:
                errors.append(f"{platform} screenshot validation failed: {screenshot_error}")
            collected[platform].append(record)
            accepted_record = True
        if accepted_record:
            evidence.append(str(path))

    deduplicated: dict[str, list[dict]] = {}
    for platform, records in collected.items():
        unique = {}
        for record in records:
            identity = _record_identity(record, platform)
            if identity is not None:
                unique.setdefault(identity, record)
        deduplicated[platform] = list(unique.values())

    counts = {platform: len(records) for platform, records in deduplicated.items()}
    for platform in request.platforms:
        expected = request.platform_counts.get(platform, request.count)
        if expected > 0 and counts[platform] < expected:
            errors.append(f"{platform}: expected {expected} records, found {counts[platform]}")

    if "bilibili" in request.platforms and (request.complete or request.bilibili_complete):
        incomplete = sum(not _bilibili_complete(record) for record in deduplicated["bilibili"])
        if incomplete:
            errors.append(f"Bilibili complete validation failed for {incomplete} records")
    if "xhs" in request.platforms and (request.complete or request.xhs_complete):
        incomplete = sum(
            not _xhs_complete(record, started_ns, request.xhs_comments)
            for record in deduplicated["xhs"]
        )
        if incomplete:
            errors.append(f"XHS complete validation failed for {incomplete} records")

    records = normalize_records(
        [record for platform in request.platforms for record in deduplicated[platform]]
    )
    samples = [
        {"platform": platform, "field_count": len(record)}
        for platform in request.platforms
        for record in deduplicated[platform]
    ][:3]
    if risk_stopped:
        status = "risk-stopped"
    elif not records:
        status = "failed"
    elif errors:
        status = "partial"
    else:
        status = "success"
    return {
        "status": status,
        "counts": counts,
        "records": records,
        "evidence": evidence,
        "diagnostics": diagnostics,
        "samples": samples,
        "errors": errors,
    }


_RISK_PATTERN = re.compile(
    r"(?i)(?:\b(?:403|429|461|471|999|risk|locked|blocked)\b|\bcooldown(?:\b|_))"
)
_RUNTIME_PRECONDITION_PATTERN = re.compile(
    r"\Amedia-missher-diagnostic "
    r"platform=(bilibili|xhs|douyin|weibo) "
    r"kind=precondition code=("
    + "|".join(re.escape(code) for code in sorted(_SAFE_PRECONDITION_CODES))
    + r")\r?\n?\Z"
)


def _has_risk_signal(text: str) -> bool:
    # Local start guards are already stopped, structured preconditions. Preserve
    # the diagnostic exit instead of racing it with another termination signal.
    lines = [line for line in text.splitlines() if _RUNTIME_PRECONDITION_PATTERN.fullmatch(line) is None]
    return _RISK_PATTERN.search("\n".join(lines)) is not None


def _runtime_precondition_diagnostics(
    *, returncode: int, stderr: str
) -> dict[str, dict[str, str]] | None:
    if returncode != 78:
        return None
    lines = stderr.splitlines()
    if not 1 <= len(lines) <= 4:
        return None
    diagnostics = {}
    for line in lines:
        match = _RUNTIME_PRECONDITION_PATTERN.fullmatch(line)
        if match is None or match.group(1) in diagnostics:
            return None
        diagnostics[match.group(1)] = {"kind": "precondition", "code": match.group(2)}
    return diagnostics


def _recover_current_snapshot(run_dir: Path, started_ns: int) -> None:
    """Materialize only this stopped engine's last atomic committed envelope."""
    from media_missher_history import HistoryError, load_run
    candidates = [path for path in run_dir.glob("run-*/committed.json") if path.is_file() or path.is_symlink()]
    if not candidates:
        return
    if len(candidates) != 1 or candidates[0].is_symlink() or candidates[0].stat().st_mtime_ns < started_ns:
        raise ConfigurationError("unsafe current committed snapshot")
    try:
        loaded = load_run(run_dir.parent, run_dir.name)
    except HistoryError as error:
        raise ConfigurationError("current committed snapshot is invalid") from error
    if loaded["context"] is None or loaded["context"]["started_ns"] != started_ns:
        raise ConfigurationError("current committed snapshot identity mismatch")
    artifacts = loaded["committed_artifacts"]
    inner = candidates[0].parent
    payloads = {loaded["manifest"]["paths"][key]: value for key, value in artifacts.items()}
    payloads["manifest.json"] = loaded["manifest"]
    for name, value in payloads.items():
        target = inner / name
        if target.is_symlink():
            raise ConfigurationError("unsafe current projection path")
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if target.exists():
            target_stat = _owned_private_stat(target, "current projection")
            if target_stat.st_mtime_ns >= started_ns and target.read_bytes() == payload:
                continue
        descriptor, temporary = tempfile.mkstemp(prefix=".restore-", dir=inner)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)


def _run_collection_request_unlocked(
    request: CollectionRequest,
    *,
    layout: RuntimeLayout,
    data_root: Path,
    cdp_url: str = DEFAULT_CDP_URL,
    preflight_runner: Callable = None,
    execution_timeout: float | None = None,
    command_environment: Mapping[str, str] | None = None,
    context_request: CollectionRequest | None = None,
    profile_digest: str | None = None,
    continuation: Mapping | None = None,
    collection_fds: tuple[int, ...] = (),
) -> dict:
    from media_missher_history import HistoryError, write_context
    from media_missher_progress import load_progress
    try:
        progress_module = load_progress(layout.current)
    except (OSError, ValueError, ImportError, SyntaxError):
        result = _preflight_failure("installed progress module unavailable or invalid", checks={"progress_module": False})
        result["preflight"]["code"] = "progress-module-invalid"
        return result
    progress = progress_module.ProgressRecorder()
    run_phase = progress.start("run")
    preflight_phase = progress.start("controller-preflight")

    def finish_summary(summary):
        progress.finish(run_phase, "completed" if summary["status"] == "success" else "failed")
        summary["phase_timings"] = list(progress.timings)
        summary["phase_timings_persisted"] = progress.path is not None and not progress.storage_failed
        return summary
    if preflight_runner is None or preflight_runner is run_preflight:
        preflight_report = _run_preflight_unlocked(
            layout,
            live=True,
            cdp_url=cdp_url,
            timeout=10.0,
        )
    else:
        preflight_report = preflight_runner(
            layout,
            live=True,
            cdp_url=cdp_url,
            timeout=10.0,
        )
    progress.finish(preflight_phase, "completed" if preflight_report.get("status") == "ok" else "failed")
    if preflight_report.get("status") != "ok":
        return finish_summary({
            "status": "preflight-failed",
            "run_dir": None,
            "evidence": [],
            "errors": list(preflight_report.get("errors", [])),
            "preflight": preflight_report,
        })

    run_dir = create_run_directory(data_root)
    progress.bind_path(run_dir / "phase-timings.json")
    # Compare evidence mtimes to a timestamp from the same filesystem. Some
    # filesystems can report a newly-created file slightly behind the process
    # wall clock even though it was written afterwards. The run directory is
    # unique, private, and created immediately before this cutoff.
    started_ns = run_dir.stat().st_mtime_ns
    try:
        version_path = layout.current / "VERSION"
        version = version_path.read_text(encoding="ascii").strip() if version_path.is_file() else "unknown"
        write_context(
            run_dir, context_request or request, profile_digest or _profile_identity(layout, cdp_url), version,
            parent_run_id=continuation["parent_run_id"] if continuation else None,
        )
        exclude_file = None
        if continuation:
            exclude_file = run_dir / "continuation.json"
            with _open_private_binary(exclude_file) as handle:
                handle.write(json.dumps({"schema": 1, "platforms": {platform: continuation["skip_ids"][platform] for platform in request.platforms}}, separators=(",", ":")).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
        command = build_engine_command(
            request, run_dir, layout=layout, cdp_url=cdp_url, exclude_file=exclude_file
        )
        if command_environment:
            command = command.with_environment(command_environment)
        command = replace(command, pass_fds=collection_fds)
        if execution_timeout is None:
            per_platform = request.platform_timeout if request.platform_timeout > 0 else 3600.0
            execution_timeout = per_platform * len(request.platforms) + 60.0
        completed = execute_engine(command, timeout=execution_timeout, run_dir=run_dir, progress_module=progress_module, reporter=progress)
    except (ConfigurationError, HistoryError, OSError, subprocess.SubprocessError) as exc:
        return finish_summary({
            "status": "failed",
            "run_dir": str(run_dir),
            "evidence": [],
            "errors": [str(exc)],
            "preflight": preflight_report,
        })
    validation_phase = progress.start("validation")
    feishu_artifacts = tuple(run_dir.glob("feishu_*"))
    stdout = completed.stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = completed.stderr_path.read_text(encoding="utf-8", errors="replace")
    combined_log = f"{stdout}\n{stderr}"
    runtime_preflight_diagnostics = _runtime_precondition_diagnostics(
        returncode=completed.returncode,
        stderr=stderr,
    )
    discovery_errors: list[str] = []
    try:
        _recover_current_snapshot(run_dir, started_ns)
        evidence = discover_current_json(run_dir, started_ns=started_ns)
    except (ConfigurationError, OSError) as exc:
        evidence = ()
        discovery_errors.append(str(exc))
    validation = validate_run(evidence, request, started_ns)
    errors = list(discovery_errors)
    if feishu_artifacts:
        errors.append("unexpected Feishu artifact was generated")
    if completed.timed_out:
        errors.append("engine execution timed out")
    if completed.returncode != 0:
        errors.append(f"engine exited with status {completed.returncode}")
    errors.extend(validation["errors"])
    progress.finish(validation_phase, "completed" if validation["status"] == "success" else "failed")
    if runtime_preflight_diagnostics is not None:
        errors = ["runtime platform preflight failed"]
        status = "preflight-failed"
    elif (
        completed.risk_detected
        or _has_risk_signal(combined_log)
        or validation["status"] == "risk-stopped"
    ):
        status = "risk-stopped"
    elif feishu_artifacts:
        status = "failed"
    elif completed.timed_out or completed.returncode != 0:
        status = "partial" if validation["records"] else "failed"
    else:
        status = validation["status"]

    if status == "risk-stopped" and "xhs" in request.platforms:
        # The output monitor may have stopped the engine before it could latch
        # risk itself. The engine is now reaped; retain both controller leases
        # while the same installed policy records that restrictive fallback.
        try:
            pause = subprocess.run(
                [str(layout.python), str(layout.current / "scripts" / "xhs_safety.py"), "--record-risk", "risk-signal"],
                env={**os.environ, "MEDIA_MISSHER_HOME": str(layout.home), "PYTHONDONTWRITEBYTECODE": "1", "MEDIA_MISSHER_LEASE_FDS": ",".join(str(fd) for fd in collection_fds)},
                pass_fds=collection_fds,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5.0, check=False,
            )
            if pause.returncode != 0:
                errors.append("xhs risk pause could not be persisted; local safety state requires inspection")
        except (OSError, subprocess.SubprocessError):
            errors.append("xhs risk pause could not be persisted; local safety state requires inspection")

    output_phase = progress.start("output")
    outputs = list(validation["evidence"]) if request.output_format == "json" else []
    if (
        request.output_format != "json"
        and validation["records"]
        and status in {"success", "partial"}
    ):
        try:
            outputs.append(
                str(
                    write_output(
                        validation["records"],
                        request.output_format,
                        run_dir / "validated",
                    )
                )
            )
        except (OSError, ValueError, sqlite3.Error) as exc:
            errors.append(f"output conversion failed: {exc}")
            status = "partial" if validation["records"] else "failed"

    validation_summary = {key: value for key, value in validation.items() if key != "records"}
    summary = {
        "status": status,
        "run_dir": str(run_dir),
        "evidence": list(validation["evidence"]),
        "outputs": outputs,
        "errors": errors,
        "returncode": completed.returncode,
        "timed_out": completed.timed_out,
        "duration_seconds": round(completed.duration_seconds, 3),
        "stdout_path": str(completed.stdout_path),
        "stderr_path": str(completed.stderr_path),
        "preflight": preflight_report,
        "validation": validation_summary,
    }
    if runtime_preflight_diagnostics is not None:
        summary["diagnostics"] = runtime_preflight_diagnostics
    summary["safety_limits"] = {"xhs_batch_notes": 10, "xhs_batch_pages": 3, "xhs_batch_interval_seconds": 600} if "xhs" in request.platforms else {}
    if continuation:
        summary["continuation"] = {
            "parent_run_id": continuation["parent_run_id"],
            "prior_counts": continuation["prior_counts"],
            "new_counts": validation["counts"],
            "requested_counts": continuation["requested_counts"],
        }
    if status != "preflight-failed":
        from media_missher_history import _write_json_exclusive
        try:
            _write_json_exclusive(run_dir / "run-result.json", {"schema": 1, "status": status})
        except (HistoryError, OSError) as error:
            errors.append(f"run finalization failed: {type(error).__name__}")
            summary["status"] = "risk-stopped" if status == "risk-stopped" else "partial" if validation["records"] else "failed"
    progress.finish(output_phase, "completed" if summary["status"] == "success" else "failed")
    return finish_summary(summary)


def _preflight_failure(error: str, *, checks: Mapping[str, bool]) -> dict:
    code = (
        "runtime-version-mismatch" if checks.get("runtime_version") is False
        else "collection-busy" if checks.get("collection_lease") is False and error == "another Media@Missher collection is already running"
        else "platform-risk-latched" if checks.get("collection_lease") is False and error == "platform-risk-latched"
        else "shared-state-invalid" if checks.get("collection_lease") is False
        else None
    )
    return {
        "status": "preflight-failed",
        "run_dir": None,
        "evidence": [],
        "errors": [error],
        "preflight": {
            "status": "failed",
            "checks": dict(checks),
            "errors": [error],
            **({"code": code} if code is not None else {}),
        },
    }


def _profile_identity(layout: RuntimeLayout, cdp_url: str, profile: Mapping | None = None) -> str:
    """Bind continuation to effective local configuration without retaining it."""
    value = {"runtime_home": str(layout.home.expanduser().absolute()), "cdp_url": cdp_url, "profile": dict(profile or {})}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def run_collection_request(
    request: CollectionRequest,
    *,
    layout: RuntimeLayout,
    data_root: Path,
    cdp_url: str = DEFAULT_CDP_URL,
    preflight_runner: Callable = None,
    execution_timeout: float | None = None,
    command_environment: Mapping[str, str] | None = None,
    resume_run: str | None = None,
    profile_digest: str | None = None,
) -> dict:
    from media_missher_history import HistoryError, prepare_continuation
    if not request.search:
        missing_uids = [
            platform
            for platform in request.platforms
            if platform not in request.platform_uids
        ]
        if missing_uids:
            error = f"creator UID is required for: {', '.join(missing_uids)}"
            return _preflight_failure(error, checks={"creator_uids": False})
    try:
        with _runtime_lease(layout, timeout=10.0):
            version_report = runtime_version_check(layout)
            if not version_report["matches"]:
                failure = _preflight_failure(
                    _version_error(version_report),
                    checks={"runtime_lease": True, "release": True, "runtime_version": False},
                )
                failure["preflight"]["runtime_version"] = version_report
                return failure
            try:
                with _collection_lease(layout) as collection_lease:
                    digest = profile_digest or _profile_identity(layout, cdp_url)
                    continuation = None
                    active_request = request
                    if resume_run is not None:
                        try:
                            continuation = prepare_continuation(data_root, resume_run, request, digest)
                            remaining = {platform: count for platform, count in continuation["remaining_counts"].items() if count > 0}
                            active_request = replace(
                                request, platforms=tuple(remaining), platform_counts=remaining,
                                platform_uids={platform: uid for platform, uid in request.platform_uids.items() if platform in remaining},
                                complete=request.complete and bool({"bilibili", "xhs"}.intersection(remaining)),
                                bilibili_complete=request.bilibili_complete and "bilibili" in remaining,
                                xhs_complete=request.xhs_complete and "xhs" in remaining,
                                xhs_comments=request.xhs_comments if "xhs" in remaining else 0,
                            )
                        except HistoryError as error:
                            return _preflight_failure(str(error), checks={"continuation": False})
                    return _run_collection_request_unlocked(
                        active_request,
                        layout=layout,
                        data_root=data_root,
                        cdp_url=cdp_url,
                        preflight_runner=preflight_runner,
                        execution_timeout=execution_timeout,
                        command_environment=command_environment,
                        context_request=request,
                        profile_digest=digest,
                        continuation=continuation,
                        collection_fds=collection_lease.pass_fds,
                    )
            except _CollectionLeaseError as exc:
                return _preflight_failure(
                    str(exc),
                    checks={
                        "runtime_lease": True,
                        "release": True,
                        "collection_lease": False,
                    },
                )
    except _RuntimeLeaseError as exc:
        return _preflight_failure(
            str(exc),
            checks={
                "runtime_lease": exc.lease_acquired,
                "release": False,
            },
        )


def _cdp_version_url(cdp_url: str) -> str:
    normalized = cdp_url.rstrip("/")
    if normalized.endswith("/json/version"):
        return normalized
    return f"{normalized}/json/version"


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _probe_state_writable(state: Path) -> tuple[bool, str | None]:
    descriptor: int | None = None
    probe: Path | None = None
    error: str | None = None
    try:
        descriptor, raw_probe = tempfile.mkstemp(prefix=".preflight-", dir=state)
        probe = Path(raw_probe)
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, b"media-missher-preflight\n")
        os.fsync(descriptor)
    except OSError as exc:
        error = f"runtime state write probe failed: {type(exc).__name__}: {exc}"
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                error = f"runtime state write probe close failed: {type(exc).__name__}: {exc}"
        if probe is not None:
            try:
                probe.unlink()
            except OSError as exc:
                error = f"runtime state write probe cleanup failed: {type(exc).__name__}: {exc}"
    return error is None, error


def _validated_preflight_timeout(timeout: float) -> float:
    if isinstance(timeout, bool):
        raise ConfigurationError("timeout must be finite and greater than zero")
    try:
        parsed = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("timeout must be finite and greater than zero") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ConfigurationError("timeout must be finite and greater than zero")
    return parsed


def runtime_version_check(layout: RuntimeLayout) -> dict:
    """One bounded local check, shared by passive preflight and collection."""
    result = {"current": "unavailable", "required": REQUIRED_RUNTIME_VERSION, "matches": False}
    try:
        path = layout.current / "VERSION"
        _reject_symlink_components(path, "runtime version")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 32 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
                return result
            value = os.read(descriptor, 33)
            # Never reflect arbitrary file contents into model-facing output.
            if re.fullmatch(rb"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\n?", value):
                result["current"] = value.decode("ascii").rstrip("\n")
                result["matches"] = result["current"] == REQUIRED_RUNTIME_VERSION
        finally:
            os.close(descriptor)
    except (OSError, ConfigurationError):
        pass
    return result


def _version_error(report: Mapping) -> str:
    return f"runtime {report['required']} is required; current: {report['current']}; install the matching candidate before collection"


def _run_preflight_unlocked(
    layout: RuntimeLayout,
    *,
    live: bool,
    cdp_url: str = DEFAULT_CDP_URL,
    timeout: float = 10.0,
    urlopen: Callable | None = None,
) -> dict:
    timeout = _validated_preflight_timeout(timeout)
    if not isinstance(layout, RuntimeLayout):
        raise ConfigurationError("runtime layout is required")
    version_report = runtime_version_check(layout)
    if not version_report["matches"]:
        return {
            "status": "failed", "runtime_home": str(layout.home),
            "checks": {"runtime_lease": True, "release": True, "runtime_version": False},
            "code": "runtime-version-mismatch",
            "runtime_version": version_report, "errors": [_version_error(version_report)],
        }
    home = layout.home.expanduser().absolute()
    current = layout.current.expanduser().absolute()
    python = layout.python.expanduser().absolute()
    state = layout.state.expanduser().absolute()
    entrypoints = tuple(current / "scripts" / name for name in RUNTIME_ENTRYPOINTS)
    exact_layout = (
        current == (home / "current").absolute()
        and python == (home / "venv" / "bin" / "python").absolute()
        and state == (home / "state").absolute()
    )
    safe_boundaries = (
        not home.is_symlink()
        and _path_within(current, home)
        and _path_within(home / "venv", home)
        and _path_within(state, home)
    )
    state_private = False
    if state.is_dir() and not state.is_symlink():
        try:
            state_stat = state.stat()
            state_private = stat.S_IMODE(state_stat.st_mode) == 0o700
            if hasattr(os, "getuid"):
                state_private = state_private and state_stat.st_uid == os.getuid()
        except OSError:
            state_private = False
    entrypoints_present = all(
        entrypoint.is_file() and _path_within(entrypoint, current)
        for entrypoint in entrypoints
    )
    state_writable = False
    state_probe_error: str | None = None
    if state_private and safe_boundaries:
        state_writable, state_probe_error = _probe_state_writable(state)
    checks = {
        "runtime_lease": True,
        "release": True,
        "runtime_version": True,
        "layout": exact_layout and safe_boundaries,
        "runtime_home": home.is_dir(),
        "current": current.is_dir(),
        "python": python.is_file() and os.access(python, os.X_OK),
        "state": state.is_dir(),
        "state_private": state_private,
        "state_writable": state_writable,
        "entrypoints": entrypoints_present,
        "python_version": False,
        "playwright": False,
        "entrypoint_help": False,
    }
    errors: list[str] = []
    if not checks["layout"]:
        errors.append("runtime layout paths do not match the shared-home contract")
    if not checks["runtime_home"]:
        errors.append(f"runtime home is not a directory: {home}")
    if not checks["current"]:
        errors.append(f"current runtime is not a directory: {current}")
    if not checks["python"]:
        errors.append(f"runtime python is missing or not executable: {python}")
    if not checks["state"]:
        errors.append(f"runtime state is not a directory: {state}")
    if checks["state"] and not checks["state_private"]:
        errors.append(f"runtime state must be owned by the current user with mode 0700: {state}")
    if checks["state"] and not checks["state_writable"]:
        errors.append(state_probe_error or f"runtime state is not safely writable: {state}")
    for entrypoint in entrypoints:
        if not entrypoint.is_file() or not _path_within(entrypoint, current):
            errors.append(f"runtime entrypoint is missing: {entrypoint}")

    if checks["python"]:
        try:
            version_result = subprocess.run(
                [
                    str(python),
                    "-c",
                    "import sys; print('.'.join(str(part) for part in sys.version_info[:3]))",
                ],
                cwd=current if current.is_dir() else home,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            version_parts = tuple(
                int(part) for part in version_result.stdout.strip().split(".")
            )
            checks["python_version"] = (
                version_result.returncode == 0
                and len(version_parts) >= 2
                and version_parts[:2] in {(3, 11), (3, 12)}
            )
            if not checks["python_version"]:
                errors.append("runtime Python 3.11 or 3.12 is required for the pinned dependencies")
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            errors.append(f"runtime Python version probe failed: {type(exc).__name__}: {exc}")
        try:
            playwright_result = subprocess.run(
                [str(python), "-c", "import playwright"],
                cwd=current if current.is_dir() else home,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            checks["playwright"] = playwright_result.returncode == 0
            if not checks["playwright"]:
                errors.append("runtime Python cannot import Playwright")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"Playwright import probe failed: {type(exc).__name__}: {exc}")

    if checks["python"] and checks["entrypoints"] and checks["current"]:
        help_checks = []
        for entrypoint in entrypoints:
            try:
                completed = subprocess.run(
                    [str(python), str(entrypoint), "--help"],
                    cwd=current,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                help_checks.append(completed.returncode == 0)
                if completed.returncode != 0:
                    errors.append(
                        f"entrypoint --help exited with status {completed.returncode}: {entrypoint}"
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                help_checks.append(False)
                errors.append(
                    f"entrypoint --help failed: {entrypoint}: {type(exc).__name__}: {exc}"
                )
        checks["entrypoint_help"] = all(help_checks)

    cdp: dict[str, str | None] | None = None
    if live:
        checks["cdp"] = False
        opener = urlopen or urllib.request.urlopen
        request = urllib.request.Request(
            _cdp_version_url(cdp_url),
            headers={"Accept": "application/json"},
        )
        try:
            with opener(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not payload.get("Browser"):
                raise ValueError("CDP version response is missing Browser")
            checks["cdp"] = True
            cdp = {
                "browser": str(payload.get("Browser")),
                "protocol_version": (
                    str(payload.get("Protocol-Version"))
                    if payload.get("Protocol-Version") is not None
                    else None
                ),
            }
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"CDP unavailable: {type(exc).__name__}: {exc}")

    report = {
        "status": "ok" if all(checks.values()) else "failed",
        "runtime_home": str(home),
        "checks": checks,
        "errors": errors,
    }
    report["runtime_version"] = version_report
    if cdp is not None:
        report["cdp"] = cdp
    return report


def run_preflight(
    layout: RuntimeLayout,
    *,
    live: bool,
    cdp_url: str = DEFAULT_CDP_URL,
    timeout: float = 10.0,
    urlopen: Callable | None = None,
) -> dict:
    timeout = _validated_preflight_timeout(timeout)
    if not isinstance(layout, RuntimeLayout):
        raise ConfigurationError("runtime layout is required")
    try:
        with _runtime_lease(layout, timeout=timeout):
            return _run_preflight_unlocked(
                layout,
                live=live,
                cdp_url=cdp_url,
                timeout=timeout,
                urlopen=urlopen,
            )
    except _RuntimeLeaseError as exc:
        return {
            "status": "failed",
            "runtime_home": str(layout.home.expanduser().absolute()),
            "checks": {
                "runtime_lease": exc.lease_acquired,
                "release": False,
            },
            "errors": [str(exc)],
        }
