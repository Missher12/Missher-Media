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
    url: str = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid=synthetic-user"
    json_error: Exception | None = None
    json_calls: int = 0

    async def json(self) -> object:
        self.json_calls += 1
        if self.json_error is not None:
            raise self.json_error
        return self.payload


@dataclass(frozen=True)
class ObservedRequest:
    resource_type: str = "document"


@dataclass(frozen=True)
class ObservedResponse:
    url: str
    status: int
    request: ObservedRequest = field(default_factory=ObservedRequest)


@dataclass
class ResponseEventContext:
    listeners: list[Any] = field(default_factory=list)

    def on(self, event: str, listener: Any) -> None:
        assert event == "response"
        self.listeners.append(listener)

    def remove_listener(self, event: str, listener: Any) -> None:
        assert event == "response"
        self.listeners.remove(listener)

    def emit_response(self, response: ObservedResponse) -> None:
        for listener in tuple(self.listeners):
            listener(response)


@dataclass
class UnremovableResponseEventContext:
    listeners: list[Any] = field(default_factory=list)

    def on(self, event: str, listener: Any) -> None:
        assert event == "response"
        self.listeners.append(listener)


def test_creator_response_predicate_is_bound_to_the_requested_uid() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import _is_feed_response

    wrong = Response({}, url="https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid=other")
    right = Response({}, url="https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid=target")

    assert _is_feed_response(wrong, "target") is False
    assert _is_feed_response(right, "target") is True


def test_safe_observed_api_route_omits_query_and_rejects_dynamic_paths() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        _safe_observed_api_route,
    )

    response = Response(
        {},
        url=(
            "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space-v2"
            "?host_mid=must-not-leak&token=must-not-leak"
        ),
    )

    assert _safe_observed_api_route(response) == (
        "api.bilibili.com/x/polymer/web-dynamic/v1/feed/space-v2"
    )
    assert _safe_observed_api_route(
        Response({}, url="https://space.bilibili.com/must-not-leak/dynamic")
    ) is None


@pytest.mark.parametrize("identity_key", ("host_mid", "mid"))
def test_creator_response_predicate_accepts_exact_official_identity_aliases(
    identity_key: str,
) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import _is_feed_response

    exact = Response(
        {},
        url=(
            "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
            f"?{identity_key}=target"
        ),
    )
    conflicting = Response(
        {},
        url=(
            "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
            f"?{identity_key}=target&{identity_key}=other"
        ),
    )

    assert _is_feed_response(exact, "target") is True
    assert _is_feed_response(conflicting, "target") is False


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
class InitialTimeoutWaiter:
    async def __aenter__(self) -> "InitialTimeoutWaiter":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    @property
    def value(self) -> Coroutine[Any, Any, Response]:
        async def result() -> Response:
            raise PlaywrightTimeoutError("synthetic initial response timeout")

        return result()


@dataclass
class CapturePage:
    url: str = "https://www.bilibili.com/"
    responses: list[Response] = field(default_factory=list)
    gotos: list[str] = field(default_factory=list)
    evaluations: list[str] = field(default_factory=list)
    cards: list[list[dict[str, Any]]] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)
    dynamic_details: list[dict[str, Any]] = field(default_factory=list)
    dynamic_elements: list[Any] = field(default_factory=list)
    dynamic_targets_require_feed: bool = False
    waits: list[Any] = field(default_factory=list)

    def expect_response(self, predicate: Any, **kwargs: Any) -> ResponseWaiter:
        response = self.responses.pop(0)
        assert predicate(response)
        return ResponseWaiter(response)

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.gotos.append(url)

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        self.evaluations.append(script)
        if "MEDIA_MISSHER_DYNAMIC_DETAIL" in script:
            return self.dynamic_details.pop(0) if self.dynamic_details else {
                "dynamic_id": arg,
                "risk_text": "",
                "liked": None,
                "comments": None,
                "shares": None,
                "collected": None,
            }
        if "__INITIAL_STATE__" in script:
            return self.details.pop(0) if self.details else {"videoData": None, "risk_text": ""}
        if "bili-video-card" in script:
            return self.cards.pop(0) if self.cards else []
        return None

    def locator(self, _selector: str) -> "DynamicLocator":
        elements = self.dynamic_elements
        if self.dynamic_targets_require_feed and not self.url.endswith("/dynamic"):
            elements = []
        return DynamicLocator(elements)

    async def wait_for_function(self, script: str, *, arg: Any, timeout: int) -> None:
        if "MEDIA_MISSHER_WAIT_EXACT_DYNAMIC_TARGET" in script:
            assert timeout == 5_000
            self.waits.append(arg)
            return
        assert timeout == 10_000
        self.waits.append(arg)


