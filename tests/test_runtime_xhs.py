from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest

from runtime.media_missher_runtime.browser import PreconditionError
from runtime.media_missher_runtime.models import CollectionRequest
from runtime.media_missher_runtime.platforms.xhs import PlaywrightError, PlaywrightTimeoutError


def run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fake coroutine unexpectedly suspended")


@dataclass
class Response:
    payload: object
    status: int = 200
    url: str = "https://www.xiaohongshu.com/api/sns/web/v1/user_posted"
    error: Exception | None = None
    request: object | None = None

    async def json(self) -> object:
        if self.error:
            raise self.error
        return self.payload


@dataclass
class Request:
    url: str
    post_data_json: object = None


class UnreadablePostRequest:
    def __init__(self, url: str) -> None:
        self.url = url

    @property
    def post_data_json(self) -> object:
        raise RuntimeError("synthetic non-JSON request body")


@dataclass
class Waiter:
    page: "Page"
    predicate: Any
    active: bool = False

    async def __aenter__(self) -> "Waiter":
        self.active = True
        self.page.listeners += 1
        return self

    async def __aexit__(self, *_args: Any) -> None:
        self.active = False
        self.page.listeners -= 1

    @property
    def value(self) -> Any:
        async def value() -> Response:
            while self.page.responses:
                response = self.page.responses.pop(0)
                if self.predicate(response):
                    return response
                self.page.ignored_responses += 1
            if self.page.challenge_on_response_timeout:
                self.page.challenge = "challenge-selector"
            raise PlaywrightTimeoutError("synthetic response timeout")
        return value()


@dataclass
class Locator:
    page: "Page"
    note_id: str | None = None
    selector: str = ""

    def locator(self, selector: str) -> "Locator":
        self.page.locator_paths.append((self.selector, selector))
        return Locator(self.page, selector=f"{self.selector} {selector}".strip())

    async def click(self, **_kwargs: Any) -> None:
        if self.page.close_click_error and ".close-circle" in self.selector:
            raise PlaywrightError("synthetic Playwright close failure")
        if self.note_id:
            self.page.clicked.append(self.note_id)
        self.page.modal_visible = False if self.note_id is None else True
        if ".close-circle" in self.selector and self.page.challenge_on_close:
            self.page.challenge = "challenge-selector"

    async def press(self, key: str, **_kwargs: Any) -> None:
        assert key == "Escape"
        self.page.modal_visible = False

    async def is_visible(self, **_kwargs: Any) -> bool:
        return self.page.modal_visible

    async def wait_for(self, **kwargs: Any) -> None:
        self.page.modal_waits.append(kwargs)
        if self.page.modal_wait_error:
            raise PlaywrightError("synthetic Playwright modal wait failure")

    async def evaluate_all(self, _script: str, note_id: str) -> None:
        assert self.note_id is not None
        self.page.synthetic_clicks.append(note_id)
        self.page.clicked.append(note_id)
        self.page.modal_visible = True

    async def element_handles(self) -> list["ElementHandle"]:
        assert self.selector == "#userPostedFeeds .note-item[data-note-id]"
        return [ElementHandle(self.page, card) for card in self.page.cards]


@dataclass
class ElementHandle:
    page: "Page"
    card: dict[str, Any]
    selector: str | None = None
    visible: bool = True
    disposed: bool = False

    def __post_init__(self) -> None:
        self.page.active_handles += 1

    async def evaluate(self, script: str, arg: Any) -> bool:
        assert "exact creator card interaction" in script
        lowered = script.casefold()
        for forbidden in (
            "cookie",
            "localstorage",
            "sessionstorage",
            "xsec_token",
            "location.search",
            ".href",
        ):
            assert forbidden not in lowered
        if not self.page.detail_dom_mutated:
            self.page.detail_dom_mutated = True
            if self.page.detail_dom_url_override is not None:
                self.page.url = self.page.detail_dom_url_override
            if self.page.detail_dom_note_id_override is not None:
                self.card["note_id"] = self.page.detail_dom_note_id_override
        expected = arg["expected"] if isinstance(arg, dict) else arg
        target = arg.get("target") if isinstance(arg, dict) else None
        if target is not None and self.page.detail_validation_error:
            raise PlaywrightError("synthetic candidate validation failure")
        matches = self.card.get("note_id") == expected and self.card.get("visible", True)
        if target is None:
            return matches
        return (
            matches
            and isinstance(target, ElementHandle)
            and target.card is self.card
            and target.visible
            and not target.disposed
        )

    async def query_selector(self, selector: str) -> "ElementHandle | None":
        assert self.selector is None
        links = self.card.get("links")
        if links is None:
            visible = selector in {"a.cover.mask.ld", "a.title"}
        else:
            match = next((link for link in links if link.get("selector") == selector), None)
            if match is None:
                return None
            visible = bool(match.get("visible", True))
        return ElementHandle(self.page, self.card, selector=selector, visible=visible)

    async def click(self, **_kwargs: Any) -> None:
        assert self.selector is not None
        if not self.visible:
            raise PlaywrightError("synthetic hidden element click")
        note_id = self.card.get("note_id")
        self.page.handle_clicks.append((note_id, self.selector))
        self.page.clicked.append(note_id)
        self.page.modal_visible = True
        if self.page.detail_response_on_click is not None:
            self.page.responses.append(self.page.detail_response_on_click)
            self.page.detail_response_on_click = None

    async def dispose(self) -> None:
        if self.disposed:
            return
        self.disposed = True
        self.page.active_handles -= 1
        self.page.disposed_handles.append((self.card.get("note_id"), self.selector))


@dataclass
class Keyboard:
    page: "Page"

    async def press(self, key: str) -> None:
        assert key == "Escape"
        self.page.keyboard_presses.append(key)
        self.page.modal_visible = False


