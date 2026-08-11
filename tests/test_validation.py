import json
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from media_missher_adapter import CollectionRequest, validate_run


FIXTURES = Path(__file__).parent / "fixtures"
PNG = b"\x89PNG\r\n\x1a\nsynthetic-private-evidence"


def copy_fixture(tmp_path, name, *, started_ns=None):
    destination = tmp_path / name
    destination.write_text((FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8")
    if started_ns is not None:
        os.utime(destination, ns=(started_ns + 1, started_ns + 1))
    return destination


def screenshot_evidence(tmp_path, *, case="valid", request_mode="all"):
    started_ns = time.time_ns() - 1_000_000_000
    inner = tmp_path / "run-engine"
    screenshot_dir = inner / "screenshots"
    screenshot_dir.mkdir(parents=True)
    records = json.loads(
        (FIXTURES / "bilibili_creator.json").read_text(encoding="utf-8")
    )
    identity = records[0].get("bvid") or records[0]["dynamic_id"]
    filename = f"bilibili-{identity}.png"
    screenshot = screenshot_dir / filename
    screenshot.write_bytes(PNG if case != "non-png" else b"not-a-png")
    screenshot.chmod(0o600)
    os.utime(screenshot, ns=(started_ns + 1, started_ns + 1))
    record = records[0]
    record.update(
        {
            "screenshot_path": f"screenshots/{filename}",
            "screenshot_mode": request_mode,
            "screenshot_capture_kind": "article",
            "screenshot_observed_at": datetime.now(timezone.utc).isoformat(),
            "screenshot_sha256": hashlib.sha256(PNG).hexdigest(),
            "screenshot_status": "complete",
        }
    )
    if case == "partial":
        record.pop("screenshot_sha256")
    elif case == "absolute":
        record["screenshot_path"] = str(screenshot)
    elif case == "traversal":
        record["screenshot_path"] = f"../screenshots/{filename}"
    elif case == "foreign-run":
        record["screenshot_path"] = f"../run-foreign/screenshots/{filename}"
    elif case == "symlink":
        target = tmp_path / "outside.png"
        target.write_bytes(PNG)
        target.chmod(0o600)
        screenshot.unlink()
        screenshot.symlink_to(target)
    elif case == "stale":
        os.utime(screenshot, ns=(started_ns - 1, started_ns - 1))
    elif case == "wrong-mode":
        record["screenshot_mode"] = "opened" if request_mode == "all" else "all"
    elif case == "wrong-hash":
        record["screenshot_sha256"] = "0" * 64
    elif case == "wrong-kind":
        record["screenshot_capture_kind"] = "viewport"
    elif case == "non-utc":
        record["screenshot_observed_at"] = "2026-08-11T08:00:00+08:00"
    source = inner / "bilibili.json"
    source.write_text(json.dumps(records), encoding="utf-8")
    os.utime(source, ns=(started_ns + 1, started_ns + 1))
    request = CollectionRequest(
        platforms=("bilibili",),
        count=1,
        screenshot_mode=request_mode,
        allow_navigation=True,
    )
    return source, request, started_ns, filename


@pytest.mark.parametrize(
    "platform, fixture",
    [
        ("bilibili", "bilibili_creator.json"),
        ("bilibili", "bilibili_search.json"),
        ("xhs", "xhs_creator.json"),
        ("xhs", "xhs_search.json"),
        ("douyin", "douyin_creator.json"),
        ("douyin", "douyin_search.json"),
        ("weibo", "weibo_creator.json"),
        ("weibo", "weibo_search.json"),
    ],
)
def test_synthetic_platform_contracts_validate(tmp_path, platform, fixture):
    started_ns = time.time_ns() - 1_000_000
    path = copy_fixture(tmp_path, fixture, started_ns=started_ns)
    search = "synthetic topic" if "search" in fixture else None
    result = validate_run(
        (path,),
        CollectionRequest(platforms=(platform,), count=1, search=search),
        started_ns,
    )
    assert result["status"] == "success", result["errors"]
    assert result["counts"] == {platform: 1}
    assert len(result["records"]) == 1


def test_validation_reports_count_shortfall_as_partial(tmp_path):
    started_ns = time.time_ns() - 1_000_000
    path = copy_fixture(tmp_path, "weibo_creator.json", started_ns=started_ns)
    result = validate_run(
        (path,), CollectionRequest(platforms=("weibo",), count=2), started_ns
    )
    assert result["status"] == "partial"
    assert any("expected 2" in error for error in result["errors"])


def test_validation_accepts_and_rewrites_a_private_screenshot_reference(tmp_path):
    source, request, started_ns, filename = screenshot_evidence(tmp_path)

    result = validate_run((source,), request, started_ns)

    assert result["status"] == "success", result["errors"]
    assert result["records"][0]["screenshot_path"] == (
        f"run-engine/screenshots/{filename}"
    )


def test_opened_mode_without_a_detail_open_has_no_screenshot_obligation(tmp_path):
    started_ns = time.time_ns() - 1_000_000
    source = copy_fixture(
        tmp_path, "bilibili_creator.json", started_ns=started_ns
    )

    result = validate_run(
        (source,),
        CollectionRequest(
            platforms=("bilibili",),
            count=1,
            screenshot_mode="opened",
            allow_navigation=True,
        ),
        started_ns,
    )

    assert result["status"] == "success"


def test_failed_screenshot_is_a_partial_result_without_losing_the_record(tmp_path):
    started_ns = time.time_ns() - 1_000_000
    records = json.loads(
        (FIXTURES / "bilibili_creator.json").read_text(encoding="utf-8")
    )
    records[0].update(
        {
            "detail_attempted": True,
            "screenshot_status": "failed",
            "screenshot_error_code": "capture-failed",
        }
    )
    source = tmp_path / "bilibili.json"
    source.write_text(json.dumps(records), encoding="utf-8")
    os.utime(source, ns=(started_ns + 1, started_ns + 1))

    result = validate_run(
        (source,),
        CollectionRequest(
            platforms=("bilibili",),
            count=1,
            screenshot_mode="opened",
            allow_navigation=True,
        ),
        started_ns,
    )

    assert result["status"] == "partial"
    assert result["counts"] == {"bilibili": 1}
    assert any("screenshot" in error.lower() for error in result["errors"])


@pytest.mark.parametrize(
    "case",
    (
        "partial",
        "absolute",
        "traversal",
        "foreign-run",
        "symlink",
        "stale",
        "wrong-mode",
        "wrong-hash",
        "wrong-kind",
        "non-utc",
        "non-png",
    ),
)
def test_validation_rejects_invalid_screenshot_evidence(tmp_path, case):
    source, request, started_ns, _filename = screenshot_evidence(
        tmp_path, case=case
    )

    result = validate_run((source,), request, started_ns)

    assert result["status"] == "partial"
    assert result["counts"] == {"bilibili": 1}
    assert any("screenshot" in error.lower() for error in result["errors"])


def test_screenshot_all_requires_evidence_for_every_record(tmp_path):
    started_ns = time.time_ns() - 1_000_000
    source = copy_fixture(
        tmp_path, "bilibili_creator.json", started_ns=started_ns
    )

    result = validate_run(
        (source,),
        CollectionRequest(
            platforms=("bilibili",),
            count=1,
            screenshot_mode="all",
            allow_navigation=True,
        ),
        started_ns,
    )

    assert result["status"] == "partial"
    assert any("screenshot" in error.lower() for error in result["errors"])


@pytest.mark.parametrize(
    ("platform_status", "overall_status", "expected_status"),
    (
        ("complete", "complete", "success"),
        ("shortfall", "failed", "partial"),
        ("incomplete", "failed", "partial"),
        ("failed", "failed", "partial"),
        ("not-run", "failed", "partial"),
        ("risk-stopped", "risk-stopped", "risk-stopped"),
    ),
)
def test_validation_preserves_runtime_manifest_failure_statuses(
    tmp_path, platform_status, overall_status, expected_status
):
    started_ns = time.time_ns() - 1_000_000
    content = tmp_path / "bilibili.json"
    content.write_text(
        (FIXTURES / "bilibili_creator.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    diagnostic = {
        "complete": {"kind": "ok", "code": "ok"},
        "shortfall": {"kind": "result", "code": "count-shortfall"},
        "incomplete": {"kind": "result", "code": "incomplete-record"},
        "failed": {"kind": "source-response", "code": "source-response-failed"},
        "not-run": {"kind": "not-run", "code": "preflight-aborted"},
        "risk-stopped": {"kind": "risk-stop", "code": "payload-471"},
    }[platform_status]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "counts": {"bilibili": 1},
                "paths": {"bilibili": "bilibili.json"},
                "platforms": {"bilibili": platform_status},
                "status": overall_status,
                "diagnostics": {"bilibili": diagnostic},
            }
        ),
        encoding="utf-8",
    )
    os.utime(content, ns=(started_ns + 1, started_ns + 1))
    os.utime(manifest, ns=(started_ns + 1, started_ns + 1))

    result = validate_run(
        (manifest, content),
        CollectionRequest(platforms=("bilibili",), count=1),
        started_ns,
    )

    assert result["status"] == expected_status
    assert result["counts"] == {"bilibili": 1}
    assert [record["dynamic_id"] for record in result["records"]] == [
        "synthetic-bili-creator-1"
    ]
    manifest_diagnostic = next(
        item for item in result["diagnostics"] if Path(item["path"]).name == "manifest.json"
    )
    assert manifest_diagnostic["platforms"] == {"bilibili": diagnostic}


