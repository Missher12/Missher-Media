"""A backend-agnostic runner for one frozen :class:`CollectionPlan`.

The runner owns the part every platform and every backend shares:

* sequential, one-target-at-a-time execution, because one run has exactly one
  browser owner;
* the difference between ``fixed`` (one bounded batch that respects the count)
  and ``best_effort`` (as many bounded batches as the platform policy, the run
  deadline and the per-target budget allow);
* a risk stop that ends the **whole** run, so no later target is started after a
  platform risk signal;
* per-run user deduplication: one user homepage is visited once per run, even
  when several topic tasks discover the same UID;
* a checkpoint after every batch, so a stopped run still owns a verified prefix;
* cancellation that keeps the verified prefix.

Nothing here opens a browser, shells out or imports Playwright. The caller
injects ``execute_task``; the CLI supplies the real one, tests supply fakes, and
a missing one resolves to a per-mode default that raises
:class:`~media_missher_runtime.backends.PreconditionLikeError` with the fixed
code ``plan-executor-missing`` instead of pretending something was collected.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import Any

from .backends import PreconditionLikeError
from .batch_policy import BatchPolicy, policy_for
from .best_effort import (
    BatchRequest,
    BatchResult,
    BestEffortRunner,
    RequestCancelled,
    RiskStop,
    identity_of,
)
from .capabilities import evidence_level
from .contracts import (
    COUNT_MODE_BEST_EFFORT,
    COUNT_MODE_FIXED,
    RECORD_KIND_POSTS,
    SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    STOP_REASON_BUDGET,
    STOP_REASON_CANCELLED,
    STOP_REASON_COUNT_REACHED,
    STOP_REASON_DEADLINE,
    STOP_REASON_ERROR,
    STOP_REASON_NATURAL_END,
    STOP_REASON_RISK,
    STOP_REASON_TIMEOUT,
    STOP_REASON_UNSUPPORTED,
    STOP_REASONS,
    TASK_MODES,
    CollectionPlan,
    RunManifest,
    Target,
    TaskState,
)
from .exporting import record_kind


#: Reason recorded on every target that never started because an earlier target
#: latched a platform risk signal.
PRIOR_RISK_STOP = "prior-risk-stop"
#: Fixed code used when no executor was injected for a mode.
MISSING_EXECUTOR = "plan-executor-missing"
#: Fixed code used when an executor returns something that is not a TaskOutcome.
EXECUTOR_CONTRACT = "plan-executor-contract"
#: Metadata fields merged when two tasks observe the same user UID.
_USER_LIST_FIELDS = ("topics", "topic_container_ids", "post_ids")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _record_identity(record: Mapping[str, Any], platform: str) -> str | None:
    """Per-run dedup identity for one record, or ``None`` when it has none."""

    key = identity_of(record, platform)
    if key is not None:
        return key
    kind = record.get("type")
    kind = kind if isinstance(kind, str) and kind else "record"
    for name in ("uid", "author_id", "native_id", "id"):
        value = record.get(name)
        if isinstance(value, str) and value:
            return f"{platform}:{kind}:{name}:{value}"
        if isinstance(value, int) and not isinstance(value, bool):
            return f"{platform}:{kind}:{name}:{value}"
    return None


def _user_identity(record: Mapping[str, Any]) -> str | None:
    for name in ("uid", "author_id", "native_id"):
        value = record.get(name)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _merge_user(existing: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    """Keep one profile per UID while preserving every topic relation."""

    for name in _USER_LIST_FIELDS:
        current = existing.get(name)
        extra = incoming.get(name)
        if not isinstance(extra, list):
            continue
        merged = list(current) if isinstance(current, list) else []
        for item in extra:
            if item not in merged:
                merged.append(item)
        existing[name] = merged
    stamp = incoming.get("last_observed_at") or incoming.get("observed_at")
    if isinstance(stamp, str) and stamp:
        previous = existing.get("last_observed_at")
        if not isinstance(previous, str) or stamp > previous:
            existing["last_observed_at"] = stamp


@dataclass(slots=True)
class TaskContext:
    """Everything one bounded batch is allowed to know about its target.

    ``budget`` is what this batch may still collect (``None`` when the plan
    authorized unbounded ``best_effort``); ``target_budget`` is the plan's
    allowance for the whole target. ``excluded_ids`` are per-run dedup
    identities, never platform identifiers or page text.
    """

    target: Target
    task_index: int
    task_total: int
    count_mode: str
    count: int
    budget: int | None
    deadline_seconds: float
    policy: BatchPolicy
    backend: str
    evidence_level: str
    excluded_ids: tuple[str, ...] = ()
    known_user_ids: tuple[str, ...] = ()
    checkpoint: Callable[[object, Sequence[Mapping[str, Any]]], None] | None = None
    batch_index: int = 0
    target_budget: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, Target):
            raise ValueError("task context requires a target")
        if self.count_mode not in {COUNT_MODE_FIXED, COUNT_MODE_BEST_EFFORT}:
            raise ValueError("unsupported count mode")
        if not isinstance(self.policy, BatchPolicy):
            raise ValueError("task context requires a batch policy")

    def to_json(self) -> dict[str, Any]:
        return {
            "target": self.target.to_json(),
            "target_identity": self.target.identity,
            "task_index": self.task_index,
            "task_total": self.task_total,
            "batch_index": self.batch_index,
            "count_mode": self.count_mode,
            "count": self.count,
            "budget": self.budget,
            "target_budget": self.target_budget,
            "deadline_seconds": self.deadline_seconds,
            "backend": self.backend,
            "evidence_level": self.evidence_level,
            "excluded_ids": list(self.excluded_ids),
            "known_user_ids": list(self.known_user_ids),
            "policy": self.policy.to_json(),
        }


@dataclass(slots=True)
class TaskOutcome:
    """What one bounded batch really produced."""

    records: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    exhausted: bool = False
    pages: int = 0
    users: list[dict[str, Any]] = field(default_factory=list)
    risk_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.records, list) or not all(
            isinstance(item, dict) for item in self.records
        ):
            raise ValueError("task outcome records must be a list of objects")
        if not isinstance(self.users, list) or not all(
            isinstance(item, dict) for item in self.users
        ):
            raise ValueError("task outcome users must be a list of objects")
        if isinstance(self.pages, bool) or not isinstance(self.pages, int) or self.pages < 0:
            raise ValueError("task outcome pages must be a non-negative integer")
        if self.stop_reason is not None and self.stop_reason not in STOP_REASONS:
            raise ValueError("unsupported task stop reason")
        if self.risk_code is not None and not isinstance(self.risk_code, str):
            raise ValueError("risk code must be a string")

    def to_json(self) -> dict[str, Any]:
        return {
            "records": len(self.records),
            "users": len(self.users),
            "pages": self.pages,
            "exhausted": bool(self.exhausted),
            "stop_reason": self.stop_reason,
            "risk_code": self.risk_code,
        }


TaskExecutor = Callable[[Target, TaskContext], Awaitable[TaskOutcome]]


async def missing_executor(target: Target, context: TaskContext) -> TaskOutcome:
    """The per-mode default: refuse to invent a collection path."""

    raise PreconditionLikeError(MISSING_EXECUTOR)


#: One default per plan mode. All of them refuse with the same fixed code; the
#: mapping exists so a mode-specific executor can be added without a branch.
DEFAULT_EXECUTORS: dict[str, TaskExecutor] = {
    mode: missing_executor for mode in TASK_MODES
}


@dataclass(slots=True)
class RunSummary:
    """The run-level result the caller reports, checkpoints and exports."""

    backend: str
    plan: CollectionPlan
    status: str
    started_at: str
    finished_at: str
    observed_at: str
    stop_reason: str | None
    resumable: bool
    tasks: list[dict[str, Any]]
    counts: dict[str, Any]
    record_kinds: dict[str, int]
    records: list[dict[str, Any]] = field(default_factory=list)
    users: list[dict[str, Any]] = field(default_factory=list)
    risk_code: str | None = None
    elapsed_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "backend": self.backend,
            "plan": self.plan.to_json(),
            "tasks": [dict(item) for item in self.tasks],
            "counts": dict(self.counts),
            "record_kinds": dict(self.record_kinds),
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "observed_at": self.observed_at,
            "stop_reason": self.stop_reason,
            "resumable": bool(self.resumable),
        }

    def all_records(self) -> list[dict[str, Any]]:
        """Posts plus user profiles, in discovery order."""

        return [*self.records, *self.users]

    def build_manifest(
        self, run_id: str, evidence_paths: Sequence[str] = ()
    ) -> RunManifest:
        return build_run_manifest(self, run_id, evidence_paths)


#: ``PlanRunner.run`` returns a :class:`RunSummary`; the alias exists so callers
#: can annotate against the outcome shape instead of the concrete class.
RunOutcomeLike = RunSummary


def build_run_manifest(
    summary: RunSummary, run_id: str, evidence_paths: Sequence[str] = ()
) -> RunManifest:
    """Validate and freeze the run-level manifest for one finished run."""

    if not isinstance(summary, RunSummary):
        raise ValueError("run manifest requires a run summary")
    return RunManifest(
        run_id=run_id,
        schema_version=MANIFEST_SCHEMA_VERSION,
        backend=summary.backend,
        status=summary.status,
        plan=summary.plan,
        tasks=tuple(dict(item) for item in summary.tasks),
        counts={
            key: value
            for key, value in summary.counts.items()
            if isinstance(value, int) and not isinstance(value, bool)
        },
        record_kinds={key: int(value) for key, value in summary.record_kinds.items()},
        evidence_paths=tuple(str(item) for item in evidence_paths),
        observed_at=summary.observed_at,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
    )


class PlanRunner:
    """Run one plan, sequentially, with everything injected."""

    def __init__(
        self,
        plan: CollectionPlan,
        *,
        execute_task: TaskExecutor | None = None,
        cancel_check: Callable[[], bool] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], str] | None = None,
        checkpoint: Callable[[TaskState, Sequence[Mapping[str, Any]]], None] | None = None,
        initial_records: Sequence[Mapping[str, Any]] = (),
        deadline_started_at: float | None = None,
    ) -> None:
        if not isinstance(plan, CollectionPlan):
            raise ValueError("plan runner requires a collection plan")
        if execute_task is not None and not callable(execute_task):
            raise ValueError("execute_task must be callable")
        if checkpoint is not None and not callable(checkpoint):
            raise ValueError("checkpoint must be callable")
        self.plan = plan
        self.backend = plan.backend
        self._execute_task = execute_task
        self._cancel_check = cancel_check or (lambda: False)
        self._sleep = sleep or asyncio.sleep
        self._monotonic = monotonic
        self._clock = clock or _utc_now
        self._checkpoint = checkpoint
        self._initial_records = [dict(item) for item in initial_records]
        self._deadline_started_at = deadline_started_at

    # -- helpers -----------------------------------------------------------

    def _cancelled(self) -> bool:
        return bool(self._cancel_check())

    def _executor_for(self, target: Target) -> TaskExecutor:
        if self._execute_task is not None:
            return self._execute_task
        return DEFAULT_EXECUTORS.get(target.mode, missing_executor)

    def policy_for(self, target: Target) -> BatchPolicy:
        """The effective finite batch policy for one target.

        The plan may only make a platform's own limits stricter: pages, batch
        records and the stall limit are clamped down, and the interval between
        batches is never shortened below the platform's own value (the existing
        Xiaohongshu 10-record / 3-page / 600-second rule is therefore preserved).
        """

        base = policy_for(target.platform)
        # A fixed target is one bounded batch; its count budget decides how much
        # of that batch may be kept.
        max_batches = 1 if self.plan.count_mode == COUNT_MODE_FIXED else base.max_batches
        requested_records = self.plan.batch_records
        batch_records = base.batch_records
        if isinstance(requested_records, int) and not isinstance(requested_records, bool):
            batch_records = min(base.batch_records, requested_records)
        return BatchPolicy(
            platform=base.platform,
            batch_records=batch_records,
            batch_pages=min(base.batch_pages, self.plan.batch_pages),
            interval_seconds=max(
                base.interval_seconds, float(self.plan.batch_interval_seconds)
            ),
            max_batches=max_batches,
            stall_limit=min(base.stall_limit, self.plan.stall_limit),
        )

    # -- execution ---------------------------------------------------------

    async def run(self) -> RunSummary:
        started = self._deadline_started_at if self._deadline_started_at is not None else self._monotonic()
        started_at = self._clock()
        states = [TaskState(target=target) for target in self.plan.targets]
        records: list[dict[str, Any]] = []
        users: list[dict[str, Any]] = []
        records_by_target: dict[str, int] = {}
        timings: dict[str, float] = {}
        seen_records: set[str] = set()
        seen_users: dict[str, dict[str, Any]] = {}
        precondition: PreconditionLikeError | None = None
        risk_code: str | None = None
        cancelled = False
        halted = False
        halt_reason: str | None = None
        stop_reason: str | None = None
        ran = 0

        try:
            for index, state in enumerate(states):
                target = state.target
                if halted:
                    state.phase = "not-run"
                    state.stop_reason = halt_reason
                    continue
                if self._cancelled():
                    cancelled = True
                    halted = True
                    halt_reason = STOP_REASON_CANCELLED
                    state.phase = "not-run"
                    state.stop_reason = STOP_REASON_CANCELLED
                    continue
                remaining = self.plan.run_deadline_seconds - (
                    self._monotonic() - started
                )
                if remaining <= 0:
                    halted = True
                    halt_reason = STOP_REASON_DEADLINE
                    stop_reason = STOP_REASON_DEADLINE
                    state.phase = "not-run"
                    state.stop_reason = STOP_REASON_DEADLINE
                    continue
                ran += 1
                target_sink: list[PreconditionLikeError] = []
                outcome = await self._run_target(
                    state,
                    index=index,
                    total=len(states),
                    deadline_seconds=remaining,
                    seen_records=seen_records,
                    seen_users=seen_users,
                    records=records,
                    users=users,
                    records_by_target=records_by_target,
                    timings=timings,
                    precondition_sink=target_sink,
                )
                if outcome is not None:
                    precondition = outcome
                    ran -= 1
                    break
                if state.stop_reason == STOP_REASON_RISK:
                    risk_code = _risk_code_of(state)
                    halted = True
                    halt_reason = PRIOR_RISK_STOP
                elif state.phase == "cancelled":
                    cancelled = True
                    halted = True
                    halt_reason = STOP_REASON_CANCELLED
        except asyncio.CancelledError:
            # A real task cancellation stops the run; whatever was verified is
            # already checkpointed and remains evidence.
            raise

        finished_at = self._clock()
        if precondition is not None:
            if not records and not users:
                raise precondition
            for state in states:
                if state.phase == "pending":
                    state.phase = "not-run"
                    state.stop_reason = STOP_REASON_ERROR

        if risk_code is not None:
            stop_reason = STOP_REASON_RISK
        elif cancelled:
            stop_reason = STOP_REASON_CANCELLED
        elif stop_reason is None:
            for state in reversed(states[:ran]):
                if state.stop_reason is not None:
                    stop_reason = state.stop_reason
                    break

        profiles_complete, profiles_failed = _profile_counts(users)
        counts: dict[str, Any] = {
            "records": len(records),
            "users": len(users),
            "unique_records": len(records) + len(users),
            "profiles_complete": profiles_complete,
            "profiles_failed": profiles_failed,
            "targets": len(states),
            "targets_run": ran,
            "targets_not_run": len(states) - ran,
            "records_per_target": dict(records_by_target),
            "elapsed_seconds": round(self._monotonic() - started, 3),
        }
        return RunSummary(
            backend=self.plan.backend,
            plan=self.plan,
            status=_run_status(states, ran, risk_code, cancelled),
            started_at=started_at,
            finished_at=finished_at,
            observed_at=finished_at,
            stop_reason=stop_reason,
            resumable=_run_resumable(states, stop_reason),
            tasks=[_task_json(state, timings) for state in states],
            counts=counts,
            record_kinds=_record_kinds([*records, *users]),
            records=records,
            users=users,
            risk_code=risk_code,
            elapsed_seconds=counts["elapsed_seconds"],
        )

    async def _run_target(
        self,
        state: TaskState,
        *,
        index: int,
        total: int,
        deadline_seconds: float,
        seen_records: set[str],
        seen_users: dict[str, dict[str, Any]],
        records: list[dict[str, Any]],
        users: list[dict[str, Any]],
        records_by_target: dict[str, int],
        timings: dict[str, float],
        precondition_sink: list[PreconditionLikeError],
    ) -> PreconditionLikeError | None:
        """Run one target; return a precondition failure or ``None``."""

        target = state.target
        policy = self.policy_for(target)
        executor = self._executor_for(target)
        count = self.plan.count_for(target)
        target_budget = self.plan.budget_for(target)
        target_started = self._monotonic()
        from .best_effort import target_identities
        initial = [item for item in self._initial_records if target.identity in target_identities(item)]
        holder: dict[str, Any] = {"records": [], "users": [item for item in initial if record_kind(item) != RECORD_KIND_POSTS], "uids": set()}
        for item in holder["users"]:
            _absorb_user_record(item, target, users, seen_users)
        checkpoint = self._checkpoint_for(state, holder)

        async def execute(request: BatchRequest) -> BatchResult:
            context = TaskContext(
                target=target,
                task_index=index,
                task_total=total,
                count_mode=self.plan.count_mode,
                count=count,
                budget=request.remaining_budget,
                target_budget=target_budget,
                deadline_seconds=max(0.001, deadline_seconds - (self._monotonic() - target_started)),
                policy=policy,
                backend=self.plan.backend,
                evidence_level=evidence_level(
                    self.plan.backend, target.platform, target.mode
                ),
                excluded_ids=tuple(request.exclude_ids),
                known_user_ids=tuple(sorted({_user_identity(item) for item in seen_users.values() if record_kind(item) == "user_profiles" and _user_identity(item) is not None})),
                checkpoint=checkpoint,
                batch_index=request.batch_index,
            )
            try:
                outcome = await executor(target, context)
                if not isinstance(outcome, TaskOutcome):
                    raise PreconditionLikeError(EXECUTOR_CONTRACT)
            except PreconditionLikeError as error:
                # ``BestEffortRunner`` treats any executor failure as a failed
                # batch, so the refusing executor is remembered here and
                # re-raised by the runner once the target loop unwinds.
                precondition_sink.append(error)
                raise
            for item in outcome.users:
                holder["users"].append(dict(item))
                uid = _user_identity(item)
                if uid is not None:
                    holder["uids"].add(uid)
            state.users = len(holder["uids"])
            if outcome.risk_code:
                # The batch was cut short by a risk signal, but the records it
                # had already returned are verified evidence: keep them in the
                # prefix instead of discarding an observed window.
                _remember(holder, outcome.records, target)
                raise RiskStop(outcome.risk_code)
            return BatchResult(
                records=[dict(item) for item in outcome.records],
                pages=outcome.pages,
                exhausted=bool(outcome.exhausted),
                empty=not outcome.records,
                stop_reason=outcome.stop_reason,
            )

        runner = BestEffortRunner(
            policy=policy,
            count_mode=self.plan.count_mode,
            count=count,
            per_target_budget=target_budget,
            deadline_seconds=max(0.001, float(deadline_seconds)),
            cancel_check=self._cancel_check,
            sleep=self._sleep,
            monotonic=self._monotonic,
            checkpoint=checkpoint,
            max_total=None,
        )
        state.started_at = state.started_at or self._clock()
        produced: list[dict[str, Any]] = []
        try:
            result = await runner.run(state, execute, initial=[item for item in initial if record_kind(item) == RECORD_KIND_POSTS])
            produced = _with_held(
                [dict(item) for item in result.records], holder, target
            )
        except RequestCancelled:
            # The cancel check fired between batches: everything already
            # checkpointed is verified evidence and is kept as the prefix.
            state.phase = "cancelled"
            state.stop_reason = STOP_REASON_CANCELLED
            produced = _with_held(list(holder["records"]), holder, target)
        except RiskStop as error:
            state.phase = "risk-stopped"
            state.stop_reason = STOP_REASON_RISK
            state.checkpoint = {**state.checkpoint, "risk_code": error.code}
            produced = _with_held(list(holder["records"]), holder, target)
        except asyncio.CancelledError:
            state.phase = "cancelled"
            state.stop_reason = STOP_REASON_CANCELLED
            produced = _with_held(list(holder["records"]), holder, target)
        state.finished_at = self._clock()
        state.posts = len(produced)
        state.unique_posts = len(produced)
        timings[target.identity] = round(self._monotonic() - target_started, 3)
        _absorb_records(produced, target, records, seen_records, records_by_target)
        for record in produced:
            _absorb_user_record(record, target, users, seen_users)
        for item in holder["users"]:
            _absorb_user_record(item, target, users, seen_users)
        state.checkpoint["user_records"] = list(holder["users"])
        if precondition_sink:
            error = precondition_sink[0]
            state.phase = "failed"
            state.stop_reason = STOP_REASON_ERROR
            state.checkpoint = {**state.checkpoint, "precondition": error.code}
            checkpoint(state, produced)
            return error
        checkpoint(state, produced)
        return None

    # -- checkpointing -----------------------------------------------------

    def _checkpoint_for(
        self, state: TaskState, holder: dict[str, Any]
    ) -> Callable[[object, Sequence[Mapping[str, Any]]], None]:
        """Return the ``(state, records)`` callback this target reports through."""

        def persist(current: object, items: Sequence[Mapping[str, Any]]) -> None:
            snapshot = [dict(item) for item in items if isinstance(item, Mapping)]
            snapshot = _with_held(snapshot, holder, state.target)
            holder["records"] = snapshot
            if isinstance(current, TaskState):
                target_state = current
            elif isinstance(current, Mapping):
                state.checkpoint = {**state.checkpoint, **dict(current)}
                target_state = state
            else:
                target_state = state
            if self._checkpoint is not None:
                self._checkpoint(target_state, snapshot)

        return persist


# ---------------------------------------------------------------------------
# run-level bookkeeping helpers
# ---------------------------------------------------------------------------


def _remember(
    holder: dict[str, Any], produced: Sequence[Mapping[str, Any]], target: Target
) -> None:
    """Hold an interrupted batch's records outside the batch-runner prefix.

    ``BestEffortRunner`` reports a risk-stopped batch with the prefix it had
    *before* that batch, so the records the interrupted batch already returned
    are parked here and merged back into the verified prefix afterwards.
    """

    held: list[dict[str, Any]] = holder.setdefault("held", [])
    known = {
        _record_identity(item, target.platform)
        for item in held
    }
    for item in produced:
        record = dict(item)
        key = _record_identity(record, target.platform)
        if key is not None and key in known:
            continue
        if key is not None:
            known.add(key)
        held.append(record)


def _with_held(
    produced: list[dict[str, Any]],
    holder: dict[str, Any],
    target: Target,
) -> list[dict[str, Any]]:
    """Union of what the batch runner registered and the held prefix."""

    seen = {_record_identity(item, target.platform) for item in produced}
    merged = list(produced)
    for item in [*holder.get("records", ()), *holder.get("held", ())]:
        key = _record_identity(item, target.platform)
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        merged.append(dict(item))
    return merged


def _absorb_records(
    produced: Sequence[Mapping[str, Any]],
    target: Target,
    records: list[dict[str, Any]],
    seen_records: set[str],
    records_by_target: dict[str, int],
) -> int:
    added = 0
    from .best_effort import add_target_identity, target_identities
    for item in produced:
        record = dict(item)
        key = _record_identity(record, target.platform)
        if key is not None and key in seen_records:
            existing = next(row for row in records if _record_identity(row, target.platform) == key)
            if target.identity not in target_identities(existing):
                add_target_identity(existing, target.identity)
                added += 1
            continue
        if key is not None:
            seen_records.add(key)
        add_target_identity(record, target.identity)
        records.append(record)
        added += 1
    records_by_target[target.identity] = records_by_target.get(target.identity, 0) + added
    return added


def _absorb_user_record(
    record: Mapping[str, Any],
    target: Target,
    users: list[dict[str, Any]],
    seen_users: dict[str, dict[str, Any]],
) -> None:
    """Merge one user record, keyed by UID, without duplicating the homepage.

    Only user-profile and topic-participant records are absorbed here; a post
    that happens to carry an author UID is not a visited homepage.
    """

    candidate = dict(record)
    if record_kind(candidate) == RECORD_KIND_POSTS:
        return
    uid = _user_identity(candidate)
    if uid is None:
        users.append(candidate)
        return
    identity = f"{target.platform}:{candidate.get('type')}:{uid}"
    if record_kind(candidate) == "topic_participants":
        identity += ":" + str(candidate.get("topic") or target.identity) + ":" + str(candidate.get("post_id") or "")
    existing = seen_users.get(identity)
    if existing is not None:
        _merge_user(existing, candidate)
        return
    candidate.setdefault("target_identity", target.identity)
    seen_users[identity] = candidate
    users.append(candidate)


def _profile_counts(users: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    complete = 0
    failed = 0
    for record in users:
        status = record.get("profile_status")
        if status == "complete":
            complete += 1
        elif status == "failed":
            failed += 1
    return complete, failed


def _record_kinds(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    kinds: dict[str, int] = {}
    for record in records:
        kind = record_kind(record)
        kinds[kind] = kinds.get(kind, 0) + 1
    return kinds


def _risk_code_of(state: TaskState) -> str:
    code = state.checkpoint.get("risk_code")
    return code if isinstance(code, str) and code else "risk-signal"


def _run_status(
    states: Sequence[TaskState], ran: int, risk_code: str | None, cancelled: bool
) -> str:
    if risk_code is not None:
        return "risk-stopped"
    if cancelled:
        return "cancelled"
    if any(
        state.phase == "failed"
        or state.stop_reason in {STOP_REASON_ERROR, STOP_REASON_TIMEOUT}
        for state in states
    ):
        return "failed"
    executed = list(states[:ran])
    if executed and len(executed) == len(states) and all(
        state.stop_reason in {STOP_REASON_COUNT_REACHED, STOP_REASON_NATURAL_END}
        for state in executed
    ):
        return "complete"
    if not executed:
        return "failed"
    return "partial"


def _run_resumable(states: Sequence[TaskState], stop_reason: str | None) -> bool:
    if stop_reason == STOP_REASON_RISK or any(state.stop_reason == STOP_REASON_RISK for state in states):
        return False
    if any(state.checkpoint.get("evidence_shortfall") in {"incomplete-record", "screenshot-shortfall"} for state in states):
        return False
    if any(state.phase == "not-run" for state in states):
        return True
    if any(state.stop_reason == STOP_REASON_UNSUPPORTED for state in states):
        return False
    return stop_reason in {
        STOP_REASON_BUDGET,
        STOP_REASON_DEADLINE,
        STOP_REASON_CANCELLED,
        STOP_REASON_RISK,
        STOP_REASON_TIMEOUT,
    }


def _task_json(state: TaskState, timings: Mapping[str, float]) -> dict[str, Any]:
    payload = state.to_json()
    payload["elapsed_seconds"] = timings.get(state.target.identity, 0.0)
    payload["not_run"] = state.phase == "not-run"
    return payload


__all__ = [
    "DEFAULT_EXECUTORS",
    "EXECUTOR_CONTRACT",
    "MISSING_EXECUTOR",
    "PRIOR_RISK_STOP",
    "PlanRunner",
    "RunOutcomeLike",
    "RunSummary",
    "TaskContext",
    "TaskExecutor",
    "TaskOutcome",
    "build_run_manifest",
    "missing_executor",
]