@dataclass
class Page:
    url: str = "https://www.xiaohongshu.com/"
    responses: list[Response] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    challenge: str = ""
    gotos: list[str] = field(default_factory=list)
    clicked: list[str] = field(default_factory=list)
    synthetic_clicks: list[str] = field(default_factory=list)
    handle_clicks: list[tuple[str | None, str]] = field(default_factory=list)
    disposed_handles: list[tuple[str | None, str | None]] = field(default_factory=list)
    active_handles: int = 0
    listeners: int = 0
    modal_visible: bool = False
    evaluations: list[str] = field(default_factory=list)
    wait_scripts: list[tuple[str, object, int]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    locator_paths: list[tuple[str, str]] = field(default_factory=list)
    modal_waits: list[dict[str, Any]] = field(default_factory=list)
    keyboard_presses: list[str] = field(default_factory=list)
    ignored_responses: int = 0
    challenge_on_response_timeout: bool = False
    challenge_on_wait_timeout: bool = False
    timeout_card_change: bool = False
    timeout_search_settle: bool = False
    timeout_note_render: bool = False
    close_click_error: bool = False
    modal_wait_error: bool = False
    challenge_on_close: bool = False
    search_settlement_states: list[dict[str, Any]] = field(default_factory=list)
    settlement_checks: int = 0
    wait_timeouts: list[int] = field(default_factory=list)
    detail_open_waits: list[int] = field(default_factory=list)
    creator_dom_responses: list[Response] = field(default_factory=list)
    creator_dom_url_override: str | None = None
    detail_response_on_click: Response | None = None
    detail_dom_url_override: str | None = None
    detail_dom_note_id_override: str | None = None
    detail_dom_mutated: bool = False
    detail_validation_error: bool = False
    detail_metrics: dict[str, object] = field(default_factory=dict)
    detail_metric_frames: list[dict[str, object]] = field(default_factory=list)
    challenge_on_detail_open_settle: bool = False
    challenge_on_detail_metric_poll: bool = False
    detail_risk: str = ""
    locator_queries: list[str] = field(default_factory=list)

    @property
    def keyboard(self) -> Keyboard:
        return Keyboard(self)

    def expect_response(self, predicate: Any, *, timeout: int) -> Waiter:
        assert timeout == 10_000
        self.events.append("listener")
        return Waiter(self, predicate)

    async def goto(self, url: str, **_kwargs: Any) -> None:
        self.url = url
        self.gotos.append(url)
        self.events.append("navigate")

    def get_by_test_id(self, *_args: Any, **_kwargs: Any) -> Locator:
        return Locator(self)

    def locator(self, selector: str, *, has: Any = None) -> Locator:
        assert "must-not-leak" not in selector
        self.locator_queries.append(selector)
        if selector == "[data-note-id]":
            return Locator(self, self.cards[0]["note_id"] if self.cards else None, selector)
        return Locator(self, selector=selector)

    async def evaluate(self, script: str, *args: Any) -> Any:
        self.evaluations.append(script)
        if "window.scrollTo" in script:
            return None
        if "creator DOM fallback" in script:
            lowered = script.casefold()
            for forbidden in (
                "cookie",
                "localstorage",
                "sessionstorage",
                "xsec_token",
                "location.search",
                ".href",
                "document.body",
            ):
                assert forbidden not in lowered
            filters_hidden_children = (
                "if (!isVisible(element)) continue;" in script
                and "element?.innerText?.trim()" in script
            )
            cards = []
            for card in self.cards:
                if not card.get("visible", True):
                    continue
                hidden_fields = set(card.get("hidden_fields", ()))
                cards.append(
                    {
                        key: (
                            None
                            if filters_hidden_children and key in hidden_fields
                            else card.get(key)
                        )
                        for key in ("note_id", "title", "author", "liked")
                    }
                )
            self.responses.extend(self.creator_dom_responses)
            self.creator_dom_responses.clear()
            if self.creator_dom_url_override is not None:
                self.url = self.creator_dom_url_override
            return {"cards": cards}
        if "search settlement observation" in script:
            self.events.append("search-settle")
            self.settlement_checks += 1
            if self.search_settlement_states:
                return self.search_settlement_states.pop(0)
            identifiers = sorted(card["note_id"] for card in self.cards if card.get("note_id"))
            state = f"cards:{'|'.join(identifiers)}" if identifiers else "empty:search-no-result"
            return {"risk_text": self.challenge, "state": state}
        if "comments-container" in script:
            return {"risk_text": self.challenge, "comments": [{"author": "A", "text": "hello", "date": "today", "liked": "1"}]}
        if "engage-bar" in script:
            return {"risk_text": self.detail_risk or self.challenge, "metrics": self.detail_metrics}
        if "userPostedFeeds" in script:
            return {"risk_text": self.challenge, "cards": self.cards}
        if "feeds-page" in script:
            self.events.append("read-search")
            return {"risk_text": self.challenge, "cards": self.cards}
        return {"risk_text": self.challenge, "visible": self.modal_visible}

    async def wait_for_function(self, script: str, *, arg: object = None, timeout: int) -> None:
        self.wait_scripts.append((script, arg, timeout))
        if "search page settled" in script:
            self.events.append("search-settle")
            should_timeout = self.timeout_search_settle
        elif "exact note card rendered" in script:
            self.events.append("note-render")
            should_timeout = self.timeout_note_render
        elif "unseen note card" in script:
            should_timeout = self.timeout_card_change
        else:
            should_timeout = False
        if should_timeout:
            if self.challenge_on_wait_timeout:
                self.challenge = "challenge-selector"
            raise PlaywrightTimeoutError("synthetic wait timeout")

    async def wait_for_timeout(self, milliseconds: int) -> None:
        if 5_000 <= milliseconds <= 15_000:
            self.detail_open_waits.append(milliseconds)
            if self.challenge_on_detail_open_settle:
                self.challenge = "challenge-selector"
            return
        self.wait_timeouts.append(milliseconds)
        if self.detail_metric_frames:
            self.detail_metrics = self.detail_metric_frames.pop(0)
        if self.challenge_on_detail_metric_poll:
            self.challenge = "challenge-selector"


@dataclass
class Browser:
    page: Page
    allow_navigation: bool = True
    navigations: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    navigation_status: int | None = None
    navigation_url_override: str | None = None

    def require_page(self, platform: str) -> Page:
        assert platform == "xhs"
        return self.page

    async def navigate(self, page: Page, url: str, *, allowed_hosts: tuple[str, ...]) -> object:
        self.navigations.append((url, allowed_hosts))
        if not self.allow_navigation:
            raise PreconditionError("navigation")
        await page.goto(url)
        if self.navigation_url_override is not None:
            page.url = self.navigation_url_override
        if self.navigation_status is None:
            return None
        return type("NavigationResponse", (), {"status": self.navigation_status})()


def note(note_id: str, *, title: object = "Nice note", liked: object = 0) -> dict[str, Any]:
    return {
        "note_id": note_id, "type": "normal", "display_title": title,
        "interact_info": {"liked_count": liked, "liked": True, "sticky": False},
        "user": {"nickname": "Creator", "user_id": "must-not-leak"}, "xsec_token": "must-not-leak",
    }


def creator_response(*items: dict[str, Any], has_more: object = False, cursor: object = "0", uid: str = "u", post_uid: str | None = None) -> Response:
    url = f"https://www.xiaohongshu.com/api/sns/web/v1/user_posted?user_id={quote(uid, safe='')}&xsec_token=must-not-leak"
    request = Request(url, {"user_id": post_uid, "xsec_token": "must-not-leak"} if post_uid is not None else None)
    return Response({"code": 0, "success": True, "msg": "ok", "data": {"cursor": cursor, "has_more": has_more, "notes": list(items)}}, url=url, request=request)


def detail_response(note_id: str, **overrides: Any) -> Response:
    current_time = int(datetime.now(UTC).timestamp() * 1000)
    card = {
        "note_id": note_id, "title": "Detail title", "desc": "Detail desc", "type": "normal",
        "time": current_time - 1_000, "last_update_time": current_time - 1_000,
        "interact_info": {"liked_count": 0, "comment_count": 2, "collected_count": 3, "share_count": 4},
        "user": {"nickname": "Creator", "user_id": "must-not-leak"}, "xsec_token": "must-not-leak",
    }
    card.update(overrides)
    url = "https://www.xiaohongshu.com/api/sns/web/v1/feed"
    return Response(
        {"code": 0, "success": True, "msg": "ok", "data": {"current_time": current_time, "items": [{"id": note_id, "note_card": card}]}},
        url=url,
        request=Request(url, {"source_note_id": note_id}),
    )


def test_creator_parses_safe_schema_dedupes_and_paginates() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    page = Page(responses=[creator_response(note("one"), note("one"), has_more=1, cursor="next", uid="user id"), creator_response(note("two"), has_more=0, cursor="end", uid="user id")])
    records = run(collect_creator(CollectionRequest(platform="xhs", count=0, page_cap=3, uid="user id"), Browser(page)))
    assert [r["note_id"] for r in records] == ["one", "two"]
    assert page.gotos == ["https://www.xiaohongshu.com/user/profile/user%20id"]
    assert records[0]["id"] == records[0]["native_id"] == "one"
    assert records[0]["url"] == records[0]["link"] == "https://www.xiaohongshu.com/explore/one"
    assert records[0]["liked"] == 0 and records[0]["comments"] is None
    assert page.clicked == [] and page.detail_open_waits == []
    serialized = json.dumps(records)
    assert "must-not-leak" not in serialized and "xsec_token" not in serialized and "user_id" not in serialized


def test_creator_count_stops_without_extra_scroll_and_disabled_navigation_requires_matching_page() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    page = Page(responses=[creator_response(note("one"), has_more=True, cursor="next"), creator_response(note("never"))])
    assert [r["note_id"] for r in run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u"), Browser(page)))] == ["one"]
    assert len(page.responses) == 1
    with pytest.raises(PreconditionError):
        run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u"), Browser(Page(url="https://www.xiaohongshu.com/search_result?keyword=x"), allow_navigation=False)))


def test_search_reads_dom_cards_canonicalizes_links_and_never_completes() -> None:
    from runtime.media_missher_runtime.platforms.xhs import search
    page = Page(cards=[{"note_id": "abc_1", "title": "T", "desc": "D", "author": "N", "liked": "1.2万", "href": "/explore/abc_1?xsec_token=must-not-leak"}])
    records = run(search(CollectionRequest(platform="xhs", count=1, keyword="two words"), Browser(page)))
    assert page.gotos == ["https://www.xiaohongshu.com/search_result?keyword=two%20words&source=web_search_result_notes"]
    assert records[0]["link"] == "https://www.xiaohongshu.com/explore/abc_1"
    assert records[0]["liked"] == 12000 and records[0]["search_keyword"] == "two words"
    assert records[0]["comments"] is None
    assert records[0]["collected"] is None
    assert records[0]["shares"] is None
    assert records[0]["publish_time"] is None
    assert records[0]["cover"] is None
    assert records[0]["image_count"] is None
    assert page.detail_open_waits == []
    with pytest.raises(ValueError, match="complete search"):
        run(search(CollectionRequest(platform="xhs", count=1, keyword="term", complete=True), Browser(page)))


def test_search_preserves_only_observable_safe_business_fields() -> None:
    from runtime.media_missher_runtime.platforms.xhs import search

    published_ms = 1_767_225_600_000
    page = Page(
        cards=[
            {
                "note_id": "search_1",
                "title": "Visible title",
                "desc": "Visible description",
                "type": "video",
                "author": "Visible author",
                "author_avatar": (
                    "https://cdn.example.invalid/avatar.jpg?width=64&"
                    "auth_key=must-not-leak"
                ),
                "liked": "0",
                "comments": "2",
                "collected": "3",
                "shares": "4",
                "publish_time": published_ms,
                "cover": {
                    "url": (
                        "https://cdn.example.invalid/cover.jpg?width=720&"
                        "signature=must-not-leak"
                    ),
                    "width": "720",
                    "height": "960",
                },
                "image_count": "0",
                "href": "/explore/search_1?xsec_token=must-not-leak",
                "xsec_token": "must-not-leak",
                "user_id": "must-not-leak-user-id",
            }
        ]
    )

    record = run(
        search(
            CollectionRequest(platform="xhs", count=1, keyword="synthetic"),
            Browser(page),
        )
    )[0]

    assert record["desc"] == "Visible description"
    assert record["type"] == "video"
    assert record["liked"] == 0
    assert record["comments"] == 2
    assert record["collected"] == 3
    assert record["shares"] == record["raw_share_count"] == 4
    assert record["publish_time"] == published_ms
    assert record["publish_date"] == datetime.fromtimestamp(
        published_ms / 1000, ZoneInfo("Asia/Shanghai")
    ).strftime("%Y-%m-%d")
    assert record["date_source"] == "search_dom"
    assert record["date_precision"] == "second"
    assert record["cover"] == "https://cdn.example.invalid/cover.jpg?width=720"
    assert record["cover_width"] == 720
    assert record["cover_height"] == 960
    assert record["image_count"] == 0
    assert record["author_avatar"] == "https://cdn.example.invalid/avatar.jpg?width=64"
    assert record["metric_sources"] == {
        "liked": "search_dom",
        "comments": "search_dom",
        "collected": "search_dom",
        "shares": "search_dom",
        "raw_share_count": "search_dom",
    }
    assert record["detail_source"] == "search_dom"
    assert record["complete"] is False
    assert record["detail_attempted"] is False
    assert record["engagement_fresh"] is False
    encoded = json.dumps(record)
    assert "must-not-leak" not in encoded
    assert "xsec_token" not in encoded
    assert "user_id" not in encoded
    observer = next(
        script
        for script in page.evaluations
        if "search card business fields" in script
    )
    for required in (
        "desc",
        "type",
        "comments",
        "collected",
        "shares",
        "publish_time",
        "cover",
        "image_count",
    ):
        assert required in observer
    lowered = observer.casefold()
    for forbidden in (
        "cookie",
        "localstorage",
        "sessionstorage",
        "xsec_token",
        "user_id",
        "location.search",
    ):
        assert forbidden not in lowered


def test_search_drops_malformed_observable_media_metadata() -> None:
    from runtime.media_missher_runtime.platforms.xhs import parse_search_item

    record = parse_search_item(
        {
            "note_id": "search_2",
            "title": "Visible title",
            "cover": {
                "url": "https://[invalid",
                "width": "9" * 5_000,
                "height": -1,
            },
            "image_count": "9" * 5_000,
        },
        "synthetic",
        observed_at="2026-01-01T00:00:00+00:00",
    )

    assert record["cover"] is None
    assert record["cover_width"] is None
    assert record["cover_height"] is None
    assert record["image_count"] is None


def test_complete_uses_current_detail_response_and_modal_comments() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    page = Page(responses=[creator_response(note("one")), detail_response("one")], cards=[{"note_id": "one"}])
    record = run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u", complete=True, comment_limit=1), Browser(page)))[0]
    assert page.clicked == ["one"] and page.listeners == 0
    assert record["complete"] is True and record["detail_completed"] is True
    assert record["engagement_fresh"] is True and record["engagement_source"] == "detail_api"
    assert record["date_precision"] == "second" and record["date_estimated"] is False
    assert record["comments_data"] == [{"author": "A", "text": "hello", "date": "today", "liked": 1}]
    assert record["comments_detail"] == record["comments_data"]
    assert record["comments_fetched"] == 1
    assert record["metric_sources"] == {
        "liked": "detail_api",
        "comments": "detail_api",
        "collected": "detail_api",
        "shares": "detail_api",
        "raw_share_count": "detail_api",
    }


def test_complete_preserves_safe_legacy_detail_business_fields() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response(
        "one",
        desc="Detail body #Inline[话题]#",
        ip_location="Synthetic region",
        user={
            "nickname": "Creator",
            "user_id": "must-not-leak-user-id",
            "avatar": "https://cdn.example.invalid/avatar.jpg",
        },
        image_list=[
            {
                "url_default": "https://cdn.example.invalid/first.jpg",
                "width": 1080,
                "height": 1440,
                "file_id": "must-not-leak-file-id",
                "trace_id": "must-not-leak-trace-id",
            },
            {
                "info_list": [{"url": "https://cdn.example.invalid/second.jpg"}],
                "width": 720,
                "height": 960,
            },
        ],
        tag_list=[{"name": "API tag"}, {"name": "Inline"}],
        xsec_token="must-not-leak-token",
    )
    card = detail.payload["data"]["items"][0]["note_card"]  # type: ignore[index]
    published_ms = card["time"]
    updated_ms = card["last_update_time"]
    page = Page(
        responses=[creator_response(note("one")), detail],
        cards=[{"note_id": "one"}],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert {
        "author",
        "author_avatar",
        "collected",
        "comments",
        "complete",
        "cover",
        "cover_height",
        "cover_width",
        "date",
        "date_precision",
        "date_source",
        "desc",
        "detail_attempted",
        "detail_checked_at",
        "detail_link",
        "detail_source",
        "engagement_detail_fields",
        "engagement_fresh",
        "engagement_observed_at",
        "engagement_source",
        "engagement_stale_fields",
        "image_count",
        "image_details",
        "images",
        "ip_location",
        "last_update_time",
        "liked",
        "link",
        "metric_observed_at",
        "metric_sources",
        "missing_fields",
        "note_id",
        "publish_date",
        "publish_time",
        "quality_score",
        "raw_share_count",
        "tag_list",
        "tags",
        "title",
        "type",
    }.issubset(record)
    assert record["detail_source"] == "detail_api"
    assert record["detail_link"] == record["link"]
    assert record["date_source"] == "detail_api"
    assert record["publish_time"] == published_ms
    assert record["publish_date"] == datetime.fromtimestamp(
        published_ms / 1000, ZoneInfo("Asia/Shanghai")
    ).strftime("%Y-%m-%d")
    assert record["last_update_time"] == updated_ms
    assert record["ip_location"] == "Synthetic region"
    assert record["author_avatar"] == "https://cdn.example.invalid/avatar.jpg"
    assert record["cover"] == "https://cdn.example.invalid/first.jpg"
    assert record["cover_width"] == 1080
    assert record["cover_height"] == 1440
    assert record["images"] == [
        "https://cdn.example.invalid/first.jpg",
        "https://cdn.example.invalid/second.jpg",
    ]
    assert record["image_count"] == 2
    assert record["image_details"] == [
        {
            "url": "https://cdn.example.invalid/first.jpg",
            "width": 1080,
            "height": 1440,
        },
        {
            "url": "https://cdn.example.invalid/second.jpg",
            "width": 720,
            "height": 960,
        },
    ]
    assert record["tags"] == ["Inline", "API tag"]
    assert record["tag_list"] == "Inline,API tag"
    assert record["raw_share_count"] == record["shares"] == 4
    assert record["quality_score"] == 8
    assert record["engagement_detail_fields"] == [
        "liked",
        "comments",
        "collected",
        "raw_share_count",
    ]
    assert record["engagement_stale_fields"] == []
    assert set(record["metric_observed_at"]) == {
        "liked",
        "comments",
        "collected",
        "raw_share_count",
    }
    assert all(
        isinstance(value, int) and value > 0
        for value in record["metric_observed_at"].values()
    )
    encoded = json.dumps(record)
    for forbidden in (
        "xsec_token",
        "must-not-leak-token",
        "user_id",
        "must-not-leak-user-id",
        "file_id",
        "trace_id",
    ):
        assert forbidden not in encoded


def test_complete_preserves_video_and_sanitizes_media_urls() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response(
        "one",
        type="video",
        cover={
            "url_default": "https://cdn.example.invalid/cover.jpg?width=720&token=must-not-leak",
            "width": 720,
            "height": 1280,
        },
        image_list=[],
        video={
            "consumer": {"origin_video_key": "public/video-key.mp4"},
            "media": {
                "stream": {
                    "h264": [
                        {
                            "master_url": "https://video.example.invalid/main.mp4?quality=hd&xsec_token=must-not-leak",
                            "backup_urls": [
                                "https://video.example.invalid/backup.mp4?quality=hd"
                            ],
                        }
                    ]
                }
            },
        },
    )
    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(
                Page(
                    responses=[creator_response(note("one")), detail],
                    cards=[{"note_id": "one"}],
                )
            ),
        )
    )[0]

    assert record["cover"] == "https://cdn.example.invalid/cover.jpg?width=720"
    assert record["cover_width"] == 720
    assert record["cover_height"] == 1280
    assert record["image_count"] == 0
    assert record["video_urls"] == [
        "https://sns-video-bd.xhscdn.com/public/video-key.mp4",
        "https://video.example.invalid/main.mp4?quality=hd",
        "https://video.example.invalid/backup.mp4?quality=hd",
    ]
    assert record["video_url"] == ",".join(record["video_urls"])
    assert "must-not-leak" not in json.dumps(record)
    assert "xsec_token" not in json.dumps(record)


@pytest.mark.parametrize("sensitive_key", ("sign", "auth_key", "signature", "expires"))
def test_media_url_sanitizer_removes_signed_request_helpers(
    sensitive_key: str,
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import _safe_content_url

    result = _safe_content_url(
        "https://cdn.example.invalid/media.jpg?width=720&"
        f"{sensitive_key}=must-not-leak"
    )

    assert result == "https://cdn.example.invalid/media.jpg?width=720"


def test_complete_drops_malformed_media_urls_without_losing_detail_record() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response(
        "one",
        user={"nickname": "Creator", "avatar": "https://[invalid"},
        image_list=[
            {"url_default": "https://[invalid", "width": 1, "height": 1},
            {
                "url_default": "https://cdn.example.invalid/safe.jpg",
                "width": 720,
                "height": 960,
            },
        ],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(
                Page(
                    responses=[creator_response(note("one")), detail],
                    cards=[{"note_id": "one"}],
                )
            ),
        )
    )[0]

    assert record["complete"] is True
    assert record["author_avatar"] is None
    assert record["images"] == ["https://cdn.example.invalid/safe.jpg"]
    assert record["cover"] == "https://cdn.example.invalid/safe.jpg"


def test_creator_list_preserves_safe_preview_fields_without_request_helpers() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    item = note("one")
    item.update(
        {
            "desc": "Preview body",
            "time": 1_767_225_600_000,
            "cover": {
                "url_default": "https://cdn.example.invalid/preview.jpg",
                "width": 640,
                "height": 800,
            },
            "user": {
                "nickname": "Creator",
                "user_id": "must-not-leak-user-id",
                "avatar": "https://cdn.example.invalid/avatar.jpg",
            },
            "interact_info": {
                "liked_count": 1,
                "comment_count": 2,
                "collected_count": 3,
                "share_count": 4,
            },
        }
    )
    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u"),
            Browser(Page(responses=[creator_response(item)])),
        )
    )[0]

    assert record["desc"] == "Preview body"
    assert record["author_avatar"] == "https://cdn.example.invalid/avatar.jpg"
    assert record["cover"] == "https://cdn.example.invalid/preview.jpg"
    assert record["cover_width"] == 640
    assert record["cover_height"] == 800
    assert record["publish_time"] == 1_767_225_600_000
    assert record["date_source"] == "list_api"
    assert record["raw_share_count"] == record["shares"] == 4
    assert record["detail_source"] == "list_api"
    assert record["metric_sources"] == {
        "liked": "list_api",
        "comments": "list_api",
        "collected": "list_api",
        "shares": "list_api",
        "raw_share_count": "list_api",
    }
    encoded = json.dumps(record)
    assert "xsec_token" not in encoded
    assert "user_id" not in encoded


