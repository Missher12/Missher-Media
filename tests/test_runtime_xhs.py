from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

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
            raise TimeoutError("synthetic response timeout")
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
            raise RuntimeError("synthetic Playwright close failure")
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
            raise RuntimeError("synthetic Playwright modal wait failure")

    async def evaluate_all(self, _script: str, note_id: str) -> None:
        assert self.note_id is not None
        self.page.clicked.append(note_id)
        self.page.modal_visible = True


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
        if selector == "[data-note-id]":
            return Locator(self, self.cards[0]["note_id"] if self.cards else None, selector)
        return Locator(self, selector=selector)

    async def evaluate(self, script: str, *args: Any) -> Any:
        self.evaluations.append(script)
        if "window.scrollTo" in script:
            return None
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
            raise TimeoutError("synthetic wait timeout")

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.wait_timeouts.append(milliseconds)


@dataclass
class Browser:
    page: Page
    allow_navigation: bool = True
    navigations: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    navigation_status: int | None = None

    def require_page(self, platform: str) -> Page:
        assert platform == "xhs"
        return self.page

    async def navigate(self, page: Page, url: str, *, allowed_hosts: tuple[str, ...]) -> object:
        self.navigations.append((url, allowed_hosts))
        if not self.allow_navigation:
            raise PreconditionError("navigation")
        await page.goto(url)
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
    return Response({"code": 0, "success": True, "msg": "ok", "data": {"current_time": current_time, "items": [{"id": note_id, "note_card": card}] }}, url="https://www.xiaohongshu.com/api/sns/web/v1/feed")


def test_creator_parses_safe_schema_dedupes_and_paginates() -> None:
    from runtime.media_missher_runtime.platforms.xhs import collect_creator
    page = Page(responses=[creator_response(note("one"), note("one"), has_more=1, cursor="next", uid="user id"), creator_response(note("two"), has_more=0, cursor="end", uid="user id")])
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
    assert record["date_precision"] == "second" and record["date_estimated"] is False
    assert record["comments_data"] == [{"author": "A", "text": "hello", "date": "today", "liked": 1}]
    assert record["metric_sources"] == {"liked": "detail_api", "comments": "detail_api", "collected": "detail_api", "shares": "detail_api"}


def test_incomplete_detail_risk_stops_without_further_clicks_and_http_is_checked_before_json() -> None:
    from runtime.media_missher_runtime.platforms.xhs import CollectionStopped, collect_creator
    page = Page(responses=[creator_response(note("one"), note("two")), Response("not-json", status=403, url="https://www.xiaohongshu.com/api/sns/web/v1/feed")], cards=[{"note_id": "one"}, {"note_id": "two"}])
    with pytest.raises(CollectionStopped, match="http-403"):
        run(collect_creator(CollectionRequest(platform="xhs", count=2, uid="u", complete=True), Browser(page)))
    assert page.clicked == ["one"]


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


def test_detail_server_observation_preserves_same_second_millisecond_ordering() -> None:
    from runtime.media_missher_runtime.platforms.xhs import _detail_server_observed_at
    attempt_started_at = datetime(2026, 8, 3, 10, 20, 30, 500_000, tzinfo=UTC)
    response_time = datetime(2026, 8, 3, 10, 20, 30, 600_000, tzinfo=UTC)
    attempt_finished_at = datetime(2026, 8, 3, 10, 20, 30, 700_000, tzinfo=UTC)
    payload = {"data": {"current_time": int(response_time.timestamp() * 1000)}}

    observed_at = _detail_server_observed_at(
        payload,
        attempt_started_at=attempt_started_at,
        attempt_finished_at=attempt_finished_at,
    )

    assert observed_at is not None
    assert datetime.fromisoformat(observed_at) >= attempt_started_at
    assert observed_at.endswith("+00:00") and ".600" in observed_at


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
    bad_detail = Response({}, status=500, url="https://www.xiaohongshu.com/api/sns/web/v1/feed")
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
        malformed = Response(payload, url="https://www.xiaohongshu.com/api/sns/web/v1/feed")
        page = Page(responses=[creator_response(note("one")), malformed], cards=[{"note_id": "one"}])
        request = CollectionRequest(platform="xhs", count=1, uid="u", complete=True)

    with pytest.raises(SourceResponseError, match="payload"):
        run(collect_creator(request, Browser(page)))


@pytest.mark.parametrize("value, expected", [("2万", 20000), ("1.5亿", 150000000), ("0", 0), (None, None), ("NaN万", None), (float("inf"), None)])
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
    assert report == {"status": "complete", "started_at": "start", "finished_at": "end", "final_items": 1, "complete_items": 1, "fresh_items": 1, "detail_attempts": 1, "detail_successes": 1, "reason": "redacted"}
    assert checkpoint == {"items": [{"note_id": "n", "observed_at": "now"}]}
    assert "must-not-leak" not in encoded
