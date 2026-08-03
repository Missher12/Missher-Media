from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape, unescape
from html.parser import HTMLParser
from numbers import Real
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

from ..browser import BrowserSession, PreconditionError
from ..models import CollectionRequest
from ..safety import classify_response

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - production dependency is optional in unit tests
    PlaywrightTimeoutError = TimeoutError


_WEIBO_HOSTS = ("weibo.com", "www.weibo.com")
_SEARCH_HOST = "s.weibo.com"
_CREATOR_PATH = "/ajax/statuses/mymblog"
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_RISK_CODES = frozenset({461, 471, 999})
_CHALLENGE_REASONS = frozenset({"challenge-selector", "请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控", "安全验证", "验证码"})
_MAX_RAW_HTML = 4096
_MISSING = object()


class CollectionStopped(RuntimeError):
    """A platform risk or verification signal requires collection to stop."""


class SourceResponseError(RuntimeError):
    """A browser-observed Weibo source response was not usable."""


@dataclass(slots=True)
class WeiboCollector:
    request: CollectionRequest
    browser: BrowserSession | Any

    async def collect(self) -> list[dict[str, Any]]:
        return await (self.collect_creator() if self.request.uid is not None else self.search())

    async def collect_creator(self) -> list[dict[str, Any]]:
        if self.request.uid is None:
            raise ValueError("creator collection requires uid")
        if self.request.complete:
            raise ValueError("complete creator is not supported")
        page = self.browser.require_page("weibo")
        target = _creator_page_url(self.request.uid)
        if not getattr(self.browser, "allow_navigation", False):
            _require_open_creator_target(page, target)
        await _raise_for_page_challenge(page)
        if not getattr(self.browser, "allow_navigation", False):
            raise PreconditionError("Weibo creator collection requires authorized navigation/reload")
        response = await _capture_creator_while(page, lambda: self._navigate_and_check(page, target, _WEIBO_HOSTS))
        return await self._collect_creator_pages(page, response)

    async def _collect_creator_pages(self, page: Any, response: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        prior_since: object = _MISSING
        for page_number in range(self.request.page_cap):
            await _raise_for_page_challenge(page)
            data = _creator_data(await _response_payload(response))
            since_id = data.get("since_id")
            # A repeated cursor means the browser has not advanced; do not count
            # a potentially replayed page toward the requested result.
            if prior_since is not _MISSING and since_id == prior_since:
                break
            added = _append_creator_records(records, seen, _items(data.get("list")), self.request.target_count)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 or _empty_cursor(since_id):
                break
            total = _metric(data.get("total"))
            if total is not None and len(records) >= total:
                break
            if page_number + 1 >= self.request.page_cap:
                break
            prior_since = since_id
            try:
                response = await _capture_creator_while(page, lambda: _scroll_and_check(page))
            except PlaywrightTimeoutError:
                break
        return records

    async def search(self) -> list[dict[str, Any]]:
        if self.request.keyword is None:
            raise ValueError("search requires keyword")
        if self.request.complete:
            raise ValueError("complete search is not supported")
        page = self.browser.require_page("weibo")
        target = _search_page_url(self.request.keyword)
        try:
            if getattr(self.browser, "allow_navigation", False):
                await self._navigate_and_wait_search(page, target)
            else:
                _require_open_search_target(page, self.request.keyword)
                await _wait_for_search_cards_or_challenge(page)
        except PlaywrightTimeoutError:
            await _raise_for_page_challenge(page)
            return []
        await _raise_for_page_challenge(page)

        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page_number in range(self.request.page_cap):
            observation = await _read_search_cards(page)
            _raise_for_risk_observation(observation)
            added = _append_search_records(records, seen, _items(observation.get("cards")), self.request.keyword, self.request.target_count)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 or page_number + 1 >= self.request.page_cap:
                break
            next_url = _valid_next_search_url(observation.get("next"), self.request.keyword)
            if next_url is None:
                break
            try:
                await self._navigate_and_wait_search(page, next_url)
            except PlaywrightTimeoutError:
                await _raise_for_page_challenge(page)
                break
            await _raise_for_page_challenge(page)
        return records

    async def _navigate_and_check(self, page: Any, url: str, hosts: tuple[str, ...]) -> None:
        response = await self.browser.navigate(page, url, allowed_hosts=hosts)
        _raise_for_navigation_status(response)
        await _raise_for_page_challenge(page)

    async def _navigate_and_wait_search(self, page: Any, url: str) -> None:
        response = await self.browser.navigate(page, url, allowed_hosts=(_SEARCH_HOST,))
        _raise_for_navigation_status(response)
        await _wait_for_search_cards_or_challenge(page)


async def collect_creator(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await WeiboCollector(request, browser).collect_creator()


async def search(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await WeiboCollector(request, browser).search()


async def _capture_creator_while(page: Any, action: Callable[[], Any]) -> Any:
    async with page.expect_response(_is_creator_response, timeout=10_000) as response_info:
        await action()
    return await response_info.value


def _is_creator_response(response: Any) -> bool:
    parsed = urlparse(getattr(response, "url", ""))
    return parsed.hostname in _WEIBO_HOSTS and parsed.path == _CREATOR_PATH


async def _response_payload(response: Any) -> Mapping[str, Any]:
    status = getattr(response, "status", None)
    if isinstance(status, bool) or not isinstance(status, int):
        raise SourceResponseError("Weibo source response has no numeric HTTP status")
    decision = classify_response(status=status)
    if decision.stop_all:
        raise CollectionStopped(decision.reason or "risk response")
    if not 200 <= status < 300:
        raise SourceResponseError(f"Weibo source returned http-{status}")
    try:
        payload = await response.json()
    except Exception as error:
        raise SourceResponseError("Weibo source JSON decode failed") from error
    if not isinstance(payload, Mapping):
        raise SourceResponseError("Weibo source returned a non-object JSON payload")
    _raise_for_payload_risk(payload)
    return payload


def _raise_for_payload_risk(payload: Mapping[str, Any]) -> None:
    if "code" not in payload:
        return
    code = _int_like(payload["code"])
    if code is None:
        raise SourceResponseError("Weibo payload code is not an integer")
    if code in _RISK_CODES:
        raise CollectionStopped(f"payload-{code}")
    if code != 0:
        raise SourceResponseError(f"Weibo payload returned code {code}")


def _creator_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    ok = payload.get("ok")
    if isinstance(ok, bool) or not isinstance(ok, int) or ok != 1:
        raise SourceResponseError("Weibo creator payload ok is not 1")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise SourceResponseError("Weibo creator payload data is not an object")
    if not isinstance(data.get("list"), Sequence) or isinstance(data.get("list"), (str, bytes, bytearray)):
        raise SourceResponseError("Weibo creator payload list is not an array")
    return data


def parse_creator_item(item: Mapping[str, Any], *, author_domain: str | None = None, observed_at: str | None = None) -> dict[str, Any]:
    user = _mapping(item.get("user"))
    mblog_id = _safe_id(item.get("mblogid")) or _safe_id(item.get("idstr")) or _safe_id(item.get("id"))
    domain = _safe_id(author_domain) or _safe_id(user.get("domain")) or "u"
    link = _post_link(mblog_id, domain)
    text = clean_html(_text(item.get("text_raw")) or _text(item.get("text")))
    published = _text(item.get("created_at"))
    pic_ids = _safe_picture_ids(item)
    return {
        "platform": "weibo", "type": "post", "mblog_id": mblog_id, "title": text, "link": link, "date": published,
        "liked": _metric(item.get("attitudes_count")), "comments": _metric(item.get("comments_count")),
        "shares": _metric(item.get("reposts_count")), "collected": None, "pics": pic_ids, "source": _text(item.get("source")),
        "id": mblog_id, "native_id": mblog_id, "url": link, "author": _text(user.get("screen_name")),
        "published_at": published, "observed_at": observed_at or _observed_at(),
    }


def parse_search_item(item: Mapping[str, Any], keyword: str, *, observed_at: str | None = None) -> dict[str, Any]:
    mblog_id = _safe_id(item.get("mblogid")) or _safe_id(item.get("mid")) or _safe_id(item.get("idstr")) or _safe_id(item.get("id"))
    domain = _safe_id(item.get("author_domain")) or "u"
    link = _post_link(mblog_id, domain)
    text = clean_html(_text(item.get("text")) or _text(item.get("text_raw")))
    published = _text(item.get("date")) or _text(item.get("created_at"))
    raw_html = sanitize_raw_html(_text(item.get("raw_html")))
    return {
        "platform": "weibo", "type": "post", "mblog_id": mblog_id, "title": text, "link": link, "date": published,
        "liked": _metric(item.get("liked")), "comments": _metric(item.get("comments")), "shares": _metric(item.get("shares")),
        "collected": _metric(item.get("collected")), "source": _text(item.get("source")), "raw_html": raw_html,
        "search_keyword": keyword, "id": mblog_id, "native_id": mblog_id, "url": link,
        "author": _text(item.get("author")), "published_at": published, "observed_at": observed_at or _observed_at(),
    }


def _append_creator_records(records: list[dict[str, Any]], seen: set[str], items: list[Any], target: int | None) -> int:
    added = 0
    observed_at = _observed_at()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record = parse_creator_item(item, observed_at=observed_at)
        native_id = record["native_id"]
        if not isinstance(native_id, str) or native_id in seen:
            continue
        seen.add(native_id)
        records.append(record)
        added += 1
        if target is not None and len(records) >= target:
            break
    return added


def _append_search_records(records: list[dict[str, Any]], seen: set[str], items: list[Any], keyword: str, target: int | None) -> int:
    added = 0
    observed_at = _observed_at()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record = parse_search_item(item, keyword, observed_at=observed_at)
        native_id = record["native_id"]
        if not isinstance(native_id, str) or native_id in seen:
            continue
        seen.add(native_id)
        records.append(record)
        added += 1
        if target is not None and len(records) >= target:
            break
    return added


async def _read_search_cards(page: Any) -> Mapping[str, Any]:
    result = await page.evaluate(
        """() => {
            const bodyText = document.body?.innerText || '';
            const challenge = document.querySelector('.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], [class*="captcha"], [class*="verify"]');
            const phrases = ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控', '安全验证', '验证码'];
            const risk_text = challenge ? 'challenge-selector' : (phrases.find((phrase) => bodyText.includes(phrase)) || '');
            const cards = Array.from(document.querySelectorAll('#pl_feedlist_index .card-wrap[mid]')).map((card) => {
                const content = card.querySelector('.card-feed .content');
                const full = content?.querySelector('[node-type="feed_list_content_full"]');
                const short = content?.querySelector('[node-type="feed_list_content"]');
                const from = card.querySelector('.from a');
                const metric = (type) => {
                    const text = card.querySelector(`[action-type="${type}"]`)?.textContent || '';
                    const matched = text.replace(/,/g, '').match(/\\d+/);
                    return matched ? Number(matched[0]) : null;
                };
                const href = from?.getAttribute('href') || null;
                const authorDomain = href?.match(/^\\/([^\\/?#]+)\\//)?.[1] || null;
                return {
                    mid: card.getAttribute('mid'), text: full?.innerHTML || short?.innerHTML || content?.innerHTML || null,
                    raw_html: full?.outerHTML || short?.outerHTML || content?.outerHTML || null,
                    date: from?.textContent || null, href, author_domain: authorDomain,
                    author: card.querySelector('.name')?.textContent || null,
                    shares: metric('feed_list_forward'), comments: metric('feed_list_comment'),
                    collected: metric('feed_list_favorite'), liked: metric('feed_list_like'),
                    source: card.querySelector('.from')?.textContent || null,
                };
            });
            return {risk_text, cards, next: document.querySelector('.m-page a.next')?.href || null};
        }"""
    )
    return result if isinstance(result, Mapping) else {"risk_text": "", "cards": [], "next": None}


async def _raise_for_page_challenge(page: Any) -> None:
    result = await page.evaluate(
        """() => {
            const bodyText = document.body?.innerText || '';
            const selector = document.querySelector('.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], [class*="captcha"], [class*="verify"]');
            const phrases = ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控', '安全验证', '验证码'];
            return {risk_text: selector ? 'challenge-selector' : (phrases.find((phrase) => bodyText.includes(phrase)) || '')};
        }"""
    )
    _raise_for_risk_observation(result)


async def _wait_for_search_cards_or_challenge(page: Any) -> None:
    await page.wait_for_function(
        """() => {
            const bodyText = document.body?.innerText || '';
            const phrases = ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控', '安全验证', '验证码'];
            return document.querySelector('#pl_feedlist_index .card-wrap[mid]')
                || document.querySelector('.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], [class*="captcha"], [class*="verify"]')
                || phrases.some((phrase) => bodyText.includes(phrase));
        }""",
        timeout=10_000,
    )


async def _scroll(page: Any) -> None:
    await page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")


async def _scroll_and_check(page: Any) -> None:
    await _scroll(page)
    await _raise_for_page_challenge(page)


def _raise_for_navigation_status(response: Any) -> None:
    status = getattr(response, "status", None)
    if isinstance(status, int) and classify_response(status=status).stop_all:
        raise CollectionStopped(f"http-{status}")


def _raise_for_risk_observation(observation: object) -> None:
    text = _mapping(observation).get("risk_text")
    if isinstance(text, str) and text in _CHALLENGE_REASONS:
        raise CollectionStopped(text)


def _require_open_creator_target(page: Any, target: str) -> None:
    actual, expected = urlparse(getattr(page, "url", "")), urlparse(target)
    if actual.scheme != "https" or actual.hostname not in _WEIBO_HOSTS or actual.path != expected.path:
        raise PreconditionError("matching Weibo creator page is required when navigation is disabled")


def _require_open_search_target(page: Any, keyword: str) -> None:
    parsed = urlparse(getattr(page, "url", ""))
    query = parse_qs(parsed.query, keep_blank_values=True)
    if parsed.scheme != "https" or parsed.hostname != _SEARCH_HOST or parsed.path != "/weibo" or query.get("q") != [keyword]:
        raise PreconditionError("matching Weibo search page is required when navigation is disabled")


def _creator_page_url(uid: str) -> str:
    return f"https://weibo.com/u/{quote(uid, safe='')}"


def _search_page_url(keyword: str) -> str:
    return f"https://{_SEARCH_HOST}/weibo?{urlencode({'q': keyword})}"


def _valid_next_search_url(value: object, keyword: str) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if parsed.scheme != "https" or parsed.hostname != _SEARCH_HOST or parsed.path != "/weibo" or query.get("q") != [keyword]:
        return None
    # Discard fragments and userinfo while retaining the platform-generated
    # pagination parameters needed by the next page.
    return urlunparse(("https", _SEARCH_HOST, "/weibo", "", parsed.query, ""))


def _post_link(mblog_id: str | None, domain: str) -> str | None:
    if not mblog_id:
        return None
    if domain == "u":
        return f"https://weibo.com/detail/{mblog_id}"
    return f"https://weibo.com/{domain}/{mblog_id}"


def _safe_picture_ids(item: Mapping[str, Any]) -> list[str] | None:
    raw = _items(item.get("pic_ids"))
    if not raw:
        raw = list(_mapping(item.get("pic_infos")).keys())
    values = [value for value in (_safe_id(item) for item in raw) if value is not None]
    return values or None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _safe_id(value: object) -> str | None:
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    return text if isinstance(text, str) and _SAFE_ID.fullmatch(text) else None


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _metric(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    if isinstance(value, int):
        return value
    try:
        return value if math.isfinite(value) else None
    except (OverflowError, TypeError, ValueError):
        return None


def _int_like(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    return None


def _empty_cursor(value: object) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style"}:
            self.skip_depth += 1
        elif not self.skip_depth and tag.casefold() in {"br", "p", "div", "li", "section", "article"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag.casefold() in {"p", "div", "li", "section", "article"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def clean_html(value: str | None) -> str | None:
    if not value:
        return None
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    cleaned = " ".join(unescape("".join(parser.parts)).split())
    return cleaned or None


class _SafeMarkup(HTMLParser):
    _DROP = frozenset({"script", "style", "form", "iframe", "input", "textarea", "button", "select", "option"})
    _VOID = frozenset({"br", "hr", "img", "meta", "link"})
    _ALLOWED = frozenset({"a", "b", "strong", "i", "em", "span", "p", "div", "br", "ul", "ol", "li", "blockquote", "code", "pre", "img"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.casefold()
        if name in self._DROP:
            self.drop_depth += 1
            return
        if self.drop_depth or name not in self._ALLOWED:
            return
        safe_attrs = []
        for key, value in attrs:
            lowered = key.casefold()
            text = value or ""
            if re.search(r"(?:token|secret|password|passwd|credential|cookie|auth)", text, re.I):
                continue
            if lowered.startswith("on") or lowered in {"href", "src", "action", "formaction", "style"}:
                continue
            if lowered in {"class", "title", "alt", "aria-label"}:
                safe_attrs.append((lowered, text))
        rendered = "".join(f' {key}="{_escape_attr(value)}"' for key, value in safe_attrs)
        self.parts.append(f"<{name}{rendered}>")

    def handle_endtag(self, tag: str) -> None:
        name = tag.casefold()
        if name in self._DROP and self.drop_depth:
            self.drop_depth -= 1
        elif not self.drop_depth and name in self._ALLOWED and name not in self._VOID:
            self.parts.append(f"</{name}>")

    def handle_data(self, data: str) -> None:
        if not self.drop_depth:
            self.parts.append(escape(data, quote=False))


def _escape_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def sanitize_raw_html(value: str | None) -> str | None:
    if not value:
        return None
    parser = _SafeMarkup()
    parser.feed(value)
    parser.close()
    result = "".join(parser.parts)[:_MAX_RAW_HTML]
    return result or None
