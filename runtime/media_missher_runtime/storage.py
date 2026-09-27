from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


#: Platforms the private run manifest accepts. The manifest schema itself is
#: unchanged; only the accepted platform names grow.
PLATFORMS = frozenset({"bilibili", "xhs", "douyin", "weibo", "x"})
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PRIVATE_BYTES = 50 * 1024 * 1024
_PNG_BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}\.png")

DIAGNOSTIC_CODES = {
    "ok": frozenset({"ok"}),
    "result": frozenset(
        {"count-shortfall", "incomplete-record", "screenshot-shortfall"}
    ),
    "not-run": frozenset({"preflight-aborted", "prior-risk-stop"}),
    "dependency": frozenset({"module-not-found"}),
    "precondition": frozenset(
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
            "xhs-cooldown",
            "xhs-risk-latched",
            "xhs-safety-busy",
            "xhs-safety-state-invalid",
        }
    ),
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


def _validate_diagnostic(status: object, value: object) -> None:
    if not isinstance(status, str) or status not in _STATUS_KINDS:
        raise ValueError("manifest has an invalid platform status")
    if not isinstance(value, Mapping) or set(value) != {"kind", "code"}:
        raise ValueError("manifest has an invalid diagnostic schema")
    kind, code = value.get("kind"), value.get("code")
    if (
        not isinstance(kind, str)
        or not isinstance(code, str)
        or kind not in DIAGNOSTIC_CODES
        or code not in DIAGNOSTIC_CODES[kind]
        or kind not in _STATUS_KINDS[status]
    ):
        raise ValueError("manifest has an invalid diagnostic value")
    exact_result = {
        "complete": ("ok", "ok"),
        "shortfall": ("result", "count-shortfall"),
    }.get(status)
    if exact_result is not None and (kind, code) != exact_result:
        raise ValueError("manifest status and diagnostic do not match")
    if status == "incomplete" and (kind, code) not in {
        ("result", "incomplete-record"),
        ("result", "screenshot-shortfall"),
    }:
        raise ValueError("manifest status and diagnostic do not match")


