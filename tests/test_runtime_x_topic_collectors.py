"""X 与微博话题采集器：两条证据路线共用一个标准化流程。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import pytest

from media_missher_runtime.extraction import probe_kind
from media_missher_runtime.contracts import (
    BACKEND_CDP,
    EVIDENCE_PAGE,
    EVIDENCE_RESPONSE,
)
from media_missher_runtime.models import CollectionRequest
from media_missher_runtime.platforms import weibo_topic, x


# ---------------------------------------------------------------------------
# 通用 fake page / browser
# ---------------------------------------------------------------------------


@dataclass
class FakeResponse:
    url: str
    status: int = 200
    payload: Any = None

    async def json(self) -> Any:
        return self.payload


@dataclass
class FakePage:
    url: str
    evaluation: Any = None
    navigation: Any = None
    observe_responses: bool = True
    responses: list[FakeResponse] = field(default_factory=list)
    navigation_status: int = 200
    closed: bool = False

    def is_closed(self) -> bool:
        return self.closed

    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        if callable(self.evaluation):
            return self.evaluation(expression, arg)
        return self.evaluation

    class _Expectation:
        def __init__(self, page: "FakePage", predicate: Any) -> None:
            self.page = page
            self.predicate = predicate
            self.value: Any = None

        async def __aenter__(self) -> "FakePage._Expectation":
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    def expect_response(self, predicate: Any, timeout: int | None = None) -> Any:
        """Return the bounded capture context the collector awaits.

        ``expect_response = None`` on a subclass models a session that cannot
        observe response bodies at all (the BrowserSkill route).
        """

        page = self

        class _Context:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

            @property
            async def value(self) -> Any:
                for response in page.responses:
                    if predicate(response):
                        return response
                raise TimeoutError("no matching response")

        return _Context()


@dataclass
class FakeBrowser:
    page: FakePage
    allow_navigation: bool = True
    published: list[tuple[str, int]] = field(default_factory=list)

    def require_page(self, _platform: str) -> FakePage:
        return self.page

    def publish_progress(self, platform: str, records: list[dict[str, Any]]) -> None:
        self.published.append((platform, len(records)))

    async def navigate(self, page: FakePage, url: str, *, allowed_hosts: tuple[str, ...]) -> Any:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in set(allowed_hosts):
            raise AssertionError("navigation must stay on an allowlisted https host")
        page.url = url
        if callable(page.navigation):
            page.navigation(url)
        return FakeResponse(url=url, status=page.navigation_status, payload=None)


def _bind(page: FakePage, responses: list[FakeResponse]) -> None:
    page.responses = responses


def _page_without_responses(**kwargs: Any) -> Any:
    """A session that cannot observe the page's own responses.

    The collector chooses its evidence route from ``expect_response`` being
    callable, so this models the BrowserSkill backend exactly.
    """

    page = FakePage(**kwargs)
    page.expect_response = None  # type: ignore[assignment]
    return page


# ---------------------------------------------------------------------------
# X collector
# ---------------------------------------------------------------------------


def _x_search_request(**overrides: Any) -> CollectionRequest:
    base: dict[str, Any] = {
        "platform": "x",
        "count": 5,
        "keyword": "ai",
        "backend": BACKEND_CDP,
    }
    base.update(overrides)
    return CollectionRequest(**base)


_RESPONSE_URL = (
    'https://x.com/i/api/graphql/abc/SearchTimeline?variables={"rawQuery":"ai","product":"Latest","count":20}'
)


def _timeline_payload(tweet_id: str, handle: str = "alice") -> dict[str, Any]:
    return {
        "data": {
            "search_by_raw_query": {
                "result": {
                    "timeline": {
                        "instructions": [
                            {
                                "entries": [
                                    {
                                        "entryId": f"tweet-{tweet_id}",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "rest_id": tweet_id,
                                                        "core": {
                                                            "user_results": {
                                                                "result": {
                                                                    "rest_id": "2040009202018504704",
                                                                    "core": {
                                                                        "screen_name": handle,
                                                                        "name": "Alice",
                                                                    },
                                                                }
                                                            }
                                                        },
                                                        "legacy": {
                                                            "id_str": tweet_id,
                                                            "full_text": "hello",
                                                            "created_at": "Sun Aug 30 11:39:23 +0000 2026",
                                                            "favorite_count": 3,
                                                            "reply_count": 1,
                                                        },
                                                    },
                                                }
                                            },
                                        },
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }


def test_x_response_route_reads_only_the_bound_operation_and_query():
    page = FakePage(url="https://x.com/home")
    browser = FakeBrowser(page=page)
    other_query = FakeResponse(
        url='https://x.com/i/api/graphql/abc/SearchTimeline?variables={"rawQuery":"other"}',
        payload=_timeline_payload("1"),
    )
    home = FakeResponse(
        url='https://x.com/i/api/graphql/abc/HomeTimeline?variables={"rawQuery":"ai"}',
        payload=_timeline_payload("2"),
    )
    bound = FakeResponse(url=_RESPONSE_URL, payload=_timeline_payload("3"))

    def navigate(url: str) -> None:
        _bind(page, [other_query, home, bound])

    page.navigation = navigate
    collector = x.XCollector(_x_search_request(), browser)
    records = asyncio.run(collector.collect())

    assert [record["tweet_id"] for record in records] == ["3"]
    assert records[0]["backend"] == BACKEND_CDP
    assert records[0]["evidence_level"] == EVIDENCE_RESPONSE
    assert records[0]["text_complete"] is False


def test_x_page_route_is_used_when_responses_cannot_be_observed():
    page = _page_without_responses(
        url="https://x.com/alice",
        evaluation=lambda expression, _arg=None: (
            {
                "posts": [
                    {
                        "permalink": "https://x.com/alice/status/77",
                        "handle": "alice",
                        "author_name": "Alice",
                        "text": "visible",
                    }
                ]
            }
            if "data-testid" in expression
            else {"risk": False, "reason": None}
        ),
    )
    browser = FakeBrowser(page=page)
    request = _x_search_request(backend=BACKEND_CDP, uid=None, keyword="ai")
    collector = x.XCollector(request, browser)
    records = asyncio.run(collector.collect())

    assert [record["tweet_id"] for record in records] == ["77"]
    assert records[0]["backend"] == BACKEND_CDP
    assert records[0]["evidence_level"] == EVIDENCE_PAGE
    assert records[0]["author_id"] is None


def test_x_creator_collection_never_treats_another_author_as_the_target():
    page = _page_without_responses(
        url="https://x.com/alice",
        evaluation=lambda expression, _arg=None: (
            {
                "posts": [
                    {"permalink": "https://x.com/bob/status/1", "handle": "bob", "text": "nope"},
                    {"permalink": "https://x.com/alice/status/2", "handle": "alice", "text": "yes"},
                ]
            }
            if "data-testid" in expression
            else {"risk": False, "reason": None}
        ),
    )
    browser = FakeBrowser(page=page)
    request = CollectionRequest(
        platform="x", count=5, uid="alice", backend=BACKEND_CDP
    )
    records = asyncio.run(x.XCollector(request, browser).collect())
    assert [record["tweet_id"] for record in records] == ["2"]


def test_x_collector_stops_on_a_risk_probe_before_reading_the_list():
    page = _page_without_responses(
        url="https://x.com/alice",
        evaluation=lambda expression, _arg=None: (
            {"risk": True, "reason": "challenge-selector"} if "phrases" in expression else {}
        ),
    )
    browser = FakeBrowser(page=page)
    request = CollectionRequest(
        platform="x", count=5, uid="alice", backend=BACKEND_CDP
    )
    with pytest.raises(x.CollectionStopped):
        asyncio.run(x.XCollector(request, browser).collect())


def test_x_collector_requires_an_exact_open_page_without_navigation_authorization():
    page = _page_without_responses(
        url="https://x.com/someone-else",
        evaluation=lambda _expression, _arg=None: {"risk": False},
    )
    browser = FakeBrowser(page=page, allow_navigation=False)
    request = CollectionRequest(
        platform="x", count=5, uid="alice", backend=BACKEND_CDP
    )
    with pytest.raises(Exception) as error:
        asyncio.run(x.XCollector(request, browser).collect())
    assert "precondition" in type(error.value).__module__ or "matching" in str(error.value)


# ---------------------------------------------------------------------------
# 微博话题采集器
# ---------------------------------------------------------------------------

_TOPIC_PAGE = "https://s.weibo.com/weibo?q=%23%E6%97%85%E8%A1%8C%23"
_PROFILE_PAGE = "https://weibo.com/u/1001"


def _topic_request(**overrides: Any) -> CollectionRequest:
    base: dict[str, Any] = {
        "platform": "weibo",
        "count": 5,
        "topic": "旅行",
        "topic_kind": "topic",
        "backend": BACKEND_CDP,
    }
    base.update(overrides)
    return CollectionRequest(**base)


def _topic_observation(posts: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    return {"posts": posts, "next_page_url": next_url}


def _profile_observation() -> dict[str, Any]:
    return {
        "display_name": "某用户",
        "followers_text": "1.2万",
        "following_text": "34",
        "bio": "公开简介",
    }


def test_topic_collector_registers_outer_authors_and_visits_each_homepage_once():
    calls: list[str] = []
    observations = {
        _TOPIC_PAGE: _topic_observation(
            [
                {
                    "mid": "5001",
                    "text": "第一条",
                    "author_name": "外层甲",
                    "author_uid": "1001",
                    "author_href": _PROFILE_PAGE,
                },
                {
                    "mid": "5002",
                    "text": "第二条",
                    "author_name": "外层甲",
                    "author_uid": "1001",
                    "author_href": _PROFILE_PAGE,
                },
                {
                    "mid": "5003",
                    "text": "转发",
                    "author_name": "外层乙",
                    "author_uid": "1002",
                    "author_href": "https://weibo.com/u/1002",
                    "retweet_author_name": "原作者",
                },
            ]
        ),
        _PROFILE_PAGE: _profile_observation(),
        "https://weibo.com/u/1002": {**_profile_observation(), "display_name": "外层乙"},
    }

    class Page:
        def __init__(self) -> None:
            self.url = _TOPIC_PAGE

        def is_closed(self) -> bool:
            return False

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

        async def evaluate(self, expression: str, _arg: Any = None) -> Any:
            if "phrases" in expression:
                return {"risk": False, "reason": None}
            if "selectors" in expression:
                return {"logged_out": False, "reason": None}
            if "display_name" in expression:
                return observations.get(self.url, {})
            return observations.get(self.url, {"posts": [], "next_page_url": None})

    class Browser:
        def __init__(self) -> None:
            self.page = Page()
            self.allow_navigation = True
            self.published: list[tuple[str, int]] = []

        def require_page(self, _platform: str) -> Page:
            return self.page

        def publish_progress(self, platform: str, records: list[dict[str, Any]]) -> None:
            self.published.append((platform, len(records)))

        async def navigate(self, page: Page, url: str, *, allowed_hosts: tuple[str, ...]) -> Any:
            calls.append(url)
            page.url = url
            return FakeResponse(url=url, status=200)

    browser = Browser()
    records = asyncio.run(weibo_topic.TopicCollector.build(_topic_request(), browser).collect())

    posts = [record for record in records if record["type"] == "topic_post"]
    users = [record for record in records if record["type"] == "topic_participant"]
    profiles = [record for record in records if record["type"] == "user_profile"]

    assert [post["mblog_id"] for post in posts] == ["5001", "5002", "5003"]
    assert {user["uid"] for user in users} == {"1001", "1002"}
    assert users[0]["post_ids"] == ["5001", "5002"]
    assert [profile["uid"] for profile in profiles] == ["1001", "1002"]
    # 同一运行内同一用户主页只访问一次。
    assert calls.count(_PROFILE_PAGE) == 1
    assert profiles[0]["followers"] == 12000.0
    assert profiles[0]["field_quality"]["followers"] == "rounded"


@dataclass
class _ScriptedPage:
    """A page whose answer depends on which extractor is asking.

    The extractors are distinguished by a marker that appears only in that
    extractor's own options payload, so the fake cannot answer the risk probe and
    the field probe with the same object.
    """

    url: str
    topic_observation: Any = None
    profile_observation: Any = None
    logged_out: bool = False
    risk: bool = False
    navigations: list[str] = field(default_factory=list)

    def is_closed(self) -> bool:
        return False

    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    async def evaluate(self, expression: str, _arg: Any = None) -> Any:
        kind = probe_kind(expression)
        if kind == "risk":
            return {"risk": self.risk, "reason": "challenge-selector" if self.risk else None}
        if kind == "login":
            return {"logged_out": self.logged_out, "reason": "login-selector"}
        if kind == "weibo_profile":
            return self.profile_observation or {}
        if kind == "weibo_topic":
            return self.topic_observation or {"posts": [], "next_page_url": None}
        raise AssertionError(f"unexpected probe: {kind}")


@dataclass
class _ScriptedBrowser:
    page: _ScriptedPage
    allow_navigation: bool = True

    def require_page(self, _platform: str) -> _ScriptedPage:
        return self.page

    def publish_progress(self, _platform: str, _records: list[dict[str, Any]]) -> None:
        return None

    async def navigate(self, page: _ScriptedPage, url: str, *, allowed_hosts: tuple[str, ...]) -> Any:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in set(allowed_hosts):
            raise AssertionError("navigation must stay on an allowlisted https host")
        page.navigations.append(url)
        page.url = url
        return FakeResponse(url=url, status=200)


def test_topic_collector_records_a_fixed_reason_when_a_homepage_requires_login():
    page = _ScriptedPage(
        url=_TOPIC_PAGE,
        topic_observation=_topic_observation(
            [
                {
                    "mid": "5001",
                    "text": "第一条",
                    "author_name": "外层甲",
                    "author_uid": "1001",
                    "author_href": _PROFILE_PAGE,
                }
            ]
        ),
        logged_out=True,
    )
    records = asyncio.run(
        weibo_topic.TopicCollector.build(
            _topic_request(), _ScriptedBrowser(page=page)
        ).collect()
    )
    profiles = [record for record in records if record["type"] == "user_profile"]
    assert len(profiles) == 1
    assert profiles[0]["profile_status"] == "failed"
    assert profiles[0]["failure_reason"] == "profile-login-required"
    # 已确认的用户条目与来源关系不会因为主页失败而丢失。
    assert any(record["type"] == "topic_participant" for record in records)
    assert profiles[0]["uid"] == "1001"


def test_topic_collector_records_a_fixed_reason_for_an_unavailable_homepage():
    page = _ScriptedPage(
        url=_TOPIC_PAGE,
        topic_observation=_topic_observation(
            [
                {
                    "mid": "5001",
                    "text": "第一条",
                    "author_name": "外层甲",
                    "author_uid": "1001",
                    "author_href": _PROFILE_PAGE,
                }
            ]
        ),
        profile_observation={},
    )
    records = asyncio.run(
        weibo_topic.TopicCollector.build(
            _topic_request(), _ScriptedBrowser(page=page)
        ).collect()
    )
    profiles = [record for record in records if record["type"] == "user_profile"]
    assert profiles[0]["failure_reason"] == "profile-unavailable"
    assert profiles[0]["link"] == _PROFILE_PAGE


def test_topic_collector_stops_the_whole_task_on_a_page_risk_signal():
    page = _ScriptedPage(url=_TOPIC_PAGE, risk=True)
    with pytest.raises(weibo_topic.CollectionStopped):
        asyncio.run(
            weibo_topic.TopicCollector.build(
                _topic_request(), _ScriptedBrowser(page=page)
            ).collect()
        )


def test_topic_collector_refuses_a_super_topic_instead_of_searching_a_keyword():
    request = _topic_request(topic="https://weibo.com/p/100808abcdef", topic_kind="super")

    class Browser:
        allow_navigation = True

        def require_page(self, _platform: str) -> Any:
            raise AssertionError("a super topic must be refused before any page work")

    with pytest.raises(weibo_topic.TopicError) as error:
        asyncio.run(weibo_topic.TopicCollector.build(request, Browser()).collect())
    assert "topic-container-unsupported" in str(error.value)


def test_topic_collector_keeps_one_user_across_two_topics_with_separate_relations():
    registry = weibo_topic.ParticipantRegistry()
    first = weibo_topic.parse_topic_input("#旅行#")
    second = weibo_topic.parse_topic_input("#摄影#")
    for topic, mid in ((first, "6001"), (second, "6002")):
        posts, _next = weibo_topic.normalize_topic_payload(
            _topic_observation(
                [
                    {
                        "mid": mid,
                        "text": "post",
                        "author_name": "同一个人",
                        "author_uid": "1001",
                        "author_href": _PROFILE_PAGE,
                    }
                ]
            ),
            topic=topic,
            observed_at="2026-09-20T00:00:00+00:00",
            backend=BACKEND_CDP,
            evidence_level=EVIDENCE_RESPONSE,
            source_url=topic.page_url,
            registry=registry,
        )
        assert len(posts) == 1
    assert list(registry.users) == ["1001"]
    assert registry.users["1001"]["topics"] == ["旅行", "摄影"]
    assert len(registry.relations) == 2


def test_topic_collector_reports_pages_it_really_read():
    page = _ScriptedPage(
        url=_TOPIC_PAGE,
        topic_observation=_topic_observation(
            [
                {
                    "mid": "5001",
                    "text": "第一条",
                    "author_name": "外层甲",
                    "author_uid": "1001",
                    "author_href": _PROFILE_PAGE,
                }
            ]
        ),
        profile_observation=_profile_observation(),
    )
    collector = weibo_topic.TopicCollector.build(
        _topic_request(), _ScriptedBrowser(page=page)
    )
    asyncio.run(collector.collect())
    assert collector.pages == 1
    assert page.navigations.count(_PROFILE_PAGE) == 1


def test_topic_collector_does_not_treat_an_inner_quote_author_as_a_participant():
    registry = weibo_topic.ParticipantRegistry()
    topic = weibo_topic.parse_topic_input("#旅行#")
    weibo_topic.normalize_topic_payload(
        _topic_observation(
            [
                {
                    "mid": "5009",
                    "text": "只有引用作者",
                    "author_name": None,
                    "author_uid": None,
                    "retweet_author_name": "原作者",
                }
            ]
        ),
        topic=topic,
        observed_at="2026-09-20T00:00:00+00:00",
        backend=BACKEND_CDP,
        evidence_level=EVIDENCE_RESPONSE,
        source_url=topic.page_url,
        registry=registry,
    )
    assert registry.users == {}
    assert registry.skipped_inner_authors == 1


def test_topic_observation_mapping_is_exportable_as_plain_json():
    import json

    record = weibo_topic.normalize_profile(
        "1001",
        _profile_observation(),
        observed_at="2026-09-20T00:00:00+00:00",
        backend=BACKEND_CDP,
        evidence_level=EVIDENCE_RESPONSE,
        source_url=_PROFILE_PAGE,
    )
    json.dumps(record, ensure_ascii=False)
    assert isinstance(record, Mapping)


def test_topic_fixed_count_bounds_profile_visits_to_accepted_posts():
    page = _ScriptedPage(url=_TOPIC_PAGE, topic_observation=_topic_observation([
        {"mid": "5001", "text": "one", "author_uid": "1001", "author_href": "https://weibo.com/u/1001"},
        {"mid": "5002", "text": "two", "author_uid": "1002", "author_href": "https://weibo.com/u/1002"},
    ]), profile_observation={})
    from dataclasses import replace
    collector = weibo_topic.TopicCollector.build(replace(_topic_request(), count=1), _ScriptedBrowser(page=page))
    rows = asyncio.run(collector.collect())
    assert [row['mblog_id'] for row in rows if row['type'] == 'topic_post'] == ['5001']
    assert set(collector.profiles) == {'1001'}
