#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import stat
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ENTRYPOINTS = ("scrape_all.py", "scrape_bilibili.py", "scrape_xhs.py", "scrape_douyin.py", "scrape_weibo.py")


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


def inspect_runtime(
    home: Path,
    *,
    live: bool = False,
    cdp_url: str = "http://127.0.0.1:9222",
    timeout: float = 10.0,
    runner=subprocess.run,
    opener=urllib.request.urlopen,
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
        "state_writable": bool(state_owner and state_mode is not None and state_mode & 0o300 == 0o300),
        "interpreter": interpreter.is_file() and os.access(interpreter, os.X_OK),
        "requirements": (current / "requirements.lock").is_file() and not (current / "requirements.lock").is_symlink(),
        "scripts": scripts.is_dir() and not scripts.is_symlink(),
        "entrypoints": all((scripts / name).is_file() and not (scripts / name).is_symlink() for name in ENTRYPOINTS),
    }
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
    return {"status": "ok" if not errors else "failed", "checks": checks, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = inspect_runtime(
        runtime_home(),
        live=args.live,
        cdp_url=args.cdp_url,
        timeout=args.timeout,
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
