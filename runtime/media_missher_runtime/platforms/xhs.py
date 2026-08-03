"""Browser-mediated Xiaohongshu collection with safe rich business outputs.

This module never calls Xiaohongshu APIs itself.  It only observes responses
the authenticated user browser produces while navigating its normal UI. Public
content detail is retained; request helpers, account IDs, and tracking data are
not persisted.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any, Callable
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from ..browser import BrowserSession, PreconditionError
from ..models import CollectionRequest
from ..safety import classify_response

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - browser is optional during offline tests
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = TimeoutError


_HOST = "www.xiaohongshu.com"
_HOSTS = ("xiaohongshu.com", _HOST)
_CREATOR_PATH = "/api/sns/web/v1/user_posted"
_DETAIL_PATH = "/api/sns/web/v1/feed"
_DETAIL_RESPONSE_HOSTS = frozenset({_HOST, "edith.xiaohongshu.com"})
_NOTE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_PLACEHOLDERS = frozenset({"", "-", "--", "暂无标题", "untitled", "无标题"})
_CHALLENGE_PHRASES = (
    "请完成验证", "访问受限", "请求过于频繁", "账号异常", "风控", "安全验证", "验证码",
)
_RISK_WORDS = ("risk", "locked", "blocked", "cooldown", "challenge")
_RISK_CODES = frozenset({461, 471, 999})
_DETAIL_ATTEMPT_SKEW_SECONDS = 2
_DETAIL_METRIC_POLL_INTERVAL_MS = 250
_DETAIL_METRIC_POLL_ATTEMPTS = 12
_SEARCH_SETTLE_ATTEMPTS = 40
_SEARCH_SETTLE_INTERVAL_MS = 250
_REQUIRED_DETAIL_METRICS = ("liked", "comments", "collected")
_FRESH_DETAIL_METRIC_SOURCES = frozenset({"detail_api", "detail_html"})
_CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SENSITIVE_URL_PART = re.compile(
    r"(?:token|secret|password|passwd|credential|cookie|session|authorization|xsec)",
    re.IGNORECASE,
)
_SENSITIVE_URL_KEY = re.compile(
    r"(?:token|secret|password|passwd|credential|cookie|session|authorization|"
    r"xsec|signature|expires?|expiry|auth[_-]?key|"
    r"(?:^|[_-])auth(?:[_-]|$)|(?:^|[_-])sign(?:[_-]|$))",
    re.IGNORECASE,
)
_MAX_MEDIA_ITEMS = 100
_MAX_TAGS = 100
_MAX_COUNT = (1 << 63) - 1
_MISSING = object()


class CollectionStopped(RuntimeError):
    """A risk/challenge signal means this collection must stop immediately."""


class SourceResponseError(RuntimeError):
    """A browser-generated response was malformed or non-risk unsuccessful."""


class CaptureTimeout(TimeoutError):
    """A response listener timed out after a fresh challenge check."""

    _CODES = frozenset({"creator-capture-timeout", "detail-capture-timeout"})

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unsupported capture timeout code")
        self.code = code
        super().__init__(code)


@dataclass(slots=True)
class XhsCollector:
    request: CollectionRequest
    browser: BrowserSession | Any

    async def collect(self) -> list[dict[str, Any]]:
        return await (self.collect_creator() if self.request.uid is not None else self.search())

    async def collect_creator(self) -> list[dict[str, Any]]:
        if self.request.uid is None:
            raise ValueError("creator collection requires uid")
        page = self.browser.require_page("xhs")
        target = _creator_url(self.request.uid)
        if not getattr(self.browser, "allow_navigation", False):
            _require_open_target(page, target, "matching Xiaohongshu creator page")
            # A passive wait cannot prove that the response belongs to this run.
            raise PreconditionError("Xiaohongshu creator collection requires authorized navigation")
        await _raise_for_challenge(page)
        creator_predicate = lambda response: _is_creator_response(response, self.request.uid)
        navigation_succeeded = False

        async def navigate() -> None:
            nonlocal navigation_succeeded
            await self._navigate_and_check(page, target)
            navigation_succeeded = True

        try:
            response = await _capture_while(
                page,
                creator_predicate,
                navigate,
            )
        except PlaywrightTimeoutError as error:
            await _raise_for_challenge(page)
            if not navigation_succeeded or getattr(page, "url", "") != target:
                raise CaptureTimeout("creator-capture-timeout") from error
            observation = await _read_creator_cards(page)
            await _raise_for_challenge(page)
            if getattr(page, "url", "") != target:
                raise CaptureTimeout("creator-capture-timeout") from error
            records = _creator_dom_records(
                _as_sequence(observation.get("cards")), self.request.target_count
            )
            if not records:
                raise CaptureTimeout("creator-capture-timeout") from error
        else:
            records = await self._collect_creator_pages(page, response)
        if self.request.complete:
            for record in records:
                await self._complete_record(page, record)
        else:
            for record in records:
                record.update({"complete": False, "detail_completed": False, "detail_attempted": False, "missing_fields": []})
        return records

    async def search(self) -> list[dict[str, Any]]:
        if self.request.keyword is None:
            raise ValueError("search requires keyword")
        if self.request.complete:
            raise ValueError("complete search is not supported")
        page = self.browser.require_page("xhs")
        target = _search_url(self.request.keyword)
        if getattr(self.browser, "allow_navigation", False):
            await self._navigate_and_check(page, target)
        else:
            _require_open_target(page, target, "matching Xiaohongshu search page")
        await _wait_for_search_settled(page)
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page_number in range(self.request.page_cap):
            await _raise_for_challenge(page)
            observation = await _read_search_cards(page)
            _raise_for_observation(observation)
            added = _append_search(records, seen, _as_sequence(observation.get("cards")), self.request.keyword, self.request.target_count)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 or page_number + 1 >= self.request.page_cap:
                break
            await _scroll_and_check(page)
            try:
                await _wait_for_card_change(page, sorted(seen))
            except PlaywrightTimeoutError as error:
                await _raise_for_challenge(page)
                raise CaptureTimeout("creator-capture-timeout") from error
        return records

    async def _collect_creator_pages(self, page: Any, response: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        prior_cursor: object = _MISSING
        for page_number in range(self.request.page_cap):
            await _raise_for_challenge(page)
            payload = await _response_payload(response)
            notes, has_more, cursor = _creator_page(payload)
            added = _append_creator(records, seen, notes, self.request.target_count)
            if self.request.target_count is not None and len(records) >= self.request.target_count:
                break
            if added == 0 or not has_more or page_number + 1 >= self.request.page_cap:
                break
            if _empty_cursor(cursor) or (prior_cursor is not _MISSING and cursor == prior_cursor):
                break
            prior_cursor = cursor
            try:
                response = await _capture_while(
                    page,
                    lambda candidate: _is_creator_response(candidate, self.request.uid),
                    lambda: _scroll_and_check(page),
                )
            except PlaywrightTimeoutError:
                await _raise_for_challenge(page)
                break
        return records

    async def _complete_record(self, page: Any, record: dict[str, Any]) -> None:
        note_id = record.get("note_id")
        record["detail_attempted"] = False
        record["detail_completed"] = False
        if not _safe_note_id(note_id):
            record["missing_fields"] = _missing_completion(record)
            record["complete"] = False
            return
        await _raise_for_challenge(page)
        if not await _wait_for_note_card(page, note_id):
            record["missing_fields"] = _missing_completion(record)
            record["complete"] = False
            return
        record["detail_attempted"] = True
        primary_error: BaseException | None = None
        try:
            attempt_started_at = datetime.now(UTC)
            try:
                response = await _capture_while(
                    page,
                    lambda candidate: _is_detail_response(candidate, note_id),
                    lambda: _click_note_and_check(page, note_id),
                )
            except PlaywrightTimeoutError as error:
                await _raise_for_challenge(page)
                raise CaptureTimeout("detail-capture-timeout") from error
            payload = await _response_payload(response)
            attempt_finished_at = datetime.now(UTC)
            card = _detail_card(
                payload,
                note_id,
                attempt_started_at=attempt_started_at,
                attempt_finished_at=attempt_finished_at,
            )
            if card is not None:
                observed_at = _detail_server_observed_at(
                    payload,
                    attempt_started_at=attempt_started_at,
                    attempt_finished_at=attempt_finished_at,
                )
                if observed_at is None:  # defensive: _detail_card already requires this
                    raise SourceResponseError("Xiaohongshu detail payload has invalid current_time")
                _merge_detail(record, card, engagement_observed_at=observed_at)
                record["detail_completed"] = True
                missing_metrics = _missing_required_metrics(record)
                if missing_metrics:
                    html = await _wait_for_detail_metrics(page, missing_metrics)
                    _supplement_missing_detail_html(record, html)
            elif _has_current_detail_time(
                payload,
                attempt_started_at=attempt_started_at,
                attempt_finished_at=attempt_finished_at,
            ):
                # Keep a non-authoritative DOM observation useful, but never
                # manufacture a publish time or mark it complete from HTML.
                html = await _read_detail_html(page)
                _raise_for_observation(html)
                _merge_detail_html(record, html)
            if self.request.comment_limit > 0 and record["detail_completed"]:
                comments = await _read_comments(page, self.request.comment_limit)
                _raise_for_observation(comments)
                comments_data = _safe_comments(
                    _as_sequence(comments.get("comments")),
                    self.request.comment_limit,
                )
                record["comments_data"] = comments_data
                # Preserve the old public business aliases without restoring
                # comment IDs, account IDs, request tokens, or raw payloads.
                record["comments_detail"] = comments_data
                record["comments_fetched"] = len(comments_data)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                await _close_modal(page)
            except CollectionStopped:
                raise
            except BaseException:
                if primary_error is None:
                    raise
        missing = _missing_completion(record)
        record["missing_fields"] = missing
        record["complete"] = not missing
        _annotate_legacy_quality(record)

    async def _navigate_and_check(self, page: Any, target: str) -> None:
        response = await self.browser.navigate(page, target, allowed_hosts=_HOSTS)
        status = getattr(response, "status", None)
        if isinstance(status, int):
            decision = classify_response(status=status)
            if decision.stop_all:
                raise CollectionStopped(decision.reason or "risk response")
            if not 200 <= status < 300:
                raise SourceResponseError(f"Xiaohongshu navigation returned http-{status}")
        await _raise_for_challenge(page)


async def collect_creator(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await XhsCollector(request, browser).collect_creator()


async def search(request: CollectionRequest, browser: BrowserSession | Any) -> list[dict[str, Any]]:
    return await XhsCollector(request, browser).search()


def parse_count(value: object) -> int | None:
    """Parse only finite native numeric counts, including 万 and 亿 abbreviations."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Real):
        try:
            numeric = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        return (
            int(value)
            if math.isfinite(numeric) and 0 <= numeric <= _MAX_COUNT
            else None
        )
    if not isinstance(value, str):
        return None
    text = value.strip().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([万亿]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    result = number * multiplier
    return (
        int(result)
        if math.isfinite(result) and 0 <= result <= _MAX_COUNT
        else None
    )


def _detail_count(source: Mapping[str, Any], field: str) -> int | None:
    """Preserve the old API-only distinction between absent and present-empty."""
    value = source.get(field, _MISSING)
    if value is _MISSING or value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return 0
    return parse_count(value)


def build_run_report(status: str, records: Sequence[Mapping[str, Any]], started_at: str, finished_at: str, reason: str | None = None) -> dict[str, Any]:
    """Return aggregate-only diagnostics safe to persist outside the browser."""
    report: dict[str, Any] = {
        "status": str(status), "started_at": str(started_at), "finished_at": str(finished_at),
        "final_items": len(records),
        "complete_items": sum(item.get("complete") is True for item in records),
        "fresh_items": sum(item.get("engagement_fresh") is True for item in records),
        "detail_attempts": sum(item.get("detail_attempted") is True for item in records),
        "detail_successes": sum(item.get("detail_completed") is True for item in records),
    }
    if reason is not None:
        report["reason"] = _safe_report_reason(reason)
    return report


def build_checkpoint(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, str | None]]]:
    """A resumable checkpoint intentionally contains no titles, tokens, or payloads."""
    return {"items": [
        {"note_id": note_id, "observed_at": _text(record.get("observed_at"))}
        for record in records
        if (note_id := _text(record.get("note_id"))) and _safe_note_id(note_id)
    ]}


