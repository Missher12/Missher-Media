"""Versioned collection contracts, capability matrix and platform normalizers."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json

import pytest

from media_missher_runtime.batch_policy import (
    BatchOutcome,
    BatchPolicy,
    decide_next,
    policy_for,
)
from media_missher_runtime.best_effort import (
    BatchRequest,
    BatchResult,
    BestEffortRunner,
    RequestCancelled,
    RiskStop,
    identity_of,
)
from media_missher_runtime.capabilities import (
    CapabilityError,
    evidence_level,
    require,
    require_task,
    support_level,
    supported,
)
from media_missher_runtime.contracts import (
    BACKEND_COMPUTER_USE,
    BACKEND_CDP,
    COUNT_MODE_BEST_EFFORT,
    COUNT_MODE_FIXED,
    EVIDENCE_PAGE,
    EVIDENCE_RESPONSE,
    STOP_REASON_BUDGET,
    STOP_REASON_CANCELLED,
    STOP_REASON_COUNT_REACHED,
    STOP_REASON_DEADLINE,
    STOP_REASON_NATURAL_END,
    STOP_REASON_NO_NEW,
    STOP_REASON_RISK,
    CollectionPlan,
    ContractError,
    RunManifest,
    Target,
    TaskState,
    normalize_backend,
    target_from_legacy,
)
from media_missher_runtime.platforms import weibo_topic, x


# ---------------------------------------------------------------------------
# backend selection
# ---------------------------------------------------------------------------


def test_explicit_backend_wins_over_profile_preference():
    with pytest.raises(ContractError, match="backend-retired-computer-use"):
        normalize_backend("computer_use", preference="cdp")
    assert normalize_backend("cdp", preference="computer_use") == BACKEND_CDP


def test_profile_preference_is_used_when_the_run_does_not_choose():
    with pytest.raises(ContractError, match="backend-retired-computer-use"):
        normalize_backend(None, preference="computer_use")
    assert normalize_backend(None, preference="cdp") == BACKEND_CDP


def test_missing_configuration_defaults_to_cdp():
    assert normalize_backend(None) == BACKEND_CDP
    assert normalize_backend(None, preference="") == BACKEND_CDP


def test_auto_backend_is_rejected_instead_of_silently_switching():
    with pytest.raises(ContractError):
        normalize_backend("auto")
    with pytest.raises(ContractError):
        normalize_backend("AUTO")


def test_deprecated_browser_assist_bridge_is_not_remapped_to_a_backend():
    with pytest.raises(ContractError, match="browser-assist-replaced"):
        normalize_backend(None, legacy_assist="computer_use")
    assert normalize_backend("cdp", legacy_assist="off") == BACKEND_CDP


# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------


def test_display_name_alone_cannot_form_a_creator_target():
    with pytest.raises(ContractError):
        Target(platform="weibo", mode="creator", label="小 A")


def test_same_display_label_with_different_uids_stays_distinct():
    first = Target(platform="weibo", mode="creator", uid="1001", label="同名")
    second = Target(platform="weibo", mode="creator", uid="1002", label="同名")
    assert first.identity != second.identity
    plan = CollectionPlan(targets=(first, second))
    assert plan.platforms == ("weibo",)


def test_duplicate_targets_are_refused():
    duplicated = Target(platform="x", mode="creator", handle="alice")
    with pytest.raises(ContractError):
        CollectionPlan(targets=(duplicated, duplicated))


def test_more_than_four_targets_is_allowed():
    targets = tuple(
        Target(platform="weibo", mode="creator", uid=str(1000 + index))
        for index in range(7)
    )
    plan = CollectionPlan(targets=targets)
    assert len(plan.targets) == 7


def test_legacy_single_target_adapter_keeps_uid_and_keyword_apart():
    creator = target_from_legacy("bilibili", uid="12345")
    assert creator.mode == "creator"
    search = target_from_legacy("xhs", keyword="露营")
    assert search.mode == "search"
    with pytest.raises(ContractError):
        target_from_legacy("weibo", uid="1", keyword="a")
    with pytest.raises(ContractError):
        target_from_legacy("weibo")


def test_topic_target_requires_weibo_and_an_explicit_kind():
    with pytest.raises(ContractError):
        Target(platform="weibo", mode="topic", topic="旅行")
    with pytest.raises(ContractError):
        Target(platform="xhs", mode="topic", topic="旅行", topic_kind="topic")
    assert Target(
        platform="weibo", mode="topic", topic="旅行", topic_kind="topic"
    ).identity == "weibo:topic:topic:旅行"


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def test_fixed_count_mode_requires_a_positive_count():
    target = Target(platform="x", mode="search", keyword="ai")
    with pytest.raises(ContractError):
        CollectionPlan(targets=(target,), count=0)
    plan = CollectionPlan(targets=(target,), count=0, count_mode=COUNT_MODE_BEST_EFFORT)
    assert plan.count_for(target) == 0


def test_xhs_batch_pages_cannot_exceed_the_existing_platform_limit():
    target = Target(platform="xhs", mode="search", keyword="露营")
    plan = CollectionPlan(targets=(target,), batch_pages=99)
    assert plan.batch_pages == 3


def test_plan_json_round_trip_is_stable():
    plan = CollectionPlan(
        targets=(
            Target(platform="weibo", mode="creator", uid="1001", label="A"),
            Target(platform="x", mode="search", keyword="ai", sort="latest"),
            Target(platform="weibo", mode="topic", topic="旅行", topic_kind="topic"),
        ),
        backend=BACKEND_CDP,
        count_mode=COUNT_MODE_BEST_EFFORT,
        per_target_budget=40,
        run_deadline_seconds=1800,
    )
    restored = CollectionPlan.from_json(json.loads(json.dumps(plan.to_json())))
    assert restored.to_json() == plan.to_json()
    assert restored.backend == BACKEND_CDP


def test_plan_json_rejects_unknown_target_fields():
    payload = {
        "schema_version": 1,
        "targets": [{"platform": "x", "mode": "search", "keyword": "ai", "evil": 1}],
    }
    with pytest.raises(ContractError):
        CollectionPlan.from_json(payload)


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def test_manifest_requires_a_matching_observation_time():
    plan = CollectionPlan(
        targets=(Target(platform="x", mode="search", keyword="ai"),)
    )
    with pytest.raises(ContractError):
        RunManifest(
            run_id="run-1",
            schema_version=1,
            backend=BACKEND_CDP,
            status="complete",
            plan=plan,
            tasks=(),
            counts={},
            record_kinds={},
            evidence_paths=(),
            observed_at="2026-01-01T00:00:00+00:00",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
        )


# ---------------------------------------------------------------------------
# capability matrix
# ---------------------------------------------------------------------------


def test_only_cdp_advertises_response_body_support():
    assert support_level(BACKEND_CDP, "x", "search", "response_body") == "full"
    assert support_level(BACKEND_COMPUTER_USE, "x", "search", "response_body") == "absent"
    assert evidence_level(BACKEND_CDP, "x", "search") == EVIDENCE_RESPONSE
    assert evidence_level(BACKEND_COMPUTER_USE, "x", "search") == EVIDENCE_PAGE


def test_retired_backend_has_no_active_capabilities():
    for name in ("detail_records", "screenshots", "media_assets"):
        assert not supported(BACKEND_COMPUTER_USE, "xhs", "creator", name)
    assert supported(BACKEND_CDP, "xhs", "creator", "detail_records")


def test_requiring_an_absent_capability_is_a_capability_error():
    with pytest.raises(CapabilityError):
        require(BACKEND_COMPUTER_USE, "x", "search", "response_body")


def test_topics_are_only_executable_on_weibo():
    assert supported(BACKEND_CDP, "weibo", "topic", "list_records")
    with pytest.raises(CapabilityError):
        require_task(BACKEND_CDP, "xhs", "topic")


# ---------------------------------------------------------------------------
# X normalization
# ---------------------------------------------------------------------------


def _x_post(**overrides):
    base = dict(
        tweet_id="1899999999999999999",
        author_id="2040009202018504704",
        handle="alice",
        author_name="Alice",
        text="hello world",
        text_complete=True,
        published_at="2026-08-30T11:39:23+00:00",
        date_text="Sun Aug 30 11:39:23 +0000 2026",
        observed_at="2026-09-20T00:00:00+00:00",
        metric_values={"liked": 5},
        source_url="https://x.com/alice/status/1899999999999999999",
        query="ai",
        backend=BACKEND_CDP,
        evidence_level=EVIDENCE_RESPONSE,
    )
    base.update(overrides)
    return x.normalize_post(**base)


def test_large_native_identifiers_stay_text():
    record = _x_post()
    assert record["tweet_id"] == "1899999999999999999"
    assert isinstance(record["tweet_id"], str)
    assert isinstance(record["author_id"], str)
    assert record["link"] == "https://x.com/alice/status/1899999999999999999"


def test_missing_author_identity_is_null_rather_than_guessed_from_the_handle():
    record = _x_post(author_id=None)
    assert record["author_id"] is None
    assert record["field_quality"]["author_id"] == "unknown"


def test_absent_metrics_are_null_and_never_zero():
    record = _x_post(metric_values={})
    for field in ("liked", "comments", "shares", "quotes", "views", "bookmarks"):
        assert record[field] is None
        assert record["field_quality"][field] == "unknown"


def test_abbreviated_metric_keeps_display_text_and_rounded_precision():
    record = _x_post(
        metric_values={"liked": 1200.0},
        metric_display={"liked": "1.2K"},
    )
    assert record["liked"] == 1200.0
    assert record["liked_display"] == "1.2K"
    assert record["field_quality"]["liked"] == "rounded"


def test_exact_display_metric_is_reported_as_exact():
    value, precision = x.parse_display_metric("1,234")
    assert (value, precision) == (1234, "exact")


def test_bookmarks_and_collected_are_one_same_origin_metric():
    record = _x_post(metric_values={"bookmarks": 12})
    assert record["bookmarks"] == 12
    assert record["collected"] == 12


def test_truncated_long_post_is_marked_rather_than_presented_as_complete():
    record = _x_post(text="cut off…", text_complete=False)
    assert record["text_complete"] is False
    assert record["field_quality"]["text"] == "truncated"


def test_quoted_post_is_a_reference_not_a_second_record():
    record = _x_post(
        relation="quote",
        referenced_tweet_ids=["123"],
        quoted_tweet_id="123",
    )
    assert record["referenced_tweet_ids"] == ["123"]
    assert record["relation"] == "quote"


def test_dedup_key_is_platform_native_identity():
    record = _x_post()
    assert x.dedup_key(record) == "x:post:1899999999999999999"


def test_search_url_encodes_the_keyword_and_names_the_sort_order():
    url = x.search_url("萤火虫 漫展", "latest")
    assert "q=%E8%90%A4%E7%81%AB%E8%99%AB%20%E6%BC%AB%E5%B1%95" in url
    assert "f=live" in url
    assert "f=top" in x.search_url("萤火虫漫展", "top")
    with pytest.raises(ValueError):
        x.search_url("ai", "chronological")


def test_hashtag_reuses_search_instead_of_a_guessed_timeline_endpoint():
    url = x.hashtag_url("旅行")
    assert url.startswith("https://x.com/search?")
    assert "HashtagTimeline" not in url


def test_response_binding_matches_only_the_current_query_and_operation():
    binding = x.target_binding(Target(platform="x", mode="search", keyword="ai"))
    matching = (
        "https://x.com/i/api/graphql/abc/SearchTimeline"
        '?variables={"rawQuery":"ai","product":"Latest","count":20}'
    )
    other_query = (
        "https://x.com/i/api/graphql/abc/SearchTimeline"
        '?variables={"rawQuery":"other"}'
    )
    other_operation = (
        "https://x.com/i/api/graphql/abc/HomeTimeline"
        '?variables={"rawQuery":"ai"}'
    )
    assert x.response_matches(url=matching, binding=binding)
    assert not x.response_matches(url=other_query, binding=binding)
    assert not x.response_matches(url=other_operation, binding=binding)
    assert not x.response_matches(
        url="https://evil.example/i/api/graphql/abc/SearchTimeline?variables=%7B%22rawQuery%22%3A%22ai%22%7D",
        binding=binding,
    )


def test_creator_binding_matches_the_exact_author_not_any_timeline():
    binding = x.target_binding(
        Target(platform="x", mode="creator", handle="alice", uid="2040009202018504704")
    )
    matching = (
        "https://x.com/i/api/graphql/abc/UserTweets"
        '?variables={"userId":"2040009202018504704","count":20}'
    )
    other_user = (
        "https://x.com/i/api/graphql/abc/UserTweets"
        '?variables={"userId":"1","count":20}'
    )
    assert x.response_matches(url=matching, binding=binding)
    assert not x.response_matches(url=other_user, binding=binding)


_X_RESPONSE_FIXTURE = {
    "data": {
        "user": {
            "result": {
                "timeline": {
                    "instructions": [
                        {
                            "type": "TimelineAddEntries",
                            "entries": [
                                {
                                    "entryId": "tweet-1",
                                    "content": {
                                        "itemContent": {
                                            "tweet_results": {
                                                "result": {
                                                    "rest_id": "1899999999999999999",
                                                    "core": {
                                                        "user_results": {
                                                            "result": {
                                                                "rest_id": "2040009202018504704",
                                                                "core": {
                                                                    "screen_name": "alice",
                                                                    "name": "Alice",
                                                                },
                                                            }
                                                        }
                                                    },
                                                    "legacy": {
                                                        "id_str": "1899999999999999999",
                                                        "full_text": "short legacy text",
                                                        "created_at": "Sun Aug 30 11:39:23 +0000 2026",
                                                        "conversation_id_str": "1899999999999999999",
                                                        "favorite_count": 8363,
                                                        "reply_count": 6,
                                                        "retweet_count": 404,
                                                        "quote_count": 2,
                                                        "lang": "zh",
                                                        "extended_entities": {
                                                            "media": [
                                                                {
                                                                    "type": "photo",
                                                                    "media_url_https": "https://pbs.twimg.com/media/a.jpg",
                                                                    "original_info": {"width": 1200, "height": 800},
                                                                }
                                                            ]
                                                        },
                                                    },
                                                    "views": {"count": "415822"},
                                                    "note_tweet": {
                                                        "note_tweet_results": {
                                                            "result": {"text": "the expanded long text"}
                                                        }
                                                    },
                                                }
                                            }
                                        }
                                    },
                                }
                            ],
                        }
                    ]
                }
            }
        }
    }
}


def test_response_route_prefers_the_expanded_long_form_text():
    records = x.normalize_response_payload(
        _X_RESPONSE_FIXTURE,
        observed_at="2026-09-20T00:00:00+00:00",
        query="ai",
    )
    assert len(records) == 1
    record = records[0]
    assert record["text"] == "the expanded long text"
    assert record["text_complete"] is True
    assert record["tweet_id"] == "1899999999999999999"
    assert record["author_id"] == "2040009202018504704"
    assert record["views"] == 415822
    assert record["comments"] == 6
    assert record["media_kind"] == "photo"
    assert record["media_width"] == 1200
    assert record["evidence_level"] == EVIDENCE_RESPONSE


def test_response_route_marks_a_post_without_note_tweet_as_truncated():
    payload = json.loads(json.dumps(_X_RESPONSE_FIXTURE))
    result = payload["data"]["user"]["result"]["timeline"]["instructions"][0]["entries"][0]
    del result["content"]["itemContent"]["tweet_results"]["result"]["note_tweet"]
    records = x.normalize_response_payload(
        payload, observed_at="2026-09-20T00:00:00+00:00", query="ai"
    )
    assert records[0]["text"] == "short legacy text"
    assert records[0]["text_complete"] is False


def test_response_route_refuses_an_unknown_operation():
    assert x.observed_operation("https://x.com/i/api/graphql/x/Recommendations") is None
    assert x.observed_operation("https://x.com/i/api/graphql/x/SearchTimeline") == "SearchTimeline"
    assert x.observed_operation("https://example.com/i/api/graphql/x/SearchTimeline") is None


def test_page_route_refuses_cards_from_another_author():
    payload = {
        "posts": [
            {
                "permalink": "https://x.com/bob/status/123",
                "handle": "bob",
                "text": "not alice",
            }
        ]
    }
    records = x.normalize_page_payload(
        payload,
        query=None,
        target_identity="x:creator:alice",
        observed_at="2026-09-20T00:00:00+00:00",
        source_url="https://x.com/alice",
        expected_handle="alice",
    )
    assert records == []


def test_page_route_records_the_page_evidence_level():
    payload = {
        "posts": [
            {
                "permalink": "https://x.com/alice/status/123",
                "handle": "alice",
                "author_name": "Alice",
                "text": "visible text",
                "datetime": "2026-08-30T11:39:23.000Z",
                "like_metric": 12,
                "image_urls": ["https://pbs.twimg.com/media/a.jpg"],
            }
        ]
    }
    records = x.normalize_page_payload(
        payload,
        query=None,
        target_identity="x:creator:alice",
        observed_at="2026-09-20T00:00:00+00:00",
        source_url="https://x.com/alice",
        expected_handle="alice",
    )
    assert len(records) == 1
    assert records[0]["evidence_level"] == EVIDENCE_PAGE
    assert records[0]["backend"] == BACKEND_CDP
    assert records[0]["author_id"] is None
    assert records[0]["tweet_id"] == "123"


# ---------------------------------------------------------------------------
# Weibo topics and profiles
# ---------------------------------------------------------------------------


def test_plain_hashtag_input_becomes_a_standard_topic():
    parsed = weibo_topic.parse_topic_input("#旅行#")
    assert parsed.kind == "topic"
    assert parsed.name == "旅行"
    assert parsed.page_url.startswith("https://s.weibo.com/weibo?q=")


def test_super_topic_link_is_recognized_and_kept_distinct_from_a_plain_topic():
    parsed = weibo_topic.parse_topic_input("https://weibo.com/p/100808abc123")
    assert parsed.kind == "super"
    assert parsed.container_id == "100808abc123"
    assert not weibo_topic.supported_topic_kind(parsed.kind)


def test_keyword_search_is_not_silently_treated_as_a_super_topic():
    with pytest.raises(weibo_topic.TopicError):
        weibo_topic.parse_topic_input("https://weibo.com/p/230491")


def test_topic_post_extraction_counts_only_the_outer_author():
    topic = weibo_topic.parse_topic_input("#旅行#")
    registry = weibo_topic.ParticipantRegistry()
    payload = {
        "posts": [
            {
                "mid": "5001",
                "text": "outer post",
                "author_name": "外层",
                "author_domain": "u",
                "author_href": "https://weibo.com/u/1001",
                "author_uid": "1001",
                "liked": 3,
            },
            {
                "mid": "5002",
                "text": "forwarded",
                "author_name": "转发者",
                "author_domain": "u",
                "author_href": "https://weibo.com/u/1002",
                "author_uid": "1002",
                "retweet_author_name": "原作者",
                "liked": 1,
            },
            {
                "mid": "5003",
                "text": "only an inner author",
                "author_name": None,
                "author_href": None,
                "author_uid": None,
                "retweet_author_name": "原作者",
            },
            {"mid": "not-a-safe-id", "text": "ignored"},
        ]
    }
    posts, next_url = weibo_topic.normalize_topic_payload(
        payload,
        topic=topic,
        observed_at="2026-09-20T00:00:00+00:00",
        backend=BACKEND_CDP,
        evidence_level=EVIDENCE_RESPONSE,
        source_url=topic.page_url,
        registry=registry,
    )
    assert next_url is None
    assert [post["mblog_id"] for post in posts] == ["5001", "5002", "5003"]
    assert set(registry.users) == {"1001", "1002"}
    assert registry.skipped_inner_authors == 1
    assert posts[1]["inner_author_name"] == "原作者"
    assert posts[1]["via_repost"] is True


def test_one_user_in_two_topics_keeps_both_relations_but_one_user_entry():
    first = weibo_topic.parse_topic_input("#旅行#")
    second = weibo_topic.parse_topic_input("#摄影#")
    registry = weibo_topic.ParticipantRegistry()
    for topic, mid in ((first, "6001"), (second, "6002")):
        weibo_topic.normalize_topic_payload(
            {
                "posts": [
                    {
                        "mid": mid,
                        "text": "post",
                        "author_name": "同一个人",
                        "author_domain": "u",
                        "author_uid": "1001",
                    }
                ]
            },
            topic=topic,
            observed_at="2026-09-20T00:00:00+00:00",
            backend=BACKEND_CDP,
            evidence_level=EVIDENCE_RESPONSE,
            source_url=topic.page_url,
            registry=registry,
        )
    assert len(registry.users) == 1
    entry = registry.users["1001"]
    assert entry["topics"] == ["旅行", "摄影"]
    assert entry["post_ids"] == ["6001", "6002"]
    assert len(registry.relations) == 2


def test_profile_record_keeps_missing_fields_null_and_abbreviations_rounded():
    record = weibo_topic.normalize_profile(
        "1001",
        {
            "display_name": "某用户",
            "followers": "1.2万",
            "following": "34",
            "posts": None,
        },
        observed_at="2026-09-20T00:00:00+00:00",
        backend=BACKEND_CDP,
        evidence_level=EVIDENCE_RESPONSE,
        source_url="https://weibo.com/u/1001",
    )
    assert record["followers"] == 12000.0
    assert record["followers_display"] == "1.2万"
    assert record["field_quality"]["followers"] == "rounded"
    assert record["following"] == 34
    assert record["field_quality"]["following"] == "exact"
    assert record["posts"] is None
    assert record["field_quality"]["posts"] == "unknown"
    assert record["region"] is None
    assert record["profile_status"] == "complete"


def test_profile_failure_keeps_a_fixed_reason_and_the_user_entry():
    record = weibo_topic.normalize_profile(
        "1001",
        {},
        observed_at="2026-09-20T00:00:00+00:00",
        backend=BACKEND_CDP,
        evidence_level=EVIDENCE_RESPONSE,
        source_url=None,
        failure_reason=weibo_topic.profile_failure_reason("login"),
    )
    assert record["profile_status"] == "failed"
    assert record["failure_reason"] == "profile-login-required"
    assert record["link"] == "https://weibo.com/u/1001"
    assert weibo_topic.profile_failure_reason("unknown-signal") == "profile-unavailable"


def test_profile_alias_links_normalize_to_the_canonical_uid_url():
    assert (
        weibo_topic.canonical_profile_url("https://weibo.com/1001")
        == "https://weibo.com/u/1001"
    )
    assert (
        weibo_topic.canonical_profile_url("/u/1001?is_all=1")
        == "https://weibo.com/u/1001"
    )
    assert weibo_topic.canonical_profile_url("https://evil.example/u/1001") is None


# ---------------------------------------------------------------------------
# best_effort runner
# ---------------------------------------------------------------------------


def _target_state(platform="x"):
    target = Target(platform=platform, mode="search", keyword="ai")
    return TaskState(target=target)


def _posts(platform, start, count):
    key = {"x": "tweet_id", "weibo": "mblog_id"}[platform]
    return [
        {"platform": platform, "type": "post", key: str(start + index)}
        for index in range(count)
    ]


def test_best_effort_keeps_collecting_past_ten_records():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=0, max_batches=6
    )
    runner = BestEffortRunner(
        policy=policy,
        count_mode=COUNT_MODE_BEST_EFFORT,
        deadline_seconds=600,
        sleep=_no_sleep,
    )
    calls = []

    async def execute(request: BatchRequest) -> BatchResult:
        calls.append(request.batch_index)
        start = request.batch_index * 10
        return BatchResult(records=_posts("x", start, 10), pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    assert len(outcome.records) == 60
    assert calls == [0, 1, 2, 3, 4, 5]
    assert outcome.state.stop_reason == STOP_REASON_BUDGET


def test_repeated_cursor_is_deduplicated_and_stalls_out():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=0, max_batches=8
    )
    runner = BestEffortRunner(
        policy=policy, count_mode=COUNT_MODE_BEST_EFFORT, deadline_seconds=600, sleep=_no_sleep
    )

    async def execute(request: BatchRequest) -> BatchResult:
        return BatchResult(records=_posts("x", 0, 10), pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    assert len(outcome.records) == 10
    assert outcome.state.stop_reason == STOP_REASON_NO_NEW
    # The stall limit is two consecutive batches without a new identity, so the
    # first batch plus those two attempts were executed.
    assert outcome.state.batches == 3


def test_pinned_and_repeated_cards_are_counted_once():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=0, max_batches=3
    )
    runner = BestEffortRunner(
        policy=policy, count_mode=COUNT_MODE_BEST_EFFORT, deadline_seconds=600, sleep=_no_sleep
    )
    batches = [
        _posts("x", 0, 3) + [{"platform": "x", "type": "post", "tweet_id": "999", "is_pinned": True}],
        [{"platform": "x", "type": "post", "tweet_id": "999", "is_pinned": True}] + _posts("x", 3, 3),
        _posts("x", 6, 3),
    ]

    async def execute(request: BatchRequest) -> BatchResult:
        return BatchResult(records=batches[request.batch_index], pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    identities = [record["tweet_id"] for record in outcome.records]
    assert identities.count("999") == 1
    assert len(identities) == len(set(identities))


def test_zero_results_end_immediately_with_an_explicit_reason():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=0, max_batches=5
    )
    runner = BestEffortRunner(
        policy=policy, count_mode=COUNT_MODE_BEST_EFFORT, deadline_seconds=600, sleep=_no_sleep
    )
    calls = []

    async def execute(request: BatchRequest) -> BatchResult:
        calls.append(request.batch_index)
        return BatchResult(records=[], pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    assert calls == [0]
    assert outcome.state.stop_reason == "empty-results"
    assert outcome.records == []


def test_run_deadline_stops_before_an_illegal_wait():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=200, max_batches=8
    )
    clock = _FakeClock()
    runner = BestEffortRunner(
        policy=policy,
        count_mode=COUNT_MODE_BEST_EFFORT,
        deadline_seconds=600,
        sleep=_no_sleep,
        monotonic=clock,
    )

    async def execute(request: BatchRequest) -> BatchResult:
        clock.advance(200)
        return BatchResult(records=_posts("x", request.batch_index * 10, 10), pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    # 200s per batch plus the 200s pause fits three batches inside 600s; the
    # fourth would need another 200s pause past the remaining window.
    assert outcome.state.batches == 3
    assert outcome.state.stop_reason == STOP_REASON_DEADLINE


def test_risk_signal_stops_without_retrying_and_keeps_the_verified_prefix():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=0, max_batches=5
    )
    runner = BestEffortRunner(
        policy=policy, count_mode=COUNT_MODE_BEST_EFFORT, deadline_seconds=600, sleep=_no_sleep
    )
    calls = []

    async def execute(request: BatchRequest) -> BatchResult:
        calls.append(request.batch_index)
        if request.batch_index == 1:
            raise RiskStop("http-429")
        return BatchResult(records=_posts("x", request.batch_index * 10, 5), pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    assert calls == [0, 1]
    assert len(outcome.records) == 5
    assert outcome.state.stop_reason == STOP_REASON_RISK
    assert outcome.state.phase == "risk-stopped"
    assert outcome.state.checkpoint["risk_code"] == "http-429"


def test_cancellation_keeps_the_accepted_prefix_and_reports_cancelled():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=0, max_batches=5
    )
    state = {"cancelled": False}
    checkpoints = []
    runner = BestEffortRunner(
        policy=policy,
        count_mode=COUNT_MODE_BEST_EFFORT,
        deadline_seconds=600,
        sleep=_no_sleep,
        cancel_check=lambda: state["cancelled"],
        checkpoint=lambda task_state, records: checkpoints.append(len(records)),
    )

    async def execute(request: BatchRequest) -> BatchResult:
        state["cancelled"] = True
        return BatchResult(records=_posts("x", request.batch_index * 10, 4), pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    assert len(outcome.records) == 4
    assert outcome.state.stop_reason == STOP_REASON_CANCELLED
    assert checkpoints[-1] == 4


def test_fixed_count_stops_exactly_at_the_requested_target():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=0, max_batches=5
    )
    runner = BestEffortRunner(
        policy=policy, count_mode=COUNT_MODE_FIXED, count=4, deadline_seconds=600, sleep=_no_sleep
    )

    async def execute(request: BatchRequest) -> BatchResult:
        return BatchResult(records=_posts("x", 0, 10), pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    assert len(outcome.records) == 4
    assert outcome.state.stop_reason == STOP_REASON_COUNT_REACHED


def test_batch_budget_is_reported_as_a_pause_not_as_completion():
    policy = BatchPolicy(
        platform="x", batch_records=5, batch_pages=3, interval_seconds=0, max_batches=2
    )
    runner = BestEffortRunner(
        policy=policy, count_mode=COUNT_MODE_BEST_EFFORT, deadline_seconds=600, sleep=_no_sleep
    )

    async def execute(request: BatchRequest) -> BatchResult:
        return BatchResult(records=_posts("x", request.batch_index * 5, 5), pages=1)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    assert outcome.state.stop_reason == STOP_REASON_BUDGET
    assert len(outcome.records) == 10


def test_natural_end_is_reported_when_the_platform_runs_out():
    policy = BatchPolicy(
        platform="x", batch_records=10, batch_pages=3, interval_seconds=0, max_batches=5
    )
    runner = BestEffortRunner(
        policy=policy, count_mode=COUNT_MODE_BEST_EFFORT, deadline_seconds=600, sleep=_no_sleep
    )

    async def execute(request: BatchRequest) -> BatchResult:
        return BatchResult(records=_posts("x", 0, 3), pages=1, exhausted=True)

    outcome = asyncio.run(runner.run(_target_state(), execute))
    assert outcome.state.stop_reason == STOP_REASON_NATURAL_END
    assert outcome.state.phase == "complete"
    assert len(outcome.records) == 3


def test_identity_key_separates_record_kinds_and_platforms():
    assert identity_of({"type": "post", "tweet_id": "1"}, "x") == "x:post:tweet_id:1"
    assert (
        identity_of({"type": "user_profile", "uid": "1"}, "weibo")
        == "weibo:user_profile:uid:1"
    )
    assert identity_of({"type": "post", "uid": "1"}, "weibo") == "weibo:post:uid:1"
    assert identity_of({"type": "post"}, "x") is None


def test_xhs_policy_numbers_cannot_be_quietly_relaxed():
    policy = policy_for("xhs")
    assert policy.batch_records == 10
    assert policy.batch_pages == 3
    assert policy.interval_seconds == 600


def test_x_has_its_own_policy_instead_of_inheriting_xhs_limits():
    policy = policy_for("x")
    assert policy.platform == "x"
    assert policy.batch_records != policy_for("xhs").batch_records
    assert policy.interval_seconds != policy_for("xhs").interval_seconds


def test_decide_next_prefers_completion_over_a_budget_pause():
    policy = policy_for("x")
    decision = decide_next(
        policy=policy,
        batch_index=0,
        outcome=BatchOutcome(added=5, pages=1, exhausted=True),
        total=5,
        elapsed_seconds=1,
        deadline_seconds=100,
        stall_count=0,
        fixed_target=None,
    )
    assert decision.stop is True
    assert decision.reason == STOP_REASON_NATURAL_END


def test_decide_next_never_waits_past_the_deadline():
    policy = BatchPolicy(
        platform="x", batch_records=5, batch_pages=1, interval_seconds=600, max_batches=5
    )
    decision = decide_next(
        policy=policy,
        batch_index=0,
        outcome=BatchOutcome(added=5, pages=1),
        total=5,
        elapsed_seconds=100,
        deadline_seconds=300,
        stall_count=0,
        fixed_target=None,
    )
    assert decision.stop is True
    assert decision.reason == STOP_REASON_DEADLINE


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


async def _no_sleep(_seconds: float) -> None:
    return None


def test_request_cancelled_is_a_distinct_signal_from_a_platform_risk_stop():
    assert issubclass(RequestCancelled, RuntimeError)
    assert issubclass(RiskStop, RuntimeError)


def test_task_state_json_is_serializable():
    state = _target_state()
    state.phase = "collecting"
    state.posts = 3
    json.dumps(state.to_json())


def test_replace_helper_keeps_plan_immutability():
    plan = CollectionPlan(targets=(Target(platform="x", mode="search", keyword="ai"),))
    with pytest.raises(Exception):
        plan.count = 5  # type: ignore[misc]
    assert replace(plan, count=5).count == 5
