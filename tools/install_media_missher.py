from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, Union

try:
    from tools.scan_active_residuals import scan_roots
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from scan_active_residuals import scan_roots


Executor = Callable[..., None]
Renamer = Callable[[Union[str, os.PathLike[str]], Union[str, os.PathLike[str]]], None]
Cleaner = Callable[[Path], None]
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".DS_Store")
_OWNER_MARKER = ".media-missher-owner.json"
_OWNER_PAYLOAD = {"name": "media-missher-runtime-home", "schema": 1}
_RELEASE_MARKER = ".media-missher-release"
_INSTALL_LOCK = ".media-missher-install.lock"


@dataclass(frozen=True)
class InstallResult:
    current: Path
    previous: Path | None
    venv: Path
    venv_previous: Path | None
    state: Path
    codex_current: Path | None
    codex_previous: Path | None
    openclaw_current: Path | None
    openclaw_previous: Path | None


class InstallationRollbackError(RuntimeError):
    def __init__(self, original_error: BaseException, rollback_errors: Sequence[BaseException]) -> None:
        self.original_error = original_error
        self.rollback_errors = tuple(rollback_errors)
        details = "; ".join(f"{type(error).__name__}: {error}" for error in self.rollback_errors)
        super().__init__(f"installation failed and rollback reported errors: {details}")


@dataclass
class _Component:
    stage: Path
    current: Path
    previous: Path
    prior_moved: bool = False
    installed: bool = False


def _default_executor(command: Sequence[str], *, env: Mapping[str, str] | None = None) -> None:
    subprocess.run(list(command), check=True, env=dict(env) if env is not None else None)


def _invoke(executor: Executor, command: Sequence[str], *, env: Mapping[str, str] | None) -> None:
    result = executor(list(command), env=dict(env) if env is not None else None)
    returncode = getattr(result, "returncode", 0)
    if isinstance(returncode, int) and returncode != 0:
        raise subprocess.CalledProcessError(returncode, list(command))


def _clean_subprocess_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PIP_") and key.upper() not in {"PYTHONHOME", "PYTHONPATH"}
    }