def test_complete_keeps_preview_cover_when_detail_images_are_enriched() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    item = note("one")
    item["cover"] = {
        "url_default": "https://cdn.example.invalid/preview.jpg",
        "width": 640,
        "height": 800,
    }
    detail = detail_response(
        "one",
        image_list=[
            {
                "url_default": "https://cdn.example.invalid/original.jpg",
                "width": 1080,
                "height": 1440,
            }
        ],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(
                Page(
                    responses=[creator_response(item), detail],
                    cards=[{"note_id": "one"}],
                )
            ),
        )
    )[0]

    assert record["cover"] == "https://cdn.example.invalid/preview.jpg"
    assert record["cover_width"] == 640
    assert record["cover_height"] == 800
    assert record["images"] == ["https://cdn.example.invalid/original.jpg"]


@pytest.mark.parametrize(
    "value",
    (None, True, -1, 0, float("inf"), float("nan"), 10**1000),
)
def test_creator_list_does_not_fail_or_fabricate_invalid_publish_time(
    value: object,
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import parse_creator_item

    item = note("one")
    item["time"] = value
    record = parse_creator_item(item, observed_at="2026-01-01T00:00:00+00:00")

    assert record["date"] is None
    assert record["published_at"] is None
    assert record["publish_time"] is None
    assert record["publish_date"] is None
    assert record["date_source"] is None
    assert record["date_precision"] is None


def test_complete_supplements_only_missing_required_api_metric_from_open_modal() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    del detail.payload["data"]["items"][0]["note_card"]["interact_info"]["collected_count"]  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one")), detail],
        cards=[{"note_id": "one"}],
        detail_metrics={"liked": "999", "comments": "888", "collected": "7"},
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is True
    assert record["detail_completed"] is True
    assert record["engagement_fresh"] is True
    assert record["engagement_source"] == "detail_api"
    assert record["engagement_observed_at"] is not None
    assert record["liked"] == 0 and record["comments"] == 2
    assert record["collected"] == 7 and record["shares"] == 4
    assert record["metric_sources"] == {
        "liked": "detail_api",
        "comments": "detail_api",
        "collected": "detail_html",
        "shares": "detail_api",
        "raw_share_count": "detail_api",
    }
    assert set(record["engagement_detail_fields"]) == {
        "liked",
        "comments",
        "collected",
        "raw_share_count",
    }
    assert set(record["metric_observed_at"]) == {
        "liked",
        "comments",
        "collected",
        "raw_share_count",
    }
    assert page.wait_timeouts == []
    assert sum("engage-bar" in script for script in page.evaluations) == 1


def test_complete_preserves_legacy_explicit_blank_detail_count_as_zero() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    detail.payload["data"]["items"][0]["note_card"]["interact_info"]["collected_count"] = ""  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one")), detail],
        cards=[{"note_id": "one"}],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is True
    assert record["collected"] == 0
    assert record["metric_sources"]["collected"] == "detail_api"
    assert record["engagement_fresh"] is True
    assert page.wait_timeouts == []
    assert not any("engage-bar" in script for script in page.evaluations)


@pytest.mark.parametrize("raw", [None, "--"])
def test_complete_does_not_turn_unknown_detail_count_into_zero(raw: object) -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    detail.payload["data"]["items"][0]["note_card"]["interact_info"]["collected_count"] = raw  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one")), detail],
        cards=[{"note_id": "one"}],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is False
    assert record["collected"] is None
    assert record["missing_fields"] == ["collected"]


def test_detail_html_records_safe_field_level_provenance() -> None:
    from runtime.media_missher_runtime.platforms.xhs import (
        _merge_detail_html,
        parse_creator_item,
    )

    record = parse_creator_item(note("one"), observed_at="2026-01-01T00:00:00+00:00")
    _merge_detail_html(
        record,
        {"metrics": {"liked": "0", "comments": "2", "collected": "3"}},
    )

    assert record["detail_source"] == "detail_html"
    assert isinstance(record["detail_checked_at"], int)
    assert record["engagement_detail_fields"] == [
        "liked",
        "comments",
        "collected",
    ]
    assert set(record["metric_observed_at"]) == {
        "liked",
        "comments",
        "collected",
    }
    assert record["engagement_stale_fields"] == []


def test_complete_waits_for_delayed_required_modal_metric_render() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    del detail.payload["data"]["items"][0]["note_card"]["interact_info"]["collected_count"]  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one")), detail],
        cards=[{"note_id": "one"}],
        detail_metrics={"collected": "--"},
        detail_metric_frames=[{"collected": "7"}],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is True
    assert record["collected"] == 7
    assert record["metric_sources"]["collected"] == "detail_html"
    assert page.wait_timeouts == [250]
    assert sum("engage-bar" in script for script in page.evaluations) == 2


def test_detail_metric_wait_timeout_reads_once_and_stays_incomplete() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    del detail.payload["data"]["items"][0]["note_card"]["interact_info"]["collected_count"]  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one")), detail],
        cards=[{"note_id": "one"}],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is False
    assert record["missing_fields"] == ["collected"]
    assert page.wait_timeouts == [250] * 12
    assert sum(page.wait_timeouts) == 3_000
    assert sum("engage-bar" in script for script in page.evaluations) == len(page.wait_timeouts) + 1


def test_detail_metric_wait_challenge_stops_before_dom_read_or_next_record() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, collect_creator

    detail = detail_response("one")
    del detail.payload["data"]["items"][0]["note_card"]["interact_info"]["collected_count"]  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one"), note("two")), detail],
        cards=[{"note_id": "one"}, {"note_id": "two"}],
        challenge_on_detail_metric_poll=True,
    )

    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=2, uid="u", complete=True),
                Browser(page),
            )
        )

    assert page.clicked == ["one"]
    assert page.wait_timeouts == [250]
    assert sum("engage-bar" in script for script in page.evaluations) == 1


