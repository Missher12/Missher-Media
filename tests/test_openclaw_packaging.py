from __future__ import annotations

import json
import importlib.util
import fcntl
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT_ROOT / "openclaw-media-missher"
RELEASE_MARKER = ".media-missher-release"
OWNER_MARKER = ".media-missher-owner.json"
INSTALL_LOCK = ".media-missher-install.lock"
COLLECTION_LOCK = ".media-missher-collection.lock"


def test_openclaw_skill_is_compact_and_has_valid_frontmatter() -> None:
    entries = {path.relative_to(PACKAGE).as_posix() for path in PACKAGE.rglob("*") if path.is_file()}
    assert entries == {"SKILL.md", "scripts/preflight.py", "scripts/run_collection.py"}
    text = (PACKAGE / "SKILL.md").read_text(encoding="utf-8")
    header = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert header
    fields = dict(line.split(": ", 1) for line in header.group(1).splitlines())
    assert fields["name"] == "media-missher"
    assert fields["description"].startswith("Use when ")
    assert "preflight.py" in text and "run_collection.py" in text


def test_openclaw_skill_retains_the_bounded_xhs_action_contract() -> None:
    text = (PACKAGE / "SKILL.md").read_text(encoding="utf-8")

    assert "at most one Xiaohongshu detail open" in text
    assert "at most three comment-container scrolls" in text
    assert "Do not retry a `risk-stopped` result" in text
    # Chrome CDP is the only active backend; old requests are refused.
    assert "--backend cdp" in text
    assert "Chrome CDP is the only active backend" in text
    assert "backend-retired-browserskill" in text
    assert "backend-retired-computer-use" in text
    assert "browser-assist-replaced" in text
    assert "rejected before navigation with `xhs-browser-assist-unsupported`" not in text
    assert "Xiaohongshu uses Playwright/CDP only" not in text
    # Only cdp can observe a response body, so the XHS detail contract needs it.
    assert "Rendered-page observations never imply response bodies" in text


def test_openclaw_package_has_no_platform_code_assets_or_personal_paths() -> None:
    forbidden_entries = {"platforms", "venv", ".venv", "browser", "data", "output", "node_modules"}
    assert not forbidden_entries.intersection(path.name for path in PACKAGE.rglob("*"))
    for path in PACKAGE.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "/Users/" not in text
            assert "cookie" not in text.casefold()
    from tools.scan_active_residuals import scan_roots
    assert scan_roots([PACKAGE]) == []


def _make_runtime_home(tmp_path: Path, *, version: str = "3.12.0") -> Path:
    home = tmp_path / "Runtime @ Home"
    shutil.copytree(PROJECT_ROOT / "runtime", home / "current", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    interpreter = home / "venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then\n"
        "  case \"$2\" in\n"
        f"    *version_info*) printf '%s\\n' '{version}'; exit 0 ;;\n"
        "    *) exit 0 ;;\n"
        "  esac\n"
        "fi\n"
        f"exec {shlex.quote(str(Path(sys.executable).resolve()))} \"$@\"\n",
        encoding="utf-8",
    )
    interpreter.chmod(0o700)
    state = home / "state"
    state.mkdir(mode=0o700)
    (home / "current" / RELEASE_MARKER).write_text("synthetic-release\n", encoding="utf-8")
    (home / "venv" / RELEASE_MARKER).write_text("synthetic-release\n", encoding="utf-8")
    (home / OWNER_MARKER).write_text(
        '{"name": "media-missher-runtime-home", "schema": 1}\n',
        encoding="utf-8",
    )
    (home / OWNER_MARKER).chmod(0o600)
    (home / INSTALL_LOCK).touch(mode=0o600)
    return home


def _make_installed_package(tmp_path: Path, *, release: str = "synthetic-release") -> Path:
    portable = tmp_path / "OpenClaw @ Skill"
    shutil.copytree(PACKAGE, portable)
    marker = portable / RELEASE_MARKER
    marker.write_text(release + "\n", encoding="utf-8")
    marker.chmod(0o600)
    return portable


