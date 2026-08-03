import json
import os
import shlex
import shutil
import stat
import sys
import time
from pathlib import Path

from media_missher_adapter import (
    CollectionRequest,
    ConfigurationError,
    build_engine_command,
    create_run_directory,
    discover_current_json,
    execute_engine,
    read_output,
    resolve_runtime_layout,
    run_collection_request,
)


def ok_preflight(*_args, **_kwargs):
    return {"status": "ok", "checks": {"synthetic": True}, "errors": []}


NESTED_RUNTIME_SOURCE = r'''#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from pathlib import Path

PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")

parser = argparse.ArgumentParser()
parser.add_argument("--count", "--max", dest="count", type=int, default=1)
parser.add_argument("--format", default="json")
parser.add_argument("--output", type=Path, required=False)
parser.add_argument("--platform")
parser.add_argument("--platform-timeout", type=float, default=300)
parser.add_argument("--xhs-comments", type=int, default=0)
parser.add_argument("--comments", type=int, default=0)
parser.add_argument("--complete", action="store_true")
parser.add_argument("--bilibili-complete", action="store_true")
parser.add_argument("--xhs-complete", action="store_true")
parser.add_argument("--no-feishu", action="store_true")
parser.add_argument("--search")
for platform in PLATFORMS:
    parser.add_argument(f"--{platform}-count", type=int)
    parser.add_argument(f"--{platform}-uid")
args = parser.parse_args()
mode = os.environ.get("MEDIA_MISSHER_FAKE_MODE", "ok")
if mode == "sleep":
    time.sleep(float(os.environ.get("MEDIA_MISSHER_FAKE_SLEEP", "5")))
if mode == "risk_wait":
    print("risk signal 471: synthetic stop", file=sys.stderr, flush=True)
    time.sleep(float(os.environ.get("MEDIA_MISSHER_FAKE_SLEEP", "5")))
if mode == "blocked_wait":
    print("account blocked: synthetic stop", file=sys.stderr, flush=True)
    time.sleep(float(os.environ.get("MEDIA_MISSHER_FAKE_SLEEP", "5")))
if mode == "benign_log":
    print("synthetic unlocked state", file=sys.stderr, flush=True)

outer = args.output or Path.cwd()
outer.mkdir(parents=True, exist_ok=True)
inner = outer / f"run-{time.time_ns()}-synthetic"
inner.mkdir(mode=0o700)
(inner / "received_argv.txt").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
script_name = Path(sys.argv[0]).name
platforms = tuple((args.platform or ",".join(PLATFORMS)).split(",")) if script_name == "scrape_all.py" else (script_name.removeprefix("scrape_").removesuffix(".py"),)
paths = {}
counts = {}
statuses = {}
for platform in platforms:
    requested = getattr(args, f"{platform}_count", None)
    count = requested if requested is not None else args.count
    count = max(1, count)
    cap = os.environ.get("MEDIA_MISSHER_FAKE_COUNT_CAP")
    if cap is not None:
        count = min(count, max(0, int(cap)))
    counts[platform] = count
    statuses[platform] = "complete"
    records = [{
        "platform": platform,
        {"bilibili": "dynamic_id", "xhs": "note_id", "douyin": "aweme_id", "weibo": "mblog_id"}[platform]: f"synthetic-{platform}-{index}",
        "title": "synthetic title",
        "link": f"https://example.invalid/{platform}/{index}",
        "date": "2026-01-01",
        "liked": 1,
        "comments": 2,
        "shares": 3,
        "collected": 4,
    } for index in range(count)]
    if mode != "manifest_missing_data":
        artifact = inner / f"{platform}.json"
        artifact.write_text(json.dumps(records), encoding="utf-8")
        artifact.chmod(0o600)
        paths[platform] = artifact.name

if "xhs" in platforms:
    report = inner / "xhs_report.json"
    report.write_text(json.dumps({"status": "complete", "started_at": 1, "finished_at": 2, "final_items": counts["xhs"]}), encoding="utf-8")
    report.chmod(0o600)
    paths["xhs_report"] = report.name
    checkpoint = inner / "xhs_checkpoint.json"
    checkpoint.write_text(json.dumps({"items": [{"note_id": "synthetic-xhs-0", "observed_at": "2026-01-01T00:00:00Z"}]}), encoding="utf-8")
    checkpoint.chmod(0o600)
    paths["xhs_checkpoint"] = checkpoint.name

manifest_status = "risk-stopped" if mode == "manifest_risk" else "complete"
if mode == "manifest_risk":
    statuses[platforms[-1]] = "risk-stopped"
manifest = inner / "manifest.json"
manifest.write_text(json.dumps({"counts": counts, "paths": paths, "platforms": statuses, "status": manifest_status}), encoding="utf-8")
manifest.chmod(0o600)
print("synthetic collection complete")
raise SystemExit(75 if mode == "manifest_risk" else 0)
'''


