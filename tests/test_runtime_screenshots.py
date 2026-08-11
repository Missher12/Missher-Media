from __future__ import annotations

import asyncio
import hashlib
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from runtime.media_missher_runtime.screenshots import (
    EvidenceScreenshot,
    ScreenshotError,
)
from runtime.media_missher_runtime.storage import RunStore


PNG = b"\x89PNG\r\n\x1a\nsynthetic-image"
FULL_PNG = b"\x89PNG\r\n\x1a\nsynthetic-full-page"
_DEFAULT_BOX = object()


class Locator:
    def __init__(
        self,
        *,
        count: int = 1,
        visible: bool = True,
        box: dict[str, float] | None | object = _DEFAULT_BOX,
        payload: bytes = PNG,
        failure: BaseException | None = None,
    ) -> None:
        self._count = count
        self._visible = visible
        self._box = (
            {"width": 640, "height": 480}
            if box is _DEFAULT_BOX
            else box
        )
        self._payload = payload
        self._failure = failure
        self.captures = 0

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def bounding_box(self) -> dict[str, float] | None:
        return self._box

    async def screenshot(self, **kwargs: object) -> bytes:
        assert kwargs == {"type": "png"}
        self.captures += 1
        if self._failure is not None:
            raise self._failure
        return self._payload


class Page:
    def __init__(
        self,
        locator: Locator,
        *,
        risk: bool = False,
        risk_states: list[bool] | None = None,
        document_size: dict[str, float] | None = None,
        full_payload: bytes = FULL_PNG,
        full_failure: BaseException | None = None,
    ) -> None:
        self.article_locator = locator
        self.risk = risk
        self.risk_states = list(risk_states or [])
        self.document_size = document_size or {"width": 1280, "height": 4096}
        self.full_payload = full_payload
        self.full_failure = full_failure
        self.locator_selectors: list[str] = []
        self.full_captures = 0
        self.risk_options: dict[str, Any] | None = None

    async def evaluate(
        self,
        script: str,
        options: dict[str, Any] | None = None,
    ) -> bool | dict[str, float]:
        if "MEDIA_MISSHER_DOCUMENT_DIMENSIONS" in script:
            return self.document_size
        assert options is not None
        self.risk_options = options
        return self.risk_states.pop(0) if self.risk_states else self.risk

    def locator(self, selector: str) -> Locator:
        self.locator_selectors.append(selector)
        return self.article_locator

    async def screenshot(self, **kwargs: object) -> bytes:
        assert kwargs == {"full_page": True, "type": "png"}
        self.full_captures += 1
        if self.full_failure is not None:
            raise self.full_failure
        return self.full_payload


def _capture(store: RunStore) -> EvidenceScreenshot:
    return EvidenceScreenshot(
        store,
        clock=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_capture_binds_private_article_evidence_to_record(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, "article")
    page = Page(Locator())

    artifact = await _capture(store).capture(
        page,
        platform="xhs",
        native_id="note-123",
        request_mode="opened",
    )

    assert artifact.as_record_fields() == {
        "screenshot_path": "screenshots/xhs-note-123.png",
        "screenshot_mode": "opened",
        "screenshot_capture_kind": "article",
        "screenshot_observed_at": "2026-08-11T00:00:00+00:00",
        "screenshot_sha256": hashlib.sha256(PNG).hexdigest(),
        "screenshot_status": "complete",
    }
    target = store.path / artifact.path
    assert target.read_bytes() == PNG
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert page.article_locator.captures == 1
    assert page.full_captures == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locator",
    (
        Locator(count=0),
        Locator(count=2),
        Locator(visible=False),
        Locator(box=None),
        Locator(box={"width": 0, "height": 100}),
        Locator(box={"width": 99, "height": 80}),
        Locator(box={"width": 4097, "height": 100}),
        Locator(box={"width": 100, "height": 30001}),
        Locator(failure=RuntimeError("article failed")),
    ),
)
async def test_invalid_or_failed_article_capture_falls_back_once(
    tmp_path: Path, locator: Locator
) -> None:
    store = RunStore.create(tmp_path, f"fallback-{id(locator)}")
    page = Page(locator)

    artifact = await _capture(store).capture(
        page,
        platform="bilibili",
        native_id="123456",
        request_mode="all",
    )

    assert artifact.capture_kind == "full_page_fallback"
    assert (store.path / artifact.path).read_bytes() == FULL_PNG
    assert page.full_captures == 1