@dataclass
class ProductionBrowser:
    page: CapturePage
    allow_navigation: bool = True
    navigations: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    navigation_result: object = None
    detail_open: Any = None
    screenshots: Any = None

    def require_page(self, platform: str) -> CapturePage:
        assert platform == "bilibili"
        return self.page

    async def navigate(self, page: CapturePage, url: str, *, allowed_hosts: tuple[str, ...]) -> None:
        self.navigations.append((url, allowed_hosts))
        if not self.allow_navigation:
            raise PreconditionError("navigation")
        await page.goto(url)
        return self.navigation_result  # type: ignore[return-value]


def test_creator_initial_response_timeout_has_a_safe_specific_code() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        CaptureTimeout,
        collect_creator,
    )

    class InitialTimeoutPage(CapturePage):
        def expect_response(self, predicate: Any, **kwargs: Any) -> InitialTimeoutWaiter:
            assert kwargs["timeout"] == 10_000
            return InitialTimeoutWaiter()

    with pytest.raises(CaptureTimeout) as timeout:
        _run(
            collect_creator(
                CollectionRequest(platform="bilibili", count=1, uid="creator"),
                ProductionBrowser(InitialTimeoutPage()),
            )
        )

    assert timeout.value.code == "creator-capture-timeout"
    assert timeout.value.observation == "no-endpoint"


@dataclass
class DelayedSearchPage(CapturePage):
    card_states: list[list[dict[str, Any]]] = field(default_factory=list)
    wait_outcomes: list[str] = field(default_factory=list)
    state_index: int = 0
    wait_args: list[list[str]] = field(default_factory=list)

    async def evaluate(self, script: str, arg: Any = None) -> Any:
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


@dataclass
class DelayedDynamicPage(CapturePage):
    dynamic_states_after_wait: list[list[Any]] = field(default_factory=list)
    dynamic_wait_outcomes: list[str] = field(default_factory=list)
    dynamic_wait_args: list[str] = field(default_factory=list)
    dynamic_feed_risks: list[str] = field(default_factory=list)
    dynamic_risk_checks: int = 0

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if "MEDIA_MISSHER_DYNAMIC_FEED_RISK" in script:
            self.dynamic_risk_checks += 1
            return {
                "risk_text": self.dynamic_feed_risks.pop(0)
                if self.dynamic_feed_risks
                else ""
            }
        return await super().evaluate(script, arg)

    async def wait_for_function(self, script: str, *, arg: Any, timeout: int) -> None:
        if "MEDIA_MISSHER_WAIT_EXACT_DYNAMIC_TARGET" not in script:
            await super().wait_for_function(script, arg=arg, timeout=timeout)
            return
        assert timeout == 5_000
        assert isinstance(arg, str)
        self.dynamic_wait_args.append(arg)
        outcome = self.dynamic_wait_outcomes.pop(0) if self.dynamic_wait_outcomes else "ready"
        if outcome == "timeout":
            raise PlaywrightTimeoutError("synthetic dynamic timeout")
        if self.dynamic_states_after_wait:
            self.dynamic_elements = self.dynamic_states_after_wait.pop(0)


