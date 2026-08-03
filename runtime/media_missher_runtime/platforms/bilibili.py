from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any
from urllib.parse import urlencode

from ..browser import BrowserSession, PageJson, PreconditionError
from ..models import CollectionRequest
from ..safety import classify_response


_BILIBILI_HOSTS = ("bilibili.com", "www.bilibili.com")
_DYNAMIC_ENDPOINT = "https://www.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
_TAG_PATTERN = re.compile(r"<[^>]+>")
_PLACEHOLDER_TITLES = frozenset({"", "-", "--", "暂无标题", "untitled"})


class CollectionStopped(RuntimeError):
    """A platform-wide risk response requires collection to stop immediately."""


@dataclass(slots=True)
class BilibiliCollector:
    request: CollectionRequest
    browser: BrowserSession | Any

    async def collect(self) -> list[dict[str, Any]]:
        if self.request.uid is not None:
            return await self.collect_creator()
        return await self.search()

    async def collect_creator(self) -> list[dict[str, Any]]:
        if self.request.uid is None:
            raise ValueError("creator collection requires uid")

        page = self.browser.require_page("bilibili")
        records: list[dict[str, Any]] = []
        native_ids: set[str] = set()
        offset = ""

        for _ in range(self.request.page_cap):
            response = await self.browser.page_json(page, _creator_url(self.request.uid, offset))
            payload = _check_response(response)
            data = _mapping(payload.get("data"))
            items = _items(data.get("items"))
            added = 0
            for item in items:
                record = parse_creator_item(item)
                native_id = record.get("dynamic_id")
                if not isinstance(native_id, str) or not native_id or native_id in native_ids:
                    continue
                native_ids.add(native_id)
                records.append(record)
                added += 1
                if self.request.target_count is not None and len(records) >= self.request.target_count:
                    break

            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 or not data.get("has_more"):
                break
            next_offset = data.get("offset")
            if not isinstance(next_offset, str) or not next_offset or next_offset == offset:
                break
            offset = next_offset

        if self.request.complete:
            for record in records:
                await self._complete_record(record)
        else:
            for record in records:
                record["complete"] = False
                record["missing_fields"] = []
        return records

    async def search(self) -> list[dict[str, Any]]:
        if self.request.keyword is None:
            raise ValueError("search requires keyword")
        if self.request.complete:
            raise ValueError("complete search is not supported")
        source = _require_search_capability(self.browser)
        response = None if source is None else await source(
            keyword=self.request.keyword,
            allow_navigation=True,
            allowed_hosts=_BILIBILI_HOSTS,
        )
        raw_records: list[Mapping[str, Any]]
        if response is None:
            fallback = getattr(self.browser, "search_bilibili_dom", None)
            if callable(fallback):
                raw = await fallback(
                    keyword=self.request.keyword,
                    allow_navigation=False,
                    allowed_hosts=_BILIBILI_HOSTS,
                )
            else:
                raw = await _open_page_search_dom(self.browser)
            raw_records = [item for item in _items(raw) if isinstance(item, Mapping)]
        else:
            payload = _check_response(response)
            data = _mapping(payload.get("data"))
            if data.get("is_risk"):
                raise CollectionStopped("payload-is_risk")
            listing = _mapping(data.get("list"))
            raw_records = [item for item in _items(listing.get("vlist")) if isinstance(item, Mapping)]

        records: list[dict[str, Any]] = []
        native_ids: set[str] = set()
        for item in raw_records:
            record = parse_search_item(item, self.request.keyword)
            native_id = record.get("native_id")
            if not isinstance(native_id, str) or not native_id or native_id in native_ids:
                continue
            native_ids.add(native_id)
            records.append(record)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
        return records

    async def _complete_record(self, record: dict[str, Any]) -> None:
        detail_received = False
        source = getattr(self.browser, "bilibili_detail", None)
        if callable(source):
            detail = await source(record=record, allow_navigation=True, allowed_hosts=_BILIBILI_HOSTS)
            if detail is not None:
                payload = _check_response(detail)
                if isinstance(payload, Mapping):
                    _merge_detail(record, payload)
                    detail_received = True
        missing = _missing_completion_fields(record, detail_received)
        record["complete"] = not missing
        record["missing_fields"] = missing


