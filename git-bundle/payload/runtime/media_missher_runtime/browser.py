from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .page_risk import risk_probe_function


try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - exercised when a real browser is configured
    async_playwright = None
    PlaywrightTimeoutError = TimeoutError


_HOSTS = {
    "x": frozenset({"x.com", "www.x.com", "twitter.com", "www.twitter.com"}),
    "bilibili": frozenset({"bilibili.com", "www.bilibili.com", "space.bilibili.com", "search.bilibili.com", "api.bilibili.com", "t.bilibili.com"}),
    "xhs": frozenset({"xiaohongshu.com", "www.xiaohongshu.com"}),
    "douyin": frozenset({"douyin.com", "www.douyin.com"}),
    "weibo": frozenset({"weibo.com", "www.weibo.com", "s.weibo.com"}),
}
_ENTRY_URLS = {
    "x": "https://x.com/home",
    "bilibili": "https://www.bilibili.com/",
    "xhs": "https://www.xiaohongshu.com/explore",
    "douyin": "https://www.douyin.com/",
    "weibo": "https://weibo.com/",
}
_LOGGED_OUT_SELECTORS = {
    "x": ('[data-testid="loginButton"]', '[data-testid="LoginForm_Login_Button"]', 'a[href="/login"]'),
    "bilibili": (
        ".header-login-entry",
        ".login-panel-popover",
        "[class*='login-entry']",
    ),
    "xhs": (
        ".login-container",
        ".login-btn",
        "[class*='login-container']",
    ),
    "douyin": (
        "[data-e2e='login-button']",
        "[data-e2e='login-panel']",
        "[class*='login-button']",
    ),
    "weibo": (
        "[node-type='loginBtn']",
        ".gn_login",
        "[action-type='login']",
    ),
}
_LOGIN_PATH_SEGMENTS = frozenset(
    {"login", "login.php", "signin", "signin.php", "passport"}
)
_RISK_HTTP_STATUSES = frozenset({403, 429})
_AUTH_SETTLE_ATTEMPTS = 5
_AUTH_SETTLE_DELAY_MS = 250


class PreconditionError(RuntimeError):
    """Raised when the user has not prepared an authenticated browser page."""


def publish_accepted(browser: Any, platform: str, records: Sequence[dict[str, Any]]) -> None:
    publisher = getattr(browser, "publish_progress", None)
    if publisher is not None:
        publisher(platform, [dict(record) for record in records])


