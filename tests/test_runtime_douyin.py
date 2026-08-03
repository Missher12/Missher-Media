from __future__ import annotations

import json
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
    payload: object
    status: int = 200
    url: str = "https://www.douyin.com/aweme/v1/web/aweme/post/"
    json_error: Exception | None = None
    json_calls: int = 0

    async def json(self) -> object:
        self.json_calls += 1
        if self.json_error:
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
    url: str = "https://www.douyin.com/"
    responses: list[Response] = field(default_factory=list)
    gotos: list[str] = field(default_factory=list)
    evaluations: list[str] = field(default_factory=list)
    waits: list[list[str]] = field(default_factory=list)
    challenge: str = ""

    def expect_response(self, predicate: Any, **kwargs: Any) -> ResponseWaiter:
        response = self.responses.pop(0)
        assert predicate(response)
        assert kwargs["timeout"] == 10_000
        return ResponseWaiter(response)

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.gotos.append(url)

    async def evaluate(self, script: str) -> Any:
        self.evaluations.append(script)
        if "window.scrollTo" in script:
            return None
        return {"risk_text": self.challenge}

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
        assert platform == "douyin"
        return self.page

    async def navigate(self, page: CapturePage, url: str, *, allowed_hosts: tuple[str, ...]) -> object:
        self.navigations.append((url, allowed_hosts))
        if not self.allow_navigation:
            raise PreconditionError("navigation")
        await page.goto(url)
        return self.navigation_result


def _aweme(identifier: str, *, title: object = "Synthetic title", images: object = None, duration: object = 3210) -> dict[str, Any]:
    result: dict[str, Any] = {
        "aweme_id": identifier,
        "desc": title,
        "create_time": 1_700_000_000,
        "duration": duration,
        "author": {"nickname": "Synthetic author", "sec_uid": "must-not-leak"},
        "statistics": {"digg_count": 0, "comment_count": 2, "share_count": 3, "collect_count": None, "play_count": 4, "forward_count": 5},
        "video": {"duration": duration, "play_addr": {"url_list": ["https://secret.example/video"]}},
        "authentication_token": "must-not-leak",
    }
    if images is not None:
        result["images"] = images
    return result


def _creator(*items: dict[str, Any], has_more: bool = False, cursor: int = 0) -> Response:
    return Response({"status_code": 0, "aweme_list": list(items), "has_more": has_more, "max_cursor": cursor})


def _search(*items: dict[str, Any], has_more: bool = False, cursor: int = 0) -> Response:
    return Response({"status_code": 0, "data": [{"aweme_info": item} for item in items], "has_more": has_more, "cursor": cursor}, url="https://www.douyin.com/aweme/v1/web/general/search/single/")


def test_creator_captures_browser_generated_responses_and_emits_safe_compatibility_schema() -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator

    page = CapturePage(responses=[_creator(_aweme("one"), _aweme("two", images=[{}]), has_more=False)])
    browser = ProductionBrowser(page)
    records = _run(collect_creator(CollectionRequest(platform="douyin", count=2, uid="creator id"), browser))

    assert [record["aweme_id"] for record in records] == ["one", "two"]
    assert page.gotos == ["https://www.douyin.com/user/creator%20id"]
    assert browser.navigations == [("https://www.douyin.com/user/creator%20id", ("www.douyin.com",))]
    assert records[0]["link"] == records[0]["url"] == "https://www.douyin.com/video/one"
    assert records[0]["id"] == records[0]["native_id"] == "one"
    assert records[0]["author"] == "Synthetic author"
    assert records[0]["comments"] == 2 and records[0]["liked"] == 0 and records[0]["collected"] is None
    assert records[0]["plays"] == 4 and records[0]["duration_ms"] == 3210
    assert records[1]["type"] == "images"
    assert records[0]["published_at"] == records[0]["date"]
    assert records[0]["observed_at"].endswith("+00:00")
    assert "page_json" not in "\n".join(page.evaluations)
    rendered = json.dumps(records)
    for secret in ("sec_uid", "authentication_token", "play_addr", "url_list", "must-not-leak"):
        assert secret not in rendered