def test_complete_replaces_stale_creator_metric_when_fresh_api_omits_it() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    del detail.payload["data"]["items"][0]["note_card"]["interact_info"]["liked_count"]  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one", liked=123)), detail],
        cards=[{"note_id": "one"}],
        detail_metrics={"liked": "7"},
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is True
    assert record["liked"] == 7
    assert record["metric_sources"]["liked"] == "detail_html"
    assert record["comments"] == 2 and record["collected"] == 3
    assert record["metric_sources"]["comments"] == "detail_api"
    assert record["metric_sources"]["collected"] == "detail_api"
    assert record["engagement_source"] == "detail_api"
    assert sum("engage-bar" in script for script in page.evaluations) == 1


def test_complete_rejects_stale_creator_metric_when_api_and_modal_omit_it() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    del detail.payload["data"]["items"][0]["note_card"]["interact_info"]["liked_count"]  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one", liked=123)), detail],
        cards=[{"note_id": "one"}],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is False
    assert record["liked"] == 123
    assert record["missing_fields"] == ["liked"]
    assert record["metric_sources"]["liked"] == "list_api"
    assert record["engagement_fresh"] is False
    assert record["engagement_source"] == "detail_api"


@pytest.mark.parametrize("field", ("liked", "comments", "collected"))
def test_completion_requires_fresh_source_for_each_required_metric(field: str) -> None:
    from runtime.media_missher_runtime.platforms.xhs import _missing_completion

    record = {
        "note_id": "one",
        "title": "Detail title",
        "date": "2026-08-04T00:00:00+00:00",
        "date_precision": "second",
        "detail_attempted": True,
        "detail_completed": True,
        "engagement_fresh": True,
        "engagement_source": "detail_api",
        "liked": 1,
        "comments": 2,
        "collected": 3,
        "metric_sources": {
            "liked": "detail_api",
            "comments": "detail_api",
            "collected": "detail_api",
        },
    }
    del record["metric_sources"][field]

    assert _missing_completion(record) == [field]


