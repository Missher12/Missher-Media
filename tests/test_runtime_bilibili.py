from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Coroutine

import pytest

from runtime.media_missher_runtime.browser import PageJson, PreconditionError
from runtime.media_missher_runtime.models import CollectionRequest


def _run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fake coroutine unexpectedly suspended")


def _dynamic(
    native_id: str,
    *,
    bvid: str | None = None,
    title: str = "Synthetic title",
    description: str = "Synthetic description",
    published: int | None = 1_700_000_000,
    liked: int | None = 3,
    comments: int | None = 2,
    shares: int | None = 1,
    collected: int | None = 0,
) -> dict[str, Any]:
    dynamic: dict[str, Any] = {"desc": {"text": description}}
    if bvid is not None:
        dynamic["major"] = {"archive": {"bvid": bvid, "title": title, "desc": description}}
    return {
        "id_str": native_id,
        "type": "DYNAMIC_TYPE_AV" if bvid else "DYNAMIC_TYPE_WORD",
        "basic": {"jump_url": f"//www.bilibili.com/video/{bvid}" if bvid else f"//t.bilibili.com/{native_id}"},
        "modules": {
            "module_author": {"pub_ts": published},
            "module_dynamic": dynamic,
            "module_stat": {"like": liked, "reply": comments, "forward": shares, "favorite": collected},
        },
    }


def _creator_page(*items: dict[str, Any], has_more: bool, offset: str = "next") -> PageJson:
    return PageJson(200, {"code": 0, "data": {"has_more": has_more, "items": list(items), "offset": offset}})


@dataclass
class CreatorBrowser:
    responses: list[PageJson]
    urls: list[str] = field(default_factory=list)

    def require_page(self, platform: str) -> object:
        assert platform == "bilibili"
        return type("Page", (), {"url": "https://www.bilibili.com/feed"})()

    async def page_json(self, page: object, url: str) -> PageJson:
        self.urls.append(url)
        return self.responses.pop(0)


def test_creator_parses_archive_and_dynamic_records_without_inventing_unknowns() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    browser = CreatorBrowser([
        _creator_page(
            _dynamic("dyn-alpha", bvid="BVsynthetic1", collected=0),
            _dynamic("dyn-beta", bvid=None, liked=None, comments=0, shares=None, collected=None),
            has_more=False,
        )
    ])

    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=0, uid="synthetic-user"), browser))

    assert [(record["type"], record["dynamic_id"], record["bvid"]) for record in records] == [
        ("video", "dyn-alpha", "BVsynthetic1"),
        ("dynamic", "dyn-beta", None),
    ]
    assert records[0]["link"] == "https://www.bilibili.com/video/BVsynthetic1"
    assert records[1]["link"] == "https://t.bilibili.com/dyn-beta"
    assert records[1]["liked"] is None
    assert records[1]["comments"] == 0
    assert records[1]["shares"] is None
    assert records[1]["collected"] is None
    assert records[0]["date_precision"] == "second"


def test_creator_deduplicates_before_exact_count_and_does_not_fetch_extra_page() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    browser = CreatorBrowser([
        _creator_page(_dynamic("one"), _dynamic("two"), has_more=True, offset="offset-one"),
        _creator_page(_dynamic("two"), _dynamic("three"), has_more=True, offset="offset-two"),
        _creator_page(_dynamic("four"), has_more=False),
    ])

    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=3, uid="synthetic-user"), browser))

    assert [record["dynamic_id"] for record in records] == ["one", "two", "three"]
    assert len(browser.urls) == 2
    assert "offset=offset-one" in browser.urls[1]


def test_creator_count_zero_respects_page_cap_and_stops_on_unchanged_page() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    browser = CreatorBrowser([
        _creator_page(_dynamic("one"), has_more=True),
        _creator_page(_dynamic("one"), has_more=True),
        _creator_page(_dynamic("two"), has_more=True),
    ])

    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=0, page_cap=3, uid="synthetic-user"), browser))

    assert [record["dynamic_id"] for record in records] == ["one"]
    assert len(browser.urls) == 2


def test_creator_stops_when_source_is_exhausted() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    browser = CreatorBrowser([_creator_page(_dynamic("one"), has_more=False), _creator_page(_dynamic("two"), has_more=False)])

    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=9, uid="synthetic-user"), browser))

    assert [record["dynamic_id"] for record in records] == ["one"]
    assert len(browser.urls) == 1


def test_creator_stops_immediately_on_risk_response() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import CollectionStopped, collect_creator

    browser = CreatorBrowser([PageJson(200, {"code": 461}), _creator_page(_dynamic("never"), has_more=False)])

    with pytest.raises(CollectionStopped, match="payload-461"):
        _run(collect_creator(CollectionRequest(platform="bilibili", count=2, uid="synthetic-user"), browser))
    assert len(browser.urls) == 1


@dataclass
class SearchBrowser:
    payload: PageJson | None = None
    dom_records: list[dict[str, Any]] | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    bilibili_allowed_hosts = ("bilibili.com", "www.bilibili.com")

    async def search_bilibili(self, **kwargs: Any) -> PageJson | None:
        self.calls.append(kwargs)
        return self.payload

    async def search_bilibili_dom(self, **kwargs: Any) -> list[dict[str, Any]] | None:
        self.calls.append(kwargs)
        return self.dom_records


