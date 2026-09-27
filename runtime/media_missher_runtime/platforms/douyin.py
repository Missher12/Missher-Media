from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any, Callable
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from ..browser import BrowserSession, PreconditionError, publish_accepted
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
_CONTENT_QUERY_KEYS = frozenset({"keyword", "q", "uid", "sec_uid"})
_CREATOR_IDENTITY_QUERY_KEYS = ("sec_user_id", "sec_uid", "uid")
_AWEME_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SAFE_OBSERVED_API_PATH = re.compile(r"/aweme/[A-Za-z0-9_./-]{1,180}")
_CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SENSITIVE_URL_VALUE = re.compile(
    r"(?:token|secret|password|passwd|credential|cookie|session|authorization|xsec)",
    re.IGNORECASE,
)
_SENSITIVE_URL_KEY = re.compile(
    r"(?:token|secret|password|passwd|credential|cookie|session|authorization|"
    r"xsec|signature|expires?|expiry|auth[_-]?key|"
    r"(?:^|[_-])auth(?:[_-]|$)|(?:^|[_-])sign(?:[_-]|$))",
    re.IGNORECASE,
)


class CollectionStopped(RuntimeError):
    """A Douyin risk or challenge signal requires the whole collection to stop."""


class SourceResponseError(RuntimeError):
    """A browser-generated Douyin response cannot be safely consumed."""


