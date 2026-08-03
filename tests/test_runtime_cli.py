from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest


class FakeDispatcher:
    def __init__(self, outcomes: dict[str, object] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.events: list[str] = []
        self.requests: list[Any] = []
        self.entered = False
        self.closed = False

    async def __aenter__(self) -> "FakeDispatcher":
        self.entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

    async def collect(self, request: Any) -> list[dict[str, object]]:
        platform = request.platform
        self.events.append(f"start:{platform}")
        self.requests.append(request)
        outcome = self.outcomes.get(platform)
        if isinstance(outcome, BaseException):
            raise outcome
        self.events.append(f"end:{platform}")
        if outcome is not None:
            return outcome  # type: ignore[return-value]
        records: list[dict[str, object]] = []
        for position in range(request.count or 1):
            record: dict[str, object] = {"platform": platform, "id": f"{platform}-{position + 1}", "zero": 0, "unknown": None}
            if request.complete:
                record["complete"] = True
            if platform == "xhs":
                record.update({"note_id": f"xhs-{position + 1}", "observed_at": "2026-08-03T00:00:00Z"})
            records.append(record)
        return records


def _manifest(output: Path) -> tuple[Path, dict[str, Any]]:
    run_dirs = list(output.glob("run-*"))
    assert len(run_dirs) == 1
    manifest = run_dirs[0] / "manifest.json"
    return run_dirs[0], json.loads(manifest.read_text(encoding="utf-8"))


def test_creator_dispatches_sequentially_and_preserves_platform_options(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    code = main(
        [
            "creator",
            "--platforms",
            "bilibili,xhs,douyin,weibo",
            "--count",
            "1",
            "--xhs-count",
            "2",
            "--bilibili-uid",
            "bili-user",
            "--xhs-uid",
            "xhs-user",
            "--douyin-uid",
            "douyin-user",
            "--weibo-uid",
            "weibo-user",
            "--bilibili-complete",
            "--xhs-complete",
            "--xhs-comments",
            "4",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 0
    assert dispatcher.entered is True and dispatcher.closed is True
    assert dispatcher.events == [
        "start:bilibili", "end:bilibili",
        "start:xhs", "end:xhs",
        "start:douyin", "end:douyin",
        "start:weibo", "end:weibo",
    ]
    requests = {request.platform: request for request in dispatcher.requests}
    assert requests["bilibili"].uid == "bili-user" and requests["bilibili"].complete is True
    assert requests["xhs"].uid == "xhs-user" and requests["xhs"].count == 2
    assert requests["xhs"].complete is True and requests["xhs"].comment_limit == 4
    assert requests["douyin"].complete is False and requests["weibo"].complete is False

    run_dir, manifest = _manifest(tmp_path)
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
    assert manifest == {
        "counts": {"bilibili": 1, "xhs": 2, "douyin": 1, "weibo": 1},
        "paths": {
            "bilibili": "bilibili.json",
            "xhs": "xhs.json",
            "xhs_checkpoint": "xhs_checkpoint.json",
            "xhs_report": "xhs_report.json",
            "douyin": "douyin.json",
            "weibo": "weibo.json",
        },
        "platforms": {"bilibili": "complete", "xhs": "complete", "douyin": "complete", "weibo": "complete"},
        "status": "complete",
    }
    for name in ("bilibili.json", "xhs.json", "xhs_checkpoint.json", "xhs_report.json", "douyin.json", "weibo.json", "manifest.json"):
        assert stat.S_IMODE((run_dir / name).stat().st_mode) == 0o600
    report_text = (run_dir / "xhs_report.json").read_text(encoding="utf-8")
    assert json.loads(report_text)["status"] == "complete"
    assert json.loads((run_dir / "xhs_checkpoint.json").read_text(encoding="utf-8")) == {"items": [
        {"note_id": "xhs-1", "observed_at": "2026-08-03T00:00:00Z"},
        {"note_id": "xhs-2", "observed_at": "2026-08-03T00:00:00Z"},
    ]}
    assert "unknown" not in report_text


def test_risk_stop_aborts_all_later_platforms_and_is_recorded_privately(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import RiskStop, main

    dispatcher = FakeDispatcher({"xhs": RiskStop("risk response")})
    code = main(
        [
            "creator", "--platforms", "bilibili,xhs,douyin,weibo", "--count", "1",
            "--bilibili-uid", "b", "--xhs-uid", "x", "--douyin-uid", "d", "--weibo-uid", "w",
            "--output-dir", str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 75
    assert dispatcher.events == ["start:bilibili", "end:bilibili", "start:xhs"]
    _, manifest = _manifest(tmp_path)
    assert manifest["status"] == "risk-stopped"
    assert manifest["platforms"] == {
        "bilibili": "complete", "xhs": "risk-stopped", "douyin": "not-run", "weibo": "not-run"
    }
    assert "risk response" not in json.dumps(manifest)


def test_non_risk_failure_is_isolated_and_later_platforms_continue(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher({"xhs": ValueError("secret detail must not enter manifest")})
    code = main(
        [
            "creator", "--platforms", "bilibili,xhs,douyin", "--count", "1",
            "--bilibili-uid", "b", "--xhs-uid", "x", "--douyin-uid", "d",
            "--output-dir", str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 1
    assert dispatcher.events == ["start:bilibili", "end:bilibili", "start:xhs", "start:douyin", "end:douyin"]
    _, manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["platforms"] == {"bilibili": "complete", "xhs": "failed", "douyin": "complete"}
    assert manifest["counts"] == {"bilibili": 1, "xhs": 0, "douyin": 1}
    assert "secret detail" not in json.dumps(manifest)


def test_count_shortfall_and_incomplete_detail_cannot_be_reported_as_complete(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher(
        {
            "bilibili": [{"platform": "bilibili", "id": "one"}],
            "xhs": [{"platform": "xhs", "note_id": "note", "observed_at": "now", "complete": False}],
        }
    )
    code = main(
        [
            "creator", "--platforms", "bilibili,xhs", "--count", "2",
            "--bilibili-uid", "b", "--xhs-uid", "x", "--xhs-complete", "--output-dir", str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 1
    run_dir, manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["platforms"] == {"bilibili": "shortfall", "xhs": "shortfall"}
    assert json.loads((run_dir / "xhs_report.json").read_text(encoding="utf-8"))["status"] == "shortfall"


def test_complete_mode_rejects_full_count_with_incomplete_record(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher({"xhs": [{"platform": "xhs", "note_id": "note", "observed_at": "now", "complete": False}]})
    code = main(
        [
            "creator", "--platforms", "xhs", "--count", "1", "--xhs-uid", "x", "--xhs-complete",
            "--output-dir", str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 1
    _, manifest = _manifest(tmp_path)
    assert manifest["platforms"] == {"xhs": "incomplete"}


def test_search_dispatches_one_keyword_request(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    code = main(
        ["search", "--platform", "weibo", "--keyword", "synthetic topic", "--count", "3", "--output-dir", str(tmp_path)],
        dispatcher=dispatcher,
    )

    assert code == 0
    assert dispatcher.events == ["start:weibo", "end:weibo"]
    request = dispatcher.requests[0]
    assert request.keyword == "synthetic topic" and request.uid is None and request.count == 3


def test_preflight_failure_happens_before_a_run_directory_is_created(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    class PreflightFailure(FakeDispatcher):
        async def preflight(self, requests: object) -> None:
            raise RuntimeError("page is missing")

    dispatcher = PreflightFailure()
    code = main(
        ["search", "--platform", "weibo", "--keyword", "topic", "--output-dir", str(tmp_path)],
        dispatcher=dispatcher,
    )

    assert code == 1
    assert dispatcher.closed is True
    assert not list(tmp_path.glob("run-*"))


@pytest.mark.parametrize(
    "argv",
    [
        ["creator", "--platforms", "bilibili,bilibili", "--bilibili-uid", "b"],
        ["creator", "--platforms", "unknown", "--unknown-uid", "u"],
        ["creator", "--platforms", "bilibili"],
        ["search", "--platform", "bilibili", "--keyword", ""],
    ],
)
def test_invalid_routing_fails_before_dispatch(argv: list[str], tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    with pytest.raises(SystemExit) as caught:
        main([*argv, "--output-dir", str(tmp_path)], dispatcher=dispatcher)

    assert caught.value.code == 2
    assert dispatcher.entered is False
    assert not list(tmp_path.glob("run-*"))


def test_legacy_json_only_aliases_remain_accepted_for_adapter_cutover(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    code = main(
        [
            "--platform", "bilibili", "--count", "1", "--bilibili-uid", "b",
            "--format", "json", "--output", str(tmp_path), "--no-feishu", "--platform-timeout", "42",
        ],
        dispatcher=dispatcher,
    )

    assert code == 0
    assert [request.platform for request in dispatcher.requests] == ["bilibili"]


def test_single_platform_shim_legacy_search_shape_accepts_max_uid_and_xhs_comments(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    code = main(
        [
            "--search", "synthetic topic", "--max", "2", "--uid", "optional-user",
            "--comments", "3", "--format", "json", "--output", str(tmp_path),
        ],
        fixed_platform="xhs",
        dispatcher=dispatcher,
    )

    assert code == 0
    request = dispatcher.requests[0]
    assert request.platform == "xhs" and request.keyword == "synthetic topic" and request.count == 2
