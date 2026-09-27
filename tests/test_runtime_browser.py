from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
    waits: list[float] = field(default_factory=list)

    async def evaluate(self, script: str, argument: object = None) -> object:
        self.evaluated = script
        self.evaluated_argument = argument
        return self.result

    async def wait_for_timeout(self, milliseconds: float) -> None:
        self.waits.append(milliseconds)


@dataclass
class FakeResponse:
    status: int


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


def test_require_page_fails_closed_when_platform_tabs_are_ambiguous() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    remote = FakeBrowser(
        [
            FakePage("https://www.xiaohongshu.com/explore/one"),
            FakePage("https://www.xiaohongshu.com/explore/two"),
        ]
    )
    session = BrowserSession(FakePlaywright(remote), remote)

    with pytest.raises(PreconditionError, match="ambiguous"):
        session.require_page("xhs")


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


def test_close_releases_owned_pages_before_playwright_without_closing_browser() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession
    events: list[str] = []

    class TemporaryPage:
        def is_closed(self) -> bool:
            return False

        async def close(self) -> None:
            events.append("page")

    class Playwright(FakePlaywright):
        async def stop(self) -> None:
            events.append("playwright")

    remote = FakeBrowser([])
    session = BrowserSession(Playwright(remote), remote)
    session._temporary_pages.append(TemporaryPage())
    _run(session.close())
    assert events == ["page", "playwright"]
    assert not remote.closed
    assert session._temporary_pages == []


@pytest.mark.parametrize("failure", [RuntimeError("page close failed"), asyncio.CancelledError()])
def test_close_continues_owned_cleanup_and_propagates_first_failure(failure) -> None:
    from runtime.media_missher_runtime.browser import BrowserSession
    events: list[str] = []

    class TemporaryPage:
        def __init__(self, name, error=None):
            self.name, self.error = name, error

        def is_closed(self) -> bool:
            return False

        async def close(self) -> None:
            events.append(self.name)
            if self.error is not None:
                raise self.error

    remote = FakeBrowser([])
    playwright = FakePlaywright(remote)
    session = BrowserSession(playwright, remote)
    session._temporary_pages.extend([TemporaryPage("remaining"), TemporaryPage("failed", failure)])
    with pytest.raises(type(failure)) as captured:
        _run(session.close())
    assert captured.value is failure
    assert events == ["failed", "remaining"]
    assert playwright.stopped
    assert not remote.closed
    assert session._temporary_pages == []


def test_release_temporary_page_immediately_closes_and_untracks_only_owned_page() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    class Page:
        def __init__(self) -> None:
            self.closed = False

        def is_closed(self) -> bool:
            return self.closed

        async def close(self) -> None:
            self.closed = True

    remote = FakeBrowser([])
    session = BrowserSession(FakePlaywright(remote), remote)
    owned = Page()
    existing = Page()
    session._register_temporary_page(owned)

    _run(session._release_temporary_page(existing))
    assert existing.closed is False
    _run(session._release_temporary_page(owned))

    assert owned.closed is True
    assert session._temporary_pages == []


def test_authorized_authentication_uses_and_closes_only_a_temporary_platform_page() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    class TemporaryPage(FakePage):
        def __init__(self) -> None:
            super().__init__(
                "about:blank",
                {"logged_out": False, "challenge": False, "ready": True},
            )
            self.gotos: list[tuple[str, object]] = []
            self.closed = False

        async def goto(self, url: str, **kwargs: object) -> object:
            self.gotos.append((url, kwargs.get("wait_until")))
            self.url = url
            return FakeResponse(200)

        async def close(self) -> None:
            self.closed = True

        def is_closed(self) -> bool:
            return self.closed

    class TemporaryContext(FakeContext):
        def __init__(self, pages: list[FakePage]) -> None:
            super().__init__(pages)
            self.created: list[TemporaryPage] = []

        async def new_page(self) -> TemporaryPage:
            page = TemporaryPage()
            self.pages.append(page)
            self.created.append(page)
            return page

    existing = FakePage("https://www.bilibili.com/video/existing", False)
    context = TemporaryContext([existing])
    remote = FakeBrowser([])
    remote.contexts = [context]
    playwright = FakePlaywright(remote)
    session = BrowserSession(playwright, remote, allow_navigation=True)

    prepared = _run(session.require_authenticated_page("bilibili"))

    assert prepared is context.created[0]
    assert session.require_page("bilibili") is prepared
    assert context.created[0].gotos == [
        ("https://www.bilibili.com/", "domcontentloaded")
    ]

    _run(session.close())

    assert context.created[0].closed is True
    assert existing.url == "https://www.bilibili.com/video/existing"
    assert playwright.stopped is True


