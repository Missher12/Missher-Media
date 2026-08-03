from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Coroutine

import pytest

from runtime.media_missher_runtime.browser import PreconditionError
from runtime.media_missher_runtime.models import CollectionRequest
from runtime.media_missher_runtime.platforms.douyin import PlaywrightTimeoutError


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
class LazyResponseWaiter:
    page: "ChallengeTimingPage"
    predicate: Any
    exited: bool = False
    cancelled: bool = False

    async def __aenter__(self) -> "LazyResponseWaiter":
        self.page.listener_active = True
        return self

    async def __aexit__(self, exc_type: object, *args: Any) -> None:
        self.exited = True
        self.cancelled = exc_type is not None
        self.page.listener_active = False

    @property
    def value(self) -> Coroutine[Any, Any, Response]:
        async def result() -> Response:
            if not self.page.responses:
                raise TimeoutError("synthetic response timeout")
            response = self.page.responses.pop(0)
            assert self.predicate(response)
            return response

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
class ChallengeTimingPage(CapturePage):
    challenge_on_navigation: bool = False
    challenge_on_scroll: bool = False
    listener_active: bool = False
    listener_waiters: list[LazyResponseWaiter] = field(default_factory=list)

    def expect_response(self, predicate: Any, **kwargs: Any) -> LazyResponseWaiter:
        assert kwargs["timeout"] == 10_000
        waiter = LazyResponseWaiter(self, predicate)
        self.listener_waiters.append(waiter)
        return waiter

    async def goto(self, url: str, **kwargs: Any) -> None:
        await super().goto(url, **kwargs)
        if self.challenge_on_navigation:
            self.challenge = "challenge-selector"

    async def evaluate(self, script: str) -> Any:
        result = await super().evaluate(script)
        if "window.scrollTo" in script and self.challenge_on_scroll:
            self.challenge = "challenge-selector"
        return result


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


def test_aweme_parser_restores_safe_public_avatar_and_cover_without_signed_parameters() -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    item = _aweme("safe-media")
    item["author"]["avatar_thumb"] = {
        "url_list": [
            "https://cdn.example.invalid/avatar.jpeg?width=96&token=must-not-leak&expires=123#fragment"
        ]
    }
    item["video"]["cover"] = {
        "url_list": [
            "https://cdn.example.invalid/cover.jpeg?height=720&signature=must-not-leak"
        ]
    }

    record = parse_aweme_item(item, observed_at="2026-01-01T00:00:00+00:00")

    assert record["author_avatar"] == "https://cdn.example.invalid/avatar.jpeg?width=96"
    assert record["cover"] == "https://cdn.example.invalid/cover.jpeg?height=720"
    rendered = json.dumps(record)
    for forbidden in ("token", "expires", "signature", "must-not-leak", "#fragment"):
        assert forbidden not in rendered


def test_aweme_parser_rejects_malformed_public_media_urls() -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    item = _aweme("malformed-media")
    item["author"]["avatar_thumb"] = {"url_list": ["https://[invalid"]}
    item["video"]["cover"] = {"url_list": ["javascript:alert(1)"]}

    record = parse_aweme_item(item)

    assert record["author_avatar"] is None
    assert record["cover"] is None


def test_aweme_parser_accepts_realistic_sign_cdn_and_tries_safe_media_fallbacks() -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    item = _aweme("realistic-media")
    item["author"]["avatar_thumb"] = {"url_list": ["javascript:alert(1)"]}
    item["author"]["avatar_medium"] = {
        "url_list": ["https://p3-sign.douyinpic.com/design-avatar.jpeg?width=96"]
    }
    item["video"]["cover"] = {"url_list": ["https://[invalid"]}
    item["video"]["dynamic_cover"] = {
        "url_list": ["https://p3-sign.douyinpic.com/design-cover.jpeg?height=720"]
    }

    record = parse_aweme_item(item)

    assert record["author_avatar"] == "https://p3-sign.douyinpic.com/design-avatar.jpeg?width=96"
    assert record["cover"] == "https://p3-sign.douyinpic.com/design-cover.jpeg?height=720"


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