class BrowserRiskError(RuntimeError):
    """Raised when platform preparation observes a non-retryable risk signal."""

    def __init__(self, code: str) -> None:
        if code not in {"http-403", "http-429", "challenge"}:
            raise ValueError("invalid browser risk code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PageJson:
    status: int
    payload: Any


@dataclass(slots=True)
class BrowserSession:
    _playwright: Any
    _browser: Any
    allow_navigation: bool = False
    _prepared_pages: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _temporary_pages: list[Any] = field(default_factory=list, init=False, repr=False)
    detail_open: Any = field(init=False, repr=False)
    screenshots: Any = field(default=None, init=False, repr=False)
    progress_callback: Any = field(default=None, init=False, repr=False)
    last_pages: int = field(default=0, init=False)
    last_exhausted: bool = field(default=False, init=False)
    last_stop_reason: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        from .detail_open import DetailOpenCoordinator

        self.detail_open = DetailOpenCoordinator(
            register_temporary_page=self._register_temporary_page,
            release_temporary_page=self._release_temporary_page,
        )

    @classmethod
    async def connect(
        cls,
        cdp_url: str,
        *,
        allow_navigation: bool = False,
        browser_assist: str = "off",
    ) -> "BrowserSession":
        if browser_assist != "off":
            raise ValueError("backend-retired-browserskill")
        factory = async_playwright
        if factory is None:
            from playwright.async_api import async_playwright as factory
        playwright = await factory().start()
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
        except BaseException:
            try:
                await playwright.stop()
            except BaseException:
                pass
            raise
        return cls(playwright, browser, allow_navigation=allow_navigation)

    def _register_temporary_page(self, page: Any) -> None:
        if not any(page is candidate for candidate in self._temporary_pages):
            self._temporary_pages.append(page)

    async def _release_temporary_page(self, page: Any) -> None:
        if not any(page is candidate for candidate in self._temporary_pages):
            return
        if not _page_is_closed(page):
            await page.close()
        self._temporary_pages = [
            candidate for candidate in self._temporary_pages if candidate is not page
        ]
        self._prepared_pages = {
            platform: candidate
            for platform, candidate in self._prepared_pages.items()
            if candidate is not page
        }

    def bind_store(self, store: Any) -> None:
        from .screenshots import EvidenceScreenshot

        self.screenshots = EvidenceScreenshot(store)

    def bind_progress(self, callback: Any) -> None:
        self.progress_callback = callback

    def publish_progress(
        self, platform: str, records: list[dict[str, Any]]
    ) -> None:
        if self.progress_callback is not None:
            self.progress_callback(platform, records)

    def require_page(self, platform: str) -> Any:
        hosts = _HOSTS.get(platform)
        if hosts is None:
            raise ValueError("unsupported platform")
        prepared = self._prepared_pages.get(platform)
        if prepared is not None and not _page_is_closed(prepared):
            _validate_platform_location(platform, prepared)
            return prepared
        self._prepared_pages.pop(platform, None)
        matches: list[Any] = []
        for context in self._browser.contexts:
            for page in context.pages:
                if urlparse(page.url).hostname in hosts:
                    matches.append(page)
        if len(matches) > 1:
            raise PreconditionError(f"open/authenticated {platform} page is ambiguous")
        if matches:
            return matches[0]
        raise PreconditionError(f"Open/authenticated {platform} page is required".lower())

    async def require_authenticated_page(self, platform: str) -> Any:
        """Return an open platform page unless it is clearly logged out."""
        if platform not in _HOSTS:
            raise ValueError("unsupported platform")
        prepared = self._prepared_pages.get(platform)
        page = (
            await self._open_temporary_platform_page(platform)
            if self.allow_navigation
            and (prepared is None or _page_is_closed(prepared))
            else self.require_page(platform)
        )
        _validate_platform_location(platform, page)
        temporary = any(page is candidate for candidate in self._temporary_pages)
        attempts = _AUTH_SETTLE_ATTEMPTS if temporary else 1
        ready = False
        for attempt in range(attempts):
            _validate_platform_location(platform, page)
            observation = await _authentication_observation(page, platform)
            _validate_platform_location(platform, page)
            if observation["challenge"]:
                raise BrowserRiskError("challenge")
            if observation["logged_out"]:
                raise PreconditionError(f"{platform} page is clearly logged out")
            ready = observation["ready"]
            if attempt + 1 < attempts:
                await page.wait_for_timeout(_AUTH_SETTLE_DELAY_MS)
        _validate_platform_location(platform, page)
        if not ready:
            raise PreconditionError(f"{platform} page readiness check timed out")
        return page

    async def _open_temporary_platform_page(self, platform: str) -> Any:
        context = _select_context(self._browser, platform)
        page = await context.new_page()
        self._temporary_pages.append(page)
        self._prepared_pages[platform] = page
        try:
            response = await self.navigate(
                page,
                _ENTRY_URLS[platform],
                allowed_hosts=tuple(_HOSTS[platform]),
            )
        except PlaywrightTimeoutError as error:
            raise PreconditionError("platform entry navigation timed out") from error
        status = getattr(response, "status", None)
        if isinstance(status, bool) or not isinstance(status, int):
            raise PreconditionError("platform entry navigation returned no response")
        if status in _RISK_HTTP_STATUSES:
            raise BrowserRiskError(f"http-{status}")
        if not 200 <= status < 300:
            raise PreconditionError("platform entry navigation was unsuccessful")
        return page

    async def page_json(self, page: Any, url: str) -> PageJson:
        page_origin = urlparse(page.url)
        request_origin = urlparse(url)
        if (page_origin.scheme, page_origin.hostname, page_origin.port) != (
            request_origin.scheme,
            request_origin.hostname,
            request_origin.port,
        ):
            raise PreconditionError("request URL must use the selected page origin")
        result = await page.evaluate(
            """async (requestUrl) => {
                const response = await fetch(requestUrl);
                return {status: response.status, json: await response.json()};
            }""",
            url,
        )
        return PageJson(status=int(result["status"]), payload=result["json"])

    async def navigate(self, page: Any, url: str, *, allowed_hosts: tuple[str, ...]) -> Any:
        """Navigate only when the collection invocation explicitly authorized it."""
        if not self.allow_navigation:
            raise PreconditionError("browser navigation is not authorized")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in set(allowed_hosts):
            raise PreconditionError("navigation URL must use an exact allowlisted host")
        return await page.goto(url, wait_until="domcontentloaded")

    async def close(self) -> None:
        failure: BaseException | None = None
        try:
            for page in reversed(self._temporary_pages):
                try:
                    if not _page_is_closed(page):
                        await page.close()
                except BaseException as error:
                    if failure is None:
                        failure = error
            try:
                await self._playwright.stop()
            except BaseException as error:
                if failure is None:
                    failure = error
        finally:
            self._temporary_pages.clear()
            self._prepared_pages.clear()
        if failure is not None:
            raise failure


def _page_is_closed(page: Any) -> bool:
    checker = getattr(page, "is_closed", None)
    return bool(checker()) if callable(checker) else False


def _select_context(browser: Any, platform: str) -> Any:
    contexts = list(browser.contexts)
    if not contexts:
        raise PreconditionError("existing browser context is required")
    matching = [
        context
        for context in contexts
        if any(
            not _page_is_closed(page)
            and urlparse(page.url).hostname in _HOSTS[platform]
            for page in context.pages
        )
    ]
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1 or len(contexts) > 1:
        raise PreconditionError("platform browser context is ambiguous")
    return contexts[0]


def _validate_platform_location(platform: str, page: Any) -> None:
    parsed = urlparse(page.url)
    if parsed.hostname not in _HOSTS[platform]:
        raise PreconditionError("prepared page left the exact platform host")
    path_segments = {
        segment.casefold() for segment in parsed.path.split("/") if segment
    }
    if path_segments.intersection(_LOGIN_PATH_SEGMENTS):
        raise PreconditionError(f"{platform} page is clearly logged out")


async def _authentication_observation(
    page: Any, platform: str
) -> dict[str, bool]:
    value = await page.evaluate(
        """(options) => {
            const visible = (element) => {
                if (!element || !element.isConnected) return false;
                for (let node = element; node; node = node.parentElement) {
                    const style = window.getComputedStyle(node);
                    if (node.hidden || node.getAttribute('aria-hidden') === 'true'
                        || style.display === 'none' || style.visibility === 'hidden'
                        || style.visibility === 'collapse' || Number(style.opacity || '1') === 0) return false;
                }
                const rect = element.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const anyVisible = (selectors) => selectors.some((selector) =>
                Array.from(document.querySelectorAll(selector)).some(visible)
            );
            return {
                logged_out: anyVisible(options.logged_out_selectors),
                challenge: (""" + risk_probe_function(platform) + """)().risk,
                ready: document.readyState === 'interactive'
                    || document.readyState === 'complete',
            };
        }""",
        {
            "logged_out_selectors": list(_LOGGED_OUT_SELECTORS[platform]),
        },
    )
    if not isinstance(value, Mapping) or any(
        not isinstance(value.get(key), bool)
        for key in ("logged_out", "challenge", "ready")
    ):
        raise PreconditionError(
            f"{platform} authentication check did not return booleans"
        )
    return {
        "logged_out": value["logged_out"],
        "challenge": value["challenge"],
        "ready": value["ready"],
    }
