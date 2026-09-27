"""Bounded visible-list collection for the CDP visible-page helpers.

Only page-visible fields are emitted. This module never requests response
bodies, opens details, downloads media, or changes browser owner.
"""
from datetime import UTC, datetime
import re
from urllib.parse import urlparse, urlunparse

from .browser import BrowserRiskError, PreconditionError
from .extraction import legacy_list_expression, risk_expression, login_expression
from .platforms import bilibili, douyin, weibo, xhs


def target_url(request):
    module = {"bilibili": bilibili, "douyin": douyin, "weibo": weibo, "xhs": xhs}[request.platform]
    if request.platform == "xhs":
        return module._creator_url(request.uid) if request.uid else module._search_url(request.keyword)
    return module._creator_page_url(request.uid) if request.uid else module._search_page_url(request.keyword)


def _identity(platform, item):
    for link in item.get("links", []):
        if not isinstance(link, str):
            continue
        parsed = urlparse(link)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            continue
        key = native = None
        if platform == "bilibili" and parsed.hostname in {"www.bilibili.com", "bilibili.com", "t.bilibili.com"}:
            match = re.fullmatch(r"/video/(BV[A-Za-z0-9]{10})/?", parsed.path)
            if match:
                key, native = "bvid", match[1]
            else:
                match = re.fullmatch(r"/(?:opus/)?([0-9]{1,32})/?", parsed.path)
                if match:
                    key, native = "dynamic_id", match[1]
        elif platform == "xhs" and parsed.hostname in {"xiaohongshu.com", "www.xiaohongshu.com"}:
            match = re.fullmatch(r"/(?:explore|discovery/item)/([a-fA-F0-9]{24})/?", parsed.path)
            if match:
                key, native = "note_id", match[1]
        elif platform == "douyin" and parsed.hostname in {"douyin.com", "www.douyin.com"}:
            match = re.fullmatch(r"/video/([0-9]{1,32})/?", parsed.path)
            if match:
                key, native = "aweme_id", match[1]
        elif platform == "weibo" and parsed.hostname in {"weibo.com", "www.weibo.com"}:
            match = re.fullmatch(r"/[0-9]{1,32}/[A-Za-z0-9]{1,32}/?", parsed.path)
            raw = item.get("raw")
            if match and isinstance(raw, str) and re.fullmatch(r"[0-9]{1,32}", raw):
                key, native = "mblog_id", raw
        if native:
            return key, native, urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return None


async def _check(page):
    risk = await page.evaluate(risk_expression())
    if isinstance(risk, dict) and risk.get("risk") is True:
        raise BrowserRiskError("challenge")
    login = await page.evaluate(login_expression())
    if isinstance(login, dict) and login.get("logged_out") is True:
        raise PreconditionError("platform login required")


async def collect_page(request, browser):
    if request.complete or request.comment_limit or request.screenshot_mode != "off":
        raise PreconditionError("page backend does not provide detail, comments or screenshots")
    page = browser.require_page(request.platform)
    target = target_url(request)
    if not request.continue_page or page.url != target:
        if not browser.allow_navigation:
            if page.url != target:
                raise PreconditionError("exact target page is not open")
        else:
            await _check(page)
            await browser.navigate(page, target, allowed_hosts=(urlparse(target).hostname,))
    elif page.url != target:
        raise PreconditionError("target page changed")
    records = []
    seen = set(request.exclude_ids)
    browser.last_pages = 0
    for index in range(request.page_cap):
        await _check(page)
        if page.url != target:
            raise PreconditionError("target page changed")
        observation = await page.evaluate(legacy_list_expression(request.platform))
        if not isinstance(observation, dict) or not isinstance(observation.get("items"), list):
            raise PreconditionError("invalid page observation")
        browser.last_pages += 1
        for item in observation["items"]:
            if not isinstance(item, dict):
                continue
            identity = _identity(request.platform, item)
            if identity is None or identity[1] in seen:
                continue
            key, native, link = identity
            seen.add(native)
            record = {"platform": request.platform, "type": "post", key: native, "native_id": native,
                      "link": link, "title": item.get("title") or item.get("text"), "author": item.get("author"),
                      "date_text": item.get("date_text"), "observed_at": datetime.now(UTC).isoformat(),
                      "backend": request.backend, "evidence_level": "page", "source_url": target,
                      "field_quality": {"title": "visible", "liked": "missing", "comments": "missing"},
                      "liked": None, "comments": None, "shares": None}
            records.append(record)
            browser.publish_progress(request.platform, records)
            if request.target_count is not None and len(records) >= request.target_count:
                return records
        if index + 1 < request.page_cap:
            await _check(page)
            await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            await page.wait_for_timeout(3000 if request.platform == "xhs" else 1500)
    return records