def test_search_parses_browser_generated_json_and_passes_explicit_navigation_guard() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    browser = SearchBrowser(PageJson(200, {"code": 0, "data": {"list": {"vlist": [{
        "bvid": "BVsearch01", "title": "<em>synthetic</em> title", "description": "description",
        "arcurl": "//www.bilibili.com/video/BVsearch01", "pubdate": 1_700_000_001,
        "like": 0, "review": 2,
    }]}, "page": {"numPages": 1}, "is_risk": False}}))

    records = _run(search(CollectionRequest(platform="bilibili", count=1, keyword="synthetic query"), browser))

    assert records == [{
        "platform": "bilibili", "type": "video", "bvid": "BVsearch01", "native_id": "BVsearch01",
        "title": "synthetic title", "desc": "description", "link": "https://www.bilibili.com/video/BVsearch01",
        "date": "2023-11-14T22:13:21+00:00", "liked": 0, "comments": 2, "shares": None,
        "collected": None, "search_keyword": "synthetic query",
    }]
    assert browser.calls == [{"keyword": "synthetic query", "allow_navigation": True, "allowed_hosts": ("bilibili.com", "www.bilibili.com")}]


def test_search_falls_back_to_semantic_dom_when_json_source_is_unavailable() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    browser = SearchBrowser(payload=None, dom_records=[{"bvid": "BVdom001", "title": "DOM result", "href": "/video/BVdom001", "like": None}])

    records = _run(search(CollectionRequest(platform="bilibili", count=1, keyword="synthetic"), browser))

    assert records[0]["bvid"] == "BVdom001"
    assert records[0]["link"] == "https://www.bilibili.com/video/BVdom001"
    assert records[0]["liked"] is None
    assert browser.calls[1]["allow_navigation"] is False


def test_search_rejects_non_allowlisted_navigation_source() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    class UnsafeSearchBrowser:
        async def search_bilibili(self, **kwargs: Any) -> PageJson:
            return PageJson(200, {"code": 0, "data": {"list": {"vlist": []}}})

    with pytest.raises(PreconditionError, match="allowlisted"):
        _run(search(CollectionRequest(platform="bilibili", count=1, keyword="synthetic"), UnsafeSearchBrowser()))


def test_search_complete_mode_is_prohibited() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    with pytest.raises(ValueError, match="complete"):
        _run(search(CollectionRequest(platform="bilibili", count=1, keyword="synthetic", complete=True), SearchBrowser()))


def test_search_uses_an_already_open_page_for_dom_fallback_without_navigation() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import search

    class OpenSearchPage:
        url = "https://www.bilibili.com/search"

        async def evaluate(self, script: str) -> list[dict[str, Any]]:
            assert "bili-video-card" in script
            return [{"bvid": "BVopen001", "title": "Open result", "href": "/video/BVopen001"}]

    class ExistingPageBrowser:
        def require_page(self, platform: str) -> OpenSearchPage:
            assert platform == "bilibili"
            return OpenSearchPage()

    records = _run(search(CollectionRequest(platform="bilibili", count=1, keyword="synthetic"), ExistingPageBrowser()))

    assert records[0]["bvid"] == "BVopen001"


@dataclass
class DetailBrowser(CreatorBrowser):
    details: dict[str, dict[str, Any]] = field(default_factory=dict)
    detail_calls: list[str] = field(default_factory=list)

    async def bilibili_detail(self, *, record: dict[str, Any], allow_navigation: bool, allowed_hosts: tuple[str, ...]) -> dict[str, Any] | None:
        self.detail_calls.append(record["dynamic_id"])
        assert allow_navigation is True
        assert allowed_hosts == ("bilibili.com", "www.bilibili.com")
        return self.details.get(record["dynamic_id"])


def test_complete_uses_sequential_detail_data_only_when_all_required_fields_exist() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    browser = DetailBrowser(
        [_creator_page(_dynamic("one", bvid="BVdetail1", title="-", published=None, liked=None, comments=None, shares=None, collected=None), has_more=False)],
        details={"one": {"title": "Detailed title", "date": 1_700_000_002, "liked": 4, "comments": 0, "shares": 1, "collected": 2}},
    )

    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user", complete=True), browser))

    assert browser.detail_calls == ["one"]
    assert records[0]["complete"] is True
    assert records[0]["missing_fields"] == []
    assert records[0]["title"] == "Detailed title"
    assert records[0]["comments"] == 0


def test_complete_preserves_incomplete_record_with_exact_missing_fields() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    browser = DetailBrowser([_creator_page(_dynamic("one", bvid="BVmissing1", title="--", published=None, liked=None, comments=None, shares=None, collected=None), has_more=False)])

    records = _run(collect_creator(CollectionRequest(platform="bilibili", count=1, uid="synthetic-user", complete=True), browser))

    assert records[0]["complete"] is False
    assert records[0]["missing_fields"] == ["title", "date", "detail", "liked", "comments", "shares", "collected"]
