from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Coroutine

import pytest

from runtime.media_missher_runtime.browser import PreconditionError
from runtime.media_missher_runtime.models import CollectionRequest


def _run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fake coroutine unexpectedly suspended")


@dataclass
class Response:
    payload: dict[str, Any]
    status: int = 200
    url: str = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

    async def json(self) -> dict[str, Any]:
        return self.payload


@dataclass
class ResponseWaiter:
    response: Response

    async def __aenter__(self) -> "ResponseWaiter":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    @property
    def value(self) -> Coroutine[Any, Any, Response]:
        async def result() -> Response:
            return self.response

        return result()


@dataclass
class CapturePage:
    url: str = "https://www.bilibili.com/"
    responses: list[Response] = field(default_factory=list)
    gotos: list[str] = field(default_factory=list)
    evaluations: list[str] = field(default_factory=list)
    cards: list[list[dict[str, Any]]] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)

    def expect_response(self, predicate: Any, **kwargs: Any) -> ResponseWaiter:
        response = self.responses.pop(0)
        assert predicate(response)
        return ResponseWaiter(response)

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.gotos.append(url)

    async def evaluate(self, script: str) -> Any:
        self.evaluations.append(script)
        if "__INITIAL_STATE__" in script:
            return self.details.pop(0) if self.details else {"videoData": None, "risk_text": ""}
        if "bili-video-card" in script:
            return self.cards.pop(0) if self.cards else []
        return None


@dataclass
class ProductionBrowser:
    page: CapturePage
    allow_navigation: bool = True
    navigations: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    navigation_result: object = None

    def require_page(self, platform: str) -> CapturePage:
        assert platform == "bilibili"
        return self.page

    async def navigate(self, page: CapturePage, url: str, *, allowed_hosts: tuple[str, ...]) -> None:
        self.navigations.append((url, allowed_hosts))
        if not self.allow_navigation:
            raise PreconditionError("navigation")
        await page.goto(url)
        return self.navigation_result  # type: ignore[return-value]


def _item(identifier: str, *, bvid: str | None = None, comment: object = {"count": 0}) -> dict[str, Any]:
    major = {"archive": {"bvid": bvid, "title": "Synthetic title", "desc": "Synthetic desc"}} if bvid else {}
    return {
        "id_str": identifier,
        "type": "DYNAMIC_TYPE_AV" if bvid else "DYNAMIC_TYPE_WORD",
        "modules": {
            "module_author": {"name": "Synthetic author", "pub_ts": 1_700_000_000},
            "module_dynamic": {"major": major, "desc": {"text": "Synthetic dynamic"}},
            "module_stat": {"comment": comment, "forward": {"count": 2}, "like": {"count": 3}, "favorite": {"count": None}},
        },
    }


def _feed(*items: dict[str, Any], has_more: bool) -> Response:
    return Response({"code": 0, "data": {"items": list(items), "has_more": has_more, "offset": "synthetic-offset"}})


def test_creator_navigates_and_captures_generated_api_responses_without_page_json() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(responses=[_feed(_item("first", bvid="BVcap001"), has_more=True), _feed(_item("second"), has_more=False)])
    browser = ProductionBrowser(page)

    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=2, uid="synthetic-user"), browser))

    assert [record["native_id"] for record in records] == ["first", "second"]
    assert page.gotos == ["https://space.bilibili.com/synthetic-user/dynamic"]
    assert len(page.evaluations) == 1
    assert all("api.bilibili.com" in response.url for response in [])
    assert records[0]["comments"] == 0
    assert records[0]["collected"] is None
    assert records[0]["url"] == records[0]["link"]
    assert records[0]["author"] == "Synthetic author"
    assert records[0]["detail_completed"] is False
    assert records[0]["observed_at"].endswith("+00:00")


def test_creator_navigation_requires_explicit_authorization() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    browser = ProductionBrowser(CapturePage(responses=[_feed(_item("never"), has_more=False)]), allow_navigation=False)

    with pytest.raises(PreconditionError, match="navigation"):
        _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user"), browser))


