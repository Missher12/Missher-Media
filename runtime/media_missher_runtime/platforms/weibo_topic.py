"""微博话题参与用户发现与公开主页采集。

数据流（`DEEPSEEK_V4_PROMPT.md` 第三节第 4 条）：

``核验话题 → 分页读取可见话题帖子 → 提取外层发帖用户 → 按微博 UID 去重
→ 依次访问这些用户的公开主页 → 提取可见资料 → 保存帖子/用户/话题关系``

范围边界：

* “参与用户”只包含当前可访问话题帖子中的外层发布者，含确实出现在结果里的
  转发发帖者。引用原作者、推荐卡片作者、浏览者或点赞者都不算参与者。
* 只采集公开且页面实际可见的主页字段。页面没有的字段留 ``null``，缩写数值
  保留原文并标注精度。
* 不递归抓取这些用户的全部微博、关注列表或粉丝关系，不采集私信、Cookie、
  Token、密码，也不绕过任何权限。
* 同一运行内同一用户主页只抓一次，多个话题关系分别保留。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from ..contracts import (
    BACKEND_CDP,
    EVIDENCE_PAGE,
    EVIDENCE_RESPONSE,
    TOPIC_KIND_STANDARD,
    TOPIC_KIND_SUPER,
    Target,
)
from ..extraction import as_items, as_mapping, display_metric_fields


WEIBO_HOSTS: tuple[str, ...] = ("weibo.com", "www.weibo.com", "m.weibo.cn", "s.weibo.com")
SEARCH_HOST = "s.weibo.com"
TOPIC_HOST = "s.weibo.com"
PARSER_VERSION = "weibo-topic-1"

#: ``#话题#`` 与超话不是同一种页面。普通话题走 ``s.weibo.com/weibo?q=%23话题%23``；
#: 超话走 ``weibo.com/p/100808...`` 一类的超话主页，需要另一套解析路径。
SUPER_TOPIC_PATH = re.compile(r"^/p/100808[0-9a-zA-Z]+/?$")
STANDARD_TOPIC_PATH = re.compile(r"^/weibo/?$")
PROFILE_PATH = re.compile(r"^/u/([0-9]{1,32})/?$")
PROFILE_ALIAS_PATH = re.compile(r"^/([0-9]{1,32})/?$")
#: 微博原生帖子 ID（mid）与用户 UID 都是纯数字；昵称、域名等文本标识不能当 ID 用。
_MID = re.compile(r"[0-9]{1,32}")

_UID = re.compile(r"[0-9]{1,32}")
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ABBREVIATED = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([万亿wWkK])\s*$")
_ABBREVIATION_FACTOR = {"万": 10_000, "w": 10_000, "亿": 100_000_000, "k": 1_000}


class TopicError(RuntimeError):
    """话题输入无法核验为受支持的微博话题。"""


class CollectionStopped(RuntimeError):
    """平台风险信号要求立即停止。"""


class SourceResponseError(RuntimeError):
    """观察到的话题来源响应不可用。"""


@dataclass(frozen=True, slots=True)
class TopicInput:
    """规范化后的话题输入。"""

    kind: str
    name: str
    page_url: str
    container_id: str | None = None

    @property
    def identity(self) -> str:
        return f"weibo:topic:{self.kind}:{self.container_id or self.name}"


def parse_topic_input(value: str) -> TopicInput:
    """识别用户给出的话题名称或官方链接。

    普通 ``#话题#`` 与超话使用各自解析路径。尚不支持的类型给出准确说明，
    而不是把普通关键词搜索冒充超话采集。
    """

    if not isinstance(value, str) or not value.strip():
        raise TopicError("topic-input-empty")
    text = value.strip()
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        if parsed.hostname not in WEIBO_HOSTS:
            raise TopicError("topic-host-unsupported")
        if SUPER_TOPIC_PATH.match(parsed.path):
            container = parsed.path.rsplit("/", 1)[-1]
            if _SAFE_ID.fullmatch(container) is None:
                raise TopicError("topic-container-invalid")
            return TopicInput(
                kind=TOPIC_KIND_SUPER,
                name=container,
                page_url=f"https://weibo.com{parsed.path}",
                container_id=container,
            )
        if STANDARD_TOPIC_PATH.match(parsed.path) and parsed.hostname == TOPIC_HOST:
            values = parse_qs(parsed.query, keep_blank_values=True).get("q") or []
            name = _standard_topic_name(values[0]) if values else None
            if name is None:
                raise TopicError("topic-query-invalid")
            return TopicInput(
                kind=TOPIC_KIND_STANDARD,
                name=name,
                page_url=standard_topic_url(name),
            )
        if parsed.hostname in {"weibo.com", "www.weibo.com"} and parsed.path.startswith("/p/"):
            raise TopicError("topic-container-unsupported")
        raise TopicError("topic-path-unsupported")
    return TopicInput(
        kind=TOPIC_KIND_STANDARD,
        name=_standard_topic_name(text) or text,
        page_url=standard_topic_url(_standard_topic_name(text) or text),
    )


def _standard_topic_name(value: str) -> str | None:
    text = value.strip()
    if not text or len(text) > 200:
        return None
    if text.startswith("#") and text.endswith("#") and len(text) > 2:
        return text[1:-1].strip() or None
    if text.startswith("#") or text.endswith("#"):
        return None
    return text


def standard_topic_url(name: str) -> str:
    clean = name.strip().lstrip("#").rstrip("#").strip()
    if not clean:
        raise TopicError("topic-name-empty")
    return f"https://{TOPIC_HOST}/weibo?q={quote(f'#{clean}#', safe='')}"


def profile_url(uid: str) -> str:
    if not isinstance(uid, str) or _UID.fullmatch(uid) is None:
        raise TopicError("profile-uid-invalid")
    return f"https://weibo.com/u/{uid}"


def canonical_profile_url(value: object) -> str | None:
    """把页面里出现的各种主页写法归一到 ``https://weibo.com/u/<uid>``。"""

    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value if "//" in value else f"https://weibo.com{value}")
    if parsed.hostname not in WEIBO_HOSTS:
        return None
    match = PROFILE_PATH.match(parsed.path)
    if match is not None:
        return profile_url(match.group(1))
    match = PROFILE_ALIAS_PATH.match(parsed.path)
    if match is not None and parsed.path != "/u":
        return profile_url(match.group(1))
    return None