@dataclass
class DynamicElement:
    dynamic_id: str | None = None
    href: str | None = None
    clickable: bool = True
    disposed: bool = False

    async def evaluate(self, script: str, expected: str) -> bool:
        assert "MEDIA_MISSHER_EXACT_DYNAMIC_TARGET" in script
        return self.clickable and (self.dynamic_id == expected or self.href in {
            f"https://t.bilibili.com/{expected}",
            f"https://www.bilibili.com/opus/{expected}",
        })

    async def dispose(self) -> None:
        self.disposed = True


@dataclass
class DynamicLocator:
    elements: list[Any]

    async def element_handles(self) -> list[Any]:
        return self.elements


@dataclass
class AssistedCoordinator:
    result_page: CapturePage | None = None
    clicks: list[str] = field(default_factory=list)
    retry_policies: list[bool] = field(default_factory=list)
    released: list[CapturePage] = field(default_factory=list)
    responses_to_emit: list[ObservedResponse] = field(default_factory=list)
    click_error: BaseException | None = None

    async def click_exact(
        self,
        page: CapturePage,
        element: DynamicElement,
        *,
        platform: str,
        native_id: str,
        retry_stale_selector: bool = True,
    ) -> CapturePage:
        assert platform == "bilibili"
        assert element.dynamic_id == native_id or element.href is not None
        self.clicks.append(native_id)
        self.retry_policies.append(retry_stale_selector)
        context = getattr(page, "context", None)
        for response in self.responses_to_emit:
            context.emit_response(response)
        if self.click_error is not None:
            raise self.click_error
        target = self.result_page or page
        target.url = f"https://t.bilibili.com/{native_id}"
        return target

    async def release(self, page: CapturePage) -> None:
        self.released.append(page)


@dataclass(frozen=True)
class ScreenshotArtifact:
    native_id: str
    request_mode: str

    def as_record_fields(self) -> dict[str, str]:
        return {
            "screenshot_path": f"screenshots/bilibili-{self.native_id}.png",
            "screenshot_mode": self.request_mode,
            "screenshot_capture_kind": "article",
            "screenshot_observed_at": "2026-08-11T00:00:00+00:00",
            "screenshot_sha256": "b" * 64,
            "screenshot_status": "complete",
        }


@dataclass
class Screenshots:
    failure: BaseException | None = None
    captures: list[tuple[str, str, str]] = field(default_factory=list)

    async def capture(
        self,
        _page: CapturePage,
        *,
        platform: str,
        native_id: str,
        request_mode: str,
    ) -> ScreenshotArtifact:
        self.captures.append((platform, native_id, request_mode))
        if self.failure is not None:
            raise self.failure
        return ScreenshotArtifact(native_id, request_mode)


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


def test_creator_accepts_an_unbound_query_only_after_exact_payload_identity() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    item = _item("payload-bound")
    item["modules"]["module_author"]["mid"] = "synthetic-user"
    response = _feed(item, has_more=False)
    response.url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

    records = _run(
        collect_creator(
            CollectionRequest(
                platform="bilibili", count=1, uid="synthetic-user"
            ),
            ProductionBrowser(CapturePage(responses=[response])),
        )
    )

    assert [record["native_id"] for record in records] == ["payload-bound"]


def test_creator_rejects_an_unbound_query_without_exact_payload_identity() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        SourceResponseError,
        collect_creator,
    )

    item = _item("wrong-payload")
    item["modules"]["module_author"]["mid"] = "other"
    response = _feed(item, has_more=False)
    response.url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

    with pytest.raises(SourceResponseError, match="payload identity"):
        _run(
            collect_creator(
                CollectionRequest(
                    platform="bilibili", count=1, uid="synthetic-user"
                ),
                ProductionBrowser(CapturePage(responses=[response])),
            )
        )


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


