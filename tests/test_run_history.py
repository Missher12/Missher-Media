from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

import media_missher_history as history
from media_missher_adapter import CollectionRequest


PROFILE_DIGEST = "a" * 64
PNG = b"\x89PNG\r\n\x1a\nprivate-test"


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path


def _private_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return path


def _request(
    *, count: int = 3, output_format: str = "json", uid: str = "private-uid",
    screenshot_mode: str = "off",
):
    return CollectionRequest(
        platforms=("xhs",),
        count=count,
        platform_uids={"xhs": uid},
        xhs_complete=True,
        xhs_comments=2,
        output_format=output_format,
        allow_navigation=True,
        screenshot_mode=screenshot_mode,
        collect_as_much_as_safe=count == 0,
    )


def _xhs_record(note_id: str, *, complete: bool = True, observed_at: str = "2026-09-07T01:02:03Z", liked: int = 1) -> dict:
    return {
        "platform": "xhs",
        "note_id": note_id,
        "link": f"https://www.xiaohongshu.com/explore/{note_id}",
        "complete": complete,
        "observed_at": observed_at,
        "engagement_observed_at": observed_at,
        "liked": liked,
        "comments": 2,
        "collected": 3,
        "shares": 4,
    }


def _make_semantically_complete(record: dict, started_ns: int, comments: int = 2) -> dict:
    observed_ms = started_ns // 1_000_000 + 1
    comments_data = [
        {"author": f"Author {index}", "text": f"Comment {index}", "date": "today", "liked": index}
        for index in range(comments)
    ]
    record.update(
        {
            "detail_attempted": True,
            "detail_completed": True,
            "missing_fields": [],
            "date": "2026-09-07",
            "date_precision": "day",
            "date_estimated": False,
            "date_source": "detail_api",
            "engagement_fresh": True,
            "engagement_source": "detail_api",
            "engagement_observed_at": observed_ms,
            "metric_sources": {
                "liked": "detail_api",
                "comments": "detail_api",
                "collected": "detail_api",
                "shares": "detail_api",
            },
            "metric_observed_at": {
                "liked": observed_ms,
                "comments": observed_ms,
                "collected": observed_ms,
                "raw_share_count": observed_ms,
            },
            "desc": "Synthetic body",
            "author": "Synthetic author",
            "cover": "https://cdn.example.invalid/cover.jpg",
            "detail_business_fields": ["desc", "author", "media"],
            "comments_requested": comments,
            "comments_fetched": comments,
            "comments_data": comments_data,
        }
    )
    return record


def _write_run(
    data_root: Path,
    run_id: str,
    records: list[dict],
    *,
    request=None,
    parent_run_id: str | None = None,
    status: str = "incomplete",
    with_context: bool = True,
    semantic_complete: bool = True,
) -> Path:
    request = request or _request()
    outer = _private_dir(data_root / run_id)
    if with_context:
        context_path = history.write_context(
            outer,
            request,
            PROFILE_DIGEST,
            "15.3.0",
            parent_run_id=parent_run_id,
        )
        started_ns = json.loads(context_path.read_text(encoding="utf-8"))["started_ns"]
        records = [
            _make_semantically_complete(dict(record), started_ns, request.xhs_comments)
            if semantic_complete and record.get("platform") == "xhs" and record.get("complete") is True
            else record
            for record in records
        ]
    inner = _private_dir(outer / "run-engine")
    _private_json(inner / "xhs.json", records)
    diagnostics = {
        "complete": {"kind": "ok", "code": "ok"},
        "incomplete": {"kind": "result", "code": "incomplete-record"},
        "risk-stopped": {"kind": "risk-stop", "code": "challenge"},
    }
    overall = "complete" if status == "complete" else "risk-stopped" if status == "risk-stopped" else "failed"
    _private_json(
        inner / "manifest.json",
        {
            "counts": {"xhs": len(records)},
            "paths": {"xhs": "xhs.json"},
            "platforms": {"xhs": status},
            "status": overall,
            "diagnostics": {"xhs": diagnostics[status]},
        },
    )
    return outer


