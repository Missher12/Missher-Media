# Media@Missher V15 Xiaohongshu Bounded Detail Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a one-click Xiaohongshu detail action budget and retrieve a requested visible comment slice with at most three low-frequency comment-container scrolls, while returning truthful partial evidence when bounded work is insufficient.

**Architecture:** Keep `XhsCollector` authoritative for exact-note response capture, record merging, screenshots, completion, and cleanup. Add a focused private `_xhs_detail_enrichment` module for exact-page guarding, bounded comment-container interaction, normalized deduplication, growth detection, and internal stop reasons; pass a Xiaohongshu-only no-stale-replay policy through the existing detail coordinator and BrowserSkill bridge without changing Bilibili defaults.

**Tech Stack:** Python 3.11+, asyncio, Playwright CDP, Tencent BrowserSkill CLI `0.1.10`/extension `0.1.6`, dataclasses, pytest, pytest-asyncio, pytest-socket, uv.

---

## Execution boundary

Work in `/Users/missher/Documents/Media@Missher` on the existing
`codex/media-missher-v15` branch. The worktree already contains reviewed but
uncommitted V15 hardening, so preserve every pre-existing change and inspect each
patch in context.

Do not install the source runtime, start a BrowserSkill session, run a real
platform collection, stage files, commit, tag, push, publish, or change the
private GitHub repository. Although the generic planning workflow recommends
frequent commits, the active project boundary requires uncommitted checkpoints
until the user explicitly authorizes release actions.

Read the approved design before implementation:

```bash
sed -n '1,380p' docs/superpowers/specs/2026-08-13-xhs-bounded-detail-enrichment-design.md
```

Never weaken exact `note_id` binding, the existing 5–15 second settle, challenge
checks, navigation authorization, sequential execution, output privacy, count or
page caps, platform timeout, or completed-prefix retention.

## File map

Create:

- `runtime/media_missher_runtime/platforms/_xhs_detail_enrichment.py` — private
  action limits, exact-page guard, comment observation, unique-container scroll,
  normalized accumulation, growth stop, and internal result/error types.
- `tests/test_runtime_xhs_detail_enrichment.py` — socket-free unit tests for all
  action-budget, completion, no-growth, container, exact-target, and risk paths.

Modify:

- `runtime/media_missher_runtime/browser_skill.py` — add a default-preserving
  `retry_stale_selector` policy to the marked-tab click.
- `runtime/media_missher_runtime/detail_open.py` — pass that policy through
  `DetailOpenCoordinator.click_exact`.
- `runtime/media_missher_runtime/platforms/xhs.py` — request no click replay,
  call the bounded loader, map comments to existing fields, transform risk, and
  remove the one-shot reader.
- `tests/test_runtime_browser_skill.py`, `tests/test_runtime_detail_open.py`,
  `tests/test_runtime_xhs.py` — prove the new seam, integration, cleanup, partial
  status, screenshot order, and unchanged defaults.
- `PROJECT_CONTEXT.md`, both skill `SKILL.md` files, and the active commands,
  validation, and troubleshooting references — document the bounded contract and
  dated offline evidence without claiming installed or live acceptance.

No public CLI, request model, adapter schema, output format, or validator code is
expected to change.

### Task 1: Add the Xiaohongshu no-replay seam

**Files:**

- Modify: `runtime/media_missher_runtime/browser_skill.py:285-355`
- Modify: `runtime/media_missher_runtime/detail_open.py:163-226`
- Test: `tests/test_runtime_browser_skill.py`
- Test: `tests/test_runtime_detail_open.py`

- [x] **Step 1: Write the failing bridge test**

Add beside the existing structured stale-selector retry test:

