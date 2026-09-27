from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from runtime.media_missher_runtime.browser import PreconditionError
from runtime.media_missher_runtime.detail_open import (
    DetailOpenCoordinator,
    missing_engagement_fields,
)


def test_missing_engagement_fields_preserves_known_zero() -> None:
    assert missing_engagement_fields(
        {
            "liked": 0,
            "comments": 2,
            "collected": None,
            "shares": None,
        }
    ) == ("collected", "shares")


@dataclass
class Context:
    pages: list[Any] = field(default_factory=list)


class Locator:
    def __init__(self, page: "Page") -> None:
        self.page = page

    async def count(self) -> int:
        return self.page.target_count

    async def evaluate_all(self, _script: str) -> None:
        self.page.marker_removed = True
        if self.page.cleanup_error is not None:
            raise self.page.cleanup_error


class Element:
    def __init__(self, page: "Page", failure: BaseException | None = None) -> None:
        self.page = page
        self.failure = failure
        self.clicked = 0
        self.markers: list[str] = []

    async def evaluate(self, _script: str, value: str) -> None:
        self.markers.append(value)
        if self.page.target_count_override is None:
            self.page.target_count = 1

    async def click(self) -> None:
        self.clicked += 1
        if self.failure is not None:
            raise self.failure
        self.page.open_detail()


class Page:
    def __init__(
        self,
        url: str,
        *,
        detail_url: str | None = None,
        popup_url: str | None = None,
        target_count: int | None = None,
        cleanup_error: BaseException | None = None,
    ) -> None:
        self.url = url
        self.detail_url = detail_url
        self.popup_url = popup_url
        self.context = Context([self])
        self.target_count_override = target_count
        self.target_count = target_count or 0
        self.cleanup_error = cleanup_error
        self.marker_removed = False
        self.current_title = "original title"
        self.closed = False

    def locator(self, _selector: str) -> Locator:
        return Locator(self)

    async def title(self) -> str:
        return self.current_title

    async def evaluate(self, script: str, value: str | None = None) -> None:
        if "document.title" in script and value is not None:
            self.current_title = value

    def is_closed(self) -> bool:
        return self.closed

    def open_detail(self) -> None:
        if self.popup_url is not None:
            self.context.pages.append(Popup(self.popup_url, self.context, self))
        elif self.detail_url is not None:
            self.url = self.detail_url

    async def opener(self) -> None:
        return None


class Popup:
    def __init__(
        self,
        url: str,
        context: Context,
        opener_page: Page | None = None,
    ) -> None:
        self.url = url
        self.context = context
        self.opener_page = opener_page
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True

    async def opener(self) -> Page | None:
        return self.opener_page




@pytest.mark.asyncio
async def test_default_coordinator_marks_clicks_and_removes_marker() -> None:
    page = Page(
        "https://www.xiaohongshu.com/explore",
        detail_url="https://www.xiaohongshu.com/explore/note-123",
    )
    element = Element(page)

    result = await DetailOpenCoordinator().click_exact(
        page, element, platform="xhs", native_id="note-123"
    )

    assert result is page
    assert element.clicked == 1
    assert len(element.markers) == 1 and len(element.markers[0]) == 32
    assert page.marker_removed is True
    assert page.current_title == "original title"






@pytest.mark.asyncio
async def test_coordinator_registers_one_exact_same_context_popup() -> None:
    page = Page(
        "https://www.bilibili.com/",
        popup_url="https://t.bilibili.com/123456",
    )
    element = Element(page)
    registered: list[Any] = []
    coordinator = DetailOpenCoordinator(register_temporary_page=registered.append)

    result = await coordinator.click_exact(
        page, element, platform="bilibili", native_id="123456"
    )

    assert result is page.context.pages[-1]
    assert registered == [result]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_count", "detail_url"),
    (
        (0, "https://www.xiaohongshu.com/explore/note-123"),
        (2, "https://www.xiaohongshu.com/explore/note-123"),
        (1, "https://www.xiaohongshu.com/explore/other"),
        (1, "https://example.invalid/explore/note-123"),
    ),
)
async def test_coordinator_fails_closed_for_ambiguous_target_or_location(
    target_count: int, detail_url: str
) -> None:
    page = Page(
        "https://www.xiaohongshu.com/explore",
        detail_url=detail_url,
        target_count=target_count,
    )
    element = Element(page)

    with pytest.raises(PreconditionError):
        await DetailOpenCoordinator().click_exact(
            page, element, platform="xhs", native_id="note-123"
        )

    assert page.marker_removed is True
    assert element.clicked == (1 if target_count == 1 else 0)