def test_authorized_entry_navigation_timeout_is_a_platform_precondition() -> None:
    from runtime.media_missher_runtime import browser as module

    class TimeoutPage(FakePage):
        def __init__(self) -> None:
            super().__init__("about:blank")
            self.closed = False

        async def goto(self, url: str, **kwargs: object) -> object:
            assert kwargs.get("wait_until") == "domcontentloaded"
            raise module.PlaywrightTimeoutError("synthetic entry timeout")

        async def close(self) -> None:
            self.closed = True

        def is_closed(self) -> bool:
            return self.closed

    class Context:
        def __init__(self) -> None:
            self.pages: list[TimeoutPage] = []

        async def new_page(self) -> TimeoutPage:
            page = TimeoutPage()
            self.pages.append(page)
            return page

    context = Context()
    remote = FakeBrowser([])
    remote.contexts = [context]
    session = module.BrowserSession(
        FakePlaywright(remote), remote, allow_navigation=True
    )

    with pytest.raises(module.PreconditionError, match="entry navigation timed out"):
        _run(session.require_authenticated_page("douyin"))

    _run(session.close())
    assert context.pages[0].closed is True


def test_authorized_temporary_page_is_cleaned_up_when_authentication_fails() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    class LoggedOutPage(FakePage):
        def __init__(self) -> None:
            super().__init__(
                "about:blank",
                {"logged_out": True, "challenge": False, "ready": True},
            )
            self.closed = False

        async def goto(self, url: str, **_kwargs: object) -> object:
            self.url = url
            return FakeResponse(200)

        async def close(self) -> None:
            self.closed = True

    class Context:
        def __init__(self) -> None:
            self.pages: list[LoggedOutPage] = []

        async def new_page(self) -> LoggedOutPage:
            page = LoggedOutPage()
            self.pages.append(page)
            return page

    context = Context()
    remote = FakeBrowser([])
    remote.contexts = [context]
    playwright = FakePlaywright(remote)
    session = BrowserSession(playwright, remote, allow_navigation=True)

    with pytest.raises(PreconditionError, match="logged out"):
        _run(session.require_authenticated_page("xhs"))

    _run(session.close())

    assert context.pages[0].closed is True
    assert playwright.stopped is True


def test_authorized_page_uses_the_unique_context_that_already_has_the_platform() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    class TemporaryPage(FakePage):
        def __init__(self) -> None:
            super().__init__(
                "about:blank",
                {"logged_out": False, "challenge": False, "ready": True},
            )

        async def goto(self, url: str, **_kwargs: object) -> FakeResponse:
            self.url = url
            return FakeResponse(200)

        async def close(self) -> None:
            return None

    class Context(FakeContext):
        def __init__(self, pages: list[FakePage]) -> None:
            super().__init__(pages)
            self.created: list[TemporaryPage] = []

        async def new_page(self) -> TemporaryPage:
            page = TemporaryPage()
            self.pages.append(page)
            self.created.append(page)
            return page

    unrelated = Context([FakePage("https://example.test/")])
    authenticated = Context(
        [
            FakePage(
                "https://weibo.com/u/private",
                {"logged_out": False, "challenge": False, "ready": True},
            )
        ]
    )
    remote = FakeBrowser([])
    remote.contexts = [unrelated, authenticated]
    session = BrowserSession(FakePlaywright(remote), remote, allow_navigation=True)

    prepared = _run(session.require_authenticated_page("weibo"))

    assert unrelated.created == []
    assert authenticated.created == [prepared]


def test_authorized_page_fails_closed_when_multiple_contexts_are_ambiguous() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    class Context(FakeContext):
        async def new_page(self) -> FakePage:
            raise AssertionError("an ambiguous context must not be selected")

    remote = FakeBrowser([])
    remote.contexts = [
        Context([FakePage("https://one.example/")]),
        Context([FakePage("https://two.example/")]),
    ]
    session = BrowserSession(FakePlaywright(remote), remote, allow_navigation=True)

    with pytest.raises(PreconditionError, match="ambiguous"):
        _run(session.require_authenticated_page("xhs"))


