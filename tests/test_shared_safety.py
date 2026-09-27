import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from media_missher_runtime.shared_safety import SharedSafetyError, collection_lease, shared_directory
from media_missher_runtime.xhs_policy import SafetyBlocked, SharedXhsSafetyGate, XhsSafetyGate


def runtime_home(tmp_path, name):
    home = tmp_path / name
    home.mkdir(mode=0o700)
    (home / "state").mkdir(mode=0o700)
    return home


def test_two_runtime_homes_share_one_nonblocking_lock(tmp_path):
    first = runtime_home(tmp_path, "git")
    second = runtime_home(tmp_path, "harness")
    with collection_lease(first):
        with pytest.raises(SharedSafetyError, match="collection-busy"):
            with collection_lease(second):
                pytest.fail("another runtime entered")
    with collection_lease(second):
        pass


def test_standalone_adapter_module_checks_host_lease_and_persistent_risk(tmp_path):
    import importlib.util
    from media_missher_runtime.batch_journal import atomic_json
    from media_missher_runtime import shared_safety
    home = runtime_home(tmp_path, 'standalone')
    with collection_lease(home):
        atomic_json(shared_directory()/'computer-use-lease.json', {'owner':'other','expires_at':9999999999})
    spec = importlib.util.spec_from_file_location('_standalone_safety_fixture', shared_safety.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(module.SharedSafetyError, match='collection-busy'):
        with module.collection_lease(home):pytest.fail('cross-owner entry')
    # State-only maintenance may record a risk but never acquires a collection
    # session through the retired host-owner bypass.
    with collection_lease(home, state_only=True):
        shared_safety.record_platform_risk('weibo','challenge')
    with pytest.raises(module.SharedSafetyError, match='platform-risk-latched'):
        with module.collection_lease(home):pytest.fail('risk bypass')


def test_parent_segments_do_not_poison_shared_registry(tmp_path):
    from media_missher_runtime.shared_safety import registered_homes
    home = runtime_home(tmp_path, "git")
    (tmp_path / "anchor").mkdir()
    alias = tmp_path / "anchor" / ".." / "git"
    with collection_lease(alias):
        assert registered_homes() == (home,)
    with collection_lease(home):
        pass


def test_case_aliases_deduplicate_by_directory_identity(tmp_path):
    from media_missher_runtime.shared_safety import registered_homes
    home = runtime_home(tmp_path, "runtime-case")
    alias = home.with_name("RUNTIME-CASE")
    if not alias.exists():
        pytest.skip("case-insensitive filesystem regression")
    with collection_lease(home):
        pass
    with collection_lease(alias):
        assert len(registered_homes()) == 1
    with collection_lease(home):
        assert SharedXhsSafetyGate().status()["reason"] == "ready"


def test_shared_root_cannot_be_registered_as_a_runtime(tmp_path):
    with pytest.raises(SharedSafetyError, match="shared-state-invalid"):
        with collection_lease(shared_directory()):
            pytest.fail("shared state registered as runtime")
    assert not (shared_directory() / "runtime-homes.json").exists()
    with collection_lease(runtime_home(tmp_path, "normal")):
        assert SharedXhsSafetyGate().status()["reason"] == "ready"


def test_inherited_descriptor_is_verified_and_parent_lock_survives(tmp_path):
    home = runtime_home(tmp_path, "git")
    script = """from pathlib import Path
from media_missher_runtime.shared_safety import collection_lease
with collection_lease(Path(__import__('sys').argv[1]), inherit=True):
    print('held')
"""
    with collection_lease(home) as lease:
        result = subprocess.run([sys.executable, "-c", script, str(home)], env={**os.environ, **lease.environment, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "runtime")}, pass_fds=lease.pass_fds, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "held\n"
        with pytest.raises(SharedSafetyError, match="collection-busy"):
            with collection_lease(home):
                pytest.fail("child unlocked parent")


@pytest.mark.parametrize("descriptor", ["9999", "1", "1,1", "", "９９", str(10**100)])
def test_environment_only_cannot_skip_guard(tmp_path, monkeypatch, descriptor):
    home = runtime_home(tmp_path, "git")
    monkeypatch.setenv("MEDIA_MISSHER_LEASE_FDS", descriptor)
    with pytest.raises(SharedSafetyError, match="shared-lease-invalid"):
        with collection_lease(home, inherit=True):
            pytest.fail("invalid descriptor accepted")


def test_child_keeps_lock_when_parent_closes_its_descriptors(tmp_path):
    home = runtime_home(tmp_path, "git")
    script = """from pathlib import Path
import sys
from media_missher_runtime.shared_safety import collection_lease
with collection_lease(Path(sys.argv[1]), inherit=True):
    print('ready', flush=True)
    input()
"""
    child = None
    try:
        with collection_lease(home) as lease:
            child = subprocess.Popen([sys.executable, "-c", script, str(home)], env={**os.environ, **lease.environment, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "runtime")}, pass_fds=lease.pass_fds, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert child.stdout.readline() == "ready\n"
        with pytest.raises(SharedSafetyError, match="collection-busy"):
            with collection_lease(home):
                pytest.fail("parent close unlocked active child")
        child.communicate("\n", timeout=3)
        assert child.returncode == 0
        with collection_lease(home):
            pass
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=3)


