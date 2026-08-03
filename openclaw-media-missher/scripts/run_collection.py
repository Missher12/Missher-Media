#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def runtime_home() -> Path:
    configured = os.environ.get("MEDIA_MISSHER_HOME")
    return (Path(configured).expanduser() if configured else Path.home() / ".local" / "share" / "media-missher").absolute()


def main(argv: list[str] | None = None) -> int:
    home = runtime_home()
    current = home / "current"
    venv = home / "venv"
    scripts = current / "scripts"
    interpreter = venv / "bin" / "python"
    entrypoint = scripts / "scrape_all.py"
    if any(path.is_symlink() for path in (home, current, venv, scripts, entrypoint)):
        print("shared runtime path must not be a symlink", file=sys.stderr)
        return 1
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK) or not entrypoint.is_file():
        print("shared runtime is not installed or is incomplete", file=sys.stderr)
        return 1
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run(
        [str(interpreter), str(entrypoint), *(sys.argv[1:] if argv is None else argv)],
        check=False,
        env=environment,
        timeout=None,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