def test_complete_opens_unknown_dynamic_without_browserskill_and_only_fills_missing_metrics() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    item = _item("123456", comment={"count": 4})
    item["modules"]["module_stat"]["forward"] = {"count": 5}
    page = CapturePage(
        responses=[_feed(item, has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": 30_000,
            "comments": 40_000,
            "shares": 50_000,
            "collected": 6,
        }],
    )
    coordinator = AssistedCoordinator()

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            complete=True,
            browser_assist="off",
        ),
        ProductionBrowser(page, detail_open=coordinator),
    ))[0]

    assert coordinator.clicks == ["123456"]
    assert coordinator.retry_policies == [False]
    assert (record["liked"], record["comments"], record["shares"]) == (3, 4, 5)
    assert record["collected"] == 6
    assert record["detail_attempted"] is True
    assert record["detail_completed"] is True
    assert record["complete"] is True
    assert record["missing_fields"] == []


def test_complete_unknown_dynamic_remains_incomplete_after_one_bridge_free_click() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": None,
            "comments": None,
            "shares": None,
            "collected": None,
        }],
    )
    coordinator = AssistedCoordinator()
    screenshots = Screenshots()

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            complete=True,
            browser_assist="off",
        ),
        ProductionBrowser(page, detail_open=coordinator, screenshots=screenshots),
    ))[0]

    assert coordinator.clicks == ["123456"]
    assert coordinator.retry_policies == [False]
    assert record["detail_attempted"] is True
    assert record["collected"] is None
    assert record["complete"] is False
    assert record["missing_fields"] == ["collected"]
    assert screenshots.captures == []


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


@pytest.mark.asyncio
async def test_dynamic_target_finder_requires_one_exact_id_match() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        _find_exact_dynamic_target,
    )

    other = DynamicElement(dynamic_id="other")
    hidden = DynamicElement(dynamic_id="123456", clickable=False)
    expected = DynamicElement(dynamic_id="123456")
    page = CapturePage(dynamic_elements=[other, hidden, expected])

    assert await _find_exact_dynamic_target(page, "123456") is expected
    assert other.disposed is True
    assert hidden.disposed is True
    assert expected.disposed is False

    duplicate = DynamicElement(href="https://t.bilibili.com/123456")
    page.dynamic_elements.append(duplicate)
    with pytest.raises(PreconditionError, match="exact Bilibili dynamic target is ambiguous"):
        await _find_exact_dynamic_target(page, "123456")
    assert all(element.disposed for element in page.dynamic_elements)


def test_exact_dynamic_target_wait_uses_one_css_selector_literal() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        _wait_for_exact_dynamic_target,
    )

    class ScriptPage:
        script = ""

        async def wait_for_function(
            self, script: str, *, arg: Any, timeout: int
        ) -> None:
            assert arg == "synthetic"
            assert timeout == 5_000
            self.script = script

    page = ScriptPage()
    _run(_wait_for_exact_dynamic_target(page, "synthetic"))

    assert (
        "'a[href*=\"t.bilibili.com/\"], a[href*=\"/opus/\"], "
        "[data-did], [dyn-id], [data-dynamic-id]'"
    ) in page.script


def test_dynamic_feed_risk_uses_one_css_selector_literal() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        _read_dynamic_feed_risk,
    )

    class ScriptPage:
        script = ""

        async def evaluate(self, script: str) -> dict[str, str]:
            self.script = script
            return {"risk_text": ""}

    page = ScriptPage()
    _run(_read_dynamic_feed_risk(page))

    assert (
        "'.geetest_panel, .geetest_holder, #geetest-wrap, "
        "iframe[src*=\"geetest\"], [class*=\"captcha\"]'"
    ) in page.script


