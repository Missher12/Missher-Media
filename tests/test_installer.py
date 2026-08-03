from __future__ import annotations

import fcntl
import json
import os
import pwd
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
                "if [ \"$1\" = \"-c\" ]; then\n"
                "  case \"$2\" in\n"
                f"    *version_info*) printf '%s\\n' '{sys.version_info[0]}.{sys.version_info[1]}'; exit 0 ;;\n"
                "    *) exit 0 ;;\n"
                "  esac\n"
                "fi\n"
                f"exec {shlex.quote(str(Path(sys.executable).resolve()))} \"$@\"\n",
                encoding="utf-8",
            )
            interpreter.chmod(0o700)
        pip_install = values[1:3] == ("-m", "pip") and "install" in values
        if self.failure is not None and (
            self.failure in " ".join(values) or (self.failure == "pip install" and pip_install)
        ):
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
    pip_calls = [command for command in commands if command[1:3] == ("-m", "pip") and "install" in command]
    assert len(pip_calls) == 1
    assert "--requirement" in pip_calls[0]
    assert Path(pip_calls[0][pip_calls[0].index("--requirement") + 1]).name == "requirements.lock"
    assert any(command[1:3] == ("-c", "import playwright; import media_missher_runtime") for command in commands)
    help_scripts = {Path(command[1]).name for command in commands if len(command) >= 3 and command[-1] == "--help"}
    assert help_scripts == {"scrape_all.py", "scrape_bilibili.py", "scrape_xhs.py", "scrape_douyin.py", "scrape_weibo.py"}


def test_install_writes_one_release_id_to_all_four_components(tmp_path: Path) -> None:
    result = _install(tmp_path)
    marker_name = ".media-missher-release"
    components = (result.current, result.venv, result.codex_current, result.openclaw_current)

    release_ids = {component.joinpath(marker_name).read_text(encoding="utf-8").strip() for component in components}

    assert len(release_ids) == 1
    assert all(stat.S_IMODE(component.joinpath(marker_name).stat().st_mode) == 0o600 for component in components)


