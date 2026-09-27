from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
import pytest

from media_missher_adapter import CollectionRequest as AdapterRequest
from media_missher_adapter import RuntimeLayout, build_engine_command, discover_current_json
from runtime.media_missher_runtime import cli
from runtime.media_missher_runtime.models import CollectionRequest


def test_cancelled_controller_preserves_committed_platform(tmp_path: Path) -> None:
    class Dispatcher:
        def __init__(self):
            self.second_started = asyncio.Event()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def collect(self, request):
            if request.platform == "bilibili":
                return [{"platform": "bilibili", "bvid": "BVsynthetic", "title": "fixture"}]
            self.second_started.set()
            await asyncio.Event().wait()

    async def exercise():
        dispatcher = Dispatcher()
        operation = asyncio.create_task(cli._run_requests(
            [CollectionRequest("bilibili", 1, uid="fixture"), CollectionRequest("xhs", 1, uid="fixture")],
            output_dir=tmp_path, dispatcher=dispatcher, platform_timeout=10,
        ))
        await dispatcher.second_started.wait()
        operation.cancel()
        try:
            await operation
        except asyncio.CancelledError:
            pass

    started = tmp_path.stat().st_mtime_ns
    asyncio.run(exercise())
    artifacts = discover_current_json(tmp_path, started_ns=started)
    manifest_path = next(path for path in artifacts if path.name == "manifest.json")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["counts"]["bilibili"] == 1
    assert manifest["platforms"]["bilibili"] == "complete"
    assert manifest["status"] == "failed"


def test_search_parameters_reach_runtime(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    request = AdapterRequest(
        platforms=("xhs",), search="fixture", count=2, xhs_comments=7,
        platform_timeout=45, allow_navigation=True, screenshot_mode="all",
    )
    layout = RuntimeLayout(tmp_path, repository / "runtime", Path(sys.executable), tmp_path / "state")
    command = build_engine_command(request, tmp_path, layout=layout)
    parser = cli.build_parser(fixed_platform="xhs")
    parsed = parser.parse_args(cli._normalize_legacy_argv(command.argv[2:]))
    effective = cli._requests_from_args(parser, parsed)[0]
    assert parsed.platform_timeout == 45
    assert effective.comment_limit == 7


def test_douyin_crosses_duplicate_page_with_advancing_cursor() -> None:
    from test_runtime_douyin import CapturePage, ProductionBrowser, _aweme, _creator
    from runtime.media_missher_runtime.platforms.douyin import collect_creator
    page = CapturePage(responses=[
        _creator(_aweme("one"), has_more=True, cursor=1),
        _creator(_aweme("one"), has_more=True, cursor=2),
        _creator(_aweme("two"), has_more=False, cursor=3),
    ])
    result = asyncio.run(collect_creator(CollectionRequest("douyin", 2, page_cap=3, uid="creator"), ProductionBrowser(page)))
    assert [item["native_id"] for item in result] == ["one", "two"]


def test_weibo_crosses_duplicate_page_with_advancing_cursor() -> None:
    from test_runtime_weibo import Page, Browser, _creator, _post
    from runtime.media_missher_runtime.platforms.weibo import collect_creator
    page = Page(responses=[
        _creator(_post("one"), since_id="first"),
        _creator(_post("one"), since_id="second"),
        _creator(_post("two"), since_id=None),
    ])
    result = asyncio.run(collect_creator(CollectionRequest("weibo", 2, page_cap=3, uid="creator"), Browser(page)))
    assert [item["native_id"] for item in result] == ["MBone", "MBtwo"]


@pytest.mark.parametrize("stop", ["risk", "cancel"])
def test_accepted_prefix_is_durable_before_platform_returns(tmp_path: Path, stop: str) -> None:
    class Dispatcher:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
        def bind_progress(self, sink):
            self.sink = sink
        def partial_records(self, platform):
            return self.prefix
        async def collect(self, request):
            self.prefix = [{"platform": "xhs", "native_id": "one", "note_id": "one", "complete": True}]
            self.sink("xhs", self.prefix)
            manifest = json.loads(next(tmp_path.glob("run-*/manifest.json")).read_text())
            assert manifest["counts"]["xhs"] == 1
            assert manifest["status"] != "complete"
            if stop == "risk":
                raise cli.RiskStop("http-429")
            raise asyncio.CancelledError
    async def exercise():
        try:
            return await cli._run_requests([CollectionRequest("xhs", 2, uid="fixture")], output_dir=tmp_path, dispatcher=Dispatcher(), platform_timeout=10)
        except asyncio.CancelledError:
            return None
    result = asyncio.run(exercise())
    manifest = json.loads(next(tmp_path.glob("run-*/manifest.json")).read_text())
    assert manifest["counts"]["xhs"] == 1
    assert manifest["status"] == ("risk-stopped" if stop == "risk" else "failed")
    assert result == (75 if stop == "risk" else None)


def test_resume_skips_known_xhs_notes_before_detail_open() -> None:
    from runtime.media_missher_runtime.platforms import xhs
    from test_runtime_xhs import Page, Browser, creator_response, note, run
    page = Page(responses=[creator_response(note("old"), note("new"))])
    records = run(xhs.collect_creator(CollectionRequest("xhs", 1, uid="u", exclude_ids=("old",)), Browser(page)))
    assert [item["native_id"] for item in records] == ["new"]
    assert "old" not in page.clicked


def test_search_comments_without_detail_mode_are_rejected(tmp_path: Path) -> None:
    parser = cli.build_parser()
    parsed = parser.parse_args(["search", "--platform", "xhs", "--keyword", "fixture", "--comments", "1", "--output", str(tmp_path)])
    with pytest.raises(SystemExit):
        cli._requests_from_args(parser, parsed)


def test_bilibili_duplicate_page_requires_an_advancing_offset() -> None:
    from test_runtime_bilibili_production import CapturePage, ProductionBrowser, _feed, _item, _run
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator
    responses = [_feed(_item("one"), has_more=True), _feed(_item("one"), has_more=True), _feed(_item("two"), has_more=False)]
    for index, response in enumerate(responses):
        response.payload["data"]["offset"] = str(index + 1)
    page = CapturePage(responses=responses)
    records = _run(collect_creator(CollectionRequest("bilibili", 2, uid="synthetic-user"), ProductionBrowser(page)))
    assert [item["native_id"] for item in records] == ["one", "two"]
