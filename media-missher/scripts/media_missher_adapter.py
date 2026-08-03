#!/usr/bin/env python3
"""Standard-library adapter primitives for the external Media@Missher engine."""

from __future__ import annotations

import csv
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
from urllib.parse import urlsplit, urlunsplit
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
    environment = {
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
    risk_detected = threading.Event()

    def terminate_process_group(process: subprocess.Popen, grace_seconds: float = 5.0):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=grace_seconds)

    def copy_and_monitor(stream, destination):
        tail = ""
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            destination.write(chunk)
            destination.flush()
            tail = (tail + chunk.decode("utf-8", errors="replace"))[-1024:]
            if _RISK_PATTERN.search(tail):
                risk_detected.set()

    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(
            list(command.argv),
            cwd=command.script.parent.parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
            bufsize=0,
        )
        readers = (
            threading.Thread(target=copy_and_monitor, args=(process.stdout, stdout), daemon=True),
            threading.Thread(target=copy_and_monitor, args=(process.stderr, stderr), daemon=True),
        )
        for reader in readers:
            reader.start()
        deadline = started + timeout
        while process.poll() is None:
            if risk_detected.is_set():
                terminate_process_group(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                terminate_process_group(process)
                break
            time.sleep(0.02)
        if process.poll() is None:
            process.wait(timeout=5)
        for reader in readers:
            reader.join(timeout=5)
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
    discovered = []
    for path in root.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve()
        if resolved.parent != root or path.stat().st_mtime_ns < started_ns:
            continue
        discovered.append(resolved)
    return tuple(sorted(discovered))


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


def write_output(records, format_name: str, output_base: Path) -> Path:
    normalized = normalize_records(records)
    path = _output_path(output_base, format_name)
    _prepare_private_parent(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        if format_name == "json":
            temporary.write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif format_name == "jsonl":
            with temporary.open("x", encoding="utf-8") as handle:
                for record in normalized:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                    handle.write("\n")
        elif format_name == "csv":
            columns = list(normalized[0]) if normalized else []
            with temporary.open("x", encoding="utf-8", newline="") as handle:
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


def redact_for_summary(value, *, secrets: set[str] | None = None):
    configured_secrets = {item for item in (secrets or set()) if item}

    def redact(item):
        if isinstance(item, Mapping):
            cleaned = {}
            for key, child in item.items():
                normalized_key = str(key).strip().lower()
                if normalized_key in _SENSITIVE_KEYS or any(
                    marker in normalized_key
                    for marker in ("password", "credential", "access_token", "refresh_token")
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
    )
    for key, platform in key_platforms:
        if record.get(key) is not None:
            return platform
    return None


def _record_identity(record: Mapping, platform: str) -> str:
    keys = {
        "bilibili": ("dynamic_id", "bvid", "link"),
        "xhs": ("note_id", "link"),
        "douyin": ("aweme_id", "link"),
        "weibo": ("mblog_id", "link"),
    }[platform]
    for key in keys:
        if record.get(key) not in (None, ""):
            return f"{platform}:{key}:{record[key]}"
    return f"{platform}:anonymous:{json.dumps(record, sort_keys=True, ensure_ascii=False)}"


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


def _xhs_complete(record: Mapping, started_ns: int) -> bool:
    observed_ns = _parse_observed_ns(
        record.get("engagement_observed_at") or record.get("metric_observed_at")
    )
    source = str(record.get("engagement_source") or "").lower()
    precision = str(record.get("date_precision") or "").lower()
    return bool(
        record.get("complete") is True
        and record.get("detail_attempted") is True
        and record.get("date")
        and precision not in {"", "unknown", "estimated", "estimated_day"}
        and record.get("engagement_fresh") is True
        and source in {"detail", "detail_api", "html", "cdp", "detail_html", "detail_cdp"}
        and observed_ns is not None
        and observed_ns >= started_ns
        and all(record.get(key) is not None for key in ("liked", "comments", "collected"))
    )


def validate_run(paths, request: CollectionRequest, started_ns: int) -> dict:
    errors: list[str] = []
    evidence: list[str] = []
    collected: dict[str, list[dict]] = {platform: [] for platform in request.platforms}
    risk_stopped = False
    for raw_path in paths:
        unresolved = Path(raw_path).expanduser()
        if unresolved.is_symlink():
            path = unresolved.absolute()
            evidence.append(str(path))
            errors.append(f"stale or unsafe evidence: {path}")
            continue
        path = unresolved.resolve()
        evidence.append(str(path))
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
            if status in {"risk", "risk-stopped", "locked", "cooldown"}:
                risk_stopped = True
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
        for record in records:
            platform = _platform_from_record(record, path)
            if platform not in request.platforms:
                errors.append(f"unexpected or unknown platform record in {path}")
                continue
            collected[platform].append(record)

    deduplicated: dict[str, list[dict]] = {}
    for platform, records in collected.items():
        unique = {}
        for record in records:
            unique.setdefault(_record_identity(record, platform), record)
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
            not _xhs_complete(record, started_ns) for record in deduplicated["xhs"]
        )
        if incomplete:
            errors.append(f"XHS complete validation failed for {incomplete} records")

    records = normalize_records(
        [record for platform in request.platforms for record in deduplicated[platform]]
    )
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
        "errors": errors,
    }


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
    validation = validate_run(evidence, request, started_ns)
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
    errors.extend(validation["errors"])
    if (
        completed.risk_detected
        or _RISK_PATTERN.search(combined_log)
        or validation["status"] == "risk-stopped"
    ):
        status = "risk-stopped"
    elif feishu_artifacts:
        status = "failed"
    elif completed.timed_out or completed.returncode != 0:
        status = "partial" if evidence else "failed"
    else:
        status = validation["status"]

    outputs = [str(path) for path in evidence] if request.output_format == "json" else []
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

    validation_summary = {
        key: value for key, value in validation.items() if key != "records"
    }
    validation_summary["samples"] = redact_for_summary(validation["records"][:3])
    return {
        "status": status,
        "run_dir": str(run_dir),
        "evidence": [str(path) for path in evidence],
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
