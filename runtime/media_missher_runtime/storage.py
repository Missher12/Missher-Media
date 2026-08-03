from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


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
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target

    def write_manifest(
        self,
        *,
        counts: Mapping[str, int],
        status: str,
        paths: Mapping[str, str],
        **extra: object,
    ) -> Path:
        if extra:
            raise ValueError("manifest supports counts, status, and paths only")
        return self.write_json("manifest.json", {"counts": dict(counts), "status": status, "paths": dict(paths)})
