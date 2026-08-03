#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import stat
import subprocess
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse


ENTRYPOINTS = ("scrape_all.py", "scrape_bilibili.py", "scrape_xhs.py", "scrape_douyin.py", "scrape_weibo.py")
RELEASE_MARKER = ".media-missher-release"
OWNER_MARKER = ".media-missher-owner.json"
INSTALL_LOCK = ".media-missher-install.lock"
OWNER_PAYLOAD = {"name": "media-missher-runtime-home", "schema": 1}


def runtime_home() -> Path:
    configured = os.environ.get("MEDIA_MISSHER_HOME")
    return (Path(configured).expanduser() if configured else Path.home() / ".local" / "share" / "media-missher").absolute()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the shared Media@Missher runtime without collecting data.")
    parser.add_argument("--json", action="store_true", help="Print the complete JSON report")
    parser.add_argument("--live", action="store_true", help="Probe the existing Chrome CDP endpoint")
    parser.add_argument("--cdp-url", default=os.environ.get("MEDIA_MISSHER_CDP_URL", "http://127.0.0.1:9222"))
    parser.add_argument("--timeout", type=_positive_timeout, default=10.0, help="Bound each subprocess and live probe")
    return parser


def _positive_timeout(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and positive")
    return result


def _run_check(runner, command: list[str], *, environment: dict[str, str], timeout: float):
    try:
        return runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _reject_symlink_components(path: Path, label: str) -> None:
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink")


@contextmanager
def _shared_install_lock(home: Path, timeout: float):
    lock = home / INSTALL_LOCK
    if lock.is_symlink():
        raise ValueError("installation lock is a symlink")
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("installation lock is not a regular file")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for the installer lock")
                time.sleep(0.02)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _probe_state_writable(state: Path) -> tuple[bool, str | None]:
    descriptor: int | None = None
    probe: Path | None = None
    error: str | None = None
    try:
        descriptor, raw_probe = tempfile.mkstemp(prefix=".preflight-", dir=state)
        probe = Path(raw_probe)
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, b"media-missher-preflight\n")
        os.fsync(descriptor)
    except OSError as exc:
        error = f"runtime state write probe failed: {type(exc).__name__}: {exc}"
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                error = f"runtime state write probe close failed: {type(exc).__name__}: {exc}"
        if probe is not None:
            try:
                probe.unlink()
            except OSError as exc:
                error = f"runtime state write probe cleanup failed: {type(exc).__name__}: {exc}"
    return error is None, error


def _read_release(root: Path) -> str | None:
    marker = root / RELEASE_MARKER
    if marker.is_symlink() or not marker.is_file():
        return None
    try:
        value = marker.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return value if value and len(value) <= 128 and not any(character.isspace() for character in value) else None


def _owned_home(home: Path) -> bool:
    marker = home / OWNER_MARKER
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        return stat.S_IMODE(marker.stat().st_mode) == 0o600 and json.loads(marker.read_text(encoding="utf-8")) == OWNER_PAYLOAD
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def inspect_runtime(
    home: Path,
    *,
    live: bool = False,
    cdp_url: str = "http://127.0.0.1:9222",
    timeout: float = 10.0,
    runner=subprocess.run,
    opener=urllib.request.urlopen,
    skill_root: Path | None = None,
) -> dict[str, object]:
    home = Path(home).expanduser().absolute()
    package = Path(skill_root).expanduser().absolute() if skill_root is not None else None
    try:
        _reject_symlink_components(home, "runtime home")
        if package is not None:
            _reject_symlink_components(package, "OpenClaw skill")
    except ValueError as exc:
        return {
            "status": "failed",
            "checks": {"paths_no_symlink": False},
            "errors": [str(exc)],
        }
    if home.is_dir() and not _owned_home(home):
        return {
            "status": "failed",
            "checks": {"home": True, "home_owned": False},
            "errors": ["runtime home ownership marker is missing or invalid"],
        }
    if home.is_dir():
        try:
            with _shared_install_lock(home, timeout):
                return _inspect_runtime_unlocked(
                    home,
                    live=live,
                    cdp_url=cdp_url,
                    timeout=timeout,
                    runner=runner,
                    opener=opener,
                    skill_root=package,
                )
        except (OSError, TimeoutError, ValueError) as exc:
            return {
                "status": "failed",
                "checks": {"install_lock": False},
                "errors": [str(exc)],
            }
    return _inspect_runtime_unlocked(
        home,
        live=live,
        cdp_url=cdp_url,
        timeout=timeout,
        runner=runner,
        opener=opener,
        skill_root=package,
    )


