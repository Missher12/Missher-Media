#!/usr/bin/env python3
from __future__ import annotations

import os
import fcntl
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path


RELEASE_MARKER = ".media-missher-release"
INSTALL_LOCK = ".media-missher-install.lock"
COLLECTION_LOCK = ".media-missher-collection.lock"


def runtime_home() -> Path:
    configured = os.environ.get("MEDIA_MISSHER_HOME")
    return (Path(configured).expanduser() if configured else Path.home() / ".local" / "share" / "media-missher").absolute()


def _reject_symlink_components(path: Path, label: str) -> None:
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink")


def _read_release(root: Path) -> str | None:
    marker = root / RELEASE_MARKER
    if marker.is_symlink() or not marker.is_file():
        return None
    try:
        value = marker.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return value if value and len(value) <= 128 and not any(character.isspace() for character in value) else None


@contextmanager
def _shared_install_lock(home: Path):
    lock = home / INSTALL_LOCK
    if lock.is_symlink():
        raise ValueError("installation lock is a symlink")
    descriptor = os.open(lock, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("installation lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


@contextmanager
def _exclusive_collection_lock(home: Path):
    lock = home / COLLECTION_LOCK
    _reject_symlink_components(lock, "collection lock")
    flags = (
        os.O_RDWR
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(lock, flags | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(descriptor, 0o600)
    except FileExistsError:
        descriptor = os.open(lock, flags)
    acquired = False
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (hasattr(os, "getuid") and opened.st_uid != os.getuid())
        ):
            raise ValueError("collection lock must be a private owned regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another Media@Missher collection is already running") from exc
        acquired = True
        yield
    finally:
        try:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    home = runtime_home()
    skill = Path(__file__).absolute().parents[1]
    current = home / "current"
    venv = home / "venv"
    scripts = current / "scripts"
    interpreter = venv / "bin" / "python"
    entrypoint = scripts / "scrape_all.py"
    try:
        for path, label in ((home, "runtime home"), (current, "runtime current"), (venv, "runtime venv"), (scripts, "runtime scripts"), (entrypoint, "runtime entrypoint"), (skill, "OpenClaw skill")):
            _reject_symlink_components(path, label)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        install_lease = _shared_install_lock(home)
        install_lease.__enter__()
    except (OSError, ValueError) as exc:
        print(f"shared runtime install lock is unavailable: {exc}", file=sys.stderr)
        return 1
    try:
        releases = (_read_release(current), _read_release(venv), _read_release(skill))
        if not all(releases) or len(set(releases)) != 1:
            print("shared runtime release markers are missing or inconsistent", file=sys.stderr)
            return 1
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK) or not entrypoint.is_file():
            print("shared runtime is not installed or is incomplete", file=sys.stderr)
            return 1
        try:
            with _exclusive_collection_lock(home):
                environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
                completed = subprocess.run(
                    [str(interpreter), str(entrypoint), *(sys.argv[1:] if argv is None else argv)],
                    check=False,
                    env=environment,
                    timeout=None,
                )
                return completed.returncode
        except (OSError, ValueError) as exc:
            print(f"collection lock is unavailable: {exc}", file=sys.stderr)
            return 1
    finally:
        install_lease.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