def test_completion_requires_a_valid_detail_payload_not_only_modal_metrics() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _missing_completion

    record = {
        "note_id": "one",
        "title": "Title",
        "date": "2026-01-01T00:00:00+00:00",
        "date_precision": "second",
        "detail_attempted": True,
        "detail_completed": False,
        "liked": 1,
        "comments": 2,
        "collected": 3,
        "metric_sources": {
            "liked": "detail_html",
            "comments": "detail_html",
            "collected": "detail_html",
        },
        "engagement_fresh": True,
        "engagement_source": "detail_html",
    }

    assert _missing_completion(record) == ["detail"]


def test_complete_stays_incomplete_when_api_and_modal_both_lack_required_metric() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    del detail.payload["data"]["items"][0]["note_card"]["interact_info"]["collected_count"]  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one")), detail],
        cards=[{"note_id": "one"}],
        detail_metrics={"liked": "999", "comments": "888"},
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is False
    assert record["detail_completed"] is True
    assert record["engagement_fresh"] is False
    assert record["engagement_source"] == "detail_api"
    assert record["collected"] is None
    assert record["missing_fields"] == ["collected"]
    assert record["metric_sources"] == {
        "liked": "detail_api",
        "comments": "detail_api",
        "shares": "detail_api",
        "raw_share_count": "detail_api",
    }


def test_missing_api_metric_modal_risk_stops_before_next_record() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, collect_creator

    detail = detail_response("one")
    del detail.payload["data"]["items"][0]["note_card"]["interact_info"]["collected_count"]  # type: ignore[index]
    page = Page(
        responses=[creator_response(note("one"), note("two")), detail],
        cards=[{"note_id": "one"}, {"note_id": "two"}],
        detail_metrics={"collected": "7"},
        detail_risk="challenge-selector",
    )

    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=2, uid="u", complete=True),
                Browser(page),
            )
        )

    assert page.clicked == ["one"]
    assert page.modal_visible is False