def uid_from_href(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value if "//" in value else f"https://weibo.com{value}")
    if parsed.hostname not in WEIBO_HOSTS:
        return None
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("uid", "id"):
        values = query.get(key) or []
        if values and _UID.fullmatch(values[0]):
            return values[0]
    match = PROFILE_PATH.match(parsed.path)
    if match is not None:
        return match.group(1)
    return None


def parse_display_metric(value: object) -> tuple[int | float | None, str, str | None]:
    """解析页面展示的计数，返回数值、精度与原始展示文本。"""

    if isinstance(value, bool):
        return None, "unknown", None
    if isinstance(value, int):
        return value, "exact", str(value)
    text = value.strip() if isinstance(value, str) else None
    if not text:
        return None, "unknown", None
    normalized = text.replace(",", "").replace("，", "").strip()
    match = _ABBREVIATED.match(normalized)
    if match is not None:
        return float(match.group(1)) * _ABBREVIATION_FACTOR[match.group(2).casefold()], "rounded", text
    if re.fullmatch(r"[0-9]+", normalized):
        return int(normalized), "exact", text
    return None, "unknown", text


@dataclass(slots=True)
class ParticipantRegistry:
    """按 UID 去重的参与用户登记表，保留来源关系证据。"""

    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    relations: list[dict[str, Any]] = field(default_factory=list)
    skipped_inner_authors: int = 0

    def register(
        self,
        *,
        uid: str,
        handle: str | None,
        display_name: str | None,
        topic: TopicInput,
        post_id: str | None,
        observed_at: str,
        via_repost: bool,
    ) -> bool:
        if _UID.fullmatch(uid) is None:
            raise TopicError("participant-uid-invalid")
        existing = self.users.get(uid)
        if existing is None:
            self.users[uid] = {
                "platform": "weibo",
                "type": "topic_participant",
                "uid": uid,
                "author_id": uid,
                "native_id": uid,
                "handle": handle,
                "display_name": display_name,
                "link": profile_url(uid),
                "topics": [topic.name],
                "topic_container_ids": [topic.container_id] if topic.container_id else [],
                "post_ids": [post_id] if post_id else [],
                "first_observed_at": observed_at,
                "last_observed_at": observed_at,
                "via_repost": bool(via_repost),
            }
            created = True
        else:
            created = False
            if topic.name not in existing["topics"]:
                existing["topics"].append(topic.name)
            if topic.container_id and topic.container_id not in existing["topic_container_ids"]:
                existing["topic_container_ids"].append(topic.container_id)
            if post_id and post_id not in existing["post_ids"]:
                existing["post_ids"].append(post_id)
            existing["last_observed_at"] = observed_at
            existing["via_repost"] = existing["via_repost"] or bool(via_repost)
            if display_name and not existing.get("display_name"):
                existing["display_name"] = display_name
            if handle and not existing.get("handle"):
                existing["handle"] = handle
        self.relations.append(
            {
                "platform": "weibo",
                "type": "topic_participant_relation",
                "topic": topic.name,
                "topic_kind": topic.kind,
                "topic_container_id": topic.container_id,
                "uid": uid,
                "post_id": post_id,
                "native_id": uid,
                "link": profile_url(uid),
                "observed_at": observed_at,
                "via_repost": bool(via_repost),
            }
        )
        return created