@pytest.mark.parametrize(("source", "cursor"), (("creator", None), ("creator", ""), ("search", None), ("search", "")))
def test_empty_or_missing_cursor_exhausts_before_scrolling(source: str, cursor: object) -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator, search

    if source == "creator":
        payload = {"status_code": 0, "aweme_list": [_aweme("one")], "has_more": True, "max_cursor": cursor}
        page = CapturePage(responses=[Response(payload), _creator(_aweme("never"), has_more=False)])
        records = _run(collect_creator(CollectionRequest(platform="douyin", count=0, page_cap=2, uid="creator"), ProductionBrowser(page)))
    else:
        payload = {"status_code": 0, "data": [{"aweme_info": _aweme("one")}], "has_more": True, "cursor": cursor}
        page = CapturePage(responses=[Response(payload, url="https://www.douyin.com/aweme/v1/web/general/search/single/"), _search(_aweme("never"), has_more=False)])
        records = _run(search(CollectionRequest(platform="douyin", count=0, page_cap=2, keyword="term"), ProductionBrowser(page)))

    assert [record["native_id"] for record in records] == ["one"]
    assert not any("window.scrollTo" in script for script in page.evaluations)
    assert len(page.responses) == 1


def test_search_uses_response_offset_when_cursor_is_absent() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    url = "https://www.douyin.com/aweme/v1/web/general/search/single/"
    first = Response(
        {
            "status_code": 0,
            "data": [{"aweme_info": _aweme("one")}],
            "has_more": 1,
            "offset": 15,
        },
        url=url,
    )
    second = Response(
        {
            "status_code": 0,
            "data": [{"aweme_info": _aweme("two")}],
            "has_more": 0,
            "offset": 30,
        },
        url=url,
    )
    page = CapturePage(responses=[first, second])

    records = _run(
        search(
            CollectionRequest(platform="douyin", count=0, page_cap=3, keyword="term"),
            ProductionBrowser(page),
        )
    )

    assert [record["native_id"] for record in records] == ["one", "two"]
    assert [record["cursor"] for record in records] == [15, 30]
    assert sum("window.scrollTo" in script for script in page.evaluations) == 1


def test_search_stops_after_a_repeated_response_offset() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    url = "https://www.douyin.com/aweme/v1/web/general/search/single/"
    responses = [
        Response(
            {
                "status_code": 0,
                "data": [{"aweme_info": _aweme("one")}],
                "has_more": 1,
                "offset": 15,
            },
            url=url,
        ),
        Response(
            {
                "status_code": 0,
                "data": [{"aweme_info": _aweme("two")}],
                "has_more": 1,
                "offset": 15,
            },
            url=url,
        ),
        Response(
            {
                "status_code": 0,
                "data": [{"aweme_info": _aweme("never")}],
                "has_more": 0,
                "offset": 30,
            },
            url=url,
        ),
    ]
    page = CapturePage(responses=responses)

    records = _run(
        search(
            CollectionRequest(platform="douyin", count=0, page_cap=4, keyword="term"),
            ProductionBrowser(page),
        )
    )

    assert [record["native_id"] for record in records] == ["one", "two"]
    assert sum("window.scrollTo" in script for script in page.evaluations) == 1
    assert len(page.responses) == 1


def test_search_does_not_guess_a_cursor_when_cursor_and_offset_are_absent() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    url = "https://www.douyin.com/aweme/v1/web/general/search/single/"
    first = Response(
        {
            "status_code": 0,
            "data": [{"aweme_info": _aweme("one")}],
            "has_more": 1,
        },
        url=url,
    )
    page = CapturePage(responses=[first, _search(_aweme("never"), has_more=False)])

    records = _run(
        search(
            CollectionRequest(platform="douyin", count=0, page_cap=3, keyword="term"),
            ProductionBrowser(page),
        )
    )

    assert [record["native_id"] for record in records] == ["one"]
    assert records[0]["cursor"] is None
    assert not any("window.scrollTo" in script for script in page.evaluations)
    assert len(page.responses) == 1