def test_write_context_is_private_fixed_and_never_persists_raw_target(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    outer = _private_dir(data_root / "run-new")
    started_ns = outer.stat().st_mtime_ns
    request = _request(uid="do-not-persist-this-uid", screenshot_mode="opened")

    path = history.write_context(outer, request, PROFILE_DIGEST, "15.3.0")

    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert set(payload) == {
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
    assert payload["schema"] == 1
    assert payload["run_id"] == "run-new"
    assert payload["started_ns"] == started_ns
    assert payload["requested_counts"] == {"xhs": 3}
    assert payload["profile_digest"] == PROFILE_DIGEST
    assert "do-not-persist-this-uid" not in raw
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.stat().st_nlink == 1
    assert history.request_digest(request) == history.request_digest(
        _request(
            output_format="csv",
            uid="do-not-persist-this-uid",
            screenshot_mode="opened",
        )
    )


def test_list_history_includes_bound_and_legacy_runs_without_freshness_claim(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(data_root, "run-bound", [_xhs_record("note-a")])
    _write_run(
        data_root,
        "run-legacy",
        [_xhs_record("note-b")],
        with_context=False,
        status="complete",
    )

    entries = history.list_history(data_root)

    assert [(item["run_id"], item["bound"]) for item in entries] == [
        ("run-bound", True),
        ("run-legacy", False),
    ]
    assert all(item["historical"] is True for item in entries)
    assert all("fresh" not in item for item in entries)
    assert entries[0]["counts"] == {"xhs": 1}


def test_history_rejects_duplicate_json_keys_manifest_count_and_duplicate_ids(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    duplicate_key = _write_run(data_root, "run-duplicate-key", [_xhs_record("note-a")])
    manifest = duplicate_key / "run-engine" / "manifest.json"
    manifest.write_text('{"counts":{"xhs":1},"counts":{"xhs":1}}', encoding="utf-8")
    with pytest.raises(history.HistoryError, match="duplicate key"):
        history.load_run(data_root, "run-duplicate-key")

    bad_count = _write_run(data_root, "run-bad-count", [_xhs_record("note-b")])
    payload = json.loads((bad_count / "run-engine" / "manifest.json").read_text())
    payload["counts"]["xhs"] = 2
    _private_json(bad_count / "run-engine" / "manifest.json", payload)
    with pytest.raises(history.HistoryError, match="count"):
        history.load_run(data_root, "run-bad-count")

    _write_run(
        data_root,
        "run-duplicate-id",
        [_xhs_record("note-c"), _xhs_record("note-c")],
    )
    with pytest.raises(history.HistoryError, match="duplicate native ID"):
        history.load_run(data_root, "run-duplicate-id")


@pytest.mark.parametrize("field", ["path", "platform_status", "diagnostic_kind", "diagnostic_code", "controller_status"])
def test_catalog_keeps_good_run_when_one_run_has_malformed_field_types(tmp_path, field):
    root = _private_dir(tmp_path / "runs")
    _write_run(root, "run-good", [_xhs_record("good")], status="complete")
    bad = _write_run(root, "run-bad", [_xhs_record("bad")])
    path = bad / "run-engine" / "manifest.json"
    manifest = json.loads(path.read_text())
    if field == "path": manifest["paths"]["xhs"] = []
    elif field == "platform_status": manifest["platforms"]["xhs"] = {}
    elif field == "diagnostic_kind": manifest["diagnostics"]["xhs"]["kind"] = []
    elif field == "diagnostic_code": manifest["diagnostics"]["xhs"]["code"] = {}
    else: _private_json(bad / "run-result.json", {"schema": 1, "status": []})
    _private_json(path, manifest)
    entries = history.list_history(root)
    assert [(entry["run_id"], entry["status"]) for entry in entries] == [("run-bad", "invalid"), ("run-good", "complete")]


def test_history_rejects_unsafe_native_ids_and_free_form_diagnostics(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(data_root, "run-unsafe-id", [_xhs_record("../../private")])
    with pytest.raises(history.HistoryError, match="native ID"):
        history.load_run(data_root, "run-unsafe-id")

    _write_run(data_root, "run-transport-unsafe-id", [_xhs_record("note.with-dot")])
    with pytest.raises(history.HistoryError, match="native ID"):
        history.load_run(data_root, "run-transport-unsafe-id")

    run = _write_run(data_root, "run-free-form", [_xhs_record("note-a")])
    manifest_path = run / "run-engine" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["platforms"]["xhs"] = "failed"
    manifest["status"] = "failed"
    manifest["diagnostics"]["xhs"] = {
        "kind": "source-response",
        "code": "private-server-message",
    }
    _private_json(manifest_path, manifest)
    with pytest.raises(history.HistoryError, match="diagnostic value"):
        history.load_run(data_root, "run-free-form")


def test_bound_context_allows_manifest_subset_of_original_platforms(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    run = _write_run(data_root, "run-platform-mismatch", [_xhs_record("note-a")])
    context_path = run / "run-context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["requested_counts"] = {"bilibili": 3, "xhs": 3}
    _private_json(context_path, context)

    loaded = history.load_run(data_root, "run-platform-mismatch")

    assert loaded["counts"] == {"xhs": 1}


def test_list_history_keeps_good_runs_when_another_run_is_unavailable(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(data_root, "run-good", [_xhs_record("note-a")])
    unavailable = _private_dir(data_root / "run-private-value")
    history.write_context(unavailable, _request(), PROFILE_DIGEST, "15.3.0")

    entries = history.list_history(data_root)

    assert entries[0]["run_id"] == "run-good"
    assert entries[0]["status"] == "failed"
    assert entries[1] == {
        "run_id": "run-private-value",
        "historical": True,
        "bound": None,
        "status": "unavailable",
        "code": "history-unavailable",
        "counts": {},
        "started_ns": None,
        "created_at": None,
        "observation_times": [],
    }
    assert "private-value" not in json.dumps(entries[1]["code"])
    with pytest.raises(history.HistoryError):
        history.load_run(data_root, "run-private-value")


@pytest.mark.parametrize("unsafe", ["../run-safe", "/tmp/run-safe", "run-safe/child", "safe"])
def test_exact_run_id_rejects_path_escape_and_non_run_names(tmp_path, unsafe):
    data_root = _private_dir(tmp_path / "runs")
    with pytest.raises(history.HistoryError, match="run ID"):
        history.load_run(data_root, unsafe)


def test_history_rejects_wrong_permissions_symlinks_and_hardlinks(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    wrong_mode = _write_run(data_root, "run-mode", [_xhs_record("note-a")])
    (wrong_mode / "run-engine" / "xhs.json").chmod(0o644)
    with pytest.raises(history.HistoryError, match="0600"):
        history.load_run(data_root, "run-mode")

    outside = _private_dir(tmp_path / "outside")
    symlink = data_root / "run-link"
    symlink.symlink_to(outside, target_is_directory=True)
    with pytest.raises(history.HistoryError, match="symlink"):
        history.load_run(data_root, "run-link")

    hardlinked = _write_run(data_root, "run-hardlink", [_xhs_record("note-b")])
    os.link(hardlinked / "run-context.json", tmp_path / "second-link.json")
    with pytest.raises(history.HistoryError, match="hard link"):
        history.load_run(data_root, "run-hardlink")


def test_history_rejects_symlinked_data_root_ancestor(tmp_path):
    container = _private_dir(tmp_path / "container")
    data_root = _private_dir(container / "runs")
    _write_run(data_root, "run-safe", [_xhs_record("note-a")])
    alias = tmp_path / "alias"
    alias.symlink_to(container, target_is_directory=True)

    with pytest.raises(history.HistoryError, match="symlink"):
        history.load_run(alias / "runs", "run-safe")


def test_prepare_continuation_walks_bound_chain_and_skips_only_complete_xhs(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(data_root, "run-parent", [_xhs_record("note-a")])
    _write_run(
        data_root,
        "run-child",
        [_xhs_record("note-b"), _xhs_record("note-incomplete", complete=False)],
        parent_run_id="run-parent",
    )

    plan = history.prepare_continuation(
        data_root, "run-child", _request(), PROFILE_DIGEST
    )

    assert plan == {
        "parent_run_id": "run-child",
        "ancestor_run_ids": ["run-parent", "run-child"],
        "requested_counts": {"xhs": 3},
        "prior_counts": {"xhs": 2},
        "remaining_counts": {"xhs": 1},
        "skip_ids": {"xhs": ["note-a", "note-b"]},
    }


def test_prepare_continuation_does_not_skip_forged_complete_xhs_record(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(
        data_root,
        "run-forged",
        [_xhs_record("note-forged", complete=True)],
        semantic_complete=False,
    )

    plan = history.prepare_continuation(
        data_root, "run-forged", _request(), PROFILE_DIGEST
    )

    assert plan["skip_ids"] == {"xhs": []}
    assert plan["prior_counts"] == {"xhs": 0}
    assert plan["remaining_counts"] == {"xhs": 3}


def test_prepare_continuation_requires_requested_screenshot_evidence(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    request = _request(count=1, screenshot_mode="all")
    _write_run(data_root, "run-no-screenshot", [_xhs_record("note-a")], request=request)

    plan = history.prepare_continuation(
        data_root, "run-no-screenshot", request, PROFILE_DIGEST
    )

    assert plan["skip_ids"] == {"xhs": []}
    assert plan["remaining_counts"] == {"xhs": 1}


def test_screenshot_continuation_accepts_bound_file_then_rejects_hardlink(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    request = _request(count=2, screenshot_mode="all")
    run = _write_run(data_root, "run-screenshot", [_xhs_record("note-a")], request=request)
    context = json.loads((run / "run-context.json").read_text(encoding="utf-8"))
    inner = run / "run-engine"
    screenshot_dir = _private_dir(inner / "screenshots")
    screenshot = screenshot_dir / "xhs-note-a.png"
    screenshot.write_bytes(PNG)
    screenshot.chmod(0o600)
    observed_ns = context["started_ns"] + 1_000_000_000
    os.utime(screenshot, ns=(observed_ns, observed_ns))
    records = json.loads((inner / "xhs.json").read_text(encoding="utf-8"))
    records[0].update(
        {
            "screenshot_path": "screenshots/xhs-note-a.png",
            "screenshot_mode": "all",
            "screenshot_capture_kind": "article",
            "screenshot_observed_at": datetime.fromtimestamp(
                observed_ns / 1_000_000_000, timezone.utc
            ).isoformat(),
            "screenshot_sha256": hashlib.sha256(PNG).hexdigest(),
            "screenshot_status": "complete",
        }
    )
    _private_json(inner / "xhs.json", records)

    plan = history.prepare_continuation(
        data_root, "run-screenshot", request, PROFILE_DIGEST
    )
    assert plan["skip_ids"] == {"xhs": ["note-a"]}

    os.link(screenshot, tmp_path / "linked-screenshot.png")
    with pytest.raises(history.HistoryError, match="hard link"):
        history.load_run(data_root, "run-screenshot")


def test_prepare_continuation_uses_bilibili_complete_contract(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    request = CollectionRequest(
        platforms=("bilibili",), count=2, bilibili_complete=True
    )
    outer = _private_dir(data_root / "run-bilibili")
    history.write_context(outer, request, PROFILE_DIGEST, "15.3.0")
    inner = _private_dir(outer / "run-engine")
    records = [
        {
            "platform": "bilibili", "dynamic_id": "invalid", "link": "https://t.bilibili.com/invalid",
            "complete": True, "title": "动态", "date": "2026-09-07", "liked": 1,
            "comments": 2, "shares": 3, "collected": 4,
        },
        {
            "platform": "bilibili", "dynamic_id": "accepted", "link": "https://t.bilibili.com/accepted",
            "complete": True, "title": "A real title", "date": "2026-09-07", "liked": 1,
            "comments": 2, "shares": 3, "collected": 4,
        },
    ]
    _private_json(inner / "bilibili.json", records)
    _private_json(
        inner / "manifest.json",
        {
            "counts": {"bilibili": 2},
            "paths": {"bilibili": "bilibili.json"},
            "platforms": {"bilibili": "incomplete"},
            "status": "failed",
            "diagnostics": {
                "bilibili": {"kind": "result", "code": "incomplete-record"}
            },
        },
    )

    plan = history.prepare_continuation(
        data_root, "run-bilibili", request, PROFILE_DIGEST
    )

    assert plan["skip_ids"] == {"bilibili": ["accepted"]}
    assert plan["prior_counts"] == {"bilibili": 1}
    assert plan["remaining_counts"] == {"bilibili": 1}


def test_prepare_continuation_rejects_risk_in_any_ancestor(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(
        data_root,
        "run-risk",
        [_xhs_record("note-a")],
        status="risk-stopped",
    )
    _write_run(
        data_root,
        "run-child",
        [_xhs_record("note-b")],
        parent_run_id="run-risk",
    )

    with pytest.raises(history.HistoryError, match="risk-stopped ancestor"):
        history.prepare_continuation(data_root, "run-child", _request(), PROFILE_DIGEST)


def test_bilibili_video_snapshot_uses_bvid_for_screenshot_and_dynamic_id_for_history(tmp_path):
    from media_missher_adapter import _recover_current_snapshot, discover_current_json
    root = _private_dir(tmp_path / "runs")
    request = CollectionRequest(("bilibili",), count=2, platform_uids={"bilibili": "fixture"}, allow_navigation=True, screenshot_mode="all")
    outer = _private_dir(root / "run-bilibili-video")
    history.write_context(outer, request, PROFILE_DIGEST, "15.3.0")
    started_ns = json.loads((outer / "run-context.json").read_text())["started_ns"]
    inner = _private_dir(outer / "run-engine")
    screenshot_dir = _private_dir(inner / "screenshots")
    screenshot = screenshot_dir / "bilibili-BVfixture.png"
    screenshot.write_bytes(PNG)
    screenshot.chmod(0o600)
    record = {
        "platform": "bilibili", "dynamic_id": "12345", "bvid": "BVfixture",
        "link": "https://www.bilibili.com/video/BVfixture", "complete": True,
        "screenshot_path": "screenshots/bilibili-BVfixture.png", "screenshot_mode": "all",
        "screenshot_capture_kind": "article", "screenshot_status": "complete",
        "screenshot_observed_at": datetime.fromtimestamp(screenshot.stat().st_mtime_ns / 1_000_000_000, timezone.utc).isoformat(),
        "screenshot_sha256": hashlib.sha256(PNG).hexdigest(),
    }
    manifest = {"counts": {"bilibili": 1}, "paths": {"bilibili": "bilibili.json"}, "platforms": {"bilibili": "shortfall"}, "status": "failed", "diagnostics": {"bilibili": {"kind": "result", "code": "count-shortfall"}}}
    _private_json(inner / "committed.json", {"schema": 1, "manifest": manifest, "artifacts": {"bilibili": [record]}})
    _recover_current_snapshot(outer, started_ns)
    assert discover_current_json(outer, started_ns=started_ns) == (inner / "manifest.json", inner / "bilibili.json")
    plan = history.prepare_continuation(root, outer.name, request, PROFILE_DIGEST)
    assert plan["skip_ids"] == {"bilibili": ["12345"]}


def test_outer_controller_risk_result_blocks_continuation(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    run = _write_run(data_root, "run-controller-risk", [_xhs_record("note-a")])
    _private_json(
        run / "run-result.json",
        {"schema": 1, "status": "risk-stopped"},
    )

    loaded = history.load_run(data_root, "run-controller-risk")
    assert loaded["controller_status"] == "risk-stopped"
    assert history.list_history(data_root)[0]["status"] == "risk-stopped"
    with pytest.raises(history.HistoryError, match="risk-stopped ancestor"):
        history.prepare_continuation(
            data_root, "run-controller-risk", _request(), PROFILE_DIGEST
        )


def test_malformed_outer_controller_result_is_rejected(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    run = _write_run(data_root, "run-result-invalid", [_xhs_record("note-a")])
    _private_json(
        run / "run-result.json",
        {"schema": 1, "status": "private-status"},
    )

    with pytest.raises(history.HistoryError, match="run result"):
        history.load_run(data_root, "run-result-invalid")


def test_prepare_continuation_rejects_unbound_mismatch_exhaustion_and_unlimited(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(data_root, "run-legacy", [_xhs_record("legacy")], with_context=False)
    with pytest.raises(history.HistoryError, match="pre-context"):
        history.prepare_continuation(data_root, "run-legacy", _request(), PROFILE_DIGEST)

    _write_run(data_root, "run-bound", [_xhs_record("note-a")])
    with pytest.raises(history.HistoryError, match="profile digest"):
        history.prepare_continuation(data_root, "run-bound", _request(), "b" * 64)
    with pytest.raises(history.HistoryError, match="request digest"):
        history.prepare_continuation(
            data_root, "run-bound", CollectionRequest(platforms=("xhs",), count=4), PROFILE_DIGEST
        )

    _write_run(
        data_root,
        "run-full",
        [_xhs_record("note-b"), _xhs_record("note-c"), _xhs_record("note-d")],
    )
    with pytest.raises(history.HistoryError, match="no remaining"):
        history.prepare_continuation(data_root, "run-full", _request(), PROFILE_DIGEST)

    unlimited = _request(count=0)
    _write_run(data_root, "run-unlimited", [_xhs_record("note-e")], request=unlimited)
    with pytest.raises(history.HistoryError, match="unlimited"):
        history.prepare_continuation(data_root, "run-unlimited", unlimited, PROFILE_DIGEST)


def test_prepare_continuation_rejects_search_runs(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    request = CollectionRequest(platforms=("xhs",), count=3, search="private topic")
    _write_run(data_root, "run-search", [_xhs_record("note-search")], request=request)

    with pytest.raises(history.HistoryError, match="creator-only"):
        history.prepare_continuation(data_root, "run-search", request, PROFILE_DIGEST)


def test_export_run_writes_new_private_historical_export_and_keeps_source_immutable(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    source = _write_run(
        data_root,
        "run-legacy",
        [_xhs_record("note-a")],
        with_context=False,
        status="complete",
    )
    before = {
        path.relative_to(source): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }

    result = history.export_run(data_root, "run-legacy", "json")

    output = Path(result["output_path"])
    metadata = Path(result["metadata_path"])
    assert result["historical"] is True
    assert result["source_run_id"] == "run-legacy"
    assert output.parent == data_root / "exports"
    assert json.loads(output.read_text(encoding="utf-8"))[0]["note_id"] == "note-a"
    assert json.loads(metadata.read_text(encoding="utf-8"))["kind"] == "historical-export"
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert {
        path.relative_to(source): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    } == before


def test_committed_snapshot_wins_over_newer_mismatched_legacy_files(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    run = _write_run(data_root, "run-committed", [_xhs_record("note-old")])
    inner = run / "run-engine"
    committed_record = json.loads((inner / "xhs.json").read_text(encoding="utf-8"))[0]
    committed_manifest = json.loads(
        (inner / "manifest.json").read_text(encoding="utf-8")
    )
    _private_json(
        inner / "committed.json",
        {
            "schema": 1,
            "manifest": committed_manifest,
            "artifacts": {"xhs": [committed_record]},
        },
    )
    newer_records = [committed_record, _xhs_record("note-new", complete=False)]
    _private_json(inner / "xhs.json", newer_records)
    newer_manifest = dict(committed_manifest)
    newer_manifest["counts"] = {"xhs": 2}
    _private_json(inner / "manifest.json", newer_manifest)

    loaded = history.load_run(data_root, "run-committed")
    exported = history.export_run(data_root, "run-committed", "json")

    assert loaded["counts"] == {"xhs": 1}
    assert [record["note_id"] for record in loaded["records"]] == ["note-old"]
    assert loaded["committed_artifacts"]["xhs"][0]["note_id"] == "note-old"
    assert [record["note_id"] for record in json.loads(Path(exported["output_path"]).read_text())] == ["note-old"]


def test_invalid_committed_snapshot_never_falls_back_to_valid_legacy_files(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    run = _write_run(data_root, "run-invalid-committed", [_xhs_record("note-old")])
    _private_json(
        run / "run-engine" / "committed.json",
        {"schema": 1, "manifest": {}, "artifacts": {}},
    )

    with pytest.raises(history.HistoryError, match="committed snapshot"):
        history.load_run(data_root, "run-invalid-committed")


def test_committed_count_cannot_exceed_its_original_request(tmp_path):
    root = _private_dir(tmp_path / "runs")
    run = _write_run(root, "run-overcount", [_xhs_record("one"), _xhs_record("two")], request=_request(count=1))
    inner = run / "run-engine"
    _private_json(inner / "committed.json", {
        "schema": 1,
        "manifest": json.loads((inner / "manifest.json").read_text()),
        "artifacts": {"xhs": json.loads((inner / "xhs.json").read_text())},
    })
    with pytest.raises(history.HistoryError, match="exceeds.*requested"):
        history.load_run(root, run.name)


def test_continuation_rejects_cumulative_accepted_overcount(tmp_path):
    root = _private_dir(tmp_path / "runs")
    request = _request(count=2)
    _write_run(root, "run-parent", [_xhs_record("one"), _xhs_record("two")], request=request)
    _write_run(root, "run-child", [_xhs_record("three")], request=request, parent_run_id="run-parent")
    with pytest.raises(history.HistoryError, match="exceeds.*requested"):
        history.prepare_continuation(root, "run-child", request, PROFILE_DIGEST)


def test_continuation_binds_platform_timeout_but_allows_output_conversion(tmp_path):
    root = _private_dir(tmp_path / "runs")
    request = replace(_request(), platform_timeout=30)
    _write_run(root, "run-bound-timeout", [_xhs_record("one")], request=request)
    assert history.request_digest(request) == history.request_digest(replace(request, platform_timeout=30.0, output_format="csv"))
    with pytest.raises(history.HistoryError, match="request digest"):
        history.prepare_continuation(root, "run-bound-timeout", replace(request, platform_timeout=900), PROFILE_DIGEST)


def test_current_projection_restores_identical_but_stale_files(tmp_path):
    from media_missher_adapter import _recover_current_snapshot, discover_current_json
    root = _private_dir(tmp_path / "runs")
    run = _write_run(root, "run-stale-projection", [_xhs_record("one")])
    inner = run / "run-engine"
    started_ns = json.loads((run / "run-context.json").read_text())["started_ns"]
    manifest = json.loads((inner / "manifest.json").read_text())
    records = json.loads((inner / "xhs.json").read_text())
    _private_json(inner / "committed.json", {"schema": 1, "manifest": manifest, "artifacts": {"xhs": records}})
    snapshot = (inner / "committed.json").read_bytes()
    for name, value in (("manifest.json", manifest), ("xhs.json", records)):
        path = inner / name
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        os.utime(path, ns=(started_ns - 1, started_ns - 1))
    _recover_current_snapshot(run, started_ns)
    assert (inner / "committed.json").read_bytes() == snapshot
    assert all((inner / name).stat().st_mtime_ns >= started_ns for name in ("manifest.json", "xhs.json"))
    assert discover_current_json(run, started_ns=started_ns)


def test_legacy_load_has_no_committed_artifact_projection(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(data_root, "run-legacy-projection", [_xhs_record("note-old")])

    assert history.load_run(data_root, "run-legacy-projection")["committed_artifacts"] is None


def test_compare_runs_reports_both_observation_times_and_numeric_deltas(tmp_path):
    data_root = _private_dir(tmp_path / "runs")
    _write_run(
        data_root,
        "run-before",
        [_xhs_record("note-a", observed_at="2026-09-07T01:00:00Z", liked=2)],
    )
    _write_run(
        data_root,
        "run-after",
        [_xhs_record("note-a", observed_at="2026-09-07T02:00:00Z", liked=7)],
    )

    comparison = history.compare_runs(data_root, "run-before", "run-after")

    assert comparison["historical"] is True
    assert comparison["freshness_claim"] is False
    row = comparison["records"][0]
    assert row["platform"] == "xhs"
    assert row["native_id"] == "note-a"
    assert row["before_observed_at"] == "2026-09-07T01:00:00Z"
    assert row["after_observed_at"] == "2026-09-07T02:00:00Z"
    assert row["before_metrics"]["liked"] == 2
    assert row["after_metrics"]["liked"] == 7
    assert row["deltas"]["liked"] == 5
