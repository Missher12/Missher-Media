from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from numbers import Real
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from ..browser import BrowserSession, PageJson, PreconditionError
from ..detail_open import missing_engagement_fields
from ..models import CollectionRequest
from ..safety import classify_response
from ..screenshots import ScreenshotError

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - production browser dependency is optional in unit tests
    PlaywrightError = RuntimeError
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
_CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
_MAX_TITLE_CHARS = 100
_MAX_DESC_CHARS = 20_000
_DYNAMIC_TARGET_TIMEOUT_MS = 5_000
_SENSITIVE_URL_PART = re.compile(
    r"(?:token|secret|password|passwd|credential|cookie|session|authorization|xsec|auth|signature|sign|expires?|expiry)",
    re.IGNORECASE,
)


class CollectionStopped(RuntimeError):
    """A platform-wide risk response requires collection to stop immediately."""


class SourceResponseError(RuntimeError):
    """A browser-generated source response could not be consumed safely."""


def _needs_dynamic_open(
    request: CollectionRequest, record: Mapping[str, Any]
) -> bool:
    dynamic_id = record.get("dynamic_id")
    return (
        record.get("bvid") is None
        and isinstance(dynamic_id, str)
        and bool(dynamic_id)
        and (
            request.screenshot_mode == "all"
            or (
                request.browser_assist == "browserskill"
                and bool(missing_engagement_fields(record))
            )
        )
    )


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
        for record in records:
            opened_video = False
            if self.request.complete:
                opened_video = await self._complete_record(page, record)
            else:
                record["complete"] = False
                record["detail_completed"] = False
                record["missing_fields"] = []
            if _needs_dynamic_open(self.request, record):
                await self._ensure_creator_feed(page, record["dynamic_id"])
                await self._open_dynamic_record(page, record)
            elif (
                isinstance(record.get("bvid"), str)
                and self.request.screenshot_mode == "all"
                and not opened_video
            ):
                await self._open_video_for_screenshot(page, record)
            elif opened_video and self.request.screenshot_mode in {"opened", "all"}:
                await self._capture_verified_video_screenshot(
                    page,
                    record,
                    record["bvid"],
                )
        return records

    async def _ensure_creator_feed(self, page: Any, dynamic_id: str) -> None:
        if self.request.uid is None:
            raise ValueError("creator collection requires uid")
        creator_url = _creator_page_url(self.request.uid)
        if getattr(page, "url", None) != creator_url:
            await self._navigate(page, creator_url)
        try:
            await _wait_for_exact_dynamic_target(page, dynamic_id)
        except PlaywrightTimeoutError as error:
            observation = await _read_dynamic_feed_risk(page)
            _raise_for_risk_observation(observation)
            raise PreconditionError(
                "exact Bilibili dynamic target unavailable"
            ) from error
        observation = await _read_dynamic_feed_risk(page)
        _raise_for_risk_observation(observation)

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

    async def _complete_record(self, page: Any, record: dict[str, Any]) -> bool:
        detail_received = False
        detail_attempted = False
        bvid = record.get("bvid")
        detail_required = isinstance(bvid, str) and bool(bvid)
        if detail_required and getattr(self.browser, "allow_navigation", False):
            detail_attempted = True
            await self._navigate(page, _video_page_url(bvid))
            observation = await _read_video_detail(page)
            _raise_for_risk_observation(observation)
            video_data = _mapping(observation.get("videoData"))
            if _valid_video_data(video_data, bvid):
                _merge_video_detail(record, video_data)
                detail_received = True
        missing = _missing_completion_fields(
            record,
            detail_received,
            detail_required=detail_required,
        )
        record["detail_attempted"] = detail_attempted
        record["detail_source"] = "detail_api" if detail_received else "list_api"
        record["detail_completed"] = detail_received or not detail_required
        record["complete"] = not missing
        record["missing_fields"] = missing
        record["quality_score"] = _quality_score(record)
        return detail_attempted

    async def _open_dynamic_record(self, page: Any, record: dict[str, Any]) -> None:
        dynamic_id = record.get("dynamic_id")
        if not isinstance(dynamic_id, str) or not dynamic_id:
            raise PreconditionError("exact Bilibili dynamic identifier is invalid")
        coordinator = getattr(self.browser, "detail_open", None)
        if coordinator is None:
            raise PreconditionError("exact detail coordinator is unavailable")
        target = await _find_exact_dynamic_target(page, dynamic_id)
        detail_page = page
        try:
            record["detail_attempted"] = True
            detail_page = await coordinator.click_exact(
                page,
                target,
                platform="bilibili",
                native_id=dynamic_id,
            )
            observation = await _read_dynamic_detail(detail_page, dynamic_id)
            _raise_for_risk_observation(observation)
            merged = _merge_dynamic_detail(record, observation)
            missing_engagement = list(missing_engagement_fields(record))
            record["detail_source"] = "detail_dom" if merged else "list_api"
            record["detail_completed"] = not missing_engagement
            missing = _missing_completion_fields(
                record,
                detail_received=not missing_engagement,
                detail_required=False,
            )
            record["missing_fields"] = missing
            record["complete"] = not missing
            record["quality_score"] = _quality_score(record)
            if self.request.screenshot_mode in {"opened", "all"}:
                await self._capture_screenshot(detail_page, record, dynamic_id)
        finally:
            await _dispose_element_handle(target)
            if detail_page is not page:
                release = getattr(coordinator, "release", None)
                if release is not None:
                    await release(detail_page)

    async def _open_video_for_screenshot(
        self, page: Any, record: dict[str, Any]
    ) -> None:
        bvid = record.get("bvid")
        if not isinstance(bvid, str) or not bvid:
            raise PreconditionError("exact Bilibili video identifier is invalid")
        record["detail_attempted"] = True
        await self._navigate(page, _video_page_url(bvid))
        observation = await _read_video_detail(page)
        _raise_for_risk_observation(observation)
        await self._capture_verified_video_screenshot(
            page,
            record,
            bvid,
            observation=observation,
        )

    async def _capture_verified_video_screenshot(
        self,
        page: Any,
        record: dict[str, Any],
        bvid: str,
        *,
        observation: Mapping[str, Any] | None = None,
    ) -> None:
        if observation is None:
            observation = await _read_video_detail(page)
            _raise_for_risk_observation(observation)
        video_data = _mapping(observation.get("videoData"))
        if (
            not _valid_video_detail_url(getattr(page, "url", None), bvid)
            or video_data.get("bvid") != bvid
        ):
            _mark_screenshot_failed(record)
            return
        await self._capture_screenshot(page, record, bvid)

    async def _capture_screenshot(
        self, page: Any, record: dict[str, Any], native_id: str
    ) -> None:
        service = getattr(self.browser, "screenshots", None)
        if service is None:
            _mark_screenshot_failed(record)
            return
        try:
            artifact = await service.capture(
                page,
                platform="bilibili",
                native_id=native_id,
                request_mode=self.request.screenshot_mode,
            )
        except ScreenshotError as error:
            if str(error) == "risk-page":
                raise CollectionStopped("challenge") from error
            _mark_screenshot_failed(record)
        else:
            record.update(artifact.as_record_fields())

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


