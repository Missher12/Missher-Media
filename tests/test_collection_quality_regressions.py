"""Synthetic regressions for collection correctness and avoiding duplicate visits."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from runtime.media_missher_runtime.browser import PreconditionError
from runtime.media_missher_runtime.extraction import DISPLAY_COUNT_JS, display_count, probe_kind, risk_expression
from runtime.media_missher_runtime.models import CollectionRequest
from runtime.media_missher_runtime.platforms import bilibili, douyin, weibo


class SearchPage:
    def __init__(self, batches, *, keyword="term"):
        self.url = "https://search.bilibili.com/all?" + urlencode({"keyword": keyword})
        self.batches = batches
        self.position = 0
        self.wait_snapshots = []
        self.scrolls = 0

    async def evaluate(self, script, arg=None):
        if "bili-video-card" in script:
            return {"cards": self.batches[self.position], "risk_text": ""}
        if "window.scrollTo" in script:
            self.scrolls += 1
        return {"risk_text": ""}

    async def wait_for_function(self, script, *, arg, timeout):
        self.wait_snapshots.append(arg)
        if self.position + 1 < len(self.batches):
            self.position += 1
        else:
            raise bilibili.PlaywrightTimeoutError("fixture has not advanced")


class SearchBrowser:
    allow_navigation = True

    def __init__(self, page):
        self.page = page
        self.navigations = []

    def require_page(self, platform):
        return self.page

    async def navigate(self, page, url, **kwargs):
        self.navigations.append(url)
        page.url = url


def card(identifier):
    return {"bvid": identifier, "title": identifier, "href": "/video/" + identifier}


def test_bilibili_incremental_search_advances_past_excluded_page_without_reload():
    page = SearchPage([[card("BVold")], [card("BVnew")]])
    browser = SearchBrowser(page)
    result = asyncio.run(bilibili.search(CollectionRequest(
        platform="bilibili", keyword="term", count=1, page_cap=3,
        continue_page=True, exclude_ids=("BVold", "BVhistoric"),
    ), browser))
    assert [record["native_id"] for record in result] == ["BVnew"]
    assert browser.navigations == []
    assert page.scrolls == 1
    assert page.wait_snapshots == [["BVold"]]


def test_bilibili_exact_batch_count_does_not_hide_verified_search_end():
    class EndPage(SearchPage):
        async def evaluate(self, script, arg=None):
            result = await super().evaluate(script, arg)
            if isinstance(result, dict) and "cards" in result:
                result["ended"] = True
            return result

    browser = SearchBrowser(EndPage([[card("BVlast")]]))
    browser.last_exhausted = False
    rows = asyncio.run(bilibili.search(CollectionRequest(platform="bilibili", keyword="term", count=1, continue_page=True), browser))
    assert len(rows) == 1 and browser.last_exhausted is True
    assert browser.page.scrolls == 0


@pytest.mark.parametrize("url", [
    "https://search.bilibili.com/all?keyword=other",
    "https://search.bilibili.com/all",
    "https://search.bilibili.com/all?keyword=term&keyword=other",
    "https://search.bilibili.com.evil.invalid/all?keyword=term",
    "https://user@search.bilibili.com/all?keyword=term",
])
def test_bilibili_passive_or_continuation_requires_exact_search(url):
    page = SearchPage([[card("BVwrong")]])
    page.url = url
    browser = SearchBrowser(page)
    with pytest.raises(PreconditionError, match="matching Bilibili"):
        asyncio.run(bilibili.search(CollectionRequest(platform="bilibili", keyword="term", count=1, continue_page=True), browser))
    assert not browser.navigations and not page.scrolls


@pytest.mark.parametrize("query,accepted", [
    ("keyword=term", True),
    ("keyword=other", False),
    ("", False),
    ("keyword=term&keyword=other", False),
    ("keyword=term&q=other", False),
    ("keyword=term&tracking=ignored", True),
])
def test_douyin_search_response_is_bound_to_exact_keyword(query, accepted):
    response = SimpleNamespace(url="https://www.douyin.com/aweme/v1/web/general/search/single/?" + query)
    assert douyin._is_search_response(response, "term") is accepted


def test_douyin_search_all_mix_items_are_available_before_id_dedup_and_count():
    payload = {"data": [
        {"aweme_mix_info": {"mix_items": [None, {"aweme_id": "one"}, {"aweme_id": "two"}]}},
        {"aweme_info": {"aweme_id": "one"}},
        {"aweme_info": {"aweme_id": "three"}},
    ], "has_more": 0, "cursor": 0}
    items, has_more, _ = douyin._page_items(payload, "search")
    rows = []
    douyin._append_records(rows, set(), items, keyword="term", cursor=0, target=2)
    assert [row["native_id"] for row in rows] == ["one", "two"]
    assert has_more is False


@pytest.mark.parametrize("raw,expected,precision", [
    ("0", 0, "exact"), ("1,234", 1234, "exact"), ("1.2万", 12000, "approximate"),
    ("点赞 1.2万", 12000, "approximate"), ("2亿", 200000000, "approximate"),
    ("2.5K", 2500, "approximate"), ("1M", 1000000, "approximate"),
    ("100+", 100, "approximate"), ("赞", None, "missing"),
    (None, None, "missing"), (True, None, "missing"), ("-1", None, "missing"),
    ("1.2.3", None, "missing"), ("1元", None, "missing"),
    ("2.5K Followers", 2500, "approximate"), ("7 replies. Reply", 7, "exact"),
    ("5 Likes. Unlike", 5, "exact"), ("12 Following", 12, "exact"),
])
def test_display_counts_preserve_units_and_precision(raw, expected, precision):
    parsed = display_count(raw)
    assert parsed["value"] == expected
    assert parsed["precision"] == precision
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required to compare actual DOM parser")
    script = DISPLAY_COUNT_JS + "process.stdout.write(JSON.stringify(mmDisplayCount(" + json.dumps(raw) + ")));"
    observed = json.loads(subprocess.check_output([node, "-e", script], text=True))
    assert observed == parsed


def test_weibo_search_preserves_original_metric_display_without_fabricating_zero():
    row = weibo.parse_search_item({"mid": "123", "liked": 12000, "comments": None,
                                  "metric_display": {"liked": {"raw": "1.2万"}}}, "term")
    assert row["liked"] == 12000 and row["comments"] is None
    assert row["metric_display"]["liked"] == {"raw": "1.2万", "value": 12000, "precision": "approximate"}


def test_weibo_missing_raw_display_keeps_valid_numeric_fallback():
    row = weibo.parse_search_item({"mid": "123", "liked": 0,
                                  "metric_display": {"liked": {"raw": None}}}, "term")
    assert row["liked"] == 0
    assert row["metric_display"]["liked"]["precision"] == "exact"


def test_weibo_topic_preserves_metric_precision():
    from runtime.media_missher_runtime.platforms.weibo_topic import TopicInput, normalize_topic_post

    row = normalize_topic_post({"mid": "123", "text": "post", "liked": 12000,
                                "metric_display": {"liked": {"raw": "1.2万"}}},
                               topic=TopicInput(name="term", kind="standard", page_url="https://s.weibo.com/weibo?q=term"),
                               observed_at="2026-10-03T00:00:00Z", backend="cdp",
                               evidence_level="page", source_url="https://s.weibo.com/weibo?q=term")
    assert row["liked"] == 12000
    assert row["metric_display"]["liked"]["precision"] == "approximate"


@pytest.mark.parametrize("hidden,width,expected", [(True, 10, False), (False, 0, False), (False, 10, True)])
def test_bilibili_end_requires_visible_marker_in_reader_and_wait(hidden, width, expected):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for actual extractor JavaScript")

    class ScriptPage:
        reader = ""
        waiter = ""

        async def evaluate(self, script):
            self.reader = script
            return {"cards": [], "risk_text": ""}

        async def wait_for_function(self, script, **kwargs):
            self.waiter = script

    page = ScriptPage()
    asyncio.run(bilibili._read_search_cards(page))
    asyncio.run(bilibili._wait_for_search_change(page, []))
    fixture = """
        const end = {isConnected:true, hidden:HIDDEN, parentElement:null,
          getAttribute:()=>null, getBoundingClientRect:()=>({width:WIDTH,height:10})};
        const document = {location:{pathname:'/all'},
          querySelectorAll:(selector)=>selector.startsWith('.search-end,')?[end]:[],
          querySelector:()=>null};
        const window = {getComputedStyle:()=>({display:'block',visibility:'visible',opacity:'1'})};
    """.replace("HIDDEN", json.dumps(hidden)).replace("WIDTH", str(width))
    script = fixture + "process.stdout.write(JSON.stringify({read:(" + page.reader + ")().ended,wait:(" + page.waiter + ")([])}));"
    result = json.loads(subprocess.check_output([node, "-e", script], text=True))
    assert result == {"read": expected, "wait": expected}


@pytest.mark.parametrize("payload", [
    {"code": -500, "message": "internal error"},
    {"code": 0, "data": {"items": {}, "has_more": False}},
    {"code": 0, "data": {"items": []}},
])
def test_bilibili_source_error_or_unknown_shape_is_not_empty_success(payload):
    with pytest.raises(bilibili.SourceResponseError):
        bilibili._feed_data(payload)


@pytest.mark.parametrize("payload,source", [
    ({"status_code": 0, "aweme_list": {}, "has_more": 0}, "creator"),
    ({"status_code": 0, "aweme_list": []}, "creator"),
    ({"status_code": 0, "data": None, "has_more": 0}, "search"),
])
def test_douyin_source_shape_failure_is_not_empty_success(payload, source):
    with pytest.raises(douyin.SourceResponseError, match="schema changed"):
        douyin._page_items(payload, source)


def test_explicit_empty_last_pages_are_valid():
    assert bilibili._feed_data({"code": 0, "data": {"items": [], "has_more": False}})["items"] == []
    assert douyin._page_items({"aweme_list": [], "has_more": 0}, "creator") == ([], False, None)


def test_bilibili_preserves_dynamic_and_video_counts_in_separate_domains():
    record = bilibili.parse_creator_item({"id_str": "dynamic123", "modules": {
        "module_dynamic": {"major": {"archive": {"bvid": "BVvideo123", "stat": {"like": 100, "reply": 0}}}},
        "module_stat": {"like": {"count": 7}, "comment": {"count": 3}, "forward": {"count": 2}},
    }}, observed_at="2026-10-03T00:00:00+00:00")
    bilibili._merge_video_detail(record, {"bvid": "BVvideo123", "title": "Video", "desc": "",
                                         "pubdate": 1700000000, "stat": {"favorite": 5}})
    assert (record["liked"], record["comments"], record["shares"], record["collected"]) == (100, 0, None, 5)
    assert record["engagement_scope"] == "video"
    observations = record["engagement_observations"]
    assert observations["dynamic"]["entity_id"] == "dynamic123"
    assert observations["dynamic"]["values"]["shares"] == 2
    assert observations["video"]["entity_id"] == "BVvideo123"
    assert observations["video"]["field_sources"]["liked"] == "list_api"
    assert observations["video"]["field_observed_at"]["liked"] == "2026-10-03T00:00:00+00:00"
    assert observations["video"]["field_sources"]["collected"] == "detail_api"


def test_shared_risk_probe_keeps_discovery_marker():
    assert probe_kind(risk_expression()) == "risk"


def test_weibo_missing_cursor_is_not_a_verified_empty_end():
    with pytest.raises(weibo.SourceResponseError, match="schema changed"):
        weibo._creator_data({"ok": 1, "data": {"list": []}})


def test_bilibili_detail_mismatch_never_changes_existing_record():
    record = {"bvid": "BVone", "liked": 7}
    with pytest.raises(PreconditionError, match="identifier mismatch"):
        bilibili._merge_video_detail(record, {"bvid": "BVtwo", "stat": {"like": 99}})
    assert record == {"bvid": "BVone", "liked": 7}


def test_weibo_actual_dom_parser_and_python_normalizer_keep_display_units():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for actual extractor JavaScript")

    class MetricPage:
        async def evaluate(self, script, *args):
            if args:
                return {"risk_text": ""}
            fixture = """
                const card={getAttribute:()=> '12345', querySelector:(selector)=>
                    selector.startsWith('[action-type=')?{textContent:'1.2万'}:null};
                const document={querySelectorAll:()=>[card],querySelector:()=>null};
            """
            result = subprocess.check_output([node, "-e", fixture + "process.stdout.write(JSON.stringify((" + script + ")()));"], text=True)
            return json.loads(result)

    observed = asyncio.run(weibo._read_search_cards(MetricPage()))
    row = weibo.parse_search_item(observed["cards"][0], "term")
    assert row["liked"] == 12000
    assert row["metric_display"]["liked"] == {"raw": "1.2万", "value": 12000, "precision": "approximate"}