def _runtime_python_version(executable: Path) -> tuple[int, int] | None:
    try:
        completed = subprocess.run(
            [str(executable), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=_clean_subprocess_environment(),
        )
        major, minor = (int(part) for part in completed.stdout.strip().split(".", 1))
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        return None
    return (major, minor) if completed.returncode == 0 else None


def select_runtime_python(explicit: Path | str | None) -> Path:
    if explicit is not None:
        candidates = [_absolute(explicit)]
    else:
        names = ("python3.13", "python3.12", "python3.11")
        candidates = [Path(sys.executable).absolute(), Path.home() / ".local" / "bin" / "python3.11"]
        candidates.extend(Path(found).absolute() for name in names if (found := shutil.which(name)))
    seen: set[str] = set()
    for candidate in candidates:
        identity = str(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        version = _runtime_python_version(candidate)
        if version is not None and version >= (3, 11):
            return candidate
    qualifier = f": {explicit}" if explicit is not None else ""
    raise ValueError(f"Python 3.11 or newer is required{qualifier}")


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _has_glob(path: Path) -> bool:
    return any(marker in str(path) for marker in ("*", "?", "[", "]", "{", "}"))


def _reject_symlink_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink")


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _validate_roots(
    source: Path,
    home: Path,
    codex_root: Path | None,
    openclaw_root: Path | None,
    *,
    runtime_only: bool,
) -> None:
    roots = {"source": source, "home": home}
    if not runtime_only:
        if codex_root is None or openclaw_root is None:
            raise ValueError("skill install roots are required")
        roots.update({"codex root": codex_root, "openclaw root": openclaw_root})
    unsafe = {Path("/"), Path.home().absolute()}
    for label, path in roots.items():
        if path in unsafe or _has_glob(path):
            raise ValueError(f"unsafe {label}")
        _reject_symlink_components(path, label)
    install_roots = [("home", home)]
    if not runtime_only:
        assert codex_root is not None and openclaw_root is not None
        install_roots.extend((("codex root", codex_root), ("openclaw root", openclaw_root)))
    for index, (left_label, left) in enumerate(install_roots):
        if _overlaps(source, left):
            raise ValueError(f"source and {left_label} overlap")
        for right_label, right in install_roots[index + 1:]:
            if _overlaps(left, right):
                raise ValueError(f"{left_label} and {right_label} overlap")


def _reject_source_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise ValueError(f"installation source is a symlink: {root.name}")
    if not root.is_dir():
        raise ValueError(f"installation source is missing: {root.name}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"installation source contains a symlink: {path.name}")


def _prepare_directory(path: Path, mode: int = 0o700) -> None:
    if path.is_symlink():
        raise ValueError(f"installation directory is a symlink: {path.name}")
    existed = path.exists()
    path.mkdir(parents=True, mode=mode, exist_ok=True)
    if not existed:
        path.chmod(mode)


def _valid_owner_marker(path: Path) -> bool:
    marker = path / _OWNER_MARKER
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        if (marker.stat().st_mode & 0o777) != 0o600:
            return False
        return json.loads(marker.read_text(encoding="utf-8")) == _OWNER_PAYLOAD
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def _write_owner_marker(path: Path) -> None:
    marker = path / _OWNER_MARKER
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, (json.dumps(_OWNER_PAYLOAD, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        marker.unlink(missing_ok=True)
        raise
    else:
        os.close(descriptor)


def _prepare_owned_runtime_home(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("runtime home contains a symlink")
    if path.exists() and not path.is_dir():
        raise ValueError("runtime home is not a directory")
    if path.exists():
        entries = list(path.iterdir())
        if entries and not _valid_owner_marker(path):
            raise ValueError("runtime home ownership marker is missing or invalid")
        if not entries:
            path.chmod(0o700)
            _write_owner_marker(path)
    else:
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
        _write_owner_marker(path)
    if not _valid_owner_marker(path):
        raise ValueError("runtime home ownership marker is missing or invalid")


def _copy_source(source: Path, target: Path) -> None:
    _reject_source_symlinks(source)
    shutil.copytree(source, target, ignore=_IGNORE)


def _write_release_marker(root: Path, release: str) -> None:
    marker = root / _RELEASE_MARKER
    if marker.is_symlink():
        raise ValueError(f"release marker is a symlink: {root.name}")
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, (release + "\n").encode("ascii"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _clean_owned(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        shutil.rmtree(path)


def _acquire_install_lock(home: Path) -> int:
    lock = home / _INSTALL_LOCK
    if lock.is_symlink():
        raise ValueError("installation lock is a symlink")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("installation lock is not a regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _release_install_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _validate_staging(runtime_stage: Path, interpreter: Path, executor: Executor) -> None:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(runtime_stage),
    }
    _invoke(
        executor,
        [str(interpreter), "-c", "import playwright; import media_missher_runtime"],
        env=environment,
    )
    for name in ("scrape_all.py", "scrape_bilibili.py", "scrape_xhs.py", "scrape_douyin.py", "scrape_weibo.py"):
        _invoke(executor, [str(interpreter), str(runtime_stage / "scripts" / name), "--help"], env=environment)


def _rotate(
    components: Sequence[_Component],
    renamer: Renamer,
    cleaner: Cleaner,
    release: str,
) -> None:
    try:
        for component in components:
            if component.current.is_symlink():
                raise ValueError(f"current target is a symlink: {component.current.name}")
            if component.current.exists():
                renamer(component.current, component.previous)
                component.prior_moved = True
            renamer(component.stage, component.current)
            component.installed = True
    except BaseException as original_error:
        rollback_errors: list[BaseException] = []
        failed_releases: list[Path] = []
        for component in reversed(components):
            if component.installed and component.current.exists():
                failed = component.current.parent / f".{component.current.name}.failed-{release}"
                try:
                    renamer(component.current, failed)
                    failed_releases.append(failed)
                    component.installed = False
                except BaseException as exc:
                    rollback_errors.append(exc)
            if component.prior_moved and component.previous.exists() and not component.current.exists():
                try:
                    renamer(component.previous, component.current)
                    component.prior_moved = False
                except BaseException as exc:
                    rollback_errors.append(exc)
            elif component.prior_moved and component.current.exists():
                rollback_errors.append(RuntimeError(f"rollback target remains occupied: {component.current}"))
        for failed in failed_releases:
            try:
                cleaner(failed)
            except BaseException as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise InstallationRollbackError(original_error, rollback_errors) from original_error
        raise


def install(
    *,
    source: Path | str,
    home: Path | str,
    codex_root: Path | str | None = None,
    openclaw_root: Path | str | None = None,
    executor: Executor = _default_executor,
    renamer: Renamer = os.replace,
    cleaner: Cleaner = _clean_owned,
    runtime_only: bool = False,
    python: Path | str | None = None,
) -> InstallResult:
    source_path = _absolute(source)
    runtime_home = _absolute(home)
    codex_parent = None if runtime_only or codex_root is None else _absolute(codex_root)
    openclaw_parent = None if runtime_only or openclaw_root is None else _absolute(openclaw_root)
    _validate_roots(source_path, runtime_home, codex_parent, openclaw_parent, runtime_only=runtime_only)

    runtime_source = source_path / "runtime"
    package_sources = [] if runtime_only else [source_path / "media-missher", source_path / "openclaw-media-missher"]
    for item in (runtime_source, *package_sources):
        _reject_source_symlinks(item)
    runtime_python = select_runtime_python(python)

    _prepare_owned_runtime_home(runtime_home)
    install_parents: list[Path] = []
    if not runtime_only:
        assert codex_parent is not None and openclaw_parent is not None
        install_parents.extend((codex_parent, openclaw_parent))
    for directory in install_parents:
        _prepare_directory(directory)
    state = runtime_home / "state"
    _prepare_directory(state)
    state.chmod(0o700)

    release = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + f"-{secrets.token_hex(4)}"
    runtime_stage = runtime_home / f".current.staging-{release}"
    venv_stage = runtime_home / f".venv.staging-{release}"
    package_stages: list[Path] = []
    if not runtime_only:
        assert codex_parent is not None and openclaw_parent is not None
        package_stages = [
            codex_parent / f".media-missher.staging-{release}",
            openclaw_parent / f".media-missher.staging-{release}",
        ]
    stages = (runtime_stage, venv_stage, *package_stages)
    lock_descriptor = _acquire_install_lock(runtime_home)
    try:
        _copy_source(runtime_source, runtime_stage)
        for package_source, package_stage in zip(package_sources, package_stages):
            _copy_source(package_source, package_stage)
        findings = scan_roots((runtime_stage, *package_stages))
        if findings:
            raise ValueError("staged installation contains forbidden residuals")

        venv = runtime_home / "venv"
        subprocess_environment = _clean_subprocess_environment()
        if venv.is_symlink():
            raise ValueError("runtime venv is a symlink")
        if venv.exists():
            if not venv.is_dir():
                raise ValueError("runtime venv is not a directory")
            shutil.copytree(venv, venv_stage, symlinks=True, ignore=_IGNORE)
        interpreter = venv_stage / "bin" / "python"
        staged_version = _runtime_python_version(interpreter) if venv_stage.exists() else None
        if staged_version is None or staged_version < (3, 11):
            _clean_owned(venv_stage)
            _invoke(
                executor,
                [str(runtime_python), "-m", "venv", str(venv_stage)],
                env=subprocess_environment,
            )
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            raise ValueError("runtime interpreter is missing or not executable")
        _invoke(
            executor,
            [
                str(interpreter),
                "-m",
                "pip",
                "--isolated",
                "--require-virtualenv",
                "install",
                "--disable-pip-version-check",
                "--requirement",
                str(runtime_stage / "requirements.lock"),
            ],
            env=subprocess_environment,
        )
        _validate_staging(runtime_stage, interpreter, executor)
        for stage in stages:
            _write_release_marker(stage, release)
        if scan_roots(stages):
            raise ValueError("installed runtime contains forbidden residuals")

        components = [
            _Component(runtime_stage, runtime_home / "current", runtime_home / f"previous-{release}"),
            _Component(venv_stage, venv, runtime_home / f"venv.previous-{release}"),
        ]
        if not runtime_only:
            assert codex_parent is not None and openclaw_parent is not None
            components.extend(
                (
                    _Component(package_stages[0], codex_parent / "media-missher", codex_parent / f"media-missher.previous-{release}"),
                    _Component(package_stages[1], openclaw_parent / "media-missher", openclaw_parent / f"media-missher.previous-{release}"),
                )
            )
        _rotate(components, renamer, cleaner, release)
        return InstallResult(
            current=components[0].current.resolve(),
            previous=components[0].previous.resolve() if components[0].prior_moved else None,
            venv=components[1].current.resolve(),
            venv_previous=components[1].previous.resolve() if components[1].prior_moved else None,
            state=state.resolve(),
            codex_current=components[2].current.resolve() if not runtime_only else None,
            codex_previous=components[2].previous.resolve() if not runtime_only and components[2].prior_moved else None,
            openclaw_current=components[3].current.resolve() if not runtime_only else None,
            openclaw_previous=components[3].previous.resolve() if not runtime_only and components[3].prior_moved else None,
        )
    finally:
        try:
            for stage in stages:
                _clean_owned(stage)
        finally:
            _release_install_lock(lock_descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atomically install the shared Media@Missher runtime and compact skills.")
    project = Path(__file__).resolve().parents[1]
    parser.add_argument("--source", type=Path, default=project)
    parser.add_argument("--home", type=Path, default=Path.home() / ".local" / "share" / "media-missher")
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--openclaw-root", type=Path, default=Path.home() / ".openclaw" / "workspace" / "skills")
    parser.add_argument("--runtime-only", action="store_true", help="Install only the shared runtime and dependency environment")
    parser.add_argument("--python", type=Path, help="Python 3.11+ interpreter used to create the runtime environment")
    args = parser.parse_args(argv)
    result = install(
        source=args.source,
        home=args.home,
        codex_root=args.codex_root,
        openclaw_root=args.openclaw_root,
        runtime_only=args.runtime_only,
        python=args.python,
    )
    print(json.dumps({"current": str(result.current), "state": str(result.state)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["InstallationRollbackError", "InstallResult", "install", "main", "select_runtime_python"]
