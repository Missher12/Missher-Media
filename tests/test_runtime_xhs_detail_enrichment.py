from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from runtime.media_missher_runtime.browser import PreconditionError
from runtime.media_missher_runtime.platforms._xhs_detail_enrichment import (
    COMMENT_SCROLL_LIMIT,
    COMMENT_SCROLL_WAIT_MS,
    XhsCommentRisk,
    load_bounded_comments,
)


@dataclass
class Page:
    url: str = "https://www.xiaohongshu.com/explore/note-1"
    reads: list[object] = field(default_factory=list)
    scrolls: list[object] = field(default_factory=list)
    evaluations: list[str] = field(default_factory=list)
    waits: list[int] = field(default_factory=list)

    async def evaluate(self, script: str, _arg: object = None) -> object:
        self.evaluations.append(script)
        if "MEDIA_MISSHER_XHS_COMMENT_READ" in script:
            if not self.reads:
                raise AssertionError("unexpected comment read")
            return self.reads.pop(0)
        if "MEDIA_MISSHER_XHS_COMMENT_SCROLL" in script:
            if not self.scrolls:
                raise AssertionError("unexpected comment scroll")
            return self.scrolls.pop(0)
        raise AssertionError("unexpected page script")

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


def comment(text: str | None, *, author: str | None = "A") -> dict[str, Any]:
    return {"author": author, "text": text, "date": "today", "liked": "1"}


def normalize(items: Sequence[Any], limit: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or len(output) >= limit:
            continue
        output.append(
            {
                "author": item.get("author"),
                "text": item.get("text"),
                "date": item.get("date"),
                "liked": int(item["liked"]) if item.get("liked") else None,
            }
        )
    return output


@pytest.mark.asyncio
async def test_initial_visible_slice_completes_without_scroll() -> None:
    page = Page(reads=[{"risk_text": "", "comments": [comment("one")]}])

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=10,
        total=1,
        normalize_comments=normalize,
    )

    assert result.stop_reason == "complete"
    assert result.comments_fetched == 1
    assert result.scrolls == 0
    assert page.waits == []


@pytest.mark.asyncio
async def test_growing_frames_deduplicate_and_stop_at_requested_slice() -> None:
    page = Page(
        reads=[
            {"risk_text": "", "comments": [comment("one")]},
            {"risk_text": "", "comments": [comment("one"), comment("two")]},
        ],
        scrolls=[{"risk_text": "", "state": "scrolled"}],
    )

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=2,
        total=None,
        normalize_comments=normalize,
    )

    assert [item["text"] for item in result.comments] == ["one", "two"]
    assert result.comments_fetched == 2
    assert result.scrolls == 1
    assert result.stop_reason == "complete"
    assert page.waits == [COMMENT_SCROLL_WAIT_MS]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    ("container-missing", "container-ambiguous", "container-not-scrollable"),
)
async def test_container_failure_returns_partial_without_wait(state: str) -> None:
    page = Page(
        reads=[{"risk_text": "", "comments": [comment("one")]}],
        scrolls=[{"risk_text": "", "state": state}],
    )

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=2,
        total=2,
        normalize_comments=normalize,
    )

    assert result.stop_reason == state
    assert result.comments_fetched == 1
    assert result.scrolls == 0
    assert page.waits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "total", "reason"),
    ((0, None, "not-requested"), (10, 0, "complete")),
)
async def test_zero_target_never_touches_dom(
    requested: int,
    total: int | None,
    reason: str,
) -> None:
    page = Page()

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=requested,
        total=total,
        normalize_comments=normalize,
    )

    assert result.stop_reason == reason
    assert result.comments_fetched == result.scrolls == 0
    assert page.evaluations == []


@pytest.mark.asyncio
async def test_known_total_smaller_than_limit_is_the_target() -> None:
    page = Page(
        reads=[{"risk_text": "", "comments": [comment("one"), comment("two")]}]
    )

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=10,
        total=2,
        normalize_comments=normalize,
    )

    assert result.comments_fetched == 2
    assert result.stop_reason == "complete"
    assert result.scrolls == 0


@pytest.mark.asyncio
async def test_unknown_total_uses_requested_limit() -> None:
    page = Page(
        reads=[{"risk_text": "", "comments": [comment("one")]}],
        scrolls=[{"risk_text": "", "state": "container-not-scrollable"}],
    )

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=2,
        total=None,
        normalize_comments=normalize,
    )

    assert result.comments_fetched == 1
    assert result.stop_reason == "container-not-scrollable"


@pytest.mark.asyncio
async def test_empty_business_comment_is_discarded() -> None:
    page = Page(
        reads=[{"risk_text": "", "comments": [comment(None, author=None)]}],
        scrolls=[{"risk_text": "", "state": "container-missing"}],
    )

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=1,
        total=1,
        normalize_comments=normalize,
    )

    assert result.comments_fetched == 0
    assert result.stop_reason == "container-missing"