def test_creator_restores_feed_between_video_and_dynamic_records() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    dynamic = DynamicElement(dynamic_id="second")
    page = DelayedDynamicPage(
        responses=[
            _feed(
                _item("first", bvid="BVfirst1"),
                _item("second"),
                has_more=False,
            )
        ],
        details=[{
            "risk_text": "",
            "videoData": {
                "bvid": "BVfirst1",
                "title": "First",
                "pubdate": 1_700_000_010,
                "desc": "First video",
                "stat": {"like": 3, "reply": 0, "share": 1, "favorite": 2},
            },
        }],
        dynamic_details=[{
            "dynamic_id": "second",
            "risk_text": "",
            "liked": 3,
            "comments": 4,
            "shares": 5,
            "collected": 6,
        }],
        dynamic_elements=[],
        dynamic_states_after_wait=[[dynamic]],
        dynamic_targets_require_feed=True,
    )
    coordinator = AssistedCoordinator()

    records = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=2,
            uid="synthetic-user",
            complete=True,
            browser_assist="browserskill",
        ),
        ProductionBrowser(page, detail_open=coordinator),
    ))

    assert [record["native_id"] for record in records] == ["first", "second"]
    assert page.gotos == [
        "https://space.bilibili.com/synthetic-user/dynamic",
        "https://www.bilibili.com/video/BVfirst1",
        "https://space.bilibili.com/synthetic-user/dynamic",
    ]
    assert coordinator.clicks == ["second"]
    assert page.dynamic_wait_args == ["second"]
    assert page.dynamic_risk_checks == 1
    assert dynamic.disposed is True


def test_creator_restores_feed_between_two_same_page_dynamics() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    first = DynamicElement(dynamic_id="first")
    second = DynamicElement(dynamic_id="second")
    page = DelayedDynamicPage(
        responses=[_feed(_item("first"), _item("second"), has_more=False)],
        dynamic_details=[
            {"dynamic_id": "first", "risk_text": "", "liked": 1, "comments": 2, "shares": 3, "collected": 4},
            {"dynamic_id": "second", "risk_text": "", "liked": 5, "comments": 6, "shares": 7, "collected": 8},
        ],
        dynamic_elements=[],
        dynamic_states_after_wait=[[first], [second]],
        dynamic_targets_require_feed=True,
    )
    coordinator = AssistedCoordinator()

    records = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=2,
            uid="synthetic-user",
            browser_assist="browserskill",
        ),
        ProductionBrowser(page, detail_open=coordinator),
    ))

    assert [record["native_id"] for record in records] == ["first", "second"]
    assert coordinator.clicks == ["first", "second"]
    assert page.dynamic_wait_args == ["first", "second"]
    assert page.dynamic_risk_checks == 2
    assert page.gotos == [
        "https://space.bilibili.com/synthetic-user/dynamic",
        "https://space.bilibili.com/synthetic-user/dynamic",
    ]
    assert first.disposed is True
    assert second.disposed is True


def test_creator_dynamic_target_wait_timeout_fails_without_clicking() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = DelayedDynamicPage(
        responses=[_feed(_item("delayed"), has_more=False)],
        dynamic_wait_outcomes=["timeout"],
    )
    coordinator = AssistedCoordinator()

    with pytest.raises(PreconditionError, match="exact Bilibili dynamic target unavailable"):
        _run(collect_creator(
            CollectionRequest(
                platform="bilibili",
                count=1,
                uid="synthetic-user",
                browser_assist="browserskill",
            ),
            ProductionBrowser(page, detail_open=coordinator),
        ))

    assert coordinator.clicks == []
    assert page.dynamic_wait_args == ["delayed"]
    assert page.dynamic_risk_checks == 1


def test_creator_dynamic_target_wait_rechecks_risk_before_finding_target() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        CollectionStopped,
        collect_creator,
    )

    target = DynamicElement(dynamic_id="blocked")
    page = DelayedDynamicPage(
        responses=[_feed(_item("blocked"), has_more=False)],
        dynamic_states_after_wait=[[target]],
        dynamic_feed_risks=["请完成验证"],
    )
    coordinator = AssistedCoordinator()

    with pytest.raises(CollectionStopped, match="请完成验证"):
        _run(collect_creator(
            CollectionRequest(
                platform="bilibili",
                count=1,
                uid="synthetic-user",
                browser_assist="browserskill",
            ),
            ProductionBrowser(page, detail_open=coordinator),
        ))

    assert coordinator.clicks == []
    assert page.dynamic_risk_checks == 1