def normalize_topic_post(
    card: Mapping[str, Any],
    *,
    topic: TopicInput,
    observed_at: str,
    backend: str,
    evidence_level: str,
    source_url: str | None,
) -> dict[str, Any] | None:
    """把一张话题页卡片转成帖子记录。

    外层作者才是话题参与者。卡片里出现的引用/转发内层作者单独记录在
    ``inner_author_name``，不参与用户登记。
    """

    mid = card.get("mid")
    if not isinstance(mid, str) or _MID.fullmatch(mid) is None:
        return None
    uid = card.get("author_uid")
    if not isinstance(uid, str) or _UID.fullmatch(uid) is None:
        uid = uid_from_href(card.get("author_href"))
    domain = card.get("author_domain")
    domain = domain if isinstance(domain, str) and _SAFE_ID.fullmatch(domain) else "u"
    link = (
        f"https://weibo.com/detail/{mid}"
        if domain == "u"
        else f"https://weibo.com/{domain}/{mid}"
    )
    truncated = card.get("truncated") is True
    metrics = display_metric_fields(card)
    return {
        "platform": "weibo",
        "type": "topic_post",
        "mblog_id": mid,
        "id": mid,
        "native_id": mid,
        "topic": topic.name,
        "topic_kind": topic.kind,
        "topic_container_id": topic.container_id,
        "title": card.get("text"),
        "text": card.get("text"),
        "text_complete": not truncated,
        "link": link,
        "url": link,
        "date": card.get("date_text"),
        "published_at": card.get("date_text"),
        "observed_at": observed_at,
        "author": card.get("author_name"),
        "author_id": uid,
        "author_uid": uid,
        "handle": card.get("author_domain"),
        "liked": metrics["liked"]["value"],
        "comments": metrics["comments"]["value"],
        "shares": metrics["shares"]["value"],
        "collected": metrics["collected"]["value"],
        "metric_display": metrics,
        "source": card.get("source"),
        "inner_author_name": card.get("retweet_author_name"),
        "via_repost": bool(card.get("retweet_author_name")),
        "backend": backend,
        "evidence_level": evidence_level,
        "source_url": source_url,
        "field_quality": {"text": "truncated" if truncated else "exact"},
        "parser_version": PARSER_VERSION,
    }


