from __future__ import annotations


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


def test_search_parser_keeps_legacy_fields_and_uniform_aliases() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import parse_search_item

    record = parse_search_item({"bvid": "BVsearch", "title": "<em>Title</em>", "description": "Desc", "like": 0, "review": 1}, "term", observed_at="2026-01-01T00:00:00+00:00")

    assert record["title"] == "Title"
    assert record["liked"] == 0
    assert record["native_id"] == record["id"] == "BVsearch"
    assert record["url"] == record["link"] == "https://www.bilibili.com/video/BVsearch"
    assert record["detail_completed"] is False
    assert record["search_keyword"] == "term"
