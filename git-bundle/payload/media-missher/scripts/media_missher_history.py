"""Private, bounded, offline run-history operations for Media@Missher.

Historical evidence is deliberately separate from current-run validation.  This
module never assigns freshness to old records and never launches a collector.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


PLATFORMS = ("bilibili", "xhs", "douyin", "weibo", "x")
CONTEXT_NAME = "run-context.json"
COMMITTED_NAME = "committed.json"
RESULT_NAME = "run-result.json"
CONTEXT_KEYS = frozenset(
    {
        "schema",
        "run_id",
        "started_ns",
        "request_digest",
        "profile_digest",
        "runtime_version",
        "requested_counts",
        "parent_run_id",
        "created_at",
    }
)
MANIFEST_KEYS = frozenset({"counts", "paths", "platforms", "status", "diagnostics"})
MAX_CONTEXT_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
MAX_CHAIN_DEPTH = 32
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_RUN_ID = re.compile(r"run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_NATIVE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_NATIVE_ID_KEYS = {
    "bilibili": ("dynamic_id", "bvid"),
    "xhs": ("note_id",),
    "douyin": ("aweme_id",),
    "weibo": ("mblog_id",),
}
_METRICS = ("liked", "comments", "collected", "shares", "plays")
_DIAGNOSTICS = {
    "complete": frozenset({("ok", "ok")}),
    "shortfall": frozenset({("result", "count-shortfall")}),
    "incomplete": frozenset(
        {("result", "incomplete-record"), ("result", "screenshot-shortfall")}
    ),
    "failed": frozenset(
        {
            ("dependency", "module-not-found"),
            ("source-response", "source-response-failed"),
            ("timeout", "platform-timeout"),
            ("timeout", "creator-capture-timeout"),
            ("timeout", "detail-capture-timeout"),
            ("collector-contract", "invalid-records"),
            ("internal", "unexpected"),
            *(
                ("precondition", code)
                for code in {
                    "precondition-failed", "bsk-missing", "bsk-unhealthy",
                    "bsk-incompatible", "bsk-busy", "bsk-transport", "bsk-timeout",
                    "bsk-target-ambiguous", "bsk-session-start", "bsk-tab-list",
                    "bsk-tab-borrow", "bsk-snapshot", "bsk-click", "bsk-tab-return",
                    "bsk-session-stop", "browser-assist-replaced", "xhs-cooldown",
                    "xhs-risk-latched", "xhs-safety-busy", "xhs-safety-state-invalid",
                }
            ),
        }
    ),
    "risk-stopped": frozenset(
        ("risk-stop", code)
        for code in {"http-403", "http-429", "payload-461", "payload-471", "payload-999", "challenge", "risk-signal"}
    ),
    "not-run": frozenset(
        {("not-run", "preflight-aborted"), ("not-run", "prior-risk-stop")}
    ),
}


class HistoryError(ValueError):
    """Raised when historical evidence cannot be safely read or continued."""

    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


def _validate_run_id(value: object, *, label: str = "run ID") -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise HistoryError(f"invalid {label}")
    return value


def _reject_symlink_components(path: Path, label: str) -> None:
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            value = os.lstat(current)
        except OSError as exc:
            raise HistoryError(f"{label} is unavailable: {type(exc).__name__}") from exc
        if stat.S_ISLNK(value.st_mode):
            raise HistoryError(f"{label} contains a symlink")


def _owned_private_dir(path: Path, label: str) -> os.stat_result:
    _reject_symlink_components(path, label)
    try:
        value = os.lstat(path)
    except OSError as exc:
        raise HistoryError(f"{label} is unavailable: {type(exc).__name__}") from exc
    if stat.S_ISLNK(value.st_mode):
        raise HistoryError(f"{label} must not be a symlink")
    if not stat.S_ISDIR(value.st_mode):
        raise HistoryError(f"{label} must be a directory")
    if stat.S_IMODE(value.st_mode) != 0o700:
        raise HistoryError(f"{label} must use exact mode 0700")
    if hasattr(os, "getuid") and value.st_uid != os.getuid():
        raise HistoryError(f"{label} must be owned by the current user")
    return value


def _read_private_file(path: Path, label: str, limit: int) -> bytes:
    _reject_symlink_components(path, label)
    try:
        expected = os.lstat(path)
    except OSError as exc:
        raise HistoryError(f"{label} is unavailable: {type(exc).__name__}") from exc
    if stat.S_ISLNK(expected.st_mode):
        raise HistoryError(f"{label} must not be a symlink")
    if not stat.S_ISREG(expected.st_mode):
        raise HistoryError(f"{label} must be a regular file")
    if stat.S_IMODE(expected.st_mode) != 0o600:
        raise HistoryError(f"{label} must use exact mode 0600")
    if expected.st_nlink != 1:
        raise HistoryError(f"{label} must not have a hard link")
    if hasattr(os, "getuid") and expected.st_uid != os.getuid():
        raise HistoryError(f"{label} must be owned by the current user")
    if expected.st_size > limit:
        raise HistoryError(f"{label} exceeds its size limit")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if not os.path.samestat(expected, opened):
            raise HistoryError(f"{label} changed while being opened")
        payload = os.read(descriptor, limit + 1)
    except OSError as exc:
        raise HistoryError(f"{label} is unavailable: {type(exc).__name__}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(payload) > limit:
        raise HistoryError(f"{label} exceeds its size limit")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HistoryError(f"invalid historical JSON: duplicate key: {key}")
        result[key] = value
    return result


def _read_json(path: Path, label: str, limit: int) -> Any:
    try:
        return json.loads(
            _read_private_file(path, label, limit).decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except HistoryError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HistoryError(f"{label} is invalid JSON: {type(exc).__name__}") from exc


def _write_json_exclusive(path: Path, value: object) -> Path:
    if os.path.lexists(path):
        raise HistoryError(f"refusing to overwrite private file: {path.name}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".history-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as exc:
        raise HistoryError(f"refusing to overwrite private file: {path.name}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _requested_counts(request: object) -> dict[str, int]:
    platforms = tuple(getattr(request, "platforms", ()))
    overrides = getattr(request, "platform_counts", {})
    default = getattr(request, "count", None)
    if not platforms or any(platform not in PLATFORMS for platform in platforms):
        raise HistoryError("request has invalid platforms")
    result: dict[str, int] = {}
    for platform in platforms:
        value = overrides.get(platform, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HistoryError("request has invalid requested counts")
        result[platform] = value
    return result


def request_digest(request: object) -> str:
    """Return the continuation identity, excluding output representation.

    Raw creator IDs and search text contribute only one-way hashes to the digest
    input and are never written to ``run-context.json``.
    """

    platforms = tuple(getattr(request, "platforms", ()))
    uids = getattr(request, "platform_uids", {})
    search = getattr(request, "search", None)
    identity = {
        "platforms": list(platforms),
        "requested_counts": _requested_counts(request),
        "target_digests": {
            platform: _sha256_text(f"{platform}\0{uids[platform]}")
            for platform in platforms
            if platform in uids
        },
        "search_digest": _sha256_text(str(search)) if search is not None else None,
        "complete": bool(getattr(request, "complete", False)),
        "bilibili_complete": bool(getattr(request, "bilibili_complete", False)),
        "xhs_complete": bool(getattr(request, "xhs_complete", False)),
        "xhs_comments": getattr(request, "xhs_comments", 0),
        "collect_as_much_as_safe": bool(getattr(request, "collect_as_much_as_safe", False)),
        "allow_navigation": bool(getattr(request, "allow_navigation", False)),
        "browser_assist": getattr(request, "browser_assist", "off"),
        "screenshot_mode": getattr(request, "screenshot_mode", "off"),
        "platform_timeout": float(getattr(request, "platform_timeout", 300.0)),
    }
    canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_text(canonical)


def _validate_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise HistoryError(f"invalid {label}")
    return value


def write_context(
    outer_run_dir: Path,
    request: object,
    profile_digest: str,
    runtime_version: str,
    parent_run_id: str | None = None,
) -> Path:
    """Persist schema-1 continuation identity before collector launch."""

    outer = Path(outer_run_dir).expanduser().absolute()
    parent = outer.parent
    _owned_private_dir(parent, "data root")
    outer_stat = _owned_private_dir(outer, "outer run directory")
    run_id = _validate_run_id(outer.name)
    if parent_run_id is not None:
        _validate_run_id(parent_run_id, label="parent run ID")
        if parent_run_id == run_id:
            raise HistoryError("parent run ID cannot reference itself")
    profile = _validate_digest(profile_digest, "profile digest")
    if not isinstance(runtime_version, str) or not runtime_version.strip() or len(runtime_version) > 64:
        raise HistoryError("invalid runtime version")
    if any(ord(character) < 32 for character in runtime_version):
        raise HistoryError("invalid runtime version")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    context = {
        "schema": 1,
        "run_id": run_id,
        "started_ns": outer_stat.st_mtime_ns,
        "request_digest": request_digest(request),
        "profile_digest": profile,
        "runtime_version": runtime_version,
        "requested_counts": _requested_counts(request),
        "parent_run_id": parent_run_id,
        "created_at": now,
    }
    return _write_json_exclusive(outer / CONTEXT_NAME, context).resolve()


def _load_context(outer: Path) -> dict[str, Any] | None:
    path = outer / CONTEXT_NAME
    if not os.path.lexists(path):
        return None
    value = _read_json(path, "run context", MAX_CONTEXT_BYTES)
    if not isinstance(value, dict) or set(value) != CONTEXT_KEYS or value.get("schema") != 1:
        raise HistoryError("run context has an invalid fixed schema")
    _validate_run_id(value.get("run_id"))
    if value["run_id"] != outer.name:
        raise HistoryError("run context ID does not match its directory")
    if isinstance(value.get("started_ns"), bool) or not isinstance(value.get("started_ns"), int) or value["started_ns"] <= 0:
        raise HistoryError("run context has an invalid start timestamp")
    _validate_digest(value.get("request_digest"), "request digest")
    _validate_digest(value.get("profile_digest"), "profile digest")
    if value.get("parent_run_id") is not None:
        _validate_run_id(value["parent_run_id"], label="parent run ID")
    counts = value.get("requested_counts")
    if not isinstance(counts, dict) or not counts or any(
        key not in PLATFORMS or isinstance(item, bool) or not isinstance(item, int) or item < 0
        for key, item in counts.items()
    ):
        raise HistoryError("run context has invalid requested counts")
    if not isinstance(value.get("runtime_version"), str) or not value["runtime_version"]:
        raise HistoryError("run context has an invalid runtime version")
    if not isinstance(value.get("created_at"), str) or not value["created_at"].endswith("Z"):
        raise HistoryError("run context has an invalid UTC creation time")
    return value


def _load_controller_status(outer: Path) -> str | None:
    path = outer / RESULT_NAME
    if not os.path.lexists(path):
        return None
    value = _read_json(path, "run result", MAX_CONTEXT_BYTES)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "status"}
        or value.get("schema") != 1
        or not isinstance(value.get("status"), str)
        or value.get("status") not in {"success", "partial", "failed", "risk-stopped"}
    ):
        raise HistoryError("run result has an invalid fixed schema")
    return value["status"]


def _validate_manifest(value: object) -> dict[str, Any]:
    expected_keys = MANIFEST_KEYS
    if isinstance(value, dict) and value.get("schema_version") in {2, 3}:
        expected_keys = MANIFEST_KEYS | {"schema_version", "backend", "record_kinds"}
        kinds = value.get("record_kinds")
        permitted_backends = {"cdp", "browserskill"} if value["schema_version"] == 2 else {"cdp", "computer_use"}
        if value.get("backend") not in permitted_backends or not isinstance(kinds, dict) or set(kinds) - {"posts", "user_profiles", "topic_participants"} or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in kinds.values()):
            raise HistoryError("historical manifest run identity is invalid")
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise HistoryError("historical manifest has an invalid fixed schema")
    counts, paths = value.get("counts"), value.get("paths")
    platforms, diagnostics = value.get("platforms"), value.get("diagnostics")
    if not all(isinstance(item, dict) for item in (counts, paths, platforms, diagnostics)):
        raise HistoryError("historical manifest fields must be objects")
    selected = set(platforms)
    if not selected or not selected.issubset(PLATFORMS) or set(counts) != selected or set(diagnostics) != selected:
        raise HistoryError("historical manifest platform keys do not match")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in counts.values()):
        raise HistoryError("historical manifest count is invalid")
    allowed_paths = selected | ({"xhs_report", "xhs_checkpoint"} if "xhs" in selected else set())
    if set(paths) - allowed_paths:
        raise HistoryError("historical manifest paths are invalid")
    if any(not isinstance(name, str) or name != f"{key}.json" for key, name in paths.items()):
        raise HistoryError("historical manifest path is unsafe")
    if len(set(paths.values())) != len(paths):
        raise HistoryError("historical manifest paths are invalid")
    for platform, platform_status in platforms.items():
        diagnostic = diagnostics[platform]
        if not isinstance(platform_status, str) or platform_status not in _DIAGNOSTICS or not isinstance(diagnostic, dict) or set(diagnostic) != {"kind", "code"}:
            raise HistoryError("historical manifest diagnostic schema is invalid")
        if not all(isinstance(diagnostic[key], str) for key in ("kind", "code")) or (diagnostic["kind"], diagnostic["code"]) not in _DIAGNOSTICS[platform_status]:
            raise HistoryError("historical manifest diagnostic value is invalid")
        if platform_status == "complete" and platform not in paths:
            raise HistoryError("historical manifest is missing a completed platform path")
    expected = "risk-stopped" if "risk-stopped" in platforms.values() else "complete" if all(item == "complete" for item in platforms.values()) else "failed"
    if value.get("schema_version") in {2, 3} and expected == "failed" and any(counts.values()):
        expected = "partial"
    if value.get("status") != expected:
        raise HistoryError("historical manifest overall status is inconsistent")
    return value


def _load_committed_snapshot(
    inner: Path,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    path = inner / COMMITTED_NAME
    journal_value = None
    if (inner / "journal").exists():
        try:
            from media_missher_runtime.batch_journal import journal_snapshot
            journal_value = journal_snapshot(inner)
        except (ValueError, OSError) as exc:
            raise HistoryError("committed journal is invalid") from exc
    if not os.path.lexists(path) and journal_value is None:
        return None
    try:
        value = _read_json(path, "committed snapshot", MAX_ARTIFACT_BYTES) if os.path.lexists(path) else journal_value
        if not isinstance(value, dict) or set(value) != {"schema", "manifest", "artifacts"}:
            raise HistoryError("committed snapshot has an invalid fixed schema")
        if value.get("schema") != 1 or not isinstance(value.get("artifacts"), dict):
            raise HistoryError("committed snapshot has an invalid fixed schema")
        manifest = _validate_manifest(value.get("manifest"))
        artifacts = value["artifacts"]
        if set(artifacts) != set(manifest["paths"]):
            raise HistoryError("committed snapshot artifact keys do not match")
        return manifest, artifacts
    except HistoryError as exc:
        raise HistoryError("committed snapshot is invalid") from exc


def _native_id(record: Mapping[str, Any], platform: str) -> str:
    for key in (("tweet_id",) if platform == "x" else _NATIVE_ID_KEYS[platform]):
        value = record.get(key)
        if isinstance(value, str) and _NATIVE_ID.fullmatch(value) is not None:
            return value
    raise HistoryError(f"{platform} record has no valid native ID")


def _validate_screenshot_reference(
    inner: Path, platform: str, record: Mapping[str, Any]
) -> None:
    raw_path = record.get("screenshot_path")
    if raw_path is None:
        return
    from media_missher_adapter import _screenshot_native_id

    # Bilibili videos use bvid for capture but dynamic_id for creator dedupe.
    native_id = _screenshot_native_id(record, platform)
    if native_id is None:
        raise HistoryError(f"historical {platform} screenshot identity is invalid")
    expected = f"screenshots/{platform}-{native_id}.png"
    if raw_path != expected:
        raise HistoryError(f"historical {platform} screenshot path is unsafe")
    screenshot_dir = inner / "screenshots"
    _owned_private_dir(screenshot_dir, "historical screenshot directory")
    payload = _read_private_file(
        screenshot_dir / f"{platform}-{native_id}.png",
        "historical screenshot",
        MAX_ARTIFACT_BYTES,
    )
    digest = record.get("screenshot_sha256")
    if (
        not payload.startswith(_PNG_SIGNATURE)
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or hashlib.sha256(payload).hexdigest() != digest
    ):
        raise HistoryError(f"historical {platform} screenshot is invalid")


def _accepted_for_continuation(
    loaded: Mapping[str, Any], platform: str, record: dict[str, Any], request: object
) -> bool:
    """Apply the original semantic validators without asserting present freshness."""

    from media_missher_adapter import (
        _bilibili_complete,
        _validate_screenshot_record,
        _xhs_complete,
    )

    started_ns = loaded["context"]["started_ns"]
    if platform == "xhs" and not _xhs_complete(
        record, started_ns, getattr(request, "xhs_comments", 0)
    ):
        return False
    if platform == "bilibili" and (
        getattr(request, "complete", False)
        or getattr(request, "bilibili_complete", False)
    ) and not _bilibili_complete(record):
        return False
    screenshot_mode = getattr(request, "screenshot_mode", "off")
    if screenshot_mode != "off":
        source = Path(loaded["engine_run_dir"]) / f"{platform}.json"
        if _validate_screenshot_record(
            dict(record),
            platform=platform,
            source_json=source,
            request_mode=screenshot_mode,
            started_ns=started_ns,
        ) is not None:
            return False
    return True


def _observation_times(records: list[dict[str, Any]]) -> list[Any]:
    result: list[Any] = []
    for record in records:
        values: list[Any] = [
            record.get("observed_at"),
            record.get("engagement_observed_at"),
            record.get("detail_checked_at"),
            record.get("screenshot_observed_at"),
        ]
        metric_times = record.get("metric_observed_at")
        if isinstance(metric_times, Mapping):
            values.extend(metric_times.values())
        for value in values:
            if isinstance(value, (str, int, float)) and not isinstance(value, bool) and value not in result:
                result.append(value)
    return result


def _resolve_outer(data_root: Path, run_id: str) -> tuple[Path, Path]:
    root = Path(data_root).expanduser().absolute()
    _owned_private_dir(root, "data root")
    exact = _validate_run_id(run_id)
    outer = root / exact
    _owned_private_dir(outer, "outer run directory")
    if outer.parent != root:
        raise HistoryError("run must be a direct child of the data root")
    return root, outer


def load_run(data_root: Path, exact_run_id: str) -> dict[str, Any]:
    """Load one exact historical run without applying current-run freshness."""

    _root, outer = _resolve_outer(data_root, exact_run_id)
    context = _load_context(outer)
    controller_status = _load_controller_status(outer)
    # Versioned plan runs live directly under the private data root. Legacy
    # controller runs retain their one nested engine directory.
    direct = None
    if os.path.lexists(outer / "manifest.json"):
        direct = _read_json(outer / "manifest.json", "historical manifest", MAX_MANIFEST_BYTES)
    inner_candidates: list[Path] = [outer] if (isinstance(direct, dict) and direct.get("schema_version") in {2, 3}) or (outer / "journal").exists() else []
    for candidate in outer.iterdir():
        if candidate.name == CONTEXT_NAME or not candidate.name.startswith("run-"):
            continue
        if candidate.is_symlink():
            raise HistoryError("engine run directory must not be a symlink")
        if candidate.is_dir():
            _validate_run_id(candidate.name, label="engine run ID")
            _owned_private_dir(candidate, "engine run directory")
            inner_candidates.append(candidate)
    if len(inner_candidates) != 1:
        raise HistoryError(
            f"expected exactly one historical engine run, found {len(inner_candidates)}",
            code="unavailable" if not inner_candidates else "invalid",
        )
    inner = inner_candidates[0]
    committed = _load_committed_snapshot(inner)
    committed_artifacts = None
    if committed is None:
        if not os.path.lexists(inner / "manifest.json"):
            raise HistoryError("historical manifest is unavailable", code="unavailable")
        manifest = _validate_manifest(
            _read_json(inner / "manifest.json", "historical manifest", MAX_MANIFEST_BYTES)
        )
        artifacts = {
            key: _read_json(inner / name, f"historical artifact {key}", MAX_ARTIFACT_BYTES)
            for key, name in manifest["paths"].items()
        }
    else:
        manifest, artifacts = committed
        committed_artifacts = artifacts
    if context is not None and not set(manifest["platforms"]).issubset(context["requested_counts"]):
        raise HistoryError("manifest platforms are outside the run context")
    if context is not None:
        for platform, count in manifest["counts"].items():
            requested = context["requested_counts"][platform]
            if requested > 0 and count > requested:
                raise HistoryError(f"historical {platform} count exceeds its requested count")
    records_by_platform: dict[str, list[dict[str, Any]]] = {}
    for key, name in manifest["paths"].items():
        artifact = artifacts[key]
        if key not in manifest["platforms"]:
            continue
        if not isinstance(artifact, list) or any(not isinstance(record, dict) for record in artifact):
            raise HistoryError(f"historical {key} artifact must contain a record list")
        if len(artifact) != manifest["counts"][key]:
            raise HistoryError(f"historical {key} count does not match its manifest")
        seen: set[str] = set()
        for record in artifact:
            if record.get("platform") != key:
                raise HistoryError(f"historical {key} record platform does not match")
            kind = record.get("type")
            if manifest.get("schema_version") in {2, 3} and kind in {"user_profile", "profile", "topic_participant", "topic_participant_relation"}:
                uid = record.get("uid") or record.get("author_id")
                if not isinstance(uid, str) or _NATIVE_ID.fullmatch(uid) is None:
                    raise HistoryError("historical user identity is invalid")
                native = f"{kind}:{uid}"
                if kind in {"topic_participant", "topic_participant_relation"}:
                    native += ":" + str(record.get("topic") or record.get("target_identity") or "") + ":" + str(record.get("post_id") or "")
            else:
                native = "post:" + _native_id(record, key)
            if native in seen:
                raise HistoryError(f"historical {key} artifact has a duplicate native ID")
            seen.add(native)
            if not isinstance(record.get("link"), str) or not record["link"].strip():
                raise HistoryError(f"historical {key} record has no valid link")
            _validate_screenshot_reference(inner, key, record)
        records_by_platform[key] = artifact
    for platform, count in manifest["counts"].items():
        if platform not in records_by_platform and count != 0:
            raise HistoryError(f"historical {platform} count has no declared artifact")
        records_by_platform.setdefault(platform, [])
    if manifest.get("schema_version") in {2, 3}:
        from media_missher_runtime.exporting import record_kind
        actual_kinds = {}
        for items in records_by_platform.values():
            for item in items:
                kind = record_kind(item)
                actual_kinds[kind] = actual_kinds.get(kind, 0) + 1
        if any(actual_kinds.get(k, 0) != manifest["record_kinds"].get(k, 0) for k in set(actual_kinds) | set(manifest["record_kinds"])):
            raise HistoryError("historical record kind counts do not match")
    records = [record for platform in PLATFORMS for record in records_by_platform.get(platform, [])]
    return {
        "run_id": exact_run_id,
        "historical": True,
        "bound": context is not None,
        "context": context,
        "controller_status": controller_status,
        "manifest": manifest,
        "committed_artifacts": committed_artifacts,
        "counts": dict(manifest["counts"]),
        "records_by_platform": records_by_platform,
        "records": records,
        "observation_times": _observation_times(records),
        "outer_run_dir": str(outer),
        "engine_run_dir": str(inner),
    }


def list_history(data_root: Path) -> list[dict[str, Any]]:
    """Return fixed metadata for all exact private run children."""

    root = Path(data_root).expanduser().absolute()
    _owned_private_dir(root, "data root")
    result = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.name.startswith("run-"):
            continue
        try:
            loaded = load_run(root, child.name)
        except HistoryError as exc:
            result.append(
                {
                    "run_id": child.name,
                    "historical": True,
                    "bound": None,
                    "status": exc.code if exc.code in {"invalid", "unavailable"} else "invalid",
                    "code": f"history-{exc.code}" if exc.code in {"invalid", "unavailable"} else "history-invalid",
                    "counts": {},
                    "started_ns": None,
                    "created_at": None,
                    "observation_times": [],
                }
            )
            continue
        context = loaded["context"]
        result.append(
            {
                "run_id": loaded["run_id"],
                "historical": True,
                "bound": loaded["bound"],
                "status": "risk-stopped" if loaded["controller_status"] == "risk-stopped" else loaded["manifest"]["status"],
                "counts": loaded["counts"],
                "started_ns": context["started_ns"] if context else None,
                "created_at": context["created_at"] if context else None,
                "observation_times": loaded["observation_times"],
            }
        )
    return result


def prepare_continuation(
    data_root: Path,
    exact_parent_run_id: str,
    request: object,
    profile_digest: str,
) -> dict[str, Any]:
    """Derive bounded skip IDs and remaining counts from an explicit run chain."""

    if getattr(request, "search", None) is not None:
        raise HistoryError("continuation is creator-only; search runs cannot be continued")
    expected_request = request_digest(request)
    expected_profile = _validate_digest(profile_digest, "profile digest")
    requested = _requested_counts(request)
    if any(count == 0 for count in requested.values()):
        raise HistoryError("unlimited count zero cannot be continued")
    current = _validate_run_id(exact_parent_run_id, label="parent run ID")
    visited: set[str] = set()
    newest_first: list[str] = []
    skip_sets = {platform: set() for platform in requested}
    while current is not None:
        if current in visited:
            raise HistoryError("continuation chain contains a cycle")
        if len(visited) >= MAX_CHAIN_DEPTH:
            raise HistoryError("continuation chain exceeds its bounded depth")
        visited.add(current)
        loaded = load_run(data_root, current)
        context = loaded["context"]
        if context is None:
            raise HistoryError("pre-context historical runs cannot be continued")
        if context["request_digest"] != expected_request:
            raise HistoryError("continuation request digest does not match")
        if context["profile_digest"] != expected_profile:
            raise HistoryError("continuation profile digest does not match")
        if context["requested_counts"] != requested:
            raise HistoryError("continuation requested counts do not match")
        if (
            loaded["controller_status"] == "risk-stopped"
            or loaded["manifest"]["status"] == "risk-stopped"
            or "risk-stopped" in loaded["manifest"]["platforms"].values()
        ):
            raise HistoryError("cannot continue a risk-stopped ancestor")
        for platform in requested:
            for record in loaded["records_by_platform"].get(platform, []):
                if not _accepted_for_continuation(loaded, platform, record, request):
                    continue
                skip_sets[platform].add(_native_id(record, platform))
        newest_first.append(current)
        current = context["parent_run_id"]
    prior = {platform: len(skip_sets[platform]) for platform in requested}
    if any(prior[platform] > requested[platform] for platform in requested):
        raise HistoryError("continuation accepted count exceeds its requested count")
    remaining = {platform: requested[platform] - prior[platform] for platform in requested}
    if not any(remaining.values()):
        raise HistoryError("continuation has no remaining target")
    return {
        "parent_run_id": exact_parent_run_id,
        "ancestor_run_ids": list(reversed(newest_first)),
        "requested_counts": requested,
        "prior_counts": prior,
        "remaining_counts": remaining,
        "skip_ids": {platform: sorted(skip_sets[platform]) for platform in requested},
    }


def _ensure_exports_dir(root: Path) -> Path:
    exports = root / "exports"
    if os.path.lexists(exports):
        _owned_private_dir(exports, "history exports directory")
    else:
        exports.mkdir(mode=0o700)
        exports.chmod(0o700)
    return exports


def export_run(data_root: Path, exact_run_id: str, format_name: str) -> dict[str, Any]:
    """Re-export validated history and write a private provenance sidecar."""

    loaded = load_run(data_root, exact_run_id)
    root = Path(data_root).expanduser().absolute()
    exports = _ensure_exports_dir(root)
    token = secrets.token_hex(6)
    output_base = exports / f"historical-{exact_run_id}-{token}"
    try:
        from media_missher_adapter import write_output

        output = write_output(loaded["records"], format_name, output_base)
    except (OSError, ValueError) as exc:
        raise HistoryError(f"historical export failed: {type(exc).__name__}") from exc
    metadata_path = exports / f"{output.stem}.metadata.json"
    metadata = {
        "schema": 1,
        "kind": "historical-export",
        "historical": True,
        "source_run_id": exact_run_id,
        "source_started_ns": loaded["context"]["started_ns"] if loaded["context"] else None,
        "source_created_at": loaded["context"]["created_at"] if loaded["context"] else None,
        "source_observation_times": loaded["observation_times"],
        "counts": loaded["counts"],
        "output_filename": output.name,
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json_exclusive(metadata_path, metadata)
    return {**metadata, "output_path": str(output), "metadata_path": str(metadata_path)}


def export_selected_run(
    data_root: Path,
    exact_run_id: str,
    *,
    record_kinds: Sequence[str],
    format_name: str = "xlsx",
    platforms: Sequence[str] = (),
    topics: Sequence[str] = (),
    targets: Sequence[str] = (),
    fields: Sequence[str] = (),
    field_groups: Sequence[str] = (),
    filter_field: str | None = None,
    filter_value: str | None = None,
    file_name: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """按用户选择离线导出一次历史运行，并写入私有溯源边车。

    只读取已保存的本地结果：不打开浏览器、不导航、不补抓字段。用户可以多次
    用不同筛选重复导出。请求了尚未采集的字段时，结果里明确列出缺失字段。
    """

    loaded = load_run(data_root, exact_run_id)
    root = Path(data_root).expanduser().absolute()
    exports = _ensure_exports_dir(root)
    token = secrets.token_hex(6)
    from media_missher_runtime.exporting import (
        ExportError,
        ExportOverwriteError,
        ExportSelection,
        describe_coverage,
        export_records,
    )

    where: dict[str, Any] = {}
    if filter_field is not None:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", filter_field):
            raise HistoryError("invalid export filter field")
        where[filter_field] = filter_value
    try:
        selection = ExportSelection(
            run_id=exact_run_id,
            record_kinds=tuple(record_kinds),
            format=format_name,
            platforms=tuple(platforms),
            targets=tuple(targets),
            topics=tuple(topics),
            fields=tuple(fields),
            field_groups=tuple(field_groups),
            where=where,
            file_name=file_name or f"historical-{exact_run_id}-{token}.{format_name}",
            overwrite=overwrite,
        )
        result = export_records(
            loaded["records"],
            selection,
            destination_root=exports,
            run_status=str(loaded["manifest"].get("status", "unknown")),
            observed_at=(loaded["observation_times"][-1] if loaded.get("observation_times") else None),
            backend=loaded["manifest"].get("backend") if isinstance(loaded["manifest"].get("backend"), str) else None,
        )
    except ExportOverwriteError as exc:
        raise HistoryError("export destination already exists") from exc
    except ExportError as exc:
        raise HistoryError(f"historical export selection is invalid: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise HistoryError(f"historical export failed: {type(exc).__name__}") from exc

    artifact = result.paths[0] if result.paths else ""
    metadata_path = exports / f"{Path(artifact).stem}.metadata.json" if artifact else exports / f"historical-{exact_run_id}-{token}.metadata.json"
    metadata = {
        "schema": 2,
        "kind": "historical-selection-export",
        "historical": True,
        "source_run_id": exact_run_id,
        "source_started_ns": loaded["context"]["started_ns"] if loaded["context"] else None,
        "source_created_at": loaded["context"]["created_at"] if loaded["context"] else None,
        "source_observation_times": loaded["observation_times"],
        "source_status": loaded["manifest"].get("status"),
        "source_backend": loaded["manifest"].get("backend", "cdp"),
        "selection": selection.to_json(),
        "counts": dict(result.counts),
        "rows": result.rows,
        "missing_fields": list(result.skipped_fields),
        "warnings": list(result.warnings),
        "coverage": describe_coverage(loaded["records"]),
        "output_filenames": [Path(path).name for path in result.paths],
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json_exclusive(metadata_path, metadata)
    return {**metadata, "output_path": artifact, "output_paths": list(result.paths), "metadata_path": str(metadata_path)}


def _record_observed_at(record: Mapping[str, Any]) -> Any:
    for key in ("observed_at", "engagement_observed_at", "detail_checked_at", "screenshot_observed_at"):
        value = record.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return value
    metric_times = record.get("metric_observed_at")
    if isinstance(metric_times, Mapping):
        for value in metric_times.values():
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                return value
    return None


def _metrics(record: Mapping[str, Any] | None) -> dict[str, int | float | None]:
    if record is None:
        return {}
    return {
        key: value
        for key in _METRICS
        if (value := record.get(key)) is None
        or (isinstance(value, (int, float)) and not isinstance(value, bool))
    }


def compare_runs(data_root: Path, before_run_id: str, after_run_id: str) -> dict[str, Any]:
    """Compare historical metrics by platform/native ID without freshness claims."""

    before, after = load_run(data_root, before_run_id), load_run(data_root, after_run_id)
    indexed: list[dict[tuple[str, str], dict[str, Any]]] = []
    for loaded in (before, after):
        indexed.append(
            {
                (platform, _native_id(record, platform)): record
                for platform, records in loaded["records_by_platform"].items()
                for record in records
            }
        )
    rows = []
    for platform, native in sorted(set(indexed[0]) | set(indexed[1])):
        old, new = indexed[0].get((platform, native)), indexed[1].get((platform, native))
        old_metrics, new_metrics = _metrics(old), _metrics(new)
        deltas = {
            key: new_metrics[key] - old_metrics[key]
            for key in _METRICS
            if isinstance(old_metrics.get(key), (int, float))
            and not isinstance(old_metrics.get(key), bool)
            and isinstance(new_metrics.get(key), (int, float))
            and not isinstance(new_metrics.get(key), bool)
        }
        rows.append(
            {
                "platform": platform,
                "native_id": native,
                "change": "matched" if old is not None and new is not None else "removed" if new is None else "added",
                "before_observed_at": _record_observed_at(old or {}),
                "after_observed_at": _record_observed_at(new or {}),
                "before_metrics": old_metrics,
                "after_metrics": new_metrics,
                "deltas": deltas,
            }
        )
    return {
        "historical": True,
        "freshness_claim": False,
        "before_run_id": before_run_id,
        "after_run_id": after_run_id,
        "records": rows,
    }