@pytest.mark.asyncio
async def test_primary_click_error_wins_over_marker_cleanup_error() -> None:
    primary = RuntimeError("primary")
    cleanup = RuntimeError("cleanup")
    page = Page(
        "https://www.xiaohongshu.com/explore",
        cleanup_error=cleanup,
    )
    element = Element(page, primary)

    with pytest.raises(RuntimeError) as captured:
        await DetailOpenCoordinator().click_exact(
            page, element, platform="xhs", native_id="note-123"
        )

    assert captured.value is primary
    assert page.marker_removed is True


@pytest.mark.asyncio
async def test_coordinator_waits_for_a_delayed_same_page_url_commit() -> None:
    page = Page("https://www.xiaohongshu.com/explore")
    element = Element(page)

    def delayed_open() -> None:
        asyncio.get_running_loop().call_later(
            0.01,
            setattr,
            page,
            "url",
            "https://www.xiaohongshu.com/explore/note-123",
        )

    page.open_detail = delayed_open  # type: ignore[method-assign]

    result = await DetailOpenCoordinator().click_exact(
        page,
        element,
        platform="xhs",
        native_id="note-123",
    )

    assert result is page


@pytest.mark.asyncio
async def test_coordinator_waits_for_a_delayed_about_blank_popup_commit() -> None:
    page = Page("https://www.bilibili.com/")
    element = Element(page)
    popup = Popup("about:blank", page.context, page)

    def delayed_open() -> None:
        page.context.pages.append(popup)
        asyncio.get_running_loop().call_later(
            0.01,
            setattr,
            popup,
            "url",
            "https://t.bilibili.com/123456",
        )

    page.open_detail = delayed_open  # type: ignore[method-assign]
    coordinator = DetailOpenCoordinator()

    result = await coordinator.click_exact(
        page,
        element,
        platform="bilibili",
        native_id="123456",
    )

    assert result is popup
    await coordinator.release(result)
    assert popup.closed is True


@pytest.mark.asyncio
async def test_coordinator_rejects_cross_platform_same_id() -> None:
    page = Page(
        "https://www.xiaohongshu.com/explore",
        detail_url="https://t.bilibili.com/note-123",
    )

    with pytest.raises(PreconditionError):
        await DetailOpenCoordinator().click_exact(
            page,
            Element(page),
            platform="xhs",
            native_id="note-123",
        )


@pytest.mark.asyncio
async def test_invalid_multiple_new_popups_are_all_released_but_existing_page_is_untouched() -> None:
    page = Page("https://www.bilibili.com/")
    existing = Popup("https://example.invalid/user", page.context)
    page.context.pages.append(existing)
    invalid = Popup("https://example.invalid/123456", page.context, page)
    exact = Popup("https://t.bilibili.com/123456", page.context, page)
    element = Element(page)

    def open_two() -> None:
        page.context.pages.extend((invalid, exact))

    page.open_detail = open_two  # type: ignore[method-assign]

    with pytest.raises(PreconditionError):
        await DetailOpenCoordinator().click_exact(
            page,
            element,
            platform="bilibili",
            native_id="123456",
        )

    assert existing.closed is False
    assert invalid.closed is True
    assert exact.closed is True


