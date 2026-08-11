from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


def test_creator_parser_supports_observed_nested_metrics_and_preserves_zero_and_null() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "synthetic-dynamic",
        "modules": {
            "module_author": {"name": "Synthetic author", "pub_ts": 1_700_000_000},
            "module_dynamic": {"major": {"archive": {"bvid": "BVsynthetic", "title": "Title", "desc": "Desc"}}},
            "module_stat": {"comment": {"count": 0}, "forward": {"count": None}, "like": {"count": 2}, "favorite": {"count": 0}},
        },
    }, observed_at="2026-01-01T00:00:00+00:00")

    assert record["comments"] == 0
    assert record["shares"] is None
    assert record["liked"] == 2
    assert record["collected"] == 0
    assert record["native_id"] == "synthetic-dynamic"
    assert record["url"] == record["link"]
    assert record["author"] == "Synthetic author"
    assert record["quality_score"] == 3


def test_creator_parser_falls_back_to_archive_stat_and_dynamic_link() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "synthetic-dynamic",
        "modules": {
            "module_author": {},
            "module_dynamic": {"desc": {"text": "Dynamic text"}, "major": {"archive": {"stat": {"like": 1, "reply": 2, "share": 3, "favorite": 4}}}},
            "module_stat": {},
        },
    })

    assert record["type"] == "dynamic"
    assert record["link"] == "https://t.bilibili.com/synthetic-dynamic"
    assert (record["liked"], record["comments"], record["shares"], record["collected"]) == (1, 2, 3, 4)


@pytest.mark.parametrize(
    ("native_type", "major"),
    (
        ("DYNAMIC_TYPE_WORD", {}),
        ("DYNAMIC_TYPE_DRAW", {"draw": {"items": [{"src": "https://cdn.example.invalid/image.png"}]}}),
    ),
)
def test_creator_parser_preserves_pure_text_and_image_dynamics_without_bvid(
    native_type: str,
    major: dict[str, object],
) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "123456",
        "type": native_type,
        "modules": {
            "module_author": {"name": "Synthetic author", "pub_ts": 1_700_000_000},
            "module_dynamic": {"desc": {"text": "Synthetic dynamic"}, "major": major},
            "module_stat": {},
        },
    })

    assert record["type"] == "dynamic"
    assert record["dynamic_id"] == "123456"
    assert record["bvid"] is None
    assert record["native_id"] == "123456"


def test_search_parser_keeps_legacy_fields_and_uniform_aliases() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_search_item

    record = parse_search_item({"bvid": "BVsearch", "title": "<em>Title</em>", "description": "Desc", "like": 0, "review": 1}, "term", observed_at="2026-01-01T00:00:00+00:00")

    assert record["title"] == "Title"
    assert record["liked"] == 0
    assert record["native_id"] == record["id"] == "BVsearch"
    assert record["url"] == record["link"] == "https://www.bilibili.com/video/BVsearch"
    assert record["detail_completed"] is False
    assert record["search_keyword"] == "term"


