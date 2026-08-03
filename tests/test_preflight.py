import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import preflight
import media_missher_adapter as adapter
from media_missher_adapter import resolve_runtime_layout, run_preflight


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
    return resolve_runtime_layout(environ={"MEDIA_MISSHER_HOME": str(home)})


def test_preflight_checks_complete_runtime_without_live_network(fake_engine_root):
    layout = make_runtime_layout(fake_engine_root)

    report = run_preflight(layout, live=False)

    assert report["status"] == "ok"
    assert report["checks"] == {
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