def test_creator_deduplicates_before_truncation_and_stops_when_cursor_does_not_advance() -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator

    page = CapturePage(responses=[_creator(_aweme("one"), _aweme("two"), has_more=True, cursor=7), _creator(_aweme("two"), _aweme("three"), has_more=True, cursor=7)])
    records = _run(collect_creator(CollectionRequest(platform="douyin", count=3, page_cap=4, uid="creator"), ProductionBrowser(page)))

    assert [record["aweme_id"] for record in records] == ["one", "two", "three"]
    assert len(page.responses) == 0
    assert sum("window.scrollTo" in script for script in page.evaluations) == 1


def test_creator_exact_count_avoids_an_extra_scroll_and_count_zero_is_page_capped() -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator

    exact = CapturePage(responses=[_creator(_aweme("one"), has_more=True, cursor=1), _creator(_aweme("never"), has_more=False)])
    assert [record["aweme_id"] for record in _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(exact)))] == ["one"]
    assert len(exact.responses) == 1

    unbounded = CapturePage(responses=[_creator(_aweme("one"), has_more=True, cursor=1), _creator(_aweme("two"), has_more=True, cursor=2), _creator(_aweme("never"), has_more=False)])
    assert [record["aweme_id"] for record in _run(collect_creator(CollectionRequest(platform="douyin", count=0, page_cap=2, uid="creator"), ProductionBrowser(unbounded)))] == ["one", "two"]
    assert len(unbounded.responses) == 1


def test_search_navigates_to_exact_host_and_uses_single_or_stream_responses() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    stream = _search(_aweme("two"), has_more=False)
    stream.url = "https://www.douyin.com/aweme/v1/web/general/search/stream/"
    page = CapturePage(responses=[_search(_aweme("one"), has_more=True, cursor=1), stream])
    records = _run(search(CollectionRequest(platform="douyin", count=2, keyword="two words"), ProductionBrowser(page)))

    assert [record["native_id"] for record in records] == ["one", "two"]
    assert records[0]["search_keyword"] == "two words"
    assert records[0]["cursor"] == 1 and records[1]["cursor"] == 0
    assert page.gotos == ["https://www.douyin.com/search/two%20words"]
    assert page.evaluations.count("() => window.scrollTo(0, document.documentElement.scrollHeight)") == 1


def test_search_ignores_malformed_items_and_stops_on_duplicate_only_or_timeout() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    malformed = Response({"status_code": 0, "data": [None, {}, {"aweme_info": _aweme("one")}], "has_more": True, "cursor": 1}, url="https://www.douyin.com/aweme/v1/web/general/search/single/")
    duplicate = _search(_aweme("one"), has_more=True, cursor=2)
    page = CapturePage(responses=[malformed, duplicate, _search(_aweme("never"), has_more=False)])
    assert [record["native_id"] for record in _run(search(CollectionRequest(platform="douyin", count=0, page_cap=4, keyword="term"), ProductionBrowser(page)))] == ["one"]
    assert len(page.responses) == 1


def test_scroll_response_timeout_is_bounded_and_nonrisk_failures_are_controlled() -> None:
    from runtime.media_missher_runtime.platforms.douyin import SourceResponseError, collect_creator

    @dataclass
    class TimeoutWaiter:
        async def __aenter__(self) -> "TimeoutWaiter":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        @property
        def value(self) -> Coroutine[Any, Any, Response]:
            async def result() -> Response:
                raise TimeoutError("synthetic timeout")

            return result()

    class TimeoutPage(CapturePage):
        def expect_response(self, predicate: Any, **kwargs: Any) -> ResponseWaiter | TimeoutWaiter:
            if self.responses:
                return super().expect_response(predicate, **kwargs)
            return TimeoutWaiter()

    timeout_page = TimeoutPage(responses=[_creator(_aweme("one"), has_more=True, cursor=1)])
    assert [record["aweme_id"] for record in _run(collect_creator(CollectionRequest(platform="douyin", count=0, page_cap=3, uid="creator"), ProductionBrowser(timeout_page)))] == ["one"]
    assert sum("window.scrollTo" in script for script in timeout_page.evaluations) == 1

    server_error = Response({}, status=500)
    with pytest.raises(SourceResponseError, match="http-500"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(CapturePage(responses=[server_error]))))
    invalid_json = Response(None, json_error=ValueError("synthetic decode"))
    with pytest.raises(SourceResponseError, match="JSON decode"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(CapturePage(responses=[invalid_json]))))


