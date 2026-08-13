from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Coroutine
from urllib.parse import urlencode

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
    url: str = "https://weibo.com/ajax/statuses/mymblog?uid=creator"
    json_error: Exception | None = None
    json_calls: int = 0

    async def json(self) -> object:
        self.json_calls += 1
        if self.json_error:
            raise self.json_error
        return self.payload


def test_creator_response_predicate_is_bound_to_the_requested_uid() -> None:
    from runtime.media_missher_runtime.platforms.weibo import _is_creator_response

    wrong = Response({}, url="https://weibo.com/ajax/statuses/mymblog?uid=other")
    right = Response({}, url="https://weibo.com/ajax/statuses/mymblog?uid=target")

    assert _is_creator_response(wrong, "target") is False
    assert _is_creator_response(right, "target") is True


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

    async def evaluate(self, script: str, argument: Any = None) -> Any:
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
    waits: list[tuple[str, Any]] = field(default_factory=list)

    async def wait_for_function(self, script: str, **kwargs: Any) -> None:
        from runtime.media_missher_runtime.platforms.weibo import PlaywrightTimeoutError

        await super().wait_for_function(script, **kwargs)
        self.waits.append((script, kwargs.get("arg")))
        if len(self.gotos) >= self.timeout_after_gotos:
            if self.timeout_challenge is not None:
                self.challenge = self.timeout_challenge
            raise PlaywrightTimeoutError("synthetic hydration timeout")


@dataclass
class ChallengeDomPage(Page):
    body_text: str = ""
    ordinary_class: str = ""
    hidden_challenge: bool = False
    visible_challenge: str | None = None
    visible_block_text: str = ""

    async def evaluate(self, script: str, argument: Any = None) -> Any:
        self.evaluations.append(script)
        phrases = ("请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控", "安全验证", "验证码")
        if argument is None:
            selector_match = (
                bool(self.ordinary_class and "verify" in self.ordinary_class)
                or self.hidden_challenge
                or self.visible_challenge is not None
            )
            phrase = next((item for item in phrases if item in self.body_text), "")
            return {"risk_text": "challenge-selector" if selector_match else phrase}

        selectors = tuple(argument["challenge_selectors"])
        blocking = tuple(argument["blocking_selectors"])
        assert tuple(argument["blocking_phrases"]) == phrases
        assert "document.body" not in script
        assert '[class*="verify"]' not in script
        assert "hasNormalContent" not in script
        assert "container.innerText" in script
        visibility_checked = "getComputedStyle" in script and "getBoundingClientRect" in script
        wildcard_verify = any("verify" in selector and "*=" in selector for selector in selectors)
        if self.ordinary_class and "verify" in self.ordinary_class and wildcard_verify:
            return {"risk_text": "challenge-selector"}
        if self.hidden_challenge and not visibility_checked:
            return {"risk_text": "challenge-selector"}
        expected = {
            "geetest": ".geetest_panel",
            "captcha": ".captcha",
            "overlay": '[data-testid="challenge-page"]',
        }
        if self.visible_challenge is not None:
            assert expected[self.visible_challenge] in selectors
            return {"risk_text": "challenge-selector"}
        phrase = next((item for item in phrases if item in self.visible_block_text), "")
        if phrase and blocking:
            return {"risk_text": phrase}
        return {"risk_text": ""}


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


def _creator(
    *posts: dict[str, Any],
    since_id: object = None,
    total: object = None,
    ok: object = 1,
    uid: str = "creator",
) -> Response:
    return Response(
        {"ok": ok, "data": {"list": list(posts), "since_id": since_id, "total": total}},
        url=f"https://weibo.com/ajax/statuses/mymblog?{urlencode({'uid': uid})}",
    )


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


def test_creator_parser_restores_safe_public_avatar_and_region_without_signed_parameters() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("safe-public-fields")
    post["region_name"] = "发布于 上海"
    post["user"]["avatar_hd"] = (
        "https://cdn.example.invalid/avatar.jpeg?width=180&token=must-not-leak&expires=123#fragment"
    )

    record = parse_creator_item(post, observed_at="2026-01-01T00:00:00+00:00")

    assert record["region_name"] == "发布于 上海"
    assert record["author_avatar"] == "https://cdn.example.invalid/avatar.jpeg?width=180"
    rendered = json.dumps(record, ensure_ascii=False)
    for forbidden in ("token", "expires", "must-not-leak", "#fragment"):
        assert forbidden not in rendered


def test_creator_parser_rejects_malformed_public_avatar_url() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("malformed-avatar")
    post["user"]["avatar_hd"] = "https://[invalid"

    record = parse_creator_item(post)

    assert record["author_avatar"] is None


def test_creator_parser_accepts_sign_in_public_path_and_tries_avatar_fallbacks() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("avatar-fallback")
    post["user"]["avatar_hd"] = "javascript:alert(1)"
    post["user"]["avatar_large"] = (
        "https://cdn.example.invalid/design-avatar.jpeg?width=180"
    )

    record = parse_creator_item(post)

    assert record["author_avatar"] == (
        "https://cdn.example.invalid/design-avatar.jpeg?width=180"
    )