def test_search_prefers_an_explicit_cursor_over_response_offset() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    url = "https://www.douyin.com/aweme/v1/web/general/search/single/"
    responses = [
        Response(
            {
                "status_code": 0,
                "data": [{"aweme_info": _aweme("one")}],
                "has_more": 1,
                "cursor": 7,
                "offset": 15,
            },
            url=url,
        ),
        Response(
            {
                "status_code": 0,
                "data": [{"aweme_info": _aweme("two")}],
                "has_more": 1,
                "cursor": 7,
                "offset": 30,
            },
            url=url,
        ),
        Response(
            {
                "status_code": 0,
                "data": [{"aweme_info": _aweme("never")}],
                "has_more": 0,
                "cursor": 8,
                "offset": 45,
            },
            url=url,
        ),
    ]
    page = CapturePage(responses=responses)

    records = _run(
        search(
            CollectionRequest(platform="douyin", count=0, page_cap=4, keyword="term"),
            ProductionBrowser(page),
        )
    )

    assert [record["native_id"] for record in records] == ["one", "two"]
    assert [record["cursor"] for record in records] == [7, 7]
    assert len(page.responses) == 1


@pytest.mark.parametrize("source", ("creator", "search"))
def test_integer_has_more_one_collects_a_second_page_and_zero_does_not_scroll(source: str) -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator, search

    if source == "creator":
        first = Response({"status_code": 0, "aweme_list": [_aweme("one")], "has_more": 1, "max_cursor": 1})
        second = Response({"status_code": 0, "aweme_list": [_aweme("two")], "has_more": 0, "max_cursor": 2})
        page = CapturePage(responses=[first, second])
        records = _run(collect_creator(CollectionRequest(platform="douyin", count=0, page_cap=3, uid="creator"), ProductionBrowser(page)))
        exhausted = CapturePage(responses=[Response({"status_code": 0, "aweme_list": [_aweme("one")], "has_more": 0, "max_cursor": 1}), _creator(_aweme("never"))])
        exhausted_records = _run(collect_creator(CollectionRequest(platform="douyin", count=0, page_cap=3, uid="creator"), ProductionBrowser(exhausted)))
    else:
        url = "https://www.douyin.com/aweme/v1/web/general/search/single/"
        first = Response({"status_code": 0, "data": [{"aweme_info": _aweme("one")}], "has_more": 1, "cursor": 1}, url=url)
        second = Response({"status_code": 0, "data": [{"aweme_info": _aweme("two")}], "has_more": 0, "cursor": 2}, url=url)
        page = CapturePage(responses=[first, second])
        records = _run(search(CollectionRequest(platform="douyin", count=0, page_cap=3, keyword="term"), ProductionBrowser(page)))
        exhausted = CapturePage(responses=[Response({"status_code": 0, "data": [{"aweme_info": _aweme("one")}], "has_more": 0, "cursor": 1}, url=url), _search(_aweme("never"))])
        exhausted_records = _run(search(CollectionRequest(platform="douyin", count=0, page_cap=3, keyword="term"), ProductionBrowser(exhausted)))

    assert [record["native_id"] for record in records] == ["one", "two"]
    assert sum("window.scrollTo" in script for script in page.evaluations) == 1
    assert [record["native_id"] for record in exhausted_records] == ["one"]
    assert not any("window.scrollTo" in script for script in exhausted.evaluations)
    assert len(exhausted.responses) == 1


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


def test_search_unwraps_aweme_info_mix_and_direct_items() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    payload = {
        "status_code": 0,
        "data": [
            {"aweme_info": _aweme("wrapped"), "token": "must-not-leak"},
            {
                "aweme_mix_info": {
                    "mix_items": [_aweme("mixed")],
                    "token": "must-not-leak",
                }
            },
            _aweme("direct"),
        ],
        "has_more": 0,
        "cursor": 0,
    }
    page = CapturePage(
        responses=[
            Response(
                payload,
                url="https://www.douyin.com/aweme/v1/web/general/search/single/",
            )
        ]
    )

    records = _run(
        search(
            CollectionRequest(platform="douyin", count=3, keyword="term"),
            ProductionBrowser(page),
        )
    )

    assert [record["native_id"] for record in records] == [
        "wrapped",
        "mixed",
        "direct",
    ]
    rendered = json.dumps(records)
    assert "must-not-leak" not in rendered
    assert "authentication_token" not in rendered