@pytest.mark.parametrize(
    "diagnostics",
    [
        {},
        {"bilibili": {"kind": "source-response", "code": "private-server-message"}},
        {"bilibili": {"kind": "internal", "code": "unexpected", "detail": "private"}},
        {"weibo": {"kind": "ok", "code": "ok"}},
    ],
)
def test_validation_rejects_non_strict_manifest_diagnostics(tmp_path, diagnostics):
    started_ns = time.time_ns() - 1_000_000
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "counts": {"bilibili": 0},
                "paths": {},
                "platforms": {"bilibili": "failed"},
                "status": "failed",
                "diagnostics": diagnostics,
            }
        ),
        encoding="utf-8",
    )
    os.utime(manifest, ns=(started_ns + 1, started_ns + 1))

    result = validate_run(
        (manifest,), CollectionRequest(platforms=("bilibili",), count=1), started_ns
    )

    assert result["status"] == "failed"
    assert any("diagnostic" in error for error in result["errors"])
    assert "private-server-message" not in json.dumps(result)


@pytest.mark.parametrize("payload", ["{not-json", json.dumps({"unexpected": "object"})])
def test_validation_rejects_malformed_or_unexpected_top_level_json(tmp_path, payload):
    path = tmp_path / "xhs_bad.json"
    path.write_text(payload, encoding="utf-8")
    started_ns = path.stat().st_mtime_ns - 1
    result = validate_run(
        (path,), CollectionRequest(platforms=("xhs",), count=1), started_ns
    )
    assert result["status"] == "failed"
    assert result["errors"]


