from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Coroutine

import pytest


def _run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fake coroutine unexpectedly suspended")


@dataclass
class FakePage:
    url: str
    result: object = None
    evaluated: str | None = None
    evaluated_argument: object = None

    async def evaluate(self, script: str, argument: object = None) -> object:
        self.evaluated = script
        self.evaluated_argument = argument
        return self.result


@dataclass
class FakeContext:
    pages: list[FakePage]


class FakeBrowser:
    def __init__(self, pages: list[FakePage]) -> None:
        self.contexts = [FakeContext(pages)]
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser, failure: BaseException | None = None) -> None:
        self.browser = browser
        self.failure = failure
        self.cdp_url: str | None = None

    async def connect_over_cdp(self, url: str) -> FakeBrowser:
        self.cdp_url = url
        if self.failure is not None:
            raise self.failure
        return self.browser


class FakePlaywright:
    def __init__(self, browser: FakeBrowser, failure: BaseException | None = None) -> None:
        self.chromium = FakeChromium(browser, failure)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class FakeAsyncPlaywright:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright
        self.started = False

    async def start(self) -> FakePlaywright:
        self.started = True
        return self.playwright


def test_connect_uses_existing_cdp_browser_without_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.media_missher_runtime import browser as module

    fake_browser = FakeBrowser([FakePage("https://www.bilibili.com/")])
    fake_playwright = FakePlaywright(fake_browser)
    factory = FakeAsyncPlaywright(fake_playwright)
    monkeypatch.setattr(module, "async_playwright", lambda: factory)

    session = _run(module.BrowserSession.connect("http://127.0.0.1:9222"))

    assert factory.started is True
    assert fake_playwright.chromium.cdp_url == "http://127.0.0.1:9222"
    assert session.require_page("bilibili") is fake_browser.contexts[0].pages[0]


def test_connect_stops_playwright_and_preserves_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.media_missher_runtime import browser as module

    failure = asyncio.CancelledError("cancelled")
    fake_playwright = FakePlaywright(FakeBrowser([]), failure)
    factory = FakeAsyncPlaywright(fake_playwright)
    monkeypatch.setattr(module, "async_playwright", lambda: factory)

    with pytest.raises(asyncio.CancelledError) as caught:
        _run(module.BrowserSession.connect("http://127.0.0.1:9222"))

    assert caught.value is failure
    assert fake_playwright.stopped is True


def test_require_page_demands_an_open_authenticated_platform_page() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    session = BrowserSession(FakePlaywright(FakeBrowser([FakePage("https://example.test/")])), FakeBrowser([]))

    with pytest.raises(PreconditionError, match="open/authenticated"):
        session.require_page("weibo")


def test_page_json_stays_on_the_selected_origin_and_returns_only_json() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    page = FakePage("https://www.douyin.com/feed", {"status": 200, "json": {"zero": 0, "null": None}})
    session = BrowserSession(FakePlaywright(FakeBrowser([page])), FakeBrowser([page]))

    response = _run(session.page_json(page, "https://www.douyin.com/api/item"))

    assert response.status == 200
    assert response.payload == {"zero": 0, "null": None}
    assert "fetch" in (page.evaluated or "")
    with pytest.raises(PreconditionError, match="origin"):
        _run(session.page_json(page, "https://example.test/api"))


def test_close_disconnects_without_closing_any_page_or_context() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    page = FakePage("https://weibo.com/")
    remote = FakeBrowser([page])
    playwright = FakePlaywright(remote)
    session = BrowserSession(playwright, remote)

    _run(session.close())

    assert remote.closed is False
    assert playwright.stopped is True
    assert page.url == "https://weibo.com/"


def test_navigation_requires_explicit_opt_in_and_an_exact_allowlisted_host() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    class NavigationPage:
        url = "https://www.bilibili.com/"

        def __init__(self) -> None:
            self.gotos: list[str] = []

        async def goto(self, url: str, **kwargs: object) -> str:
            self.gotos.append(url)
            return url

    page = NavigationPage()
    disabled = BrowserSession(FakePlaywright(FakeBrowser([])), FakeBrowser([]))
    with pytest.raises(PreconditionError, match="authorized"):
        _run(disabled.navigate(page, "https://space.bilibili.com/synthetic/dynamic", allowed_hosts=("space.bilibili.com",)))

    enabled = BrowserSession(FakePlaywright(FakeBrowser([])), FakeBrowser([]), allow_navigation=True)
    assert _run(enabled.navigate(page, "https://space.bilibili.com/synthetic/dynamic", allowed_hosts=("space.bilibili.com",))) == "https://space.bilibili.com/synthetic/dynamic"
    with pytest.raises(PreconditionError, match="exact allowlisted"):
        _run(enabled.navigate(page, "https://space.bilibili.com.invalid/synthetic", allowed_hosts=("space.bilibili.com",)))
    assert page.gotos == ["https://space.bilibili.com/synthetic/dynamic"]


@pytest.mark.parametrize(
    ("platform", "login_url"),
    [
        ("bilibili", "https://www.bilibili.com/login"),
        ("xhs", "https://www.xiaohongshu.com/login"),
        ("douyin", "https://www.douyin.com/login"),
        ("weibo", "https://weibo.com/login.php"),
    ],
)
def test_authenticated_page_check_rejects_same_host_login_urls(
    platform: str, login_url: str
) -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    page = FakePage(login_url, False)
    remote = FakeBrowser([page])
    session = BrowserSession(FakePlaywright(remote), remote)

    with pytest.raises(PreconditionError, match="logged out"):
        _run(session.require_authenticated_page(platform))

    assert page.evaluated is None


@pytest.mark.parametrize(
    ("platform", "page_url", "expected_selector"),
    [
        ("bilibili", "https://space.bilibili.com/1/dynamic", ".header-login-entry"),
        ("xhs", "https://www.xiaohongshu.com/explore", ".login-container"),
        ("douyin", "https://www.douyin.com/user/creator", "[data-e2e='login-button']"),
        ("weibo", "https://weibo.com/u/1", "[node-type='loginBtn']"),
    ],
)
def test_authenticated_page_check_rejects_explicit_visible_logged_out_markers(
    platform: str, page_url: str, expected_selector: str
) -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    page = FakePage(page_url, True)
    remote = FakeBrowser([page])
    session = BrowserSession(FakePlaywright(remote), remote)

    with pytest.raises(PreconditionError, match="logged out"):
        _run(session.require_authenticated_page(platform))

    assert expected_selector in page.evaluated_argument["selectors"]
    evaluated = page.evaluated or ""
    assert "cookie" not in evaluated.lower()
    assert "localstorage" not in evaluated.lower()
    assert "sessionstorage" not in evaluated.lower()


@pytest.mark.parametrize(
    ("platform", "page_url"),
    [
        ("bilibili", "https://space.bilibili.com/1/dynamic"),
        ("xhs", "https://www.xiaohongshu.com/explore"),
        ("douyin", "https://www.douyin.com/user/creator"),
        ("weibo", "https://weibo.com/u/1"),
    ],
)
def test_authenticated_page_check_accepts_platform_pages_without_logged_out_markers(
    platform: str, page_url: str
) -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    page = FakePage(page_url, False)
    remote = FakeBrowser([page])
    session = BrowserSession(FakePlaywright(remote), remote)

    assert _run(session.require_authenticated_page(platform)) is page