```python
@pytest.mark.asyncio
async def test_stale_click_is_not_replayed_when_policy_disables_retry() -> None:
    fake = FakeRunner(
        _happy_responses(
            click_results=[
                _json_result(
                    {"error": {"code": "stale-selector"}},
                    returncode=1,
                )
            ]
        )
    )
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(
            Page(),
            selector=TARGET_SELECTOR,
            retry_stale_selector=False,
        )

    assert captured.value.code == "bsk-transport"
    assert sum(command[0] == "snapshot" for command in fake.commands) == 1
    assert sum(command[0] == "click" for command in fake.commands) == 1
    assert any(command[:2] == ("tab", "return") for command in fake.commands)
```

- [x] **Step 2: Write the failing coordinator forwarding test**

Extend the fake `Bridge` in `tests/test_runtime_detail_open.py`:

```python
class Bridge:
    def __init__(self, action: Callable[[], None]) -> None:
        self.action = action
        self.selectors: list[str] = []
        self.titles: list[str] = []
        self.retry_policies: list[bool] = []

    async def click_marked_tab(
        self,
        page: Page,
        *,
        selector: str,
        retry_stale_selector: bool = True,
    ) -> None:
        self.selectors.append(selector)
        self.titles.append(await page.title())
        self.retry_policies.append(retry_stale_selector)
        self.action()
```

Add:

```python
@pytest.mark.asyncio
async def test_coordinator_forwards_disabled_stale_selector_retry() -> None:
    page = Page(
        "https://www.xiaohongshu.com/explore",
        detail_url="https://www.xiaohongshu.com/explore/note-123",
    )
    element = Element(page)
    bridge = Bridge(page.open_detail)

    result = await DetailOpenCoordinator(bridge=bridge).click_exact(
        page,
        element,
        platform="xhs",
        native_id="note-123",
        retry_stale_selector=False,
    )

    assert result is page
    assert bridge.retry_policies == [False]
    assert element.clicked == 0
```

Also add `assert bridge.retry_policies == [True]` to the existing default-assisted
test so Bilibili-compatible behavior stays locked.

- [x] **Step 3: Run the focused tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_browser_skill.py tests/test_runtime_detail_open.py
```

Expected: new calls fail because neither method accepts
`retry_stale_selector` yet.

- [x] **Step 4: Implement the bridge policy with the existing behavior as default**

Change the bridge signature:

```python
async def click_marked_tab(
    self,
    page: Any,
    *,
    selector: str,
    retry_stale_selector: bool = True,
) -> None:
    if not isinstance(retry_stale_selector, bool):
        raise BrowserSkillError("bsk-transport")
```

Keep all current lifecycle code and replace only the click retry condition:

```python
if (
    retry_stale_selector
    and click.returncode == 1
    and _is_stale_selector_result(click)
):
    await self._snapshot(session_id, tab_id)
    click = await self._run(*click_command)
```

The existing one-time snapshot retry remains because it does not issue a click.

- [x] **Step 5: Pass the policy through the coordinator**

Extend the signature and validate before marking an element:

```python
async def click_exact(
    self,
    page: Any,
    element: Any,
    *,
    platform: str,
    native_id: str,
    retry_stale_selector: bool = True,
) -> Any:
    if not isinstance(retry_stale_selector, bool):
        raise PreconditionError("invalid detail click policy")
```

Pass it only on the assisted branch:

```python
await self.bridge.click_marked_tab(
    page,
    selector=selector,
    retry_stale_selector=retry_stale_selector,
)
```

- [x] **Step 6: Run GREEN and checkpoint without staging**

Run the Step 3 command. Expected: both files pass, including the old default
retry and new no-replay cases. Then run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and no staged files.

### Task 2: Build the deep bounded-comment module

**Files:**

- Create: `runtime/media_missher_runtime/platforms/_xhs_detail_enrichment.py`
- Create: `tests/test_runtime_xhs_detail_enrichment.py`

- [x] **Step 1: Write the fake page and normalization fixture**

Create the test file with this surface:

```python
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
    reads: list[dict[str, Any]] = field(default_factory=list)
    scrolls: list[dict[str, Any]] = field(default_factory=list)
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