def test_direct_non_xhs_core_cannot_overlap_another_home(tmp_path, monkeypatch, capsys):
    from media_missher_runtime import cli
    first = runtime_home(tmp_path, "git")
    second = runtime_home(tmp_path, "harness")
    monkeypatch.setenv("MEDIA_MISSHER_HOME", str(second))
    def unexpected(*_args, **_kwargs):
        pytest.fail("busy collection reached browser")
    monkeypatch.setattr(cli.BrowserSession, "connect", unexpected)
    with collection_lease(first):
        assert cli.main(["creator", "--platform", "weibo", "--weibo-uid", "fixture", "--count", "1", "--output", str(tmp_path / "out")]) == 78
    assert "code=collection-busy" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_migration_merges_risk_and_latest_time_and_ack_keeps_cooldown(tmp_path):
    first = runtime_home(tmp_path, "git")
    second = runtime_home(tmp_path, "harness")
    old = XhsSafetyGate(first / "state", clock=lambda: 1000)
    with old.batch():
        old.latch("http-429")
    later = XhsSafetyGate(second / "state", clock=lambda: 1100)
    with later.batch():
        pass
    with collection_lease(first):
        assert SharedXhsSafetyGate(clock=lambda: 1200).status()["reason"] == "xhs-risk-latched"
    with collection_lease(second):
        gate = SharedXhsSafetyGate(clock=lambda: 1200)
        status = gate.status()
        assert status["last_started_at"] == 1100
        assert status["risk"]["code"] == "http-429"
        assert gate.acknowledge()["remaining_seconds"] == 500
        assert gate.status()["reason"] == "xhs-cooldown"
        with pytest.raises(SafetyBlocked, match="xhs-cooldown"):
            with gate.batch():
                pytest.fail("ack reset cooldown")
    assert old.status()["risk"] is None
    assert later.status()["last_started_at"] == 1100
    with collection_lease(first):
        assert SharedXhsSafetyGate(clock=lambda: 1200).status()["reason"] == "xhs-cooldown"


def test_shared_batch_locks_and_updates_legacy_state(tmp_path):
    home = runtime_home(tmp_path, "git")
    old = XhsSafetyGate(home / "state", clock=lambda: 1000)
    with collection_lease(home):
        gate = SharedXhsSafetyGate(clock=lambda: 1000)
        with gate.batch():
            with pytest.raises(SafetyBlocked, match="xhs-safety-busy"):
                old.status()
            gate.latch("challenge")
    assert old.status()["risk"]["code"] == "challenge"
    assert old.status()["last_started_at"] == 1000


def test_corrupt_legacy_state_cannot_be_replaced_with_empty_state(tmp_path):
    home = runtime_home(tmp_path, "git")
    state = home / "state" / "xhs-safety.json"
    state.write_text("corrupt")
    state.chmod(0o600)
    with collection_lease(home):
        with pytest.raises(SafetyBlocked, match="xhs-safety-state-invalid"):
            SharedXhsSafetyGate().status()
    assert state.read_text() == "corrupt"


def test_shared_directory_cannot_be_symlinked(tmp_path):
    shared_directory().parent.mkdir(parents=True, exist_ok=True)
    shared_directory().symlink_to(tmp_path)
    with pytest.raises(SharedSafetyError, match="shared-state-invalid"):
        with collection_lease(runtime_home(tmp_path, "git")):
            pytest.fail("linked state accepted")
