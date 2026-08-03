from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Coroutine

import pytest

from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError
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
    url: str = "https://weibo.com/ajax/statuses/mymblog"
    json_error: Exception | None = None
    json_calls: int = 0

    async def json(self) -> object:
        self.json_calls += 1
        if self.json_error:
            raise self.json_error
        return self.payload


@dataclass
class Waiter:
    page: "Page"
    predicate: Any
    exited: bool = False
    cancelled: bool = False

    async def __aenter__(self) -> "Waiter":
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
class Page:
    url: str = "https://weibo.com/"
    responses: list[Response] = field(default_factory=list)
    search_pages: list[dict[str, Any]] = field(default_factory=list)
    challenge: str = ""
    challenge_on_goto: bool = False
    listener_active: bool = False
    listener_count: int = 0
    gotos: list[str] = field(default_factory=list)
    evaluations: list[str] = field(default_factory=list)
    scrolls: int = 0

    def expect_response(self, predicate: Any, **kwargs: Any) -> Waiter:
        assert kwargs["timeout"] == 10_000
        self.listener_count += 1
        return Waiter(self, predicate)

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.gotos.append(url)
        if self.challenge_on_goto:
            self.challenge = "challenge-selector"

    async def evaluate(self, script: str) -> Any:
        self.evaluations.append(script)
        if "window.scrollTo" in script:
            self.scrolls += 1
            return None
        if "card-wrap" in script:
            return self.search_pages.pop(0) if self.search_pages else {"risk_text": "", "cards": [], "next": None}
        return {"risk_text": self.challenge}

    async def wait_for_function(self, script: str, **kwargs: Any) -> None:
        assert kwargs["timeout"] == 10_000


@dataclass
class PhraseTimeoutPage(Page):
    timeout_after_gotos: int = 1
    timeout_challenge: str | None = None
    waits: list[str] = field(default_factory=list)

    async def wait_for_function(self, script: str, **kwargs: Any) -> None:
        await super().wait_for_function(script, **kwargs)
        self.waits.append(script)
        if len(self.gotos) >= self.timeout_after_gotos:
            if self.timeout_challenge is not None:
                self.challenge = self.timeout_challenge
            raise TimeoutError("synthetic hydration timeout")


@dataclass
class Browser:
    page: Page
    allow_navigation: bool = True
    navigations: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def require_page(self, platform: str) -> Page:
        assert platform == "weibo"
        return self.page

    async def navigate(self, page: Page, url: str, *, allowed_hosts: tuple[str, ...]) -> None:
        self.navigations.append((url, allowed_hosts))
        if not self.allow_navigation:
            raise PreconditionError("navigation")
        await page.goto(url)


def _post(identifier: str, *, text: str = "<b>Hello &amp; world</b>", favorited: object = False) -> dict[str, Any]:
    return {
        "idstr": identifier, "mblogid": "MB" + identifier, "created_at": "2026-01-01", "text_raw": text,
        "attitudes_count": 0, "comments_count": 2, "reposts_count": 3, "favorited": favorited,
        "pic_ids": ["pic-1"], "source": "Synthetic client",
        "user": {"screen_name": "Author", "id": "secret-user", "avatar_hd": "https://secret"},
        "analysis": {"tracking": "must-not-leak"},
    }


def _creator(*posts: dict[str, Any], since_id: object = None, total: object = None, ok: object = 1) -> Response:
    return Response({"ok": ok, "data": {"list": list(posts), "since_id": since_id, "total": total}})


def test_browser_weibo_host_allowlist_is_exact_and_includes_search_host() -> None:
    class Context:
        def __init__(self) -> None:
            self.pages = [type("P", (), {"url": "https://s.weibo.com/weibo?q=x"})()]
    remote = type("B", (), {"contexts": [Context()]})()
    session = BrowserSession(type("PW", (), {})(), remote)
    assert session.require_page("weibo").url.startswith("https://s.weibo.com/")


def test_creator_parser_keeps_compatibility_aliases_zero_null_and_drops_sensitive_user_data() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    record = parse_creator_item(_post("safe-id", favorited=True), author_domain="author", observed_at="2026-01-01T00:00:00+00:00")
    assert record["platform"] == "weibo" and record["mblog_id"] == "MBsafe-id"
    assert record["title"] == "Hello & world" and record["liked"] == 0 and record["collected"] is None
    assert record["id"] == record["native_id"] == "MBsafe-id"
    assert record["link"] == record["url"] == "https://weibo.com/author/MBsafe-id"
    assert record["author"] == "Author" and record["published_at"] == record["date"]
    rendered = json.dumps(record)
    for forbidden in ("secret-user", "avatar_hd", "analysis", "tracking", "favorited"):
        assert forbidden not in rendered


@pytest.mark.parametrize("identifier", ("bad/id", "has space", "x" * 65, None))
def test_parser_never_builds_links_for_unsafe_or_unknown_native_ids(identifier: object) -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("fallback")
    post["mblogid"] = identifier
    post["idstr"] = identifier
    post["id"] = identifier
    record = parse_creator_item(post, author_domain="bad/path")
    assert record["native_id"] is None and record["link"] is None