@pytest.mark.asyncio
async def test_no_growth_stops_after_one_scroll() -> None:
    frame = {"risk_text": "", "comments": [comment("one")]}
    page = Page(
        reads=[frame, frame],
        scrolls=[{"risk_text": "", "state": "scrolled"}],
    )

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=3,
        total=3,
        normalize_comments=normalize,
    )

    assert result.stop_reason == "no-growth"
    assert result.scrolls == 1
    assert page.waits == [COMMENT_SCROLL_WAIT_MS]


@pytest.mark.asyncio
async def test_budget_exhaustion_never_uses_a_fourth_scroll() -> None:
    page = Page(
        reads=[
            {"risk_text": "", "comments": [comment(str(i)) for i in range(size)]}
            for size in (1, 2, 3, 4)
        ],
        scrolls=[
            {"risk_text": "", "state": "scrolled"}
            for _ in range(COMMENT_SCROLL_LIMIT)
        ],
    )

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=5,
        total=5,
        normalize_comments=normalize,
    )

    assert result.stop_reason == "budget-exhausted"
    assert result.scrolls == COMMENT_SCROLL_LIMIT == 3
    assert page.waits == [COMMENT_SCROLL_WAIT_MS] * COMMENT_SCROLL_LIMIT


@pytest.mark.asyncio
@pytest.mark.parametrize("risk_location", ("initial", "scroll", "post-scroll"))
async def test_risk_stops_at_its_first_observation(risk_location: str) -> None:
    safe = {"risk_text": "", "comments": [comment("one")]}
    risk = {"risk_text": "challenge-selector", "comments": []}
    page = Page(
        reads=[risk] if risk_location == "initial" else [safe, risk],
        scrolls=(
            [
                {"risk_text": "challenge-selector", "state": None}
                if risk_location == "scroll"
                else {"risk_text": "", "state": "scrolled"}
            ]
            if risk_location != "initial"
            else []
        ),
    )

    with pytest.raises(XhsCommentRisk, match="challenge-selector"):
        await load_bounded_comments(
            page,
            note_id="note-1",
            requested=2,
            total=2,
            normalize_comments=normalize,
        )

    expected_waits = [COMMENT_SCROLL_WAIT_MS] if risk_location == "post-scroll" else []
    assert page.waits == expected_waits


@pytest.mark.asyncio
async def test_wrong_detail_url_fails_before_dom_observation() -> None:
    page = Page(url="https://www.xiaohongshu.com/explore/other")

    with pytest.raises(PreconditionError, match="exact Xiaohongshu detail"):
        await load_bounded_comments(
            page,
            note_id="note-1",
            requested=1,
            total=1,
            normalize_comments=normalize,
        )

    assert page.evaluations == []


@pytest.mark.asyncio
async def test_detail_url_change_before_scroll_fails_closed() -> None:
    class ChangingPage(Page):
        async def evaluate(self, script: str, _arg: object = None) -> object:
            result = await super().evaluate(script, _arg)
            if "MEDIA_MISSHER_XHS_COMMENT_READ" in script:
                self.url = "https://www.xiaohongshu.com/explore/other"
            return result

    page = ChangingPage(
        reads=[{"risk_text": "", "comments": [comment("one")]}],
        scrolls=[{"risk_text": "", "state": "scrolled"}],
    )

    with pytest.raises(PreconditionError, match="exact Xiaohongshu detail"):
        await load_bounded_comments(
            page,
            note_id="note-1",
            requested=2,
            total=2,
            normalize_comments=normalize,
        )

    assert sum("COMMENT_SCROLL" in script for script in page.evaluations) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", ("not-a-sequence", {"not": "a-list"}))
async def test_malformed_comment_sequence_is_empty(malformed: object) -> None:
    page = Page(
        reads=[{"risk_text": "", "comments": malformed}],
        scrolls=[{"risk_text": "", "state": "container-missing"}],
    )

    result = await load_bounded_comments(
        page,
        note_id="note-1",
        requested=1,
        total=1,
        normalize_comments=normalize,
    )

    assert result.comments == ()
    assert result.stop_reason == "container-missing"


@pytest.mark.asyncio
async def test_malformed_scroll_state_fails_closed() -> None:
    page = Page(
        reads=[{"risk_text": "", "comments": [comment("one")]}],
        scrolls=[{"risk_text": "", "state": "unknown"}],
    )

    with pytest.raises(PreconditionError, match="comment scroll state"):
        await load_bounded_comments(
            page,
            note_id="note-1",
            requested=2,
            total=2,
            normalize_comments=normalize,
        )