def test_installer_holds_an_exclusive_lock_through_rotation(tmp_path: Path) -> None:
    first = _install(tmp_path)
    lock_path = first.current.parent / ".media-missher-install.lock"
    real_replace = os.replace
    shared_lock_was_blocked = False

    def observe_runtime_cutover(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        nonlocal shared_lock_was_blocked
        source_path, target_path = Path(source), Path(target)
        real_replace(source, target)
        if ".current.staging-" in source_path.name and target_path == first.current:
            descriptor = os.open(lock_path, os.O_RDONLY)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                shared_lock_was_blocked = True
            finally:
                os.close(descriptor)

    _install(tmp_path, renamer=observe_runtime_cutover)

    assert shared_lock_was_blocked is True


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


def test_upgrade_moves_prior_skills_outside_discovery_roots_into_private_recovery(
    tmp_path: Path,
) -> None:
    from tools.scan_active_residuals import scan_roots

    first = _install(tmp_path)
    obsolete_term = "".join(("Media", "Crawler"))
    for skill in (first.codex_current, first.openclaw_current):
        legacy_engine = skill / "engine"
        legacy_engine.mkdir()
        legacy_engine.joinpath("legacy.py").write_text(
            f"old skill from {obsolete_term}\n", encoding="utf-8"
        )

    upgraded = _install(tmp_path)

    codex_root = tmp_path / "codex-skills"
    openclaw_root = tmp_path / "openclaw-skills"
    assert {path.name for path in codex_root.iterdir()} == {"media-missher"}
    assert {path.name for path in openclaw_root.iterdir()} == {"media-missher"}
    assert upgraded.codex_previous is not None
    assert upgraded.openclaw_previous is not None
    assert codex_root not in upgraded.codex_previous.parents
    assert openclaw_root not in upgraded.openclaw_previous.parents

    recovery = tmp_path / "runtime-home" / "recovery"
    assert upgraded.codex_previous.parent == recovery / "codex"
    assert upgraded.openclaw_previous.parent == recovery / "openclaw"
    assert upgraded.codex_previous.joinpath("engine", "legacy.py").is_file()
    assert upgraded.openclaw_previous.joinpath("engine", "legacy.py").is_file()
    assert scan_roots((codex_root, openclaw_root)) == []
    assert {finding.term for finding in scan_roots((recovery,))} == {obsolete_term}
    for private_directory in (recovery, recovery / "codex", recovery / "openclaw"):
        assert stat.S_IMODE(private_directory.stat().st_mode) == 0o700


def test_upgrade_restores_exact_private_modes_on_existing_recovery_directories(
    tmp_path: Path,
) -> None:
    _install(tmp_path)
    recovery = tmp_path / "runtime-home" / "recovery"
    for private_directory in (recovery, recovery / "codex", recovery / "openclaw"):
        private_directory.chmod(0o755)

    _install(tmp_path)

    for private_directory in (recovery, recovery / "codex", recovery / "openclaw"):
        assert stat.S_IMODE(private_directory.stat().st_mode) == 0o700


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
            if values[1:3] == ("-m", "pip") and "install" in values:
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
            values = tuple(str(item) for item in command)
            if values[1:3] == ("-m", "pip") and "install" in values:
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
    assert {path.name for path in (tmp_path / "codex-skills").iterdir()} == {
        "media-missher"
    }
    assert {path.name for path in (tmp_path / "openclaw-skills").iterdir()} == {
        "media-missher"
    }
    recovery = tmp_path / "runtime-home" / "recovery"
    assert list((recovery / "codex").iterdir()) == []
    assert list((recovery / "openclaw").iterdir()) == []


def test_rollback_restores_every_old_target_before_collecting_cleanup_failures(tmp_path: Path) -> None:
    import tools.install_media_missher as installer

    first = _install(tmp_path)
    targets = (first.current, first.current.parent / "venv", first.codex_current, first.openclaw_current)
    for target in targets:
        target.joinpath("old-marker").write_text(target.name, encoding="utf-8")
    real_replace = os.replace
    cleanup_attempts: list[Path] = []

    def fail_openclaw_stage(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        source_path, target_path = Path(source), Path(target)
        if ".staging-" in source_path.name and target_path == first.openclaw_current:
            raise OSError("synthetic forward failure")
        real_replace(source, target)

    def fail_failed_release_cleanup(path: Path) -> None:
        if ".failed-" in path.name:
            cleanup_attempts.append(path)
            raise OSError(f"cleanup failure {len(cleanup_attempts)}")
        installer._clean_owned(path)

    with pytest.raises(installer.InstallationRollbackError) as caught:
        _install(
            tmp_path,
            renamer=fail_openclaw_stage,
            cleaner=fail_failed_release_cleanup,
        )

    assert len(cleanup_attempts) == 3
    assert len(caught.value.rollback_errors) == 3
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


def test_installer_rejects_an_unowned_nonempty_runtime_home_without_mutating_it(tmp_path: Path) -> None:
    home = tmp_path / "Documents"
    unrelated = home / "current" / "owner-file"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("unrelated", encoding="utf-8")
    home.chmod(0o755)
    executor = FakeExecutor()

    with pytest.raises(ValueError, match="ownership"):
        _install(tmp_path, home=home, executor=executor)

    assert unrelated.read_text(encoding="utf-8") == "unrelated"
    assert stat.S_IMODE(home.stat().st_mode) == 0o755
    assert executor.calls == []


def test_installer_marks_a_dedicated_home_and_requires_the_marker_on_upgrade(tmp_path: Path) -> None:
    first = _install(tmp_path)
    marker = first.current.parent / ".media-missher-owner.json"

    assert marker.is_file() and not marker.is_symlink()
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    marker.unlink()

    with pytest.raises(ValueError, match="ownership"):
        _install(tmp_path)


def test_install_reuses_existing_venv_without_recreating_it(tmp_path: Path) -> None:
    first = _install(tmp_path)
    executor = FakeExecutor()

    _install(tmp_path, executor=executor)

    assert first.current.parent.joinpath("venv", "bin", "python").is_file()
    assert not any(command[1:3] == ("-m", "venv") for command, _ in executor.calls)


@pytest.mark.parametrize("old_version", ("3.9", "3.10"))
def test_upgrade_rebuilds_only_the_staged_venv_when_existing_python_is_too_old(
    tmp_path: Path,
    old_version: str,
) -> None:
    first = _install(tmp_path)
    active_interpreter = first.venv / "bin" / "python"
    active_interpreter.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then\n"
        "  case \"$2\" in\n"
        f"    *version_info*) printf '%s\\n' '{old_version}'; exit 0 ;;\n"
        "  esac\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    active_interpreter.chmod(0o700)
    old_bytes = active_interpreter.read_bytes()
    executor = FakeExecutor()

    upgraded = _install(tmp_path, executor=executor)

    assert any(command[1:3] == ("-m", "venv") for command, _ in executor.calls)
    assert upgraded.venv_previous is not None
    assert upgraded.venv_previous.joinpath("bin", "python").read_bytes() == old_bytes
    assert upgraded.venv.joinpath("bin", "python").read_bytes() != old_bytes


def test_failed_old_venv_rebuild_leaves_the_active_venv_unchanged(tmp_path: Path) -> None:
    first = _install(tmp_path)
    active_interpreter = first.venv / "bin" / "python"
    active_interpreter.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then printf '%s\\n' '3.10'; exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    active_interpreter.chmod(0o700)
    old_bytes = active_interpreter.read_bytes()

    with pytest.raises(RuntimeError, match="synthetic"):
        _install(tmp_path, executor=FakeExecutor(failure="pip install"))

    assert first.venv.joinpath("bin", "python").read_bytes() == old_bytes


def test_venv_and_pip_use_isolated_sanitized_subprocesses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIP_TARGET", str(tmp_path / "outside-target"))
    monkeypatch.setenv("PIP_CONFIG_FILE", str(tmp_path / "pip.conf"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "outside-pythonpath"))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "outside-pythonhome"))
    executor = FakeExecutor()

    _install(tmp_path, executor=executor)

    venv_call = next(item for item in executor.calls if item[0][1:3] == ("-m", "venv"))
    pip_call = next(item for item in executor.calls if item[0][1:3] == ("-m", "pip"))
    assert "--isolated" in pip_call[0]
    assert "--require-virtualenv" in pip_call[0]
    for _, environment in (venv_call, pip_call):
        assert environment is not None
        assert "PYTHONPATH" not in environment
        assert "PYTHONHOME" not in environment
        assert not any(name.startswith("PIP_") for name in environment)
    assert not (tmp_path / "outside-target").exists()


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