def test_popup_dynamic_is_released_immediately_after_record() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    target = DynamicElement(dynamic_id="123456")
    popup = CapturePage(dynamic_details=[{
        "dynamic_id": "123456",
        "risk_text": "",
        "liked": 3,
        "comments": 4,
        "shares": 5,
        "collected": 6,
    }])
    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[target],
    )
    coordinator = AssistedCoordinator(result_page=popup)

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            browser_assist="browserskill",
        ),
        ProductionBrowser(page, detail_open=coordinator),
    ))[0]

    assert record["detail_completed"] is True
    assert coordinator.released == [popup]
    assert target.disposed is True
    assert page.url == "https://space.bilibili.com/synthetic-user/dynamic"


@pytest.mark.parametrize(("status", "use_popup"), ((403, False), (429, True)))
def test_dynamic_detail_exact_document_http_risk_stops_before_dom_or_screenshot(
    status: int, use_popup: bool
) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        CollectionStopped,
        collect_creator,
    )

    detail_page = CapturePage(dynamic_details=[{
        "dynamic_id": "123456",
        "risk_text": "",
        "liked": 30,
        "comments": 40,
        "shares": 50,
        "collected": 60,
    }])
    target = DynamicElement(dynamic_id="123456")
    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[target],
        dynamic_details=[] if use_popup else list(detail_page.dynamic_details),
    )
    context = ResponseEventContext()
    page.context = context
    popup = detail_page if use_popup else None
    coordinator = AssistedCoordinator(
        result_page=popup,
        responses_to_emit=[ObservedResponse(
            url="https://t.bilibili.com/123456",
            status=status,
        )],
    )
    screenshots = Screenshots()

    with pytest.raises(CollectionStopped, match=f"http-{status}"):
        _run(collect_creator(
            CollectionRequest(
                platform="bilibili",
                count=1,
                uid="synthetic-user",
                complete=True,
                browser_assist="off",
            ),
            ProductionBrowser(
                page,
                detail_open=coordinator,
                screenshots=screenshots,
            ),
        ))

    active_detail_page = popup or page
    assert coordinator.clicks == ["123456"]
    assert coordinator.retry_policies == [False]
    assert not any(
        "MEDIA_MISSHER_DYNAMIC_DETAIL" in script
        for script in active_detail_page.evaluations
    )
    assert screenshots.captures == []
    assert context.listeners == []
    assert target.disposed is True
    assert coordinator.released == ([popup] if popup is not None else [])


def test_dynamic_detail_response_observer_rejects_unrelated_traffic_and_cleans_up() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    target = DynamicElement(dynamic_id="123456")
    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[target],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": 30,
            "comments": 40,
            "shares": 50,
            "collected": 6,
        }],
    )
    context = ResponseEventContext()
    page.context = context
    coordinator = AssistedCoordinator(responses_to_emit=[
        ObservedResponse(url="https://t.bilibili.com/other", status=403),
        ObservedResponse(
            url="https://t.bilibili.com/123456",
            status=429,
            request=ObservedRequest(resource_type="xhr"),
        ),
        ObservedResponse(url="https://t.bilibili.com/123456", status=200),
    ])

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            complete=True,
            browser_assist="off",
        ),
        ProductionBrowser(page, detail_open=coordinator),
    ))[0]

    assert record["collected"] == 6
    assert record["complete"] is True
    assert context.listeners == []
    assert target.disposed is True


def test_dynamic_detail_response_observer_cleans_up_when_click_fails() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    target = DynamicElement(dynamic_id="123456")
    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[target],
    )
    context = ResponseEventContext()
    page.context = context
    coordinator = AssistedCoordinator(
        click_error=PreconditionError("synthetic click failure")
    )

    with pytest.raises(PreconditionError, match="synthetic click failure"):
        _run(collect_creator(
            CollectionRequest(
                platform="bilibili",
                count=1,
                uid="synthetic-user",
                complete=True,
                browser_assist="off",
            ),
            ProductionBrowser(page, detail_open=coordinator),
        ))

    assert coordinator.clicks == ["123456"]
    assert context.listeners == []
    assert target.disposed is True