def test_creator_parser_keeps_only_safe_picture_ids_with_compatibility_alias_and_count() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("pictures")
    post["pic_ids"] = ["pic-1", "bad/id", "pic_2", 7, True, None]

    record = parse_creator_item(post, observed_at="2026-01-01T00:00:00+00:00")

    assert record["pic_ids"] == ["pic-1", "pic_2", "7"]
    assert record["pics"] is None
    assert record["pic_num"] == 3
    assert "bad/id" not in json.dumps(record)


def test_creator_parser_uses_safe_pic_infos_keys_without_leaking_picture_payloads() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("pic-infos")
    post.pop("pic_ids")
    post["pic_infos"] = {
        "pic-1": {
            "largest": {
                "url": "https://cdn.example.invalid/pic-1.jpg?width=720&token=must-not-leak"
            }
        },
        "bad/id": {"token": "must-not-leak"},
    }

    record = parse_creator_item(post, observed_at="2026-01-01T00:00:00+00:00")

    assert record["pic_ids"] == ["pic-1"]
    assert record["pics"] == ["https://cdn.example.invalid/pic-1.jpg?width=720"]
    assert record["pic_num"] == 1
    rendered = json.dumps(record)
    assert "token" not in rendered and "must-not-leak" not in rendered


def test_creator_picture_count_distinguishes_unknown_from_explicit_empty() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    missing = _post("missing-pictures")
    missing.pop("pic_ids")
    explicit_empty = _post("empty-pictures")
    explicit_empty["pic_ids"] = []

    unknown_record = parse_creator_item(missing, observed_at="2026-01-01T00:00:00+00:00")
    empty_record = parse_creator_item(explicit_empty, observed_at="2026-01-01T00:00:00+00:00")

    assert unknown_record["pic_ids"] is None and unknown_record["pics"] is None
    assert unknown_record["pic_num"] is None
    assert empty_record["pic_ids"] == [] and empty_record["pics"] == []
    assert empty_record["pic_num"] == 0


def test_creator_picture_count_keeps_unrecognizable_nonempty_container_unknown() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("invalid-pictures")
    post["pic_ids"] = ["bad/id", True, None]

    record = parse_creator_item(post, observed_at="2026-01-01T00:00:00+00:00")

    assert record["pic_ids"] is None
    assert record["pics"] is None
    assert record["pic_num"] is None


def test_creator_picture_parser_falls_back_to_safe_pic_info_keys() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("picture-fallback")
    post["pic_ids"] = ["bad/id", True]
    post["pic_infos"] = {
        "safe-picture": {
            "large": {
                "url": "https://cdn.example.invalid/safe-picture.jpg?signature=must-not-leak&width=720"
            }
        },
        "also/bad": {"token": "must-not-leak"},
    }

    record = parse_creator_item(post, observed_at="2026-01-01T00:00:00+00:00")

    assert record["pic_ids"] == ["safe-picture"]
    assert record["pics"] == ["https://cdn.example.invalid/safe-picture.jpg?width=720"]
    assert record["pic_num"] == 1
    rendered = json.dumps(record)
    assert "signature" not in rendered and "must-not-leak" not in rendered


@pytest.mark.parametrize("pic_num", (0, 3))
def test_creator_picture_parser_preserves_explicit_safe_picture_count_without_ids(
    pic_num: int,
) -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post(f"picture-count-{pic_num}")
    post.pop("pic_ids")
    post["pic_num"] = pic_num

    record = parse_creator_item(post, observed_at="2026-01-01T00:00:00+00:00")

    assert record["pic_num"] == pic_num
    assert record["pic_ids"] == ([] if pic_num == 0 else None)
    assert record["pics"] == ([] if pic_num == 0 else None)


@pytest.mark.parametrize("pic_num", (True, -1, 1.5, "2"))
def test_creator_picture_parser_rejects_unsafe_picture_counts(pic_num: object) -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_creator_item

    post = _post("invalid-picture-count")
    post.pop("pic_ids")
    post["pic_num"] = pic_num

    record = parse_creator_item(post, observed_at="2026-01-01T00:00:00+00:00")

    assert record["pic_ids"] is None
    assert record["pics"] is None
    assert record["pic_num"] is None


def test_search_picture_fields_remain_unknown_without_dom_evidence() -> None:
    from runtime.media_missher_runtime.platforms.weibo import parse_search_item

    record = parse_search_item(
        {"mid": "search-post", "text": "No image evidence in the search DOM"},
        "term",
        observed_at="2026-01-01T00:00:00+00:00",
    )

    assert record["pic_ids"] is None
    assert record["pics"] is None
    assert record["pic_num"] is None


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

    page = Page(responses=[_creator(_post("one"), _post("two"), since_id="next", total=2, uid="a b")])
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
        response = Response(
            None,
            status=status,
            url="https://weibo.com/ajax/statuses/mymblog?uid=x",
            json_error=AssertionError("must not parse JSON"),
        )
        with pytest.raises(CollectionStopped, match=f"http-{status}"):
            _run(collect_creator(CollectionRequest(platform="weibo", count=1, uid="x"), Browser(Page(responses=[response]))))
        assert response.json_calls == 0
    for payload in (
        _creator(_post("one"), ok=0, uid="x"),
        Response({"code": 461}, url="https://weibo.com/ajax/statuses/mymblog?uid=x"),
        Response(
            {"ok": 1, "data": {"list": [_post("one")], "since_id": "same"}},
            url="https://weibo.com/ajax/statuses/mymblog?uid=x",
        ),
    ):
        page = Page(responses=[payload, _creator(_post("two"), since_id="same", uid="x")])
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
    assert page.waits[0][1]["blocking_phrases"] == ["请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控", "安全验证", "验证码"]


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