def test_html_strip_and_sanitized_raw_markup_are_bounded_and_safe() -> None:
    from runtime.media_missher_runtime.platforms.weibo import clean_html, sanitize_raw_html

    assert clean_html("A<script>secret</script><br>B &amp; C") == "A B & C"
    raw = sanitize_raw_html('<article onclick="x()"><script>secret</script><a href="https://x.test/a?token=secret#f">X</a><input value="password=secret"></article>' * 100)
    assert len(raw or "") <= 4096
    for forbidden in ("script", "onclick", "?token", "#f", "password=secret"):
        assert forbidden not in (raw or "").casefold()


def test_sanitized_raw_markup_escapes_entity_decoded_markup_as_text() -> None:
    from runtime.media_missher_runtime.platforms.weibo import sanitize_raw_html

    raw = sanitize_raw_html("&lt;img src=x onerror=alert(1)&gt;")

    assert raw == "&lt;img src=x onerror=alert(1)&gt;"
    assert "<img" not in (raw or "")


def test_sanitized_raw_markup_drops_secret_markers_from_every_retained_attribute() -> None:
    from runtime.media_missher_runtime.platforms.weibo import sanitize_raw_html

    raw = sanitize_raw_html(
        '<div title="token-value" class="secret-card" aria-label="cookie-value">'
        '<img alt="password-value" title="safe-label"></div>'
    )

    assert raw == '<div><img title="safe-label"></div>'
    for marker in ("token", "secret", "password", "cookie"):
        assert marker not in (raw or "").casefold()


def test_creator_capture_navigation_and_count_rules_do_not_construct_api_requests() -> None:
    from runtime.media_missher_runtime.platforms.weibo import collect_creator

    page = Page(responses=[_creator(_post("one"), _post("two"), since_id="next", total=2)])
    records = _run(collect_creator(CollectionRequest(platform="weibo", count=1, uid="a b"), Browser(page)))
    assert [record["native_id"] for record in records] == ["MBone"]
    assert page.gotos == ["https://weibo.com/u/a%20b"]
    assert page.scrolls == 0 and all("ajax/" not in call for call in page.gotos)

    capped = Page(responses=[_creator(_post("one"), since_id="1"), _creator(_post("two"), since_id="2")])
    assert len(_run(collect_creator(CollectionRequest(platform="weibo", count=0, page_cap=2, uid="creator"), Browser(capped)))) == 2
    assert capped.scrolls == 1


def test_creator_passive_mode_requires_authorized_navigation_without_listener_or_scroll() -> None:
    from runtime.media_missher_runtime.platforms.weibo import collect_creator

    page = Page(url="https://weibo.com/u/creator", responses=[_creator(_post("never"))])
    with pytest.raises(PreconditionError, match="authorized navigation/reload"):
        _run(collect_creator(CollectionRequest(platform="weibo", count=1, uid="creator"), Browser(page, allow_navigation=False)))

    assert page.listener_count == 0
    assert page.scrolls == 0
    assert len(page.responses) == 1


def test_creator_passive_mode_still_validates_exact_target_before_navigation_requirement() -> None:
    from runtime.media_missher_runtime.platforms.weibo import collect_creator

    page = Page(url="https://weibo.com/u/other", responses=[_creator(_post("never"))])
    with pytest.raises(PreconditionError, match="matching Weibo creator"):
        _run(collect_creator(CollectionRequest(platform="weibo", count=1, uid="creator"), Browser(page, allow_navigation=False)))

    assert page.listener_count == 0
    assert page.scrolls == 0


def test_creator_challenge_is_rejected_before_navigation_or_listener() -> None:
    from runtime.media_missher_runtime.platforms.weibo import CollectionStopped, collect_creator

    challenged = Page(responses=[_creator(_post("never"))], challenge="challenge-selector")
    with pytest.raises(CollectionStopped):
        _run(collect_creator(CollectionRequest(platform="weibo", count=1, uid="creator"), Browser(challenged)))
    assert challenged.gotos == [] and challenged.listener_count == 0 and not challenged.listener_active


def test_creator_risk_nonjson_ok_and_no_progress_are_controlled() -> None:
    from runtime.media_missher_runtime.platforms.weibo import CollectionStopped, SourceResponseError, collect_creator

    for status in (403, 429):
        response = Response(None, status=status, json_error=AssertionError("must not parse JSON"))
        with pytest.raises(CollectionStopped, match=f"http-{status}"):
            _run(collect_creator(CollectionRequest(platform="weibo", count=1, uid="x"), Browser(Page(responses=[response]))))
        assert response.json_calls == 0
    for payload in (_creator(_post("one"), ok=0), Response({"code": 461}), Response({"ok": 1, "data": {"list": [_post("one")], "since_id": "same"}})):
        page = Page(responses=[payload, _creator(_post("two"), since_id="same")])
        if isinstance(payload, Response) and payload.payload.get("ok") == 1:
            assert len(_run(collect_creator(CollectionRequest(platform="weibo", count=0, page_cap=3, uid="x"), Browser(page)))) == 1
        else:
            with pytest.raises((CollectionStopped, SourceResponseError)):
                _run(collect_creator(CollectionRequest(platform="weibo", count=1, uid="x"), Browser(page)))


