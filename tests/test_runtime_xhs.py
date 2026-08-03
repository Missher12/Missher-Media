from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from runtime.media_missher_runtime.browser import PreconditionError
from runtime.media_missher_runtime.models import CollectionRequest


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

    async def json(self) -> object:
        if self.error:
            raise self.error
        return self.payload


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
            response = self.page.responses.pop(0)
            assert self.predicate(response)
            return response
        return value()


@dataclass
class Locator:
    page: "Page"
    note_id: str | None = None

    async def click(self) -> None:
        if self.note_id:
            self.page.clicked.append(self.note_id)
        self.page.modal_visible = False if self.note_id is None else True

    async def press(self, key: str) -> None:
        assert key == "Escape"
        self.page.modal_visible = False

    async def is_visible(self) -> bool:
        return self.page.modal_visible

    async def evaluate_all(self, _script: str, note_id: str) -> None:
        assert self.note_id is not None
        self.page.clicked.append(note_id)
        self.page.modal_visible = True


@dataclass
class Page:
    url: str = "https://www.xiaohongshu.com/"
    responses: list[Response] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    challenge: str = ""
    gotos: list[str] = field(default_factory=list)
    clicked: list[str] = field(default_factory=list)
    listeners: int = 0
    modal_visible: bool = False
    evaluations: list[str] = field(default_factory=list)

    def expect_response(self, predicate: Any, *, timeout: int) -> Waiter:
        assert timeout == 10_000
        return Waiter(self, predicate)

    async def goto(self, url: str, **_kwargs: Any) -> None:
        self.url = url
        self.gotos.append(url)

    def get_by_test_id(self, *_args: Any, **_kwargs: Any) -> Locator:
        return Locator(self)

    def locator(self, selector: str, *, has: Any = None) -> Locator:
        assert "must-not-leak" not in selector
        if selector == "[data-note-id]":
            return Locator(self, self.cards[0]["note_id"] if self.cards else None)
        return Locator(self)

    async def evaluate(self, script: str, *args: Any) -> Any:
        self.evaluations.append(script)
        if "window.scrollTo" in script:
            return None
        if "comments-container" in script:
            return {"risk_text": self.challenge, "comments": [{"author": "A", "text": "hello", "date": "today", "liked": "1"}]}
        if "userPostedFeeds" in script:
            return {"risk_text": self.challenge, "cards": self.cards}
        if "feeds-page" in script:
            return {"risk_text": self.challenge, "cards": self.cards}
        return {"risk_text": self.challenge, "visible": self.modal_visible}

    async def wait_for_function(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@dataclass
class Browser:
    page: Page
    allow_navigation: bool = True
    navigations: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def require_page(self, platform: str) -> Page:
        assert platform == "xhs"
        return self.page

    async def navigate(self, page: Page, url: str, *, allowed_hosts: tuple[str, ...]) -> None:
        self.navigations.append((url, allowed_hosts))
        if not self.allow_navigation:
            raise PreconditionError("navigation")
        await page.goto(url)


def note(note_id: str, *, title: object = "Nice note", liked: object = 0) -> dict[str, Any]:
    return {
        "note_id": note_id, "type": "normal", "display_title": title,
        "interact_info": {"liked_count": liked, "liked": True, "sticky": False},
        "user": {"nickname": "Creator", "user_id": "must-not-leak"}, "xsec_token": "must-not-leak",
    }


def creator_response(*items: dict[str, Any], has_more: object = False, cursor: object = "0") -> Response:
    return Response({"code": 0, "success": True, "msg": "ok", "data": {"cursor": cursor, "has_more": has_more, "notes": list(items)}})


def detail_response(note_id: str, **overrides: Any) -> Response:
    card = {
        "note_id": note_id, "title": "Detail title", "desc": "Detail desc", "type": "normal",
        "time": 1_700_000_000_000, "last_update_time": 1_700_000_000_000,
        "interact_info": {"liked_count": 0, "comment_count": 2, "collected_count": 3, "share_count": 4},
        "user": {"nickname": "Creator", "user_id": "must-not-leak"}, "xsec_token": "must-not-leak",
    }
    card.update(overrides)
    return Response({"code": 0, "success": True, "msg": "ok", "data": {"current_time": 1_700_000_001_000, "items": [{"id": note_id, "note_card": card}] }}, url="https://www.xiaohongshu.com/api/sns/web/v1/feed")


def test_creator_parses_safe_schema_dedupes_and_paginates() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    page = Page(responses=[creator_response(note("one"), note("one"), has_more=1, cursor="next"), creator_response(note("two"), has_more=0, cursor="end")])
    records = run(collect_creator(CollectionRequest(platform="xhs", count=0, page_cap=3, uid="user id"), Browser(page)))
    assert [r["note_id"] for r in records] == ["one", "two"]
    assert page.gotos == ["https://www.xiaohongshu.com/user/profile/user%20id"]
    assert records[0]["id"] == records[0]["native_id"] == "one"
    assert records[0]["url"] == records[0]["link"] == "https://www.xiaohongshu.com/explore/one"
    assert records[0]["liked"] == 0 and records[0]["comments"] is None
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
    with pytest.raises(ValueError, match="complete search"):
        run(search(CollectionRequest(platform="xhs", count=1, keyword="term", complete=True), Browser(page)))


def test_complete_uses_current_detail_response_and_modal_comments() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    page = Page(responses=[creator_response(note("one")), detail_response("one")], cards=[{"note_id": "one"}])
    record = run(collect_creator(CollectionRequest(platform="xhs", count=1, uid="u", complete=True, comment_limit=1), Browser(page)))[0]
    assert page.clicked == ["one"] and page.listeners == 0
    assert record["complete"] is True and record["detail_completed"] is True
    assert record["engagement_fresh"] is True and record["engagement_source"] == "detail_api"
    assert record["date_precision"] == "second" and record["comments_data"] == [{"author": "A", "text": "hello", "date": "today", "liked": 1}]
    assert record["metric_sources"] == {"liked": "detail_api", "comments": "detail_api", "collected": "detail_api", "shares": "detail_api"}


def test_incomplete_detail_risk_stops_without_further_clicks_and_http_is_checked_before_json() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, collect_creator
    page = Page(responses=[creator_response(note("one"), note("two")), Response("not-json", status=403, url="https://www.xiaohongshu.com/api/sns/web/v1/feed")], cards=[{"note_id": "one"}, {"note_id": "two"}])
    with pytest.raises(CollectionStopped, match="http-403"):
        run(collect_creator(CollectionRequest(platform="xhs", count=2, uid="u", complete=True), Browser(page)))
    assert page.clicked == ["one"]


@pytest.mark.parametrize("value, expected", [("2万", 20000), ("1.5亿", 150000000), ("0", 0), (None, None), ("NaN万", None), (float("inf"), None)])
def test_count_parser_is_finite_and_localized(value: object, expected: object) -> None:
    from runtime.media_missher_runtime.platforms.xhs import parse_count
    assert parse_count(value) == expected


def test_risk_success_false_challenge_and_reports_cannot_leak_content_or_secrets() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, build_checkpoint, build_run_report, collect_creator
    with pytest.raises(CollectionStopped):
        run(collect_creator(
            CollectionRequest(platform="xhs", count=1, uid="u"),
            Browser(Page(responses=[Response({"code": 0, "success": False, "msg": "account locked"})])),
        ))
    report = build_run_report("complete", [{"note_id": "n", "title": "must-not-leak", "detail_attempted": True, "detail_completed": True, "complete": True, "engagement_fresh": True}], "start", "end", reason="xsec_token=must-not-leak")
    checkpoint = build_checkpoint([{"note_id": "n", "observed_at": "now", "xsec_token": "must-not-leak"}])
    encoded = json.dumps({"report": report, "checkpoint": checkpoint})
    assert report == {"status": "complete", "started_at": "start", "finished_at": "end", "final_items": 1, "complete_items": 1, "fresh_items": 1, "detail_attempts": 1, "detail_successes": 1, "reason": "redacted"}
    assert checkpoint == {"items": [{"note_id": "n", "observed_at": "now"}]}
    assert "must-not-leak" not in encoded