class CaptureTimeout(TimeoutError):
    """The initial creator response did not arrive inside the bounded wait."""

    _CODES = frozenset({"creator-capture-timeout"})
    _OBSERVATIONS = frozenset(
        {"no-endpoint", "identity-mismatch", "unclassified"}
    )

    def __init__(
        self,
        code: str,
        *,
        observation: str = "unclassified",
        routes: Sequence[str] = (),
    ) -> None:
        if code not in self._CODES:
            raise ValueError("unsupported capture timeout code")
        if observation not in self._OBSERVATIONS:
            raise ValueError("unsupported capture timeout observation")
        self.code = code
        self.observation = observation
        self.routes = tuple(
            route for route in routes if _safe_observed_route_text(route)
        )[:12]
        super().__init__(code)


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
        if not getattr(self.browser, "allow_navigation", False):
            _require_open_target(page, target, "matching Douyin creator page")
        await _raise_for_page_challenge(page)
        observation = {"value": "no-endpoint"}
        observed_routes: set[str] = set()

        def creator_predicate(response: Any) -> bool:
            if route := _safe_observed_api_route(response):
                observed_routes.add(route)
            binding = _creator_response_binding(response, self.request.uid)
            if binding == "mismatch":
                observation["value"] = "identity-mismatch"
            return binding in {"exact", "unbound"}
        try:
            if getattr(self.browser, "allow_navigation", False):
                response = await _capture_response_while(
                    page,
                    creator_predicate,
                    lambda: _scroll_and_check(page) if self.request.continue_page and page.url == target else self._navigate_and_check(page, target),
                )
            else:
                response = await _capture_response_while(
                    page, creator_predicate, _noop
                )
        except PlaywrightTimeoutError as error:
            await _raise_for_page_challenge(page)
            _require_open_target(
                page, target, "matching Douyin creator page"
            )
            dom_observation = await _read_creator_dom(page)
            await _raise_for_page_challenge(page)
            records = _creator_dom_records(
                dom_observation, self.request.target_count, self.request.exclude_ids
            )
            if records:
                return records
            raise CaptureTimeout(
                "creator-capture-timeout",
                observation=observation["value"],
                routes=sorted(observed_routes),
            ) from error
        return await self._collect_pages(page, response, source="creator")

    async def search(self) -> list[dict[str, Any]]:
        if self.request.keyword is None:
            raise ValueError("search requires keyword")
        if self.request.complete:
            raise ValueError("complete search is not supported")
        page = self.browser.require_page("douyin")
        target = _search_page_url(self.request.keyword)
        if not getattr(self.browser, "allow_navigation", False):
            _require_open_target(page, target, "matching Douyin search page")
        await _raise_for_page_challenge(page)
        if getattr(self.browser, "allow_navigation", False):
            response = await _capture_response_while(page, _is_search_response, lambda: _scroll_and_check(page) if self.request.continue_page and page.url == target else self._navigate_and_check(page, target))
        else:
            response = await _capture_response_while(page, _is_search_response, _noop)
        return await self._collect_pages(page, response, source="search")

    async def _collect_pages(self, page: Any, response: Any, *, source: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        native_ids: set[str] = set(self.request.exclude_ids)
        prior_cursor: object = _MISSING
        predicate = (
            (lambda candidate: _is_creator_candidate_response(candidate, self.request.uid))
            if source == "creator"
            else _is_search_response
        )
        for page_number in range(self.request.page_cap):
            if hasattr(self.browser, "last_pages"):
                self.browser.last_pages += 1
            await _raise_for_page_challenge(page)
            payload = await _response_payload(response)
            if source == "creator" and self.request.uid is not None:
                _require_creator_payload_binding(
                    response, payload, self.request.uid
                )
            items, has_more, cursor = _page_items(payload, source)
            added = _append_records(
                records,
                native_ids,
                items,
                keyword=self.request.keyword if source == "search" else None,
                cursor=cursor if source == "search" else _MISSING,
                target=self.request.target_count,
            )
            publish_accepted(self.browser, "douyin", records)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if not has_more or page_number + 1 >= self.request.page_cap:
                break
            if _empty_cursor(cursor):
                break
            if prior_cursor is not _MISSING and cursor == prior_cursor:
                break
            prior_cursor = cursor
            try:
                response = await _capture_response_while(page, predicate, lambda: _scroll_and_check(page))
            except PlaywrightTimeoutError:
                break
        return records

    async def _navigate(self, page: Any, url: str) -> None:
        response = await self.browser.navigate(page, url, allowed_hosts=_DOUYIN_HOSTS)
        status = getattr(response, "status", None)
        if isinstance(status, int) and classify_response(status=status).stop_all:
            raise CollectionStopped(f"http-{status}")

    async def _navigate_and_check(self, page: Any, url: str) -> None:
        await self._navigate(page, url)
        await _raise_for_page_challenge(page)


async def collect_creator(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await DouyinCollector(request, browser).collect_creator()


async def search(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await DouyinCollector(request, browser).search()


async def _capture_response_while(
    page: Any,
    predicate: Callable[[Any], bool],
    action: Callable[[], Any],
    *,
    timeout_ms: int = 10_000,
) -> Any:
    async with page.expect_response(predicate, timeout=timeout_ms) as response_info:
        await action()
    return await response_info.value


def _is_creator_response(response: Any, expected_uid: str | None = None) -> bool:
    binding = _creator_response_binding(response, expected_uid)
    return binding == "endpoint" if expected_uid is None else binding == "exact"


def _is_creator_candidate_response(response: Any, expected_uid: str) -> bool:
    return _creator_response_binding(response, expected_uid) in {"exact", "unbound"}


def _safe_observed_api_route(response: Any) -> str | None:
    parsed = urlparse(getattr(response, "url", ""))
    hostname = parsed.hostname
    if not isinstance(hostname, str) or not (
        hostname == "douyin.com" or hostname.endswith(".douyin.com")
    ):
        return None
    if _SAFE_OBSERVED_API_PATH.fullmatch(parsed.path) is None:
        return None
    route = f"{hostname}{parsed.path}"
    return route if _safe_observed_route_text(route) else None


def _safe_observed_route_text(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 240:
        return False
    if any(character in value for character in ("?", "#", "@", "=", "\\")):
        return False
    hostname, separator, path = value.partition("/")
    return bool(separator) and (
        hostname == "douyin.com" or hostname.endswith(".douyin.com")
    ) and _SAFE_OBSERVED_API_PATH.fullmatch(f"/{path}") is not None


def _creator_response_binding(
    response: Any, expected_uid: str | None
) -> str | None:
    parsed = urlparse(getattr(response, "url", ""))
    if parsed.hostname != _DOUYIN_HOST or parsed.path != _CREATOR_PATH:
        return None
    if expected_uid is None:
        return "endpoint"
    query = parse_qs(parsed.query, keep_blank_values=True)
    observed = next(
        (query[key] for key in _CREATOR_IDENTITY_QUERY_KEYS if query.get(key)),
        [],
    )
    if not observed:
        return "unbound"
    return "exact" if all(value == expected_uid for value in observed) else "mismatch"


def _require_creator_payload_binding(
    response: Any, payload: Mapping[str, Any], expected_uid: str
) -> None:
    binding = _creator_response_binding(response, expected_uid)
    if binding == "exact":
        return
    if binding != "unbound":
        raise SourceResponseError("Douyin creator response identity mismatched")
    items = [item for item in _items(payload.get("aweme_list")) if isinstance(item, Mapping)]
    if not items:
        raise SourceResponseError("Douyin creator payload identity is unavailable")
    for item in items:
        author = _mapping(item.get("author"))
        identities = (
            _identity_text(author.get("sec_uid")),
            _identity_text(author.get("sec_user_id")),
        )
        if expected_uid not in identities:
            raise SourceResponseError("Douyin creator payload identity mismatched")


def _identity_text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


async def _read_creator_dom(page: Any) -> Mapping[str, Any]:
    result = await page.evaluate(
        """/* MEDIA_MISSHER_DOUYIN_CREATOR_DOM */ () => {
            const visible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number(style.opacity || '1') !== 0
                    && rect.width > 0 && rect.height > 0;
            };
            const bodyText = document.body?.innerText || '';
            const challengeSelector = document.querySelector(
                '.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], [class*="captcha"], [class*="verify"]'
            );
            const phrases = ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控', '安全验证', '验证码'];
            const selectors = [
                '[data-e2e="user-post-list"]',
                '[data-e2e="scroll-list"]',
                'main'
            ];
            let containers = [];
            for (const selector of selectors) {
                containers = Array.from(document.querySelectorAll(selector))
                    .filter((node) => visible(node) && node.querySelector('a[href*="/video/"]'));
                if (containers.length) break;
            }
            if (containers.length !== 1) {
                return {
                    risk_text: challengeSelector ? 'challenge-selector' : (phrases.find((phrase) => bodyText.includes(phrase)) || ''),
                    list_unique: false,
                    cards: [],
                };
            }
            const seen = new Set();
            const cards = [];
            for (const anchor of containers[0].querySelectorAll('a[href*="/video/"]')) {
                let parsed;
                try {
                    parsed = new URL(anchor.getAttribute('href') || '', window.location.href);
                } catch (_error) {
                    continue;
                }
                const segments = parsed.pathname.split('/').filter(Boolean);
                if (parsed.protocol !== 'https:'
                    || parsed.hostname !== 'www.douyin.com'
                    || segments.length !== 2
                    || segments[0] !== 'video'
                    || !/^[A-Za-z0-9_-]{1,64}$/.test(segments[1])
                    || seen.has(segments[1])) continue;
                seen.add(segments[1]);
                const card = anchor.closest('li, article, [data-e2e*="post-item"]') || anchor;
                const image = card.querySelector('img') || anchor.querySelector('img');
                const title = anchor.getAttribute('aria-label')
                    || image?.getAttribute('alt')
                    || anchor.getAttribute('title')
                    || '';
                cards.push({
                    aweme_id: segments[1],
                    title,
                    cover: image?.currentSrc || image?.getAttribute('src') || '',
                });
            }
            return {
                risk_text: challengeSelector ? 'challenge-selector' : (phrases.find((phrase) => bodyText.includes(phrase)) || ''),
                list_unique: true,
                cards,
            };
        }"""
    )
    return _mapping(result)


def _creator_dom_records(
    observation: Mapping[str, Any], target: int | None, exclude_ids: Sequence[str] = ()
) -> list[dict[str, Any]]:
    risk_text = _text(observation.get("risk_text"))
    if risk_text is not None and (
        risk_text in _CHALLENGE_REASONS or "captcha" in risk_text.casefold()
    ):
        raise CollectionStopped(risk_text)
    if observation.get("list_unique") is not True:
        return []
    records: list[dict[str, Any]] = []
    native_ids: set[str] = set(exclude_ids)
    observed_at = _observed_at()
    for raw in _items(observation.get("cards")):
        card = _mapping(raw)
        aweme_id = _safe_aweme_id(card.get("aweme_id"))
        if aweme_id is None or aweme_id in native_ids:
            continue
        native_ids.add(aweme_id)
        link = _video_link(aweme_id)
        records.append(
            {
                "platform": "douyin",
                "type": "video",
                "aweme_id": aweme_id,
                "title": _text(card.get("title")),
                "link": link,
                "date": None,
                "liked": None,
                "comments": None,
                "shares": None,
                "collected": None,
                "plays": None,
                "duration_ms": None,
                "id": aweme_id,
                "native_id": aweme_id,
                "url": link,
                "author": None,
                "author_avatar": None,
                "cover": _safe_content_url(card.get("cover")),
                "published_at": None,
                "observed_at": observed_at,
            }
        )
        if target is not None and len(records) >= target:
            break
    return records


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
    codes: list[tuple[str, object]] = []
    for field in ("status_code", "code"):
        if field in payload:
            codes.append((field, _int_like(payload[field])))
    for _, value in codes:
        if isinstance(value, int) and value in _RISK_CODES:
            raise CollectionStopped(f"payload-{value}")
    high_risk = _mapping(payload.get("douyin_ai_search_info")).get("is_hit_high_risk")
    if high_risk is True:
        raise CollectionStopped("payload-high-risk")
    invalid_field = next((field for field, value in codes if value is _INVALID), None)
    if invalid_field is not None:
        raise SourceResponseError(f"Douyin payload {invalid_field} is not an integer code")
    nonzero = next(((field, value) for field, value in codes if value != 0), None)
    if nonzero is not None:
        field, value = nonzero
        raise SourceResponseError(f"Douyin payload {field} returned code {value}")


_INVALID = object()


def _int_like(value: object) -> int | object:
    if isinstance(value, bool):
        return _INVALID
    if isinstance(value, int):
        return value
    if isinstance(value, Real):
        try:
            return int(value) if math.isfinite(value) and value == int(value) else _INVALID
        except (OverflowError, TypeError, ValueError):
            return _INVALID
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    return _INVALID


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


async def _scroll_and_check(page: Any) -> None:
    await _scroll(page)
    await _raise_for_page_challenge(page)


def _page_items(payload: Mapping[str, Any], source: str) -> tuple[list[Mapping[str, Any]], bool, object]:
    if source == "creator":
        raw_items = _items(payload.get("aweme_list"))
        cursor = payload.get("max_cursor")
    else:
        raw_items = [_unwrap_search_aweme(item) for item in _items(payload.get("data"))]
        cursor = payload.get("cursor", payload.get("offset"))
    return [item for item in raw_items if isinstance(item, Mapping)], _has_more(payload.get("has_more")), cursor


def _unwrap_search_aweme(value: object) -> Mapping[str, Any] | None:
    item = _mapping(value)
    aweme = item.get("aweme_info")
    if isinstance(aweme, Mapping):
        return aweme
    mix_items = _items(_mapping(item.get("aweme_mix_info")).get("mix_items"))
    if mix_items and isinstance(mix_items[0], Mapping):
        return mix_items[0]
    return item if _safe_aweme_id(item.get("aweme_id")) is not None else None


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
    aweme_id = _safe_aweme_id(item.get("aweme_id"))
    author = _mapping(item.get("author"))
    statistics = _mapping(item.get("statistics"))
    video = _mapping(item.get("video"))
    duration = item.get("duration", video.get("duration"))
    publish_time = _publish_time(item.get("create_time"))
    published = _date(publish_time)
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
        "author_avatar": _first_safe_media_url(
            author.get("avatar_thumb"),
            author.get("avatar_medium"),
            author.get("avatar_larger"),
        ),
        "cover": _first_safe_media_url(
            video.get("cover"),
            video.get("dynamic_cover"),
            video.get("origin_cover"),
            item.get("cover"),
        ),
        "published_at": published,
        "publish_time": publish_time,
        "publish_date": _publish_date(publish_time),
        "date_precision": "second" if publish_time is not None else None,
        "date_source": "api" if publish_time is not None else None,
        "observed_at": observed_at or _observed_at(),
    }


def _require_open_target(page: Any, target: str, message: str) -> None:
    parsed = urlparse(getattr(page, "url", ""))
    expected = urlparse(target)
    actual_segments = tuple(unquote(segment) for segment in parsed.path.split("/"))
    expected_segments = tuple(unquote(segment) for segment in expected.path.split("/"))
    if parsed.scheme != "https" or parsed.hostname != _DOUYIN_HOST or actual_segments != expected_segments:
        raise PreconditionError(message)
    intended_segment = expected_segments[-1]
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(value != intended_segment for key in _CONTENT_QUERY_KEYS for value in query.get(key, ())):
        raise PreconditionError(message)


def _creator_page_url(uid: str) -> str:
    return f"https://{_DOUYIN_HOST}/user/{quote(uid, safe='')}"


def _search_page_url(keyword: str) -> str:
    return f"https://{_DOUYIN_HOST}/search/{quote(keyword, safe='')}"


def _video_link(aweme_id: str | None) -> str | None:
    validated = _safe_aweme_id(aweme_id)
    return f"https://{_DOUYIN_HOST}/video/{validated}" if validated else None


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


def _safe_aweme_id(value: object) -> str | None:
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    return text if isinstance(text, str) and _AWEME_ID_PATTERN.fullmatch(text) else None


def _first_media_url(value: object) -> str | None:
    if isinstance(value, str):
        return _safe_content_url(value)
    media = _mapping(value)
    for candidate in _items(media.get("url_list")):
        if (url := _safe_content_url(candidate)) is not None:
            return url
    for field in ("url", "uri"):
        if (url := _safe_content_url(media.get(field))) is not None:
            return url
    return None


def _first_safe_media_url(*values: object) -> str | None:
    for value in values:
        if (url := _first_media_url(value)) is not None:
            return url
    return None


def _safe_content_url(value: object) -> str | None:
    text = _text(value)
    if text is None or len(text) > 8192:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    try:
        parsed = urlparse(text)
        valid_origin = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return None
    if not valid_origin:
        return None
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not _SENSITIVE_URL_KEY.search(key) and not _SENSITIVE_URL_VALUE.search(item)
        ],
        doseq=True,
    )
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


def _metric(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    if isinstance(value, int):
        return value
    try:
        return value if math.isfinite(value) else None
    except (OverflowError, TypeError, ValueError):
        return None


def _date(value: object) -> str | None:
    seconds = _publish_time(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _publish_time(value: object) -> int | None:
    seconds = _int_like(value)
    if not isinstance(seconds, int) or seconds <= 0:
        return None
    try:
        datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return seconds


def _publish_date(value: object) -> str | None:
    seconds = _publish_time(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, _CHINA_TIMEZONE).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()
