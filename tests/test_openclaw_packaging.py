from __future__ import annotations

import json
import importlib.util
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT_ROOT / "openclaw-media-missher"


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
    return home


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
    portable = tmp_path / "OpenClaw @ Skill"
    shutil.copytree(PACKAGE, portable)

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


def test_preflight_rejects_old_python_and_boundary_symlinks(tmp_path: Path) -> None:
    old_home = _make_runtime_home(tmp_path / "old", version="3.10.9")
    old = _run(PACKAGE / "scripts" / "preflight.py", "--json", home=old_home)
    assert old.returncode == 1
    assert json.loads(old.stdout)["checks"]["python"] is False

    linked_home = tmp_path / "linked-home"
    linked_home.mkdir()
    (linked_home / "state").mkdir(mode=0o700)
    (linked_home / "venv" / "bin").mkdir(parents=True)
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