def make_runtime_layout(fake_engine_root):
    home = fake_engine_root.parent / "runtime-home"
    shutil.copytree(fake_engine_root / "scripts", home / "current" / "scripts")
    interpreter = home / "venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ] && [ \"$2\" = \"import playwright\" ]; then exit 0; fi\n"
        f"exec {shlex.quote(str(Path(sys.executable).resolve()))} \"$@\"\n",
        encoding="utf-8",
    )
    interpreter.chmod(0o700)
    for script in (home / "current" / "scripts").glob("scrape_*.py"):
        script.write_text(NESTED_RUNTIME_SOURCE, encoding="utf-8")
    (home / "state").mkdir(mode=0o700)
    return resolve_runtime_layout(environ={"MEDIA_MISSHER_HOME": str(home)})


def test_run_directories_are_unique_and_private(tmp_path):
    first = create_run_directory(tmp_path)
    second = create_run_directory(tmp_path)
    assert first != second
    assert stat.S_IMODE(first.stat().st_mode) == 0o700
    assert stat.S_IMODE(second.stat().st_mode) == 0o700


def test_execute_engine_captures_evidence_and_never_creates_feishu(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    run_dir = create_run_directory(tmp_path)
    request = CollectionRequest(platforms=("bilibili", "xhs"), count=1)
    command = build_engine_command(request, run_dir, layout=layout)
    completed = execute_engine(command, timeout=5, run_dir=run_dir)
    assert completed.returncode == 0
    assert completed.timed_out is False
    assert completed.stdout_path.read_text(encoding="utf-8")
    assert not list(run_dir.glob("feishu_*"))
    received_path = next(run_dir.glob("run-*/received_argv.txt"))
    received = json.loads(received_path.read_text(encoding="utf-8"))
    assert "--no-feishu" in received


def test_execute_engine_times_out_only_its_child(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    run_dir = create_run_directory(tmp_path)
    request = CollectionRequest(platforms=("bilibili",), count=1)
    command = build_engine_command(request, run_dir, layout=layout)
    command = command.with_environment(
        {"MEDIA_MISSHER_FAKE_MODE": "sleep", "MEDIA_MISSHER_FAKE_SLEEP": "5"}
    )
    completed = execute_engine(command, timeout=0.1, run_dir=run_dir)
    assert completed.timed_out is True
    assert completed.returncode is not None


def test_discover_current_json_rejects_stale_files(tmp_path):
    inner = tmp_path / "run-current"
    inner.mkdir(mode=0o700)
    stale = inner / "stale.json"
    stale.write_text("[]", encoding="utf-8")
    started_ns = time.time_ns()
    os.utime(stale, ns=(started_ns - 10_000, started_ns - 10_000))
    current = inner / "bilibili.json"
    current.write_text("[]", encoding="utf-8")
    manifest = inner / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "counts": {"bilibili": 0},
                "paths": {"bilibili": current.name},
                "platforms": {"bilibili": "shortfall"},
                "status": "failed",
            }
        ),
        encoding="utf-8",
    )

    discovered = discover_current_json(tmp_path, started_ns=started_ns)

    assert current.resolve() in discovered
    assert manifest.resolve() in discovered
    assert stale.resolve() not in discovered