def test_complete_captures_exact_edith_detail_response() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    detail = detail_response("one")
    detail.url = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"
    page = Page(
        responses=[creator_response(note("one")), detail],
        cards=[{"note_id": "one"}],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["detail_completed"] is True
    assert record["engagement_fresh"] is True
    assert record["engagement_source"] == "detail_api"
    assert record["engagement_observed_at"] is not None


@pytest.mark.parametrize(
    ("url", "expected"),
    (
        ("https://edith.xiaohongshu.com/api/sns/web/v1/feed", True),
        ("https://www.xiaohongshu.com/api/sns/web/v1/feed", True),
        ("https://edith.xiaohongshu.com.evil.example/api/sns/web/v1/feed", False),
        ("https://evil-edith.xiaohongshu.com/api/sns/web/v1/feed", False),
        ("https://www.edith.xiaohongshu.com/api/sns/web/v1/feed", False),
        ("https://edith.xiaohongshu.com/api/sns/web/v1/feed/extra", False),
    ),
)
def test_detail_response_requires_exact_observed_host_and_path(
    url: str,
    expected: bool,
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import _is_detail_response

    assert _is_detail_response(Response({}, url=url)) is expected


def test_detail_listener_ignores_unrelated_feed_response_before_target_note() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    unrelated = detail_response("other")
    target = detail_response("one")
    page = Page(
        responses=[creator_response(note("one")), unrelated, target],
        cards=[{"note_id": "one"}],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert page.ignored_responses == 1
    assert record["detail_completed"] is True
    assert record["engagement_fresh"] is True
    assert record["complete"] is True


def test_detail_response_target_match_requires_exact_request_note_id() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _is_detail_response

    assert _is_detail_response(detail_response("one"), "one") is True
    assert _is_detail_response(detail_response("other"), "one") is False
    unreadable = detail_response("one")
    unreadable.request = UnreadablePostRequest(unreadable.url)
    assert _is_detail_response(unreadable, "one") is False


def test_incomplete_detail_risk_stops_without_further_clicks_and_http_is_checked_before_json() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, collect_creator
    detail_url = "https://www.xiaohongshu.com/api/sns/web/v1/feed"
    page = Page(responses=[creator_response(note("one"), note("two")), Response("not-json", status=403, url=detail_url, request=Request(detail_url, {"source_note_id": "one"}))], cards=[{"note_id": "one"}, {"note_id": "two"}])
    with pytest.raises(CollectionStopped, match="http-403"):
        run(collect_creator(CollectionRequest(platform="xhs", count=2, uid="u", complete=True), Browser(page)))
    assert page.clicked == ["one"]
    assert page.detail_open_waits == []


@pytest.mark.parametrize("current_time", (None, "not-a-timestamp", 0))
def test_detail_without_valid_current_response_timestamp_stays_incomplete(current_time: object) -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    response = detail_response("one")
    response.payload["data"]["current_time"] = current_time  # type: ignore[index]
    page = Page(responses=[creator_response(note("one")), response], cards=[{"note_id": "one"}])

    record = run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u", complete=True), Browser(page)))[0]

    assert record["detail_completed"] is False
    assert record["complete"] is False
    assert record["engagement_fresh"] is False
    assert record["engagement_observed_at"] is None
    assert "engagement_fresh" in record["missing_fields"]


def test_modal_is_closed_before_rethrowing_a_challenge() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, _close_modal
    page = Page(challenge="challenge-selector", modal_visible=True)

    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(_close_modal(page))

    assert page.modal_visible is False


@pytest.mark.parametrize("offset", (-timedelta(minutes=10), timedelta(minutes=10)))
def test_detail_server_time_outside_current_run_skew_is_not_fresh(offset: timedelta) -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    response = detail_response("one")
    current_time = int((datetime.now(UTC) + offset).timestamp() * 1000)
    response.payload["data"]["current_time"] = current_time  # type: ignore[index]
    response.payload["data"]["items"][0]["note_card"]["time"] = current_time - 1_000  # type: ignore[index]
    page = Page(responses=[creator_response(note("one")), response], cards=[{"note_id": "one"}])

    record = run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u", complete=True), Browser(page)))[0]

    assert record["engagement_fresh"] is False
    assert record["engagement_observed_at"] is None
    assert record["detail_completed"] is False


def test_detail_publish_time_after_server_current_time_is_rejected() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    response = detail_response("one")
    current_time = response.payload["data"]["current_time"]  # type: ignore[index]
    response.payload["data"]["items"][0]["note_card"]["time"] = current_time + 1_000  # type: ignore[index]
    page = Page(responses=[creator_response(note("one")), response], cards=[{"note_id": "one"}])

    record = run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u", complete=True), Browser(page)))[0]

    assert record["engagement_fresh"] is False
    assert record["detail_completed"] is False
    assert record["date"] is None


def test_detail_server_time_four_minutes_before_attempt_is_rejected() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    response = detail_response("one")
    current_time = int((datetime.now(UTC) - timedelta(minutes=4)).timestamp() * 1000)
    response.payload["data"]["current_time"] = current_time  # type: ignore[index]
    response.payload["data"]["items"][0]["note_card"]["time"] = current_time - 1_000  # type: ignore[index]
    page = Page(responses=[creator_response(note("one")), response], cards=[{"note_id": "one"}])

    record = run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u", complete=True), Browser(page)))[0]

    assert record["detail_completed"] is False
    assert record["engagement_fresh"] is False
    assert record["engagement_observed_at"] is None


def test_creator_listener_ignores_other_users_and_accepts_exact_query_or_post_uid() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _is_creator_response, collect_creator
    wrong = creator_response(note("wrong"), uid="other")
    matching = creator_response(note("right"), uid="target user")
    page = Page(responses=[wrong, matching])

    records = run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="target user"), Browser(page)))

    assert [record["note_id"] for record in records] == ["right"]
    assert page.ignored_responses == 1
    post_url = "https://www.xiaohongshu.com/api/sns/web/v1/user_posted?xsec_token=must-not-leak"
    post_response = Response({}, url=post_url, request=Request(post_url, {"user_id": "target user", "xsec_token": "must-not-leak"}))
    assert _is_creator_response(post_response, "target user") is True
    assert "must-not-leak" not in json.dumps(records)


def test_creator_predicate_safely_ignores_unreadable_post_body_when_query_uid_matches() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _is_creator_response
    url = "https://www.xiaohongshu.com/api/sns/web/v1/user_posted?user_id=target&xsec_token=must-not-leak"
    response = Response({}, url=url, request=UnreadablePostRequest(url))

    assert _is_creator_response(response, "target") is True


def test_creator_response_timeout_rechecks_challenge_before_stopping_pagination() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, collect_creator
    page = Page(
        responses=[creator_response(note("one"), has_more=True, cursor="next")],
        challenge_on_response_timeout=True,
    )

    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(collect_creator(CollectionRequest(platform="xhs", count=0, page_cap=2, uid="u"), Browser(page)))


def test_initial_creator_capture_timeout_rechecks_challenge_then_uses_fixed_code() -> None:
    from runtime.media_missher_runtime.platforms.xhs import (
        CaptureTimeout,
        CollectionStopped,
        collect_creator,
    )

    with pytest.raises(CaptureTimeout) as timeout:
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=1, uid="u"),
                Browser(Page()),
            )
        )
    assert timeout.value.code == "creator-capture-timeout"

    challenged = Page(challenge_on_response_timeout=True)
    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=1, uid="u"),
                Browser(challenged),
            )
        )
    assert not any("creator DOM fallback" in script for script in challenged.evaluations)


def test_initial_creator_timeout_uses_visible_target_dom_cards_without_sensitive_reads() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    page = Page(
        cards=[
            {
                "note_id": "dom-one",
                "title": "DOM title",
                "author": "DOM author",
                "liked": "1.2万",
                "visible": True,
                "href": "/explore/dom-one?xsec_token=must-not-leak",
                "xsec_token": "must-not-leak",
            },
            {"note_id": "dom-two", "title": "Never needed", "visible": True},
        ]
    )

    records = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u"),
            Browser(page),
        )
    )

    assert len(records) == 1
    assert records[0]["note_id"] == records[0]["native_id"] == "dom-one"
    assert records[0]["title"] == "DOM title"
    assert records[0]["author"] == "DOM author"
    assert records[0]["liked"] == 12_000
    assert records[0]["link"] == records[0]["url"] == "https://www.xiaohongshu.com/explore/dom-one"
    assert records[0]["complete"] is False
    assert records[0]["detail_attempted"] is False
    encoded = json.dumps(records, ensure_ascii=False)
    assert "must-not-leak" not in encoded
    assert "xsec_token" not in encoded
    fallback_script = next(script for script in page.evaluations if "creator DOM fallback" in script)
    assert "#userPostedFeeds" in fallback_script
    assert "data-note-id" in fallback_script
    assert "isVisible" in fallback_script


def test_creator_timeout_rejects_redirect_during_dom_fallback() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CaptureTimeout, collect_creator

    page = Page(
        cards=[{"note_id": "wrong-page", "title": "Wrong page", "visible": True}],
        creator_dom_url_override="https://www.xiaohongshu.com/user/profile/other",
    )

    with pytest.raises(CaptureTimeout) as timeout:
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=1, uid="u"),
                Browser(page),
            )
        )

    assert timeout.value.code == "creator-capture-timeout"


def test_creator_dom_fallback_does_not_read_hidden_child_text() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    page = Page(
        cards=[
            {
                "note_id": "visible-card",
                "title": "Hidden title",
                "author": "Hidden author",
                "liked": "999",
                "visible": True,
                "hidden_fields": {"title", "author", "liked"},
            }
        ]
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u"),
            Browser(page),
        )
    )[0]

    assert record["note_id"] == "visible-card"
    assert record["title"] is None
    assert record["author"] is None
    assert record["liked"] is None


@pytest.mark.parametrize(
    ("navigation_url_override", "cards"),
    (
        (
            "https://www.xiaohongshu.com/user/profile/other",
            [{"note_id": "wrong-target", "title": "Wrong target", "visible": True}],
        ),
        (
            None,
            [{"note_id": "hidden", "title": "Hidden", "visible": False}],
        ),
    ),
    ids=("target-mismatch", "no-visible-card"),
)
def test_creator_timeout_rejects_unsafe_dom_fallback_conditions(
    navigation_url_override: str | None,
    cards: list[dict[str, Any]],
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import CaptureTimeout, collect_creator

    page = Page(cards=cards)
    with pytest.raises(CaptureTimeout) as timeout:
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=1, uid="u"),
                Browser(page, navigation_url_override=navigation_url_override),
            )
        )

    assert timeout.value.code == "creator-capture-timeout"
    if navigation_url_override is not None:
        assert not any("creator DOM fallback" in script for script in page.evaluations)


