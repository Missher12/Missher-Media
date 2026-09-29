"""Bounded ``best_effort`` orchestration shared by every platform and backend.

The runner owns the loop that the collectors must not write themselves:

* one finite batch budget per attempt, taken from :mod:`batch_policy`;
* dedup by the platform's native identity, so a repeated cursor, a pinned post,
  a virtual list that re-renders, or a late response never stores the same
  record twice;
* a stall counter that stops after N consecutive batches without new records;
* a total run deadline, so a budget pause can never wait past the authorized
  window;
* a cancellation check between every action;
* a checkpoint after every batch, so a stopped run still has a resumable prefix.

It never decides platform safety. Risk latches, cooldowns and the shared
collection lock stay outside this module and outside both browser backends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import Any

from .batch_policy import (
    BatchOutcome,
    BatchPolicy,
    decide_next,
)
from .contracts import (
    COUNT_MODE_BEST_EFFORT,
    COUNT_MODE_FIXED,
    STOP_REASON_BUDGET,
    STOP_REASON_CANCELLED,
    STOP_REASON_COUNT_REACHED,
    STOP_REASON_DEADLINE,
    STOP_REASON_ERROR,
    STOP_REASON_NATURAL_END,
    STOP_REASON_NO_NEW,
    STOP_REASON_RISK,
    STOP_REASON_TIMEOUT,
    STOP_REASON_UNSUPPORTED,
    TaskState,
)


class RiskStop(RuntimeError):
    """A platform risk signal stopped collection; never retried automatically."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RequestCancelled(RuntimeError):
    """The caller cancelled this run; verified prefixes are kept."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


#: Native identity keys per platform. X posts use ``tweet_id``, Weibo topic
#: participants and user homepages use ``uid``, and every backend-independent
#: record may fall back to the shared ``native_id`` projection.
_NATIVE_ID_KEYS: dict[str, tuple[str, ...]] = {
    "x": ("tweet_id", "author_id"),
    "weibo": ("mblog_id", "uid"),
    "bilibili": ("dynamic_id", "bvid"),
    "xhs": ("note_id",),
    "douyin": ("aweme_id",),
}


def target_identities(record: Mapping[str, Any]) -> tuple[str, ...]:
    values = [record.get("target_identity")]
    if isinstance(record.get("target_identities"), (list, tuple)):
        values.extend(record["target_identities"])
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def add_target_identity(record: dict[str, Any], identity: str) -> None:
    values = tuple(dict.fromkeys((*target_identities(record), identity)))
    record.setdefault("target_identity", identity)
    if len(values) > 1:
        record["target_identities"] = list(values)


def identity_of(record: Mapping[str, Any], platform: str) -> str | None:
    """Native dedup identity: platform plus record kind plus native id.

    A user and a post are different entities, so the kind is part of the key.
    ``native_id`` is the last resort so a record that carries a recognized native
    identity is never dropped just because the platform key list is incomplete.
    """

    kind = record.get("type")
    kind = kind if isinstance(kind, str) and kind else "post"
    suffix = ":" + str(record.get("topic") or record.get("target_identity") or "") + ":" + str(record.get("post_id") or "") if kind in {"topic_participant", "topic_participant_relation"} else ""
    keys = (*_NATIVE_ID_KEYS.get(platform, ()), "native_id")
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return f"{platform}:{kind}:{key}:{value}{suffix}"
        if isinstance(value, str) and value:
            return f"{platform}:{kind}:{key}:{value}{suffix}"
    return None


@dataclass(slots=True)
class BatchResult:
    """What one executed batch returned."""

    records: list[dict[str, Any]] = field(default_factory=list)
    pages: int = 0
    exhausted: bool = False
    empty: bool = False
    stop_reason: str | None = None


@dataclass(slots=True)
class BatchRequest:
    """One bounded batch handed to the platform executor."""

    batch_index: int
    remaining_budget: int | None
    page_budget: int
    record_budget: int
    exclude_ids: tuple[str, ...]
    seen_users: tuple[str, ...] = ()


#: A platform batch executor. It runs exactly one bounded batch and reports what
#: happened; it never loops, sleeps or retries on its own.
BatchExecutor = Callable[[BatchRequest], Awaitable[BatchResult]]


@dataclass(slots=True)
class RunOutcome:
    records: list[dict[str, Any]]
    state: TaskState
    batches: int
    deduplicated: int
    elapsed_seconds: float


class BestEffortRunner:
    """Drive one target to completion inside an explicit, finite budget."""

    def __init__(
        self,
        *,
        policy: BatchPolicy,
        count_mode: str,
        count: int = 0,
        per_target_budget: int | None = None,
        deadline_seconds: float = 900.0,
        cancel_check: Callable[[], bool] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        checkpoint: Callable[[TaskState, Sequence[Mapping[str, Any]]], None] | None = None,
        max_total: int | None = None,
    ) -> None:
        if count_mode not in {COUNT_MODE_FIXED, COUNT_MODE_BEST_EFFORT}:
            raise ValueError("unsupported count mode")
        if not isinstance(deadline_seconds, (int, float)) or deadline_seconds <= 0:
            raise ValueError("deadline must be a positive number of seconds")
        if max_total is not None and (
            isinstance(max_total, bool) or not isinstance(max_total, int) or max_total < 1
        ):
            raise ValueError("max_total must be a positive integer")
        self.policy = policy
        self.count_mode = count_mode
        self.count = count
        self.per_target_budget = per_target_budget
        self.deadline_seconds = float(deadline_seconds)
        self._cancel_check = cancel_check or (lambda: False)
        self._sleep = sleep or asyncio.sleep
        self._monotonic = monotonic
        self._checkpoint = checkpoint
        self._max_total = max_total

    @property
    def fixed_target(self) -> int | None:
        if self.count_mode == COUNT_MODE_FIXED:
            return self.count if self.count > 0 else None
        return None

    @property
    def total_budget(self) -> int | None:
        """Finite total record budget, or ``None`` for authorized ``best_effort``."""

        if self.count_mode == COUNT_MODE_FIXED:
            return self.count
        if self.per_target_budget is not None:
            return self.per_target_budget
        return self._max_total

    def _check_cancelled(self) -> None:
        if self._cancel_check():
            raise RequestCancelled("cancelled")

    async def run(
        self,
        state: TaskState,
        execute: BatchExecutor,
        *,
        initial: Sequence[Mapping[str, Any]] = (),
    ) -> RunOutcome:
        started = self._monotonic()
        state.started_at = state.started_at or _now()
        state.phase = "collecting"
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        def _register(items: Sequence[Mapping[str, Any]]) -> int:
            added = 0
            for item in items:
                key = identity_of(item, self.policy.platform)
                if key is None or key in seen:
                    continue
                if self.total_budget is not None and len(records) >= self.total_budget:
                    break
                seen.add(key)
                records.append(dict(item))
                added += 1
            return added

        _register(initial)
        total_budget = self.total_budget
        batches = 0
        stall = 0
        stop_reason: str | None = None
        for batch_index in range(self.policy.max_batches):
            self._check_cancelled()
            elapsed = self._monotonic() - started
            if elapsed >= self.deadline_seconds:
                stop_reason = STOP_REASON_DEADLINE
                break
            remaining_budget = (
                None if total_budget is None else max(0, total_budget - len(records))
            )
            if remaining_budget is not None and remaining_budget == 0:
                stop_reason = STOP_REASON_COUNT_REACHED
                break
            request = BatchRequest(
                batch_index=batch_index,
                remaining_budget=remaining_budget,
                page_budget=self.policy.batch_pages,
                record_budget=self.policy.batch_records,
                exclude_ids=tuple(sorted(seen)),
                seen_users=tuple(
                    sorted(
                        {
                            str(item.get("uid") or item.get("author_id"))
                            for item in records
                            if item.get("uid") or item.get("author_id")
                        }
                    )
                ),
            )
            try:
                result = await execute(request)
            except RiskStop as error:
                state.phase = "risk-stopped"
                state.stop_reason = STOP_REASON_RISK
                state.checkpoint = {"risk_code": error.code, "batches": batches}
                return self._finish(records, state, batches, started)
            except RequestCancelled:
                state.phase = "cancelled"
                state.stop_reason = STOP_REASON_CANCELLED
                return self._finish(records, state, batches, started)
            except TimeoutError:
                state.phase = "failed"
                state.stop_reason = STOP_REASON_TIMEOUT
                return self._finish(records, state, batches, started)
            except asyncio.CancelledError:
                state.phase = "cancelled"
                state.stop_reason = STOP_REASON_CANCELLED
                self._persist(state, records)
                raise
            except Exception:  # noqa: BLE001 - any executor failure stops this target
                state.phase = "failed"
                state.stop_reason = STOP_REASON_ERROR
                return self._finish(records, state, batches, started)
            batches += 1
            state.batches = batches
            if result.stop_reason == STOP_REASON_UNSUPPORTED:
                state.phase = "unsupported"
                state.stop_reason = STOP_REASON_UNSUPPORTED
                return self._finish(records, state, batches, started)
            # Record what the batch actually returned before reacting to a
            # cancellation observed during it: the verified prefix is evidence
            # and must survive a cancelled run.
            added = _register(result.records)
            state.pages += max(0, result.pages)
            stall = 0 if added else stall + 1
            state.posts = len(records)
            state.unique_posts = len(records)
            self._persist(state, records)
            if self._cancel_check():
                state.phase = "cancelled"
                state.stop_reason = STOP_REASON_CANCELLED
                return self._finish(records, state, batches, started)
            if result.stop_reason is not None:
                stop_reason = result.stop_reason
                break
            decision = decide_next(
                policy=self.policy,
                batch_index=batch_index,
                outcome=BatchOutcome(
                    added=added,
                    pages=result.pages,
                    exhausted=result.exhausted,
                    empty=result.empty or not result.records,
                ),
                total=len(records),
                elapsed_seconds=self._monotonic() - started,
                deadline_seconds=self.deadline_seconds,
                stall_count=stall,
                fixed_target=self.fixed_target,
            )
            if decision.stop:
                stop_reason = decision.reason
                break
            if decision.wait_seconds > 0:
                state.phase = "waiting"
                state.next_batch_at = _future(decision.wait_seconds)
                self._persist(state, records)
                try:
                    await self._sleep(decision.wait_seconds)
                except asyncio.CancelledError:
                    state.phase = "cancelled"
                    state.stop_reason = STOP_REASON_CANCELLED
                    self._persist(state, records)
                    raise
                state.next_batch_at = None
                if self._monotonic() - started >= self.deadline_seconds:
                    stop_reason = STOP_REASON_DEADLINE
                    break
        else:
            stop_reason = STOP_REASON_BUDGET
        if stop_reason is None:
            stop_reason = STOP_REASON_NATURAL_END
        state.phase = "complete" if stop_reason in {
            STOP_REASON_NATURAL_END,
            STOP_REASON_COUNT_REACHED,
        } else "cancelled" if stop_reason == STOP_REASON_CANCELLED else "partial"
        state.stop_reason = stop_reason
        return self._finish(records, state, batches, started)

    def _persist(self, state: TaskState, records: Sequence[Mapping[str, Any]]) -> None:
        if self._checkpoint is None:
            return
        self._checkpoint(state, records)

    def _finish(
        self,
        records: list[dict[str, Any]],
        state: TaskState,
        batches: int,
        started: float,
    ) -> RunOutcome:
        state.finished_at = _now()
        state.posts = len(records)
        state.unique_posts = len(records)
        state.batches = batches
        state.checkpoint = {
            **state.checkpoint,
            "batches": batches,
            "records": len(records),
            "stop_reason": state.stop_reason,
        }
        self._persist(state, records)
        return RunOutcome(
            records=records,
            state=state,
            batches=batches,
            deduplicated=len(records),
            elapsed_seconds=round(self._monotonic() - started, 3),
        )


def _future(seconds: float) -> str:
    return datetime.fromtimestamp(time.time() + seconds, tz=UTC).isoformat()


__all__ = [
    "BatchExecutor",
    "BatchRequest",
    "BatchResult",
    "BestEffortRunner",
    "RequestCancelled",
    "RiskStop",
    "RunOutcome",
    "identity_of",
]