async def _capture_while(page: Any, predicate: Callable[[Any], bool], action: Callable[[], Any]) -> Any:
    async with page.expect_response(predicate, timeout=10_000) as response_info:
        await action()
    return await response_info.value


def _is_creator_response(response: Any, expected_uid: str | None = None) -> bool:
    parsed = urlparse(getattr(response, "url", ""))
    if parsed.hostname != _HOST or parsed.path != _CREATOR_PATH:
        return False
    if expected_uid is None:
        return True
    user_ids = _response_request_user_ids(response)
    return bool(user_ids) and all(value == expected_uid for value in user_ids)


def _is_detail_response(response: Any, expected_note_id: str | None = None) -> bool:
    parsed = urlparse(getattr(response, "url", ""))
    if parsed.hostname not in _DETAIL_RESPONSE_HOSTS or parsed.path != _DETAIL_PATH:
        return False
    if expected_note_id is None:
        return True
    note_ids = _response_request_note_ids(response)
    return bool(note_ids) and all(value == expected_note_id for value in note_ids)


async def _response_payload(response: Any) -> Mapping[str, Any]:
    status = getattr(response, "status", None)
    if isinstance(status, bool) or not isinstance(status, int):
        raise SourceResponseError("Xiaohongshu source response has no numeric HTTP status")
    decision = classify_response(status=status)
    if decision.stop_all:
        raise CollectionStopped(decision.reason or "risk response")
    if not 200 <= status < 300:
        raise SourceResponseError(f"Xiaohongshu source returned http-{status}")
    try:
        payload = await response.json()
    except Exception as error:
        raise SourceResponseError("Xiaohongshu source JSON decode failed") from error
    if not isinstance(payload, Mapping):
        raise SourceResponseError("Xiaohongshu source returned a non-object JSON payload")
    _raise_for_payload_risk(payload)
    path = urlparse(getattr(response, "url", "")).path
    if path == _CREATOR_PATH:
        _payload_collection(payload, "notes")
    elif path == _DETAIL_PATH:
        _payload_collection(payload, "items")
    else:
        raise SourceResponseError("Xiaohongshu response used an unexpected endpoint")
    return payload