def test_navigation_disabled_requires_exact_preopened_target_but_can_consume_a_future_response() -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator, search

    creator_page = CapturePage(url="https://www.douyin.com/user/creator", responses=[_creator(_aweme("open"), has_more=False)])
    creator_records = _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(creator_page, allow_navigation=False)))
    assert creator_records[0]["aweme_id"] == "open"
    assert creator_page.gotos == []
    assert creator_page.waits == []

    wrong_page = CapturePage(url="https://www.douyin.com/search/term", responses=[_creator(_aweme("never"))])
    with pytest.raises(PreconditionError, match="matching Douyin creator"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(wrong_page, allow_navigation=False)))
    with pytest.raises(PreconditionError, match="matching Douyin search"):
        _run(search(CollectionRequest(platform="douyin", count=1, keyword="term"), ProductionBrowser(CapturePage(url="https://www.douyin.com/user/creator"), allow_navigation=False)))


@pytest.mark.parametrize("status", (403, 429))
def test_risk_http_status_is_classified_before_json_or_scroll(status: int) -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    response = Response(None, status=status, json_error=AssertionError("JSON must not be read"))
    page = CapturePage(responses=[response])
    with pytest.raises(CollectionStopped, match=f"http-{status}"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=2, uid="creator"), ProductionBrowser(page)))
    assert response.json_calls == 0
    assert not any("window.scrollTo" in script for script in page.evaluations)


@pytest.mark.parametrize("payload", ({"status_code": 461, "aweme_list": []}, {"code": 471, "aweme_list": []}, {"status_code": 999, "aweme_list": []}, {"status_code": 0, "douyin_ai_search_info": {"is_hit_high_risk": True}, "data": []}))
def test_payload_risk_stops_immediately(payload: object) -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    page = CapturePage(responses=[Response(payload)])
    with pytest.raises(CollectionStopped):
        _run(collect_creator(CollectionRequest(platform="douyin", count=2, uid="creator"), ProductionBrowser(page)))
    assert not any("window.scrollTo" in script for script in page.evaluations)


def test_challenge_page_stops_but_normal_english_risk_in_title_does_not() -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    challenge = CapturePage(responses=[_creator(_aweme("never"))], challenge="challenge-selector")
    with pytest.raises(CollectionStopped, match="challenge"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(challenge)))

    normal = CapturePage(responses=[_creator(_aweme("risk-title", title="Risk analysis"), has_more=False)])
    assert _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(normal)))[0]["title"] == "Risk analysis"


def test_parsers_preserve_zero_null_dates_duration_and_media_type() -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    video = parse_aweme_item(_aweme("zero", duration=0), observed_at="2026-01-01T00:00:00+00:00")
    image = parse_aweme_item(_aweme("image", images=[{}]), observed_at="2026-01-01T00:00:00+00:00")
    unknown = parse_aweme_item({"aweme_id": "unknown", "desc": None, "create_time": None, "statistics": {}}, observed_at="2026-01-01T00:00:00+00:00")

    assert video["duration_ms"] == 0 and video["liked"] == 0 and video["collected"] is None
    assert video["date"] == "2023-11-14T22:13:20+00:00"
    assert image["type"] == "images"
    assert unknown["title"] is None and unknown["date"] is None and unknown["duration_ms"] is None


def test_parser_uses_observed_media_kind_and_nested_video_duration() -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    item = _aweme("media-kind", duration=987)
    item.pop("duration")
    item["media"] = {"kind": "images"}
    record = parse_aweme_item(item, observed_at="2026-01-01T00:00:00+00:00")

    assert record["type"] == "images"
    assert record["duration_ms"] == 987


def test_complete_search_is_unsupported_and_remote_browser_is_never_closed() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    browser = ProductionBrowser(CapturePage())
    with pytest.raises(ValueError, match="complete search"):
        _run(search(CollectionRequest(platform="douyin", count=1, keyword="term", complete=True), browser))
    assert not hasattr(browser, "closed")
