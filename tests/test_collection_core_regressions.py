"""Offline regressions for shared start guards and collection evidence."""
import asyncio
import json
from argparse import Namespace
from pathlib import Path

import pytest

from runtime.media_missher_runtime.batch_journal import atomic_json
from runtime.media_missher_runtime.batch_policy import policy_for
from runtime.media_missher_runtime.collection_pacing import CollectionPacing
from runtime.media_missher_runtime.contracts import CollectionPlan, ContractError, Target
from runtime.media_missher_runtime.observations import merge_observation
from runtime.media_missher_runtime.plan_runner import PlanRunner
from runtime.media_missher_runtime.shared_safety import (
    SharedSafetyError, collection_lease, platform_risk_status, record_platform_risk,
    runtime_home, shared_directory,
)
from runtime.media_missher_runtime.xhs_policy import SharedXhsSafetyGate


def test_operator_can_inspect_and_acknowledge_actual_dual_latch(capsys):
    from runtime.media_missher_runtime.xhs_policy import main
    with collection_lease(runtime_home()):
        with SharedXhsSafetyGate().batch() as gate:
            gate.latch("http-429")
        record_platform_risk("xhs", "http-429")
        record_platform_risk("weibo", "challenge")
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["reason"] == "xhs-risk-latched"
    assert main(["--acknowledge-risk"]) == 0
    assert json.loads(capsys.readouterr().out)["reason"] == "xhs-cooldown"
    with collection_lease(runtime_home(), state_only=True):
        assert set(platform_risk_status()["platforms"]) == {"weibo"}
        assert SharedXhsSafetyGate().status()["remaining_seconds"] > 0
    assert (shared_directory() / "xhs-risk-ack.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(SharedSafetyError, match="platform-risk-latched"):
        with collection_lease(runtime_home()):
            pytest.fail("other platform protection lost")


def test_ack_write_failure_keeps_shared_latch(monkeypatch):
    from runtime.media_missher_runtime import batch_journal
    from runtime.media_missher_runtime.shared_safety import acknowledge_platform_risk
    with collection_lease(runtime_home()):
        record_platform_risk("xhs", "challenge")
    def fail(*args):
        raise OSError("synthetic write failure")
    with collection_lease(runtime_home(), state_only=True):
        monkeypatch.setattr(batch_journal, "atomic_json", fail)
        with pytest.raises(OSError):
            acknowledge_platform_risk("xhs")
        assert "xhs" in platform_risk_status()["platforms"]


@pytest.mark.parametrize("value", [
    {"schema_version": True, "platforms": {}},
    {"schema_version": 1, "platforms": {"xhs": {"code": [], "observed_at": 1}}},
    {"schema_version": 1, "platforms": {"xhs": {"code": "challenge", "observed_at": -1}}},
])
def test_bad_risk_state_cannot_be_acknowledged(value):
    from runtime.media_missher_runtime.shared_safety import acknowledge_platform_risk
    with collection_lease(runtime_home(), state_only=True):
        path = shared_directory() / "platform-risk.json"
        atomic_json(path, value)
        original = path.read_bytes()
        with pytest.raises(SharedSafetyError, match="shared-state-invalid"):
            acknowledge_platform_risk("xhs")
        assert path.read_bytes() == original


def test_normal_spacing_survives_home_switch_and_keeps_platforms_separate(tmp_path):
    with collection_lease(tmp_path / "first"):
        CollectionPacing(clock=lambda: 1000).reserve("weibo")
    with collection_lease(tmp_path / "second"):
        gate = CollectionPacing(clock=lambda: 1010)
        assert gate.remaining("weibo") == 80
        assert gate.remaining("douyin") == 0
        with pytest.raises(SharedSafetyError, match="platform-cooldown"):
            gate.reserve("weibo")
        # A backward clock extends the pause; it never resets it.
        assert CollectionPacing(clock=lambda: 900).remaining("weibo") == 190
        backwards = CollectionPacing(clock=lambda: 900)
        backwards.mark_started("weibo")
        assert backwards.remaining("weibo") == 190


def test_in_run_spacing_waits_remaining_only_and_cancellation_does_not_reserve():
    now = [1000]
    waits = []
    async def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds
    async def cancel(seconds):
        raise asyncio.CancelledError
    with collection_lease(runtime_home()):
        gate = CollectionPacing(clock=lambda: now[0], sleep=sleep)
        gate.reserve("bilibili")
        now[0] += 10
        asyncio.run(gate.wait_and_reserve("bilibili"))
        assert waits == [50]
        prior = gate.path.read_bytes()
        gate.sleep = cancel
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(gate.wait_and_reserve("bilibili"))
        assert gate.path.read_bytes() == prior


def test_bad_pacing_state_fails_closed():
    with collection_lease(runtime_home()):
        gate = CollectionPacing()
        atomic_json(gate.path, {"schema_version": True, "platforms": {}})
        with pytest.raises(SharedSafetyError, match="shared-state-invalid"):
            gate.remaining("x")


def test_dispatcher_cooldown_precedes_platform_navigation():
    from runtime.media_missher_runtime.cli import RuntimeDispatcher
    from runtime.media_missher_runtime.models import CollectionRequest
    class Browser:
        async def require_authenticated_page(self, platform):
            pytest.fail("cooldown navigated")
    with collection_lease(runtime_home()):
        dispatcher = RuntimeDispatcher("http://127.0.0.1:9222")
        dispatcher.browser = Browser()
        dispatcher.pacing.reserve("weibo")
        with pytest.raises(SharedSafetyError, match="platform-cooldown"):
            asyncio.run(dispatcher.preflight([CollectionRequest("weibo", 1, uid="1")]))


def test_dispatcher_shares_preflight_reservation_then_waits_and_caps(monkeypatch):
    from runtime.media_missher_runtime import cli
    from runtime.media_missher_runtime.models import CollectionRequest
    now = [1000]
    calls = []
    async def sleep(seconds):
        calls.append(("wait", seconds))
        now[0] += seconds
    class Browser:
        async def require_authenticated_page(self, platform):
            calls.append(("preflight", platform))
    async def collect(request, browser):
        calls.append(("collect", request.target_count, request.page_cap))
        return []
    monkeypatch.setattr(cli, "_collect_with", collect)
    with collection_lease(runtime_home()):
        dispatcher = cli.RuntimeDispatcher("http://127.0.0.1:9222")
        dispatcher.browser = Browser()
        dispatcher.pacing = CollectionPacing(clock=lambda: now[0], sleep=sleep)
        request = CollectionRequest("bilibili", 99, uid="1", page_cap=99)
        async def run():
            await dispatcher.preflight([request])
            await dispatcher.collect(request)
            await dispatcher.collect(request)
        asyncio.run(run())
    assert calls == [("preflight", "bilibili"), ("collect", 20, 3), ("wait", 60), ("collect", 20, 3)]


def test_plan_xhs_cooldown_precedes_browser_connection(tmp_path, monkeypatch, capsys):
    from runtime.media_missher_runtime import cli
    with collection_lease(runtime_home()):
        with SharedXhsSafetyGate().batch():
            pass
    def unexpected(*args, **kwargs):
        pytest.fail("plan cooldown connected to browser")
    monkeypatch.setattr(cli.BrowserSession, "connect", unexpected)
    plan = CollectionPlan(targets=(Target(platform="xhs", mode="creator", uid="one"),))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan.to_json()))
    path.chmod(0o600)
    assert cli.main(["creator", "--targets-json", str(path), "--output", str(tmp_path / "out")]) == 78
    assert "code=xhs-cooldown" in capsys.readouterr().err