def test_close_attempts_every_temporary_page_and_preserves_cancellation() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    cancellation = asyncio.CancelledError("cancelled cleanup")

    class ClosingPage:
        def __init__(self, failure: BaseException | None = None) -> None:
            self.failure = failure
            self.attempted = False

        async def close(self) -> None:
            self.attempted = True
            if self.failure is not None:
                raise self.failure

        def is_closed(self) -> bool:
            return False

    remaining = ClosingPage()
    cancelled = ClosingPage(cancellation)
    remote = FakeBrowser([])
    playwright = FakePlaywright(remote)
    session = BrowserSession(playwright, remote, allow_navigation=True)
    session._temporary_pages.extend([remaining, cancelled])

    with pytest.raises(asyncio.CancelledError) as caught:
        _run(session.close())

    assert caught.value is cancellation
    assert cancelled.attempted is True
    assert remaining.attempted is True
    assert playwright.stopped is True


def test_close_attempts_every_temporary_page_and_preserves_cleanup_error() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    failure = RuntimeError("close failed")

    class ClosingPage:
        def __init__(self, error: BaseException | None = None) -> None:
            self.error = error
            self.attempted = False

        async def close(self) -> None:
            self.attempted = True
            if self.error is not None:
                raise self.error

        def is_closed(self) -> bool:
            return False

    remaining = ClosingPage()
    failed = ClosingPage(failure)
    remote = FakeBrowser([])
    playwright = FakePlaywright(remote)
    session = BrowserSession(playwright, remote, allow_navigation=True)
    session._temporary_pages.extend([remaining, failed])

    with pytest.raises(RuntimeError) as caught:
        _run(session.close())

    assert caught.value is failure
    assert failed.attempted is True
    assert remaining.attempted is True
    assert playwright.stopped is True


def test_authorized_authentication_detects_a_delayed_logged_out_marker() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    class DelayedPage(FakePage):
        def __init__(self) -> None:
            super().__init__("about:blank")
            self.observations = [
                {"logged_out": False, "challenge": False, "ready": True},
                {"logged_out": False, "challenge": False, "ready": True},
                {"logged_out": True, "challenge": False, "ready": True},
            ]

        async def goto(self, url: str, **_kwargs: object) -> FakeResponse:
            self.url = url
            return FakeResponse(200)

        async def evaluate(self, script: str, argument: object = None) -> object:
            self.evaluated = script
            self.evaluated_argument = argument
            return self.observations.pop(0)

        async def close(self) -> None:
            return None

    class Context:
        def __init__(self) -> None:
            self.pages: list[DelayedPage] = []

        async def new_page(self) -> DelayedPage:
            page = DelayedPage()
            self.pages.append(page)
            return page

    context = Context()
    remote = FakeBrowser([])
    remote.contexts = [context]
    session = BrowserSession(FakePlaywright(remote), remote, allow_navigation=True)

    with pytest.raises(PreconditionError, match="logged out"):
        _run(session.require_authenticated_page("douyin"))

    assert context.pages[0].waits == [250, 250]


@pytest.mark.parametrize(
    "redirect_url",
    [
        "https://passport.example.test/login",
        "https://www.douyin.com/login",
    ],
)
def test_authorized_authentication_rejects_a_delayed_redirect(
    redirect_url: str,
) -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    class RedirectingPage(FakePage):
        def __init__(self) -> None:
            super().__init__(
                "about:blank",
                {"logged_out": False, "challenge": False, "ready": True},
            )

        async def goto(self, url: str, **_kwargs: object) -> FakeResponse:
            self.url = url
            return FakeResponse(200)

        async def wait_for_timeout(self, milliseconds: float) -> None:
            await super().wait_for_timeout(milliseconds)
            self.url = redirect_url

        async def close(self) -> None:
            return None

    class Context:
        def __init__(self) -> None:
            self.pages: list[RedirectingPage] = []

        async def new_page(self) -> RedirectingPage:
            page = RedirectingPage()
            self.pages.append(page)
            return page

    context = Context()
    remote = FakeBrowser([])
    remote.contexts = [context]
    session = BrowserSession(FakePlaywright(remote), remote, allow_navigation=True)

    with pytest.raises(PreconditionError):
        _run(session.require_authenticated_page("douyin"))

    assert context.pages[0].waits == [250]