def _mark_screenshot_failed(record: dict[str, Any]) -> None:
    record.update(
        {
            "screenshot_status": "failed",
            "screenshot_error_code": "capture-failed",
        }
    )


def parse_creator_item(item: Mapping[str, Any], *, observed_at: str | None = None) -> dict[str, Any]:
    modules = _mapping(item.get("modules"))
    dynamic = _mapping(modules.get("module_dynamic"))
    author_module = _mapping(modules.get("module_author"))
    module_stats = _mapping(modules.get("module_stat"))
    major = _mapping(dynamic.get("major"))
    archive = _mapping(major.get("archive"))
    archive_stats = _mapping(archive.get("stat"))
    dynamic_id = _text(item.get("id_str"))
    bvid = _text(archive.get("bvid"))
    content = _extract_creator_content(item)
    published_value = author_module.get("pub_ts")
    normalized_publish = _normalize_publish_time(author_module)
    publish_time = normalized_publish["publish_time"]
    display_date = _text(author_module.get("pub_time"))
    published = _date(published_value) or display_date
    liked = _metric(module_stats, "like", fallback=archive_stats.get("like"))
    comments = _metric(module_stats, "comment", fallback=module_stats.get("reply", archive_stats.get("reply")))
    shares = _metric(module_stats, "forward", fallback=archive_stats.get("share"))
    collected = _metric(module_stats, "favorite", fallback=archive_stats.get("favorite"))
    link = _creator_link(dynamic_id, bvid)
    native_id = dynamic_id or bvid
    record = {
        "platform": "bilibili", "type": "video" if bvid else "dynamic", "native_type": _text(item.get("type")),
        "dynamic_id": dynamic_id, "bvid": bvid,
        "title": content["title"], "desc": content["desc"],
        "title_source": content["title_source"], "content_source": content["content_source"],
        "title_status": "placeholder" if _is_placeholder_title(content["title"]) else "source",
        "link": link, "date": published, "publish_time": publish_time,
        "publish_date": normalized_publish["publish_date"],
        "date_source": normalized_publish["date_source"],
        "date_precision": normalized_publish["date_precision"],
        "liked": liked, "comments": comments, "shares": shares, "collected": collected,
        "id": native_id, "native_id": native_id, "url": link, "author": _text(author_module.get("name")),
        "author_avatar": _safe_content_url(author_module.get("face")),
        "cover": _major_cover(major), "image_count": _major_image_count(major),
        "published_at": published, "detail_attempted": False, "detail_source": "list_api",
        "detail_completed": False, "observed_at": observed_at or _observed_at(),
    }
    record["quality_score"] = _quality_score(record)
    return record