def test_search_parser_restores_only_visible_business_fields() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_search_item

    record = parse_search_item({
        "bvid": "BVvisible",
        "title": "<em>Visible title</em>",
        "description": "Visible description",
        "play": "1.2万",
        "duration": "03:21",
        "tag": "动画,知识",
        "author": "Visible author",
        "date": "2026-08-03",
        "mid": "must-not-leak",
        "tracking_id": "must-not-leak",
        "raw_payload": {"cookie": "must-not-leak"},
    }, "term", observed_at="2026-01-01T00:00:00+00:00")

    assert record["play"] == 12_000
    assert record["duration"] == "03:21"
    assert record["tag"] == "动画,知识"
    assert record["description"] == record["desc"] == "Visible description"
    assert record["author"] == "Visible author"
    assert record["date"] == record["published_at"] == "2026-08-03"
    assert record["publish_time"] == int(
        datetime(2026, 8, 3, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000
    )
    assert record["publish_date"] == "2026-08-03"
    assert record["date_source"] == "search_dom"
    assert record["date_precision"] == "day"
    serialized = json.dumps(record, ensure_ascii=False)
    assert all(secret not in serialized for secret in ("must-not-leak", "tracking_id", "raw_payload"))


def test_search_parser_preserves_numeric_pubdate_with_safe_publish_aliases() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_search_item

    published_seconds = 1_700_000_000
    record = parse_search_item({
        "bvid": "BVpubdate",
        "title": "Title",
        "pubdate": published_seconds,
        "date": "must-not-override-source-time",
    }, "term")

    assert record["date"] == datetime.fromtimestamp(
        published_seconds, ZoneInfo("UTC")
    ).isoformat()
    assert record["publish_time"] == published_seconds * 1000
    assert record["publish_date"] == datetime.fromtimestamp(
        published_seconds, ZoneInfo("Asia/Shanghai")
    ).strftime("%Y-%m-%d")
    assert record["date_source"] == "api_pubdate"
    assert record["date_precision"] == "second"


@pytest.mark.parametrize(
    ("major_key", "block", "expected_title", "expected_desc"),
    (
        ("archive", {"bvid": "BVrich", "title": "Archive title", "desc": "Archive desc"}, "Archive title", "Archive desc"),
        ("opus", {"title": "Opus title", "summary": {"text": "Opus desc"}}, "Opus title", "Opus desc"),
        ("common", {"title": "Common title", "desc": "Common desc"}, "Common title", "Common desc"),
        ("pgc", {"title": "PGC title", "desc": "PGC desc"}, "PGC title", "PGC desc"),
        ("article", {"title": "Article title", "desc": "Article desc"}, "Article title", "Article desc"),
        ("music", {"title": "Music title", "desc": "Music desc"}, "Music title", "Music desc"),
        ("courses", {"title": "Course title", "desc": "Course desc"}, "Course title", "Course desc"),
        ("medialist", {"title": "List title", "desc": "List desc"}, "List title", "List desc"),
    ),
)
def test_creator_parser_extracts_rich_major_content(
    major_key: str,
    block: dict[str, object],
    expected_title: str,
    expected_desc: str,
) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": f"dynamic-{major_key}",
        "type": f"DYNAMIC_TYPE_{major_key.upper()}",
        "modules": {
            "module_author": {"name": "Synthetic author", "pub_ts": 1_700_000_000},
            "module_dynamic": {"major": {major_key: block}},
            "module_stat": {},
        },
    })

    assert record["title"] == expected_title
    assert record["desc"] == expected_desc
    assert record["native_type"] == f"DYNAMIC_TYPE_{major_key.upper()}"
    assert record["title_source"] == f"api-major-{major_key}-title"
    expected_content_source = f"api-major-{major_key}-{'summary' if major_key == 'opus' else 'desc'}"
    assert record["content_source"] == expected_content_source
    assert record["title_status"] == "source"


def test_creator_parser_extracts_live_recommendation_content() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "dynamic-live",
        "type": "DYNAMIC_TYPE_LIVE_RCMD",
        "modules": {
            "module_author": {"name": "Synthetic author"},
            "module_dynamic": {
                "major": {
                    "live_rcmd": {
                        "content": '{"live_play_info":{"title":"Live title"}}'
                    }
                }
            },
            "module_stat": {},
        },
    })

    assert record["title"] == "Live title"
    assert record["title_source"] == "api-major-live_rcmd-title"
    assert record["content_source"] is None
    assert record["native_type"] == "DYNAMIC_TYPE_LIVE_RCMD"