def test_creator_stops_on_first_risk_response_without_scrolling() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import CollectionStopped, collect_creator

    page = CapturePage(responses=[Response({"code": 461}), _feed(_item("never"), has_more=False)])
    with pytest.raises(CollectionStopped, match="payload-461"):
        _run(collect_creator(CollectionRequest(platform="bilibili", count=2, uid="synthetic-user"), ProductionBrowser(page)))
    assert page.evaluations == []


def test_creator_stops_on_risk_navigation_status_before_parsing_a_feed() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import CollectionStopped, collect_creator

    page = CapturePage(responses=[_feed(_item("never"), has_more=False)])
    browser = ProductionBrowser(page, navigation_result=Response({}, status=403, url="https://space.bilibili.com/synthetic/dynamic"))
    with pytest.raises(CollectionStopped, match="http-403"):
        _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user"), browser))


def test_search_navigates_to_exact_allowlisted_host_and_paginates_count_zero() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    page = CapturePage(cards=[
        [{"bvid": "BVsearch1", "title": "One", "href": "/video/BVsearch1"}],
        [{"bvid": "BVsearch1", "title": "One", "href": "/video/BVsearch1"}, {"bvid": "BVsearch2", "title": "Two", "href": "/video/BVsearch2"}],
        [],
    ])
    browser = ProductionBrowser(page)

    records = _run(search(CollectionRequest(platform="bilibili", count=0, page_cap=3, keyword="two words"), browser))

    assert [record["native_id"] for record in records] == ["BVsearch1", "BVsearch2"]
    assert browser.navigations[0][0] == "https://search.bilibili.com/all?keyword=two+words"
    assert len(page.evaluations) == 5


def test_search_uses_an_existing_search_page_without_navigation() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    page = CapturePage(url="https://search.bilibili.com/all", cards=[[{"bvid": "BVopen001", "title": "Open", "href": "/video/BVopen001"}]])
    browser = ProductionBrowser(page, allow_navigation=False)

    records = _run(search(CollectionRequest(platform="bilibili", count=1, keyword="synthetic"), browser))

    assert records[0]["native_id"] == "BVopen001"
    assert browser.navigations == []


def test_creator_deduplicates_before_count_truncation_across_captured_pages() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(responses=[_feed(_item("one"), _item("two"), has_more=True), _feed(_item("two"), _item("three"), has_more=False)])
    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=3, uid="synthetic-user"), ProductionBrowser(page)))

    assert [record["native_id"] for record in records] == ["one", "two", "three"]


def test_complete_reads_valid_video_data_sequentially_and_stops_on_detail_risk() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import CollectionStopped, collect_creator

    page = CapturePage(
        responses=[_feed(_item("first", bvid="BVdetail1"), _item("second", bvid="BVdetail2"), has_more=False)],
        details=[{"risk_text": "captcha required", "videoData": None}],
    )
    browser = ProductionBrowser(page)

    with pytest.raises(CollectionStopped, match="captcha"):
        _run(collect_creator(CollectionRequest(platform="bilibili", count=2, uid="synthetic-user", complete=True), browser))
    assert page.gotos == ["https://space.bilibili.com/synthetic-user/dynamic", "https://www.bilibili.com/video/BVdetail1"]


def test_complete_requires_a_structurally_valid_current_video_observation() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(
        responses=[_feed(_item("first", bvid="BVdetail1"), has_more=False)],
        details=[{"risk_text": "", "videoData": {"bvid": "BVdetail1", "title": "Complete", "pubdate": 1_700_000_010, "desc": "Desc", "stat": {"like": 3, "reply": 0, "share": 1, "favorite": 2}}}],
    )
    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user", complete=True), ProductionBrowser(page)))

    assert records[0]["complete"] is True
    assert records[0]["detail_completed"] is True
    assert records[0]["missing_fields"] == []
    assert records[0]["comments"] == 0

    invalid_page = CapturePage(
        responses=[_feed(_item("first", bvid="BVdetail1"), has_more=False)],
        details=[{"risk_text": "", "videoData": {"bvid": "BVdetail1", "title": "Incomplete"}}],
    )
    incomplete = _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user", complete=True), ProductionBrowser(invalid_page)))
    assert incomplete[0]["detail_completed"] is False
    assert "detail" in incomplete[0]["missing_fields"]
