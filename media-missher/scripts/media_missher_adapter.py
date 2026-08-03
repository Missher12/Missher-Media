#!/usr/bin/env python3
"""Standard-library adapter primitives for the external Media@Missher engine."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import urllib.request
from pathlib import Path
from typing import Callable, Mapping


PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")
DEFAULT_CDP_URL = "http://127.0.0.1:9222"


class ConfigurationError(ValueError):
    """Raised when a request cannot be validated before engine execution."""


def parse_non_negative_int(value: str | int) -> int:
    if isinstance(value, bool):
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
    profile_path = Path(path).expanduser()
    try:
        mode = stat.S_IMODE(profile_path.stat().st_mode)
    except OSError as exc:
        raise ConfigurationError(f"cannot read profile: {exc}") from exc
    if mode & 0o077:
        raise ConfigurationError("profile must use mode 0600 with no group/world permissions")
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


def resolve_engine_root(
    cli_value: Path | None,
    *,
    environ: Mapping[str, str],
    profile: Mapping | None = None,
) -> Path:
    resolved = _configured_path(
        cli_value,
        environment_name="MEDIA_MISSHER_ENGINE_ROOT",
        profile_name="engine_root",
        environ=environ,
        profile=profile,
    )
    if resolved is None:
        raise ConfigurationError(
            "engine root is required via --engine-root, MEDIA_MISSHER_ENGINE_ROOT, or profile"
        )
    return resolved


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
    return (Path.home() / ".media-missher" / "runs").resolve()


def engine_python(engine_root: Path) -> Path:
    candidate = Path(engine_root).expanduser().absolute() / "engine" / ".venv" / "bin" / "python"
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise ConfigurationError(f"engine interpreter is missing or not executable: {candidate}")
    return candidate


def _cdp_version_url(cdp_url: str) -> str:
    normalized = cdp_url.rstrip("/")
    if normalized.endswith("/json/version"):
        return normalized
    return f"{normalized}/json/version"


def run_preflight(
    engine_root: Path,
    *,
    live: bool,
    cdp_url: str = DEFAULT_CDP_URL,
    timeout: float = 10.0,
    urlopen: Callable | None = None,
) -> dict:
    if timeout <= 0:
        raise ConfigurationError("timeout must be greater than zero")
    root = Path(engine_root).expanduser().resolve()
    entrypoint = root / "scripts" / "scrape_all.py"
    checks = {
        "engine_root": root.is_dir(),
        "interpreter": False,
        "entrypoint": entrypoint.is_file(),
        "entrypoint_help": False,
    }
    errors: list[str] = []
    interpreter: Path | None = None

    if not checks["engine_root"]:
        errors.append(f"engine root is not a directory: {root}")
    try:
        interpreter = engine_python(root)
        checks["interpreter"] = True
    except ConfigurationError as exc:
        errors.append(str(exc))
    if not checks["entrypoint"]:
        errors.append(f"entrypoint is missing: {entrypoint}")

    if checks["interpreter"] and checks["entrypoint"] and interpreter is not None:
        try:
            completed = subprocess.run(
                [str(interpreter), str(entrypoint), "--help"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            checks["entrypoint_help"] = completed.returncode == 0
            if not checks["entrypoint_help"]:
                errors.append(f"entrypoint --help exited with status {completed.returncode}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"entrypoint --help failed: {type(exc).__name__}: {exc}")

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
        "engine_root": str(root),
        "checks": checks,
        "errors": errors,
    }
    if cdp is not None:
        report["cdp"] = cdp
    return report
