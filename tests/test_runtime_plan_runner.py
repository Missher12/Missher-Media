"""Plan-runner behaviour: order, counts, risk, cancellation, checkpoints.

Everything is injected, so the whole file runs with no browser, no ``bsk`` and
no network. The record fixtures use the real native identifiers the platform
normalizers produce, because the shared dedup key is built from them.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from runtime.media_missher_runtime.backends import PreconditionLikeError
from runtime.media_missher_runtime.best_effort import RiskStop
from runtime.media_missher_runtime.contracts import (
    MANIFEST_SCHEMA_VERSION,
    CollectionPlan,
    ContractError,
    Target,
)
from runtime.media_missher_runtime.exporting import record_kind
from runtime.media_missher_runtime.models import CollectionRequest
from runtime.media_missher_runtime.plan_runner import (
    MISSING_EXECUTOR,
    PRIOR_RISK_STOP,
    PlanRunner,
    TaskContext,
    TaskOutcome,
    build_run_manifest,
)


def _post(platform: str, native_id: str, **extra: object) -> dict[str, object]:
    key = {
        "weibo": "mblog_id",
        "bilibili": "dynamic_id",
        "x": "tweet_id",
        "xhs": "note_id",
        "douyin": "aweme_id",
    }[platform]
    return {"platform": platform, "type": "post", key: native_id, **extra}


def _profile(uid: str, **extra: object) -> dict[str, object]:
    return {
        "platform": "weibo",
        "type": "user_profile",
        "uid": uid,
        "author_id": uid,
        "profile_status": "complete",
        **extra,
    }


def _plan(targets: tuple[Target, ...], **overrides: object) -> CollectionPlan:
    values: dict[str, object] = {
        "targets": targets,
        "count": 2,
        "batch_pages": 1,
        "run_deadline_seconds": 600.0,
    }
    values.update(overrides)
    return CollectionPlan(**values)  # type: ignore[arg-type]


def _target(uid: str, platform: str = "weibo") -> Target:
    return Target(platform=platform, mode="creator", uid=uid)


class Recorder:
    """A fake executor that records call order and returns prepared outcomes."""

    def __init__(self, outcomes: dict[str, TaskOutcome | list[TaskOutcome]]) -> None:
        self.outcomes = outcomes
        self.order: list[tuple[str, int]] = []
        self.contexts: list[TaskContext] = []

    async def __call__(self, target: Target, context: TaskContext) -> TaskOutcome:
        self.order.append((target.identity, context.batch_index))
        self.contexts.append(context)
        prepared = self.outcomes[target.identity]
        if isinstance(prepared, list):
            return prepared[min(context.batch_index, len(prepared) - 1)]
        return prepared


def _run(runner: PlanRunner) -> object:
    return asyncio.run(runner.run())


# ---------------------------------------------------------------------------
# order, counts and count modes
# ---------------------------------------------------------------------------


def test_targets_run_sequentially_in_plan_order() -> None:
    targets = (_target("1"), _target("2"), _target("3"))
    recorder = Recorder(
        {
            target.identity: TaskOutcome(
                records=[_post("weibo", f"{target.uid}-1")], exhausted=True
            )
            for target in targets
        }
    )

    summary = _run(PlanRunner(_plan(targets), execute_task=recorder))

    assert [identity for identity, _ in recorder.order] == [
        target.identity for target in targets
    ]
    assert summary.counts["records_per_target"] == {
        target.identity: 1 for target in targets
    }
    assert [task["posts"] for task in summary.tasks] == [1, 1, 1]
    assert summary.counts["targets_run"] == 3
    assert summary.counts["targets_not_run"] == 0


def test_fixed_mode_runs_one_bounded_batch_and_respects_the_count() -> None:
    target = _target("9")
    recorder = Recorder(
        {
            target.identity: TaskOutcome(
                records=[_post("weibo", f"m{index}") for index in range(5)]
            )
        }
    )

    summary = _run(PlanRunner(_plan((target,), count=3), execute_task=recorder))

    assert len(recorder.order) == 1
    assert summary.counts["records"] == 3
    assert summary.tasks[0]["stop_reason"] == "count-reached"
    assert summary.status == "complete"


def test_fixed_mode_uses_per_target_counts() -> None:
    first, second = _target("1"), _target("2")
    plan = _plan(
        (first, second),
        count=4,
        per_target_counts={first.identity: 1},
    )
    recorder = Recorder(
        {
            target.identity: TaskOutcome(
                records=[_post("weibo", f"{target.uid}-{index}") for index in range(4)]
            )
            for target in (first, second)
        }
    )

    summary = _run(PlanRunner(plan, execute_task=recorder))

    assert summary.counts["records_per_target"] == {
        first.identity: 1,
        second.identity: 4,
    }


def test_best_effort_collects_more_than_one_fixed_batch() -> None:
    target = _target("7")
    batches = [
        TaskOutcome(records=[_post("weibo", f"{index}-{position}") for position in range(20)])
        for index in range(3)
    ]
    batches[-1].exhausted = True
    recorder = Recorder({target.identity: batches})
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    plan = _plan(
        (target,),
        count_mode="best_effort",
        count=0,
        run_deadline_seconds=100_000.0,
    )
    summary = _run(
        PlanRunner(plan, execute_task=recorder, sleep=fake_sleep)
    )

    assert len(recorder.order) == 3
    assert summary.counts["records"] == 60
    assert summary.counts["records"] > 20
    assert summary.tasks[0]["stop_reason"] == "natural-end"
    # The platform's own interval is never shortened by the plan.
    assert waits == [90.0, 90.0]


def test_best_effort_honours_a_per_target_record_budget() -> None:
    target = _target("7")
    recorder = Recorder(
        {
            target.identity: [
                TaskOutcome(
                    records=[
                        _post("weibo", f"{index}-{position}") for position in range(20)
                    ]
                )
                for index in range(3)
            ]
        }
    )
    plan = _plan(
        (target,),
        count_mode="best_effort",
        count=0,
        per_target_budget=25,
        run_deadline_seconds=100_000.0,
    )

    summary = _run(PlanRunner(plan, execute_task=recorder, sleep=_no_sleep))

    assert summary.counts["records"] == 25
    assert summary.tasks[0]["stop_reason"] == "count-reached"


async def _no_sleep(seconds: float) -> None:
    return None


# ---------------------------------------------------------------------------
# risk, cancellation and deadlines
# ---------------------------------------------------------------------------


def test_risk_code_stops_the_whole_run_and_marks_later_targets() -> None:
    first, second, third = _target("1"), _target("2"), _target("3")

    async def executor(target: Target, context: TaskContext) -> TaskOutcome:
        if target.identity == first.identity:
            return TaskOutcome(records=[_post("weibo", "kept")], risk_code="http-429")
        return TaskOutcome(records=[_post("weibo", f"{target.uid}-1")], exhausted=True)

    summary = _run(PlanRunner(_plan((first, second, third)), execute_task=executor))

    assert summary.status == "risk-stopped"
    assert summary.stop_reason == "risk-stopped"
    assert summary.risk_code == "http-429"
    assert summary.counts["records"] == 1
    assert summary.resumable is False
    phases = {task["target_identity"]: (task["phase"], task["stop_reason"]) for task in summary.tasks}
    assert phases[first.identity] == ("risk-stopped", "risk-stopped")
    assert phases[second.identity] == ("not-run", PRIOR_RISK_STOP)
    assert phases[third.identity] == ("not-run", PRIOR_RISK_STOP)
    assert summary.counts["targets_run"] == 1


def test_a_raised_risk_stop_is_treated_as_a_risk_code() -> None:
    target = _target("1")

    async def executor(target: Target, context: TaskContext) -> TaskOutcome:
        raise RiskStop("challenge")

    summary = _run(PlanRunner(_plan((target,)), execute_task=executor))

    assert summary.status == "risk-stopped"
    assert summary.risk_code == "challenge"


def test_cancellation_keeps_the_verified_prefix() -> None:
    target = _target("1")
    batches = [
        TaskOutcome(records=[_post("weibo", f"{index}-{position}") for position in range(4)])
        for index in range(3)
    ]
    recorder = Recorder({target.identity: batches})
    checkpoints: list[int] = []
    cancelled = {"value": False}

    async def fake_sleep(seconds: float) -> None:
        # The operator cancels while the run waits for the next compliant batch.
        cancelled["value"] = True

    def cancel_check() -> bool:
        return cancelled["value"]

    plan = _plan((target,), count_mode="best_effort", count=0, run_deadline_seconds=100_000.0)
    runner = PlanRunner(
        plan,
        execute_task=recorder,
        cancel_check=cancel_check,
        sleep=fake_sleep,
        checkpoint=lambda state, records: checkpoints.append(len(records)),
    )

    summary = _run(runner)

    assert summary.status == "cancelled"
    assert summary.stop_reason == "cancelled"
    assert summary.counts["records"] == 4
    assert summary.counts["records"] > 0
    assert checkpoints[-1] == 4


def test_cancellation_before_the_first_target_marks_everything_not_run() -> None:
    first, second = _target("1"), _target("2")

    async def executor(target: Target, context: TaskContext) -> TaskOutcome:
        raise AssertionError("no target may run once the run is cancelled")

    summary = _run(
        PlanRunner(
            _plan((first, second)),
            execute_task=executor,
            cancel_check=lambda: True,
        )
    )

    assert summary.status == "cancelled"
    assert summary.counts["targets_run"] == 0
    assert [task["phase"] for task in summary.tasks] == ["not-run", "not-run"]


def test_run_deadline_marks_later_targets_not_run() -> None:
    first, second = _target("1"), _target("2")
    clock = iter([0.0, 0.0, 0.0, 5.0, 5.0, 6.0, 6.0, 7.0, 7.0, 8.0, 8.0])

    def monotonic() -> float:
        return next(clock, 8.0)

    async def executor(target: Target, context: TaskContext) -> TaskOutcome:
        return TaskOutcome(records=[_post("weibo", f"{target.uid}-1")], exhausted=True)

    summary = _run(
        PlanRunner(
            _plan((first, second), run_deadline_seconds=1.0),
            execute_task=executor,
            monotonic=monotonic,
        )
    )

    assert summary.counts["targets_run"] == 1
    assert summary.tasks[1]["phase"] == "not-run"
    assert summary.tasks[1]["stop_reason"] == "run-deadline"
    assert summary.stop_reason == "run-deadline"
    assert summary.resumable is True


# ---------------------------------------------------------------------------
# users, checkpoints and reporting
# ---------------------------------------------------------------------------


def test_a_user_homepage_is_collected_once_per_run() -> None:
    first, second = _target("1"), _target("2")
    recorder = Recorder(
        {
            first.identity: TaskOutcome(
                records=[_post("weibo", "a", author_id="42")],
                users=[_profile("42", topics=["topic-a"])],
                exhausted=True,
            ),
            second.identity: TaskOutcome(
                records=[_post("weibo", "b", author_id="42")],
                users=[_profile("42", topics=["topic-b"])],
                exhausted=True,
            ),
        }
    )

    summary = _run(PlanRunner(_plan((first, second)), execute_task=recorder))

    assert summary.counts["users"] == 1
    assert summary.counts["profiles_complete"] == 1
    assert len(summary.users) == 1
    assert summary.users[0]["topics"] == ["topic-a", "topic-b"]
    assert summary.record_kinds == {"posts": 2, "user_profiles": 1}
    # The second task is told the homepage was already visited.
    assert recorder.contexts[-1].known_user_ids == ("42",)
    assert summary.counts["unique_records"] == 3


def test_duplicate_records_across_targets_are_merged_once() -> None:
    first, second = _target("1"), _target("2")
    shared = _post("weibo", "same-id")
    recorder = Recorder(
        {
            first.identity: TaskOutcome(records=[shared], exhausted=True),
            second.identity: TaskOutcome(records=[dict(shared)], exhausted=True),
        }
    )

    summary = _run(PlanRunner(_plan((first, second)), execute_task=recorder))

    assert summary.counts["records"] == 1
    # Global content is unique; each target retains its observed association.
    assert summary.counts["records_per_target"] == {first.identity: 1, second.identity: 1}
    assert summary.records[0]["target_identities"] == [first.identity, second.identity]


def test_incomplete_evidence_cannot_advertise_resume_because_another_target_is_pending():
    from runtime.media_missher_runtime.contracts import TaskState
    from runtime.media_missher_runtime.plan_runner import _run_resumable
    incomplete=TaskState(target=_target('1'),phase='failed',stop_reason='error',checkpoint={'evidence_shortfall':'incomplete-record'})
    pending=TaskState(target=_target('2'),phase='not-run',stop_reason='run-deadline')
    assert not _run_resumable([incomplete,pending],'run-deadline')


def test_checkpoint_callback_runs_after_every_batch() -> None:
    target = _target("5")
    batches = [
        TaskOutcome(records=[_post("weibo", f"{index}-{position}") for position in range(2)])
        for index in range(3)
    ]
    batches[-1].exhausted = True
    recorder = Recorder({target.identity: batches})
    snapshots: list[tuple[str, int]] = []

    plan = _plan((target,), count_mode="best_effort", count=0, run_deadline_seconds=100_000.0)
    summary = _run(
        PlanRunner(
            plan,
            execute_task=recorder,
            sleep=_no_sleep,
            checkpoint=lambda state, records: snapshots.append(
                (state.target.identity, len(records))
            ),
        )
    )

    assert len(recorder.order) == 3
    assert len(snapshots) >= 3
    # One callback per batch, and the prefix only ever grows.
    assert {2, 4, 6} <= {count for _, count in snapshots}
    counts = [count for _, count in snapshots]
    assert counts == sorted(counts)
    assert all(identity == target.identity for identity, _ in snapshots)
    assert summary.counts["records"] == 6


def test_task_context_carries_the_documented_values() -> None:
    target = _target("1")
    recorder = Recorder({target.identity: TaskOutcome(exhausted=True)})

    _run(PlanRunner(_plan((target,), count=2), execute_task=recorder))

    context = recorder.contexts[0]
    assert context.target.identity == target.identity
    assert context.task_index == 0
    assert context.task_total == 1
    assert context.count_mode == "fixed"
    assert context.count == 2
    assert context.budget == 2
    assert context.deadline_seconds > 0
    assert context.policy.platform == "weibo"
    assert context.backend == "cdp"
    assert context.evidence_level == "response"
    assert context.excluded_ids == ()
    assert context.known_user_ids == ()
    assert callable(context.checkpoint)
    assert context.to_json()["target_identity"] == target.identity


def test_run_summary_json_exposes_the_documented_keys() -> None:
    target = _target("1")
    recorder = Recorder(
        {target.identity: TaskOutcome(records=[_post("weibo", "1")], exhausted=True)}
    )

    payload = _run(PlanRunner(_plan((target,)), execute_task=recorder)).to_json()

    assert set(payload) == {
        "schema_version",
        "backend",
        "plan",
        "tasks",
        "counts",
        "record_kinds",
        "status",
        "started_at",
        "finished_at",
        "observed_at",
        "stop_reason",
        "resumable",
    }
    assert payload["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert payload["backend"] == "cdp"
    assert payload["plan"]["targets"][0]["uid"] == "1"
    assert payload["observed_at"] == payload["finished_at"]
    assert payload["counts"]["records"] == 1
    # The JSON must survive a round trip to the private run artifacts.
    assert json.loads(json.dumps(payload)) == payload


def test_run_manifest_is_validated_and_carries_the_run_identity() -> None:
    target = _target("1")
    recorder = Recorder(
        {
            target.identity: TaskOutcome(
                records=[_post("weibo", "1")], users=[_profile("42")], exhausted=True
            )
        }
    )
    summary = _run(PlanRunner(_plan((target,)), execute_task=recorder))

    manifest = build_run_manifest(summary, "run-1", ["plan.json", "summary.json"])
    payload = manifest.to_json()

    assert payload["run_id"] == "run-1"
    assert payload["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert payload["observed_at"] == payload["finished_at"]
    assert payload["record_kinds"] == {"posts": 1, "user_profiles": 1}
    assert payload["evidence_paths"] == ["plan.json", "summary.json"]
    assert all(isinstance(value, int) for value in payload["counts"].values())
    assert summary.build_manifest("run-2").to_json()["run_id"] == "run-2"

    with pytest.raises(ContractError):
        build_run_manifest(summary, "not-a-run-id")


def test_record_kinds_use_the_shared_exporter_vocabulary() -> None:
    assert record_kind(_post("weibo", "1")) == "posts"
    assert record_kind(_profile("42")) == "user_profiles"


# ---------------------------------------------------------------------------
# the missing executor
# ---------------------------------------------------------------------------


def test_a_missing_executor_refuses_with_a_fixed_precondition() -> None:
    target = _target("1")

    with pytest.raises(PreconditionLikeError) as failure:
        _run(PlanRunner(_plan((target,))))

    assert failure.value.code == MISSING_EXECUTOR

    async def executor(target: Target, context: TaskContext) -> str:
        return "not a task outcome"

    with pytest.raises(PreconditionLikeError) as contract:
        _run(PlanRunner(_plan((target,)), execute_task=executor))  # type: ignore[arg-type]

    assert contract.value.code == "plan-executor-contract"


def test_an_executor_precondition_is_reported_not_swallowed() -> None:
    target = _target("1")

    async def executor(target: Target, context: TaskContext) -> TaskOutcome:
        raise PreconditionLikeError("topic-collector-unavailable")

    with pytest.raises(PreconditionLikeError) as failure:
        _run(PlanRunner(_plan((target,)), execute_task=executor))

    assert failure.value.code == "topic-collector-unavailable"


# ---------------------------------------------------------------------------
# request model
# ---------------------------------------------------------------------------


def test_the_request_rejects_automatic_backend_switching() -> None:
    with pytest.raises(ValueError, match="automatic backend switching is not supported"):
        CollectionRequest(platform="weibo", count=1, uid="u", backend="auto")


def test_the_deprecated_browser_assist_is_not_a_new_request():
    with pytest.raises(ValueError, match="backend-retired-browserskill"):
        CollectionRequest(platform="bilibili", count=1, uid="u", browser_assist="browserskill")
    with pytest.raises(ValueError, match="unsupported browser assist mode"):
        CollectionRequest(platform="bilibili", count=1, uid="u", browser_assist="stealth")


def test_best_effort_has_no_fixed_total() -> None:
    request = CollectionRequest(
        platform="xhs", count=10, uid="u", count_mode="best_effort"
    )

    assert request.target_count is None
    assert CollectionRequest(platform="xhs", count=10, uid="u").target_count == 10
    assert CollectionRequest(platform="x", count=4, uid="u").target_count == 4
    assert CollectionRequest(platform="weibo", count=0, keyword="k").target_count is None


def test_the_request_accepts_x_and_a_weibo_topic() -> None:
    from runtime.media_missher_runtime.models import CollectionRequest as Request

    assert Request(platform="x", count=2, uid="12345").platform == "x"
    topic = Request(platform="weibo", count=2, topic="话题")
    assert topic.topic == "话题"
    assert topic.topic_kind == "topic"
    assert topic.mode == "topic"
    with pytest.raises(ValueError, match="exactly one"):
        Request(platform="weibo", count=1, uid="u", topic="话题")
    with pytest.raises(ValueError, match="exactly one"):
        Request(platform="weibo", count=1)
    with pytest.raises(ValueError, match="weibo only"):
        Request(platform="xhs", count=1, topic="话题")


def test_a_request_plan_must_describe_the_same_task() -> None:
    plan = _plan((_target("1"),))

    assert CollectionRequest(platform="weibo", count=2, uid="1", plan=plan).plan is plan
    with pytest.raises(ValueError, match="does not match the request"):
        CollectionRequest(platform="bilibili", count=2, uid="1", plan=plan)
    with pytest.raises(ValueError, match="does not match the request"):
        CollectionRequest(platform="weibo", count=2, keyword="1", plan=plan)
    with pytest.raises(ValueError, match="does not match the request"):
        CollectionRequest(platform="weibo", count=2, uid="1", plan="not-a-plan")  # type: ignore[arg-type]


def test_the_backend_field_is_frozen_into_the_plan_and_its_targets() -> None:
    target = _target("1")
    recorder = Recorder({target.identity: TaskOutcome(exhausted=True)})
    plan = _plan((target,), backend="cdp")

    summary = _run(PlanRunner(plan, execute_task=recorder))

    assert summary.backend == "cdp"
    assert recorder.contexts[0].backend == "cdp"
    assert recorder.contexts[0].evidence_level == "response"


# ---------------------------------------------------------------------------
# the CLI boundary: flags, private plan files and fixed diagnostics
# ---------------------------------------------------------------------------


class _CliDispatcher:
    """A stand-in dispatcher for the legacy and plan CLI paths."""

    def __init__(self, records_per_request: int = 1) -> None:
        self.requests: list[CollectionRequest] = []
        self.entered = False
        self._records_per_request = records_per_request

    async def __aenter__(self) -> "_CliDispatcher":
        self.entered = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def preflight(self, requests: object) -> None:
        return None

    async def collect(self, request: CollectionRequest) -> list[dict[str, object]]:
        self.requests.append(request)
        native = {"weibo": "mblog_id", "bilibili": "dynamic_id"}.get(
            request.platform, "native_id"
        )
        return [
            {"platform": request.platform, "type": "post", native: f"n{index}"}
            for index in range(self._records_per_request)
        ]


def _run_cli(
    argv: list[str], dispatcher: object, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    from runtime.media_missher_runtime.cli import main

    try:
        code = main(argv, dispatcher=dispatcher)
    except SystemExit as exit_code:  # pragma: no cover - argparse usage errors
        code = int(exit_code.code or 0)
    return code, capsys.readouterr().err


def _private_plan(tmp_path: object, payload: dict[str, object]) -> object:
    import os
    import stat as stat_module

    path = tmp_path / "plan.json"  # type: ignore[operator]
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, stat_module.S_IRUSR | stat_module.S_IWUSR)
    return path


def test_cli_runs_a_multi_target_plan_from_a_private_file(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_file = _private_plan(
        tmp_path,
        {
            "schema_version": 1,
            "targets": [
                {"platform": "weibo", "mode": "creator", "uid": "10"},
                {"platform": "bilibili", "mode": "creator", "uid": "20"},
            ],
            "count": 1,
            "run_deadline_seconds": 600.0,
        },
    )
    dispatcher = _CliDispatcher()
    code, err = _run_cli(
        ["creator", "--targets-json", str(plan_file), "--output-dir", str(tmp_path / "out")],  # type: ignore[operator]
        dispatcher,
        capsys,
    )

    assert code == 0
    assert err == ""
    assert [(request.platform, request.uid) for request in dispatcher.requests] == [
        ("weibo", "10"),
        ("bilibili", "20"),
    ]
    runs = list((tmp_path / "out").glob("run-*"))  # type: ignore[operator]
    assert len(runs) == 1
    names = sorted(item.name for item in runs[0].iterdir())
    assert names == [
        "bilibili.json",
        "checkpoint.json",
        "committed.json",
        "journal",
        "manifest.json",
        "plan.json",
        "run-binding.json",
        "run-result.json",
        "run_manifest.json",
        "summary.json",
        "weibo.json",
    ]
    manifest = json.loads((runs[0] / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"].startswith("run-")
    assert manifest["status"] == "complete"
    assert manifest["backend"] == "cdp"
    assert manifest["counts"]["records"] == 2
    assert manifest["observed_at"] == manifest["finished_at"]
    checkpoint = json.loads((runs[0] / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["records"]
    for name in names:
        mode = (runs[0] / name).stat().st_mode & 0o777
        assert mode == (0o700 if (runs[0] / name).is_dir() else 0o600)


def test_cli_rejects_a_plan_file_that_is_not_private(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    import os

    plan_file = _private_plan(
        tmp_path, {"schema_version": 1, "targets": [{"platform": "weibo", "mode": "creator", "uid": "1"}]}
    )
    os.chmod(plan_file, 0o644)

    code, err = _run_cli(
        ["creator", "--targets-json", str(plan_file), "--output-dir", str(tmp_path / "out")],  # type: ignore[operator]
        _CliDispatcher(),
        capsys,
    )

    assert code == 78
    assert err == (
        "media-missher-diagnostic platform=unknown "
        "kind=precondition code=targets-json-permissions\n"
    )


def test_cli_rejects_a_missing_or_invalid_plan_file(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    code, err = _run_cli(
        [
            "creator",
            "--targets-json",
            str(tmp_path / "missing.json"),  # type: ignore[operator]
            "--output-dir",
            str(tmp_path / "out"),  # type: ignore[operator]
        ],
        _CliDispatcher(),
        capsys,
    )
    assert code == 78
    assert "code=targets-json-invalid" in err


def test_cli_freezes_the_backend_for_the_run(
    tmp_path: object, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher = _CliDispatcher()
    code, _ = _run_cli(
        [
            "creator",
            "--platforms",
            "weibo",
            "--weibo-uid",
            "1",
            "--count",
            "1",
            "--backend",
            "computer_use",
            "--output-dir",
            str(tmp_path / "out"),  # type: ignore[operator]
        ],
        dispatcher,
        capsys,
    )

    assert code == 78
    assert dispatcher.requests == []

    refused, err = _run_cli(
        [
            "creator",
            "--platforms",
            "weibo",
            "--weibo-uid",
            "1",
            "--backend",
            "auto",
            "--output-dir",
            str(tmp_path / "out2"),  # type: ignore[operator]
        ],
        _CliDispatcher(),
        capsys,
    )
    assert refused == 78
    assert err == (
        "media-missher-diagnostic platform=weibo "
        "kind=precondition code=backend-auto-unsupported\n"
    )

    monkeypatch.setenv("MEDIA_MISSHER_PROFILE_CONFIG", str(tmp_path / "profile.json"))  # type: ignore[operator]
    (tmp_path / "profile.json").write_text(  # type: ignore[operator]
        json.dumps({"backend": "computer_use"}), encoding="utf-8"
    )
    preferred = _CliDispatcher()
    code, _ = _run_cli(
        [
            "creator",
            "--platforms",
            "weibo",
            "--weibo-uid",
            "1",
            "--count",
            "1",
            "--output-dir",
            str(tmp_path / "out3"),  # type: ignore[operator]
        ],
        preferred,
        capsys,
    )
    assert code == 78
    assert preferred.requests == []

    monkeypatch.delenv("MEDIA_MISSHER_PROFILE_CONFIG")
    fallback = _CliDispatcher()
    _run_cli(
        [
            "creator",
            "--platforms",
            "weibo",
            "--weibo-uid",
            "1",
            "--count",
            "1",
            "--output-dir",
            str(tmp_path / "out4"),  # type: ignore[operator]
        ],
        fallback,
        capsys,
    )
    assert fallback.requests[0].backend == "cdp"


def test_cli_refuses_the_deprecated_browser_assist_bridge(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    dispatcher = _CliDispatcher()
    code, err = _run_cli(
        [
            "creator",
            "--platforms",
            "weibo",
            "--weibo-uid",
            "1",
            "--browser-assist",
            "browserskill",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path / "out"),  # type: ignore[operator]
        ],
        dispatcher,
        capsys,
    )

    assert code == 78
    assert err == (
        "media-missher-diagnostic platform=weibo "
        "kind=precondition code=browser-assist-replaced\n"
    )
    assert dispatcher.entered is False
    assert not (tmp_path / "out").exists()  # type: ignore[operator]


def test_cli_never_turns_a_super_topic_into_a_keyword_search(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    dispatcher = _CliDispatcher()
    code, err = _run_cli(
        [
            "creator",
            "--topic",
            "https://weibo.com/p/100808abcdef",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path / "out"),  # type: ignore[operator]
        ],
        dispatcher,
        capsys,
    )

    assert code == 78
    assert err == (
        "media-missher-diagnostic platform=weibo "
        "kind=precondition code=topic-container-unsupported\n"
    )
    assert dispatcher.requests == []

    standard_dispatcher = _CliDispatcher()
    standard, _standard_err = _run_cli(
        [
            "creator",
            "--topic",
            "#普通话题#",
            "--count",
            "1",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path / "out2"),  # type: ignore[operator]
        ],
        standard_dispatcher,
        capsys,
    )
    # A standard topic is a real task: it reaches the topic collector and is
    # never rewritten into a keyword search.
    assert standard == 0
    assert [request.topic for request in standard_dispatcher.requests] == ["普通话题"]
    assert all(request.keyword is None for request in standard_dispatcher.requests)


def test_cli_routes_platform_x_through_the_x_collector(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    dispatcher = _CliDispatcher()
    code, _err = _run_cli(
        [
            "creator",
            "--platforms",
            "x",
            "--x-uid",
            "alice",
            "--count",
            "1",
            "--allow-navigation",
            "--output-dir",
            str(tmp_path / "out"),  # type: ignore[operator]
        ],
        dispatcher,
        capsys,
    )

    # The X collector exists, so the request reaches it instead of being refused
    # with a missing-collector precondition.
    assert code == 0
    assert [request.platform for request in dispatcher.requests] == ["x"]
    assert [request.uid for request in dispatcher.requests] == ["alice"]


def test_cli_count_mode_and_budget_reach_the_request(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    dispatcher = _CliDispatcher()
    code, _ = _run_cli(
        [
            "creator",
            "--platforms",
            "weibo",
            "--weibo-uid",
            "1",
            "--count",
            "0",
            "--count-mode",
            "best_effort",
            "--per-target-budget",
            "40",
            "--batch-pages",
            "2",
            "--batch-interval",
            "300",
            "--run-deadline",
            "1200",
            "--output-dir",
            str(tmp_path / "out"),  # type: ignore[operator]
        ],
        dispatcher,
        capsys,
    )

    # The real plan now paginates. This fixture repeats one post and never
    # declares natural exhaustion, so the stall preserves a partial prefix.
    assert code == 1
    assert len(dispatcher.requests) > 1
    request = dispatcher.requests[0]
    assert request.count_mode == "best_effort"
    assert request.best_effort_budget == 40
    assert request.target_count == 20  # bounded batch, not the total budget
    assert dispatcher.requests[1].exclude_ids == ("n0",)
    run = next((tmp_path / "out").glob("run-*"))
    frozen = json.loads((run / "plan.json").read_text())
    assert frozen["per_target_budget"] == 40
    assert frozen["run_deadline_seconds"] == 1200