def test_search_ignores_malformed_items_and_stops_on_duplicate_only_or_timeout() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    malformed = Response(
        {
            "status_code": 0,
            "data": [
                None,
                {},
                {"aweme_mix_info": {"mix_items": []}},
                {
                    "aweme_mix_info": {
                        "mix_items": ["invalid", _aweme("ignored-second")]
                    }
                },
                {"aweme_id": "bad/id"},
                {"aweme_info": _aweme("one")},
            ],
            "has_more": True,
            "cursor": 1,
        },
        url="https://www.douyin.com/aweme/v1/web/general/search/single/",
    )
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
                raise PlaywrightTimeoutError("synthetic timeout")

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


@pytest.mark.parametrize(
    ("uid", "page_url"),
    (
        ("中文 id", "https://www.douyin.com/user/%e4%b8%ad%e6%96%87%20id?uid=%E4%B8%AD%E6%96%87+id&utm_source=test"),
        (None, "https://www.douyin.com/search/%e4%b8%ad%e6%96%87%20term?keyword=%E4%B8%AD%E6%96%87+term&utm_source=test"),
    ),
)
def test_navigation_disabled_normalizes_encoded_target_and_allows_matching_content_query(uid: str | None, page_url: str) -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator, search

    if uid is not None:
        page = CapturePage(url=page_url, responses=[_creator(_aweme("open"))])
        records = _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid=uid), ProductionBrowser(page, allow_navigation=False)))
    else:
        page = CapturePage(url=page_url, responses=[_search(_aweme("open"))])
        records = _run(search(CollectionRequest(platform="douyin", count=1, keyword="中文 term"), ProductionBrowser(page, allow_navigation=False)))

    assert [record["native_id"] for record in records] == ["open"]


@pytest.mark.parametrize(
    ("uid", "page_url"),
    (
        ("creator", "https://www.douyin.com/user/creator?uid=other&utm_source=test"),
        (None, "https://www.douyin.com/search/term?keyword=other&utm_source=test"),
    ),
)
def test_navigation_disabled_rejects_conflicting_content_query(uid: str | None, page_url: str) -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator, search

    page = CapturePage(url=page_url, responses=[_creator(_aweme("never")) if uid is not None else _search(_aweme("never"))])
    with pytest.raises(PreconditionError, match="matching Douyin"):
        if uid is not None:
            _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid=uid), ProductionBrowser(page, allow_navigation=False)))
        else:
            _run(search(CollectionRequest(platform="douyin", count=1, keyword="term"), ProductionBrowser(page, allow_navigation=False)))
    assert len(page.responses) == 1


def test_existing_challenge_is_checked_before_installing_initial_listener() -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    page = ChallengeTimingPage(challenge="challenge-selector", responses=[_creator(_aweme("never"))])
    with pytest.raises(CollectionStopped, match="challenge"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(page)))

    assert page.gotos == []
    assert page.listener_waiters == []
    assert len(page.responses) == 1


def test_navigation_challenge_cancels_listener_without_consuming_response() -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    page = ChallengeTimingPage(challenge_on_navigation=True, responses=[_creator(_aweme("never"))])
    with pytest.raises(CollectionStopped, match="challenge"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(page)))

    assert page.gotos == ["https://www.douyin.com/user/creator"]
    assert len(page.responses) == 1
    assert page.listener_active is False
    assert len(page.listener_waiters) == 1
    assert page.listener_waiters[0].exited is True
    assert page.listener_waiters[0].cancelled is True