def _raise_for_payload_risk(payload: Mapping[str, Any]) -> None:
    code = _int_like(payload.get("code"))
    message = _text(payload.get("msg")) or _text(payload.get("message")) or ""
    lowered = message.casefold()
    if code in _RISK_CODES:
        raise CollectionStopped(f"payload-{code}")
    if payload.get("success") is False and any(word in lowered for word in _RISK_WORDS + _CHALLENGE_PHRASES):
        raise CollectionStopped("payload-risk")
    if payload.get("success") is False:
        raise SourceResponseError("Xiaohongshu source reported unsuccessful response")
    if code not in (None, 0):
        raise SourceResponseError(f"Xiaohongshu source reported code-{code}")


def _payload_collection(payload: Mapping[str, Any], field: str) -> tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]:
    if _int_like(payload.get("code")) != 0 or payload.get("success") is not True:
        raise SourceResponseError("Xiaohongshu endpoint payload has invalid success/code")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise SourceResponseError("Xiaohongshu endpoint payload has invalid data")
    collection = data.get(field)
    if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes, bytearray)):
        raise SourceResponseError(f"Xiaohongshu endpoint payload has invalid {field} collection")
    if any(not isinstance(item, Mapping) for item in collection):
        raise SourceResponseError(f"Xiaohongshu endpoint payload has malformed {field} item")
    return data, collection


def _response_request_user_ids(response: Any) -> list[str]:
    request = getattr(response, "request", None)
    urls = [getattr(request, "url", None), getattr(response, "url", None)]
    values: list[str] = []
    for url in urls:
        if not isinstance(url, str):
            continue
        values.extend(parse_qs(urlparse(url).query, keep_blank_values=True).get("user_id", ()))
    try:
        post_data = getattr(request, "post_data_json", None)
    except Exception:
        post_data = None
    if callable(post_data):
        try:
            post_data = post_data()
        except Exception:
            post_data = None
    if isinstance(post_data, Mapping) and isinstance(post_data.get("user_id"), str):
        values.append(post_data["user_id"])
    return values


def _response_request_note_ids(response: Any) -> list[str]:
    request = getattr(response, "request", None)
    urls = [getattr(request, "url", None), getattr(response, "url", None)]
    values: list[str] = []
    for url in urls:
        if not isinstance(url, str):
            continue
        query = parse_qs(urlparse(url).query, keep_blank_values=True)
        for key in ("source_note_id", "note_id"):
            values.extend(
                value for value in query.get(key, ()) if _safe_note_id(value)
            )
    try:
        post_data = getattr(request, "post_data_json", None)
    except Exception:
        post_data = None
    if callable(post_data):
        try:
            post_data = post_data()
        except Exception:
            post_data = None
    if isinstance(post_data, Mapping):
        for key in ("source_note_id", "note_id"):
            value = post_data.get(key)
            if _safe_note_id(value):
                values.append(value)
    return values


def _creator_page(payload: Mapping[str, Any]) -> tuple[Sequence[Mapping[str, Any]], bool, object]:
    data, notes = _payload_collection(payload, "notes")
    if "has_more" not in data or data.get("has_more") not in (True, False, 0, 1):
        raise SourceResponseError("Xiaohongshu creator payload has invalid has_more")
    if "cursor" not in data:
        raise SourceResponseError("Xiaohongshu creator payload has no cursor")
    return notes, _has_more(data.get("has_more")), data.get("cursor")


def _append_creator(records: list[dict[str, Any]], seen: set[str], items: Sequence[Mapping[str, Any]], target: int | None) -> int:
    added = 0
    for item in items:
        record = parse_creator_item(item)
        note_id = record["note_id"]
        if not _safe_note_id(note_id) or note_id in seen:
            continue
        seen.add(note_id)
        records.append(record)
        added += 1
        if target is not None and len(records) >= target:
            break
    return added