def _run(script: Path, *args: str, home: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, MEDIA_MISSHER_HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )


def test_wrappers_use_shared_runtime_from_a_special_package_path(tmp_path: Path) -> None:
    home = _make_runtime_home(tmp_path)
    portable = _make_installed_package(tmp_path)

    preflight = _run(portable / "scripts" / "preflight.py", "--json", home=home)
    collection_help = _run(portable / "scripts" / "run_collection.py", "--help", home=home)

    assert preflight.returncode == 0, preflight.stderr
    assert json.loads(preflight.stdout)["status"] == "ok"
    assert collection_help.returncode == 0, collection_help.stderr
    assert "creator" in collection_help.stdout and "search" in collection_help.stdout
    assert stat.S_IMODE((home / "state").stat().st_mode) == 0o700


def test_preflight_fails_closed_when_runtime_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing-runtime"
    completed = _run(PACKAGE / "scripts" / "preflight.py", "--json", home=missing)

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["status"] == "failed"
    assert report["checks"]["current"] is False


def test_preflight_does_not_create_a_lock_in_an_unowned_home(tmp_path: Path) -> None:
    home = tmp_path / "unowned-home"
    home.mkdir(mode=0o755)
    owner_file = home / "owner-file"
    owner_file.write_text("unrelated", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in home.iterdir() if path.is_file()}
    before_mode = stat.S_IMODE(home.stat().st_mode)
    module = _load_preflight_module()

    report = module.inspect_runtime(home)

    after = {path.name: path.read_bytes() for path in home.iterdir() if path.is_file()}
    assert report["status"] == "failed"
    assert report["checks"]["home_owned"] is False
    assert before == after
    assert stat.S_IMODE(home.stat().st_mode) == before_mode
    assert not (home / INSTALL_LOCK).exists()