def test_dynamic_detail_response_observer_fails_closed_without_listener_removal() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": 3,
            "comments": 0,
            "shares": 2,
            "collected": 1,
        }],
    )
    context = UnremovableResponseEventContext()
    page.context = context
    coordinator = AssistedCoordinator()

    with pytest.raises(PreconditionError, match="response observer"):
        _run(collect_creator(
            CollectionRequest(
                platform="bilibili",
                count=1,
                uid="synthetic-user",
                complete=True,
                browser_assist="off",
            ),
            ProductionBrowser(page, detail_open=coordinator),
        ))

    assert coordinator.clicks == []
    assert context.listeners == []


@pytest.mark.asyncio
async def test_dynamic_detail_reader_requires_exact_https_url_and_same_id() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import _read_dynamic_detail

    detail = {
        "dynamic_id": "123456",
        "risk_text": "",
        "liked": 3,
        "comments": 0,
        "shares": 2,
        "collected": 1,
    }
    page = CapturePage(
        url="https://t.bilibili.com/123456",
        dynamic_details=[detail],
    )
    assert await _read_dynamic_detail(page, "123456") == detail

    wrong_url = CapturePage(
        url="https://t.bilibili.com/other",
        dynamic_details=[detail],
    )
    with pytest.raises(PreconditionError, match="detail identifier mismatch"):
        await _read_dynamic_detail(wrong_url, "123456")

    cross_id = CapturePage(
        url="https://t.bilibili.com/123456",
        dynamic_details=[{**detail, "dynamic_id": "other"}],
    )
    with pytest.raises(PreconditionError, match="detail identifier mismatch"):
        await _read_dynamic_detail(cross_id, "123456")


def test_assist_opens_unknown_dynamic_and_merges_only_same_id_numeric_metrics() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": None,
            "comments": 7,
            "shares": 8,
            "collected": 9,
        }],
    )
    coordinator = AssistedCoordinator()
    browser = ProductionBrowser(page, detail_open=coordinator)

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            browser_assist="browserskill",
        ),
        browser,
    ))[0]

    assert coordinator.clicks == ["123456"]
    assert coordinator.retry_policies == [True]
    assert record["detail_attempted"] is True
    assert record["detail_completed"] is True
    assert record["liked"] == 3
    assert (record["comments"], record["shares"], record["collected"]) == (0, 2, 9)
    assert record["complete"] is True
    assert record["missing_fields"] == []


def test_assist_does_not_open_dynamic_when_all_engagement_values_are_known_zero() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    item = _item("123456")
    item["modules"]["module_stat"] = {
        "comment": {"count": 0},
        "forward": {"count": 0},
        "like": {"count": 0},
        "favorite": {"count": 0},
    }
    coordinator = AssistedCoordinator()
    page = CapturePage(
        responses=[_feed(item, has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
    )

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            browser_assist="browserskill",
        ),
        ProductionBrowser(page, detail_open=coordinator),
    ))[0]

    assert coordinator.clicks == []
    assert record["detail_attempted"] is False
    assert record["complete"] is False


def test_dynamic_open_remains_incomplete_when_detail_metrics_are_unknown() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": None,
            "comments": None,
            "shares": None,
            "collected": None,
        }],
    )
    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            browser_assist="browserskill",
        ),
        ProductionBrowser(page, detail_open=AssistedCoordinator()),
    ))[0]

    assert record["detail_attempted"] is True
    assert record["detail_completed"] is False
    assert record["complete"] is False
    assert record["missing_fields"] == ["collected"]