@pytest.mark.asyncio
async def test_concurrent_unrelated_page_is_not_claimed_or_closed_beside_exact_popup() -> None:
    page = Page("https://www.bilibili.com/")
    unrelated = Popup("https://example.invalid/user", page.context)
    exact = Popup("https://t.bilibili.com/123456", page.context, page)
    registered: list[Any] = []

    def open_pages() -> None:
        page.context.pages.extend((unrelated, exact))

    page.open_detail = open_pages  # type: ignore[method-assign]
    coordinator = DetailOpenCoordinator(register_temporary_page=registered.append)

    result = await coordinator.click_exact(
        page,
        Element(page),
        platform="bilibili",
        native_id="123456",
    )

    assert result is exact
    assert registered == [exact]
    await coordinator.release(exact)
    assert exact.closed is True
    assert unrelated.closed is False


@pytest.mark.asyncio
async def test_exact_same_page_ignores_concurrent_unrelated_new_page() -> None:
    page = Page("https://www.xiaohongshu.com/explore")
    unrelated = Popup("https://example.invalid/user", page.context)
    registered: list[Any] = []

    def commit_and_open_unrelated() -> None:
        page.url = "https://www.xiaohongshu.com/explore/note-123"
        page.context.pages.append(unrelated)

    page.open_detail = commit_and_open_unrelated  # type: ignore[method-assign]
    coordinator = DetailOpenCoordinator(register_temporary_page=registered.append)

    result = await coordinator.click_exact(
        page,
        Element(page),
        platform="xhs",
        native_id="note-123",
    )

    assert result is page
    assert registered == []
    assert unrelated.closed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("opener_kind", ("none", "different"))
async def test_exact_popup_without_source_page_opener_is_never_accepted_or_closed(
    opener_kind: str,
) -> None:
    page = Page("https://www.bilibili.com/")
    different = Page("https://www.bilibili.com/other")
    opener_page = None if opener_kind == "none" else different
    popup = Popup("https://t.bilibili.com/123456", page.context, opener_page)

    page.open_detail = lambda: page.context.pages.append(popup)  # type: ignore[method-assign]

    with pytest.raises(PreconditionError, match="ambiguous"):
        await DetailOpenCoordinator().click_exact(
            page,
            Element(page),
            platform="bilibili",
            native_id="123456",
        )

    assert popup.closed is False


@pytest.mark.asyncio
async def test_click_derived_wrong_popup_is_closed_on_failure() -> None:
    page = Page("https://www.bilibili.com/")
    wrong = Popup("https://t.bilibili.com/wrong", page.context, page)
    page.open_detail = lambda: page.context.pages.append(wrong)  # type: ignore[method-assign]

    with pytest.raises(PreconditionError, match="ambiguous"):
        await DetailOpenCoordinator().click_exact(
            page,
            Element(page),
            platform="bilibili",
            native_id="123456",
        )

    assert wrong.closed is True


@pytest.mark.asyncio
async def test_cdp_guard_denial_prevents_click_and_removes_marker():
    page=Page('https://www.xiaohongshu.com/explore',detail_url='https://www.xiaohongshu.com/explore/note-123')
    element=Element(page)
    def deny():raise PreconditionError('risk-stop')
    with pytest.raises(PreconditionError,match='risk-stop'):
        await DetailOpenCoordinator().click_exact(page,element,platform='xhs',native_id='note-123',guard=deny)
    assert element.clicked==0
    assert page.marker_removed


@pytest.mark.asyncio
async def test_uncertain_cdp_click_is_not_replayed():
    page=Page('https://www.xiaohongshu.com/explore',detail_url='https://www.xiaohongshu.com/explore/note-123')
    element=Element(page)
    async def uncertain():
        element.clicked+=1
        raise TimeoutError('delivered-but-unknown')
    element.click=uncertain
    with pytest.raises(TimeoutError):
        await DetailOpenCoordinator().click_exact(page,element,platform='xhs',native_id='note-123')
    assert element.clicked==1
    assert page.marker_removed