def test_dom_fallback_complete_mode_still_requires_fresh_detail_response() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    page = Page(
        cards=[
            {
                "note_id": "dom-one",
                "title": "DOM title",
                "author": "DOM author",
                "liked": "999",
                "visible": True,
            }
        ],
        creator_dom_responses=[detail_response("dom-one")],
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["complete"] is True
    assert record["detail_attempted"] is True
    assert record["detail_completed"] is True
    assert record["engagement_fresh"] is True
    assert record["engagement_source"] == "detail_api"
    assert record["engagement_observed_at"] is not None
    assert record["liked"] == 0


@pytest.mark.parametrize(
    ("cover_visible", "expected_selector"),
    ((True, "a.cover.mask.ld"), (False, "a.title")),
    ids=("visible-cover", "visible-title-fallback"),
)
def test_dom_fallback_complete_uses_real_visible_child_click(
    cover_visible: bool,
    expected_selector: str,
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    page = Page(
        cards=[
            {
                "note_id": "dom-one",
                "title": "DOM title",
                "visible": True,
                "links": [
                    {"selector": "a", "visible": False},
                    {"selector": "a.cover.mask.ld", "visible": cover_visible},
                    {"selector": "a.title", "visible": True},
                ],
            }
        ],
        detail_response_on_click=detail_response("dom-one"),
    )

    record = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )[0]

    assert record["detail_completed"] is True
    assert record["engagement_fresh"] is True
    assert page.handle_clicks == [("dom-one", expected_selector)]
    assert page.synthetic_clicks == []
    assert "a" not in [selector for _, selector in page.handle_clicks]
    assert all("dom-one" not in selector for selector in page.locator_queries)
    assert page.active_handles == 0


@pytest.mark.parametrize(
    ("random_offset", "expected_milliseconds"),
    ((0, 5_000), (10_000, 15_000)),
    ids=("minimum", "maximum"),
)
def test_detail_click_waits_once_for_a_random_five_to_fifteen_seconds(
    monkeypatch: pytest.MonkeyPatch,
    random_offset: int,
    expected_milliseconds: int,
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    def fixed_randbelow(upper_bound: int) -> int:
        assert upper_bound == 10_001
        return random_offset

    monkeypatch.setattr(secrets, "randbelow", fixed_randbelow)
    page = Page(
        url="https://www.xiaohongshu.com/user/profile/u",
        responses=[creator_response(note("dom-one")), detail_response("dom-one")],
        cards=[{"note_id": "dom-one", "visible": True}],
    )

    run(
        collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
            Browser(page),
        )
    )

    assert page.clicked == ["dom-one"]
    assert page.detail_open_waits == [expected_milliseconds]


def test_detail_open_settle_rechecks_challenge_before_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import (
        CollectionStopped,
        collect_creator,
    )

    monkeypatch.setattr(secrets, "randbelow", lambda upper_bound: 0)
    page = Page(
        url="https://www.xiaohongshu.com/user/profile/u",
        responses=[creator_response(note("dom-one")), detail_response("dom-one")],
        cards=[{"note_id": "dom-one", "visible": True}],
        challenge_on_detail_open_settle=True,
    )

    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
                Browser(page),
            )
        )

    assert page.detail_open_waits == [5_000]
    assert page.clicked == ["dom-one"]
    assert page.modal_visible is False
    assert page.listeners == 0


def test_complete_waits_exactly_once_for_each_opened_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator

    offsets = iter((0, 10_000))
    random_calls: list[int] = []

    def next_randbelow(upper_bound: int) -> int:
        random_calls.append(upper_bound)
        return next(offsets)

    monkeypatch.setattr(secrets, "randbelow", next_randbelow)
    page = Page(
        responses=[
            creator_response(note("one"), note("two")),
            detail_response("one"),
            detail_response("two"),
        ],
        cards=[
            {"note_id": "one", "visible": True},
            {"note_id": "two", "visible": True},
        ],
    )

    records = run(
        collect_creator(
            CollectionRequest(platform="xhs", count=2, uid="u", complete=True),
            Browser(page),
        )
    )

    assert [record["note_id"] for record in records] == ["one", "two"]
    assert page.clicked == ["one", "two"]
    assert page.detail_open_waits == [5_000, 15_000]
    assert random_calls == [10_001, 10_001]


@pytest.mark.parametrize(
    ("url_override", "note_id_override"),
    (
        ("https://www.xiaohongshu.com/user/profile/other", None),
        (None, "changed-card"),
    ),
    ids=("creator-target-changed", "card-id-changed"),
)
def test_detail_click_fails_closed_when_dom_target_changes_during_selection(
    url_override: str | None,
    note_id_override: str | None,
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import _click_note_and_check

    response = detail_response("dom-one")
    page = Page(
        url="https://www.xiaohongshu.com/user/profile/u",
        cards=[
            {
                "note_id": "dom-one",
                "visible": True,
                "links": [{"selector": "a.cover.mask.ld", "visible": True}],
            }
        ],
        detail_response_on_click=response,
        detail_dom_url_override=url_override,
        detail_dom_note_id_override=note_id_override,
    )

    with pytest.raises(PlaywrightError, match="current note card is unavailable"):
        run(_click_note_and_check(page, "dom-one"))

    assert page.handle_clicks == []
    assert page.synthetic_clicks == []
    assert page.detail_open_waits == []
    assert page.detail_response_on_click is response
    assert page.responses == []
    assert page.active_handles == 0


def test_detail_click_disposes_candidate_when_validation_raises() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _click_note_and_check

    page = Page(
        url="https://www.xiaohongshu.com/user/profile/u",
        cards=[{"note_id": "dom-one", "visible": True}],
        detail_validation_error=True,
    )

    with pytest.raises(PlaywrightError, match="candidate validation failure"):
        run(_click_note_and_check(page, "dom-one"))

    assert page.handle_clicks == []
    assert page.active_handles == 0


def test_dom_fallback_detail_timeout_keeps_fixed_detail_reason_code() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CaptureTimeout, collect_creator

    page = Page(
        cards=[{"note_id": "dom-one", "title": "DOM title", "visible": True}]
    )

    with pytest.raises(CaptureTimeout) as timeout:
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
                Browser(page),
            )
        )

    assert timeout.value.code == "detail-capture-timeout"


def test_detail_capture_timeout_rechecks_challenge_then_uses_fixed_code() -> None:
    from runtime.media_missher_runtime.platforms.xhs import (
        CaptureTimeout,
        CollectionStopped,
        collect_creator,
    )

    page = Page(responses=[creator_response(note("one"))], cards=[{"note_id": "one"}])
    with pytest.raises(CaptureTimeout) as timeout:
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
                Browser(page),
            )
        )
    assert timeout.value.code == "detail-capture-timeout"

    challenged = Page(
        responses=[creator_response(note("one"))],
        cards=[{"note_id": "one"}],
        challenge_on_response_timeout=True,
    )
    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(
            collect_creator(
                CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
                Browser(challenged),
            )
        )


def test_search_card_change_timeout_rechecks_challenge_before_normal_break() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, search
    page = Page(
        cards=[{"note_id": "one", "title": "T"}],
        timeout_card_change=True,
        challenge_on_wait_timeout=True,
    )

    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(search(CollectionRequest(platform="xhs", count=0, page_cap=2, keyword="term"), Browser(page)))


def test_nonrisk_navigation_http_error_is_controlled_source_error() -> None:
    from runtime.media_missher_runtime.platforms.xhs import SourceResponseError, collect_creator
    browser = Browser(Page(responses=[creator_response(note("never"))]), navigation_status=500)

    with pytest.raises(SourceResponseError, match="http-500"):
        run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u"), browser))

    assert browser.page.listeners == 0


