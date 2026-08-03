from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - exercised when a real browser is configured
    async_playwright = None


_HOSTS = {
    "bilibili": frozenset({"bilibili.com", "www.bilibili.com", "space.bilibili.com", "search.bilibili.com", "api.bilibili.com", "t.bilibili.com"}),
    "xhs": frozenset({"xiaohongshu.com", "www.xiaohongshu.com"}),
    "douyin": frozenset({"douyin.com", "www.douyin.com"}),
    "weibo": frozenset({"weibo.com", "www.weibo.com", "s.weibo.com"}),
}
_LOGGED_OUT_SELECTORS = {
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


class PreconditionError(RuntimeError):
    """Raised when the user has not prepared an authenticated browser page."""


@dataclass(frozen=True, slots=True)
class PageJson:
    status: int
    payload: Any


@dataclass(slots=True)
class BrowserSession:
    _playwright: Any
    _browser: Any
    allow_navigation: bool = False

    @classmethod
    async def connect(cls, cdp_url: str, *, allow_navigation: bool = False) -> "BrowserSession":
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

    def require_page(self, platform: str) -> Any:
        hosts = _HOSTS.get(platform)
        if hosts is None:
            raise ValueError("unsupported platform")
        for context in self._browser.contexts:
            for page in context.pages:
                if urlparse(page.url).hostname in hosts:
                    return page
        raise PreconditionError(f"Open/authenticated {platform} page is required".lower())

    async def require_authenticated_page(self, platform: str) -> Any:
        """Return an open platform page unless it is clearly logged out."""
        page = self.require_page(platform)
        path_segments = {
            segment.casefold()
            for segment in urlparse(page.url).path.split("/")
            if segment
        }
        if path_segments.intersection(_LOGIN_PATH_SEGMENTS):
            raise PreconditionError(f"{platform} page is clearly logged out")
        logged_out = await page.evaluate(
            """({selectors}) => selectors.some((selector) =>
                Array.from(document.querySelectorAll(selector)).some((element) => {
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || '1') !== 0
                        && rect.width > 0
                        && rect.height > 0;
                })
            )""",
            {"selectors": list(_LOGGED_OUT_SELECTORS[platform])},
        )
        if not isinstance(logged_out, bool):
            raise PreconditionError(f"{platform} authentication check did not return a boolean")
        if logged_out:
            raise PreconditionError(f"{platform} page is clearly logged out")
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
        await self._playwright.stop()