def comment(text: str, *, author: str = "A") -> dict[str, Any]:
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
```

- [x] **Step 2: Write failing completion and growth tests**

```python
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
```

- [x] **Step 3: Write failing deterministic-stop and risk tests**

Add table-driven tests for all three container states:

```python
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
```

Add the remaining cases as executable tests rather than prose placeholders:

```python
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
        reads=[
            {
                "risk_text": "",
                "comments": [{"author": None, "text": None, "date": "today", "liked": "1"}],
            }
        ],
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
        scrolls=[
            {"risk_text": "challenge-selector", "state": None}
            if risk_location == "scroll"
            else {"risk_text": "", "state": "scrolled"}
        ] if risk_location != "initial" else [],
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
async def test_detail_url_change_before_second_scroll_fails_closed() -> None:
    class ChangingPage(Page):
        async def wait_for_timeout(self, milliseconds: int) -> None:
            await super().wait_for_timeout(milliseconds)
            self.url = "https://www.xiaohongshu.com/explore/other"

    page = ChangingPage(
        reads=[
            {"risk_text": "", "comments": [comment("one")]},
            {"risk_text": "", "comments": [comment("one"), comment("two")]},
        ],
        scrolls=[{"risk_text": "", "state": "scrolled"}],
    )
    with pytest.raises(PreconditionError, match="exact Xiaohongshu detail"):
        await load_bounded_comments(
            page,
            note_id="note-1",
            requested=3,
            total=3,
            normalize_comments=normalize,
        )
    assert sum("COMMENT_SCROLL" in script for script in page.evaluations) == 1


