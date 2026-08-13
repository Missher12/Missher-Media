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
            isinstance(author, str)
            and author.strip()
            or isinstance(body, str)
            and body.strip()
        ):
            continue
        key = _comment_key(item)
        if key in seen:
            continue
        accumulated.append(dict(item))
        seen.add(key)


def _require_exact_detail(page: Any, note_id: str) -> None:
    if not matches_exact_detail_page(page, "xhs", note_id):
        raise PreconditionError("exact Xiaohongshu detail page is unavailable")


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
    target = (
        min(requested, total)
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0
        else requested
    )
    if target == 0:
        return XhsCommentLoadResult((), 0, "complete")

    _require_exact_detail(page, note_id)
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
        _require_exact_detail(page, note_id)
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
        _require_exact_detail(page, note_id)
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


__all__ = [
    "COMMENT_SCROLL_LIMIT",
    "COMMENT_SCROLL_WAIT_MS",
    "XhsCommentLoadResult",
    "XhsCommentRisk",
    "load_bounded_comments",
]