def test_duplicate_enrichment_preserves_zero_and_metric_domain():
    original = {"platform": "bilibili", "dynamic_id": "1", "bvid": "BV1", "liked": 0,
                "comments": None, "engagement_scope": "dynamic", "title": "", "complete": False}
    merge_observation(original, {"platform": "bilibili", "dynamic_id": "1", "bvid": "BV1",
        "title": "observed", "liked": 100, "comments": 200, "engagement_scope": "video",
        "observed_at": "2026-10-03", "complete": True})
    assert original["liked"] == 0
    assert original["comments"] is None
    assert original["title"] == "observed"
    assert original["complete"] is False
    assert original["field_sources"]["title"]["observed_at"] == "2026-10-03"
    merge_observation(original, {"dynamic_id": "other", "description": "wrong entity"})
    assert "description" not in original


def test_duplicate_display_metadata_follows_only_accepted_values():
    record = {"mblog_id": "1", "liked": 0, "comments": None}
    merge_observation(record, {"mblog_id": "1", "liked": 12000, "comments": 20000,
        "metric_display": {"liked": {"raw": "1.2万", "value": 12000, "precision": "approximate"},
                           "comments": {"raw": "2万", "value": 20000, "precision": "approximate"}},
        "field_quality": {"liked": "approximate", "comments": "approximate"}})
    assert record["liked"] == 0
    assert "liked" not in record["metric_display"]
    assert "liked" not in record["field_quality"]
    assert record["comments"] == record["metric_display"]["comments"]["value"] == 20000


def test_plan_duplicate_enrichment_is_checkpointed_without_count_inflation():
    from runtime.media_missher_runtime.plan_runner import TaskOutcome
    targets = (Target(platform="weibo", mode="search", keyword="a"), Target(platform="weibo", mode="search", keyword="b"))
    async def execute(target, context):
        record = {"platform": "weibo", "type": "post", "mblog_id": "1", "liked": 0}
        if target.keyword == "b":
            record.update(title="enriched", liked=None)
        return TaskOutcome(records=[record], exhausted=True)
    result = asyncio.run(PlanRunner(CollectionPlan(targets=targets, count=1), execute_task=execute).run())
    assert len(result.records) == 1
    assert result.records[0]["title"] == "enriched"
    assert result.records[0]["liked"] == 0
    assert len(result.records[0]["target_identities"]) == 2