def parse_search_item(item: Mapping[str, Any], keyword: str, *, observed_at: str | None = None) -> dict[str, Any]:
    bvid = _text(item.get("bvid")) or _bvid_from_href(item.get("href") or item.get("arcurl"))
    link = _search_link(bvid, item.get("href") or item.get("arcurl"))
    normalized_publish = _normalize_search_publish(item)
    display_date = _search_display_date(item.get("date"))
    published = _date(item.get("pubdate")) if normalized_publish["date_source"] == "api_pubdate" else display_date
    description = _clean_text(item.get("description")) or _clean_text(item.get("desc"))
    return {
        "platform": "bilibili", "type": "video", "bvid": bvid, "native_id": bvid,
        "title": _clean_text(item.get("title")), "desc": description, "description": description,
        "play": _display_metric(item.get("play")), "duration": _search_duration(item.get("duration")),
        "tag": _clean_text(item.get("tag")),
        "link": link, "date": published, "publish_time": normalized_publish["publish_time"],
        "publish_date": normalized_publish["publish_date"], "date_source": normalized_publish["date_source"],
        "date_precision": normalized_publish["date_precision"],
        "liked": _metric(item, "like"), "comments": _metric(item, "review", fallback=item.get("comment")),
        "shares": _metric(item, "share"), "collected": _metric(item, "favorite"), "search_keyword": keyword,
        "id": bvid, "url": link, "author": _text(item.get("author")), "published_at": published,
        "detail_completed": False, "observed_at": observed_at or _observed_at(),
    }


def _extract_creator_content(item: Mapping[str, Any], *, depth: int = 0) -> dict[str, str | None]:
    modules = _mapping(item.get("modules"))
    dynamic = _mapping(modules.get("module_dynamic"))
    major_content = _major_content(_mapping(dynamic.get("major")))

    desc = None
    content_source = None
    for value, source in (
        (dynamic.get("desc"), "api-module-dynamic-desc"),
        (modules.get("module_desc"), "api-module-desc"),
        (item.get("desc"), "api-item-desc"),
    ):
        desc = _description_text(value)
        if desc is not None:
            content_source = source
            break
    if desc is None and major_content["desc"] is not None:
        desc = major_content["desc"]
        content_source = major_content["content_source"]

    native_type = _text(item.get("type")) or ""
    if "DYNAMIC_TYPE_FORWARD" in native_type and depth < 2:
        origin = _mapping(item.get("orig") or item.get("origin"))
        origin_content = _extract_creator_content(origin, depth=depth + 1)
        origin_text = origin_content["desc"] or origin_content["title"]
        origin_author = _text(_mapping(_mapping(origin.get("modules")).get("module_author")).get("name"))
        origin_desc = None
        if origin_text is not None:
            prefix = f"转发{origin_author}" if origin_author else "转发动态"
            origin_desc = f"{prefix}：{origin_text}"
        if desc is not None:
            return {
                "title": _title_from_description(desc),
                "desc": _limit_description(f"{desc}\n{origin_desc}" if origin_desc else desc),
                "title_source": "api-forward-comment",
                "content_source": "api-forward-comment+origin" if origin_desc else "api-forward-comment",
            }
        if origin_desc is not None:
            return {
                "title": _title_from_description(origin_desc),
                "desc": _limit_description(origin_desc),
                "title_source": "api-forward-origin",
                "content_source": "api-forward-origin",
            }

    title = major_content["title"]
    title_source = major_content["title_source"]
    if title is None and desc is not None:
        title = _title_from_description(desc)
        title_source = content_source
    return {
        "title": title,
        "desc": desc,
        "title_source": title_source,
        "content_source": content_source,
    }


def _major_content(major: Mapping[str, Any]) -> dict[str, str | None]:
    for key in (
        "archive",
        "draw",
        "article",
        "opus",
        "common",
        "pgc",
        "music",
        "courses",
        "medialist",
        "live_rcmd",
    ):
        block = _mapping(major.get(key))
        if not block:
            continue
        if key == "live_rcmd":
            live = _live_content(block)
            if live["title"] is not None:
                return live
            continue
        title = None
        title_source = None
        for field in ("title", "name"):
            title = _title_from_description(_description_text(block.get(field)))
            if title is not None:
                title_source = f"api-major-{key}-{field}"
                break
        desc = None
        content_source = None
        for field in ("summary", "desc", "intro"):
            desc = _description_text(block.get(field))
            if desc is not None:
                content_source = f"api-major-{key}-{field}"
                break
        if title is not None or desc is not None:
            if title is None:
                title = _title_from_description(desc)
                title_source = content_source
            return {
                "title": title,
                "desc": desc,
                "title_source": title_source,
                "content_source": content_source,
            }
    return {"title": None, "desc": None, "title_source": None, "content_source": None}


