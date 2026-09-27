"""Per-platform bounded batch policy for ``best_effort`` collection.

``best_effort`` means "as much as is actually collectable inside the authorized
window", never an unbounded loop. Every platform therefore has its own finite
batch budget, its own pause between batches, and its own stop reason. The
Xiaohongshu limits already enforced by :mod:`xhs_policy` are kept exactly as they
are; X and the other platforms get their own conservative numbers rather than
inheriting the XHS rule by accident.

The shared collection lock and any latched risk state live outside the backend,
so switching backend, runtime home or target cannot clear them.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import (
    COUNT_MODE_BEST_EFFORT,
    COUNT_MODE_FIXED,
    PLATFORM_SET,
    STOP_REASON_BUDGET,
    STOP_REASON_COUNT_REACHED,
    STOP_REASON_DEADLINE,
    STOP_REASON_EMPTY,
    STOP_REASON_NATURAL_END,
    STOP_REASON_NO_NEW,
)
from .xhs_policy import MAX_BATCH_NOTES, MAX_BATCH_PAGES, MIN_BATCH_INTERVAL_SECONDS


@dataclass(frozen=True, slots=True)
class BatchPolicy:
    """Finite single-batch and inter-batch budget for one platform."""

    platform: str
    batch_records: int
    batch_pages: int
    interval_seconds: float
    max_batches: int
    stall_limit: int = 2

    def __post_init__(self) -> None:
        if self.platform not in PLATFORM_SET:
            raise ValueError("unsupported platform")
        for value in (self.batch_records, self.batch_pages, self.max_batches, self.stall_limit):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("batch policy limits must be positive integers")
        if (
            isinstance(self.interval_seconds, bool)
            or not isinstance(self.interval_seconds, (int, float))
            or not math.isfinite(float(self.interval_seconds))
            or float(self.interval_seconds) < 0
        ):
            raise ValueError("batch interval must be a finite non-negative number")

    def to_json(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "batch_records": self.batch_records,
            "batch_pages": self.batch_pages,
            "interval_seconds": self.interval_seconds,
            "max_batches": self.max_batches,
            "stall_limit": self.stall_limit,
        }


#: Conservative per-platform starting budgets. These are engineering limits, not
#: platform safety thresholds, and they are not a total collection cap once the
#: user authorizes several batches inside the run deadline.
DEFAULT_POLICIES: dict[str, BatchPolicy] = {
    "xhs": BatchPolicy(
        platform="xhs",
        batch_records=MAX_BATCH_NOTES,
        batch_pages=MAX_BATCH_PAGES,
        interval_seconds=float(MIN_BATCH_INTERVAL_SECONDS),
        max_batches=4,
    ),
    "x": BatchPolicy(
        platform="x",
        batch_records=20,
        batch_pages=3,
        interval_seconds=120.0,
        max_batches=5,
    ),
    "weibo": BatchPolicy(
        platform="weibo",
        batch_records=20,
        batch_pages=3,
        interval_seconds=90.0,
        max_batches=5,
    ),
    "bilibili": BatchPolicy(
        platform="bilibili",
        batch_records=20,
        batch_pages=3,
        interval_seconds=60.0,
        max_batches=6,
    ),
    "douyin": BatchPolicy(
        platform="douyin",
        batch_records=20,
        batch_pages=3,
        interval_seconds=60.0,
        max_batches=6,
    ),
}


def policy_for(platform: str) -> BatchPolicy:
    policy = DEFAULT_POLICIES.get(platform)
    if policy is None:
        raise ValueError("unsupported platform")
    return policy


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """What one batch actually did."""

    added: int
    pages: int
    exhausted: bool = False
    empty: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.added, bool) or not isinstance(self.added, int) or self.added < 0:
            raise ValueError("batch added count must be a non-negative integer")
        if isinstance(self.pages, bool) or not isinstance(self.pages, int) or self.pages < 0:
            raise ValueError("batch page count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class StopDecision:
    stop: bool
    reason: str | None = None
    wait_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.stop and self.reason is None:
            raise ValueError("a stop decision requires a reason")
        if self.wait_seconds < 0:
            raise ValueError("wait seconds must be non-negative")


CONTINUE = StopDecision(stop=False)


def decide_next(
    *,
    policy: BatchPolicy,
    batch_index: int,
    outcome: BatchOutcome,
    total: int,
    elapsed_seconds: float,
    deadline_seconds: float,
    stall_count: int,
    fixed_target: int | None,
) -> StopDecision:
    """Decide whether another bounded batch may run.

    Order matters: an explicit completion is reported before a budget pause, and
    the run deadline always wins over a budget pause so the caller never waits
    past the authorized window.
    """

    if fixed_target is not None and total >= fixed_target:
        return StopDecision(stop=True, reason=STOP_REASON_COUNT_REACHED)
    if outcome.exhausted:
        return StopDecision(stop=True, reason=STOP_REASON_NATURAL_END)
    if outcome.empty and batch_index == 0:
        return StopDecision(stop=True, reason=STOP_REASON_EMPTY)
    if outcome.added == 0 and outcome.empty:
        return StopDecision(stop=True, reason=STOP_REASON_NATURAL_END)
    if stall_count >= policy.stall_limit:
        return StopDecision(stop=True, reason=STOP_REASON_NO_NEW)
    remaining = deadline_seconds - elapsed_seconds
    if remaining <= 0:
        return StopDecision(stop=True, reason=STOP_REASON_DEADLINE)
    if batch_index + 1 >= policy.max_batches:
        # The finite batch budget was used up. This is a pause, not "everything
        # was collected", and it is reported with its own reason.
        return StopDecision(stop=True, reason=STOP_REASON_BUDGET)
    if policy.interval_seconds <= 0:
        return CONTINUE
    # Waiting for the next compliant batch time is allowed inside the authorized
    # window, but the run never sleeps past its total deadline: the remaining
    # prefix and the resumption point are kept instead.
    if policy.interval_seconds > remaining:
        return StopDecision(stop=True, reason=STOP_REASON_DEADLINE)
    return StopDecision(stop=False, wait_seconds=policy.interval_seconds)


def requires_batches(count_mode: str) -> bool:
    return count_mode == COUNT_MODE_BEST_EFFORT


def is_batched(count_mode: str) -> bool:
    return count_mode in {COUNT_MODE_FIXED, COUNT_MODE_BEST_EFFORT}


def clamp_pages(policy: BatchPolicy, requested: int | None) -> int:
    if requested is None:
        return policy.batch_pages
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise ValueError("batch pages must be a positive integer")
    return min(requested, policy.batch_pages)


def clamp_records(policy: BatchPolicy, requested: int | None) -> int:
    if requested is None:
        return policy.batch_records
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise ValueError("batch records must be a positive integer")
    return min(requested, policy.batch_records)


__all__ = [
    "BatchOutcome",
    "BatchPolicy",
    "CONTINUE",
    "DEFAULT_POLICIES",
    "StopDecision",
    "clamp_pages",
    "clamp_records",
    "decide_next",
    "is_batched",
    "policy_for",
    "requires_batches",
]
