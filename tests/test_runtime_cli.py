from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path
from typing import Any

import pytest


def _run(coroutine: Any) -> Any:
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fake coroutine unexpectedly suspended")


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
    assert all(request.browser_assist == "off" for request in requests.values())
    assert all(request.screenshot_mode == "off" for request in requests.values())

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
        "diagnostics": {
            "bilibili": {"kind": "ok", "code": "ok"},
            "xhs": {"kind": "ok", "code": "ok"},
            "douyin": {"kind": "ok", "code": "ok"},
            "weibo": {"kind": "ok", "code": "ok"},
        },
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


def test_runtime_cli_carries_bilibili_assist_modes_into_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Screenshot mode still carries; the deprecated browser-assist bridge is refused."""

    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    code = main(
        [
            "creator",
            "--platforms",
            "bilibili",
            "--bilibili-uid",
            "creator",
            "--count",
            "1",
            "--browser-assist",
            "off",
            "--screenshot-mode",
            "opened",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 0
    assert len(dispatcher.requests) == 1
    assert dispatcher.requests[0].browser_assist == "off"
    assert dispatcher.requests[0].screenshot_mode == "opened"

    refused = main(
        [
            "creator",
            "--platforms",
            "bilibili",
            "--bilibili-uid",
            "creator",
            "--count",
            "1",
            "--browser-assist",
            "browserskill",
            "--screenshot-mode",
            "opened",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path / "refused"),
        ],
        dispatcher=FakeDispatcher(),
    )

    assert refused == 78
    assert capsys.readouterr().err == (
        "media-missher-diagnostic platform=bilibili "
        "kind=precondition code=browser-assist-replaced\n"
    )
    assert not list((tmp_path / "refused").glob("run-*"))


def test_runtime_model_retires_auxiliary_bridge_for_all_platforms():
    from runtime.media_missher_runtime.models import CollectionRequest
    with pytest.raises(ValueError, match="backend-retired-browserskill"):
        CollectionRequest(platform="xhs",count=1,uid="creator",browser_assist="browserskill")
    with pytest.raises(ValueError, match="unsupported backend"):
        CollectionRequest(platform="xhs",count=1,uid="creator",backend="computer_use")


def test_runtime_cli_rejects_xhs_browser_assist_before_dispatcher(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    code = main(
        [
            "creator",
            "--platforms",
            "xhs",
            "--xhs-uid",
            "creator",
            "--count",
            "1",
            "--allow-navigation",
            "--browser-assist",
            "browserskill",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 78
    assert dispatcher.entered is False
    assert not list(tmp_path.iterdir())
    assert capsys.readouterr().err == (
        "media-missher-diagnostic platform=xhs "
        "kind=precondition code=browser-assist-replaced\n"
    )


def test_xhs_creator_defaults_to_complete_detail_collection(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    code = main(
        [
            "creator",
            "--platforms",
            "xhs",
            "--xhs-uid",
            "creator",
            "--count",
            "1",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 0
    assert dispatcher.requests[0].complete is True


def test_requested_screenshot_failure_marks_runtime_result_incomplete(
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher({
        "bilibili": [{
            "platform": "bilibili",
            "id": "bilibili-1",
            "screenshot_status": "failed",
            "screenshot_error_code": "capture-failed",
        }]
    })
    code = main(
        [
            "creator",
            "--platforms",
            "bilibili",
            "--bilibili-uid",
            "creator",
            "--count",
            "1",
            "--screenshot-mode",
            "all",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 1
    _, manifest = _manifest(tmp_path)
    assert manifest["platforms"] == {"bilibili": "incomplete"}
    assert manifest["diagnostics"] == {
        "bilibili": {"kind": "result", "code": "screenshot-shortfall"}
    }


def test_opened_screenshot_mode_without_detail_open_has_no_runtime_obligation(
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    code = main(
        [
            "creator",
            "--platforms",
            "bilibili",
            "--bilibili-uid",
            "creator",
            "--count",
            "1",
            "--screenshot-mode",
            "opened",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 0
    _, manifest = _manifest(tmp_path)
    assert manifest["platforms"] == {"bilibili": "complete"}


@pytest.mark.parametrize(
    ("mode", "record"),
    (
        ("all", {"platform": "bilibili", "id": "bilibili-1"}),
        (
            "opened",
            {
                "platform": "bilibili",
                "id": "bilibili-1",
                "detail_attempted": True,
            },
        ),
    ),
)
def test_requested_screenshot_obligation_requires_an_explicit_terminal_status(
    tmp_path: Path,
    mode: str,
    record: dict[str, object],
) -> None:
    from runtime.media_missher_runtime.cli import main

    code = main(
        [
            "creator",
            "--platforms",
            "bilibili",
            "--bilibili-uid",
            "creator",
            "--count",
            "1",
            "--screenshot-mode",
            mode,
            "--allow-navigation",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=FakeDispatcher({"bilibili": [record]}),
    )

    assert code == 1
    _, manifest = _manifest(tmp_path)
    assert manifest["platforms"] == {"bilibili": "incomplete"}
    assert manifest["diagnostics"] == {
        "bilibili": {"kind": "result", "code": "screenshot-shortfall"}
    }


@pytest.mark.parametrize(
    "arguments",
    (
        (
            "creator",
            "--platforms",
            "xhs",
            "--xhs-uid",
            "creator",
            "--count",
            "0",
            "--screenshot-mode",
            "all",
            "--allow-navigation",
        ),
        (
            "search",
            "--platform",
            "bilibili",
            "--keyword",
            "topic",
            "--screenshot-mode",
            "opened",
            "--allow-navigation",
        ),
        (
            "search",
            "--platform",
            "bilibili",
            "--keyword",
            "topic",
            "--screenshot-mode",
            "all",
            "--allow-navigation",
        ),
    ),
)
def test_runtime_cli_rejects_unbounded_or_bilibili_search_advanced_modes(
    arguments: tuple[str, ...],
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import main

    with pytest.raises(SystemExit, match="2"):
        main(
            [*arguments, "--output-dir", str(tmp_path)],
            dispatcher=FakeDispatcher(),
        )


def test_runtime_creator_screenshot_all_uses_effective_platform_counts(
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import build_parser, _requests_from_args

    parser = build_parser()
    args = parser.parse_args(
        [
            "creator",
            "--platforms",
            "bilibili,xhs",
            "--count",
            "0",
            "--bilibili-count",
            "2",
            "--xhs-count",
            "3",
            "--bilibili-uid",
            "b",
            "--xhs-uid",
            "x",
            "--screenshot-mode",
            "all",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path),
        ]
    )

    requests = _requests_from_args(parser, args)

    assert [(request.platform, request.count) for request in requests] == [
        ("bilibili", 2),
        ("xhs", 3),
    ]


@pytest.mark.parametrize(
    "count_arguments",
    (
        ("--bilibili-count", "2"),
        ("--bilibili-count", "2", "--xhs-count", "0"),
    ),
)
def test_runtime_creator_screenshot_all_rejects_any_zero_effective_count(
    count_arguments: tuple[str, ...],
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import build_parser, _requests_from_args

    parser = build_parser()
    args = parser.parse_args(
        [
            "creator",
            "--platforms",
            "bilibili,xhs",
            "--count",
            "0",
            *count_arguments,
            "--bilibili-uid",
            "b",
            "--xhs-uid",
            "x",
            "--screenshot-mode",
            "all",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path),
        ]
    )

    with pytest.raises(SystemExit, match="2"):
        _requests_from_args(parser, args)


@pytest.mark.parametrize(
    "arguments",
    (
        ("--platforms", "xhs", "--xhs-uid", "creator", "--screenshot-mode", "all"),
        ("--platforms", "douyin", "--douyin-uid", "creator", "--screenshot-mode", "opened", "--allow-navigation"),
        ("--platforms", "weibo", "--weibo-uid", "creator", "--screenshot-mode", "opened", "--allow-navigation"),
    ),
)
def test_runtime_cli_rejects_unsafe_assist_combinations(
    arguments: tuple[str, ...], tmp_path: Path
) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    output = tmp_path / "runs"
    with pytest.raises(SystemExit, match="2"):
        main(
            ["creator", *arguments, "--output-dir", str(output)],
            dispatcher=dispatcher,
        )

    assert dispatcher.requests == []
    assert not output.exists()


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
    assert manifest["diagnostics"] == {
        "bilibili": {"kind": "ok", "code": "ok"},
        "xhs": {"kind": "risk-stop", "code": "risk-signal"},
        "douyin": {"kind": "not-run", "code": "prior-risk-stop"},
        "weibo": {"kind": "not-run", "code": "prior-risk-stop"},
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
    assert manifest["diagnostics"]["xhs"] == {
        "kind": "internal",
        "code": "unexpected",
    }
    assert "secret detail" not in json.dumps(manifest)


@pytest.mark.parametrize(
    ("platform", "error_factory", "expected"),
    [
        (
            "bilibili",
            lambda: __import__(
                "runtime.media_missher_runtime.platforms.bilibili",
                fromlist=["SourceResponseError"],
            ).SourceResponseError("https://server.invalid/?uid=private-bili"),
            {"kind": "source-response", "code": "source-response-failed"},
        ),
        (
            "xhs",
            lambda: __import__(
                "runtime.media_missher_runtime.browser", fromlist=["PreconditionError"]
            ).PreconditionError("uid=private-xhs https://server.invalid/secret"),
            {"kind": "precondition", "code": "precondition-failed"},
        ),
        (
            "douyin",
            lambda: ModuleNotFoundError("private.douyin.dependency"),
            {"kind": "dependency", "code": "module-not-found"},
        ),
        (
            "weibo",
            lambda: TimeoutError("private-weibo-query"),
            {"kind": "timeout", "code": "platform-timeout"},
        ),
    ],
)
def test_failure_diagnostics_use_only_strict_codes(
    platform: str,
    error_factory: object,
    expected: dict[str, str],
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import main

    error = error_factory()  # type: ignore[operator]
    dispatcher = FakeDispatcher({platform: error})
    code = main(
        [
            "creator",
            "--platforms",
            platform,
            f"--{platform}-uid",
            "private-uid",
            "--count",
            "1",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 1
    _, manifest = _manifest(tmp_path)
    assert manifest["diagnostics"] == {platform: expected}
    encoded = json.dumps(manifest)
    for secret in (
        "server.invalid",
        "private-bili",
        "private-xhs",
        "private.douyin.dependency",
        "private-weibo-query",
    ):
        assert secret not in encoded


def test_collector_contract_diagnostic_does_not_persist_invalid_value(
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher({"bilibili": {"uid": "must-not-persist"}})
    code = main(
        [
            "creator",
            "--platforms",
            "bilibili",
            "--bilibili-uid",
            "private-uid",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 1
    _, manifest = _manifest(tmp_path)
    assert manifest["diagnostics"] == {
        "bilibili": {"kind": "collector-contract", "code": "invalid-records"}
    }
    assert "must-not-persist" not in json.dumps(manifest)


@pytest.mark.parametrize(
    "capture_code", ["creator-capture-timeout", "detail-capture-timeout"]
)
def test_xhs_capture_timeout_keeps_only_its_fixed_code(
    capture_code: str, tmp_path: Path
) -> None:
    from runtime.media_missher_runtime.cli import main
    from runtime.media_missher_runtime.platforms.xhs import CaptureTimeout

    dispatcher = FakeDispatcher({"xhs": CaptureTimeout(capture_code)})
    returncode = main(
        [
            "creator",
            "--platforms",
            "xhs",
            "--xhs-uid",
            "private-xhs",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert returncode == 1
    run_dir, manifest = _manifest(tmp_path)
    assert manifest["diagnostics"] == {
        "xhs": {"kind": "timeout", "code": capture_code}
    }
    report = json.loads((run_dir / "xhs_report.json").read_text(encoding="utf-8"))
    assert report["reason"] == capture_code


@pytest.mark.parametrize("platform", ["bilibili", "douyin"])
def test_creator_capture_timeout_keeps_only_its_fixed_code(
    platform: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = __import__(
        f"runtime.media_missher_runtime.platforms.{platform}",
        fromlist=["CaptureTimeout"],
    )
    dispatcher = FakeDispatcher(
        {
            platform: module.CaptureTimeout(
                "creator-capture-timeout", observation="identity-mismatch"
            )
        }
    )

    from runtime.media_missher_runtime.cli import main

    returncode = main(
        [
            "creator",
            "--platforms",
            platform,
            f"--{platform}-uid",
            "private-uid",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert returncode == 1
    _, manifest = _manifest(tmp_path)
    assert manifest["diagnostics"] == {
        platform: {"kind": "timeout", "code": "creator-capture-timeout"}
    }
    assert capsys.readouterr().err.strip() == (
        f"media-missher-observation platform={platform} "
        "stage=creator-source result=identity-mismatch"
    )


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("http-403", "http-403"),
        ("http-429", "http-429"),
        ("payload-461", "payload-461"),
        ("payload-471", "payload-471"),
        ("payload-999", "payload-999"),
        ("challenge-selector", "challenge"),
        ("privateuid123", "risk-signal"),
    ],
)
def test_risk_reason_is_mapped_to_a_fixed_code(
    reason: str, code: str, tmp_path: Path
) -> None:
    from runtime.media_missher_runtime.cli import RiskStop, main

    dispatcher = FakeDispatcher({"xhs": RiskStop(reason)})
    returncode = main(
        [
            "creator",
            "--platforms",
            "xhs,douyin",
            "--xhs-uid",
            "private-xhs",
            "--douyin-uid",
            "private-douyin",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert returncode == 75
    run_dir, manifest = _manifest(tmp_path)
    assert manifest["diagnostics"] == {
        "xhs": {"kind": "risk-stop", "code": code},
        "douyin": {"kind": "not-run", "code": "prior-risk-stop"},
    }
    report = json.loads((run_dir / "xhs_report.json").read_text(encoding="utf-8"))
    assert report["reason"] == code
    assert reason not in json.dumps({"manifest": manifest, "report": report}) or reason == code


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


def test_bilibili_complete_reports_still_unknown_detail_as_incomplete_record(
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import main

    record = {
        "platform": "bilibili",
        "id": "synthetic-dynamic",
        "native_id": "synthetic-dynamic",
        "dynamic_id": "synthetic-dynamic",
        "link": "https://t.bilibili.com/synthetic-dynamic",
        "url": "https://t.bilibili.com/synthetic-dynamic",
        "date": "2026-08-13T00:00:00+08:00",
        "title": "Synthetic dynamic",
        "liked": 3,
        "comments": 4,
        "shares": 5,
        "collected": None,
        "detail_attempted": True,
        "detail_completed": False,
        "detail_source": "list_api",
        "complete": False,
        "missing_fields": ["collected"],
    }

    code = main(
        [
            "creator",
            "--platforms",
            "bilibili",
            "--bilibili-uid",
            "synthetic-creator",
            "--count",
            "1",
            "--bilibili-complete",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=FakeDispatcher({"bilibili": [record]}),
    )

    assert code == 1
    run_dir, manifest = _manifest(tmp_path)
    assert manifest["platforms"] == {"bilibili": "incomplete"}
    assert manifest["diagnostics"] == {
        "bilibili": {"kind": "result", "code": "incomplete-record"}
    }
    persisted = json.loads((run_dir / "bilibili.json").read_text(encoding="utf-8"))
    assert persisted[0]["collected"] is None
    assert persisted[0]["missing_fields"] == ["collected"]


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


def test_platform_preflight_failure_emits_only_a_safe_line_before_inner_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.media_missher_runtime.browser import PreconditionError
    from runtime.media_missher_runtime.cli import PlatformPreflightError, main

    class PreflightFailure(FakeDispatcher):
        async def preflight(self, requests: object) -> None:
            raise PlatformPreflightError(
                "xhs",
                PreconditionError(
                    "https://server.invalid/?uid=private-xhs page is missing"
                ),
            )

    dispatcher = PreflightFailure()
    code = main(
        [
            "creator",
            "--platforms",
            "bilibili,xhs",
            "--bilibili-uid",
            "private-bili",
            "--xhs-uid",
            "private-xhs",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert dispatcher.closed is True
    captured = capsys.readouterr()
    assert code == 78
    assert captured.out == ""
    assert captured.err == (
        "media-missher-diagnostic platform=xhs "
        "kind=precondition code=precondition-failed\n"
    )
    assert not list(tmp_path.glob("run-*"))
    assert "server.invalid" not in captured.err
    assert "private-xhs" not in captured.err




def test_risk_stop_wins_over_prior_screenshot_shortfall_and_aborts_later_platform(
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import RiskStop, main

    dispatcher = FakeDispatcher(
        {
            "bilibili": [{
                "platform": "bilibili",
                "id": "bilibili-1",
                "screenshot_status": "failed",
                "screenshot_error_code": "capture-failed",
            }],
            "xhs": RiskStop("payload-471"),
        }
    )
    code = main(
        [
            "creator",
            "--platforms",
            "bilibili,xhs,douyin",
            "--bilibili-uid",
            "b",
            "--xhs-uid",
            "x",
            "--douyin-uid",
            "d",
            "--count",
            "1",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert code == 75
    _, manifest = _manifest(tmp_path)
    assert manifest["status"] == "risk-stopped"
    assert manifest["platforms"] == {
        "bilibili": "incomplete",
        "xhs": "risk-stopped",
        "douyin": "not-run",
    }
    assert manifest["diagnostics"] == {
        "bilibili": {"kind": "result", "code": "screenshot-shortfall"},
        "xhs": {"kind": "risk-stop", "code": "payload-471"},
        "douyin": {"kind": "not-run", "code": "prior-risk-stop"},
    }


def test_platform_risk_preflight_emits_only_a_safe_stop_before_inner_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.media_missher_runtime.cli import PlatformRiskPreflightError, main

    class PreflightRisk(FakeDispatcher):
        async def preflight(self, requests: object) -> None:
            raise PlatformRiskPreflightError("bilibili", "http-429")

    dispatcher = PreflightRisk()
    code = main(
        [
            "creator",
            "--platforms",
            "bilibili,xhs",
            "--bilibili-uid",
            "private-bili",
            "--xhs-uid",
            "private-xhs",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=dispatcher,
    )

    assert dispatcher.closed is True
    captured = capsys.readouterr()
    assert code == 75
    assert captured.out == ""
    assert captured.err == (
        "media-missher-diagnostic platform=bilibili "
        "kind=risk-stop code=http-429\n"
    )
    assert not list(tmp_path.glob("run-*"))
    assert "private-bili" not in captured.err


def test_runtime_dispatcher_preflight_attaches_only_the_failing_platform() -> None:
    from runtime.media_missher_runtime.browser import PreconditionError
    from runtime.media_missher_runtime.cli import (
        PlatformPreflightError,
        RuntimeDispatcher,
    )
    from runtime.media_missher_runtime.models import CollectionRequest

    class Session:
        async def require_authenticated_page(self, platform: str) -> object:
            if platform == "xhs":
                raise PreconditionError("private server detail")
            return object()

    from runtime.media_missher_runtime.shared_safety import collection_lease, runtime_home

    dispatcher = RuntimeDispatcher("http://127.0.0.1:9222")
    dispatcher.browser = Session()
    requests = [
        CollectionRequest(platform="bilibili", count=1, uid="one"),
        CollectionRequest(platform="xhs", count=1, uid="two"),
    ]

    with collection_lease(runtime_home()), pytest.raises(PlatformPreflightError) as failure:
        _run(dispatcher.preflight(requests))

    assert failure.value.platform == "xhs"
    assert isinstance(failure.value.cause, PreconditionError)
    assert str(failure.value) == "platform preflight failed"


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


@pytest.mark.parametrize("timeout", ["nan", "inf"])
def test_platform_timeout_rejects_non_finite_values_before_dispatch(
    timeout: str, tmp_path: Path
) -> None:
    from runtime.media_missher_runtime.cli import main

    dispatcher = FakeDispatcher()
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "search",
                "--platform",
                "weibo",
                "--keyword",
                "topic",
                "--platform-timeout",
                timeout,
                "--output-dir",
                str(tmp_path),
            ],
            dispatcher=dispatcher,
        )

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
            "--allow-navigation", "--screenshot-mode", "all",
        ],
        fixed_platform="xhs",
        dispatcher=dispatcher,
    )

    assert code == 1  # Synthetic records have no required screenshot evidence.
    request = dispatcher.requests[0]
    assert request.platform == "xhs" and request.keyword == "synthetic topic" and request.count == 2
    assert request.comment_limit == 3


@pytest.mark.parametrize(
    ("navigation_flag", "expected"),
    [([], False), (["--allow-navigation"], True)],
)
def test_runtime_cli_requires_explicit_navigation_authorization(
    navigation_flag: list[str],
    expected: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.media_missher_runtime import cli as module

    constructed: list[tuple[str, bool, str]] = []

    class CapturingDispatcher(FakeDispatcher):
        def __init__(
            self,
            cdp_url: str,
            *,
            allow_navigation: bool = False,
            browser_assist: str = "off",
        ) -> None:
            super().__init__()
            constructed.append((cdp_url, allow_navigation, browser_assist))

    async def run_requests(*_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr(module, "RuntimeDispatcher", CapturingDispatcher)
    monkeypatch.setattr(module, "_run_requests", run_requests)
    monkeypatch.setattr(module.asyncio, "run", _run)

    code = module.main(
        [
            "search",
            "--platform",
            "weibo",
            "--keyword",
            "topic",
            "--cdp-url",
            "http://127.0.0.1:9333",
            *navigation_flag,
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert code == 0
    assert constructed == [("http://127.0.0.1:9333", expected, "off")]


def test_runtime_dispatcher_forwards_navigation_authorization_to_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.media_missher_runtime import cli as module

    connected: list[tuple[str, bool, str]] = []

    class Session:
        async def close(self) -> None:
            return None

    async def connect(
        cdp_url: str,
        *,
        allow_navigation: bool = False,
        browser_assist: str = "off",
    ) -> Session:
        connected.append((cdp_url, allow_navigation, browser_assist))
        return Session()

    monkeypatch.setattr(module.BrowserSession, "connect", connect)
    dispatcher = module.RuntimeDispatcher(
        "http://127.0.0.1:9444",
        allow_navigation=True,
        browser_assist="browserskill",
    )

    _run(dispatcher.__aenter__())
    _run(dispatcher.__aexit__())

    assert connected == [("http://127.0.0.1:9444", True, "browserskill")]


def test_runtime_dispatcher_runs_assist_preflight_before_platform_pages() -> None:
    from runtime.media_missher_runtime.cli import RuntimeDispatcher
    from runtime.media_missher_runtime.models import CollectionRequest

    events: list[str] = []

    class Session:
        async def preflight_browser_assist(self) -> None:
            events.append("assist")

        async def require_authenticated_page(self, platform: str) -> object:
            events.append(platform)
            return object()

    dispatcher = RuntimeDispatcher(
        "http://127.0.0.1:9222", browser_assist="browserskill"
    )
    dispatcher.browser = Session()
    requests = [CollectionRequest(platform="xhs", count=1, uid="one")]

    _run(dispatcher.preflight(requests))

    assert events == ["xhs"]


def test_run_store_is_bound_before_collection(
    tmp_path: Path,
) -> None:
    from runtime.media_missher_runtime.cli import main

    events: list[str] = []

    class BindingDispatcher(FakeDispatcher):
        def bind_store(self, store: object) -> None:
            assert getattr(store, "path", None) is not None
            events.append("bind")

        async def collect(self, request: Any) -> list[dict[str, object]]:
            assert events == ["bind"]
            return await super().collect(request)

    code = main(
        [
            "creator",
            "--platforms",
            "bilibili",
            "--bilibili-uid",
            "creator",
            "--count",
            "1",
            "--output-dir",
            str(tmp_path),
        ],
        dispatcher=BindingDispatcher(),
    )

    assert code == 0
    assert events == ["bind"]


def test_platform_timeout_preserves_completed_xhs_records(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.cli import _run_requests
    from runtime.media_missher_runtime.models import CollectionRequest

    partial = [
        {
            "platform": "xhs",
            "note_id": "completed-note",
            "title": "Completed before timeout",
            "complete": True,
        }
    ]

    class TimeoutDispatcher:
        async def __aenter__(self) -> "TimeoutDispatcher":
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def collect(self, _request: object) -> list[dict[str, object]]:
            await asyncio.sleep(1)
            return []

        def partial_records(self, platform: str) -> list[dict[str, object]]:
            assert platform == "xhs"
            return partial

    code = asyncio.run(
        _run_requests(
            [CollectionRequest(platform="xhs", count=2, uid="creator", complete=True)],
            output_dir=tmp_path,
            dispatcher=TimeoutDispatcher(),
            platform_timeout=0.01,
        )
    )

    assert code == 1
    run_dir, manifest = _manifest(tmp_path)
    assert json.loads((run_dir / "xhs.json").read_text(encoding="utf-8")) == partial
    assert manifest["counts"] == {"xhs": 1}
    assert manifest["paths"]["xhs"] == "xhs.json"
    assert manifest["platforms"] == {"xhs": "failed"}
    assert manifest["diagnostics"] == {
        "xhs": {"kind": "timeout", "code": "platform-timeout"}
    }


def test_runtime_dispatcher_preflight_requires_authenticated_pages_once_per_platform() -> None:
    from runtime.media_missher_runtime.cli import RuntimeDispatcher
    from runtime.media_missher_runtime.models import CollectionRequest

    checked: list[str] = []

    class Session:
        async def require_authenticated_page(self, platform: str) -> object:
            checked.append(platform)
            return object()

    from runtime.media_missher_runtime.shared_safety import collection_lease, runtime_home

    dispatcher = RuntimeDispatcher("http://127.0.0.1:9222")
    dispatcher.browser = Session()
    requests = [
        CollectionRequest(platform="weibo", count=1, uid="one"),
        CollectionRequest(platform="weibo", count=2, uid="two"),
        CollectionRequest(platform="xhs", count=1, uid="three"),
    ]

    with collection_lease(runtime_home()):
        _run(dispatcher.preflight(requests))

    assert checked == ["weibo", "xhs"]