def test_validation_rejects_error_object_disguised_by_platform_filename(tmp_path):
    path = tmp_path / "weibo_20260803_000000.json"
    path.write_text(json.dumps([{"error": "login expired"}]), encoding="utf-8")
    started_ns = path.stat().st_mtime_ns - 1

    result = validate_run(
        (path,), CollectionRequest(platforms=("weibo",), count=1), started_ns
    )

    assert result["status"] == "failed"
    assert result["counts"] == {"weibo": 0}
    assert result["evidence"] == []
    assert any("content identity" in error for error in result["errors"])


def test_validation_rejects_stale_evidence(tmp_path):
    path = copy_fixture(tmp_path, "douyin_creator.json")
    started_ns = path.stat().st_mtime_ns + 1_000_000
    result = validate_run(
        (path,), CollectionRequest(platforms=("douyin",), count=1), started_ns
    )
    assert result["status"] == "failed"
    assert any("stale" in error for error in result["errors"])


def test_bilibili_complete_requires_real_title_date_and_metrics(tmp_path):
    records = json.loads((FIXTURES / "bilibili_creator.json").read_text(encoding="utf-8"))
    records[0]["title"] = "无标题"
    path = tmp_path / "bilibili_creator.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    result = validate_run(
        (path,),
        CollectionRequest(platforms=("bilibili",), count=1, bilibili_complete=True),
        path.stat().st_mtime_ns - 1,
    )
    assert result["status"] == "partial"
    assert any("Bilibili complete" in error for error in result["errors"])


