#!/usr/bin/env python3
"""Standard-library adapter primitives for the external Media@Missher engine."""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import signal
import stat
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
SKILL_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(ValueError):
    """Raised when a request cannot be validated before engine execution."""


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

        zero_requested = count == 0 or any(value == 0 for value in normalized_counts.values())
        if zero_requested and not self.collect_as_much_as_safe:
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


@dataclass(frozen=True)
class EngineCommand:
    script: Path
    argv: tuple[str, ...]
    environment: Mapping[str, str] = field(default_factory=dict)

    def with_environment(self, values: Mapping[str, str]) -> "EngineCommand":
        merged = {**self.environment, **{str(key): str(value) for key, value in values.items()}}
        return EngineCommand(self.script, self.argv, merged)


@dataclass(frozen=True)
class CompletedRun:
    returncode: int | None
    stdout_path: Path
    stderr_path: Path
    timed_out: bool
    duration_seconds: float


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


def _number_text(value: float | int) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def build_engine_command(
    request: CollectionRequest,
    staging_dir: Path,
    *,
    engine_root: Path,
) -> EngineCommand:
    root = Path(engine_root).expanduser().resolve()
    interpreter = engine_python(root)
    staging = Path(staging_dir).expanduser().resolve()
    if request.search:
        script = root / "scripts" / f"scrape_{request.platforms[0]}.py"
    else:
        script = root / "scripts" / "scrape_all.py"
    if not script.is_file():
        raise ConfigurationError(f"engine entrypoint is missing: {script}")

    argv = [str(interpreter), str(script)]
    if request.search:
        platform = request.platforms[0]
        search_count = request.platform_counts.get(platform, request.count)
        argv.extend(("--search", request.search, "--count", str(search_count)))
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
    argv.extend(("--format", "json", "--output", str(staging)))
    environment = {"PYTHONDONTWRITEBYTECODE": "1"}
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


def execute_engine(
    command: EngineCommand,
    *,
    timeout: float,
    run_dir: Path,
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
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("x", encoding="utf-8") as stdout, stderr_path.open(
        "x", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            list(command.argv),
            cwd=command.script.parent.parent,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            text=True,
            shell=False,
            start_new_session=True,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
    return CompletedRun(
        returncode=process.returncode,
        stdout_path=stdout_path.resolve(),
        stderr_path=stderr_path.resolve(),
        timed_out=timed_out,
        duration_seconds=time.monotonic() - started,
    )


def discover_current_json(run_dir: Path, *, started_ns: int) -> tuple[Path, ...]:
    root = Path(run_dir).expanduser().resolve()
    discovered = []
    for path in root.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve()
        if resolved.parent != root or path.stat().st_mtime_ns < started_ns:
            continue
        discovered.append(resolved)
    return tuple(sorted(discovered))


_RISK_PATTERN = re.compile(r"(?i)(?:\b(?:403|429|461|471|999)\b|risk|locked|cooldown)")


def run_collection_request(
    request: CollectionRequest,
    *,
    engine_root: Path,
    data_root: Path,
    cdp_url: str = DEFAULT_CDP_URL,
    preflight_runner: Callable = None,
    execution_timeout: float | None = None,
    command_environment: Mapping[str, str] | None = None,
) -> dict:
    runner = preflight_runner or run_preflight
    preflight_report = runner(engine_root, live=True, cdp_url=cdp_url, timeout=10.0)
    if preflight_report.get("status") != "ok":
        return {
            "status": "preflight-failed",
            "run_dir": None,
            "evidence": [],
            "errors": list(preflight_report.get("errors", [])),
            "preflight": preflight_report,
        }

    run_dir = create_run_directory(data_root)
    started_ns = time.time_ns()
    try:
        command = build_engine_command(request, run_dir, engine_root=engine_root)
        if command_environment:
            command = command.with_environment(command_environment)
        if execution_timeout is None:
            per_platform = request.platform_timeout if request.platform_timeout > 0 else 3600.0
            execution_timeout = per_platform * len(request.platforms) + 60.0
        completed = execute_engine(command, timeout=execution_timeout, run_dir=run_dir)
    except (ConfigurationError, OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "failed",
            "run_dir": str(run_dir),
            "evidence": [],
            "errors": [str(exc)],
            "preflight": preflight_report,
        }
    evidence = discover_current_json(run_dir, started_ns=started_ns)
    feishu_artifacts = tuple(run_dir.glob("feishu_*"))
    stdout = completed.stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = completed.stderr_path.read_text(encoding="utf-8", errors="replace")
    combined_log = f"{stdout}\n{stderr}"
    errors = []
    if feishu_artifacts:
        errors.append("unexpected Feishu artifact was generated")
    if completed.timed_out:
        errors.append("engine execution timed out")
    if completed.returncode != 0:
        errors.append(f"engine exited with status {completed.returncode}")
    if _RISK_PATTERN.search(combined_log):
        status = "risk-stopped"
    elif feishu_artifacts:
        status = "failed"
    elif completed.timed_out or completed.returncode != 0:
        status = "partial" if evidence else "failed"
    else:
        status = "success" if evidence else "failed"
        if not evidence:
            errors.append("engine produced no current JSON evidence")
    return {
        "status": status,
        "run_dir": str(run_dir),
        "evidence": [str(path) for path in evidence],
        "errors": errors,
        "returncode": completed.returncode,
        "timed_out": completed.timed_out,
        "duration_seconds": round(completed.duration_seconds, 3),
        "stdout_path": str(completed.stdout_path),
        "stderr_path": str(completed.stderr_path),
        "preflight": preflight_report,
    }


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
