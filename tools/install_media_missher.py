from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
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
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".DS_Store")


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


def _copy_source(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=_IGNORE)


def _clean_owned(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        shutil.rmtree(path)


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


def _rotate(components: Sequence[_Component], renamer: Renamer, release: str) -> None:
    try:
        for component in components:
            if component.current.is_symlink():
                raise ValueError(f"current target is a symlink: {component.current.name}")
            if component.current.exists():
                renamer(component.current, component.previous)
                component.prior_moved = True
            try:
                renamer(component.stage, component.current)
                component.installed = True
            except BaseException:
                if component.prior_moved and component.previous.exists() and not component.current.exists():
                    renamer(component.previous, component.current)
                    component.prior_moved = False
                raise
    except BaseException:
        for component in reversed(components):
            if component.installed and component.current.exists():
                failed = component.current.parent / f".{component.current.name}.failed-{release}"
                renamer(component.current, failed)
                _clean_owned(failed)
                component.installed = False
            if component.prior_moved and component.previous.exists() and not component.current.exists():
                renamer(component.previous, component.current)
                component.prior_moved = False
        raise


def install(
    *,
    source: Path | str,
    home: Path | str,
    codex_root: Path | str | None = None,
    openclaw_root: Path | str | None = None,
    executor: Executor = _default_executor,
    renamer: Renamer = os.replace,
    runtime_only: bool = False,
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

    install_parents = [runtime_home]
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
    try:
        _copy_source(runtime_source, runtime_stage)
        for package_source, package_stage in zip(package_sources, package_stages):
            _copy_source(package_source, package_stage)
        findings = scan_roots((runtime_stage, *package_stages))
        if findings:
            raise ValueError("staged installation contains forbidden residuals")

        venv = runtime_home / "venv"
        if venv.is_symlink():
            raise ValueError("runtime venv is a symlink")
        if venv.exists():
            if not venv.is_dir():
                raise ValueError("runtime venv is not a directory")
            shutil.copytree(venv, venv_stage, symlinks=True, ignore=_IGNORE)
        else:
            _invoke(executor, [sys.executable, "-m", "venv", str(venv_stage)], env=None)
        interpreter = venv_stage / "bin" / "python"
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            raise ValueError("runtime interpreter is missing or not executable")
        _invoke(
            executor,
            [str(interpreter), "-m", "pip", "install", "--disable-pip-version-check", "--requirement", str(runtime_stage / "requirements.lock")],
            env=None,
        )
        _validate_staging(runtime_stage, interpreter, executor)
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
        _rotate(components, renamer, release)
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
        for stage in stages:
            _clean_owned(stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atomically install the shared Media@Missher runtime and compact skills.")
    project = Path(__file__).resolve().parents[1]
    parser.add_argument("--source", type=Path, default=project)
    parser.add_argument("--home", type=Path, default=Path.home() / ".local" / "share" / "media-missher")
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--openclaw-root", type=Path, default=Path.home() / ".openclaw" / "workspace" / "skills")
    parser.add_argument("--runtime-only", action="store_true", help="Install only the shared runtime and dependency environment")
    args = parser.parse_args(argv)
    result = install(
        source=args.source,
        home=args.home,
        codex_root=args.codex_root,
        openclaw_root=args.openclaw_root,
        runtime_only=args.runtime_only,
    )
    print(json.dumps({"current": str(result.current), "state": str(result.state)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["InstallResult", "install", "main"]
