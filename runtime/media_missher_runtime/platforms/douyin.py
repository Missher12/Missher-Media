from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any, Callable
from urllib.parse import quote, urlparse

from ..browser import BrowserSession, PreconditionError
from ..models import CollectionRequest
from ..safety import classify_response

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - the browser dependency is optional in unit tests
    PlaywrightTimeoutError = TimeoutError


_DOUYIN_HOST = "www.douyin.com"
_DOUYIN_HOSTS = (_DOUYIN_HOST,)
_CREATOR_PATH = "/aweme/v1/web/aweme/post/"
_SEARCH_PATH = "/aweme/v1/web/general/search/"
_CHALLENGE_REASONS = frozenset({"challenge-selector", "请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控", "安全验证", "验证码"})
_RISK_CODES = frozenset({461, 471, 999})


class CollectionStopped(RuntimeError):
    """A Douyin risk or challenge signal requires the whole collection to stop."""


class SourceResponseError(RuntimeError):
    """A browser-generated Douyin response cannot be safely consumed."""


@dataclass(slots=True)
class DouyinCollector:
    request: CollectionRequest
    browser: BrowserSession | Any

    async def collect(self) -> list[dict[str, Any]]:
        return await (self.collect_creator() if self.request.uid is not None else self.search())

    async def collect_creator(self) -> list[dict[str, Any]]:
        if self.request.uid is None:
            raise ValueError("creator collection requires uid")
        page = self.browser.require_page("douyin")
        target = _creator_page_url(self.request.uid)
        if getattr(self.browser, "allow_navigation", False):
            response = await _capture_response_while(page, _is_creator_response, lambda: self._navigate(page, target))
        else:
            _require_open_target(page, target, "matching Douyin creator page")
            response = await _capture_response_while(page, _is_creator_response, _noop)
        return await self._collect_pages(page, response, source="creator")

    async def search(self) -> list[dict[str, Any]]:
        if self.request.keyword is None:
            raise ValueError("search requires keyword")
        if self.request.complete:
            raise ValueError("complete search is not supported")
        page = self.browser.require_page("douyin")
        target = _search_page_url(self.request.keyword)
        if getattr(self.browser, "allow_navigation", False):
            response = await _capture_response_while(page, _is_search_response, lambda: self._navigate(page, target))
        else:
            _require_open_target(page, target, "matching Douyin search page")
            response = await _capture_response_while(page, _is_search_response, _noop)
        return await self._collect_pages(page, response, source="search")

    async def _collect_pages(self, page: Any, response: Any, *, source: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        native_ids: set[str] = set()
        prior_cursor: object = _MISSING
        predicate = _is_creator_response if source == "creator" else _is_search_response
        for page_number in range(self.request.page_cap):
            await _raise_for_page_challenge(page)
            payload = await _response_payload(response)
            items, has_more, cursor = _page_items(payload, source)
            added = _append_records(
                records,
                native_ids,
                items,
                keyword=self.request.keyword if source == "search" else None,
                cursor=cursor if source == "search" else _MISSING,
                target=self.request.target_count,
            )
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 or not has_more or page_number + 1 >= self.request.page_cap:
                break
            if _empty_cursor(cursor):
                break
            if prior_cursor is not _MISSING and cursor == prior_cursor:
                break
            prior_cursor = cursor
            try:
                response = await _capture_response_while(page, predicate, lambda: _scroll(page))
            except PlaywrightTimeoutError:
                break
        return records

    async def _navigate(self, page: Any, url: str) -> None:
        response = await self.browser.navigate(page, url, allowed_hosts=_DOUYIN_HOSTS)
        status = getattr(response, "status", None)
        if isinstance(status, int) and classify_response(status=status).stop_all:
            raise CollectionStopped(f"http-{status}")


async def collect_creator(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await DouyinCollector(request, browser).collect_creator()


async def search(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await DouyinCollector(request, browser).search()


async def _capture_response_while(page: Any, predicate: Callable[[Any], bool], action: Callable[[], Any]) -> Any:
    async with page.expect_response(predicate, timeout=10_000) as response_info:
        await action()
    return await response_info.value


def _is_creator_response(response: Any) -> bool:
    parsed = urlparse(getattr(response, "url", ""))
    return parsed.hostname == _DOUYIN_HOST and parsed.path == _CREATOR_PATH


def _is_search_response(response: Any) -> bool:
    parsed = urlparse(getattr(response, "url", ""))
    return (
        parsed.hostname == _DOUYIN_HOST
        and parsed.path.startswith(_SEARCH_PATH)
        and ("single" in parsed.path or "stream" in parsed.path)
    )


async def _response_payload(response: Any) -> Mapping[str, Any]:
    status = getattr(response, "status", None)
    if isinstance(status, bool) or not isinstance(status, int):
        raise SourceResponseError("Douyin source response has no numeric HTTP status")
    decision = classify_response(status=status)
    if decision.stop_all:
        raise CollectionStopped(decision.reason or "risk response")
    if not 200 <= status < 300:
        raise SourceResponseError(f"Douyin source returned http-{status}")
    try:
        payload = await response.json()
    except Exception as error:
        raise SourceResponseError("Douyin source JSON decode failed") from error
    if not isinstance(payload, Mapping):
        raise SourceResponseError("Douyin source returned a non-object JSON payload")
    _raise_for_payload_risk(payload)
    return payload


def _raise_for_payload_risk(payload: Mapping[str, Any]) -> None:
    for field in ("status_code", "code"):
        value = payload.get(field)
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, int) and not isinstance(value, bool) and value in _RISK_CODES:
            raise CollectionStopped(f"payload-{value}")
    high_risk = _mapping(payload.get("douyin_ai_search_info")).get("is_hit_high_risk")
    if high_risk is True:
        raise CollectionStopped("payload-high-risk")


async def _raise_for_page_challenge(page: Any) -> None:
    observation = await page.evaluate(
        """() => {
            const bodyText = document.body?.innerText || '';
            const selector = document.querySelector(
                '.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], [class*="captcha"], [class*="verify"]'
            );
            const phrases = ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控', '安全验证', '验证码'];
            return {risk_text: selector ? 'challenge-selector' : (phrases.find((phrase) => bodyText.includes(phrase)) || '')};
        }"""
    )
    text = _mapping(observation).get("risk_text")
    if isinstance(text, str) and (text in _CHALLENGE_REASONS or "captcha" in text.casefold()):
        raise CollectionStopped(text)


async def _noop() -> None:
    """Leave the listener awaiting the next browser-generated response."""
    return None


async def _scroll(page: Any) -> None:
    await page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")


def _page_items(payload: Mapping[str, Any], source: str) -> tuple[list[Mapping[str, Any]], bool, object]:
    if source == "creator":
        raw_items = _items(payload.get("aweme_list"))
        cursor = payload.get("max_cursor")
    else:
        raw_items = [_mapping(item).get("aweme_info") for item in _items(payload.get("data"))]
        cursor = payload.get("cursor")
    return [item for item in raw_items if isinstance(item, Mapping)], _has_more(payload.get("has_more")), cursor


_MISSING = object()


def _has_more(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if value is None:
        return False
    raise SourceResponseError("Douyin source has invalid has_more signal")


def _empty_cursor(value: object) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def _append_records(
    records: list[dict[str, Any]],
    native_ids: set[str],
    items: list[Mapping[str, Any]],
    *,
    keyword: str | None,
    cursor: object,
    target: int | None,
) -> int:
    added = 0
    observed_at = _observed_at()
    for item in items:
        record = parse_aweme_item(item, observed_at=observed_at)
        native_id = record["native_id"]
        if not isinstance(native_id, str) or not native_id or native_id in native_ids:
            continue
        if keyword is not None:
            record["search_keyword"] = keyword
            record["cursor"] = cursor
        native_ids.add(native_id)
        records.append(record)
        added += 1
        if target is not None and len(records) >= target:
            break
    return added


def parse_aweme_item(item: Mapping[str, Any], *, observed_at: str | None = None) -> dict[str, Any]:
    aweme_id = _text(item.get("aweme_id"))
    author = _mapping(item.get("author"))
    statistics = _mapping(item.get("statistics"))
    video = _mapping(item.get("video"))
    duration = item.get("duration", video.get("duration"))
    published = _date(item.get("create_time"))
    link = _video_link(aweme_id)
    return {
        "platform": "douyin",
        "type": _media_type(item),
        "aweme_id": aweme_id,
        "title": _text(item.get("desc")),
        "link": link,
        "date": published,
        "liked": _metric(statistics.get("digg_count")),
        "comments": _metric(statistics.get("comment_count")),
        "shares": _metric(statistics.get("share_count")),
        "collected": _metric(statistics.get("collect_count")),
        "plays": _metric(statistics.get("play_count")),
        "duration_ms": _metric(duration),
        "id": aweme_id,
        "native_id": aweme_id,
        "url": link,
        "author": _text(author.get("nickname")),
        "published_at": published,
        "observed_at": observed_at or _observed_at(),
    }


def _require_open_target(page: Any, target: str, message: str) -> None:
    parsed = urlparse(getattr(page, "url", ""))
    expected = urlparse(target)
    if parsed.scheme != "https" or parsed.hostname != _DOUYIN_HOST or parsed.path != expected.path:
        raise PreconditionError(message)


def _creator_page_url(uid: str) -> str:
    return f"https://{_DOUYIN_HOST}/user/{quote(uid, safe='')}"


def _search_page_url(keyword: str) -> str:
    return f"https://{_DOUYIN_HOST}/search/{quote(keyword, safe='')}"


def _video_link(aweme_id: str | None) -> str | None:
    return f"https://{_DOUYIN_HOST}/video/{aweme_id}" if aweme_id else None


def _media_type(item: Mapping[str, Any]) -> str:
    if _items(item.get("images")) or _items(item.get("image_infos")):
        return "images"
    media = _mapping(item.get("media"))
    observed_type = media.get("kind", item.get("media_type", item.get("aweme_type")))
    if isinstance(observed_type, str) and observed_type.casefold() in {"image", "images"}:
        return "images"
    return "video"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _metric(value: object) -> int | float | None:
    return value if isinstance(value, Real) and not isinstance(value, bool) else None


def _date(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return value if isinstance(value, str) and value else None
    return datetime.fromtimestamp(value, UTC).isoformat()


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()
