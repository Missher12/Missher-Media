from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest


PNG = b"\x89PNG\r\n\x1a\nsynthetic"


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


@pytest.mark.parametrize("name", ("manifest.json", "./manifest.json", Path("manifest.json")))
def test_public_json_writer_reserves_manifest_name(tmp_path: Path, name: str | Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "reserved-manifest")

    with pytest.raises(ValueError, match="reserved"):
        store.write_json(name, {"untrusted": True})

    assert not (store.path / "manifest.json").exists()


def test_manifest_accepts_only_strict_status_and_diagnostic_metadata(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "manifest")
    manifest = store.write_manifest(
        counts={"bilibili": 0},
        paths={},
        platforms={"bilibili": "shortfall"},
        status="failed",
        diagnostics={
            "bilibili": {"kind": "result", "code": "count-shortfall"}
        },
    )

    assert json.loads(manifest.read_text(encoding="utf-8")) == {
        "counts": {"bilibili": 0},
        "paths": {},
        "platforms": {"bilibili": "shortfall"},
        "status": "failed",
        "diagnostics": {
            "bilibili": {"kind": "result", "code": "count-shortfall"}
        },
    }
    with pytest.raises(ValueError, match="manifest"):
        store.write_manifest(
            counts={},
            paths={},
            platforms={},
            status="complete",
            diagnostics={},
            extra="not allowed",
        )


@pytest.mark.parametrize(
    ("counts", "paths", "platforms", "status", "diagnostics"),
    (
        (
            {"unknown": 0},
            {},
            {"unknown": "shortfall"},
            "failed",
            {"unknown": {"kind": "result", "code": "count-shortfall"}},
        ),
        (
            {"bilibili": 0},
            {"unexpected": "unexpected.json"},
            {"bilibili": "shortfall"},
            "failed",
            {"bilibili": {"kind": "result", "code": "count-shortfall"}},
        ),
        (
            {"bilibili": 0},
            {"xhs_report": "xhs_report.json"},
            {"bilibili": "shortfall"},
            "failed",
            {"bilibili": {"kind": "result", "code": "count-shortfall"}},
        ),
        (
            {"bilibili": 0},
            {"bilibili": "https://example.invalid/bilibili.json?uid=private"},
            {"bilibili": "shortfall"},
            "failed",
            {"bilibili": {"kind": "result", "code": "count-shortfall"}},
        ),
        (
            {"bilibili": 0},
            {"bilibili": "bilibili.json?uid=private"},
            {"bilibili": "shortfall"},
            "failed",
            {"bilibili": {"kind": "result", "code": "count-shortfall"}},
        ),
        (
            {"bilibili": 0},
            {"bilibili": "bilibili-private-uid.json"},
            {"bilibili": "shortfall"},
            "failed",
            {"bilibili": {"kind": "result", "code": "count-shortfall"}},
        ),
        (
            {"bilibili": 0},
            {"bilibili": "/tmp/bilibili.json"},
            {"bilibili": "shortfall"},
            "failed",
            {"bilibili": {"kind": "result", "code": "count-shortfall"}},
        ),
        (
            {"xhs": 0},
            {"xhs": "xhs.json", "xhs_report": "xhs.json"},
            {"xhs": "complete"},
            "complete",
            {"xhs": {"kind": "ok", "code": "ok"}},
        ),
        (
            {"weibo": 0},
            {},
            {"weibo": "complete"},
            "complete",
            {"weibo": {"kind": "ok", "code": "ok"}},
        ),
    ),
)
def test_manifest_rejects_unknown_platforms_and_unsafe_artifact_contracts(
    tmp_path: Path,
    counts: dict[str, int],
    paths: dict[str, str],
    platforms: dict[str, str],
    status: str,
    diagnostics: dict[str, dict[str, str]],
) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "strict-artifacts")

    with pytest.raises(ValueError, match="manifest"):
        store.write_manifest(
            counts=counts,
            paths=paths,
            platforms=platforms,
            status=status,
            diagnostics=diagnostics,
        )


def test_manifest_accepts_exact_xhs_content_and_aggregate_basenames(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "xhs-artifacts")
    target = store.write_manifest(
        counts={"xhs": 1},
        paths={
            "xhs": "xhs.json",
            "xhs_report": "xhs_report.json",
            "xhs_checkpoint": "xhs_checkpoint.json",
        },
        platforms={"xhs": "complete"},
        status="complete",
        diagnostics={"xhs": {"kind": "ok", "code": "ok"}},
    )

    assert json.loads(target.read_text(encoding="utf-8"))["paths"] == {
        "xhs": "xhs.json",
        "xhs_report": "xhs_report.json",
        "xhs_checkpoint": "xhs_checkpoint.json",
    }


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


def test_run_store_writes_private_png_atomically(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "png")
    target = store.write_private_bytes("screenshots/xhs-note-123.png", PNG)

    assert target.read_bytes() == PNG
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "name",
    (
        "/tmp/private.png",
        "../private.png",
        "screenshots/../private.png",
        "other/private.png",
        "screenshots/private.jpg",
        "screenshots/.png",
    ),
)
def test_private_png_writer_rejects_unsafe_paths(tmp_path: Path, name: str) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "unsafe-png")

    with pytest.raises(ValueError):
        store.write_private_bytes(name, PNG)


@pytest.mark.parametrize("payload", (b"not-png", b""))
def test_private_png_writer_rejects_non_png_payload(
    tmp_path: Path, payload: bytes
) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "invalid-png")

    with pytest.raises(ValueError, match="PNG"):
        store.write_private_bytes("screenshots/xhs-note.png", payload)


def test_private_png_writer_never_overwrites_file_or_symlink(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "occupied-png")
    screenshot_dir = store.path / "screenshots"
    screenshot_dir.mkdir(mode=0o700)
    target = screenshot_dir / "xhs-note.png"
    target.write_bytes(b"protected")

    with pytest.raises(FileExistsError):
        store.write_private_bytes("screenshots/xhs-note.png", PNG)
    assert target.read_bytes() == b"protected"

    target.unlink()
    protected = tmp_path / "protected.png"
    protected.write_bytes(b"protected")
    target.symlink_to(protected)
    with pytest.raises(FileExistsError):
        store.write_private_bytes("screenshots/xhs-note.png", PNG)
    assert protected.read_bytes() == b"protected"


def test_private_png_writer_rejects_symlink_screenshot_directory(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.storage import RunStore

    store = RunStore.create(tmp_path, "symlink-dir")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.path / "screenshots").symlink_to(outside)

    with pytest.raises(ValueError, match="directory"):
        store.write_private_bytes("screenshots/xhs-note.png", PNG)

    assert list(outside.iterdir()) == []


def test_private_png_writer_closes_descriptor_when_fdopen_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime.media_missher_runtime import storage

    store = storage.RunStore.create(tmp_path, "fdopen-failure")
    captured: list[int] = []

    def fail_fdopen(descriptor: int, *_args: object, **_kwargs: object) -> object:
        captured.append(descriptor)
        raise RuntimeError("synthetic fdopen failure")

    monkeypatch.setattr(storage.os, "fdopen", fail_fdopen)

    with pytest.raises(RuntimeError, match="synthetic"):
        store.write_private_bytes("screenshots/xhs-note.png", PNG)

    assert len(captured) == 1
    with pytest.raises(OSError):
        os.fstat(captured[0])