def test_discover_current_json_rejects_multiple_fresh_inner_runs(tmp_path):
    started_ns = time.time_ns()
    for name in ("run-one", "run-two"):
        inner = tmp_path / name
        inner.mkdir(mode=0o700)
        (inner / "manifest.json").write_text(
            json.dumps({"counts": {}, "paths": {}, "platforms": {}, "status": "failed"}),
            encoding="utf-8",
        )

    with __import__("pytest").raises(ConfigurationError, match="exactly one fresh runtime run"):
        discover_current_json(tmp_path, started_ns=started_ns)


def test_discover_current_json_rejects_unexpected_manifest_path_key(tmp_path):
    started_ns = time.time_ns()
    inner = tmp_path / "run-current"
    inner.mkdir(mode=0o700)
    (inner / "unexpected.json").write_text("[]", encoding="utf-8")
    (inner / "manifest.json").write_text(
        json.dumps(
            {
                "counts": {"xhs": 1},
                "paths": {"unexpected": "unexpected.json"},
                "platforms": {"xhs": "complete"},
                "status": "complete",
            }
        ),
        encoding="utf-8",
    )

    with __import__("pytest").raises(ConfigurationError, match="unexpected manifest path key"):
        discover_current_json(tmp_path, started_ns=started_ns)


def test_discover_current_json_requires_path_for_completed_platform(tmp_path):
    started_ns = time.time_ns()
    inner = tmp_path / "run-current"
    inner.mkdir(mode=0o700)
    (inner / "manifest.json").write_text(
        json.dumps(
            {
                "counts": {"xhs": 1},
                "paths": {},
                "platforms": {"xhs": "complete"},
                "status": "complete",
            }
        ),
        encoding="utf-8",
    )

    with __import__("pytest").raises(ConfigurationError, match="completed platform path"):
        discover_current_json(tmp_path, started_ns=started_ns)


def test_discover_current_json_rejects_duplicate_manifest_keys(tmp_path):
    started_ns = time.time_ns()
    inner = tmp_path / "run-current"
    inner.mkdir(mode=0o700)
    (inner / "manifest.json").write_text(
        '{"counts": {}, "counts": {}, "paths": {}, "platforms": {}, "status": "failed"}',
        encoding="utf-8",
    )

    with __import__("pytest").raises(ConfigurationError, match="duplicate key"):
        discover_current_json(tmp_path, started_ns=started_ns)


def test_discover_current_json_rejects_invalid_xhs_checkpoint(tmp_path):
    started_ns = time.time_ns()
    inner = tmp_path / "run-current"
    inner.mkdir(mode=0o700)
    (inner / "xhs.json").write_text("[]", encoding="utf-8")
    (inner / "xhs_checkpoint.json").write_text("{}", encoding="utf-8")
    (inner / "manifest.json").write_text(
        json.dumps(
            {
                "counts": {"xhs": 0},
                "paths": {
                    "xhs": "xhs.json",
                    "xhs_checkpoint": "xhs_checkpoint.json",
                },
                "platforms": {"xhs": "complete"},
                "status": "complete",
            }
        ),
        encoding="utf-8",
    )

    with __import__("pytest").raises(ConfigurationError, match="checkpoint"):
        discover_current_json(tmp_path, started_ns=started_ns)


