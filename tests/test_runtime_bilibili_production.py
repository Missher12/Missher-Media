from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Coroutine

import pytest

from runtime.media_missher_runtime.browser import PreconditionError
from runtime.media_missher_runtime.models import CollectionRequest
from runtime.media_missher_runtime.platforms.bilibili import PlaywrightTimeoutError


def _run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fake coroutine unexpectedly suspended")


@dataclass
class Response:
    payload: object
    status: int = 200
    url: str = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
    json_error: Exception | None = None
    json_calls: int = 0

    async def json(self) -> object:
        self.json_calls += 1
        if self.json_error is not None:
            raise self.json_error
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
    waits: list[list[str]] = field(default_factory=list)

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

    async def wait_for_function(self, script: str, *, arg: list[str], timeout: int) -> None:
        assert timeout == 10_000
        self.waits.append(arg)


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


@dataclass
class DelayedSearchPage(CapturePage):
    card_states: list[list[dict[str, Any]]] = field(default_factory=list)
    wait_outcomes: list[str] = field(default_factory=list)
    state_index: int = 0
    wait_args: list[list[str]] = field(default_factory=list)

    async def evaluate(self, script: str) -> Any:
        self.evaluations.append(script)
        if "bili-video-card" in script:
            return {"risk_text": "", "cards": self.card_states[self.state_index]}
        return None

    async def wait_for_function(self, script: str, *, arg: list[str], timeout: int) -> None:
        assert timeout == 10_000
        self.wait_args.append(arg)
        outcome = self.wait_outcomes.pop(0)
        if outcome == "timeout":
            raise PlaywrightTimeoutError("synthetic timeout")
        self.state_index += 1


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


@pytest.mark.parametrize("status", (403, 429))
def test_creator_classifies_risk_status_before_attempting_json(status: int) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import CollectionStopped, collect_creator

    response = Response(None, status=status, json_error=AssertionError("json must not be called"))
    page = CapturePage(responses=[response])

    with pytest.raises(CollectionStopped, match=f"http-{status}"):
        _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user"), ProductionBrowser(page)))
    assert response.json_calls == 0


def test_creator_reports_nonrisk_http_and_json_decode_failures_explicitly() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    server_error = Response({}, status=500)
    with pytest.raises(RuntimeError, match="http-500"):
        _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user"), ProductionBrowser(CapturePage(responses=[server_error]))))

    invalid_json = Response(None, json_error=ValueError("synthetic decode"))
    with pytest.raises(RuntimeError, match="decode"):
        _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user"), ProductionBrowser(CapturePage(responses=[invalid_json]))))


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


def test_search_waits_for_initial_hydration_and_delayed_scrolled_cards() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    page = DelayedSearchPage(
        card_states=[
            [],
            [{"bvid": "BVdelay1", "title": "One", "href": "/video/BVdelay1"}],
            [
                {"bvid": "BVdelay1", "title": "One", "href": "/video/BVdelay1"},
                {"bvid": "BVdelay2", "title": "Two", "href": "/video/BVdelay2"},
            ],
        ],
        wait_outcomes=["advance", "advance"],
    )

    records = _run(search(CollectionRequest(platform="bilibili", count=2, page_cap=3, keyword="delayed"), ProductionBrowser(page)))

    assert [record["native_id"] for record in records] == ["BVdelay1", "BVdelay2"]
    assert page.wait_args == [[], ["BVdelay1"]]


def test_search_timeout_after_scroll_treats_unchanged_cards_as_exhausted() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    page = DelayedSearchPage(
        url="https://search.bilibili.com/all",
        card_states=[[{"bvid": "BVonly", "title": "Only", "href": "/video/BVonly"}]],
        wait_outcomes=["timeout"],
    )

    records = _run(search(CollectionRequest(platform="bilibili", count=0, page_cap=3, keyword="synthetic"), ProductionBrowser(page, allow_navigation=False)))

    assert [record["native_id"] for record in records] == ["BVonly"]
    assert page.wait_args == [["BVonly"]]


def test_search_uses_an_existing_search_page_without_navigation() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    page = CapturePage(url="https://search.bilibili.com/all", cards=[[{"bvid": "BVopen001", "title": "Open", "href": "/video/BVopen001"}]])
    browser = ProductionBrowser(page, allow_navigation=False)

    records = _run(search(CollectionRequest(platform="bilibili", count=1, keyword="synthetic"), browser))

    assert records[0]["native_id"] == "BVopen001"
    assert browser.navigations == []


def test_search_stops_immediately_when_open_page_reports_a_captcha_marker() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import CollectionStopped, search

    class RiskSearchPage(CapturePage):
        async def evaluate(self, script: str) -> Any:
            self.evaluations.append(script)
            if "bili-video-card" in script:
                return {"risk_text": "challenge-selector", "cards": [{"bvid": "BVnever", "title": "Never", "href": "/video/BVnever"}]}
            return None

    page = RiskSearchPage(url="https://search.bilibili.com/all")
    with pytest.raises(CollectionStopped, match="challenge"):
        _run(search(CollectionRequest(platform="bilibili", count=0, page_cap=3, keyword="synthetic"), ProductionBrowser(page, allow_navigation=False)))
    assert len(page.evaluations) == 1