def _live_content(block: Mapping[str, Any]) -> dict[str, str | None]:
    raw = block.get("content")
    if isinstance(raw, str):
        if len(raw) > 100_000:
            return {
                "title": None,
                "desc": None,
                "title_source": None,
                "content_source": None,
            }
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            payload = None
    else:
        payload = raw
    data = _mapping(payload)
    info = _mapping(data.get("live_play_info")) or data
    for field in ("title", "room_name"):
        if (title := _title_from_description(info.get(field))) is not None:
            return {
                "title": title,
                "desc": None,
                "title_source": f"api-major-live_rcmd-{field}",
                "content_source": None,
            }
    return {
        "title": None,
        "desc": None,
        "title_source": None,
        "content_source": None,
    }


def _description_text(value: object) -> str | None:
    if isinstance(value, str):
        lines = [
            re.sub(r"[ \t\f\v]+", " ", line).strip()
            for line in value.replace("\r", "\n").split("\n")
        ]
        return _limit_description("\n".join(line for line in lines if line))
    if not isinstance(value, Mapping):
        return None
    for field in ("text", "orig_text"):
        if (text := _description_text(value.get(field))) is not None:
            return text
    nodes = _items(value.get("rich_text_nodes"))
    if nodes:
        parts: list[str] = []
        for node in nodes:
            raw_text = _mapping(node).get("text")
            if isinstance(raw_text, str):
                parts.append(raw_text)
        return _description_text("".join(parts))
    return None


def _title_from_description(value: object) -> str | None:
    text = _description_text(value)
    title = re.sub(r"\s+", " ", text).strip() if text else None
    return title[:_MAX_TITLE_CHARS] if title else None


def _limit_description(value: str) -> str | None:
    value = value.strip()
    return value[:_MAX_DESC_CHARS] if value else None


def _major_image_items(major: Mapping[str, Any]) -> list[Any] | None:
    draw = _mapping(major.get("draw"))
    if "items" in draw:
        return _items(draw.get("items")) if _is_sequence(draw.get("items")) else None
    for key in ("opus", "common", "pgc", "article", "archive", "music", "courses", "medialist"):
        block = _mapping(major.get(key))
        for field in ("pics", "images"):
            if field in block:
                return _items(block.get(field)) if _is_sequence(block.get(field)) else None
    return None


def _major_image_count(major: Mapping[str, Any]) -> int | None:
    images = _major_image_items(major)
    return len(images) if images is not None else None


def _major_cover(major: Mapping[str, Any]) -> str | None:
    for key in (
        "archive",
        "opus",
        "common",
        "pgc",
        "article",
        "draw",
        "music",
        "courses",
        "medialist",
        "live_rcmd",
    ):
        block = _mapping(major.get(key))
        for field in ("cover", "pic", "cover_url"):
            if (url := _safe_content_url(block.get(field))) is not None:
                return url
    for image in _major_image_items(major) or []:
        if (url := _image_url(image)) is not None:
            return url
    return None


