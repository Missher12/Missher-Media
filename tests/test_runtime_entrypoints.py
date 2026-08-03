from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_entrypoint_help_commands_work_from_a_special_copied_path(tmp_path: Path) -> None:
    copied = tmp_path / "Media @ clean runtime"
    shutil.copytree(ROOT / "runtime", copied)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    for name in ("scrape_all.py", "scrape_bilibili.py", "scrape_xhs.py", "scrape_douyin.py", "scrape_weibo.py"):
        completed = subprocess.run(
            [sys.executable, str(copied / "scripts" / name), "--help"],
            cwd=tmp_path,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 0, (name, completed.stdout, completed.stderr)
        assert "output" in completed.stdout.casefold()


def test_entrypoints_are_portable_and_dependency_is_exactly_pinned() -> None:
    scripts = ROOT / "runtime" / "scripts"
    for path in scripts.glob("scrape_*.py"):
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "Path(__file__).resolve()" in text
        assert stat.S_IMODE(path.stat().st_mode) & 0o111

    assert (ROOT / "runtime" / "requirements.lock").read_text(encoding="utf-8").splitlines() == ["playwright==1.45.0"]
