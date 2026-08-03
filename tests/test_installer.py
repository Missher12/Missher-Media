from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeExecutor:
    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def __call__(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        values = tuple(str(item) for item in command)
        self.calls.append((values, env))
        if len(values) >= 4 and values[1:3] == ("-m", "venv"):
            interpreter = Path(values[3]) / "bin" / "python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"-c\" ]; then exit 0; fi\n"
                f"exec {shlex.quote(str(Path(sys.executable).resolve()))} \"$@\"\n",
                encoding="utf-8",
            )
            interpreter.chmod(0o700)
        if self.failure is not None and self.failure in " ".join(values):
            raise RuntimeError("synthetic executor failure")


def _install(tmp_path: Path, **overrides: Any):
    from tools.install_media_missher import install

    values = {
        "source": PROJECT_ROOT,
        "home": tmp_path / "runtime-home",
        "codex_root": tmp_path / "codex-skills",
        "openclaw_root": tmp_path / "openclaw-skills",
        "executor": FakeExecutor(),
    }
    values.update(overrides)
    return install(**values)


def test_install_stages_runtime_and_both_compact_skills_with_private_state(tmp_path: Path) -> None:
    executor = FakeExecutor()

    result = _install(tmp_path, executor=executor)

    assert result.current == (tmp_path / "runtime-home" / "current").resolve()
    assert result.current.joinpath("scripts", "scrape_all.py").is_file()
    assert result.previous is None
    assert result.codex_current.joinpath("SKILL.md").is_file()
    assert result.openclaw_current.joinpath("SKILL.md").is_file()
    assert result.openclaw_current.joinpath("scripts", "run_collection.py").is_file()
    assert stat.S_IMODE(result.state.stat().st_mode) == 0o700
    assert not list(tmp_path.rglob("*.staging-*"))

    commands = [command for command, _ in executor.calls]
    pip_calls = [command for command in commands if command[1:4] == ("-m", "pip", "install")]
    assert len(pip_calls) == 1
    assert "--requirement" in pip_calls[0]
    assert Path(pip_calls[0][pip_calls[0].index("--requirement") + 1]).name == "requirements.lock"
    assert any(command[1:3] == ("-c", "import playwright; import media_missher_runtime") for command in commands)
    help_scripts = {Path(command[1]).name for command in commands if len(command) >= 3 and command[-1] == "--help"}
    assert help_scripts == {"scrape_all.py", "scrape_bilibili.py", "scrape_xhs.py", "scrape_douyin.py", "scrape_weibo.py"}


def test_upgrade_keeps_unique_previous_releases_for_all_three_targets(tmp_path: Path) -> None:
    first = _install(tmp_path)
    first.current.joinpath("release-marker").write_text("runtime-one", encoding="utf-8")
    first.codex_current.joinpath("release-marker").write_text("codex-one", encoding="utf-8")
    first.openclaw_current.joinpath("release-marker").write_text("openclaw-one", encoding="utf-8")

    second = _install(tmp_path)

    assert second.previous is not None and second.previous.name.startswith("previous-")
    assert second.codex_previous is not None and second.codex_previous.name.startswith("media-missher.previous-")
    assert second.openclaw_previous is not None and second.openclaw_previous.name.startswith("media-missher.previous-")
    assert second.previous.joinpath("release-marker").read_text(encoding="utf-8") == "runtime-one"
    assert second.codex_previous.joinpath("release-marker").read_text(encoding="utf-8") == "codex-one"
    assert second.openclaw_previous.joinpath("release-marker").read_text(encoding="utf-8") == "openclaw-one"

    third = _install(tmp_path)
    assert third.previous is not None and third.previous != second.previous
    assert third.codex_previous is not None and third.codex_previous != second.codex_previous
    assert third.openclaw_previous is not None and third.openclaw_previous != second.openclaw_previous


def test_executor_failure_does_not_rotate_any_existing_current(tmp_path: Path) -> None:
    first = _install(tmp_path)
    for target in (first.current, first.codex_current, first.openclaw_current):
        target.joinpath("old-marker").write_text(target.name, encoding="utf-8")

    with pytest.raises(RuntimeError, match="synthetic"):
        _install(tmp_path, executor=FakeExecutor(failure="pip install"))

    for target in (first.current, first.codex_current, first.openclaw_current):
        assert target.joinpath("old-marker").is_file()


def test_failed_dependency_upgrade_cannot_mutate_the_active_venv(tmp_path: Path) -> None:
    first = _install(tmp_path)
    active_venv = first.current.parent / "venv"
    active_interpreter = active_venv / "bin" / "python"
    original = active_interpreter.read_bytes()

    class MutatingFailure(FakeExecutor):
        def __call__(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
            super().__call__(command, env=env)
            values = tuple(str(item) for item in command)
            if values[1:4] == ("-m", "pip", "install"):
                Path(values[0]).parent.parent.joinpath("partial-mutation").write_text("bad", encoding="utf-8")
                raise RuntimeError("synthetic partial dependency failure")

    with pytest.raises(RuntimeError, match="partial dependency"):
        _install(tmp_path, executor=MutatingFailure())

    assert active_interpreter.read_bytes() == original
    assert not active_venv.joinpath("partial-mutation").exists()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(first.current))
    assert subprocess.run([str(active_interpreter), "-c", "import playwright; import media_missher_runtime"], env=environment, check=False).returncode == 0
    for name in ("scrape_all.py", "scrape_bilibili.py", "scrape_xhs.py", "scrape_douyin.py", "scrape_weibo.py"):
        assert subprocess.run(
            [str(active_interpreter), str(first.current / "scripts" / name), "--help"],
            env=environment,
            check=False,
            capture_output=True,
        ).returncode == 0


