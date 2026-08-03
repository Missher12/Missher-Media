import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import preflight
import media_missher_adapter as adapter
from media_missher_adapter import resolve_runtime_layout, run_preflight


def write_runtime_contract(home: Path, *, release: str = "test-release") -> None:
    home.chmod(0o700)
    owner = home / ".media-missher-owner.json"
    owner.write_text(
        json.dumps({"name": "media-missher-runtime-home", "schema": 1}) + "\n",
        encoding="utf-8",
    )
    owner.chmod(0o600)
    lock = home / ".media-missher-install.lock"
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    for root in (home / "current", home / "venv"):
        marker = root / ".media-missher-release"
        marker.write_text(release + "\n", encoding="ascii")
        marker.chmod(0o600)


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"Browser": "Synthetic/1", "Protocol-Version": "1.3"}).encode()


def make_runtime_layout(fake_engine_root, *, version="3.12.0", playwright=True):
    home = fake_engine_root.parent / "runtime-home"
    current_scripts = home / "current" / "scripts"
    shutil.copytree(fake_engine_root / "scripts", current_scripts)
    interpreter = home / "venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    playwright_status = 0 if playwright else 1
    interpreter.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then\n"
        "  case \"$2\" in\n"
        f"    *version_info*) printf '%s\\n' '{version}'; exit 0 ;;\n"
        f"    'import playwright') exit {playwright_status} ;;\n"
        "  esac\n"
        "fi\n"
        f"exec {shlex.quote(str(Path(sys.executable).resolve()))} \"$@\"\n",
        encoding="utf-8",
    )
    interpreter.chmod(0o700)
    state = home / "state"
    state.mkdir(mode=0o700)
    write_runtime_contract(home)
    return resolve_runtime_layout(environ={"MEDIA_MISSHER_HOME": str(home)})


def test_preflight_checks_complete_runtime_without_live_network(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)

    report = run_preflight(layout, live=False)

    assert report["status"] == "ok"
    assert report["checks"] == {
        "runtime_lease": True,
        "release": True,
        "layout": True,
        "runtime_home": True,
        "current": True,
        "python": True,
        "state": True,
        "state_private": True,
        "state_writable": True,
        "entrypoints": True,
        "python_version": True,
        "playwright": True,
        "entrypoint_help": True,
    }
    assert report["runtime_home"] == str(layout.home)


def test_preflight_rejects_mismatched_release_before_runtime_probes(
    fake_engine_root, monkeypatch
):
    layout = make_runtime_layout(fake_engine_root)
    (layout.home / "venv" / ".media-missher-release").write_text(
        "different-release\n", encoding="ascii"
    )

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("runtime probes must not run for a mixed release")

    monkeypatch.setattr(adapter.subprocess, "run", unexpected_probe)
    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["runtime_lease"] is True
    assert report["checks"]["release"] is False
    assert any("release" in error.lower() for error in report["errors"])
    assert "different-release" not in " ".join(report["errors"])


@pytest.mark.parametrize(
    ("skill_release", "expected_status"),
    [("test-release", "ok"), ("different-release", "failed")],
)
def test_installed_codex_skill_must_match_runtime_release(
    fake_engine_root, tmp_path, monkeypatch, skill_release, expected_status
):
    layout = make_runtime_layout(fake_engine_root)
    installed_skill = tmp_path / "codex-skills" / "media-missher"
    installed_skill.mkdir(parents=True)
    marker = installed_skill / ".media-missher-release"
    marker.write_text(skill_release + "\n", encoding="ascii")
    marker.chmod(0o600)
    monkeypatch.setattr(adapter, "SKILL_ROOT", installed_skill)

    report = run_preflight(layout, live=False)

    assert report["status"] == expected_status
    assert report["checks"]["release"] is (expected_status == "ok")