def test_xhs_complete_requires_fresh_current_observation(tmp_path):
    path = copy_fixture(tmp_path, "xhs_creator.json")
    started = datetime(2026, 8, 3, 1, tzinfo=timezone.utc)
    result = validate_run(
        (path,),
        CollectionRequest(platforms=("xhs",), count=1, xhs_complete=True),
        int(started.timestamp() * 1_000_000_000),
    )
    assert result["status"] == "partial"
    assert any("XHS complete" in error for error in result["errors"])


def test_xhs_complete_accepts_current_numeric_millisecond_observation(tmp_path):
    records = json.loads((FIXTURES / "xhs_creator.json").read_text(encoding="utf-8"))
    started_ns = time.time_ns() - 1_000_000_000
    records[0]["engagement_observed_at"] = started_ns // 1_000_000 + 1
    records[0]["engagement_source"] = "detail"
    path = tmp_path / "xhs_creator.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    result = validate_run(
        (path,),
        CollectionRequest(platforms=("xhs",), count=1, xhs_complete=True),
        started_ns,
    )
    assert result["status"] == "success"


def test_validation_rejects_symlinked_evidence(tmp_path):
    target = copy_fixture(tmp_path, "weibo_creator.json")
    link = tmp_path / "weibo_link.json"
    link.symlink_to(target)
    result = validate_run(
        (link,),
        CollectionRequest(platforms=("weibo",), count=1),
        target.stat().st_mtime_ns - 1,
    )
    assert result["status"] == "failed"
    assert any("unsafe" in error for error in result["errors"])


def test_xhs_risk_report_classifies_risk_stopped(tmp_path):
    report = tmp_path / "xhs_run_report.json"
    report.write_text(
        json.dumps({"platform": "xhs", "status": "risk_stopped", "reason": "471"}),
        encoding="utf-8",
    )
    result = validate_run(
        (report,),
        CollectionRequest(platforms=("xhs",), count=1),
        report.stat().st_mtime_ns - 1,
    )
    assert result["status"] == "risk-stopped"


def test_completed_xhs_diagnostic_is_not_treated_as_content_evidence(tmp_path):
    started_ns = time.time_ns() - 1_000_000
    content = copy_fixture(tmp_path, "xhs_creator.json", started_ns=started_ns)
    report = tmp_path / "media_missher_xhs_run_synthetic.json"
    report.write_text(
        json.dumps(
            {
                "status": "completed",
                "started_at": "2026-08-03T00:00:00Z",
                "finished_at": "2026-08-03T00:00:01Z",
                "final_items": 1,
            }
        ),
        encoding="utf-8",
    )
    os.utime(report, ns=(started_ns + 1, started_ns + 1))

    result = validate_run(
        (report, content), CollectionRequest(platforms=("xhs",), count=1), started_ns
    )

    assert result["status"] == "success"
    assert result["evidence"] == [str(content.resolve())]
    assert result["diagnostics"] == [
        {"path": str(report.resolve()), "status": "completed"}
    ]


def test_validation_samples_are_metadata_only(tmp_path):
    started_ns = time.time_ns() - 1_000_000
    path = copy_fixture(tmp_path, "xhs_creator.json", started_ns=started_ns)
    result = validate_run(
        (path,), CollectionRequest(platforms=("xhs",), count=1), started_ns
    )

    assert result["samples"] == [
        {"platform": "xhs", "field_count": len(result["records"][0])}
    ]
    assert "synthetic" not in json.dumps(result["samples"], ensure_ascii=False)


def test_validate_run_cli_help_is_offline():
    script = Path(__file__).resolve().parents[1] / "media-missher" / "scripts" / "validate_run.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 0
    assert "--run-dir" in completed.stdout
    assert "--started-epoch" in completed.stdout
