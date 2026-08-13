from __future__ import annotations

import asyncio
import inspect
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

from .browser import PreconditionError
from .browser_skill import BrowserSkillBridge


ENGAGEMENT_FIELDS = ("liked", "comments", "collected", "shares")
_DETAIL_RESOLVE_TIMEOUT = 1.0
_DETAIL_POLL_INTERVAL = 0.05


def missing_engagement_fields(record: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(field for field in ENGAGEMENT_FIELDS if record.get(field) is None)


def _page_is_closed(page: Any) -> bool:
    checker = getattr(page, "is_closed", None)
    return bool(checker()) if callable(checker) else False


def matches_exact_detail_page(page: Any, platform: str, native_id: str) -> bool:
    url = getattr(page, "url", None)
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if platform == "xhs":
        return (
            parsed.hostname in {"xiaohongshu.com", "www.xiaohongshu.com"}
            and segments in (["explore", native_id], ["discovery", "item", native_id])
        )
    if platform == "bilibili":
        if parsed.hostname == "t.bilibili.com":
            return segments == [native_id]
        return (
            parsed.hostname in {"bilibili.com", "www.bilibili.com"}
            and segments in (["opus", native_id], ["dynamic", native_id])
        )
    return False


def _new_pages(context: Any, previous_pages: tuple[Any, ...]) -> list[Any]:
    return [
        candidate
        for candidate in getattr(context, "pages", ())
        if not any(candidate is previous for previous in previous_pages)
        and not _page_is_closed(candidate)
    ]


async def _is_click_derived_popup(candidate: Any, source_page: Any) -> bool:
    opener = getattr(candidate, "opener", None)
    if not callable(opener):
        return False
    try:
        owner = opener()
        if inspect.isawaitable(owner):
            owner = await owner
    except Exception:
        return False
    return owner is source_page


async def resolve_exact_detail_page(
    page: Any,
    *,
    platform: str,
    native_id: str,
    previous_pages: tuple[Any, ...] | None = None,
    observe_new_page: Callable[[Any], Any] | None = None,
) -> Any:
    if (
        platform not in {"bilibili", "xhs"}
        or not isinstance(native_id, str)
        or not native_id
        or "/" in native_id
    ):
        raise PreconditionError("exact detail identifier is invalid")
    context = getattr(page, "context", None)
    pages = list(getattr(context, "pages", ()))
    if context is None or not any(candidate is page for candidate in pages):
        raise PreconditionError("exact detail page context is unavailable")
    previous = tuple(pages) if previous_pages is None else previous_pages
    deadline = asyncio.get_running_loop().time() + _DETAIL_RESOLVE_TIMEOUT
    last_candidate: Any = None
    while True:
        created = _new_pages(context, previous)
        derived = [
            candidate
            for candidate in created
            if await _is_click_derived_popup(candidate, page)
        ]
        if observe_new_page is not None:
            for candidate in derived:
                result = observe_new_page(candidate)
                if inspect.isawaitable(result):
                    await result
        original_matches = (
            not _page_is_closed(page)
            and matches_exact_detail_page(page, platform, native_id)
        )
        popup_matches = [
            candidate
            for candidate in derived
            if matches_exact_detail_page(candidate, platform, native_id)
        ]
        candidate = None
        if original_matches and not derived:
            candidate = page
        elif not original_matches and len(derived) == 1 and len(popup_matches) == 1:
            candidate = popup_matches[0]
        if candidate is not None and candidate is last_candidate:
            return candidate
        last_candidate = candidate
        if asyncio.get_running_loop().time() >= deadline:
            raise PreconditionError("exact detail page is ambiguous")
        await asyncio.sleep(_DETAIL_POLL_INTERVAL)


@dataclass(slots=True)
class DetailOpenCoordinator:
    bridge: BrowserSkillBridge | None = None
    register_temporary_page: Callable[[Any], Any] | None = None
    release_temporary_page: Callable[[Any], Any] | None = None
    _owned_pages: list[Any] = field(default_factory=list, init=False, repr=False)

    async def _claim(self, page: Any) -> None:
        if any(page is candidate for candidate in self._owned_pages):
            return
        self._owned_pages.append(page)
        if self.register_temporary_page is not None:
            result = self.register_temporary_page(page)
            if inspect.isawaitable(result):
                await result

    async def release(self, page: Any) -> None:
        if not any(page is candidate for candidate in self._owned_pages):
            return
        if self.release_temporary_page is not None:
            result = self.release_temporary_page(page)
            if inspect.isawaitable(result):
                await result
        elif not _page_is_closed(page):
            await page.close()
        self._owned_pages = [
            candidate for candidate in self._owned_pages if candidate is not page
        ]

    async def click_exact(
        self,
        page: Any,
        element: Any,
        *,
        platform: str,
        native_id: str,
        retry_stale_selector: bool = True,
    ) -> Any:
        if not isinstance(retry_stale_selector, bool):
            raise PreconditionError("invalid detail click policy")
        token = secrets.token_hex(16)
        selector = f'[data-media-missher-target="{token}"]'
        locator = page.locator(selector)
        original_title: str | None = None
        primary_error: BaseException | None = None
        claimed_this_click: list[Any] = []

        async def claim(candidate: Any) -> None:
            if not any(candidate is item for item in claimed_this_click):
                claimed_this_click.append(candidate)
            await self._claim(candidate)

        await element.evaluate(
            "(node, value) => node.setAttribute('data-media-missher-target', value)",
            token,
        )
        try:
            if await locator.count() != 1:
                raise PreconditionError("exact detail target is ambiguous")
            context = getattr(page, "context", None)
            previous_pages = tuple(getattr(context, "pages", ()))
            if self.bridge is None:
                await element.click()
            else:
                original_title = await page.title()
                await page.evaluate(
                    "value => { document.title = value; }",
                    f"media-missher-{secrets.token_hex(16)}",
                )
                await self.bridge.click_marked_tab(
                    page,
                    selector=selector,
                    retry_stale_selector=retry_stale_selector,
                )
            detail_page = await resolve_exact_detail_page(
                page,
                platform=platform,
                native_id=native_id,
                previous_pages=previous_pages,
                observe_new_page=claim,
            )
            return detail_page
        except BaseException as error:
            primary_error = error
            for candidate in reversed(claimed_this_click):
                try:
                    await self.release(candidate)
                except BaseException:
                    pass
            raise
        finally:
            cleanup_error: BaseException | None = None
            try:
                await locator.evaluate_all(
                    "nodes => nodes.forEach(node => node.removeAttribute('data-media-missher-target'))"
                )
            except BaseException as error:
                cleanup_error = error
            if original_title is not None and not _page_is_closed(page):
                try:
                    await page.evaluate(
                        "value => { document.title = value; }", original_title
                    )
                except BaseException as error:
                    if cleanup_error is None:
                        cleanup_error = error
            if primary_error is None and cleanup_error is not None:
                raise cleanup_error


__all__ = [
    "ENGAGEMENT_FIELDS",
    "DetailOpenCoordinator",
    "matches_exact_detail_page",
    "missing_engagement_fields",
    "resolve_exact_detail_page",
]