def test_scroll_challenge_cancels_listener_without_consuming_next_response_or_scrolling_again() -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    page = ChallengeTimingPage(
        challenge_on_scroll=True,
        responses=[_creator(_aweme("one"), has_more=True, cursor=1), _creator(_aweme("never"), has_more=False)],
    )
    with pytest.raises(CollectionStopped, match="challenge"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=0, page_cap=3, uid="creator"), ProductionBrowser(page)))

    assert len(page.responses) == 1
    assert sum("window.scrollTo" in script for script in page.evaluations) == 1
    assert page.listener_active is False
    assert len(page.listener_waiters) == 2
    assert page.listener_waiters[-1].exited is True
    assert page.listener_waiters[-1].cancelled is True


def test_passive_response_timeout_exits_listener_without_leaking_it() -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator

    page = ChallengeTimingPage(url="https://www.douyin.com/user/creator")
    with pytest.raises(TimeoutError, match="response timeout"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(page, allow_navigation=False)))

    assert page.listener_active is False
    assert len(page.listener_waiters) == 1
    assert page.listener_waiters[0].exited is True


@pytest.mark.parametrize("status", (403, 429))
def test_risk_http_status_is_classified_before_json_or_scroll(status: int) -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    response = Response(None, status=status, json_error=AssertionError("JSON must not be read"))
    page = CapturePage(responses=[response])
    with pytest.raises(CollectionStopped, match=f"http-{status}"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=2, uid="creator"), ProductionBrowser(page)))
    assert response.json_calls == 0
    assert not any("window.scrollTo" in script for script in page.evaluations)


@pytest.mark.parametrize("payload", ({"status_code": 461, "aweme_list": []}, {"code": 471, "aweme_list": []}, {"status_code": 999, "aweme_list": []}, {"status_code": 0, "douyin_ai_search_info": {"is_hit_high_risk": True}, "data": []}, {"status_code": 5, "douyin_ai_search_info": {"is_hit_high_risk": True}, "data": []}))
def test_payload_risk_stops_immediately(payload: object) -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    page = CapturePage(responses=[Response(payload)])
    with pytest.raises(CollectionStopped):
        _run(collect_creator(CollectionRequest(platform="douyin", count=2, uid="creator"), ProductionBrowser(page)))
    assert not any("window.scrollTo" in script for script in page.evaluations)


@pytest.mark.parametrize(
    "payload",
    (
        {"status_code": "461", "aweme_list": []},
        {"code": "471", "aweme_list": []},
        {"status_code": 7, "code": 999, "aweme_list": []},
    ),
)
def test_int_like_or_conflicting_payload_risk_code_stops(payload: object) -> None:
    from runtime.media_missher_runtime.platforms.douyin import CollectionStopped, collect_creator

    with pytest.raises(CollectionStopped, match="payload-"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(CapturePage(responses=[Response(payload)]))))


@pytest.mark.parametrize("payload", ({"status_code": 5, "aweme_list": []}, {"code": "-1", "aweme_list": []}, {"status_code": 0, "code": "5", "aweme_list": []}))
def test_nonzero_nonrisk_payload_code_is_a_controlled_source_error(payload: object) -> None:
    from runtime.media_missher_runtime.platforms.douyin import SourceResponseError, collect_creator

    with pytest.raises(SourceResponseError, match="payload.*code"):
        _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(CapturePage(responses=[Response(payload)]))))


def test_zero_or_missing_payload_codes_are_success() -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator

    page = CapturePage(responses=[Response({"status_code": 0, "code": "0", "aweme_list": [_aweme("safe")], "has_more": False, "max_cursor": 0})])
    records = _run(collect_creator(CollectionRequest(platform="douyin", count=1, uid="creator"), ProductionBrowser(page)))

    assert [record["native_id"] for record in records] == ["safe"]


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


def test_parser_emits_source_publish_time_and_shanghai_publish_date() -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    record = parse_aweme_item(_aweme("published"), observed_at="2026-01-01T00:00:00+00:00")

    assert record["publish_time"] == 1_700_000_000
    assert isinstance(record["publish_time"], int)
    assert record["publish_date"] == "2023-11-15"
    assert record["date_precision"] == "second"
    assert record["date_source"] == "api"
    assert record["date"] == record["published_at"] == "2023-11-14T22:13:20+00:00"