@pytest.mark.asyncio
async def test_malformed_comment_sequence_is_empty() -> None:
    page = Page(
        reads=[{"risk_text": "", "comments": "not-a-sequence"}],
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
```

- [x] **Step 4: Run the new test file and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_xhs_detail_enrichment.py
```

Expected: import failure for the private module.

- [x] **Step 5: Implement stable result types and limits**

Create the module with:

```python
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..browser import PreconditionError
from ..detail_open import matches_exact_detail_page


COMMENT_SCROLL_LIMIT = 3
COMMENT_SCROLL_WAIT_MS = 1_500

CommentStopReason = Literal[
    "complete",
    "not-requested",
    "container-missing",
    "container-ambiguous",
    "container-not-scrollable",
    "no-growth",
    "budget-exhausted",
]
CommentNormalizer = Callable[[Sequence[Any], int], list[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class XhsCommentLoadResult:
    comments: tuple[dict[str, Any], ...]
    scrolls: int
    stop_reason: CommentStopReason

    @property
    def comments_fetched(self) -> int:
        return len(self.comments)


class XhsCommentRisk(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
```

Export only the two constants, `XhsCommentLoadResult`, `XhsCommentRisk`, and
`load_bounded_comments` with:

```python
__all__ = [
    "COMMENT_SCROLL_LIMIT",
    "COMMENT_SCROLL_WAIT_MS",
    "XhsCommentLoadResult",
    "XhsCommentRisk",
    "load_bounded_comments",
]
```

- [x] **Step 6: Implement exact risk-safe DOM scripts**

Use these complete constants:

```python
_VISIBLE_AND_RISK = r"""
    const visible = (node) => {
        if (!node || !node.isConnected) return false;
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && Number(style.opacity || '1') !== 0
            && rect.width > 0 && rect.height > 0;
    };
    const body = document.body?.innerText || '';
    const challenge = document.querySelector(
        '.geetest_panel, .geetest_holder, iframe[src*="captcha"], [class*="captcha"]'
    );
    const phrases = ['请完成验证','访问受限','请求过于频繁','账号异常','风控','安全验证','验证码'];
    const risk_text = challenge
        ? 'challenge-selector'
        : (phrases.find((word) => body.includes(word)) || '');
"""

_READ_COMMENTS_SCRIPT = (
    r"""(limit) => {
    /* MEDIA_MISSHER_XHS_COMMENT_READ */
"""
    + _VISIBLE_AND_RISK
    + r"""
    const comments = Array.from(document.querySelectorAll(
        '.comments-container .comment-item, .comments-el .comment-item'
    ))
        .filter(visible)
        .slice(0, limit)
        .map((item) => ({
            author: item.querySelector('.author .name')?.textContent || null,
            text: item.querySelector('.content .note-text')?.textContent || null,
            date: item.querySelector('.info .date')?.textContent || null,
            liked: item.querySelector('.interactions .like .count')?.textContent || null,
        }));
    return {risk_text, comments};
}"""
)

_SCROLL_COMMENTS_SCRIPT = (
    r"""() => {
    /* MEDIA_MISSHER_XHS_COMMENT_SCROLL */
"""
    + _VISIBLE_AND_RISK
    + r"""
    if (risk_text) return {risk_text, state: null};
    const candidates = Array.from(
        document.querySelectorAll('.comments-container, .comments-el')
    ).filter(visible);
    if (candidates.length === 0) {
        return {risk_text: '', state: 'container-missing'};
    }
    if (candidates.length !== 1) {
        return {risk_text: '', state: 'container-ambiguous'};
    }
    const container = candidates[0];
    if (container.scrollHeight <= container.clientHeight) {
        return {risk_text: '', state: 'container-not-scrollable'};
    }
    container.scrollBy({top: container.clientHeight, left: 0, behavior: 'auto'});
    return {risk_text: '', state: 'scrolled'};
}"""
)
```

The complete scripts must define `visible(node)` as connected, CSS-visible, and
positive-geometry. They must not use `window.scrollTo`, document scrolling,
`.click()`, links, cookies, browser storage, tokens, or request payloads.

- [x] **Step 7: Implement normalized accumulation and bounded control flow**

Use these guards and helpers:

```python
def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return (
        value
        if isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        else ()
    )


def _raise_for_risk(value: object) -> None:
    reason = _mapping(value).get("risk_text")
    if isinstance(reason, str) and reason.strip():
        raise XhsCommentRisk(reason.strip())


def _comment_key(item: Mapping[str, Any]) -> tuple[object, ...]:
    def text(value: object) -> str:
        return value.strip().casefold() if isinstance(value, str) else ""

    liked = item.get("liked")
    return (
        text(item.get("author")),
        text(item.get("text")),
        text(item.get("date")),
        liked if isinstance(liked, int) and not isinstance(liked, bool) else None,
    )


def _merge_comments(
    accumulated: list[dict[str, Any]],
    observed: Sequence[Any],
    *,
    target: int,
    normalize_comments: CommentNormalizer,
) -> None:
    seen = {_comment_key(item) for item in accumulated}
    for item in normalize_comments(observed, target):
        if len(accumulated) >= target:
            return
        author = item.get("author")
        body = item.get("text")
        if not (
            isinstance(author, str) and author.strip()
            or isinstance(body, str) and body.strip()
        ):
            continue
        key = _comment_key(item)
        if key in seen:
            continue
        accumulated.append(dict(item))
        seen.add(key)
```

Implement the loader with the exact target checked before the first read and
every scroll:

```python
async def load_bounded_comments(
    page: Any,
    *,
    note_id: str,
    requested: int,
    total: int | None,
    normalize_comments: CommentNormalizer,
) -> XhsCommentLoadResult:
    if requested <= 0:
        return XhsCommentLoadResult((), 0, "not-requested")
    if not matches_exact_detail_page(page, "xhs", note_id):
        raise PreconditionError("exact Xiaohongshu detail page is unavailable")
    target = (
        min(requested, total)
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0
        else requested
    )
    if target == 0:
        return XhsCommentLoadResult((), 0, "complete")

    observation = await page.evaluate(_READ_COMMENTS_SCRIPT, target)
    _raise_for_risk(observation)
    accumulated: list[dict[str, Any]] = []
    _merge_comments(
        accumulated,
        _sequence(_mapping(observation).get("comments")),
        target=target,
        normalize_comments=normalize_comments,
    )
    if len(accumulated) >= target:
        return XhsCommentLoadResult(tuple(accumulated), 0, "complete")

    scrolls = 0
    for _ in range(COMMENT_SCROLL_LIMIT):
        if not matches_exact_detail_page(page, "xhs", note_id):
            raise PreconditionError("exact Xiaohongshu detail page is unavailable")
        scrolled = await page.evaluate(_SCROLL_COMMENTS_SCRIPT)
        _raise_for_risk(scrolled)
        state = _mapping(scrolled).get("state")
        if state == "container-missing":
            return XhsCommentLoadResult(
                tuple(accumulated), scrolls, "container-missing"
            )
        if state == "container-ambiguous":
            return XhsCommentLoadResult(
                tuple(accumulated), scrolls, "container-ambiguous"
            )
        if state == "container-not-scrollable":
            return XhsCommentLoadResult(
                tuple(accumulated), scrolls, "container-not-scrollable"
            )
        if state != "scrolled":
            raise PreconditionError("Xiaohongshu comment scroll state is invalid")
        scrolls += 1
        await page.wait_for_timeout(COMMENT_SCROLL_WAIT_MS)
        observation = await page.evaluate(_READ_COMMENTS_SCRIPT, target)
        _raise_for_risk(observation)
        prior_count = len(accumulated)
        _merge_comments(
            accumulated,
            _sequence(_mapping(observation).get("comments")),
            target=target,
            normalize_comments=normalize_comments,
        )
        if len(accumulated) >= target:
            return XhsCommentLoadResult(tuple(accumulated), scrolls, "complete")
        if len(accumulated) == prior_count:
            return XhsCommentLoadResult(tuple(accumulated), scrolls, "no-growth")
    return XhsCommentLoadResult(tuple(accumulated), scrolls, "budget-exhausted")
```

- [x] **Step 8: Run GREEN and inspect the action scripts**

Run the Step 4 command. Expected: all new tests pass. Then run:

```bash
rg -n "window\.scrollTo|documentElement.*scroll|\.click\(|cookie|localStorage|sessionStorage|xsec" \
  runtime/media_missher_runtime/platforms/_xhs_detail_enrichment.py
git diff --check
```

Expected: no forbidden-script matches and no whitespace errors.

### Task 3: Integrate the budget into `XhsCollector`

**Files:**

- Modify: `runtime/media_missher_runtime/platforms/xhs.py:20-32,235-383,1424-1433,1604-1620`
- Modify: `tests/test_runtime_xhs.py`
- Test: `tests/test_runtime_xhs_detail_enrichment.py`

- [x] **Step 1: Update fake coordinator contracts and write a failing policy assertion**

Add `retry_stale_selector: bool = True` to every fake `click_exact` method in
`tests/test_runtime_xhs.py`. Extend `AssistedCoordinator` with:

```python
retry_policies: list[bool] = field(default_factory=list)
```

Record the argument inside its method and add this assertion to an existing
assisted Xiaohongshu detail test:

```python
self.retry_policies.append(retry_stale_selector)
# after collection
assert coordinator.retry_policies == [False]
```

Expected RED: production still uses the coordinator default `True`.

- [x] **Step 2: Write the failing collector mapping test**

```python
def test_bounded_comment_shortfall_maps_existing_fields_and_stays_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.media_missher_runtime.platforms import xhs
    from runtime.media_missher_runtime.platforms._xhs_detail_enrichment import (
        XhsCommentLoadResult,
    )

    calls: list[tuple[str, int, int | None]] = []

    async def fake_loader(
        _page: Page,
        *,
        note_id: str,
        requested: int,
        total: int | None,
        normalize_comments: Any,
    ) -> XhsCommentLoadResult:
        assert callable(normalize_comments)
        calls.append((note_id, requested, total))
        return XhsCommentLoadResult(
            ({"author": "A", "text": "one", "date": "today", "liked": 1},),
            1,
            "no-growth",
        )

    monkeypatch.setattr(xhs, "load_bounded_comments", fake_loader)
    page = Page(
        responses=[creator_response(note("one")), detail_response("one")],
        cards=[{"note_id": "one"}],
    )
    record = run(
        xhs.collect_creator(
            CollectionRequest(
                platform="xhs",
                count=1,
                uid="u",
                complete=True,
                comment_limit=2,
            ),
            Browser(page),
        )
    )[0]

    assert calls == [("one", 2, 2)]
    assert record["comments_requested"] == 2
    assert record["comments_fetched"] == 1
    assert record["comments_detail"] == record["comments_data"]
    assert "comments_data" in record["missing_fields"]
    assert record["complete"] is False
```

- [x] **Step 3: Write failing risk and screenshot-ordering tests**

Add these complete integration tests:

```python
def test_comment_risk_stops_before_screenshot_and_cleanup_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.media_missher_runtime.platforms import xhs
    from runtime.media_missher_runtime.platforms._xhs_detail_enrichment import (
        XhsCommentRisk,
    )

    async def risky_loader(*_args: Any, **_kwargs: Any) -> Any:
        raise XhsCommentRisk("challenge-selector")

    monkeypatch.setattr(xhs, "load_bounded_comments", risky_loader)
    screenshots = Screenshots()
    page = Page(
        responses=[creator_response(note("one")), detail_response("one")],
        cards=[{"note_id": "one"}],
    )
    request = CollectionRequest(
        platform="xhs",
        count=1,
        uid="u",
        complete=True,
        comment_limit=1,
        screenshot_mode="opened",
    )

    with pytest.raises(xhs.CollectionStopped, match="challenge-selector"):
        run(xhs.collect_creator(request, Browser(page, screenshots=screenshots)))

    assert screenshots.captures == []
    assert page.modal_visible is False


def test_comments_finish_before_one_screenshot_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.media_missher_runtime.platforms import xhs
    from runtime.media_missher_runtime.platforms._xhs_detail_enrichment import (
        XhsCommentLoadResult,
    )

    events: list[str] = []

    async def ordered_loader(*_args: Any, **_kwargs: Any) -> XhsCommentLoadResult:
        events.append("comments")
        return XhsCommentLoadResult(
            ({"author": "A", "text": "one", "date": "today", "liked": 1},),
            0,
            "complete",
        )

    class OrderedScreenshots(Screenshots):
        async def capture(self, *args: Any, **kwargs: Any) -> ScreenshotArtifact:
            events.append("screenshot")
            return await super().capture(*args, **kwargs)

    monkeypatch.setattr(xhs, "load_bounded_comments", ordered_loader)
    screenshots = OrderedScreenshots()
    page = Page(
        responses=[creator_response(note("one")), detail_response("one")],
        cards=[{"note_id": "one"}],
    )
    record = run(
        xhs.collect_creator(
            CollectionRequest(
                platform="xhs",
                count=1,
                uid="u",
                complete=True,
                comment_limit=1,
                screenshot_mode="opened",
            ),
            Browser(page, screenshots=screenshots),
        )
    )[0]

    assert events == ["comments", "screenshot"]
    assert screenshots.captures == [("xhs", "one", "opened")]
    assert record["screenshot_status"] == "complete"
```

- [x] **Step 4: Run focused XHS tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_xhs_detail_enrichment.py tests/test_runtime_xhs.py
```

Expected: failures for the default retry policy and missing loader integration.

- [x] **Step 5: Integrate the no-replay click and bounded loader**

Import:

```python
from ._xhs_detail_enrichment import XhsCommentRisk, load_bounded_comments
```

Change only the Xiaohongshu coordinator call:

```python
detail_page = await coordinator.click_exact(
    page,
    click_target,
    platform="xhs",
    native_id=note_id,
    retry_stale_selector=False,
)
```

Replace the one-shot comment block with:

```python
if (
    completion_required
    and self.request.comment_limit > 0
    and record["detail_completed"]
):
    record["comments_requested"] = self.request.comment_limit
    total_comments = record.get("comments")
    if not (
        isinstance(total_comments, int)
        and not isinstance(total_comments, bool)
        and total_comments >= 0
    ):
        total_comments = None
    try:
        comment_result = await load_bounded_comments(
            detail_page,
            note_id=note_id,
            requested=self.request.comment_limit,
            total=total_comments,
            normalize_comments=_safe_comments,
        )
    except XhsCommentRisk as error:
        raise CollectionStopped(error.reason) from error
    comments_data = list(comment_result.comments)
    record["comments_data"] = comments_data
    record["comments_detail"] = comments_data
    record["comments_fetched"] = comment_result.comments_fetched
```

Do not publish `stop_reason` or scroll counts. Remove `_read_comments` after all
references are gone. Keep screenshot capture immediately after this block.

- [x] **Step 6: Run focused GREEN and exact regression subsets**

Run the Step 4 command, then:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_browser_skill.py tests/test_runtime_detail_open.py \
  tests/test_runtime_screenshots.py tests/test_runtime_xhs_detail_enrichment.py \
  tests/test_runtime_xhs.py tests/test_runtime_bilibili_production.py \
  tests/test_runtime_cli.py tests/test_runner.py tests/test_validation.py
```

Expected: all selected tests pass, Bilibili default replay remains unchanged, and
the adapter accepts the unchanged record schema.

- [x] **Step 7: Check module depth and patch locality**

```bash
rg -n "_read_comments|load_bounded_comments|retry_stale_selector" runtime tests
git diff --stat
git diff --check
```

Expected: no `_read_comments`, one production loader call from XHS, an explicit
`retry_stale_selector=False` on XHS, no unrelated collector changes, and no
whitespace errors.

### Task 4: Document the contract without expanding the schema

**Files:**

- Modify: `PROJECT_CONTEXT.md`
- Modify: `media-missher/SKILL.md`
- Modify: `openclaw-media-missher/SKILL.md`
- Modify: `media-missher/references/commands.md`
- Modify: `media-missher/references/validation.md`
- Modify: `media-missher/references/troubleshooting.md`
- Test: `tests/test_packaging.py`
- Test: `tests/test_openclaw_packaging.py`
- Test: `tests/test_active_residuals.py`

- [x] **Step 1: Write failing documentation assertions**

Add narrow assertions against the active commands and validation references:

```python
assert "at most three" in commands.lower()
assert "comment container" in commands.lower()
assert "does not refresh or reopen" in commands.lower()
assert "1,500" in commands
assert "partial" in validation.lower()
```

Assert both skill packages retain risk-stop/no-retry guidance and mention at most
one Xiaohongshu detail open. Do not expose private class names in user docs.

- [x] **Step 2: Run documentation tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_packaging.py tests/test_openclaw_packaging.py tests/test_active_residuals.py
```

Expected: the new bounded-action assertions fail.

- [x] **Step 3: Update operational documentation**

Express this contract without claiming anti-detection:

```text
For each exact Xiaohongshu detail, Media@Missher issues at most one click command.
When a requested comment slice is short, it scrolls only the unique visible
comment container, at most three times, waiting 1,500 ms after each scroll. It
stops on enough comments, missing or ambiguous container, non-scrollability, no
growth, exhausted budget, or any risk signal. It does not refresh or reopen the
detail. A non-risk shortfall remains partial evidence; a risk signal stops the run
without retry or screenshot.
```

In `PROJECT_CONTEXT.md`, describe this as unreleased source behavior. Do not call
it installed or live-tested.

- [x] **Step 4: Run documentation GREEN and residual checks**

Run the Step 2 command, then:

```bash
python3 tools/scan_active_residuals.py --root .
git diff --check
```

Expected: tests pass, zero residual findings, and no whitespace errors.

### Task 5: Run complete offline acceptance and report exact evidence

**Files:**

- Modify after actual results only: `PROJECT_CONTEXT.md`
- Inspect: every file in the final diff

- [x] **Step 1: Run the complete sockets-disabled suite**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket
```

Expected: zero failures and zero unexpected skips. Record the exact pass count
and warnings; do not reuse the earlier `886 passed` count.

- [x] **Step 2: Compile every Python source in memory**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path

roots = (
    Path("runtime"),
    Path("media-missher"),
    Path("openclaw-media-missher"),
    Path("tests"),
    Path("tools"),
)
files = sorted(
    path
    for root in roots
    for path in root.rglob("*.py")
    if "__pycache__" not in path.parts
)
for path in files:
    compile(path.read_bytes(), str(path), "exec")
print(f"compiled={len(files)}")
PY
```

Expected: exit `0`; record the exact count.

- [x] **Step 3: Run all five entrypoint help checks**

```bash
for script in scrape_all.py scrape_bilibili.py scrape_xhs.py scrape_douyin.py scrape_weibo.py; do
  PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
    --with-requirements runtime/requirements.lock \
    python "runtime/scripts/$script" --help >/dev/null || exit 1
done
```

Expected: five successful exits and no navigation or collection.

- [x] **Step 4: Run packaging, validator, residual, and diff gates**

```bash
python3 tools/scan_active_residuals.py --root .
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py media-missher
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py openclaw-media-missher
python3 tools/install_media_missher.py --version
git diff --check
git status --short
```

Expected: zero residual findings, both skill packages valid, installer version
`15.0.0`, no whitespace errors, and all changes remain unstaged.

- [x] **Step 5: Run only installed non-live preflight**

```bash
python3 media-missher/scripts/preflight.py --json
```

Expected: prior installed V15 health only. This must be reported as not containing
or validating the uninstalled source diff.

- [x] **Step 6: Record evidence and review the final diff**

Update `PROJECT_CONTEXT.md` with actual counts and this exact boundary:

```text
No real-platform collection, BrowserSkill session, installation, staging,
commit, tag, push, or publication was performed. Installed V15 still predates
this source hardening.
```

Review:

```bash
git diff -- runtime/media_missher_runtime/browser_skill.py \
  runtime/media_missher_runtime/detail_open.py \
  runtime/media_missher_runtime/platforms/_xhs_detail_enrichment.py \
  runtime/media_missher_runtime/platforms/xhs.py
git diff -- tests/test_runtime_browser_skill.py \
  tests/test_runtime_detail_open.py \
  tests/test_runtime_xhs_detail_enrichment.py \
  tests/test_runtime_xhs.py
git diff -- PROJECT_CONTEXT.md media-missher openclaw-media-missher
```

Expected: each change maps to the approved design, public schema is unchanged,
Bilibili defaults remain intact, and no unrelated user change is overwritten.

## Final evidence checklist

- [x] XHS assisted click passes `retry_stale_selector=False`.
- [x] Generic/Bilibili default stale-selector behavior is unchanged.
- [x] Exact target guard runs before the first comment read and every scroll.
- [x] Only the unique visible comment container is scrolled.
- [x] The loader performs zero to three scrolls and waits exactly 1,500 ms after
  each successful scroll.
- [x] All completion, container, no-growth, budget, malformed-state, target, and
  risk branches have socket-free tests.
- [x] Risk stops before screenshot and is never retried.
- [x] Comment shortfall stays partial through the existing `comments_data` rule.
- [x] Screenshot remains one collector request after comment enrichment.
- [x] No public CLI, request, adapter, or output-schema expansion occurred.
- [x] Full offline and non-live gates have current exact counts.
- [x] No real collection, BrowserSkill session, install, stage, commit, tag, push,
  or publication occurred.