def test_preflight_rejects_old_python_and_boundary_symlinks(tmp_path: Path) -> None:
    old_home = _make_runtime_home(tmp_path / "old", version="3.10.9")
    old = _run(PACKAGE / "scripts" / "preflight.py", "--json", home=old_home)
    assert old.returncode == 1
    assert json.loads(old.stdout)["checks"]["python"] is False

    linked_home = tmp_path / "linked-home"
    linked_home.mkdir()
    (linked_home / "state").mkdir(mode=0o700)
    (linked_home / "venv" / "bin").mkdir(parents=True)
    (linked_home / OWNER_MARKER).write_text(
        '{"name": "media-missher-runtime-home", "schema": 1}\n',
        encoding="utf-8",
    )
    (linked_home / OWNER_MARKER).chmod(0o600)
    (linked_home / INSTALL_LOCK).touch(mode=0o600)
    (linked_home / "current").symlink_to(PROJECT_ROOT / "runtime", target_is_directory=True)
    linked = _run(PACKAGE / "scripts" / "preflight.py", "--json", home=linked_home)
    assert linked.returncode == 1
    assert json.loads(linked.stdout)["checks"]["current"] is False


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location("openclaw_preflight_test", PACKAGE / "scripts" / "preflight.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preflight_bounds_every_subprocess_and_optionally_probes_existing_cdp(tmp_path: Path) -> None:
    module = _load_preflight_module()
    home = _make_runtime_home(tmp_path)
    timeouts: list[float] = []

    def runner(command, **kwargs):
        timeouts.append(kwargs["timeout"])
        output = "3.12.0\n" if "version_info" in " ".join(command) else ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def read(self):
            return b'{"Browser":"Synthetic/1","Protocol-Version":"1.3"}'

    opened: list[tuple[str, float]] = []

    def opener(url: str, timeout: float):
        opened.append((url, timeout))
        return Response()

    report = module.inspect_runtime(
        home,
        live=True,
        cdp_url="http://127.0.0.1:9222",
        timeout=2.5,
        runner=runner,
        opener=opener,
    )

    assert report["status"] == "ok"
    assert timeouts and set(timeouts) == {2.5}
    assert opened == [("http://127.0.0.1:9222/json/version", 2.5)]
    assert report["checks"]["cdp"] is True


def test_collection_wrapper_rejects_current_and_venv_boundary_symlinks(tmp_path: Path) -> None:
    home = _make_runtime_home(tmp_path)
    real_current = home / "current-real"
    (home / "current").rename(real_current)
    (home / "current").symlink_to(real_current, target_is_directory=True)

    completed = _run(PACKAGE / "scripts" / "run_collection.py", "--help", home=home)

    assert completed.returncode == 1
    assert "symlink" in completed.stderr.casefold()


def test_preflight_probes_state_with_create_fsync_and_unlink(tmp_path: Path, monkeypatch) -> None:
    module = _load_preflight_module()
    home = _make_runtime_home(tmp_path)
    real_mkstemp = module.tempfile.mkstemp

    def deny_state_create(*args, **kwargs):
        if Path(kwargs["dir"]) == home / "state":
            raise PermissionError("synthetic state denial")
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(module.tempfile, "mkstemp", deny_state_create)

    report = module.inspect_runtime(home)

    assert report["status"] == "failed"
    assert report["checks"]["state_writable"] is False
    assert any("synthetic state denial" in error for error in report["errors"])


def test_preflight_and_launcher_reject_an_ancestor_symlink(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    home = _make_runtime_home(real_parent)
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    lexical_home = alias_parent / home.relative_to(real_parent)
    portable = _make_installed_package(tmp_path)

    module = _load_preflight_module()
    report = module.inspect_runtime(lexical_home)
    launched = _run(portable / "scripts" / "run_collection.py", "--help", home=lexical_home)

    assert report["status"] == "failed"
    assert any("symlink" in error.casefold() for error in report["errors"])
    assert launched.returncode == 1
    assert "symlink" in launched.stderr.casefold()


def test_preflight_and_launcher_reject_mixed_release_ids(tmp_path: Path) -> None:
    home = _make_runtime_home(tmp_path)
    (home / "venv" / RELEASE_MARKER).write_text("different-release\n", encoding="utf-8")
    portable = _make_installed_package(tmp_path)

    preflight = _run(portable / "scripts" / "preflight.py", "--json", home=home)
    launched = _run(portable / "scripts" / "run_collection.py", "--help", home=home)

    assert preflight.returncode == 1
    assert json.loads(preflight.stdout)["checks"]["release_consistent"] is False
    assert launched.returncode == 1
    assert "release" in launched.stderr.casefold()


def test_collection_wrapper_waits_for_the_installer_exclusive_lock(tmp_path: Path) -> None:
    home = _make_runtime_home(tmp_path)
    portable = _make_installed_package(tmp_path)
    interpreter = home / "venv" / "bin" / "python"
    interpreter.write_text("#!/bin/sh\nprintf 'immediate-launch\\n'\n", encoding="utf-8")
    interpreter.chmod(0o700)
    descriptor = os.open(home / INSTALL_LOCK, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    environment = dict(os.environ, MEDIA_MISSHER_HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.Popen(
        [sys.executable, str(portable / "scripts" / "run_collection.py"), "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process.communicate(timeout=2.0)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr
    assert "immediate-launch" in stdout


def test_collection_wrapper_rejects_a_concurrent_collection(tmp_path: Path) -> None:
    home = _make_runtime_home(tmp_path)
    portable = _make_installed_package(tmp_path)
    interpreter = home / "venv" / "bin" / "python"
    interpreter.write_text("#!/bin/sh\nprintf 'must-not-launch\\n'\n", encoding="utf-8")
    interpreter.chmod(0o700)
    lock = home / COLLECTION_LOCK
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    descriptor = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        launched = _run(
            portable / "scripts" / "run_collection.py",
            "--help",
            home=home,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert launched.returncode == 1
    assert "already running" in launched.stderr
    assert "must-not-launch" not in launched.stdout
