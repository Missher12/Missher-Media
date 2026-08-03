from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest


def test_run_store_creates_a_private_unique_run_directory(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "alpha")

    assert store.path == tmp_path / "run-alpha"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o700
    with pytest.raises(FileExistsError):
        RunStore.create(tmp_path, "alpha")


def test_run_store_writes_private_json_without_losing_values(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "data")
    target = store.write_json("records.json", {"zero": 0, "null": None, "nested": {"item": [0, None]}})

    assert json.loads(target.read_text(encoding="utf-8")) == {"zero": 0, "null": None, "nested": {"item": [0, None]}}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_manifest_accepts_only_counts_status_and_path_metadata(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "manifest")
    manifest = store.write_manifest(counts={"records": 0}, status="complete", paths={"records": "records.json"})

    assert json.loads(manifest.read_text(encoding="utf-8")) == {
        "counts": {"records": 0},
        "status": "complete",
        "paths": {"records": "records.json"},
    }
    with pytest.raises(ValueError, match="manifest"):
        store.write_manifest(counts={}, status="complete", paths={}, extra="not allowed")