def test_search_waits_for_semantic_settled_state_before_first_dom_read() -> None:
    from runtime.media_missher_runtime.platforms.xhs import search
    page = Page(cards=[{"note_id": "one", "title": "T"}])

    run(search(CollectionRequest(platform="xhs", count=1, keyword="term"), Browser(page)))

    assert page.events.index("search-settle") < page.events.index("read-search")
    assert page.settlement_checks >= 2
    settle_script = next(script for script in page.evaluations if "search settlement observation" in script)
    assert "isVisible" in settle_script and "search-no-result" in settle_script
    assert "skeleton" in settle_script and "loading" in settle_script
    assert '[class*="empty"]' not in settle_script
    assert ".no-result" not in settle_script and ".empty-result" not in settle_script


def test_search_rejects_hidden_generic_or_loading_empty_state() -> None:
    from runtime.media_missher_runtime.platforms.xhs import SourceResponseError, search
    unsettled = [{"risk_text": "", "state": None} for _ in range(40)]
    page = Page(cards=[], search_settlement_states=unsettled)

    with pytest.raises(SourceResponseError, match="did not settle"):
        run(search(CollectionRequest(platform="xhs", count=1, keyword="term"), Browser(page)))

    assert page.settlement_checks == 40
    assert all(value == 250 for value in page.wait_timeouts)


def test_search_requires_same_terminal_state_on_consecutive_checks() -> None:
    from runtime.media_missher_runtime.platforms.xhs import search
    page = Page(
        cards=[{"note_id": "one", "title": "T"}],
        search_settlement_states=[
            {"risk_text": "", "state": "empty:search-no-result"},
            {"risk_text": "", "state": "cards:one"},
            {"risk_text": "", "state": "cards:one"},
        ],
    )

    records = run(search(CollectionRequest(platform="xhs", count=1, keyword="term"), Browser(page)))

    assert [record["note_id"] for record in records] == ["one"]
    assert page.settlement_checks == 3


def test_public_detail_observation_uses_attempt_completion_past_precise_run_start() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _detail_server_observed_at
    attempt_started_at = datetime(2026, 8, 3, 10, 20, 30, 500_000, tzinfo=UTC)
    response_time = datetime(2026, 8, 3, 10, 20, 30, 600_000, tzinfo=UTC)
    precise_run_start = datetime(2026, 8, 3, 10, 20, 30, 600_500, tzinfo=UTC)
    attempt_finished_at = datetime(2026, 8, 3, 10, 20, 30, 700_123, tzinfo=UTC)
    payload = {"data": {"current_time": int(response_time.timestamp() * 1000)}}

    observed_at = _detail_server_observed_at(
        payload,
        attempt_started_at=attempt_started_at,
        attempt_finished_at=attempt_finished_at,
    )

    assert observed_at is not None
    assert datetime.fromisoformat(observed_at) >= precise_run_start
    assert datetime.fromisoformat(observed_at) == attempt_finished_at
    assert observed_at.endswith("+00:00") and ".700123" in observed_at


def test_complete_waits_for_exact_note_render_before_detail_listener() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    page = Page(responses=[creator_response(note("one")), detail_response("one")], cards=[{"note_id": "one"}])

    run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u", complete=True), Browser(page)))

    assert page.events == ["listener", "navigate", "note-render", "listener"]
    render_script, arg, timeout = next(item for item in page.wait_scripts if "exact note card rendered" in item[0])
    assert arg == "one" and "challenge-selector" in render_script and timeout == 10_000


def test_card_change_wait_predicate_requires_an_unseen_note_id() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _wait_for_card_change
    page = Page(cards=[{"note_id": "one"}])

    run(_wait_for_card_change(page, ["one", "removed"]))

    script = page.wait_scripts[-1][0]
    assert "unseen note card" in script
    assert ".some" in script and "!priorSet.has" in script


def test_modal_cleanup_uses_modal_scoped_close_and_keyboard_fallback_for_playwright_error() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _close_modal
    page = Page(modal_visible=True, close_click_error=True, modal_wait_error=True)

    run(_close_modal(page))

    assert (".note-container", ".close-circle") in page.locator_paths
    assert page.keyboard_presses == ["Escape"]
    assert page.modal_visible is False
    assert page.modal_waits == [{"state": "hidden", "timeout": 3_000}]


def test_cleanup_challenge_overrides_nonrisk_primary_detail_error() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, collect_creator
    detail_url = "https://www.xiaohongshu.com/api/sns/web/v1/feed"
    bad_detail = Response({}, status=500, url=detail_url, request=Request(detail_url, {"source_note_id": "one"}))
    page = Page(
        responses=[creator_response(note("one")), bad_detail],
        cards=[{"note_id": "one"}],
        challenge_on_close=True,
    )

    with pytest.raises(CollectionStopped, match="challenge-selector"):
        run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u", complete=True), Browser(page)))

    assert page.modal_visible is False


@pytest.mark.parametrize(
    ("source", "payload"),
    (
        ("creator", {}),
        ("creator", {"code": 0, "success": True, "data": {"notes": {}}}),
        ("detail", {}),
        ("detail", {"code": 0, "success": True, "data": {"current_time": 1, "items": {}}}),
    ),
)
def test_endpoint_payload_requires_success_code_data_and_collection_shapes(source: str, payload: object) -> None:
    from runtime.media_missher_runtime.platforms.xhs import SourceResponseError, collect_creator
    if source == "creator":
        malformed = creator_response()
        malformed.payload = payload
        page = Page(responses=[malformed])
        request = CollectionRequest(platform="xhs", count=1, uid="u")
    else:
        detail_url = "https://www.xiaohongshu.com/api/sns/web/v1/feed"
        malformed = Response(payload, url=detail_url, request=Request(detail_url, {"source_note_id": "one"}))
        page = Page(responses=[creator_response(note("one")), malformed], cards=[{"note_id": "one"}])
        request = CollectionRequest(platform="xhs", count=1, uid="u", complete=True)

    with pytest.raises(SourceResponseError, match="payload"):
        run(collect_creator(request, Browser(page)))


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("0", 0),
        ("1,234", 1234),
        ("1.2万", 12000),
        ("2万", 20000),
        ("1亿", 100000000),
        ("1.5亿", 150000000),
        (None, None),
        ("", None),
        ("--", None),
        ("加载中", None),
        ("-1", None),
        ("NaN万", None),
        ("Infinity", None),
        (float("inf"), None),
        (10**1000, None),
    ),
)
def test_count_parser_is_finite_and_localized(value: object, expected: object) -> None:
    from runtime.media_missher_runtime.platforms.xhs import parse_count
    assert parse_count(value) == expected


def test_risk_success_false_challenge_and_reports_cannot_leak_content_or_secrets() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, build_checkpoint, build_run_report, collect_creator
    risk_response = creator_response()
    risk_response.payload = {"code": 0, "success": False, "msg": "account locked"}
    with pytest.raises(CollectionStopped):
        run(collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u"),
            Browser(Page(responses=[risk_response])),
        ))
    report = build_run_report("complete", [{"note_id": "n", "title": "must-not-leak", "detail_attempted": True, "detail_completed": True, "complete": True, "engagement_fresh": True}], "start", "end", reason="xsec_token=must-not-leak")
    checkpoint = build_checkpoint([{"note_id": "n", "observed_at": "now", "xsec_token": "must-not-leak"}])
    encoded = json.dumps({"report": report, "checkpoint": checkpoint})
    assert report == {"status": "complete", "started_at": "start", "finished_at": "end", "final_items": 1, "complete_items": 1, "fresh_items": 1, "detail_attempts": 1, "detail_successes": 1, "reason": "risk-signal"}
    assert checkpoint == {"items": [{"note_id": "n", "observed_at": "now"}]}
    assert "must-not-leak" not in encoded


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("http-403", "http-403"),
        ("payload-471", "payload-471"),
        ("challenge", "challenge"),
        ("privateuid12345", "risk-signal"),
        ("https://example.invalid/?uid=private", "risk-signal"),
        ("account server message", "risk-signal"),
    ],
)
def test_xhs_report_reason_uses_only_fixed_diagnostic_codes(
    reason: str, expected: str
) -> None:
    from runtime.media_missher_runtime.platforms.xhs import build_run_report

    report = build_run_report("failed", [], "start", "end", reason=reason)

    assert report["reason"] == expected
    if expected == "risk-signal":
        assert reason not in json.dumps(report)
