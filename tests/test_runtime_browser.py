from __future__ import annotations

from dataclasses import dataclass

import pytest


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
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.cdp_url: str | None = None

    async def connect_over_cdp(self, url: str) -> FakeBrowser:
        self.cdp_url = url
        return self.browser


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = FakeChromium(browser)
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


@pytest.mark.asyncio
async def test_connect_uses_existing_cdp_browser_without_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.media_missher_runtime import browser as module

    fake_browser = FakeBrowser([FakePage("https://www.bilibili.com/")])
    fake_playwright = FakePlaywright(fake_browser)
    factory = FakeAsyncPlaywright(fake_playwright)
    monkeypatch.setattr(module, "async_playwright", lambda: factory)

    session = await module.BrowserSession.connect("http://127.0.0.1:9222")

    assert factory.started is True
    assert fake_playwright.chromium.cdp_url == "http://127.0.0.1:9222"
    assert session.require_page("bilibili") is fake_browser.contexts[0].pages[0]


@pytest.mark.asyncio
async def test_require_page_demands_an_open_authenticated_platform_page() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    session = BrowserSession(FakePlaywright(FakeBrowser([FakePage("https://example.test/")])), FakeBrowser([]))

    with pytest.raises(PreconditionError, match="open/authenticated"):
        session.require_page("weibo")


@pytest.mark.asyncio
async def test_page_json_stays_on_the_selected_origin_and_returns_only_json() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    page = FakePage("https://www.douyin.com/feed", {"status": 200, "json": {"zero": 0, "null": None}})
    session = BrowserSession(FakePlaywright(FakeBrowser([page])), FakeBrowser([page]))

    response = await session.page_json(page, "https://www.douyin.com/api/item")

    assert response.status == 200
    assert response.payload == {"zero": 0, "null": None}
    assert "fetch" in (page.evaluated or "")
    with pytest.raises(PreconditionError, match="origin"):
        await session.page_json(page, "https://example.test/api")


@pytest.mark.asyncio
async def test_close_disconnects_without_closing_any_page_or_context() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    page = FakePage("https://weibo.com/")
    remote = FakeBrowser([page])
    playwright = FakePlaywright(remote)
    session = BrowserSession(playwright, remote)

    await session.close()

    assert remote.closed is True
    assert playwright.stopped is True
    assert page.url == "https://weibo.com/"