def test_installer_rejects_a_symlinked_source_package_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "runtime").symlink_to(PROJECT_ROOT / "runtime", target_is_directory=True)

    with pytest.raises(ValueError, match="source.*symlink|symlink"):
        _install(tmp_path, source=source, runtime_only=True)


def test_installer_rechecks_source_symlinks_immediately_before_copy(tmp_path: Path, monkeypatch) -> None:
    import tools.install_media_missher as installer

    source = tmp_path / "source"
    shutil.copytree(PROJECT_ROOT / "runtime", source / "runtime")
    runtime_source = source / "runtime"
    saved_runtime = source / "runtime-real"
    real_reject = installer._reject_source_symlinks
    swapped = False

    def swap_after_initial_validation(root: Path) -> None:
        nonlocal swapped
        real_reject(root)
        if Path(root) == runtime_source and not swapped:
            runtime_source.rename(saved_runtime)
            runtime_source.symlink_to(saved_runtime, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(installer, "_reject_source_symlinks", swap_after_initial_validation)

    with pytest.raises(ValueError, match="symlink"):
        installer.install(
            source=source,
            home=tmp_path / "runtime-home",
            runtime_only=True,
            executor=FakeExecutor(),
        )


def test_installer_cli_exposes_runtime_only_safety_gate() -> None:
    script = PROJECT_ROOT / "tools" / "install_media_missher.py"
    completed = subprocess.run([sys.executable, str(script), "--help"], check=False, capture_output=True, text=True)

    assert completed.returncode == 0
    assert "--runtime-only" in completed.stdout
    assert "--python" in completed.stdout


def test_installer_cli_reports_exact_current_and_recovery_paths(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import tools.install_media_missher as installer

    _install(tmp_path)
    result = _install(tmp_path)
    monkeypatch.setattr(installer, "install", lambda **_kwargs: result)

    assert installer.main([]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "current": str(result.current),
        "previous": str(result.previous),
        "venv": str(result.venv),
        "venv_previous": str(result.venv_previous),
        "state": str(result.state),
        "codex_current": str(result.codex_current),
        "codex_previous": str(result.codex_previous),
        "openclaw_current": str(result.openclaw_current),
        "openclaw_previous": str(result.openclaw_previous),
    }


def test_system_python_bootstrap_discovers_a_python311_runtime() -> None:
    system_python = Path("/usr/bin/python3")
    if not system_python.is_file():
        pytest.skip("macOS system Python is unavailable")
    user_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    completed = subprocess.run(
        [
            str(system_python),
            "-c",
            (
                "from tools.install_media_missher import select_runtime_python; "
                "print(select_runtime_python(None))"
            ),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(user_home), "PYTHONDONTWRITEBYTECODE": "1"},
    )

    assert completed.returncode == 0, completed.stderr
    selected = Path(completed.stdout.strip())
    local_python = user_home / ".local" / "bin" / "python3.11"
    if local_python.is_file():
        assert selected == local_python
    version = subprocess.run(
        [str(selected), "-c", "import sys; print(sys.version_info[:2] >= (3, 11))"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert version.returncode == 0
    assert version.stdout.strip() == "True"


def test_system_python_driven_install_uses_the_discovered_python311(tmp_path: Path) -> None:
    system_python = Path("/usr/bin/python3")
    user_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    local_python = user_home / ".local" / "bin" / "python3.11"
    if not system_python.is_file() or not local_python.is_file():
        pytest.skip("system Python or the managed Python 3.11 runtime is unavailable")
    program = "\n".join(
        (
            "import subprocess",
            "from pathlib import Path",
            "from tools.install_media_missher import install",
            "calls = []",
            "def execute(command, *, env=None):",
            "    values = [str(item) for item in command]",
            "    calls.append(values)",
            "    if values[1:3] == ['-m', 'venv']:",
            "        interpreter = Path(values[3]) / 'bin' / 'python'",
            "        interpreter.parent.mkdir(parents=True)",
            "        interpreter.write_text('#!/bin/sh\\nexit 0\\n', encoding='utf-8')",
            "        interpreter.chmod(0o700)",
            "    return subprocess.CompletedProcess(values, 0)",
            f"install(source=Path({str(PROJECT_ROOT)!r}), home=Path({str(tmp_path / 'runtime-home')!r}), runtime_only=True, executor=execute)",
            "print(calls[0][0])",
        )
    )

    completed = subprocess.run(
        [str(system_python), "-c", program],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(user_home), "PYTHONDONTWRITEBYTECODE": "1"},
    )

    assert completed.returncode == 0, completed.stderr
    assert Path(completed.stdout.strip()) == local_python


def test_explicit_old_python_fails_before_creating_the_runtime_home(tmp_path: Path) -> None:
    system_python = Path("/usr/bin/python3")
    if not system_python.is_file():
        pytest.skip("macOS system Python is unavailable")
    version = subprocess.run(
        [str(system_python), "-c", "import sys; print(sys.version_info[:2] < (3, 11))"],
        check=False,
        capture_output=True,
        text=True,
    )
    if version.stdout.strip() != "True":
        pytest.skip("system Python is already 3.11+")
    executor = FakeExecutor()
    home = tmp_path / "runtime-home"

    with pytest.raises(ValueError, match="3.11"):
        _install(tmp_path, home=home, python=system_python, executor=executor)

    assert not home.exists()
    assert executor.calls == []


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