def _metric_value(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    parsed, precision, _ = parse_display_metric(value)
    return parsed if precision != "unknown" else None


def normalize_profile(
    uid: str,
    observation: Mapping[str, Any],
    *,
    observed_at: str,
    backend: str,
    evidence_level: str,
    source_url: str | None,
    cached: bool = False,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """把主页观察到的一份可见资料转成用户主页记录。

    页面没有展示的字段留 ``null``。缩写数值保留原文与精度状态，不冒充精确值。
    不承诺每个帐号都有相同字段。
    """

    if _UID.fullmatch(uid) is None:
        raise TopicError("profile-uid-invalid")
    quality: dict[str, str] = {}
    record: dict[str, Any] = {
        "platform": "weibo",
        "type": "user_profile",
        "uid": uid,
        "author_id": uid,
        "native_id": uid,
        "link": profile_url(uid),
        "url": profile_url(uid),
        "display_name": _text(observation.get("display_name")),
        "handle": _text(observation.get("handle")),
        "avatar_url": _text(observation.get("avatar_url")),
        "bio": _text(observation.get("bio")),
        "verified": observation.get("verified") if isinstance(observation.get("verified"), bool) else None,
        "verify_text": _text(observation.get("verify_text")),
        "region": None,
        "website": None,
        "registered_at": None,
        "tags": [item for item in as_items(observation.get("tags")) if isinstance(item, str)][:16],
        "meta_items": [item for item in as_items(observation.get("meta_items")) if isinstance(item, str)][:16],
        "followers": None,
        "following": None,
        "posts": None,
        "followers_display": None,
        "following_display": None,
        "posts_display": None,
        "observed_at": observed_at,
        "profile_status": "complete" if failure_reason is None else "failed",
        "failure_reason": failure_reason,
        "cached": bool(cached),
        "backend": backend,
        "evidence_level": evidence_level,
        "source_url": source_url or profile_url(uid),
        "field_quality": quality,
        "parser_version": PARSER_VERSION,
    }
    for field_name, display_key in (
        ("followers", "followers_text"),
        ("following", "following_text"),
        ("posts", "posts_text"),
    ):
        parsed, precision, display = parse_display_metric(observation.get(field_name))
        if parsed is None:
            parsed, precision, display = parse_display_metric(observation.get(display_key))
        record[field_name] = parsed
        record[f"{field_name}_display"] = display
        quality[field_name] = precision
    for field_name in ("display_name", "bio", "avatar_url", "verified", "verify_text"):
        if record[field_name] is None:
            quality[field_name] = "unknown"
    meta = record["meta_items"]
    for entry in meta:
        if record["region"] is None and ("地区" in entry or "IP" in entry):
            record["region"] = entry.split("：", 1)[-1].split(":", 1)[-1].strip() or None
        if record["website"] is None and ("." in entry and ("http" in entry or "www" in entry)):
            record["website"] = entry
        if record["registered_at"] is None and ("注册" in entry or "加入" in entry):
            record["registered_at"] = entry.split("：", 1)[-1].split(":", 1)[-1].strip() or None
    return record


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


#: 主页阶段可能出现的固定失败原因。
PROFILE_FAILURE_REASONS: tuple[str, ...] = (
    "profile-unavailable",
    "profile-deleted",
    "profile-permission-denied",
    "profile-login-required",
    "profile-capture-timeout",
    "profile-risk-stopped",
)

#: 内部固定信号名；对外只暴露 PROFILE_FAILURE_REASONS 里的固定原因。
_SIGNAL_UNAVAILABLE = "unavailable"
_SIGNAL_DELETED = "deleted"
_SIGNAL_PERMISSION = "permission"
_SIGNAL_LOGIN = "login"
_SIGNAL_TIMEOUT = "timeout"
_SIGNAL_RISK = "risk"

FAILURE_BY_SIGNAL: dict[str, str] = {
    "unavailable": "profile-unavailable",
    "not-found": "profile-unavailable",
    "deleted": "profile-deleted",
    "permission": "profile-permission-denied",
    "login": "profile-login-required",
    "timeout": "profile-capture-timeout",
    "risk": "profile-risk-stopped",
}


def profile_failure_reason(signal: str) -> str:
    return FAILURE_BY_SIGNAL.get(signal, "profile-unavailable")


def ordering_key(uid: str) -> tuple[int, str]:
    """稳定顺序：先按数字 UID 排序，保证同一运行顺序可复现。"""

    return (int(uid) if _UID.fullmatch(uid) else 0, uid)


def normalize_topic_payload(
    payload: Mapping[str, Any],
    *,
    topic: TopicInput,
    observed_at: str,
    backend: str,
    evidence_level: str,
    source_url: str | None,
    registry: ParticipantRegistry,
) -> tuple[list[dict[str, Any]], str | None]:
    """解析一页话题观察结果，返回帖子记录与下一页链接。"""

    posts: list[dict[str, Any]] = []
    for raw in as_items(payload.get("posts")):
        card = as_mapping(raw)
        record = normalize_topic_post(
            card,
            topic=topic,
            observed_at=observed_at,
            backend=backend,
            evidence_level=evidence_level,
            source_url=source_url,
        )
        if record is None:
            continue
        uid = record.get("author_uid")
        if isinstance(uid, str):
            registry.register(
                uid=uid,
                handle=record.get("handle"),
                display_name=record.get("author"),
                topic=topic,
                post_id=record["mblog_id"],
                observed_at=observed_at,
                via_repost=bool(record.get("via_repost")),
            )
        elif record.get("inner_author_name"):
            # 只出现内层引用作者的卡片不计入参与者。
            registry.skipped_inner_authors += 1
        posts.append(record)
    next_url = payload.get("next_page_url")
    if not isinstance(next_url, str):
        next_url = None
    else:
        parsed = urlparse(next_url)
        if parsed.scheme != "https" or parsed.hostname != TOPIC_HOST or parsed.path != "/weibo" or parse_qs(parsed.query).get("q") != [f"#{topic.name}#"]:
            next_url = None
    return posts, next_url


def topic_target(value: str) -> Target:
    """把话题输入转成计划目标；超话返回明确的 unsupported 而不是伪装。"""

    parsed = parse_topic_input(value)
    return Target(
        platform="weibo",
        mode="topic",
        label=parsed.name,
        topic=parsed.name,
        topic_kind=parsed.kind,
    )


def supported_topic_kind(kind: str) -> bool:
    return kind == TOPIC_KIND_STANDARD


def observed_now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# 话题采集与主页阶段
# ---------------------------------------------------------------------------

#: 页面稳定等待与单次话题页读取上限。
TOPIC_SETTLE_MS = 900
CAPTURE_TIMEOUT_MS = 12_000


@dataclass(slots=True)
class TopicCollector:
    """微博话题任务：先读可见话题帖，再顺序采集参与用户的公开主页。

    同一运行内同一 UID 的主页只访问一次，多个话题/帖子关系分别保留。主页阶段
    失败时记录固定原因，已确认的用户条目与来源关系不会因为主页失败而丢失。
    只读取页面实际可见的字段，不递归抓取这些用户的全部微博、关注或粉丝关系。
    """

    request: Any
    browser: Any
    topic: TopicInput
    registry: ParticipantRegistry = field(default_factory=ParticipantRegistry)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    pages: int = 0

    @classmethod
    def build(cls, request: Any, browser: Any) -> "TopicCollector":
        value = getattr(request, "topic", None)
        if not isinstance(value, str) or not value.strip():
            raise TopicError("topic-input-empty")
        return cls(request=request, browser=browser, topic=parse_topic_input(value))

    @property
    def backend(self) -> str:
        return BACKEND_CDP

    @property
    def evidence_level(self) -> str:
        route = getattr(self.browser, "evidence_level", None)
        return route if isinstance(route, str) and route in {EVIDENCE_PAGE, EVIDENCE_RESPONSE} else EVIDENCE_RESPONSE

    async def collect(self) -> list[dict[str, Any]]:
        if not supported_topic_kind(self.topic.kind):
            # 超话需要另一套页面契约：明确拒绝，不把关键词搜索冒充超话采集。
            raise TopicError("topic-container-unsupported")
        posts = await self.collect_posts()
        records: list[dict[str, Any]] = list(posts)
        ordered = sorted(self.registry.users, key=ordering_key)
        records.extend(self.registry.users[uid] for uid in ordered)
        records.extend(self.registry.relations)
        for uid in ordered:
            if uid not in getattr(self.request, "known_user_ids", ()):
                records.append(await self.collect_profile(uid))
                _publish(self.browser, records)
        return records

    # -- 话题帖阶段 --------------------------------------------------------

    async def collect_posts(self) -> list[dict[str, Any]]:
        page = self.browser.require_page("weibo")
        target = self.topic.page_url
        if not getattr(self.browser, "allow_navigation", False):
            _require_open_topic_target(page, target)
        records: list[dict[str, Any]] = []
        seen: set[str] = set(getattr(self.request, "exclude_ids", ()) or ())
        observed_at = observed_now()
        url = target
        cap = int(getattr(self.request, "page_cap", 1) or 1)
        for page_number in range(cap):
            try:
                if getattr(self.browser, "allow_navigation", False):
                    response = await self.browser.navigate(page, url, allowed_hosts=(TOPIC_HOST,))
                    status = getattr(response, "status", None)
                    if isinstance(status, int) and not isinstance(status, bool):
                        if status in {403, 429}:
                            raise CollectionStopped(f"http-{status}")
                        if not 200 <= status < 300:
                            raise SourceResponseError(f"topic navigation returned http-{status}")
                    await _settle(page)
                else:
                    _require_open_topic_target(page, url)
                    await _settle(page)
            except TimeoutError:
                break
            await raise_for_page_risk(page)
            payload = await _read_topic_page(page)
            page_posts, next_url = normalize_topic_payload(
                payload,
                topic=self.topic,
                observed_at=observed_at,
                backend=self.backend,
                evidence_level=self.evidence_level,
                source_url=getattr(page, "url", None) or url,
                registry=ParticipantRegistry(),
            )
            self.pages += 1
            added = 0
            for record in page_posts:
                mid = record["mblog_id"]
                if mid in seen:
                    continue
                seen.add(mid)
                records.append(record)
                uid = record.get("author_uid")
                if isinstance(uid, str):
                    self.registry.register(uid=uid, handle=record.get("handle"), display_name=record.get("author"), topic=self.topic, post_id=mid, observed_at=observed_at, via_repost=bool(record.get("via_repost")))
                added += 1
                limit = getattr(self.request, "target_count", None)
                if isinstance(limit, int) and limit > 0 and len(records) >= limit:
                    break
            _publish(self.browser, records)
            limit = getattr(self.request, "target_count", None)
            if isinstance(limit, int) and limit > 0 and len(records) >= limit:
                break
            if next_url is None or added == 0:
                break
            url = next_url
        return records

    # -- 主页阶段 ----------------------------------------------------------

    async def collect_profile(self, uid: str) -> dict[str, Any]:
        existing = self.profiles.get(uid)
        if existing is not None:
            # 同一运行内同一用户主页只抓一次。
            return existing
        source_url = profile_url(uid)
        observation: Mapping[str, Any] = {}
        failure: str | None = None
        try:
            observation = await self.read_profile(uid, source_url)
        except CollectionStopped:
            raise
        except TimeoutError:
            failure = profile_failure_reason(_SIGNAL_TIMEOUT)
        except TopicError as error:
            failure = profile_failure_reason(str(error))
        except SourceResponseError:
            failure = profile_failure_reason(_SIGNAL_UNAVAILABLE)
        record = normalize_profile(
            uid,
            observation,
            observed_at=observed_now(),
            backend=self.backend,
            evidence_level=self.evidence_level,
            source_url=source_url,
            cached=False,
            failure_reason=failure,
        )
        self.profiles[uid] = record
        return record

    async def read_profile(self, uid: str, source_url: str) -> Mapping[str, Any]:
        from ..extraction import login_expression, weibo_profile_expression

        page = self.browser.require_page("weibo")
        if getattr(self.browser, "allow_navigation", False):
            try:
                response = await self.browser.navigate(page, source_url, allowed_hosts=WEIBO_HOSTS)
            except TimeoutError as error:
                raise TimeoutError("profile navigation timed out") from error
            status = getattr(response, "status", None)
            if isinstance(status, int) and not isinstance(status, bool):
                if status in {403, 429}:
                    raise CollectionStopped(f"http-{status}")
                if status == 404:
                    raise TopicError(_SIGNAL_UNAVAILABLE)
                if status not in range(200, 300):
                    raise SourceResponseError(f"profile returned http-{status}")
        else:
            _require_open_profile_target(page, source_url)
        await _settle(page)
        await raise_for_page_risk(page)
        observation = await _evaluate(page, login_expression())
        if isinstance(observation, Mapping) and observation.get("logged_out") is True:
            raise TopicError(_SIGNAL_LOGIN)
        value = await _evaluate(page, weibo_profile_expression())
        if not isinstance(value, Mapping) or not value:
            raise TopicError(_SIGNAL_UNAVAILABLE)
        return value


async def _evaluate(page: Any, expression: str) -> Any:
    evaluator = getattr(page, "evaluate", None)
    if not callable(evaluator):
        raise TopicError(_SIGNAL_UNAVAILABLE)
    return await evaluator(expression)


async def _settle(page: Any) -> None:
    waiter = getattr(page, "wait_for_timeout", None)
    if callable(waiter):
        await waiter(TOPIC_SETTLE_MS)


async def raise_for_page_risk(page: Any) -> None:
    from ..extraction import risk_expression

    value = await _evaluate(page, risk_expression())
    if isinstance(value, Mapping) and value.get("risk") is True:
        raise CollectionStopped("challenge")


def _publish(browser: Any, records: Sequence[Mapping[str, Any]]) -> None:
    publisher = getattr(browser, "publish_progress", None)
    if callable(publisher):
        publisher("weibo", [dict(record) for record in records])


async def _read_topic_page(page: Any) -> Mapping[str, Any]:
    from ..extraction import weibo_topic_expression

    value = await _evaluate(page, weibo_topic_expression())
    if not isinstance(value, Mapping):
        raise SourceResponseError("topic page observation returned no object")
    return value


def _require_open_topic_target(page: Any, target: str) -> None:
    actual, expected = urlparse(getattr(page, "url", "") or ""), urlparse(target)
    if actual.scheme != "https" or actual.hostname != TOPIC_HOST or actual.path != expected.path:
        raise TopicError(_SIGNAL_UNAVAILABLE)
    actual_query = parse_qs(actual.query, keep_blank_values=True)
    expected_query = parse_qs(expected.query, keep_blank_values=True)
    if actual_query.get("q") != expected_query.get("q"):
        raise TopicError(_SIGNAL_UNAVAILABLE)


def _require_open_profile_target(page: Any, target: str) -> None:
    actual, expected = urlparse(getattr(page, "url", "") or ""), urlparse(target)
    if actual.scheme != "https" or actual.hostname not in WEIBO_HOSTS:
        raise TopicError(_SIGNAL_UNAVAILABLE)
    if actual.path.rstrip("/") != expected.path.rstrip("/"):
        raise TopicError(_SIGNAL_UNAVAILABLE)


async def collect_topic(request: Any, browser: Any) -> list[dict[str, Any]]:
    return await TopicCollector.build(request, browser).collect()