def test_creator_parser_preserves_draw_media_publish_aliases_and_safe_profile_media() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    published_seconds = 1_700_000_000
    record = parse_creator_item({
        "id_str": "dynamic-draw",
        "type": "DYNAMIC_TYPE_DRAW",
        "modules": {
            "module_author": {
                "name": "Synthetic author",
                "mid": "must-not-leak",
                "face": (
                    "https://cdn.example.invalid/avatar.jpg?size=96"
                    "&expires=1785686400&expiry=1785686401&token=must-not-leak#fragment"
                ),
                "pub_ts": published_seconds,
            },
            "module_dynamic": {
                "desc": {"rich_text_nodes": [{"text": "Draw "}, {"text": "description"}]},
                "major": {
                    "draw": {
                        "items": [
                            {
                                "src": (
                                    "https://cdn.example.invalid/first.jpg?width=720"
                                    "&expires=1785686400&expiry=1785686401&cookie=must-not-leak"
                                )
                            },
                            {"src": "https://cdn.example.invalid/second.jpg"},
                        ]
                    }
                },
            },
            "module_stat": {"comment": {"count": None}, "like": {"count": 0}},
        },
        "raw_payload": "must-not-leak",
    })

    assert record["title"] == "Draw description"
    assert record["desc"] == "Draw description"
    assert record["native_type"] == "DYNAMIC_TYPE_DRAW"
    assert record["image_count"] == 2
    assert record["cover"] == "https://cdn.example.invalid/first.jpg?width=720"
    assert record["author_avatar"] == "https://cdn.example.invalid/avatar.jpg?size=96"
    assert "expires=" not in json.dumps(record)
    assert "expiry=" not in json.dumps(record)
    assert record["publish_time"] == published_seconds * 1000
    assert record["publish_date"] == datetime.fromtimestamp(
        published_seconds, ZoneInfo("Asia/Shanghai")
    ).strftime("%Y-%m-%d")
    assert record["date_source"] == "api_pub_ts"
    assert record["title_source"] == "api-module-dynamic-desc"
    assert record["content_source"] == "api-module-dynamic-desc"
    assert record["detail_attempted"] is False
    assert record["detail_source"] == "list_api"
    assert record["comments"] is None
    assert record["liked"] == 0
    assert {"author_id", "author_link", "raw_payload", "token", "cookie"}.isdisjoint(record)


def test_creator_parser_combines_forward_comment_with_origin_content() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "dynamic-forward",
        "type": "DYNAMIC_TYPE_FORWARD",
        "modules": {
            "module_dynamic": {"desc": {"text": "Forward comment"}},
            "module_author": {"name": "Forwarder"},
            "module_stat": {},
        },
        "orig": {
            "type": "DYNAMIC_TYPE_ARTICLE",
            "modules": {
                "module_author": {"name": "Origin author", "mid": "must-not-leak"},
                "module_dynamic": {
                    "major": {"article": {"title": "Origin title", "desc": "Origin description"}}
                },
            },
        },
    })

    assert record["title"] == "Forward comment"
    assert record["desc"] == "Forward comment\n转发Origin author：Origin description"
    assert record["title_source"] == "api-forward-comment"
    assert record["content_source"] == "api-forward-comment+origin"
    assert record["native_type"] == "DYNAMIC_TYPE_FORWARD"


def test_creator_parser_rejects_malformed_media_urls_without_losing_the_record() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "dynamic-malformed-media",
        "type": "DYNAMIC_TYPE_AV",
        "modules": {
            "module_author": {"name": "Synthetic author", "face": "https://[invalid"},
            "module_dynamic": {
                "major": {
                    "archive": {
                        "bvid": "BVmalformed",
                        "title": "Still valid content",
                        "cover": "https://[invalid",
                    }
                }
            },
            "module_stat": {},
        },
    })

    assert record["native_id"] == "dynamic-malformed-media"
    assert record["title"] == "Still valid content"
    assert record["cover"] is None
    assert record["author_avatar"] is None


@pytest.mark.parametrize(
    "value",
    (None, True, -1, 0, float("inf"), float("nan"), 10**20, 10**1000),
)
def test_creator_parser_does_not_fail_or_fabricate_invalid_publish_time(
    value: object,
) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "dynamic-invalid-time",
        "modules": {
            "module_author": {"name": "Synthetic author", "pub_ts": value},
            "module_dynamic": {"desc": {"text": "Valid content"}},
            "module_stat": {},
        },
    })

    assert record["title"] == "Valid content"
    assert record["date"] is None
    assert record["published_at"] is None
    assert record["publish_time"] is None
    assert record["publish_date"] is None
    assert record["date_source"] is None
    assert record["date_precision"] is None