@pytest.mark.parametrize("mode", ("opened", "all"))
def test_dynamic_screenshot_modes_capture_only_an_opened_exact_dynamic(mode: str) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    screenshots = Screenshots()
    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": 3,
            "comments": 0,
            "shares": 2,
            "collected": 1,
        }],
    )
    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            browser_assist="browserskill" if mode == "opened" else "off",
            screenshot_mode=mode,
        ),
        ProductionBrowser(
            page,
            detail_open=AssistedCoordinator(),
            screenshots=screenshots,
        ),
    ))[0]

    assert screenshots.captures == [("bilibili", "123456", mode)]
    assert record["screenshot_status"] == "complete"
    assert record["screenshot_path"] == "screenshots/bilibili-123456.png"


def test_opened_screenshot_mode_does_not_cause_a_dynamic_open() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    coordinator = AssistedCoordinator()
    screenshots = Screenshots()
    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
    )

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            screenshot_mode="opened",
        ),
        ProductionBrowser(page, detail_open=coordinator, screenshots=screenshots),
    ))[0]

    assert coordinator.clicks == []
    assert screenshots.captures == []
    assert "screenshot_status" not in record


def test_dynamic_risk_stops_before_screenshot() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        CollectionStopped,
        collect_creator,
    )

    screenshots = Screenshots()
    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "challenge-selector",
            "liked": None,
            "comments": None,
            "shares": None,
            "collected": None,
        }],
    )

    with pytest.raises(CollectionStopped, match="challenge"):
        _run(collect_creator(
            CollectionRequest(
                platform="bilibili",
                count=1,
                uid="synthetic-user",
                screenshot_mode="all",
            ),
            ProductionBrowser(
                page,
                detail_open=AssistedCoordinator(),
                screenshots=screenshots,
            ),
        ))
    assert screenshots.captures == []


def test_dynamic_screenshot_failure_preserves_verified_metrics() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator
    from runtime.media_missher_runtime.screenshots import ScreenshotError

    screenshots = Screenshots(ScreenshotError("capture-failed"))
    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": 3,
            "comments": 4,
            "shares": 5,
            "collected": 6,
        }],
    )

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            screenshot_mode="all",
        ),
        ProductionBrowser(
            page,
            detail_open=AssistedCoordinator(),
            screenshots=screenshots,
        ),
    ))[0]

    assert (record["liked"], record["comments"], record["shares"], record["collected"]) == (3, 0, 2, 6)
    assert record["screenshot_status"] == "failed"
    assert record["screenshot_error_code"] == "capture-failed"


@pytest.mark.parametrize(
    ("final_url", "observed_bvid"),
    (
        ("https://passport.bilibili.com/login", "BVscreen1"),
        ("https://www.bilibili.com/video/BVscreen1", "BVwrong1"),
    ),
)
def test_video_screenshot_requires_exact_final_url_and_same_observed_bvid(
    final_url: str,
    observed_bvid: str,
) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    @dataclass
    class FinalUrlPage(CapturePage):
        async def goto(self, url: str, **kwargs: Any) -> None:
            await super().goto(url, **kwargs)
            if "/video/" in url:
                self.url = final_url

    screenshots = Screenshots()
    page = FinalUrlPage(
        responses=[_feed(_item("first", bvid="BVscreen1"), has_more=False)],
        details=[{
            "risk_text": "",
            "videoData": {"bvid": observed_bvid},
        }],
    )

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            screenshot_mode="all",
        ),
        ProductionBrowser(page, screenshots=screenshots),
    ))[0]

    assert screenshots.captures == []
    assert record["screenshot_status"] == "failed"
    assert record["screenshot_error_code"] == "capture-failed"


def test_video_screenshot_captures_only_after_exact_page_verification() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    screenshots = Screenshots()
    page = CapturePage(
        responses=[_feed(_item("first", bvid="BVscreen1"), has_more=False)],
        details=[{
            "risk_text": "",
            "videoData": {"bvid": "BVscreen1"},
        }],
    )

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            screenshot_mode="all",
        ),
        ProductionBrowser(page, screenshots=screenshots),
    ))[0]

    assert screenshots.captures == [("bilibili", "BVscreen1", "all")]
    assert record["screenshot_status"] == "complete"