def test_run_collection_returns_success_with_current_evidence(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    summary = run_collection_request(
        CollectionRequest(platforms=("douyin",), count=1),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
    )
    assert summary["status"] == "success"
    assert len(summary["evidence"]) == 1
    assert Path(summary["run_dir"]).is_dir()
    assert summary["validation"]["counts"] == {"douyin": 1}


def test_run_collection_converts_only_after_validation(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    summary = run_collection_request(
        CollectionRequest(platforms=("weibo",), count=1, output_format="csv"),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
    )
    assert summary["status"] == "success"
    assert len(summary["outputs"]) == 1
    converted = Path(summary["outputs"][0])
    assert converted.suffix == ".csv"
    assert len(read_output(converted, "csv")) == 1
    assert not list(Path(summary["run_dir"]).glob("feishu_*"))


def test_run_collection_uses_validated_count_for_partial_status(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    summary = run_collection_request(
        CollectionRequest(platforms=("bilibili",), count=2),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
        command_environment={"MEDIA_MISSHER_FAKE_COUNT_CAP": "1"},
    )
    assert summary["status"] == "partial"
    assert summary["validation"]["counts"] == {"bilibili": 1}


def test_run_collection_classifies_risk_and_stops(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    started = time.monotonic()
    summary = run_collection_request(
        CollectionRequest(platforms=("xhs",), count=1),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
        command_environment={"MEDIA_MISSHER_FAKE_MODE": "risk_wait"},
    )
    assert summary["status"] == "risk-stopped"
    assert summary["evidence"] == []
    assert time.monotonic() - started < 2


def test_run_collection_classifies_blocked_and_stops(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    started = time.monotonic()
    summary = run_collection_request(
        CollectionRequest(platforms=("xhs",), count=1),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
        command_environment={"MEDIA_MISSHER_FAKE_MODE": "blocked_wait"},
    )
    assert summary["status"] == "risk-stopped"
    assert summary["evidence"] == []
    assert time.monotonic() - started < 2


def test_run_collection_does_not_treat_unlocked_as_a_risk_signal(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    summary = run_collection_request(
        CollectionRequest(platforms=("xhs",), count=1),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
        command_environment={"MEDIA_MISSHER_FAKE_MODE": "benign_log"},
    )
    assert summary["status"] == "success"
    assert summary["validation"]["counts"] == {"xhs": 1}


def test_run_collection_stops_before_directory_when_preflight_fails(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    summary = run_collection_request(
        CollectionRequest(platforms=("weibo",), count=1),
        layout=layout,
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
    layout = make_runtime_layout(fake_engine_root)
    layout.python.unlink()
    summary = run_collection_request(
        CollectionRequest(platforms=("bilibili",), count=1),
        layout=layout,
        data_root=tmp_path / "runs",
        preflight_runner=ok_preflight,
    )
    assert summary["status"] == "failed"
    assert summary["evidence"] == []
    assert any("python" in error for error in summary["errors"])


def test_engine_command_uses_absolute_shared_runtime_paths(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)

    command = build_engine_command(
        CollectionRequest(platforms=("bilibili", "xhs"), count=2, xhs_complete=True),
        tmp_path,
        layout=layout,
    )

    assert command.script == (layout.current / "scripts" / "scrape_all.py")
    assert command.argv[:2] == (str(layout.python), str(command.script))
    assert all(Path(value).is_absolute() for value in command.argv[:2])
    assert command.environment["MEDIA_MISSHER_HOME"] == str(layout.home)
    assert "--platform" in command.argv
    assert "--xhs-complete" in command.argv
    assert "--no-feishu" in command.argv


def test_nested_runtime_manifest_and_complete_xhs_report_are_diagnostics(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)

    summary = run_collection_request(
        CollectionRequest(platforms=("xhs",), count=1),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
    )

    assert summary["status"] == "success"
    assert [Path(path).name for path in summary["evidence"]] == ["xhs.json"]
    assert {item["status"] for item in summary["validation"]["diagnostics"]} == {
        "complete"
    }


def test_manifest_cannot_replace_missing_platform_data(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)

    summary = run_collection_request(
        CollectionRequest(platforms=("xhs",), count=1),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
        command_environment={"MEDIA_MISSHER_FAKE_MODE": "manifest_missing_data"},
    )

    assert summary["status"] == "failed"
    assert summary["evidence"] == []
    assert summary["validation"]["counts"] == {"xhs": 0}


def test_manifest_risk_status_wins_over_partial_platform_data(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)

    summary = run_collection_request(
        CollectionRequest(platforms=("xhs",), count=1),
        layout=layout,
        data_root=tmp_path,
        preflight_runner=ok_preflight,
        execution_timeout=5,
        command_environment={"MEDIA_MISSHER_FAKE_MODE": "manifest_risk"},
    )

    assert summary["status"] == "risk-stopped"
    assert [Path(path).name for path in summary["evidence"]] == ["xhs.json"]