def test_creator_parser_bounds_legacy_title_and_description_lengths() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    long_description = "A" * 50_000
    record = parse_creator_item({
        "id_str": "dynamic-long-content",
        "modules": {
            "module_author": {"name": "Synthetic author"},
            "module_dynamic": {"desc": {"text": long_description}},
            "module_stat": {},
        },
    })

    assert record["title"] == "A" * 100
    assert record["desc"] == "A" * 20_000


def test_creator_parser_bounds_combined_forward_description() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "dynamic-long-forward",
        "type": "DYNAMIC_TYPE_FORWARD",
        "modules": {
            "module_author": {"name": "Synthetic author"},
            "module_dynamic": {"desc": {"text": "C" * 15_000}},
            "module_stat": {},
        },
        "orig": {
            "type": "DYNAMIC_TYPE_WORD",
            "modules": {
                "module_author": {"name": "Origin author"},
                "module_dynamic": {"desc": {"text": "O" * 15_000}},
            },
        },
    })

    assert len(record["title"]) == 100
    assert len(record["desc"]) == 20_000
    assert record["desc"].startswith("C" * 100)


@pytest.mark.parametrize(
    ("display", "expected_date", "expected_precision"),
    (
        ("2026年7月24日 17:52", "2026-07-24", "minute"),
        ("2026年7月24日", "2026-07-24", "day"),
    ),
)
def test_creator_parser_recovers_publish_time_from_full_display_date(
    display: str,
    expected_date: str,
    expected_precision: str,
) -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_creator_item

    record = parse_creator_item({
        "id_str": "dynamic-display-time",
        "modules": {
            "module_author": {"name": "Synthetic author", "pub_time": display},
            "module_dynamic": {"desc": {"text": "Valid content"}},
            "module_stat": {},
        },
    })

    assert record["date"] == display
    assert record["published_at"] == display
    assert record["publish_date"] == expected_date
    assert record["publish_time"] is not None
    assert record["date_source"] == "display_parse"
    assert record["date_precision"] == expected_precision


def test_display_publish_time_parser_handles_relative_and_cross_year_values() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import _normalize_publish_time

    now = datetime(2026, 1, 2, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    yesterday = _normalize_publish_time({"pub_time": "昨天 23:59"}, now=now)
    month_day = _normalize_publish_time({"pub_time": "12月31日"}, now=now)

    assert yesterday == {
        "publish_time": int(datetime(2026, 1, 1, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000),
        "publish_date": "2026-01-01",
        "date_source": "display_parse",
        "date_precision": "minute",
    }
    assert month_day == {
        "publish_time": int(datetime(2025, 12, 31, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000),
        "publish_date": "2025-12-31",
        "date_source": "display_parse",
        "date_precision": "day",
    }


def test_publish_date_helper_keeps_detail_api_date_alias() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import _publish_date

    assert _publish_date(1_700_000_000) == datetime.fromtimestamp(
        1_700_000_000,
        ZoneInfo("Asia/Shanghai"),
    ).strftime("%Y-%m-%d")


def test_detail_merge_bounds_content_and_refreshes_legacy_quality_score() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import (
        _merge_video_detail,
        _quality_score,
        parse_creator_item,
    )

    record = parse_creator_item({
        "id_str": "dynamic-detail-bounds",
        "modules": {
            "module_author": {"name": "Synthetic author"},
            "module_dynamic": {"major": {"archive": {"bvid": "BVdetail"}}},
            "module_stat": {},
        },
    })
    _merge_video_detail(record, {
        "title": "T" * 50_000,
        "desc": "D" * 50_000,
        "pubdate": 1_700_000_000,
        "stat": {"like": 2, "reply": 3, "share": 4, "favorite": 5},
    })

    record["quality_score"] = _quality_score(record)
    assert record["title"] == "T" * 100
    assert record["desc"] == "D" * 20_000
    assert record["quality_score"] == 4