def test_preflight_rejects_noncanonical_layout_before_release_lookup(
    fake_engine_root, tmp_path
):
    layout = make_runtime_layout(fake_engine_root)
    unsafe = adapter.RuntimeLayout(
        home=layout.home,
        current=tmp_path / "outside-current",
        python=layout.python,
        state=layout.state,
    )

    report = run_preflight(unsafe, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["runtime_lease"] is False
    assert any("layout" in error.lower() for error in report["errors"])


def test_preflight_rejects_missing_runtime_owner_marker(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)
    (layout.home / ".media-missher-owner.json").unlink()

    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["runtime_lease"] is False
    assert any("ownership" in error.lower() for error in report["errors"])


@pytest.mark.parametrize("unsafe_kind", ["missing", "symlink", "mode"])
def test_preflight_rejects_unsafe_install_lock(fake_engine_root, unsafe_kind):
    layout = make_runtime_layout(fake_engine_root)
    lock = layout.home / ".media-missher-install.lock"
    lock.unlink()
    if unsafe_kind == "symlink":
        target = layout.home.parent / "outside-install.lock"
        target.touch(mode=0o600)
        lock.symlink_to(target)
    elif unsafe_kind == "mode":
        lock.touch(mode=0o600)
        lock.chmod(0o644)

    report = run_preflight(layout, live=False, timeout=0.1)

    assert report["status"] == "failed"
    assert report["checks"]["runtime_lease"] is False
    assert any("lock" in error.lower() for error in report["errors"])


def test_preflight_install_exclusive_lock_times_out_without_probing(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)
    descriptor = os.open(layout.home / ".media-missher-install.lock", os.O_RDONLY)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    started = time.monotonic()
    try:
        report = run_preflight(layout, live=False, timeout=0.05)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert time.monotonic() - started < 1
    assert report["status"] == "failed"
    assert report["checks"]["runtime_lease"] is False
    assert any("lock" in error.lower() for error in report["errors"])


def test_live_preflight_accepts_cdp_version(fake_engine_root, monkeypatch):
    layout = make_runtime_layout(fake_engine_root)
    monkeypatch.setattr(preflight.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    report = run_preflight(layout, live=True, urlopen=preflight.urllib.request.urlopen)
    assert report["status"] == "ok"
    assert report["checks"]["cdp"] is True
    assert report["cdp"] == {"browser": "Synthetic/1", "protocol_version": "1.3"}


def test_live_preflight_reports_unavailable_cdp_without_starting_chrome(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)

    def failing_urlopen(*_args, **_kwargs):
        raise OSError("connection refused")

    report = run_preflight(layout, live=True, urlopen=failing_urlopen)
    assert report["status"] == "failed"
    assert report["checks"]["cdp"] is False
    assert any("connection refused" in error for error in report["errors"])


def test_preflight_requires_all_five_entrypoints(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)
    (layout.current / "scripts" / "scrape_xhs.py").unlink()

    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["entrypoints"] is False
    assert report["checks"]["entrypoint_help"] is False
    assert any("scrape_xhs.py" in error for error in report["errors"])


def test_preflight_rejects_non_private_state(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)
    layout.state.chmod(0o755)

    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["state_private"] is False


def test_preflight_rejects_state_symlink_outside_runtime_home(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)
    outside_state = layout.home.parent / "outside-state"
    outside_state.mkdir(mode=0o700)
    layout.state.rmdir()
    layout.state.symlink_to(outside_state, target_is_directory=True)

    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["layout"] is False
    assert report["checks"]["state_private"] is False


def test_preflight_rejects_entrypoint_symlink_outside_current(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)
    entrypoint = layout.current / "scripts" / "scrape_xhs.py"
    outside_entrypoint = layout.home.parent / "outside-scrape-xhs.py"
    outside_entrypoint.write_text("print('unsafe')\n", encoding="utf-8")
    entrypoint.unlink()
    entrypoint.symlink_to(outside_entrypoint)

    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["entrypoints"] is False


def test_preflight_probes_state_with_create_fsync_and_unlink(
    fake_engine_root, monkeypatch
):
    layout = make_runtime_layout(fake_engine_root)
    real_mkstemp = adapter.tempfile.mkstemp

    def deny_state_create(*args, **kwargs):
        if Path(kwargs["dir"]) == layout.state:
            raise PermissionError("synthetic write denial")
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(adapter.tempfile, "mkstemp", deny_state_create)

    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["state_writable"] is False
    assert any("synthetic write denial" in error for error in report["errors"])


def test_preflight_requires_python_311_or_newer(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root, version="3.10.14")

    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["python_version"] is False
    assert any("3.11" in error for error in report["errors"])


def test_preflight_requires_playwright_import(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root, playwright=False)

    report = run_preflight(layout, live=False)

    assert report["status"] == "failed"
    assert report["checks"]["playwright"] is False


@pytest.mark.parametrize("timeout", [float("nan"), float("inf")])
def test_preflight_rejects_non_finite_timeout_before_checks(
    fake_engine_root, timeout
):
    layout = make_runtime_layout(fake_engine_root)

    with pytest.raises(adapter.ConfigurationError, match="finite"):
        run_preflight(layout, live=False, timeout=timeout)


def test_preflight_cli_help_is_offline():
    script = Path(preflight.__file__).resolve()
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 0
    assert "--engine-root" not in completed.stdout
    assert "--live" in completed.stdout


def test_system_python_39_compiles_and_runs_runtime_lease(fake_engine_root, tmp_path):
    system_python = Path("/usr/bin/python3")
    if not system_python.is_file():
        pytest.skip("macOS system Python is unavailable")
    layout = make_runtime_layout(fake_engine_root)
    adapter_path = Path(adapter.__file__).resolve()
    compiled = tmp_path / "media_missher_adapter.pyc"
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    compile_result = subprocess.run(
        [
            str(system_python),
            "-c",
            (
                "import py_compile,sys; "
                "py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)"
            ),
            str(adapter_path),
            str(compiled),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    completed = subprocess.run(
        [
            str(system_python),
            "-c",
            (
                "import json,sys; sys.path.insert(0, sys.argv[1]); "
                "from media_missher_adapter import resolve_runtime_layout,run_preflight; "
                "layout=resolve_runtime_layout(environ={'MEDIA_MISSHER_HOME':sys.argv[2]}); "
                "print(json.dumps(run_preflight(layout, live=False)))"
            ),
            str(adapter_path.parent),
            str(layout.home),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "ok"