@pytest.mark.asyncio
async def test_article_pixel_limit_is_checked_before_capture(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, "article-pixel-limit")
    locator = Locator(box={"width": 4096, "height": 4097})
    page = Page(locator)

    artifact = await _capture(store).capture(
        page,
        platform="bilibili",
        native_id="123456",
        request_mode="all",
    )

    assert artifact.capture_kind == "full_page_fallback"
    assert locator.captures == 0
    assert page.full_captures == 1


@pytest.mark.asyncio
async def test_risk_page_creates_no_png(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, "risk")
    page = Page(Locator(), risk=True)

    with pytest.raises(ScreenshotError, match="risk-page"):
        await _capture(store).capture(
            page,
            platform="xhs",
            native_id="note-123",
            request_mode="opened",
        )

    assert not (store.path / "screenshots").exists()
    assert page.article_locator.captures == 0
    assert page.full_captures == 0
    assert page.risk_options is not None
    assert "challenge" in " ".join(page.risk_options["risk_phrases"])


@pytest.mark.asyncio
@pytest.mark.parametrize("article_count", (0, 1))
async def test_risk_appearing_after_capture_discards_png(
    tmp_path: Path,
    article_count: int,
) -> None:
    store = RunStore.create(tmp_path, f"post-capture-risk-{article_count}")
    page = Page(Locator(count=article_count), risk_states=[False, True])

    with pytest.raises(ScreenshotError, match="risk-page"):
        await _capture(store).capture(
            page,
            platform="xhs",
            native_id="note-123",
            request_mode="all",
        )

    assert not (store.path / "screenshots").exists()
    assert page.article_locator.captures == article_count
    assert page.full_captures == (0 if article_count else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document_size",
    (
        {"width": 4097, "height": 1000},
        {"width": 1000, "height": 30001},
        {"width": 4096, "height": 4097},
    ),
)
async def test_full_page_fallback_rejects_oversized_document_before_capture(
    tmp_path: Path,
    document_size: dict[str, float],
) -> None:
    store = RunStore.create(tmp_path, f"oversized-{document_size['width']}-{document_size['height']}")
    page = Page(Locator(count=0), document_size=document_size)

    with pytest.raises(ScreenshotError, match="capture-failed"):
        await _capture(store).capture(
            page,
            platform="bilibili",
            native_id="123456",
            request_mode="all",
        )

    assert page.full_captures == 0
    assert not (store.path / "screenshots").exists()


@pytest.mark.asyncio
async def test_full_page_failure_is_safe_and_writes_nothing(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, "capture-failure")
    page = Page(
        Locator(count=0),
        full_failure=RuntimeError("private screenshot detail"),
    )

    with pytest.raises(ScreenshotError) as captured:
        await _capture(store).capture(
            page,
            platform="xhs",
            native_id="note-123",
            request_mode="all",
        )

    assert str(captured.value) == "capture-failed"
    assert not (store.path / "screenshots").exists()


@pytest.mark.asyncio
async def test_capture_preserves_cancellation(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, "capture-cancelled")
    cancellation = asyncio.CancelledError("cancelled")
    page = Page(Locator(count=0), full_failure=cancellation)

    with pytest.raises(asyncio.CancelledError) as captured:
        await _capture(store).capture(
            page,
            platform="xhs",
            native_id="note-123",
            request_mode="all",
        )

    assert captured.value is cancellation
    assert not (store.path / "screenshots").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "native_id", "request_mode"),
    (
        ("weibo", "123", "all"),
        ("xhs", "../private", "all"),
        ("xhs", "note", "off"),
    ),
)
async def test_capture_rejects_unsupported_or_unsafe_arguments(
    tmp_path: Path, platform: str, native_id: str, request_mode: str
) -> None:
    store = RunStore.create(tmp_path, "invalid-args")

    with pytest.raises(ScreenshotError, match="capture-failed"):
        await _capture(store).capture(
            Page(Locator()),
            platform=platform,
            native_id=native_id,
            request_mode=request_mode,
        )


def test_browser_session_binds_store_without_module_global(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.browser import BrowserSession

    store = RunStore.create(tmp_path, "binding")
    session = BrowserSession(object(), object())

    session.bind_store(store)

    assert isinstance(session.screenshots, EvidenceScreenshot)
    assert session.screenshots.store is store