@dataclass(frozen=True, slots=True)
class RunStore:
    path: Path

    @classmethod
    def create(cls, root: Path | str, run_id: str) -> "RunStore":
        path = Path(root) / f"run-{run_id}"
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(path, 0o700)
        return cls(path)

    def write_json(self, name: str, value: Any) -> Path:
        target = self.path / name
        if target.name == "manifest.json":
            raise ValueError("manifest.json is reserved for write_manifest")
        return self._write_json_atomic(name, value)

    def _write_json_atomic(self, name: str, value: Any) -> Path:
        target = self.path / name
        if target.parent != self.path:
            raise ValueError("JSON path must stay inside the run directory")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=self.path)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
            os.chmod(target, 0o600)
            directory_descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target

    def write_private_bytes(self, relative_name: str, payload: bytes) -> Path:
        if not isinstance(relative_name, str):
            raise ValueError("private artifact path must be a string")
        relative = Path(relative_name)
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or relative.parts[0] != "screenshots"
            or relative.parts[1] in {".", ".."}
            or _PNG_BASENAME.fullmatch(relative.parts[1]) is None
        ):
            raise ValueError("private PNG path is unsafe")
        if (
            not isinstance(payload, bytes)
            or not payload.startswith(PNG_SIGNATURE)
            or len(payload) > MAX_PRIVATE_BYTES
        ):
            raise ValueError("private artifact must be a bounded PNG")

        screenshot_dir = self.path / "screenshots"
        if os.path.lexists(screenshot_dir):
            if screenshot_dir.is_symlink() or not screenshot_dir.is_dir():
                raise ValueError("screenshot directory is unsafe")
        else:
            screenshot_dir.mkdir(mode=0o700)
        os.chmod(screenshot_dir, 0o700)

        target = screenshot_dir / relative.parts[1]
        if os.path.lexists(target):
            raise FileExistsError(target)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".tmp-", suffix=".png", dir=screenshot_dir
        )
        try:
            try:
                os.fchmod(descriptor, 0o600)
                handle = os.fdopen(descriptor, "wb")
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if os.path.lexists(target):
                raise FileExistsError(target)
            os.replace(temporary_name, target)
            os.chmod(target, 0o600)
            directory_descriptor = os.open(
                screenshot_dir,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if os.path.lexists(temporary_name):
                os.unlink(temporary_name)
        return target

    def write_manifest(
        self,
        *,
        counts: Mapping[str, int],
        paths: Mapping[str, str],
        platforms: Mapping[str, str],
        status: str,
        diagnostics: Mapping[str, Mapping[str, str]],
        **extra: object,
    ) -> Path:
        if extra:
            if set(extra) != {"schema_version", "backend", "record_kinds"} or extra["schema_version"] != 3:
                raise ValueError("manifest supports only the strict runtime schema")
            if extra["backend"] != "cdp":
                raise ValueError("manifest backend is invalid")
            kinds = extra["record_kinds"]
            if not isinstance(kinds, dict) or set(kinds) - {"posts", "user_profiles", "topic_participants"} or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in kinds.values()
            ):
                raise ValueError("manifest record kinds are invalid")
        selected = set(platforms)
        if (
            not selected
            or not selected.issubset(PLATFORMS)
            or set(counts) != selected
            or set(diagnostics) != selected
        ):
            raise ValueError("manifest platform keys do not match")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        ):
            raise ValueError("manifest counts are invalid")
        allowed_paths = set(selected)
        if "xhs" in selected:
            allowed_paths.update({"xhs_report", "xhs_checkpoint"})
        if set(paths) - allowed_paths:
            raise ValueError("manifest has an unexpected artifact key")
        if any(not isinstance(value, str) for value in paths.values()):
            raise ValueError("manifest artifact paths must be strings")
        if len(set(paths.values())) != len(paths):
            raise ValueError("manifest artifact paths must be unique")
        if any(value != f"{key}.json" for key, value in paths.items()):
            raise ValueError("manifest artifact paths must be exact safe basenames")
        if any(
            platform_status == "complete" and platform not in paths
            for platform, platform_status in platforms.items()
        ):
            raise ValueError("manifest is missing a completed platform artifact")
        for platform in selected:
            _validate_diagnostic(platforms[platform], diagnostics[platform])
        if status not in ({"complete", "failed", "risk-stopped", "partial"} if extra else {"complete", "failed", "risk-stopped"}):
            raise ValueError("manifest has an invalid overall status")
        expected_status = (
            "risk-stopped"
            if any(value == "risk-stopped" for value in platforms.values())
            else "complete"
            if all(value == "complete" for value in platforms.values())
            else "failed"
        )
        if extra and expected_status == "failed" and any(counts.values()):
            expected_status = "partial"
        if status != expected_status:
            raise ValueError("manifest overall status is inconsistent")
        return self._write_json_atomic(
            "manifest.json",
            {
                **extra,
                "counts": dict(counts),
                "paths": dict(paths),
                "platforms": dict(platforms),
                "status": status,
                "diagnostics": {
                    platform: dict(diagnostics[platform]) for platform in platforms
                },
            },
        )

    def commit_snapshot(self) -> Path:
        """One atomic envelope is the recovery authority for accepted prefixes.

        Legacy JSON files remain readable by existing clients. A crash between
        their individual replacements cannot invalidate the preceding envelope.
        """
        with (self.path / "manifest.json").open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        artifacts = {}
        for key, name in manifest["paths"].items():
            with (self.path / name).open(encoding="utf-8") as handle:
                artifacts[key] = json.load(handle)
        return self._write_json_atomic("committed.json", {"schema": 1, "manifest": manifest, "artifacts": artifacts})