def _creator_dom_records(items: Sequence[Any], target: int | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    observed_at = _observed_at()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record = parse_creator_dom_item(item, observed_at=observed_at)
        note_id = record["note_id"]
        if not _safe_note_id(note_id) or note_id in seen:
            continue
        seen.add(note_id)
        records.append(record)
        if target is not None and len(records) >= target:
            break
    return records


def _append_search(records: list[dict[str, Any]], seen: set[str], items: Sequence[Mapping[str, Any]], keyword: str, target: int | None) -> int:
    added = 0
    for item in items:
        record = parse_search_item(item, keyword)
        note_id = record["note_id"]
        if not _safe_note_id(note_id) or note_id in seen:
            continue
        seen.add(note_id)
        records.append(record)
        added += 1
        if target is not None and len(records) >= target:
            break
    return added


def parse_creator_item(item: Mapping[str, Any], *, observed_at: str | None = None) -> dict[str, Any]:
    note_id = _text(item.get("note_id"))
    info = _mapping(item.get("interact_info"))
    user = _mapping(item.get("user"))
    note_card = _mapping(item.get("note_card"))
    title = _text(item.get("display_title")) or _text(item.get("title"))
    desc = _text(item.get("desc")) or _text(note_card.get("desc"))
    link = _explore_link(note_id)
    stamp = observed_at or _observed_at()
    raw_time = _first_timestamp(item)
    record = _base_record(
        note_id,
        _text(item.get("type")),
        title,
        desc,
        link,
        _timestamp(raw_time),
        parse_count(info.get("liked_count")),
        parse_count(info.get("comment_count")),
        parse_count(info.get("share_count")),
        parse_count(info.get("collected_count")),
        _text(user.get("nickname")) or _text(user.get("nick_name")),
        stamp,
    )
    _merge_preview_business_fields(record, item, source="list_api")
    return record


def parse_creator_dom_item(item: Mapping[str, Any], *, observed_at: str | None = None) -> dict[str, Any]:
    """Build a minimal creator record from an already-rendered safe DOM card."""
    note_id = _text(item.get("note_id"))
    record = _base_record(
        note_id,
        None,
        _text(item.get("title")),
        None,
        _explore_link(note_id),
        None,
        parse_count(item.get("liked")),
        None,
        None,
        None,
        _text(item.get("author")),
        observed_at or _observed_at(),
    )
    record["detail_source"] = "creator_dom"
    _annotate_legacy_quality(record)
    return record


def parse_search_item(item: Mapping[str, Any], keyword: str, *, observed_at: str | None = None) -> dict[str, Any]:
    note_id = _text(item.get("note_id"))
    title = _text(item.get("title")) or _text(item.get("display_title"))
    user = _mapping(item.get("user"))
    author = _text(item.get("author")) or _text(user.get("nickname"))
    record = {
        **_base_record(note_id, _text(item.get("type")), title, _text(item.get("desc")), _explore_link(note_id), None, parse_count(item.get("liked")), parse_count(item.get("comments")), parse_count(item.get("shares")), parse_count(item.get("collected")), author, observed_at or _observed_at()),
        "search_keyword": keyword,
    }
    cover_value = item.get("cover")
    if isinstance(cover_value, Mapping):
        cover = dict(cover_value)
    else:
        cover = {
            "url": cover_value or item.get("cover_url"),
            "width": item.get("cover_width"),
            "height": item.get("cover_height"),
        }
    publish_time = _observable_timestamp_millis(item)
    _merge_preview_business_fields(
        record,
        {
            "user": {
                "avatar": item.get("author_avatar")
                or user.get("avatar")
                or user.get("image")
            },
            "cover": cover,
            "publish_time": publish_time,
        },
        source="search_dom",
    )
    record["image_count"] = _dimension(item.get("image_count"))
    _annotate_legacy_quality(record)
    return record


def _base_record(note_id: str | None, kind: str | None, title: str | None, desc: str | None, link: str | None, date: str | None, liked: int | None, comments: int | None, shares: int | None, collected: int | None, author: str | None, observed_at: str) -> dict[str, Any]:
    return {
        "platform": "xhs", "type": kind, "note_id": note_id, "title": title, "desc": desc, "link": link,
        "date": date, "date_precision": "second" if date else None, "date_estimated": None,
        "liked": liked, "comments": comments, "shares": shares, "collected": collected,
        "id": note_id, "native_id": note_id, "url": link, "author": author, "published_at": date,
        "observed_at": observed_at, "detail_completed": False, "detail_attempted": False,
        "engagement_fresh": False, "engagement_observed_at": None, "engagement_source": None,
        "metric_sources": {}, "complete": False, "missing_fields": [],
        "detail_link": link, "detail_source": None, "date_source": None,
        "publish_time": None, "publish_date": None, "last_update_time": None,
        "ip_location": None, "author_avatar": None,
        "cover": None, "cover_width": None, "cover_height": None,
        "images": [], "image_count": None, "image_details": [],
        "tags": [], "tag_list": None, "raw_share_count": shares,
        "metric_observed_at": {}, "engagement_detail_fields": [],
        "engagement_stale_fields": [], "quality_score": 0,
        "quality_missing_fields": [],
    }


def _merge_preview_business_fields(
    record: dict[str, Any],
    item: Mapping[str, Any],
    *,
    source: str,
) -> None:
    """Keep public preview fields while excluding request/account helpers."""
    user = _mapping(item.get("user"))
    avatar = _safe_content_url(user.get("avatar") or user.get("image"))
    if avatar is not None:
        record["author_avatar"] = avatar

    cover = _mapping(item.get("cover"))
    cover_url = _first_image_url(cover)
    if cover_url is not None:
        record["cover"] = cover_url
        record["cover_width"] = _dimension(cover.get("width"))
        record["cover_height"] = _dimension(cover.get("height"))

    raw_time = _first_timestamp(item)
    if (publish_time := _timestamp_millis(raw_time)) is not None:
        record["publish_time"] = publish_time
        record["publish_date"] = _publish_date(publish_time)
        record["date"] = record["published_at"] = _timestamp(raw_time)
        record["date_precision"] = "second"
        record["date_estimated"] = False
        record["date_source"] = source

    record["raw_share_count"] = record.get("shares")
    metric_sources = dict(_mapping(record.get("metric_sources")))
    for field in ("liked", "comments", "collected", "shares"):
        if record.get(field) is not None:
            metric_sources[field] = source
    if record.get("raw_share_count") is not None:
        metric_sources["raw_share_count"] = source
    record["metric_sources"] = metric_sources
    record["detail_source"] = source
    _annotate_legacy_quality(record)


def _detail_card(
    payload: Mapping[str, Any],
    expected_id: str,
    *,
    attempt_started_at: datetime,
    attempt_finished_at: datetime,
) -> Mapping[str, Any] | None:
    data, items = _payload_collection(payload, "items")
    # `current_time` proves this response belongs to the active browser run.
    # Do not promote a payload without it to current/fresh detail data.
    server_seconds = _detail_server_seconds(
        payload,
        attempt_started_at=attempt_started_at,
        attempt_finished_at=attempt_finished_at,
    )
    if server_seconds is None:
        return None
    for item in items:
        card = _mapping(item.get("note_card"))
        if _text(card.get("note_id")) == expected_id and _text(item.get("id")) in (None, expected_id):
            published_seconds = _timestamp_seconds(card.get("time"))
            if published_seconds is not None and published_seconds > server_seconds:
                return None
            return card
    return None


def _has_current_detail_time(
    payload: Mapping[str, Any],
    *,
    attempt_started_at: datetime,
    attempt_finished_at: datetime,
) -> bool:
    return _detail_server_seconds(
        payload,
        attempt_started_at=attempt_started_at,
        attempt_finished_at=attempt_finished_at,
    ) is not None


def _merge_detail(record: dict[str, Any], card: Mapping[str, Any], *, engagement_observed_at: str) -> None:
    info = _mapping(card.get("interact_info"))
    raw_time = _first_timestamp(card)
    date = _timestamp(raw_time)
    if date is not None:
        record["date"] = record["published_at"] = date
        record["date_precision"] = "second"
        record["date_estimated"] = False
        record["date_source"] = "detail_api"
        record["publish_time"] = _timestamp_millis(raw_time)
        record["publish_date"] = _publish_date(record["publish_time"])
    observed_fields: list[str] = []
    for field, source_key in (("liked", "liked_count"), ("comments", "comment_count"), ("collected", "collected_count"), ("shares", "share_count")):
        value = _detail_count(info, source_key)
        if value is not None:
            record[field] = value
            record["metric_sources"][field] = "detail_api"
            if field == "shares":
                record["metric_sources"]["raw_share_count"] = "detail_api"
            observed_fields.append("raw_share_count" if field == "shares" else field)
    record["raw_share_count"] = record.get("shares")
    for output, input_names in (
        ("title", ("display_title", "title")),
        ("desc", ("desc",)),
        ("type", ("type",)),
    ):
        value = next(
            (_text(card.get(input_name)) for input_name in input_names if _text(card.get(input_name)) is not None),
            None,
        )
        if value is not None:
            record[output] = value
    user = _mapping(card.get("user"))
    author = _text(user.get("nickname")) or _text(user.get("nick_name"))
    if author is not None:
        record["author"] = author
    avatar = _safe_content_url(user.get("avatar") or user.get("image"))
    if avatar is not None:
        record["author_avatar"] = avatar
    if (last_update := _timestamp_millis(card.get("last_update_time"))) is not None:
        record["last_update_time"] = last_update
    if (ip_location := _text(card.get("ip_location"))) is not None:
        record["ip_location"] = ip_location
    _merge_media_business_fields(record, card)
    _merge_tag_business_fields(record, card)
    record["detail_link"] = record.get("link")
    record["detail_source"] = "detail_api"
    record["detail_checked_at"] = _iso_timestamp_seconds(engagement_observed_at)
    _mark_metric_observations(record, observed_fields, engagement_observed_at)
    record["engagement_observed_at"] = engagement_observed_at
    record["engagement_source"] = "detail_api"
    _refresh_engagement_fresh(record)
    _annotate_legacy_quality(record)


def _merge_media_business_fields(
    record: dict[str, Any], card: Mapping[str, Any]
) -> None:
    image_details: list[dict[str, Any]] = []
    image_urls: list[str] = []
    for candidate in _as_sequence(card.get("image_list"))[:_MAX_MEDIA_ITEMS]:
        image = _mapping(candidate)
        url = _first_image_url(image)
        if url is None or url in image_urls:
            continue
        image_urls.append(url)
        image_details.append(
            {
                "url": url,
                "width": _dimension(image.get("width")),
                "height": _dimension(image.get("height")),
            }
        )
    if image_urls:
        record["images"] = image_urls
        record["image_count"] = len(image_urls)
        record["image_details"] = image_details
        if record.get("cover") is None:
            record["cover"] = image_urls[0]
            record["cover_width"] = image_details[0]["width"]
            record["cover_height"] = image_details[0]["height"]
    elif _text(card.get("type")) == "video":
        record["image_count"] = 0

    if record.get("cover") is None:
        cover = _mapping(card.get("cover"))
        if (cover_url := _first_image_url(cover)) is not None:
            record["cover"] = cover_url
            record["cover_width"] = _dimension(cover.get("width"))
            record["cover_height"] = _dimension(cover.get("height"))

    video_urls = _video_urls(card)
    if video_urls:
        record["video_urls"] = video_urls
        record["video_url"] = ",".join(video_urls)


def _merge_tag_business_fields(
    record: dict[str, Any], card: Mapping[str, Any]
) -> None:
    tags: list[str] = []
    desc = _text(record.get("desc")) or ""
    for match in re.findall(r"#([^#\n]{1,50}?)(?:\[话题\])?#", desc):
        tag = match.strip()
        if tag and tag not in tags:
            tags.append(tag)
    for candidate in _as_sequence(card.get("tag_list")):
        tag = _text(_mapping(candidate).get("name"))
        if tag is not None and len(tag) <= 100 and tag not in tags:
            tags.append(tag)
        if len(tags) >= _MAX_TAGS:
            break
    record["tags"] = tags
    record["tag_list"] = ",".join(tags) if tags else None


def _mark_metric_observations(
    record: dict[str, Any], fields: Sequence[str], observed_at: str
) -> None:
    observed_ms = _iso_timestamp_millis(observed_at)
    if observed_ms is None:
        return
    metric_observed_at = dict(_mapping(record.get("metric_observed_at")))
    detail_fields = [
        field
        for field in _as_sequence(record.get("engagement_detail_fields"))
        if isinstance(field, str)
    ]
    for field in fields:
        if field not in {"liked", "comments", "collected", "raw_share_count"}:
            continue
        metric_observed_at[field] = observed_ms
        if field not in detail_fields:
            detail_fields.append(field)
    record["metric_observed_at"] = metric_observed_at
    record["engagement_detail_fields"] = detail_fields
    observed = set(fields)
    record["engagement_stale_fields"] = [
        field
        for field in _as_sequence(record.get("engagement_stale_fields"))
        if isinstance(field, str) and field not in observed
    ]


def _refresh_engagement_fresh(record: dict[str, Any]) -> None:
    stale_fields = {
        field
        for field in _as_sequence(record.get("engagement_stale_fields"))
        if isinstance(field, str)
    }
    record["engagement_fresh"] = bool(
        not stale_fields.intersection(_REQUIRED_DETAIL_METRICS)
        and all(
            _has_fresh_detail_metric(record, field)
            for field in _REQUIRED_DETAIL_METRICS
        )
    )


def _annotate_legacy_quality(record: dict[str, Any]) -> None:
    missing: list[str] = []
    if not _text(record.get("desc")):
        missing.append("desc")
    for field in ("liked", "comments", "collected"):
        if record.get(field) is None:
            missing.append(field)
    if not _text(record.get("date")):
        missing.append("date")
    if not (
        _as_sequence(record.get("images"))
        or _as_sequence(record.get("video_urls"))
        or _safe_content_url(record.get("cover"))
    ):
        missing.append("media")
    if not _as_sequence(record.get("tags")):
        missing.append("tags")
    record["quality_missing_fields"] = missing
    record["quality_score"] = sum(
        (
            not _placeholder(record.get("title")),
            bool(_text(record.get("desc"))),
            record.get("liked") is not None,
            record.get("comments") is not None,
            record.get("collected") is not None,
            bool(_text(record.get("date"))),
            "media" not in missing,
            "tags" not in missing,
        )
    )


def _merge_detail_html(record: dict[str, Any], observation: Mapping[str, Any]) -> None:
    metrics = _mapping(observation.get("metrics"))
    source = "detail_html"
    changed = False
    observed_fields: list[str] = []
    for field in ("liked", "comments", "collected"):
        value = parse_count(metrics.get(field))
        if value is not None:
            record[field] = value
            record["metric_sources"][field] = source
            changed = True
            observed_fields.append(field)
    if changed:
        observed_at = _observed_at()
        record["engagement_observed_at"] = observed_at
        record["engagement_source"] = source
        record["detail_source"] = source
        record["detail_checked_at"] = _iso_timestamp_seconds(observed_at)
        _mark_metric_observations(record, observed_fields, observed_at)
        _refresh_engagement_fresh(record)
        _annotate_legacy_quality(record)


def _missing_required_metrics(record: Mapping[str, Any]) -> list[str]:
    return [
        field
        for field in _REQUIRED_DETAIL_METRICS
        if not _has_fresh_detail_metric(record, field)
    ]


def _has_fresh_detail_metric(record: Mapping[str, Any], field: str) -> bool:
    source = _mapping(record.get("metric_sources")).get(field)
    return record.get(field) is not None and source in _FRESH_DETAIL_METRIC_SOURCES


def _supplement_missing_detail_html(
    record: dict[str, Any], observation: Mapping[str, Any]
) -> None:
    metrics = _mapping(observation.get("metrics"))
    observed_fields: list[str] = []
    for field in _REQUIRED_DETAIL_METRICS:
        if _has_fresh_detail_metric(record, field):
            continue
        value = parse_count(metrics.get(field))
        if value is not None:
            record[field] = value
            record["metric_sources"][field] = "detail_html"
            observed_fields.append(field)
    if observed_fields:
        observed_at = _observed_at()
        _mark_metric_observations(record, observed_fields, observed_at)
        _refresh_engagement_fresh(record)
        _annotate_legacy_quality(record)


def _missing_completion(record: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    missing_metrics = _missing_required_metrics(record)
    if not _safe_note_id(record.get("note_id")):
        missing.append("note_id")
    if _placeholder(record.get("title")):
        missing.append("title")
    if not _text(record.get("date")) or record.get("date_precision") != "second":
        missing.append("date")
    if record.get("detail_attempted") is not True:
        missing.append("detail_attempted")
    if record.get("detail_completed") is not True:
        missing.append("detail")
    if record.get("engagement_fresh") is not True and (
        not missing_metrics
        or record.get("engagement_source")
        not in {"detail_api", "detail_html", "detail_cdp"}
    ):
        missing.append("engagement_fresh")
    if record.get("engagement_source") not in {"detail_api", "detail_html", "detail_cdp"}:
        missing.append("engagement_source")
    missing.extend(missing_metrics)
    return missing


async def _read_creator_cards(page: Any) -> Mapping[str, Any]:
    value = await page.evaluate("""() => {
        /* creator DOM fallback */
        const isVisible = (element) => {
            if (!element) return false;
            if (typeof element.checkVisibility === 'function' && !element.checkVisibility({
                checkOpacity: true,
                checkVisibilityCSS: true,
            })) return false;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return !element.hidden
                && element.getAttribute('aria-hidden') !== 'true'
                && style.display !== 'none'
                && style.visibility !== 'hidden'
                && Number(style.opacity) !== 0
                && rect.width > 0
                && rect.height > 0;
        };
        const text = (card, selectors) => {
            for (const selector of selectors) {
                const element = card.querySelector(selector);
                if (!isVisible(element)) continue;
                const value = element?.innerText?.trim();
                if (value) return value;
            }
            return null;
        };
        const cards = Array.from(document.querySelectorAll(
            '#userPostedFeeds .note-item[data-note-id]'
        )).filter(isVisible).map((card) => ({
            note_id: card.getAttribute('data-note-id'),
            title: text(card, ['.footer > a.title', '.footer .title']),
            author: text(card, ['.author-wrapper .name', '.author-wrapper .author', '.author-wrapper']),
            liked: text(card, ['.like-wrapper .count']),
        }));
        return {cards};
    }""")
    return value if isinstance(value, Mapping) else {"cards": []}


async def _read_search_cards(page: Any) -> Mapping[str, Any]:
    value = await page.evaluate("""() => {
        /* search card business fields */
        const body = document.body?.innerText || '';
        const challenge = document.querySelector('.geetest_panel, .geetest_holder, iframe[src*="captcha"], [class*="captcha"]');
        const phrases = ['请完成验证','访问受限','请求过于频繁','账号异常','风控','安全验证','验证码'];
        const risk_text = challenge ? 'challenge-selector' : (phrases.find((word) => body.includes(word)) || '');
        const isVisible = (element) => {
            if (!element || !element.isConnected) return false;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none'
                && style.visibility !== 'hidden'
                && Number(style.opacity) !== 0
                && rect.width > 0
                && rect.height > 0;
        };
        const text = (card, selectors) => {
            for (const selector of selectors) {
                const element = card.querySelector(selector);
                if (!isVisible(element)) continue;
                const value = element?.textContent?.trim();
                if (value) return value;
            }
            return null;
        };
        const metric = (card, selectors, attribute) => (
            text(card, selectors) || card.getAttribute(attribute) || null
        );
        const imageUrl = (image) => {
            if (!isVisible(image)) return null;
            return image.currentSrc || image.getAttribute('src') || null;
        };
        const dimension = (image, name) => {
            if (!image) return null;
            const natural = name === 'width' ? image.naturalWidth : image.naturalHeight;
            if (Number.isFinite(natural) && natural > 0) return natural;
            return image.getAttribute(name) || null;
        };
        const cards = Array.from(document.querySelectorAll(
            '.feeds-page .search-layout__main .feeds-container .note-item[data-note-id]'
        )).filter(isVisible).map((card) => {
            const coverLink = card.querySelector('a.cover.mask');
            const coverImage = coverLink?.querySelector('img') || card.querySelector('.cover img');
            const authorImage = card.querySelector('.author-wrapper img, .card-bottom-wrapper img');
            const timeElement = card.querySelector(
                'time[datetime], [data-publish-time], [data-time]'
            );
            const explicitType = card.getAttribute('data-note-type')
                || card.getAttribute('data-type');
            const videoMarker = card.querySelector('video, .video-icon, .play-icon');
            return {
                note_id: card.getAttribute('data-note-id'),
                title: text(card, ['.footer > a.title', '.footer .title']),
                desc: text(card, ['.footer .desc', '.footer .description', '.desc']),
                type: explicitType || (isVisible(videoMarker) ? 'video' : null),
                author: text(card, [
                    '.author-wrapper .name',
                    '.author-wrapper .author',
                    '.card-bottom-wrapper .name',
                    '.author-wrapper',
                    '.card-bottom-wrapper',
                ]),
                author_avatar: imageUrl(authorImage),
                liked: metric(card, ['.like-wrapper .count'], 'data-liked-count'),
                comments: metric(
                    card,
                    ['.comment-wrapper .count', '.chat-wrapper .count'],
                    'data-comment-count'
                ),
                collected: metric(
                    card,
                    ['.collect-wrapper .count'],
                    'data-collected-count'
                ),
                shares: metric(
                    card,
                    ['.share-wrapper .count'],
                    'data-share-count'
                ),
                publish_time: card.getAttribute('data-publish-time')
                    || card.getAttribute('data-time')
                    || timeElement?.getAttribute('datetime')
                    || timeElement?.getAttribute('data-time')
                    || null,
                cover: {
                    url: imageUrl(coverImage),
                    width: dimension(coverImage, 'width'),
                    height: dimension(coverImage, 'height'),
                },
                image_count: card.getAttribute('data-image-count')
                    || text(card, ['.image-count', '.image-count-badge']),
            };
        });
        return {risk_text, cards};
    }""")
    return value if isinstance(value, Mapping) else {"risk_text": "", "cards": []}


async def _read_detail_html(page: Any) -> Mapping[str, Any]:
    value = await page.evaluate("""() => {
        const body = document.body?.innerText || ''; const modal = document.querySelector('.note-container');
        const phrases = ['请完成验证','访问受限','请求过于频繁','账号异常','风控','安全验证','验证码'];
        const risk_text = !modal ? '' : (phrases.find((word) => body.includes(word)) || '');
        const count = (selector) => modal?.querySelector(selector)?.textContent || null;
        return {risk_text, metrics: {liked: count('.engage-bar .like-wrapper .count'), collected: count('.engage-bar .collect-wrapper .count'), comments: count('.engage-bar .chat-wrapper .count')}};
    }""")
    return value if isinstance(value, Mapping) else {"risk_text": "", "metrics": {}}


async def _wait_for_detail_metrics(
    page: Any, missing_fields: list[str]
) -> Mapping[str, Any]:
    observation: Mapping[str, Any] = {"risk_text": "", "metrics": {}}
    for attempt in range(_DETAIL_METRIC_POLL_ATTEMPTS + 1):
        observation = await _read_detail_html(page)
        _raise_for_observation(observation)
        metrics = _mapping(observation.get("metrics"))
        if all(parse_count(metrics.get(field)) is not None for field in missing_fields):
            return observation
        if attempt == _DETAIL_METRIC_POLL_ATTEMPTS:
            return observation
        await page.wait_for_timeout(_DETAIL_METRIC_POLL_INTERVAL_MS)
        await _raise_for_challenge(page)
    return observation  # pragma: no cover - the bounded loop always returns


async def _read_comments(page: Any, limit: int) -> Mapping[str, Any]:
    value = await page.evaluate("""(limit) => {
        const body = document.body?.innerText || ''; const phrases = ['请完成验证','访问受限','请求过于频繁','账号异常','风控','安全验证','验证码'];
        const risk_text = phrases.find((word) => body.includes(word)) || '';
        const comments = Array.from(document.querySelectorAll('.comments-container .comment-item, .comments-el .comment-item')).slice(0, limit).map((item) => ({
            author: item.querySelector('.author .name')?.textContent || null, text: item.querySelector('.content .note-text')?.textContent || null,
            date: item.querySelector('.info .date')?.textContent || null, liked: item.querySelector('.interactions .like .count')?.textContent || null,
        })); return {risk_text, comments};
    }""", limit)
    return value if isinstance(value, Mapping) else {"risk_text": "", "comments": []}


async def _raise_for_challenge(page: Any) -> None:
    value = await page.evaluate("""() => {
        const body = document.body?.innerText || ''; const selector = document.querySelector('.geetest_panel, .geetest_holder, iframe[src*="captcha"], [class*="captcha"]');
        const phrases = ['请完成验证','访问受限','请求过于频繁','账号异常','风控','安全验证','验证码'];
        return {risk_text: selector ? 'challenge-selector' : (phrases.find((word) => body.includes(word)) || '')};
    }""")
    _raise_for_observation(value if isinstance(value, Mapping) else {})


def _raise_for_observation(observation: Mapping[str, Any]) -> None:
    risk = _text(observation.get("risk_text"))
    if risk:
        raise CollectionStopped(risk)


async def _scroll_and_check(page: Any) -> None:
    await _raise_for_challenge(page)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await _raise_for_challenge(page)


async def _wait_for_search_settled(page: Any) -> None:
    prior_state: str | None = None
    for attempt in range(_SEARCH_SETTLE_ATTEMPTS):
        observation = await _read_search_settlement(page)
        _raise_for_observation(observation)
        state = _text(observation.get("state"))
        if state is not None and state == prior_state:
            return
        prior_state = state
        if attempt + 1 < _SEARCH_SETTLE_ATTEMPTS:
            await page.wait_for_timeout(_SEARCH_SETTLE_INTERVAL_MS)
    raise SourceResponseError("Xiaohongshu search page did not settle")


async def _read_search_settlement(page: Any) -> Mapping[str, Any]:
    value = await page.evaluate("""() => {
        /* search settlement observation */
        const body = document.body?.innerText || '';
        const challenge = document.querySelector('.geetest_panel, .geetest_holder, iframe[src*="captcha"], [class*="captcha"]');
        const phrases = ['请完成验证','访问受限','请求过于频繁','账号异常','风控','安全验证','验证码'];
        const risk_text = challenge ? 'challenge-selector' : (phrases.find((word) => body.includes(word)) || '');
        const isVisible = (element) => {
            if (!element) return false;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0;
        };
        const loading = Array.from(document.querySelectorAll(
            '.feeds-page .search-layout__main .loading, .feeds-page .search-layout__main .loading-container, '
            + '.feeds-page .search-layout__main .skeleton, .feeds-page .search-layout__main .skeleton-item'
        )).some(isVisible);
        if (loading) return {risk_text, state: null};
        const noteIds = Array.from(document.querySelectorAll(
            '.feeds-page .search-layout__main .feeds-container .note-item[data-note-id]'
        )).filter(isVisible).map((item) => item.getAttribute('data-note-id')).filter(Boolean).sort();
        if (noteIds.length) return {risk_text, state: `cards:${noteIds.join('|')}`};
        const terminalEmpty = Array.from(document.querySelectorAll(
            '.feeds-page .search-layout__main .search-no-result'
        )).find((element) => isVisible(element) && ['暂无搜索结果','未找到相关笔记','没有找到'].some((word) => (element.textContent || '').includes(word)));
        return {risk_text, state: terminalEmpty ? 'empty:search-no-result' : null};
    }""")
    return value if isinstance(value, Mapping) else {"risk_text": "", "state": None}


async def _wait_for_card_change(page: Any, note_ids: list[str]) -> None:
    await page.wait_for_function("""(prior) => {
        /* unseen note card */
        const body = document.body?.innerText || '';
        const challenge = document.querySelector('.geetest_panel, .geetest_holder, iframe[src*="captcha"], [class*="captcha"]');
        const phrases = ['请完成验证','访问受限','请求过于频繁','账号异常','风控','安全验证','验证码'];
        if (challenge || phrases.some((word) => body.includes(word))) return true;
        const priorSet = new Set(prior);
        const ids = Array.from(document.querySelectorAll('.feeds-page .search-layout__main .feeds-container .note-item[data-note-id]')).map((el) => el.getAttribute('data-note-id')).filter(Boolean);
        return ids.some((noteId) => !priorSet.has(noteId));
    }""", arg=note_ids, timeout=10_000)
    await _raise_for_challenge(page)


async def _wait_for_note_card(page: Any, note_id: str) -> bool:
    try:
        await page.wait_for_function("""(expected) => {
            /* exact note card rendered */
            /* challenge-selector */
            const body = document.body?.innerText || '';
            const challenge = document.querySelector('.geetest_panel, .geetest_holder, iframe[src*="captcha"], [class*="captcha"]');
            const phrases = ['请完成验证','访问受限','请求过于频繁','账号异常','风控','安全验证','验证码'];
            if (challenge || phrases.some((word) => body.includes(word))) return true;
            return Array.from(document.querySelectorAll('#userPostedFeeds .note-item[data-note-id]'))
                .some((item) => item.getAttribute('data-note-id') === expected);
        }""", arg=note_id, timeout=10_000)
    except PlaywrightTimeoutError:
        await _raise_for_challenge(page)
        return False
    await _raise_for_challenge(page)
    return True


_EXACT_CREATOR_CARD_SCRIPT = """(item, expected) => {
    /* exact creator card interaction */
    const isVisible = (element) => {
        if (!element || !element.isConnected) return false;
        const style = window.getComputedStyle(element);
        if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    return item.getAttribute('data-note-id') === expected && isVisible(item);
}"""


_EXACT_CREATOR_TARGET_SCRIPT = """(item, args) => {
    /* exact creator card interaction */
    const isVisible = (element) => {
        if (!element || !element.isConnected) return false;
        const style = window.getComputedStyle(element);
        if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    return item.getAttribute('data-note-id') === args.expected
        && isVisible(item)
        && item.contains(args.target)
        && isVisible(args.target);
}"""


async def _click_note_and_check(page: Any, note_id: str) -> None:
    await _raise_for_challenge(page)
    starting_url = getattr(page, "url", "")
    cards = await page.locator(
        "#userPostedFeeds .note-item[data-note-id]"
    ).element_handles()
    selected_card = None
    click_target = None
    try:
        for card in cards:
            # The id is passed as an argument, never interpolated into CSS.
            if not await card.evaluate(_EXACT_CREATOR_CARD_SCRIPT, note_id):
                continue
            selected_card = card
            for selector in ("a.cover.mask.ld", "a.title"):
                candidate = await card.query_selector(selector)
                if candidate is None:
                    continue
                click_target = candidate
                if await card.evaluate(
                    _EXACT_CREATOR_TARGET_SCRIPT,
                    {"expected": note_id, "target": candidate},
                ):
                    break
                await _dispose_element_handle(click_target)
                click_target = None
            break
        await _raise_for_challenge(page)
        if (
            getattr(page, "url", "") != starting_url
            or selected_card is None
            or click_target is None
            or not await selected_card.evaluate(
                _EXACT_CREATOR_TARGET_SCRIPT,
                {"expected": note_id, "target": click_target},
            )
            or getattr(page, "url", "") != starting_url
        ):
            raise PlaywrightError("current note card is unavailable")
        await click_target.click(timeout=5_000)
        await _raise_for_challenge(page)
    finally:
        await _dispose_element_handle(click_target)
        for card in cards:
            await _dispose_element_handle(card)


async def _dispose_element_handle(handle: Any) -> None:
    if handle is None:
        return
    try:
        await handle.dispose()
    except (AttributeError, PlaywrightError, PlaywrightTimeoutError, TypeError):
        pass


async def _close_modal(page: Any) -> None:
    # Close first: risk detection must not leave the user-facing overlay open.
    modal = page.locator(".note-container")
    close = modal.locator(".close-circle")
    try:
        if await close.is_visible(timeout=1_000):
            await close.click(timeout=2_000)
        else:
            await page.keyboard.press("Escape")
    except (PlaywrightError, PlaywrightTimeoutError, TypeError):
        try:
            await page.keyboard.press("Escape")
        except (PlaywrightError, PlaywrightTimeoutError, TypeError):
            pass
    try:
        await modal.wait_for(state="hidden", timeout=3_000)
    except (AttributeError, PlaywrightError, PlaywrightTimeoutError, TypeError):
        pass
    await _raise_for_challenge(page)


def _safe_comments(items: Sequence[Any], limit: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping) or len(output) >= limit:
            continue
        output.append({"author": _text(item.get("author")), "text": _text(item.get("text")), "date": _text(item.get("date")), "liked": parse_count(item.get("liked"))})
    return output


def _creator_url(uid: str) -> str:
    return f"https://{_HOST}/user/profile/{quote(uid, safe='')}"


def _search_url(keyword: str) -> str:
    return f"https://{_HOST}/search_result?keyword={quote(keyword, safe='')}&source=web_search_result_notes"


def _explore_link(note_id: str | None) -> str | None:
    return f"https://{_HOST}/explore/{note_id}" if _safe_note_id(note_id) else None


def _require_open_target(page: Any, target: str, label: str) -> None:
    current, expected = urlparse(getattr(page, "url", "")), urlparse(target)
    if current.hostname != expected.hostname or current.path != expected.path or current.query != expected.query:
        raise PreconditionError(f"an open {label} is required when navigation is disabled")


def _has_more(value: object) -> bool:
    return value is True or value == 1


def _empty_cursor(cursor: object) -> bool:
    return cursor is None or cursor == ""


def _safe_note_id(value: object) -> bool:
    return isinstance(value, str) and _NOTE_ID.fullmatch(value) is not None


def _placeholder(value: object) -> bool:
    return not isinstance(value, str) or value.strip().casefold() in _PLACEHOLDERS


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _int_like(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        try:
            return int(value)
        except (OverflowError, ValueError):
            return None
    return None


def _dimension(value: object) -> int | None:
    result = _int_like(value)
    return result if result is not None and 0 <= result <= _MAX_COUNT else None


def _observable_timestamp_millis(data: Mapping[str, Any]) -> int | None:
    for field in ("publish_time", "time", "create_time", "datetime"):
        value = data.get(field)
        if (milliseconds := _timestamp_millis(value)) is not None:
            return milliseconds
        if (milliseconds := _iso_timestamp_millis(value)) is not None:
            return milliseconds
    return None


def _first_timestamp(data: Mapping[str, Any]) -> object:
    for source in (data, _mapping(data.get("note_card"))):
        for field in ("time", "create_time", "publish_time", "posted_time", "timestamp"):
            value = source.get(field)
            if _timestamp_seconds(value) is not None:
                return value
    return None


def _timestamp_millis(value: object) -> int | None:
    seconds = _timestamp_seconds(value)
    return int(seconds * 1000) if seconds is not None else None


def _publish_date(value: object) -> str | None:
    seconds = _timestamp_seconds(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, _CHINA_TIMEZONE).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def _iso_timestamp_millis(value: object) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    timestamp = parsed.timestamp()
    return int(timestamp * 1000) if math.isfinite(timestamp) and timestamp > 0 else None


def _iso_timestamp_seconds(value: object) -> int | None:
    milliseconds = _iso_timestamp_millis(value)
    return milliseconds // 1000 if milliseconds is not None else None


def _safe_content_url(value: object) -> str | None:
    text = _text(value)
    if text is None or len(text) > 8192:
        return None
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
            if not _SENSITIVE_URL_KEY.search(key)
            and not _SENSITIVE_URL_PART.search(item)
        ],
        doseq=True,
    )
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, "")
    )