def test_search_parses_semantic_cards_and_follows_only_valid_platform_next_links() -> None:
    from runtime.media_missher_runtime.platforms.weibo import search

    card = {"mid": "mid-1", "text": "<span>Text &amp; more</span>", "date": "2026-01-02", "href": "/123/MB1", "author": "Author", "liked": 0, "comments": 2, "shares": 3, "collected": None, "source": "web", "raw_html": "<div>safe</div>"}
    next_card = dict(card, mid="mid-2")
    page = Page(search_pages=[{"risk_text": "", "cards": [card], "next": "https://s.weibo.com/weibo?q=two+words&page=2#fragment"}, {"risk_text": "", "cards": [next_card], "next": None}])
    records = _run(search(CollectionRequest(platform="weibo", count=2, keyword="two words"), Browser(page)))
    assert records[0]["title"] == "Text & more" and records[0]["search_keyword"] == "two words"
    assert records[0]["raw_html"] == "<div>safe</div>"
    assert page.gotos == ["https://s.weibo.com/weibo?q=two+words", "https://s.weibo.com/weibo?q=two+words&page=2"]


@pytest.mark.parametrize("next_url", ("https://evil.test/weibo?q=term", "https://s.weibo.com/other?q=term", "https://s.weibo.com/weibo?q=other", "http://s.weibo.com/weibo?q=term"))
def test_search_rejects_invalid_next_link_without_navigation(next_url: str) -> None:
    from runtime.media_missher_runtime.platforms.weibo import search

    page = Page(search_pages=[{"risk_text": "", "cards": [{"mid": "one", "text": "one"}], "next": next_url}])
    assert len(_run(search(CollectionRequest(platform="weibo", count=0, page_cap=2, keyword="term"), Browser(page)))) == 1
    assert page.gotos == ["https://s.weibo.com/weibo?q=term"]


def test_search_passive_q_validation_complete_challenge_and_normal_risk_word() -> None:
    from runtime.media_missher_runtime.platforms.weibo import CollectionStopped, search

    passive = Page(url="https://s.weibo.com/weibo?q=term", search_pages=[{"risk_text": "", "cards": [{"mid": "one", "text": "risk analysis"}], "next": None}])
    assert _run(search(CollectionRequest(platform="weibo", count=1, keyword="term"), Browser(passive, allow_navigation=False)))[0]["title"] == "risk analysis"
    with pytest.raises(PreconditionError):
        _run(search(CollectionRequest(platform="weibo", count=1, keyword="term"), Browser(Page(url="https://s.weibo.com/weibo?q=other"), allow_navigation=False)))
    with pytest.raises(ValueError, match="complete search"):
        _run(search(CollectionRequest(platform="weibo", count=1, keyword="term", complete=True), Browser(Page())))
    blocked = Page(search_pages=[{"risk_text": "challenge-selector", "cards": [], "next": None}])
    with pytest.raises(CollectionStopped):
        _run(search(CollectionRequest(platform="weibo", count=1, keyword="term"), Browser(blocked)))


@pytest.mark.parametrize("phrase", ("请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控", "安全验证", "验证码"))
def test_search_initial_phrase_challenge_stops_when_hydration_wait_times_out(phrase: str) -> None:
    from runtime.media_missher_runtime.platforms.weibo import CollectionStopped, search

    page = PhraseTimeoutPage(challenge=phrase)
    with pytest.raises(CollectionStopped, match=phrase):
        _run(search(CollectionRequest(platform="weibo", count=1, keyword="term"), Browser(page)))

    assert page.gotos == ["https://s.weibo.com/weibo?q=term"]
    assert len(page.evaluations) == 1
    assert all(phrase in page.waits[0] for phrase in ("请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控", "安全验证", "验证码"))


def test_search_next_page_phrase_challenge_stops_after_wait_timeout_without_extra_parse_or_navigation() -> None:
    from runtime.media_missher_runtime.platforms.weibo import CollectionStopped, search

    page = PhraseTimeoutPage(
        timeout_after_gotos=2,
        timeout_challenge="风控",
        search_pages=[{"risk_text": "", "cards": [{"mid": "one", "text": "one"}], "next": "https://s.weibo.com/weibo?q=term&page=2"}],
    )
    with pytest.raises(CollectionStopped, match="风控"):
        _run(search(CollectionRequest(platform="weibo", count=0, page_cap=3, keyword="term"), Browser(page)))

    assert page.gotos == ["https://s.weibo.com/weibo?q=term", "https://s.weibo.com/weibo?q=term&page=2"]
    assert sum("card-wrap" in script for script in page.evaluations) == 1