@pytest.mark.parametrize("kwargs", [{"required_fields": ("typo",)}, {"required_fields": ("liked", "liked")}, {"required_fields": ([],)}, {"field_groups": ("typo",)}])
def test_invalid_field_contracts_refused(kwargs):
    with pytest.raises(ContractError):
        CollectionPlan(targets=(Target(platform="weibo", mode="creator", uid="1"),), **kwargs)


@pytest.mark.parametrize("name", ["allow_navigation", "collect_active_platforms"])
def test_json_plan_does_not_promote_string_false_to_authorization(name):
    plan = CollectionPlan(targets=(Target(platform="weibo", mode="creator", uid="1"),)).to_json()
    plan[name] = "false"
    with pytest.raises(ContractError):
        CollectionPlan.from_json(plan)


@pytest.mark.parametrize("liked,expected", [(None, "error"), (0, "count-reached")])
def test_required_field_missing_is_not_success_and_zero_is_valid(liked, expected):
    from runtime.media_missher_runtime.cli import PlanExecutor
    target = Target(platform="weibo", mode="creator", uid="1")
    plan = CollectionPlan(targets=(target,), count=1, required_fields=("liked",), field_groups=("metrics",))
    class Dispatcher:
        async def collect(self, request):
            return [{"platform": "weibo", "type": "post", "mblog_id": "1", "liked": liked}]
    executor = PlanExecutor(dispatcher=Dispatcher(), plan=plan, args=Namespace())
    result = asyncio.run(PlanRunner(plan, execute_task=executor).run())
    assert result.tasks[0]["stop_reason"] == expected
    assert result.tasks[0]["checkpoint"]["field_group_coverage"]["metrics"]["liked"] == int(liked is not None)


def test_required_field_diagnostic_survives_all_persisted_layers(tmp_path):
    from runtime.media_missher_runtime import cli
    plan = CollectionPlan(targets=(Target(platform="weibo", mode="creator", uid="1"),), count=1, required_fields=("liked",))
    class Dispatcher:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def collect(self, request):
            return [{"platform": "weibo", "type": "post", "mblog_id": "1"}]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan.to_json()))
    path.chmod(0o600)
    out = tmp_path / "out"
    assert cli.main(["creator", "--targets-json", str(path), "--output", str(out)], dispatcher=Dispatcher()) == 1
    manifests = list(out.rglob("manifest.json"))
    assert len(manifests) == 1
    value = json.loads(manifests[0].read_text())
    assert value["status"] == "partial"
    assert value["diagnostics"]["weibo"] == {"kind": "result", "code": "required-fields-missing"}


def test_fixed_request_uses_batch_records_cap():
    from runtime.media_missher_runtime.cli import PlanExecutor
    target = Target(platform="weibo", mode="creator", uid="1")
    plan = CollectionPlan(targets=(target,), count=50, batch_records=3)
    class Dispatcher:
        async def collect(self, request):
            assert request.count == 50
            assert request.target_count == 3
            return []
    asyncio.run(PlanRunner(plan, execute_task=PlanExecutor(dispatcher=Dispatcher(), plan=plan, args=Namespace())).run())


@pytest.mark.enable_socket
def test_shared_risk_probe_in_real_offline_chrome():
    import shutil
    from runtime.media_missher_runtime.page_risk import risk_probe_expression
    api = pytest.importorskip("playwright.async_api")
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not executable.is_file():
        discovered = shutil.which("google-chrome") or shutil.which("chromium")
        if not discovered:
            pytest.skip("local Chromium is unavailable")
        executable = Path(discovered)
    cases = [
        ('<article>普通正文讨论风控与验证码</article>', False),
        ('<div hidden><div class="captcha">验证码</div></div>', False),
        ('<div style="opacity:0"><div class="captcha">验证码</div></div>', False),
        ('<div aria-hidden="true"><div class="captcha">验证码</div></div>', False),
        ('<article role="dialog">作者讨论请求过于频繁的含义</article>', False),
        ('<div class="captcha">请完成验证</div>', True),
        ('<div role="dialog">请完成验证后继续</div>', True),
        ('<div class="error-page">访问受限</div>', True),
    ]
    async def exercise():
        async with api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=str(executable), headless=True)
            try:
                page = await browser.new_page()
                await page.route("**/*", lambda route: route.abort())
                for html, expected in cases:
                    await page.set_content(html)
                    for platform in ("xhs", "x", "bilibili", "douyin", "weibo"):
                        assert (await page.evaluate(risk_probe_expression(platform)))["risk"] is expected
            finally:
                await browser.close()
    asyncio.run(exercise())