def test_authentication_probe_does_not_scan_normal_content_text_for_risk_phrases() -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    page = FakePage(
        "https://www.xiaohongshu.com/explore",
        {"logged_out": False, "challenge": False, "ready": True},
    )
    remote = FakeBrowser([page])
    session = BrowserSession(FakePlaywright(remote), remote)

    assert _run(session.require_authenticated_page("xhs")) is page

    evaluated = page.evaluated or ""
    assert "document.title" not in evaluated
    assert "document.body?.innerText" not in evaluated
    assert "bodyText" not in evaluated
    assert "challenge_phrases" not in evaluated
    assert "challenge_phrases" not in page.evaluated_argument


@pytest.mark.parametrize("status", [403, 429])
def test_authorized_authentication_classifies_entry_risk_statuses(status: int) -> None:
    from runtime.media_missher_runtime.browser import BrowserRiskError, BrowserSession

    class RiskPage(FakePage):
        def __init__(self) -> None:
            super().__init__("about:blank")

        async def goto(self, url: str, **_kwargs: object) -> FakeResponse:
            self.url = url
            return FakeResponse(status)

        async def close(self) -> None:
            return None

    class Context:
        def __init__(self) -> None:
            self.pages: list[RiskPage] = []

        async def new_page(self) -> RiskPage:
            page = RiskPage()
            self.pages.append(page)
            return page

    context = Context()
    remote = FakeBrowser([])
    remote.contexts = [context]
    session = BrowserSession(FakePlaywright(remote), remote, allow_navigation=True)

    with pytest.raises(BrowserRiskError) as caught:
        _run(session.require_authenticated_page("bilibili"))

    assert caught.value.code == f"http-{status}"


def test_authorized_authentication_classifies_a_visible_challenge() -> None:
    from runtime.media_missher_runtime.browser import BrowserRiskError, BrowserSession

    class ChallengePage(FakePage):
        def __init__(self) -> None:
            super().__init__(
                "about:blank",
                {"logged_out": False, "challenge": True, "ready": True},
            )

        async def goto(self, url: str, **_kwargs: object) -> FakeResponse:
            self.url = url
            return FakeResponse(200)

        async def close(self) -> None:
            return None

    class Context:
        def __init__(self) -> None:
            self.pages: list[ChallengePage] = []

        async def new_page(self) -> ChallengePage:
            page = ChallengePage()
            self.pages.append(page)
            return page

    context = Context()
    remote = FakeBrowser([])
    remote.contexts = [context]
    session = BrowserSession(FakePlaywright(remote), remote, allow_navigation=True)

    with pytest.raises(BrowserRiskError) as caught:
        _run(session.require_authenticated_page("xhs"))

    assert caught.value.code == "challenge"
    assert context.pages[0].waits == []


@pytest.mark.parametrize("status", [None, 500])
def test_authorized_authentication_rejects_unsuccessful_entry_navigation(
    status: int | None,
) -> None:
    from runtime.media_missher_runtime.browser import BrowserSession, PreconditionError

    class FailedPage(FakePage):
        def __init__(self) -> None:
            super().__init__("about:blank")

        async def goto(self, url: str, **_kwargs: object) -> FakeResponse | None:
            self.url = url
            return FakeResponse(status) if status is not None else None

        async def close(self) -> None:
            return None

    class Context:
        def __init__(self) -> None:
            self.pages: list[FailedPage] = []

        async def new_page(self) -> FailedPage:
            page = FailedPage()
            self.pages.append(page)
            return page

    context = Context()
    remote = FakeBrowser([])
    remote.contexts = [context]
    session = BrowserSession(FakePlaywright(remote), remote, allow_navigation=True)

    with pytest.raises(PreconditionError, match="navigation"):
        _run(session.require_authenticated_page("weibo"))


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

    page = FakePage(
        login_url,
        {"logged_out": False, "challenge": False, "ready": True},
    )
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

    page = FakePage(
        page_url,
        {"logged_out": True, "challenge": False, "ready": True},
    )
    remote = FakeBrowser([page])
    session = BrowserSession(FakePlaywright(remote), remote)

    with pytest.raises(PreconditionError, match="logged out"):
        _run(session.require_authenticated_page(platform))

    assert expected_selector in page.evaluated_argument["logged_out_selectors"]
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

    page = FakePage(
        page_url,
        {"logged_out": False, "challenge": False, "ready": True},
    )
    remote = FakeBrowser([page])
    session = BrowserSession(FakePlaywright(remote), remote)

    assert _run(session.require_authenticated_page(platform)) is page