def test_search_does_not_treat_ordinary_english_risk_text_as_a_challenge() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    page = CapturePage(url="https://search.bilibili.com/all", cards=[[
        {"bvid": "BVordinary", "title": "Risk analysis", "description": "A normal discussion of risk", "href": "/video/BVordinary"},
    ]])
    record = _run(search(CollectionRequest(platform="bilibili", count=1, keyword="risk"), ProductionBrowser(page, allow_navigation=False)))[0]

    assert record["native_id"] == "BVordinary"
    assert record["title"] == "Risk analysis"


def test_search_observer_whitelists_visible_legacy_business_metadata() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    page = CapturePage(url="https://search.bilibili.com/all", cards=[[{
        "bvid": "BVvisible",
        "title": "Visible",
        "href": "/video/BVvisible?spm_id_from=must-not-return",
        "description": "Visible description",
        "play": "1.2万",
        "duration": "03:21",
        "tag": "动画",
        "author": "Visible author",
        "date": "2026-08-03",
    }]])

    record = _run(search(
        CollectionRequest(platform="bilibili", count=1, keyword="visible"),
        ProductionBrowser(page, allow_navigation=False),
    ))[0]

    assert (record["play"], record["duration"], record["tag"]) == (12_000, "03:21", "动画")
    script = next(script for script in page.evaluations if "bili-video-card" in script)
    assert "return {bvid, title, href, description, play, duration, tag, author, date};" in script
    assert all(fragment not in script for fragment in ("fetch(", "__INITIAL_STATE__", ".dataset", "mid:", "uid:"))


def test_creator_deduplicates_before_count_truncation_across_captured_pages() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(responses=[_feed(_item("one"), _item("two"), has_more=True), _feed(_item("two"), _item("three"), has_more=False)])
    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=3, uid="synthetic-user"), ProductionBrowser(page)))

    assert [record["native_id"] for record in records] == ["one", "two", "three"]


def test_creator_stops_without_consuming_a_third_page_when_a_page_adds_no_records() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(responses=[
        _feed(_item("one"), has_more=True),
        _feed(_item("one"), has_more=True),
        _feed(_item("never"), has_more=False),
    ])
    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=0, page_cap=3, uid="synthetic-user"), ProductionBrowser(page)))

    assert [record["native_id"] for record in records] == ["one"]
    assert len(page.responses) == 1


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
    assert records[0]["detail_attempted"] is True
    assert records[0]["detail_completed"] is True
    assert records[0]["detail_source"] == "detail_api"
    assert records[0]["title_source"] == "detail_api"
    assert records[0]["content_source"] == "detail_api"
    assert records[0]["publish_time"] == 1_700_000_010_000
    assert records[0]["date_source"] == "detail_api"
    assert records[0]["missing_fields"] == []
    assert records[0]["comments"] == 0

    invalid_page = CapturePage(
        responses=[_feed(_item("first", bvid="BVdetail1"), has_more=False)],
        details=[{"risk_text": "", "videoData": {"bvid": "BVdetail1", "title": "Incomplete"}}],
    )
    incomplete = _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user", complete=True), ProductionBrowser(invalid_page)))
    assert incomplete[0]["detail_attempted"] is True
    assert incomplete[0]["detail_completed"] is False
    assert incomplete[0]["detail_source"] == "list_api"
    assert "detail" in incomplete[0]["missing_fields"]


def test_complete_rejects_video_detail_with_unparseable_publish_time() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(
        responses=[_feed(_item("first", bvid="BVdetail1"), has_more=False)],
        details=[{
            "risk_text": "",
            "videoData": {
                "bvid": "BVdetail1",
                "title": "Complete",
                "pubdate": "not-a-timestamp",
                "desc": "Desc",
                "stat": {"like": 3, "reply": 0, "share": 1, "favorite": 2},
            },
        }],
    )

    record = _run(
        collect_creator(
            CollectionRequest(platform="bilibili", count=1, uid="synthetic-user", complete=True),
            ProductionBrowser(page),
        )
    )[0]

    assert record["detail_attempted"] is True
    assert record["detail_completed"] is False
    assert record["complete"] is False
    assert "detail" in record["missing_fields"]


def test_complete_accepts_authoritative_list_payload_for_nonvideo_dynamic() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    item = _item("word")
    item["modules"]["module_stat"]["favorite"] = {"count": 4}
    page = CapturePage(responses=[_feed(item, has_more=False)])

    record = _run(
        collect_creator(
            CollectionRequest(platform="bilibili", count=1, uid="synthetic-user", complete=True),
            ProductionBrowser(page),
        )
    )[0]

    assert record["type"] == "dynamic"
    assert record["detail_attempted"] is False
    assert record["detail_completed"] is True
    assert record["detail_source"] == "list_api"
    assert record["complete"] is True
    assert record["missing_fields"] == []
    assert page.gotos == ["https://space.bilibili.com/synthetic-user/dynamic"]


def test_complete_keeps_a_placeholder_detail_title_incomplete() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(
        responses=[_feed(_item("first", bvid="BVdetail1"), has_more=False)],
        details=[{"risk_text": "", "videoData": {"bvid": "BVdetail1", "title": "--", "pubdate": 1_700_000_010, "desc": "Desc", "stat": {"like": 3, "reply": 0, "share": 1, "favorite": 2}}}],
    )
    record = _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user", complete=True), ProductionBrowser(page)))[0]

    assert record["detail_completed"] is True
    assert record["complete"] is False
    assert record["missing_fields"] == ["title"]
