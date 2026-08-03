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

    async def evaluate(self, script: str, url: str) -> object:
        self.evaluated = script
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