def _image_url(value: object) -> str | None:
    if isinstance(value, str):
        return _safe_content_url(value)
    image = _mapping(value)
    for field in ("src", "url", "url_default", "url_pre"):
        if (url := _safe_content_url(image.get(field))) is not None:
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
            if not _SENSITIVE_URL_PART.search(key) and not _SENSITIVE_URL_PART.search(item)
        ],
        doseq=True,
    )
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


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
                const text = (...selectors) => {
                    for (const selector of selectors) {
                        const value = card.querySelector(selector)?.textContent?.trim();
                        if (value) return value;
                    }
                    return null;
                };
                const link = card.querySelector('a[href*="/video/"]');
                const href = link?.getAttribute('href') || null;
                const bvid = href?.match(/\\/video\\/(BV[^/?#]+)/)?.[1] || null;
                const title = card.querySelector('[title]')?.getAttribute('title') || link?.textContent || null;
                const description = text('.bili-video-card__info--desc', '.bili-video-card__desc');
                const play = text(
                    '.bili-video-card__stats--item:first-child',
                    '.bili-video-card__stats .bili-video-card__stats--item:first-child'
                );
                const duration = text(
                    '.bili-video-card__stats__duration',
                    '.bili-video-card__stats--duration',
                    '.bili-video-card__duration'
                );
                const visibleTags = Array.from(card.querySelectorAll(
                    '.bili-video-card__info--tag, .bili-video-card__tag'
                )).map((node) => node.textContent?.trim()).filter(Boolean);
                const tag = visibleTags.length ? Array.from(new Set(visibleTags)).join(',') : null;
                const author = text(
                    '.bili-video-card__info--author',
                    '.bili-video-card__info--owner a',
                    '.bili-video-card__info--owner span:first-child'
                );
                const date = text(
                    '.bili-video-card__info--date',
                    '.bili-video-card__info--owner span:last-child'
                );
                return {bvid, title, href, description, play, duration, tag, author, date};
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


async def _wait_for_exact_dynamic_target(page: Any, dynamic_id: str) -> None:
    await page.wait_for_function(
        """/* MEDIA_MISSHER_WAIT_EXACT_DYNAMIC_TARGET */ (expectedId) => {
            const candidates = document.querySelectorAll(
                'a[href*="t.bilibili.com/"], a[href*="/opus/"], '
                '[data-did], [dyn-id], [data-dynamic-id]'
            );
            return Array.from(candidates).some((node) => {
                if (!node.isConnected) return false;
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                const role = node.getAttribute('role');
                const actionable = node.matches('a[href], button')
                    || role === 'link' || role === 'button';
                if (!actionable || node.matches(':disabled, [aria-disabled="true"]')
                    || rect.width <= 0 || rect.height <= 0
                    || style.display === 'none' || style.visibility === 'hidden'
                    || style.pointerEvents === 'none') return false;
                for (const name of ['data-did', 'dyn-id', 'data-dynamic-id']) {
                    if (node.getAttribute(name) === expectedId) return true;
                }
                const rawHref = node.getAttribute('href');
                if (!rawHref) return false;
                try {
                    const parsed = new URL(rawHref, window.location.href);
                    const segments = parsed.pathname.split('/').filter(Boolean);
                    return parsed.protocol === 'https:'
                        && ['t.bilibili.com', 'www.bilibili.com'].includes(parsed.hostname)
                        && segments.length > 0
                        && decodeURIComponent(segments[segments.length - 1]) === expectedId;
                } catch (_error) {
                    return false;
                }
            });
        }""",
        arg=dynamic_id,
        timeout=_DYNAMIC_TARGET_TIMEOUT_MS,
    )


async def _read_dynamic_feed_risk(page: Any) -> Mapping[str, Any]:
    observation = await page.evaluate(
        """/* MEDIA_MISSHER_DYNAMIC_FEED_RISK */ () => {
            const bodyText = document.body?.innerText || '';
            const challengeSelector = document.querySelector(
                '.geetest_panel, .geetest_holder, #geetest-wrap, '
                'iframe[src*="geetest"], [class*="captcha"]'
            );
            const phrases = ['请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控'];
            const phrase = phrases.find((value) => bodyText.includes(value)) || '';
            return {risk_text: challengeSelector ? 'challenge-selector' : phrase};
        }"""
    )
    return _mapping(observation)


async def _find_exact_dynamic_target(page: Any, dynamic_id: str) -> Any:
    if not isinstance(dynamic_id, str) or not dynamic_id or "/" in dynamic_id:
        raise PreconditionError("exact Bilibili dynamic identifier is invalid")
    locator = page.locator(
        'a[href*="t.bilibili.com/"], '
        'a[href*="/opus/"], '
        '[data-did], [dyn-id], [data-dynamic-id]'
    )
    handles = await locator.element_handles()
    candidates = []
    try:
        for element in handles:
            try:
                matches = await element.evaluate(
                    """/* MEDIA_MISSHER_EXACT_DYNAMIC_TARGET */ (node, expectedId) => {
                if (!node.isConnected) return false;
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                const role = node.getAttribute('role');
                const actionable = node.matches('a[href], button')
                    || role === 'link' || role === 'button';
                if (!actionable || node.matches(':disabled, [aria-disabled="true"]')
                    || rect.width <= 0 || rect.height <= 0
                    || style.display === 'none' || style.visibility === 'hidden'
                    || style.pointerEvents === 'none') return false;
                for (const name of ['data-did', 'dyn-id', 'data-dynamic-id']) {
                    if (node.getAttribute(name) === expectedId) return true;
                }
                const rawHref = node.getAttribute('href');
                if (!rawHref) return false;
                let parsed;
                try {
                    parsed = new URL(rawHref, window.location.href);
                } catch (_error) {
                    return false;
                }
                if (parsed.protocol !== 'https:') return false;
                if (!['t.bilibili.com', 'www.bilibili.com'].includes(parsed.hostname)) {
                    return false;
                }
                const segments = parsed.pathname.split('/').filter(Boolean);
                return segments.length > 0
                    && decodeURIComponent(segments[segments.length - 1]) === expectedId;
            }""",
                    dynamic_id,
                )
            except (AttributeError, PlaywrightError, PlaywrightTimeoutError, TypeError):
                matches = False
            if matches is True:
                candidates.append(element)
        if len(candidates) != 1:
            raise PreconditionError("exact Bilibili dynamic target is ambiguous")
        selected = candidates[0]
        for element in handles:
            if element is not selected:
                await _dispose_element_handle(element)
        return selected
    except BaseException:
        for element in handles:
            await _dispose_element_handle(element)
        raise


async def _dispose_element_handle(handle: Any) -> None:
    try:
        await handle.dispose()
    except (AttributeError, PlaywrightError, PlaywrightTimeoutError, TypeError):
        pass


def _valid_video_detail_url(url: object, expected_bvid: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.hostname in {"bilibili.com", "www.bilibili.com"}
        and [segment for segment in parsed.path.split("/") if segment]
        == ["video", expected_bvid]
    )


def _valid_dynamic_detail_url(url: object, expected_dynamic_id: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    segments = [segment for segment in parsed.path.split("/") if segment]
    if parsed.hostname == "t.bilibili.com":
        return segments == [expected_dynamic_id]
    return (
        parsed.hostname in {"bilibili.com", "www.bilibili.com"}
        and segments in (["opus", expected_dynamic_id], ["dynamic", expected_dynamic_id])
    )


async def _read_dynamic_detail(
    page: Any, expected_dynamic_id: str
) -> Mapping[str, Any]:
    if not _valid_dynamic_detail_url(getattr(page, "url", None), expected_dynamic_id):
        raise PreconditionError("Bilibili detail identifier mismatch")
    observation = await page.evaluate(
        r"""/* MEDIA_MISSHER_DYNAMIC_DETAIL */ (expectedId) => {
            const bodyText = document.body?.innerText || '';
            const challengeSelector = document.querySelector(
                '.geetest_panel, .geetest_holder, #geetest-wrap, iframe[src*="geetest"], '
                + 'iframe[src*="captcha"], [class*="captcha"], .challenge-page, .challenge-overlay'
            );
            const phrases = [
                '请完成验证', '访问受限', '请求过于频繁', '账号异常', '风控',
                'risk', 'locked', 'blocked', 'cooldown', 'challenge'
            ];
            const phrase = phrases.find((value) =>
                bodyText.toLocaleLowerCase().includes(value.toLocaleLowerCase())
            ) || '';
            const riskText = challengeSelector ? 'challenge-selector' : phrase;
            const containers = Array.from(document.querySelectorAll(
                'main article, .opus-detail, .opus-detail-container, .bili-dyn-item'
            )).filter((node) => {
                const rect = node.getBoundingClientRect();
                const style = window.getComputedStyle(node);
                return rect.width > 0 && rect.height > 0
                    && style.display !== 'none' && style.visibility !== 'hidden';
            });
            const empty = {
                dynamic_id: containers.length === 1 || riskText ? expectedId : null,
                risk_text: riskText,
                liked: null,
                comments: null,
                shares: null,
                collected: null,
            };
            if (riskText || containers.length !== 1) return empty;
            const container = containers[0];
            const parseMetric = (value) => {
                if (typeof value !== 'string') return null;
                const normalized = value.replace(/,/g, '').trim();
                const match = normalized.match(/(\d+(?:\.\d+)?)\s*([万亿]?)/);
                if (!match) return null;
                const multiplier = match[2] === '亿' ? 100000000 : match[2] === '万' ? 10000 : 1;
                const number = Number(match[1]) * multiplier;
                return Number.isFinite(number) && number >= 0 ? number : null;
            };
            const metric = (selectors) => {
                for (const selector of selectors) {
                    const node = container.querySelector(selector);
                    if (!node) continue;
                    for (const value of [
                        node.getAttribute('aria-label'),
                        node.getAttribute('title'),
                        node.textContent,
                    ]) {
                        const parsed = parseMetric(value);
                        if (parsed !== null) return parsed;
                    }
                }
                return null;
            };
            return {
                dynamic_id: expectedId,
                risk_text: '',
                liked: metric(['[aria-label*="点赞"]', '.like', '.like-text']),
                comments: metric(['[aria-label*="评论"]', '.comment', '.comment-text']),
                shares: metric(['[aria-label*="转发"]', '.forward', '.share']),
                collected: metric(['[aria-label*="收藏"]', '.favorite', '.collect']),
            };
        }""",
        expected_dynamic_id,
    )
    detail = _mapping(observation)
    if detail.get("dynamic_id") != expected_dynamic_id:
        raise PreconditionError("Bilibili detail identifier mismatch")
    return {
        "dynamic_id": detail.get("dynamic_id"),
        "risk_text": detail.get("risk_text"),
        "liked": detail.get("liked"),
        "comments": detail.get("comments"),
        "shares": detail.get("shares"),
        "collected": detail.get("collected"),
    }


def _merge_dynamic_detail(
    record: dict[str, Any], detail: Mapping[str, Any]
) -> bool:
    merged = False
    for field in ("liked", "comments", "shares", "collected"):
        value = detail.get(field)
        if isinstance(value, Real) and not isinstance(value, bool):
            try:
                valid = math.isfinite(float(value)) and value >= 0
            except (OverflowError, TypeError, ValueError):
                valid = False
            if valid:
                record[field] = value
                merged = True
    return merged


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


def _dynamic_page_url(dynamic_id: str) -> str:
    return f"https://t.bilibili.com/{dynamic_id}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


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


def _display_metric(value: object) -> int | float | None:
    if isinstance(value, Real) and not isinstance(value, bool):
        try:
            numeric = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        return value if math.isfinite(numeric) and numeric >= 0 else None
    text = _text(value)
    if text is None or len(text) > 40:
        return None
    text = re.sub(r"(?:次播放|播放次数|播放)$", "", text.replace(",", "")).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([万亿]?)(?:\+)?", text)
    if match is None:
        return None
    multiplier = {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    numeric = float(match.group(1)) * multiplier
    if not math.isfinite(numeric):
        return None
    return int(numeric) if numeric.is_integer() else numeric


def _search_duration(value: object) -> str | None:
    text = _text(value)
    if text is None or len(text) > 16:
        return None
    return text if re.fullmatch(r"\d{1,3}:[0-5]\d(?::[0-5]\d)?", text) else None


def _search_display_date(value: object) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    text = re.sub(r"^[\s·•|]+", "", text).strip()
    return text[:80] if text else None


def _normalize_search_publish(item: Mapping[str, Any]) -> dict[str, int | str | None]:
    seconds = _timestamp_seconds(item.get("pubdate"))
    if seconds is not None:
        try:
            value = datetime.fromtimestamp(seconds, _CHINA_TIMEZONE)
        except (OSError, OverflowError, ValueError):
            value = None
        if value is not None:
            return _publish_result(value, source="api_pubdate", precision="second")

    raw = _search_display_date(item.get("date"))
    if raw is None:
        return _publish_result()
    match = re.fullmatch(
        r"(\d{4})(?:年|[-./])(\d{1,2})(?:月|[-./])(\d{1,2})(?:日)?(?:\s+(\d{1,2}):(\d{2}))?",
        raw,
    )
    if match is None:
        return _publish_result()
    try:
        value = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4) or 0),
            int(match.group(5) or 0),
            tzinfo=_CHINA_TIMEZONE,
        )
    except ValueError:
        return _publish_result()
    return _publish_result(
        value,
        source="search_dom",
        precision="minute" if match.group(4) else "day",
    )


def _date(value: object) -> str | None:
    seconds = _timestamp_seconds(value)
    if seconds is None:
        return value if isinstance(value, str) and value else None
    try:
        return datetime.fromtimestamp(seconds, UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _timestamp_seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        seconds = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    seconds = seconds / 1000 if seconds >= 1_000_000_000_000 else seconds
    try:
        datetime.fromtimestamp(seconds, UTC)
    except (OSError, OverflowError, ValueError):
        return None
    return seconds


def _timestamp_millis(value: object) -> int | None:
    seconds = _timestamp_seconds(value)
    return int(seconds * 1000) if seconds is not None else None


def _publish_date(value: object) -> str | None:
    seconds = _timestamp_seconds(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, _CHINA_TIMEZONE).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return None


def _publish_result(
    value: datetime | None = None,
    *,
    source: str | None = None,
    precision: str | None = None,
) -> dict[str, int | str | None]:
    if value is None:
        return {
            "publish_time": None,
            "publish_date": None,
            "date_source": None,
            "date_precision": None,
        }
    value = value.astimezone(_CHINA_TIMEZONE)
    return {
        "publish_time": int(value.timestamp() * 1000),
        "publish_date": value.strftime("%Y-%m-%d"),
        "date_source": source,
        "date_precision": precision,
    }


def _normalize_publish_time(
    author: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, int | str | None]:
    seconds = _timestamp_seconds(author.get("pub_ts"))
    if seconds is not None:
        try:
            value = datetime.fromtimestamp(seconds, _CHINA_TIMEZONE)
        except (OSError, OverflowError, ValueError):
            value = None
        if value is not None:
            return _publish_result(value, source="api_pub_ts", precision="second")

    raw = (_text(author.get("pub_time")) or "")[:80]
    if not raw:
        return _publish_result()
    current = now or datetime.now(_CHINA_TIMEZONE)
    current = current.replace(tzinfo=_CHINA_TIMEZONE) if current.tzinfo is None else current.astimezone(_CHINA_TIMEZONE)

    bare_relative = re.fullmatch(r"(今天|昨天)", raw)
    if bare_relative:
        day_offset = 0 if bare_relative.group(1) == "今天" else 1
        value = (current - timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        return _publish_result(value, source="display_parse", precision="day")

    relative = re.fullmatch(r"(今天|昨天)\s*(\d{1,2}):(\d{2})", raw)
    if relative:
        day_offset = 0 if relative.group(1) == "今天" else 1
        try:
            value = (current - timedelta(days=day_offset)).replace(
                hour=int(relative.group(2)),
                minute=int(relative.group(3)),
                second=0,
                microsecond=0,
            )
        except ValueError:
            return _publish_result()
        return _publish_result(value, source="display_parse", precision="minute")

    full_date = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2}):(\d{2}))?", raw)
    if full_date:
        try:
            value = datetime(
                int(full_date.group(1)),
                int(full_date.group(2)),
                int(full_date.group(3)),
                int(full_date.group(4) or 0),
                int(full_date.group(5) or 0),
                tzinfo=_CHINA_TIMEZONE,
            )
        except ValueError:
            return _publish_result()
        return _publish_result(value, source="display_parse", precision="minute" if full_date.group(4) else "day")

    month_day = re.fullmatch(r"(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2}):(\d{2}))?", raw)
    if month_day:
        try:
            value = datetime(
                current.year,
                int(month_day.group(1)),
                int(month_day.group(2)),
                int(month_day.group(3) or 0),
                int(month_day.group(4) or 0),
                tzinfo=_CHINA_TIMEZONE,
            )
            if value > current + timedelta(days=1):
                value = value.replace(year=current.year - 1)
        except ValueError:
            return _publish_result()
        return _publish_result(value, source="display_parse", precision="minute" if month_day.group(3) else "day")

    return _publish_result()


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
    return (
        data.get("bvid") == expected_bvid
        and _text(data.get("title")) is not None
        and _timestamp_seconds(data.get("pubdate")) is not None
        and isinstance(data.get("desc"), str)
        and isinstance(data.get("stat"), Mapping)
    )


def _merge_video_detail(record: dict[str, Any], data: Mapping[str, Any]) -> None:
    stat = _mapping(data.get("stat"))
    record["title"] = _title_from_description(data.get("title"))
    record["desc"] = _description_text(data.get("desc"))
    published_value = data.get("pubdate")
    record["date"] = _date(published_value)
    record["date_precision"] = "second" if record["date"] is not None else None
    record["publish_time"] = _timestamp_millis(published_value)
    record["publish_date"] = _publish_date(published_value)
    record["date_source"] = "detail_api" if record["publish_time"] is not None else None
    record["published_at"] = record["date"]
    record["title_source"] = "detail_api"
    record["content_source"] = "detail_api"
    record["title_status"] = "placeholder" if _is_placeholder_title(record["title"]) else "source"
    record["liked"] = _metric(stat, "like")
    record["comments"] = _metric(stat, "reply")
    record["shares"] = _metric(stat, "share")
    record["collected"] = _metric(stat, "favorite")


def _missing_completion_fields(
    record: Mapping[str, Any],
    detail_received: bool,
    *,
    detail_required: bool = True,
) -> list[str]:
    missing: list[str] = []
    if not _text(record.get("native_id")):
        missing.append("native_id")
    if _is_placeholder_title(record.get("title")):
        missing.append("title")
    if record.get("date") is None:
        missing.append("date")
    if detail_required and not detail_received:
        missing.append("detail")
    for field in ("liked", "comments", "shares", "collected"):
        if record.get(field) is None:
            missing.append(field)
    return missing


def _has_media(record: Mapping[str, Any]) -> bool:
    image_count = record.get("image_count")
    return bool(record.get("cover")) or (
        isinstance(image_count, Real)
        and not isinstance(image_count, bool)
        and image_count > 0
    )


def _quality_score(record: Mapping[str, Any]) -> int:
    score = 0
    if not _is_placeholder_title(record.get("title")):
        score += 1
    if record.get("date") is not None:
        score += 1
    if isinstance(record.get("liked"), Real) and not isinstance(record.get("liked"), bool) and record["liked"] > 0:
        score += 1
    if isinstance(record.get("comments"), Real) and not isinstance(record.get("comments"), bool) and record["comments"] > 0:
        score += 1
    if _has_media(record):
        score += 1
    return score


def _is_placeholder_title(value: object) -> bool:
    title = _text(value)
    return title is None or title.casefold() in _PLACEHOLDER_TITLES


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()
