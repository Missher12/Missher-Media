from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any

from .storage import RunStore


_ARTICLE_SELECTORS = {
    "xhs": (
        "section.note-content",
        "div.note-detail-mask div.note-content",
        "main article",
    ),
    "bilibili": (
        "main article",
        ".opus-detail",
        ".bili-dyn-item",
    ),
}
_RISK_SELECTORS = (
    ".geetest_panel",
    ".geetest_holder",
    'iframe[src*="captcha"]',
    '[class*="captcha"]',
    ".challenge-page",
    ".challenge-overlay",
    ".login-container",
    ".login-panel-popover",
)
_RISK_PHRASES = (
    "challenge",
    "captcha",
    "risk",
    "locked",
    "blocked",
    "cooldown",
    "请完成验证",
    "访问受限",
    "请求过于频繁",
    "账号异常",
    "风控",
    "安全验证",
    "验证码",
)
_SAFE_NATIVE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_MAX_CAPTURE_WIDTH = 4096
_MAX_CAPTURE_HEIGHT = 30_000
# Bound decoded image area before Playwright allocates a PNG buffer.
_MAX_CAPTURE_PIXELS = 16_777_216


@dataclass(frozen=True, slots=True)
class ScreenshotArtifact:
    path: str
    request_mode: str
    capture_kind: str
    observed_at: str
    sha256: str

    def as_record_fields(self) -> dict[str, str]:
        return {
            "screenshot_path": self.path,
            "screenshot_mode": self.request_mode,
            "screenshot_capture_kind": self.capture_kind,
            "screenshot_observed_at": self.observed_at,
            "screenshot_sha256": self.sha256,
            "screenshot_status": "complete",
        }


class ScreenshotError(RuntimeError):
    pass


class EvidenceScreenshot:
    def __init__(
        self,
        store: RunStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _risk_visible(self, page: Any) -> bool:
        value = await page.evaluate(
            """(options) => {
                const visible = (element) => {
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || '1') !== 0
                        && rect.width > 0 && rect.height > 0;
                };
                if (options.risk_selectors.some((selector) =>
                    Array.from(document.querySelectorAll(selector)).some(visible))) {
                    return true;
                }
                const text = (document.body?.innerText || '').toLocaleLowerCase();
                return options.risk_phrases.some((phrase) =>
                    text.includes(phrase.toLocaleLowerCase()));
            }""",
            {
                "risk_selectors": list(_RISK_SELECTORS),
                "risk_phrases": list(_RISK_PHRASES),
            },
        )
        if not isinstance(value, bool):
            raise ScreenshotError("capture-failed")
        return value

    async def _full_page_dimensions_are_safe(self, page: Any) -> bool:
        value = await page.evaluate(
            """/* MEDIA_MISSHER_DOCUMENT_DIMENSIONS */ () => ({
                width: Math.max(
                    document.documentElement?.scrollWidth || 0,
                    document.documentElement?.clientWidth || 0,
                    document.body?.scrollWidth || 0,
                    document.body?.clientWidth || 0
                ),
                height: Math.max(
                    document.documentElement?.scrollHeight || 0,
                    document.documentElement?.clientHeight || 0,
                    document.body?.scrollHeight || 0,
                    document.body?.clientHeight || 0
                ),
            })"""
        )
        if not isinstance(value, Mapping):
            return False
        width = value.get("width")
        height = value.get("height")
        dimensions_are_safe = all(
            isinstance(dimension, Real)
            and not isinstance(dimension, bool)
            and math.isfinite(float(dimension))
            and 0 < dimension <= maximum
            for dimension, maximum in (
                (width, _MAX_CAPTURE_WIDTH),
                (height, _MAX_CAPTURE_HEIGHT),
            )
        )
        return dimensions_are_safe and float(width) * float(height) <= _MAX_CAPTURE_PIXELS

    async def capture(
        self,
        page: Any,
        *,
        platform: str,
        native_id: str,
        request_mode: str,
    ) -> ScreenshotArtifact:
        if (
            platform not in _ARTICLE_SELECTORS
            or request_mode not in {"opened", "all"}
            or not isinstance(native_id, str)
            or "/" in native_id
            or "\\" in native_id
            or ".." in native_id
            or _SAFE_NATIVE_ID.fullmatch(native_id) is None
        ):
            raise ScreenshotError("capture-failed")
        try:
            if await self._risk_visible(page):
                raise ScreenshotError("risk-page")
            locator = page.locator(", ".join(_ARTICLE_SELECTORS[platform]))
            capture_kind = "full_page_fallback"
            payload: bytes | None = None
            if await locator.count() == 1 and await locator.is_visible():
                box = await locator.bounding_box()
                if (
                    isinstance(box, dict)
                    and isinstance(box.get("width"), (int, float))
                    and not isinstance(box.get("width"), bool)
                    and isinstance(box.get("height"), (int, float))
                    and not isinstance(box.get("height"), bool)
                    and 100 <= box["width"] <= _MAX_CAPTURE_WIDTH
                    and 80 <= box["height"] <= _MAX_CAPTURE_HEIGHT
                    and box["width"] * box["height"] <= _MAX_CAPTURE_PIXELS
                ):
                    try:
                        payload = await locator.screenshot(type="png")
                        capture_kind = "article"
                    except Exception:
                        payload = None
            if payload is None:
                if await self._risk_visible(page):
                    raise ScreenshotError("risk-page")
                if not await self._full_page_dimensions_are_safe(page):
                    raise ScreenshotError("capture-failed")
                payload = await page.screenshot(full_page=True, type="png")
            if await self._risk_visible(page):
                payload = None
                raise ScreenshotError("risk-page")
            relative_path = f"screenshots/{platform}-{native_id}.png"
            self.store.write_private_bytes(relative_path, payload)
        except ScreenshotError:
            raise
        except BaseException as error:
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            raise ScreenshotError("capture-failed") from error

        observed_at = self._clock()
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        observed_at = observed_at.astimezone(UTC)
        return ScreenshotArtifact(
            path=relative_path,
            request_mode=request_mode,
            capture_kind=capture_kind,
            observed_at=observed_at.isoformat(),
            sha256=hashlib.sha256(payload).hexdigest(),
        )


__all__ = ["EvidenceScreenshot", "ScreenshotArtifact", "ScreenshotError"]
