from __future__ import annotations

import pytest
import json
from pathlib import Path


def test_collection_request_accepts_a_creator_request() -> None:
    from runtime.media_missher_runtime.models import CollectionRequest

    request = CollectionRequest(platform="bilibili", count=2, uid="creator-1")

    assert request.platform == "bilibili"
    assert request.page_cap == 20
    assert request.target_count == 2


def test_collection_request_accepts_safe_assist_and_screenshot_modes() -> None:
    from runtime.media_missher_runtime.models import CollectionRequest

    request = CollectionRequest(
        platform="bilibili",
        count=1,
        uid="creator",
        browser_assist="off",
        screenshot_mode="opened",
    )

    assert request.browser_assist == "off"
    assert request.screenshot_mode == "opened"


def test_collection_request_accepts_xhs_screenshot_with_assist_off() -> None:
    from runtime.media_missher_runtime.models import CollectionRequest

    request = CollectionRequest(
        platform="xhs",
        count=1,
        uid="creator",
        screenshot_mode="opened",
    )

    assert request.browser_assist == "off"
    assert request.screenshot_mode == "opened"


def test_opened_screenshot_mode_keeps_xhs_count_zero_within_batch_budget() -> None:
    from runtime.media_missher_runtime.models import CollectionRequest

    request = CollectionRequest(
        platform="xhs",
        count=0,
        uid="creator",
        screenshot_mode="opened",
    )

    assert request.target_count == 10


@pytest.mark.parametrize(
    "values",
    (
        {"platform": "xhs", "count": 0, "uid": "creator", "screenshot_mode": "all"},
        {"platform": "bilibili", "count": 1, "keyword": "topic", "browser_assist": "browserskill"},
        {"platform": "bilibili", "count": 1, "keyword": "topic", "screenshot_mode": "all"},
    ),
)
def test_collection_request_rejects_unbounded_or_unsupported_advanced_modes(
    values: dict[str, object],
) -> None:
    from runtime.media_missher_runtime.models import CollectionRequest

    with pytest.raises(ValueError, match="not supported|positive|backend-retired-browserskill"):
        CollectionRequest(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    (("browser_assist", "stealth"), ("screenshot_mode", "background")),
)
def test_collection_request_rejects_unknown_modes(field: str, value: str) -> None:
    from runtime.media_missher_runtime.models import CollectionRequest

    values = {"platform": "xhs", "count": 1, "uid": "creator", field: value}
    with pytest.raises(ValueError, match="unsupported"):
        CollectionRequest(**values)


@pytest.mark.parametrize("platform", ("bilibili", "xhs", "douyin", "weibo"))
def test_collection_request_accepts_only_supported_platforms(platform: str) -> None:
    from runtime.media_missher_runtime.models import CollectionRequest

    assert CollectionRequest(platform=platform, count=0, keyword="term").target_count == (10 if platform == "xhs" else None)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"platform": "other"}, "unsupported"),
        ({"count": -1}, "nonnegative"),
        ({"comment_limit": -1}, "nonnegative"),
        ({"page_cap": 0}, "at least"),
        ({"uid": None, "keyword": None}, "exactly one"),
        ({"uid": "one", "keyword": "two"}, "exactly one"),
    ),
)
def test_collection_request_rejects_invalid_input(changes: dict[str, object], message: str) -> None:
    from runtime.media_missher_runtime.models import CollectionRequest

    values: dict[str, object] = {"platform": "weibo", "count": 1, "uid": "creator"}
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        CollectionRequest(**values)  # type: ignore[arg-type]


def test_runtime_result_preserves_structured_status() -> None:
    from runtime.media_missher_runtime.models import RunResult, RuntimeStatus

    result = RunResult(status=RuntimeStatus.COMPLETE, records=2, pages=1)

    assert result.status is RuntimeStatus.COMPLETE
    assert result.records == 2


def test_synthetic_runtime_fixtures_preserve_zero_null_nested_and_duplicates() -> None:
    fixture_root = Path("tests/runtime_fixtures")
    expected = {
        f"{platform}_{mode}.json"
        for platform in ("bilibili", "xhs", "douyin", "weibo")
        for mode in ("creator", "search")
    } | {"bilibili_complete.json", "xhs_complete.json"}

    assert {item.name for item in fixture_root.glob("*.json")} == expected
    for fixture in fixture_root.glob("*.json"):
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        assert len(payload["pages"]) == 2
        assert payload["pages"][0]["records"][0]["native_id"] == payload["pages"][1]["records"][0]["native_id"]
        assert payload["pages"][0]["records"][1]["metric_zero"] == 0
        assert payload["pages"][0]["records"][1]["nullable"] is None
        assert payload["pages"][0]["records"][0]["author"]["name"]
        assert payload["pages"][0]["records"][0]["media"]["kind"]
