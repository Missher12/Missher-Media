from __future__ import annotations

import json
import os
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


def test_atomic_json_syncs_file_and_containing_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.media_missher_runtime import storage

    store = storage.RunStore.create(tmp_path, "durable")
    real_open = os.open
    real_close = os.close
    real_fsync = os.fsync
    real_replace = os.replace
    directory_descriptors: set[int] = set()
    events: list[str] = []

    def recording_open(path: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int, mode: int = 0o777) -> int:
        descriptor = real_open(path, flags, mode)
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_descriptors.add(descriptor)
            events.append("open-directory")
        return descriptor

    def recording_fsync(descriptor: int) -> None:
        events.append("fsync-directory" if descriptor in directory_descriptors else "fsync-file")
        real_fsync(descriptor)

    def recording_replace(source: str | bytes | os.PathLike[str] | os.PathLike[bytes], target: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> None:
        events.append("replace")
        real_replace(source, target)

    def recording_close(descriptor: int) -> None:
        if descriptor in directory_descriptors:
            events.append("close-directory")
            directory_descriptors.remove(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(storage.os, "open", recording_open)
    monkeypatch.setattr(storage.os, "fsync", recording_fsync)
    monkeypatch.setattr(storage.os, "replace", recording_replace)
    monkeypatch.setattr(storage.os, "close", recording_close)

    store.write_json("durable.json", {"ready": True})

    assert events.count("fsync-file") == 1
    assert events[-3:] == ["open-directory", "fsync-directory", "close-directory"]
    assert events.index("replace") < events.index("fsync-directory")
