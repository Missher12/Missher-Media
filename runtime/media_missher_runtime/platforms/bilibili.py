from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any
from urllib.parse import urlencode, urlparse

from ..browser import BrowserSession, PageJson, PreconditionError
from ..models import CollectionRequest
from ..safety import classify_response

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - production browser dependency is optional in unit tests
    PlaywrightTimeoutError = TimeoutError


_BILIBILI_HOSTS = (
    "bilibili.com",
    "www.bilibili.com",
    "space.bilibili.com",
    "search.bilibili.com",
    "api.bilibili.com",
    "t.bilibili.com",
)
_API_HOST = "api.bilibili.com"
_FEED_PATH = "/x/polymer/web-dynamic/v1/feed/space"
_TAG_PATTERN = re.compile(r"<[^>]+>")
_PLACEHOLDER_TITLES = frozenset({"", "-", "--", "暂无标题", "untitled"})
_CHALLENGE_REASONS = frozenset({"challenge-selector", "请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控"})


class CollectionStopped(RuntimeError):
    """A platform-wide risk response requires collection to stop immediately."""


class SourceResponseError(RuntimeError):
    """A browser-generated source response could not be consumed safely."""


@dataclass(slots=True)
class BilibiliCollector:
    request: CollectionRequest
    browser: BrowserSession | Any

    async def collect(self) -> list[dict[str, Any]]:
        return await (self.collect_creator() if self.request.uid is not None else self.search())

    async def collect_creator(self) -> list[dict[str, Any]]:
        if self.request.uid is None:
            raise ValueError("creator collection requires uid")
        page = self.browser.require_page("bilibili")
        response = await _capture_feed_while(
            page,
            lambda: self._navigate(page, _creator_page_url(self.request.uid)),
        )
        records = await self._collect_feed_pages(page, response)
        if self.request.complete:
            for record in records:
                await self._complete_record(page, record)
        else:
            for record in records:
                record["complete"] = False
                record["detail_completed"] = False
                record["missing_fields"] = []
        return records

    async def _collect_feed_pages(self, page: Any, response: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        native_ids: set[str] = set()
        for page_number in range(self.request.page_cap):
            data = _feed_data(await _response_payload(response))
            added = _append_creator_records(records, native_ids, _items(data.get("items")), self.request.target_count)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 or not data.get("has_more") or page_number + 1 >= self.request.page_cap:
                break
            try:
                response = await _capture_feed_while(page, lambda: _scroll(page))
            except PlaywrightTimeoutError:
                break
        return records

    async def search(self) -> list[dict[str, Any]]:
        if self.request.keyword is None:
            raise ValueError("search requires keyword")
        if self.request.complete:
            raise ValueError("complete search is not supported")
        page = self.browser.require_page("bilibili")
        if getattr(self.browser, "allow_navigation", False):
            await self._navigate(page, _search_page_url(self.request.keyword))
            try:
                await _wait_for_search_change(page, [])
            except PlaywrightTimeoutError:
                pass
        elif urlparse(page.url).hostname != "search.bilibili.com":
            raise PreconditionError("an open Bilibili search page is required when navigation is disabled")

        records: list[dict[str, Any]] = []
        native_ids: set[str] = set()
        for page_number in range(self.request.page_cap):
            observation = await _read_search_cards(page)
            _raise_for_risk_observation(observation)
            raw_records = [item for item in _items(observation.get("cards")) if isinstance(item, Mapping)]
            added = _append_search_records(records, native_ids, raw_records, self.request.keyword, self.request.target_count)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 or page_number + 1 >= self.request.page_cap:
                break
            await _scroll(page)
            try:
                await _wait_for_search_change(page, sorted(native_ids))
            except PlaywrightTimeoutError:
                break
        return records

    async def _complete_record(self, page: Any, record: dict[str, Any]) -> None:
        detail_received = False
        bvid = record.get("bvid")
        if isinstance(bvid, str) and bvid and getattr(self.browser, "allow_navigation", False):
            await self._navigate(page, _video_page_url(bvid))
            observation = await _read_video_detail(page)
            _raise_for_risk_observation(observation)
            video_data = _mapping(observation.get("videoData"))
            if _valid_video_data(video_data, bvid):
                _merge_video_detail(record, video_data)
                detail_received = True
        missing = _missing_completion_fields(record, detail_received)
        record["detail_completed"] = detail_received
        record["complete"] = not missing
        record["missing_fields"] = missing

    async def _navigate(self, page: Any, url: str) -> None:
        response = await self.browser.navigate(page, url, allowed_hosts=_BILIBILI_HOSTS)
        status = getattr(response, "status", None)
        if isinstance(status, int):
            decision = classify_response(status=status)
            if decision.stop_all:
                raise CollectionStopped(decision.reason or "risk response")


async def collect_creator(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await BilibiliCollector(request, browser).collect_creator()


async def search(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await BilibiliCollector(request, browser).search()


def parse_creator_item(item: Mapping[str, Any], *, observed_at: str | None = None) -> dict[str, Any]:
    modules = _mapping(item.get("modules"))
    dynamic = _mapping(modules.get("module_dynamic"))
    author_module = _mapping(modules.get("module_author"))
    module_stats = _mapping(modules.get("module_stat"))
    archive = _mapping(_mapping(dynamic.get("major")).get("archive"))
    archive_stats = _mapping(archive.get("stat"))
    dynamic_id = _text(item.get("id_str"))
    bvid = _text(archive.get("bvid"))
    dynamic_text = _text(_mapping(dynamic.get("desc")).get("text"))
    title = _text(archive.get("title")) or dynamic_text
    desc = _text(archive.get("desc")) or dynamic_text
    published = _date(author_module.get("pub_ts"))
    liked = _metric(module_stats, "like", fallback=archive_stats.get("like"))
    comments = _metric(module_stats, "comment", fallback=module_stats.get("reply", archive_stats.get("reply")))
    shares = _metric(module_stats, "forward", fallback=archive_stats.get("share"))
    collected = _metric(module_stats, "favorite", fallback=archive_stats.get("favorite"))
    link = _creator_link(dynamic_id, bvid)
    native_id = dynamic_id or bvid
    return {
        "platform": "bilibili", "type": "video" if bvid else "dynamic", "dynamic_id": dynamic_id, "bvid": bvid,
        "title": title, "desc": desc, "link": link, "date": published,
        "date_precision": "second" if published is not None else None,
        "liked": liked, "comments": comments, "shares": shares, "collected": collected,
        "id": native_id, "native_id": native_id, "url": link, "author": _text(author_module.get("name")),
        "published_at": published, "detail_completed": False, "observed_at": observed_at or _observed_at(),
    }


def parse_search_item(item: Mapping[str, Any], keyword: str, *, observed_at: str | None = None) -> dict[str, Any]:
    bvid = _text(item.get("bvid")) or _bvid_from_href(item.get("href") or item.get("arcurl"))
    link = _search_link(bvid, item.get("href") or item.get("arcurl"))
    published = _date(item.get("pubdate") if "pubdate" in item else item.get("date"))
    return {
        "platform": "bilibili", "type": "video", "bvid": bvid, "native_id": bvid,
        "title": _clean_text(item.get("title")), "desc": _clean_text(item.get("description")) or _clean_text(item.get("desc")),
        "link": link, "date": published, "liked": _metric(item, "like"), "comments": _metric(item, "review", fallback=item.get("comment")),
        "shares": _metric(item, "share"), "collected": _metric(item, "favorite"), "search_keyword": keyword,
        "id": bvid, "url": link, "author": _text(item.get("author")), "published_at": published,
        "detail_completed": False, "observed_at": observed_at or _observed_at(),
    }


async def _capture_feed_while(page: Any, action: Any) -> Any:
    async with page.expect_response(_is_feed_response, timeout=10_000) as response_info:
        await action()
    return await response_info.value


def _is_feed_response(response: Any) -> bool:
    parsed = urlparse(response.url)
    return parsed.hostname == _API_HOST and parsed.path == _FEED_PATH


async def _response_payload(response: Any) -> Mapping[str, Any]:
    status = getattr(response, "status", None)
    if isinstance(status, bool) or not isinstance(status, int):
        raise SourceResponseError("Bilibili source response has no numeric HTTP status")
    decision = classify_response(status=status)
    if decision.stop_all:
        raise CollectionStopped(decision.reason or "risk response")
    if not 200 <= status < 300:
        raise SourceResponseError(f"Bilibili source returned http-{status}")
    try:
        payload = await response.json()
    except Exception as error:
        raise SourceResponseError("Bilibili source JSON decode failed") from error
    if not isinstance(payload, Mapping):
        raise SourceResponseError("Bilibili source returned a non-object JSON payload")
    decision = classify_response(status=status, payload=payload, text=_response_text(payload))
    if decision.stop_all:
        raise CollectionStopped(decision.reason or "risk response")
    return payload


def _feed_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = _mapping(payload.get("data"))
    if payload.get("code") not in (None, 0, "0"):
        return {}
    return data


async def _read_search_cards(page: Any) -> Mapping[str, Any]:
    result = await page.evaluate(
        """() => {
            const bodyText = document.body?.innerText || '';
            const challengeSelector = document.querySelector(
                '.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], [class*="captcha"]'
            );
            const phrases = ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控'];
            const phrase = phrases.find((value) => bodyText.includes(value)) || '';
            return {
            risk_text: challengeSelector ? 'challenge-selector' : phrase,
            cards: Array.from(document.querySelectorAll('.bili-video-card, .bili-video-card__wrap'))
            .map((card) => {
                const link = card.querySelector('a[href*="/video/"]');
                const href = link?.getAttribute('href') || null;
                const bvid = href?.match(/\\/video\\/(BV[^/?#]+)/)?.[1] || null;
                const title = card.querySelector('[title]')?.getAttribute('title') || link?.textContent || null;
                const description = card.querySelector('.bili-video-card__info')?.textContent || null;
                return {bvid, title, href, description};
            })
            };
        }"""
    )
    if isinstance(result, Mapping):
        return result
    return {"risk_text": "", "cards": result}


async def _read_video_detail(page: Any) -> Mapping[str, Any]:
    observation = await page.evaluate(
        """() => {
            const bodyText = document.body?.innerText || '';
            const challengeSelector = document.querySelector(
                '.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], [class*="captcha"]'
            );
            const phrases = ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控'];
            const phrase = phrases.find((value) => bodyText.includes(value)) || '';
            return {
            videoData: window.__INITIAL_STATE__?.videoData || null,
            risk_text: challengeSelector ? 'challenge-selector' : phrase
            };
        }"""
    )
    return _mapping(observation)


async def _wait_for_search_change(page: Any, previous_ids: list[str]) -> None:
    await page.wait_for_function(
        """(previousIds) => {
            const bodyText = document.body?.innerText || '';
            const challenge = document.querySelector(
                '.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], [class*="captcha"]'
            ) || ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控']
                .some((phrase) => bodyText.includes(phrase));
            if (challenge) return true;
            const ids = Array.from(document.querySelectorAll('.bili-video-card a[href*="/video/"], .bili-video-card__wrap a[href*="/video/"]'))
                .map((link) => link.getAttribute('href')?.match(/\\/video\\/(BV[^/?#]+)/)?.[1])
                .filter(Boolean);
            const current = Array.from(new Set(ids)).sort();
            const previous = Array.from(new Set(previousIds)).sort();
            const changed = current.length !== previous.length || current.some((value, index) => value !== previous[index]);
            const ended = Boolean(document.querySelector(
                '.search-end, .vui_pagenation--btn-next[disabled], .vui_pagenation--btn-next.vui_button--disabled'
            ));
            return (current.length > 0 && changed) || ended;
        }""",
        arg=previous_ids,
        timeout=10_000,
    )


async def _scroll(page: Any) -> None:
    await page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")


def _append_creator_records(records: list[dict[str, Any]], native_ids: set[str], items: list[Any], target: int | None) -> int:
    added = 0
    observed_at = _observed_at()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record = parse_creator_item(item, observed_at=observed_at)
        native_id = record["native_id"]
        if not isinstance(native_id, str) or not native_id or native_id in native_ids:
            continue
        native_ids.add(native_id)
        records.append(record)
        added += 1
        if target is not None and len(records) >= target:
            break
    return added


def _append_search_records(records: list[dict[str, Any]], native_ids: set[str], items: list[Mapping[str, Any]], keyword: str, target: int | None) -> int:
    added = 0
    observed_at = _observed_at()
    for item in items:
        record = parse_search_item(item, keyword, observed_at=observed_at)
        native_id = record["native_id"]
        if not isinstance(native_id, str) or not native_id or native_id in native_ids:
            continue
        native_ids.add(native_id)
        records.append(record)
        added += 1
        if target is not None and len(records) >= target:
            break
    return added


def _creator_page_url(uid: str) -> str:
    return f"https://space.bilibili.com/{uid}/dynamic"


def _search_page_url(keyword: str) -> str:
    return f"https://search.bilibili.com/all?{urlencode({'keyword': keyword})}"


def _video_page_url(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_text(value: object) -> str | None:
    text = _text(value)
    return _TAG_PATTERN.sub("", text).strip() if text else None


def _metric(mapping: Mapping[str, Any], name: str, *, fallback: object = None) -> int | float | None:
    value = mapping.get(name, fallback)
    if isinstance(value, Mapping):
        value = value.get("count")
    return value if isinstance(value, Real) and not isinstance(value, bool) else None


def _date(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return value if isinstance(value, str) and value else None
    return datetime.fromtimestamp(value, UTC).isoformat()


def _creator_link(dynamic_id: str | None, bvid: str | None) -> str | None:
    return f"https://www.bilibili.com/video/{bvid}" if bvid else f"https://t.bilibili.com/{dynamic_id}" if dynamic_id else None


def _search_link(bvid: str | None, observed_url: object) -> str | None:
    if bvid:
        return _video_page_url(bvid)
    if isinstance(observed_url, str) and observed_url.startswith("/video/"):
        return f"https://www.bilibili.com{observed_url.split('?', 1)[0]}"
    return None


def _bvid_from_href(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"/video/(BV[^/?#]+)", value)
    return match.group(1) if match else None


def _response_text(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("message") or payload.get("msg") or payload.get("risk_text")
    return value if isinstance(value, str) else None


def _raise_for_risk_observation(observation: Mapping[str, Any]) -> None:
    text = _response_text(observation)
    if text in _CHALLENGE_REASONS or (text is not None and "captcha" in text.casefold()):
        raise CollectionStopped(text or "captcha")
    decision = classify_response(status=200, payload=observation, text=text)
    if decision.stop_all:
        raise CollectionStopped(decision.reason or "risk response")


def _valid_video_data(data: Mapping[str, Any], expected_bvid: str) -> bool:
    return data.get("bvid") == expected_bvid and all(key in data for key in ("title", "pubdate", "desc", "stat")) and isinstance(data.get("stat"), Mapping)


def _merge_video_detail(record: dict[str, Any], data: Mapping[str, Any]) -> None:
    stat = _mapping(data.get("stat"))
    record["title"] = _text(data.get("title"))
    record["desc"] = _text(data.get("desc"))
    record["date"] = _date(data.get("pubdate"))
    record["date_precision"] = "second" if record["date"] is not None else None
    record["published_at"] = record["date"]
    record["liked"] = _metric(stat, "like")
    record["comments"] = _metric(stat, "reply")
    record["shares"] = _metric(stat, "share")
    record["collected"] = _metric(stat, "favorite")


def _missing_completion_fields(record: Mapping[str, Any], detail_received: bool) -> list[str]:
    missing: list[str] = []
    if not _text(record.get("native_id")):
        missing.append("native_id")
    if _is_placeholder_title(record.get("title")):
        missing.append("title")
    if record.get("date") is None:
        missing.append("date")
    if not detail_received:
        missing.append("detail")
    for field in ("liked", "comments", "shares", "collected"):
        if record.get(field) is None:
            missing.append(field)
    return missing


def _is_placeholder_title(value: object) -> bool:
    title = _text(value)
    return title is None or title.casefold() in _PLACEHOLDER_TITLES


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()