async def collect_creator(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await BilibiliCollector(request, browser).collect_creator()


async def search(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await BilibiliCollector(request, browser).search()


def parse_creator_item(item: Mapping[str, Any]) -> dict[str, Any]:
    modules = _mapping(item.get("modules"))
    dynamic = _mapping(modules.get("module_dynamic"))
    author = _mapping(modules.get("module_author"))
    stats = _mapping(modules.get("module_stat"))
    archive = _mapping(_mapping(dynamic.get("major")).get("archive"))
    dynamic_id = _text(item.get("id_str"))
    bvid = _text(archive.get("bvid"))
    dynamic_text = _text(_mapping(dynamic.get("desc")).get("text"))
    title = _text(archive.get("title")) or dynamic_text
    desc = _text(archive.get("desc")) or dynamic_text
    published = _date(author.get("pub_ts"))
    is_archive = bvid is not None
    return {
        "platform": "bilibili",
        "type": "video" if is_archive else "dynamic",
        "dynamic_id": dynamic_id,
        "bvid": bvid,
        "title": title,
        "desc": desc,
        "link": _creator_link(dynamic_id, bvid),
        "date": published,
        "date_precision": "second" if published is not None else None,
        "liked": _metric(stats, "like"),
        "comments": _metric(stats, "reply"),
        "shares": _metric(stats, "forward"),
        "collected": _metric(stats, "favorite"),
    }


def parse_search_item(item: Mapping[str, Any], keyword: str) -> dict[str, Any]:
    bvid = _text(item.get("bvid")) or _text(item.get("id"))
    return {
        "platform": "bilibili",
        "type": "video",
        "bvid": bvid,
        "native_id": bvid,
        "title": _clean_text(item.get("title")),
        "desc": _clean_text(item.get("description")) or _clean_text(item.get("desc")),
        "link": _search_link(bvid, item.get("arcurl") or item.get("href")),
        "date": _date(item.get("pubdate") if "pubdate" in item else item.get("date")),
        "liked": _metric(item, "like"),
        "comments": _metric(item, "review"),
        "shares": _metric(item, "share"),
        "collected": _metric(item, "favorite"),
        "search_keyword": keyword,
    }


def _creator_url(uid: str, offset: str) -> str:
    query: dict[str, str] = {"host_mid": uid}
    if offset:
        query["offset"] = offset
    return f"{_DYNAMIC_ENDPOINT}?{urlencode(query)}"


def _check_response(response: PageJson | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(response, PageJson):
        status, payload = response.status, response.payload
    else:
        status, payload = 200, response
    decision = classify_response(status=status, payload=payload, text=_response_text(payload))
    if decision.stop_all:
        raise CollectionStopped(decision.reason or "risk response")
    if not isinstance(payload, Mapping):
        raise ValueError("Bilibili source returned a non-object payload")
    return payload


def _response_text(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    message = payload.get("message") or payload.get("msg")
    return message if isinstance(message, str) else None


def _require_search_capability(browser: Any) -> Any | None:
    source = getattr(browser, "search_bilibili", None)
    hosts = getattr(browser, "bilibili_allowed_hosts", ())
    if callable(source):
        if set(_BILIBILI_HOSTS).issubset(set(hosts)):
            return source
        raise PreconditionError("Bilibili search source must be explicitly allowlisted")
    if callable(getattr(browser, "require_page", None)):
        return None
    raise PreconditionError("Bilibili search source must be explicitly allowlisted")


async def _open_page_search_dom(browser: Any) -> list[dict[str, Any]]:
    """Read semantic cards from an already-open search page without navigating."""
    page = browser.require_page("bilibili")
    records = await page.evaluate(
        """() => Array.from(document.querySelectorAll('.bili-video-card, .bili-video-card__wrap'))
            .map((card) => {
                const link = card.querySelector('a[href*="/video/"]');
                const href = link?.getAttribute('href') || null;
                const bvid = href?.match(/\\/video\\/(BV[^/?#]+)/)?.[1] || null;
                const title = card.querySelector('[title]')?.getAttribute('title') || link?.textContent || null;
                const text = card.querySelector('.bili-video-card__info')?.textContent || null;
                return {bvid, title, href, description: text};
            })"""
    )
    return [item for item in _items(records) if isinstance(item, dict)]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_text(value: object) -> str | None:
    text = _text(value)
    return _TAG_PATTERN.sub("", text).strip() if text else None


def _metric(mapping: Mapping[str, Any], name: str) -> int | float | None:
    value = mapping.get(name)
    return value if isinstance(value, Real) and not isinstance(value, bool) else None


def _date(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return value if isinstance(value, str) and value else None
    return datetime.fromtimestamp(value, UTC).isoformat()


def _creator_link(dynamic_id: str | None, bvid: str | None) -> str | None:
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"
    return f"https://t.bilibili.com/{dynamic_id}" if dynamic_id else None


def _search_link(bvid: str | None, observed_url: object) -> str | None:
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"
    if isinstance(observed_url, str) and observed_url.startswith("/video/"):
        return f"https://www.bilibili.com{observed_url.split('?', 1)[0]}"
    return None


def _merge_detail(record: dict[str, Any], detail: Mapping[str, Any]) -> None:
    for field in ("title", "desc", "liked", "comments", "shares", "collected"):
        if field in detail and detail[field] is not None:
            record[field] = detail[field]
    if "date" in detail and detail["date"] is not None:
        record["date"] = _date(detail["date"])
        record["date_precision"] = "second" if record["date"] is not None else None


def _missing_completion_fields(record: Mapping[str, Any], detail_received: bool) -> list[str]:
    missing: list[str] = []
    if not _text(record.get("dynamic_id")) and not _text(record.get("bvid")):
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