def test_creator_and_search_use_the_same_publish_time_parser() -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator, search

    creator = _run(
        collect_creator(
            CollectionRequest(platform="douyin", count=1, uid="creator"),
            ProductionBrowser(CapturePage(responses=[_creator(_aweme("creator-item"))])),
        )
    )[0]
    searched = _run(
        search(
            CollectionRequest(platform="douyin", count=1, keyword="term"),
            ProductionBrowser(CapturePage(responses=[_search(_aweme("search-item"))])),
        )
    )[0]

    fields = ("publish_time", "publish_date", "date_precision", "date_source")
    assert {field: creator[field] for field in fields} == {
        field: searched[field] for field in fields
    }


@pytest.mark.parametrize("value", (None, "", "not-a-time", True, -1, 0, 1.5, float("nan"), 10**1000))
def test_parser_does_not_fabricate_publish_metadata_for_invalid_time(value: object) -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    record = parse_aweme_item(
        {"aweme_id": "invalid-time", "create_time": value, "statistics": {}},
        observed_at="2026-01-01T00:00:00+00:00",
    )

    assert record["publish_time"] is None
    assert record["publish_date"] is None
    assert record["date_precision"] is None
    assert record["date_source"] is None
    assert record["date"] is None
    assert record["published_at"] is None


def test_parser_uses_observed_media_kind_and_nested_video_duration() -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    item = _aweme("media-kind", duration=987)
    item.pop("duration")
    item["media"] = {"kind": "images"}
    record = parse_aweme_item(item, observed_at="2026-01-01T00:00:00+00:00")

    assert record["type"] == "images"
    assert record["duration_ms"] == 987


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_parser_rejects_nonfinite_metrics_and_dates(value: float) -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    item = _aweme("finite")
    item["create_time"] = value
    item["duration"] = value
    item["statistics"] = {"digg_count": value, "comment_count": value, "share_count": value, "collect_count": value, "play_count": value}
    record = parse_aweme_item(item, observed_at="2026-01-01T00:00:00+00:00")

    assert record["date"] is None and record["published_at"] is None
    assert record["duration_ms"] is None
    assert (record["liked"], record["comments"], record["shares"], record["collected"], record["plays"]) == (None, None, None, None, None)


def test_parser_handles_out_of_range_timestamp_as_unknown() -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    record = parse_aweme_item({"aweme_id": "extreme", "create_time": 10**1000}, observed_at="2026-01-01T00:00:00+00:00")

    assert record["date"] is None and record["published_at"] is None


@pytest.mark.parametrize("identifier", ("slash/id", "query?id", "has space", "control\nchar", "x" * 65))
def test_parser_rejects_unsafe_aweme_id_and_never_builds_a_link(identifier: str) -> None:
    from runtime.media_missher_runtime.platforms.douyin import parse_aweme_item

    record = parse_aweme_item(_aweme(identifier), observed_at="2026-01-01T00:00:00+00:00")

    assert record["aweme_id"] is None
    assert record["id"] is None and record["native_id"] is None
    assert record["link"] is None and record["url"] is None


def test_collection_skips_unsafe_aweme_ids() -> None:
    from runtime.media_missher_runtime.platforms.douyin import collect_creator

    page = CapturePage(responses=[_creator(_aweme("bad/id"), _aweme("safe_id-1"), has_more=False)])
    records = _run(collect_creator(CollectionRequest(platform="douyin", count=0, uid="creator"), ProductionBrowser(page)))

    assert [record["native_id"] for record in records] == ["safe_id-1"]
    assert records[0]["url"] == "https://www.douyin.com/video/safe_id-1"


def test_complete_search_is_unsupported_and_remote_browser_is_never_closed() -> None:
    from runtime.media_missher_runtime.platforms.douyin import search

    browser = ProductionBrowser(CapturePage())
    with pytest.raises(ValueError, match="complete search"):
        _run(search(CollectionRequest(platform="douyin", count=1, keyword="term", complete=True), browser))
    assert not hasattr(browser, "closed")
