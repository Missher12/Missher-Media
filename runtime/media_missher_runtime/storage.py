from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DIAGNOSTIC_CODES = {
    "ok": frozenset({"ok"}),
    "result": frozenset({"count-shortfall", "incomplete-record"}),
    "not-run": frozenset({"preflight-aborted", "prior-risk-stop"}),
    "dependency": frozenset({"module-not-found"}),
    "precondition": frozenset({"precondition-failed"}),
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
        "incomplete": ("result", "incomplete-record"),
    }.get(status)
    if exact_result is not None and (kind, code) != exact_result:
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
            raise ValueError("manifest supports only the strict runtime schema")
        selected = set(platforms)
        if not selected or set(counts) != selected or set(diagnostics) != selected:
            raise ValueError("manifest platform keys do not match")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        ):
            raise ValueError("manifest counts are invalid")
        for platform in selected:
            _validate_diagnostic(platforms[platform], diagnostics[platform])
        if status not in {"complete", "failed", "risk-stopped"}:
            raise ValueError("manifest has an invalid overall status")
        expected_status = (
            "risk-stopped"
            if any(value == "risk-stopped" for value in platforms.values())
            else "complete"
            if all(value == "complete" for value in platforms.values())
            else "failed"
        )
        if status != expected_status:
            raise ValueError("manifest overall status is inconsistent")
        return self.write_json(
            "manifest.json",
            {
                "counts": dict(counts),
                "paths": dict(paths),
                "platforms": dict(platforms),
                "status": status,
                "diagnostics": {
                    platform: dict(diagnostics[platform]) for platform in platforms
                },
            },
        )
