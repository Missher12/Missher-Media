from __future__ import annotations

import json
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_batch_interval_and_risk_latch_survive_new_gate(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.xhs_policy import XhsSafetyGate, SafetyBlocked
    with XhsSafetyGate(tmp_path / "state", clock=lambda: 1000).batch() as gate:
        gate.latch("http-429")
    with pytest.raises(SafetyBlocked, match="xhs-risk-latched"):
        with XhsSafetyGate(tmp_path / "state", clock=lambda: 999999).batch():
            pytest.fail("risk latch automatically expired")
    gate = XhsSafetyGate(tmp_path / "state", clock=lambda: 1100)
    gate.acknowledge()
    with pytest.raises(SafetyBlocked, match="xhs-cooldown"):
        with gate.batch():
            pytest.fail("acknowledgement cleared the interval")
    with XhsSafetyGate(tmp_path / "state", clock=lambda: 1600).batch():
        pass
    assert gate.path.stat().st_mode & 0o777 == 0o600
    assert "http" not in json.dumps(gate.status())


def test_bad_state_and_symlink_fail_closed(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.xhs_policy import XhsSafetyGate, SafetyBlocked
    gate = XhsSafetyGate(tmp_path / "state", clock=lambda: 1000)
    with gate.batch():
        pass
    gate.path.write_text('{"version":1,"last_started_at":NaN}')
    with pytest.raises(SafetyBlocked, match="xhs-safety-state-invalid"):
        with gate.batch():
            pytest.fail("malformed state was accepted")
    gate.path.unlink()
    victim = tmp_path / "victim"
    victim.write_text("must remain intact")
    gate.path.symlink_to(victim)
    with pytest.raises(SafetyBlocked, match="xhs-safety-state-invalid"):
        gate.acknowledge()
    assert victim.read_text() == "must remain intact"


def test_cooldown_is_checked_before_browser_connection(tmp_path: Path, monkeypatch) -> None:
    from runtime.media_missher_runtime import cli
    from runtime.media_missher_runtime.xhs_policy import XhsSafetyGate
    monkeypatch.setenv("MEDIA_MISSHER_HOME", str(tmp_path / "runtime"))
    with XhsSafetyGate(tmp_path / "runtime" / "state").batch():
        pass
    def unexpected(*_args, **_kwargs):
        pytest.fail("blocked batch connected to the browser")
    monkeypatch.setattr(cli.BrowserSession, "connect", unexpected)
    assert cli.main(["creator", "--platform", "xhs", "--xhs-uid", "fixture", "--count", "1", "--output", str(tmp_path / "out"), "--allow-navigation"]) == 78


def test_xhs_request_caps_all_entry_modes() -> None:
    from runtime.media_missher_runtime.models import CollectionRequest
    for count in (0, 10, 50):
        request = CollectionRequest("xhs", count, page_cap=20, uid="fixture")
        assert request.target_count == 10
        assert request.page_cap == 3
    assert CollectionRequest("xhs", 2, page_cap=2, keyword="fixture").target_count == 2
    assert CollectionRequest("bilibili", 50, uid="fixture").target_count == 50


def test_xhs_page_spacing_rechecks_risk_before_scroll() -> None:
    from runtime.media_missher_runtime.platforms import xhs
    from runtime.media_missher_runtime.models import CollectionRequest
    from test_runtime_xhs import Page, Browser, creator_response, note, run
    page = Page(responses=[creator_response(note("one"), has_more=True, cursor="next", uid="creator")])
    original_wait = page.wait_for_timeout
    async def wait_and_challenge(milliseconds):
        await original_wait(milliseconds)
        page.challenge = "challenge-selector"
    page.wait_for_timeout = wait_and_challenge
    with pytest.raises(xhs.CollectionStopped):
        run(xhs.collect_creator(CollectionRequest("xhs", 2, uid="creator"), Browser(page)))
    assert not any("window.scrollTo" in script for script in page.evaluations)


def test_safety_rejects_symlinked_parent_without_creating_state(tmp_path):
    from runtime.media_missher_runtime.xhs_policy import XhsSafetyGate, SafetyBlocked
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(SafetyBlocked, match="state-invalid"):
        XhsSafetyGate(alias / "state").status()
    assert not (real / "state").exists()


def test_safety_rejects_fifo_without_blocking(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    os.mkfifo(state / "xhs-safety.json", 0o600)
    script = "from pathlib import Path; from runtime.media_missher_runtime.xhs_policy import XhsSafetyGate, SafetyBlocked\ntry: XhsSafetyGate(Path(%r)).status()\nexcept SafetyBlocked as e: print(e.code)" % str(state)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=3)
    assert result.returncode == 0
    assert result.stdout.strip() == "xhs-safety-state-invalid"


def test_mixed_platform_job_refreshes_interval_at_actual_xhs_start(tmp_path):
    from runtime.media_missher_runtime.xhs_policy import XhsSafetyGate, SafetyBlocked
    from runtime.media_missher_runtime.models import CollectionRequest
    from runtime.media_missher_runtime.cli import _run_requests
    now = [1000]
    class Dispatcher:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def collect(self, request):
            if request.platform == "bilibili": now[0] = 1700
            return []
    gate = XhsSafetyGate(tmp_path / "state", clock=lambda: now[0])
    with gate.batch():
        asyncio.run(_run_requests([CollectionRequest("bilibili", 1, uid="fixture"), CollectionRequest("xhs", 1, uid="fixture")], output_dir=tmp_path / "out", dispatcher=Dispatcher(), platform_timeout=10, safety_gate=gate))
    assert gate.status()["last_started_at"] == 1700
    now[0] = 1701
    with pytest.raises(SafetyBlocked, match="xhs-cooldown"):
        with gate.batch(): pytest.fail("preceding platform consumed XHS interval")