def _inspect_runtime_unlocked(
    home: Path,
    *,
    live: bool,
    cdp_url: str,
    timeout: float,
    runner,
    opener,
    skill_root: Path | None,
) -> dict[str, object]:
    current = home / "current"
    venv = home / "venv"
    state = home / "state"
    interpreter = venv / "bin" / "python"
    scripts = current / "scripts"
    state_mode = stat.S_IMODE(state.stat().st_mode) if state.is_dir() and not state.is_symlink() else None
    state_owner = state.stat().st_uid == os.geteuid() if state.is_dir() and not state.is_symlink() else False
    checks: dict[str, bool] = {
        "home": home.is_dir() and not home.is_symlink(),
        "current": current.is_dir() and not current.is_symlink(),
        "venv": venv.is_dir() and not venv.is_symlink(),
        "state": state.is_dir() and not state.is_symlink(),
        "state_owner": state_owner,
        "state_private": state_mode == 0o700,
        "state_writable": False,
        "home_owned": _owned_home(home),
        "paths_no_symlink": True,
        "interpreter": interpreter.is_file() and os.access(interpreter, os.X_OK),
        "requirements": (current / "requirements.lock").is_file() and not (current / "requirements.lock").is_symlink(),
        "scripts": scripts.is_dir() and not scripts.is_symlink(),
        "entrypoints": all((scripts / name).is_file() and not (scripts / name).is_symlink() for name in ENTRYPOINTS),
    }
    state_probe_error: str | None = None
    if checks["state"] and checks["state_owner"] and checks["state_private"]:
        checks["state_writable"], state_probe_error = _probe_state_writable(state)
    releases = [_read_release(current), _read_release(venv)]
    if skill_root is not None:
        releases.append(_read_release(skill_root))
    checks["release_consistent"] = all(releases) and len(set(releases)) == 1
    checks["python"] = False
    checks["playwright"] = False
    checks["runtime_import"] = False
    checks["entrypoint_help"] = False
    if checks["interpreter"] and checks["current"] and checks["venv"]:
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(current)}
        version = _run_check(
            runner,
            [str(interpreter), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
            environment=environment,
            timeout=timeout,
        )
        if version is not None and version.returncode == 0:
            try:
                major, minor, *_ = (int(item) for item in version.stdout.strip().split("."))
                checks["python"] = (major, minor) >= (3, 11)
            except (TypeError, ValueError):
                pass
        playwright = _run_check(runner, [str(interpreter), "-c", "import playwright"], environment=environment, timeout=timeout)
        imported = _run_check(runner, [str(interpreter), "-c", "import media_missher_runtime"], environment=environment, timeout=timeout)
        checks["playwright"] = playwright is not None and playwright.returncode == 0
        checks["runtime_import"] = imported is not None and imported.returncode == 0
        if checks["entrypoints"]:
            checks["entrypoint_help"] = all(
                (completed := _run_check(
                    runner,
                    [str(interpreter), str(scripts / name), "--help"],
                    environment=environment,
                    timeout=timeout,
                )) is not None and completed.returncode == 0
                for name in ENTRYPOINTS
            )
    if live:
        checks["cdp"] = False
        parsed = urlparse(cdp_url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.username is None and parsed.password is None:
            try:
                with opener(cdp_url.rstrip("/") + "/json/version", timeout=timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                checks["cdp"] = isinstance(payload, dict) and bool(payload.get("Browser")) and bool(payload.get("Protocol-Version"))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
    errors = [name for name, passed in checks.items() if not passed]
    if state_probe_error is not None:
        errors.append(state_probe_error)
    return {"status": "ok" if not errors else "failed", "checks": checks, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = inspect_runtime(
        runtime_home(),
        live=args.live,
        cdp_url=args.cdp_url,
        timeout=args.timeout,
        skill_root=Path(__file__).absolute().parents[1],
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"preflight: {report['status']}")
        for name, passed in report["checks"].items():
            print(f"  {name}: {'ok' if passed else 'failed'}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
