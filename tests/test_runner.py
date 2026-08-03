import json
import os
import stat
import time
from pathlib import Path

from media_missher_adapter import (
    CollectionRequest,
    build_engine_command,
    create_run_directory,
    discover_current_json,
    execute_engine,
    run_collection_request,
)


def ok_preflight(*_args, **_kwargs):
    return {"status": "ok", "checks": {"synthetic": True}, "errors": []}


def test_run_directories_are_unique_and_private(tmp_path):
    first = create_run_directory(tmp_path)
    second = create_run_directory(tmp_path)
    assert first != second
    assert stat.S_IMODE(first.stat().st_mode) == 0o700
    assert stat.S_IMODE(second.stat().st_mode) == 0o700


def test_execute_engine_captures_evidence_and_never_creates_feishu(fake_engine_root, tmp_path):
    run_dir = create_run_directory(tmp_path)
    request = CollectionRequest(platforms=("bilibili", "xhs"), count=1)
    command = build_engine_command(request, run_dir, engine_root=fake_engine_root)
    completed = execute_engine(command, timeout=5, run_dir=run_dir)
    assert completed.returncode == 0
    assert completed.timed_out is False
    assert completed.stdout_path.read_text(encoding="utf-8")
    assert not list(run_dir.glob("feishu_*"))
    received = json.loads((run_dir / "received_argv.txt").read_text(encoding="utf-8"))
    assert "--no-feishu" in received


def test_execute_engine_times_out_only_its_child(fake_engine_root, tmp_path):
    run_dir = create_run_directory(tmp_path)
    request = CollectionRequest(platforms=("bilibili",), count=1)
    command = build_engine_command(request, run_dir, engine_root=fake_engine_root)
    command = command.with_environment(
        {"MEDIA_MISSHER_FAKE_MODE": "sleep", "MEDIA_MISSHER_FAKE_SLEEP": "5"}
    )
    completed = execute_engine(command, timeout=0.1, run_dir=run_dir)
    assert completed.timed_out is True
    assert completed.returncode is not None


def test_discover_current_json_rejects_stale_files(tmp_path):
    stale = tmp_path / "stale.json"
    stale.write_text("[]", encoding="utf-8")
    started_ns = time.time_ns()
    os.utime(stale, ns=(started_ns - 10_000, started_ns - 10_000))
    current = tmp_path / "current.json"
    current.write_text("[]", encoding="utf-8")
    assert discover_current_json(tmp_path, started_ns=started_ns) == (current.resolve(),)


def test_run_collection_returns_success_with_current_evidence(fake_engine_root, tmp_path):
    summary = run_collection_request(
        CollectionRequest(platforms=("douyin",), count=1),
        engine_root=fake_engine_root,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
    )
    assert summary["status"] == "success"
    assert len(summary["evidence"]) == 1
    assert Path(summary["run_dir"]).is_dir()


def test_run_collection_classifies_risk_and_stops(fake_engine_root, tmp_path):
    summary = run_collection_request(
        CollectionRequest(platforms=("xhs",), count=1),
        engine_root=fake_engine_root,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
        command_environment={"MEDIA_MISSHER_FAKE_MODE": "risk"},
    )
    assert summary["status"] == "risk-stopped"
    assert summary["evidence"] == []


def test_run_collection_stops_before_directory_when_preflight_fails(fake_engine_root, tmp_path):
    summary = run_collection_request(
        CollectionRequest(platforms=("weibo",), count=1),
        engine_root=fake_engine_root,
        data_root=tmp_path,
        preflight_runner=lambda *_args, **_kwargs: {
            "status": "failed",
            "checks": {"cdp": False},
            "errors": ["CDP unavailable"],
        },
    )
    assert summary["status"] == "preflight-failed"
    assert summary["run_dir"] is None
    assert not list(tmp_path.glob("run-*"))


def test_run_collection_returns_structured_failure_when_engine_disappears(fake_engine_root, tmp_path):
    (fake_engine_root / "engine" / ".venv" / "bin" / "python").unlink()
    summary = run_collection_request(
        CollectionRequest(platforms=("bilibili",), count=1),
        engine_root=fake_engine_root,
        data_root=tmp_path / "runs",
        preflight_runner=ok_preflight,
    )
    assert summary["status"] == "failed"
    assert summary["evidence"] == []
    assert any("interpreter" in error for error in summary["errors"])