@pytest.mark.parametrize("phrase", ("风控", "验证码", "安全验证", "账号异常"))
def test_ordinary_page_text_is_not_a_challenge(phrase: str) -> None:
    from runtime.media_missher_runtime.platforms.weibo import _raise_for_page_challenge

    page = ChallengeDomPage(body_text=f"普通博文讨论{phrase}流程")

    _run(_raise_for_page_challenge(page))


@pytest.mark.parametrize(
    "page",
    (
        ChallengeDomPage(ordinary_class="author_verify_badge"),
        ChallengeDomPage(hidden_challenge=True),
    ),
    ids=("ordinary-_verify_-badge", "hidden-challenge"),
)
def test_ordinary_verify_badge_and_hidden_challenge_nodes_do_not_stop(page: ChallengeDomPage) -> None:
    from runtime.media_missher_runtime.platforms.weibo import _raise_for_page_challenge

    _run(_raise_for_page_challenge(page))


@pytest.mark.parametrize("kind", ("geetest", "captcha", "overlay"))
def test_visible_explicit_challenge_nodes_still_stop(kind: str) -> None:
    from runtime.media_missher_runtime.platforms.weibo import CollectionStopped, _raise_for_page_challenge

    with pytest.raises(CollectionStopped, match="challenge-selector"):
        _run(_raise_for_page_challenge(ChallengeDomPage(visible_challenge=kind)))


def test_visible_blocking_phrase_stops_collection() -> None:
    from runtime.media_missher_runtime.platforms.weibo import CollectionStopped, _raise_for_page_challenge

    with pytest.raises(CollectionStopped, match="访问受限"):
        _run(_raise_for_page_challenge(ChallengeDomPage(visible_block_text="访问受限")))


@pytest.mark.enable_socket
def test_challenge_probe_uses_real_offline_dom_visibility() -> None:
    async_api = pytest.importorskip("playwright.async_api")
    configured = os.environ.get("MEDIA_MISSHER_TEST_BROWSER")
    executable = Path(configured) if configured else Path(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    if not executable.is_file():
        discovered = shutil.which("google-chrome") or shutil.which("chromium")
        if discovered is None:
            pytest.skip("an installed local Chromium browser is required")
        executable = Path(discovered)

    from runtime.media_missher_runtime.platforms.weibo import (
        CollectionStopped,
        _raise_for_page_challenge,
    )

    async def exercise() -> None:
        async with async_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                executable_path=str(executable), headless=True
            )
            page = await browser.new_page(viewport={"width": 800, "height": 600})
            await page.route("**/*", lambda route: route.abort())

            async def stopped(html: str) -> bool:
                await page.set_content(html)
                try:
                    await _raise_for_page_challenge(page)
                except CollectionStopped:
                    return True
                return False

            box = "position:fixed;left:20px;top:20px;width:80px;height:40px"
            observed = {}
            observed["ordinary"] = await stopped(
                f'<article class="author_verify_badge" style="{box}">普通正文讨论风控和验证码</article>'
            )
            observed["blocking-with-feed"] = await stopped(
                f'<article style="{box}">正常 feed</article>'
                f'<div class="error-page" style="{box}">访问受限</div>'
            )
            observed["visible-challenge"] = await stopped(
                f'<div class="geetest_panel" style="{box}">验证</div>'
            )

            hidden_ancestors = (
                ("hidden-parent", "hidden"),
                ("display-none-parent", 'style="display:none"'),
                ("visibility-hidden-parent", 'style="visibility:hidden"'),
                ("transparent-parent", 'style="opacity:0"'),
                ("aria-hidden-parent", 'aria-hidden="true"'),
            )
            for name, ancestor in hidden_ancestors:
                observed[name] = await stopped(
                    f'<div {ancestor}><div class="geetest_panel" style="{box}">验证</div></div>'
                )
            observed["offscreen"] = await stopped(
                '<div class="geetest_panel" '
                'style="position:absolute;left:20px;top:-1000px;width:80px;height:40px">验证</div>'
            )
            await browser.close()
            assert observed == {
                "ordinary": False,
                "blocking-with-feed": True,
                "visible-challenge": True,
                "hidden-parent": False,
                "display-none-parent": False,
                "visibility-hidden-parent": False,
                "transparent-parent": False,
                "aria-hidden-parent": False,
                "offscreen": False,
            }

    asyncio.run(exercise())