def _first_image_url(image: Mapping[str, Any]) -> str | None:
    for field in ("url_default", "url_pre", "url"):
        if (url := _safe_content_url(image.get(field))) is not None:
            return url
    for candidate in _as_sequence(image.get("info_list")):
        if (url := _safe_content_url(_mapping(candidate).get("url"))) is not None:
            return url
    return None


def _video_urls(card: Mapping[str, Any]) -> list[str]:
    if _text(card.get("type")) != "video":
        return []
    video = _mapping(card.get("video"))
    consumer = _mapping(video.get("consumer"))
    origin_key = _text(
        consumer.get("origin_video_key") or consumer.get("originVideoKey")
    )
    candidates: list[object] = []
    if origin_key is not None and not _SENSITIVE_URL_PART.search(origin_key):
        candidates.append(
            f"https://sns-video-bd.xhscdn.com/{quote(origin_key, safe='/._-')}"
        )
    stream = _mapping(_mapping(video.get("media")).get("stream"))
    for codec in ("h264", "h265", "av1"):
        for item in _as_sequence(stream.get(codec))[:_MAX_MEDIA_ITEMS]:
            payload = _mapping(item)
            candidates.append(payload.get("master_url"))
            candidates.extend(_as_sequence(payload.get("backup_urls")))
    output: list[str] = []
    for candidate in candidates:
        url = _safe_content_url(candidate)
        if url is not None and url not in output:
            output.append(url)
        if len(output) >= _MAX_MEDIA_ITEMS:
            break
    return output