def test_injected_executor_nonzero_result_is_a_hard_failure(tmp_path: Path) -> None:
    class ReturningFailure(FakeExecutor):
        def __call__(self, command: list[str], *, env: dict[str, str] | None = None):
            super().__call__(command, env=env)
            if tuple(str(item) for item in command)[1:4] == ("-m", "pip", "install"):
                return subprocess.CompletedProcess(command, 9)
            return subprocess.CompletedProcess(command, 0)

    with pytest.raises(subprocess.CalledProcessError):
        _install(tmp_path, executor=ReturningFailure())

    assert not (tmp_path / "runtime-home" / "current").exists()


def test_rotation_failure_restores_every_prior_current(tmp_path: Path) -> None:
    first = _install(tmp_path)
    targets = (first.current, first.codex_current, first.openclaw_current)
    for target in targets:
        target.joinpath("old-marker").write_text(target.name, encoding="utf-8")
    real_replace = os.replace

    def fail_openclaw_stage(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        source_path, target_path = Path(source), Path(target)
        if ".staging-" in source_path.name and target_path == first.openclaw_current:
            raise OSError("synthetic rotation failure")
        real_replace(source, target)

    with pytest.raises(OSError, match="synthetic rotation"):
        _install(tmp_path, renamer=fail_openclaw_stage)

    for target in targets:
        assert target.joinpath("old-marker").is_file()


@pytest.mark.parametrize("case", ("home", "codex", "openclaw"))
def test_installer_rejects_symlink_roots(tmp_path: Path, case: str) -> None:
    real = tmp_path / f"real-{case}"
    real.mkdir()
    linked = tmp_path / f"linked-{case}"
    linked.symlink_to(real, target_is_directory=True)
    values = {
        "home": tmp_path / "runtime-home",
        "codex_root": tmp_path / "codex-skills",
        "openclaw_root": tmp_path / "openclaw-skills",
    }
    values[{"home": "home", "codex": "codex_root", "openclaw": "openclaw_root"}[case]] = linked

    with pytest.raises(ValueError, match="symlink"):
        _install(tmp_path, **values)


def test_installer_rejects_broad_and_overlapping_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        _install(tmp_path, home=Path("/"))
    with pytest.raises(ValueError, match="overlap"):
        _install(
            tmp_path,
            home=tmp_path / "shared",
            codex_root=tmp_path / "shared" / "codex",
            openclaw_root=tmp_path / "openclaw",
        )


def test_install_reuses_existing_venv_without_recreating_it(tmp_path: Path) -> None:
    first = _install(tmp_path)
    executor = FakeExecutor()

    _install(tmp_path, executor=executor)

    assert first.current.parent.joinpath("venv", "bin", "python").is_file()
    assert not any(command[1:3] == ("-m", "venv") for command, _ in executor.calls)


def test_runtime_only_never_inspects_or_touches_skill_sources_or_destinations(tmp_path: Path) -> None:
    from tools.install_media_missher import install

    source = tmp_path / "source"
    shutil.copytree(PROJECT_ROOT / "runtime", source / "runtime", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    real_codex = tmp_path / "real-codex"
    real_openclaw = tmp_path / "real-openclaw"
    for root, marker in ((real_codex, "codex-old"), (real_openclaw, "openclaw-old")):
        target = root / "media-missher"
        target.mkdir(parents=True)
        target.joinpath("marker").write_text(marker, encoding="utf-8")
    codex_link = tmp_path / "codex-link"
    openclaw_link = tmp_path / "openclaw-link"
    codex_link.symlink_to(real_codex, target_is_directory=True)
    openclaw_link.symlink_to(real_openclaw, target_is_directory=True)

    result = install(
        source=source,
        home=tmp_path / "runtime-home",
        codex_root=codex_link,
        openclaw_root=openclaw_link,
        executor=FakeExecutor(),
        runtime_only=True,
    )

    assert result.current.joinpath("scripts", "scrape_all.py").is_file()
    assert result.codex_current is None and result.openclaw_current is None
    assert (real_codex / "media-missher" / "marker").read_text(encoding="utf-8") == "codex-old"
    assert (real_openclaw / "media-missher" / "marker").read_text(encoding="utf-8") == "openclaw-old"
    assert not list(real_codex.glob("*.previous-*"))
    assert not list(real_openclaw.glob("*.previous-*"))


def test_installer_cli_exposes_runtime_only_safety_gate() -> None:
    script = PROJECT_ROOT / "tools" / "install_media_missher.py"
    completed = subprocess.run([sys.executable, str(script), "--help"], check=False, capture_output=True, text=True)

    assert completed.returncode == 0
    assert "--runtime-only" in completed.stdout


def test_installer_and_residual_scanner_bootstrap_with_system_python3(tmp_path: Path) -> None:
    system_python = Path("/usr/bin/python3")
    python3 = str(system_python) if system_python.is_file() else shutil.which("python3")
    assert python3 is not None

    installer = subprocess.run(
        [python3, str(PROJECT_ROOT / "tools" / "install_media_missher.py"), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    scanner = subprocess.run(
        [python3, str(PROJECT_ROOT / "tools" / "scan_active_residuals.py"), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert installer.returncode == 0, installer.stderr
    assert scanner.returncode == 0, scanner.stderr