def _timestamp(value: object) -> str | None:
    seconds = _timestamp_seconds(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC).replace(microsecond=0).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _timestamp_seconds(value: object) -> float | None:
    if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        try:
            value = float(value)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
    try:
        datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return seconds


def _detail_server_seconds(
    payload: Mapping[str, Any],
    *,
    attempt_started_at: datetime,
    attempt_finished_at: datetime,
) -> float | None:
    server_seconds = _timestamp_seconds(_mapping(payload.get("data")).get("current_time"))
    if server_seconds is None:
        return None
    earliest = attempt_started_at.timestamp() - _DETAIL_ATTEMPT_SKEW_SECONDS
    latest = attempt_finished_at.timestamp() + _DETAIL_ATTEMPT_SKEW_SECONDS
    if latest < earliest or not earliest <= server_seconds <= latest:
        return None
    return server_seconds


def _detail_server_observed_at(
    payload: Mapping[str, Any],
    *,
    attempt_started_at: datetime,
    attempt_finished_at: datetime,
) -> str | None:
    server_seconds = _detail_server_seconds(
        payload,
        attempt_started_at=attempt_started_at,
        attempt_finished_at=attempt_finished_at,
    )
    if server_seconds is None:
        return None
    # The server value proves freshness, while the public observation uses the
    # precise local completion instant so it cannot precede this run's start
    # merely because the server timestamp is millisecond-granular.
    return attempt_finished_at.astimezone(UTC).isoformat(timespec="microseconds")


def _observed_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _safe_report_reason(value: object) -> str:
    """Keep operational reason codes, never an arbitrary server/body message."""
    reason = value.strip().casefold() if isinstance(value, str) else ""
    if reason in {
        "ok",
        "count-shortfall",
        "incomplete-record",
        "preflight-aborted",
        "prior-risk-stop",
        "module-not-found",
        "precondition-failed",
        "source-response-failed",
        "http-403",
        "http-429",
        "payload-461",
        "payload-471",
        "payload-999",
        "challenge",
        "risk-signal",
        "platform-timeout",
        "creator-capture-timeout",
        "detail-capture-timeout",
        "invalid-records",
        "unexpected",
    }:
        return reason
    return "risk-signal"
