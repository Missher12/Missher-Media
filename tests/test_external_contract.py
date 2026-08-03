import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from media_missher_adapter import CollectionRequest, build_engine_command, resolve_runtime_layout


def make_runtime_layout(fake_engine_root):
    home = fake_engine_root.parent / "runtime-home"
    shutil.copytree(fake_engine_root / "scripts", home / "current" / "scripts")
    interpreter = home / "venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(str(Path(sys.executable).resolve()))} \"$@\"\n",
        encoding="utf-8",
    )
    interpreter.chmod(0o700)
    (home / "state").mkdir(mode=0o700)
    return resolve_runtime_layout(environ={"MEDIA_MISSHER_HOME": str(home)})


def assert_help_accepts(command, layout):
    completed = subprocess.run(
        [command.argv[0], str(command.script), "--help"],
        cwd=layout.current,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    flags = {item for item in command.argv[2:] if item.startswith("--")}
    assert flags.issubset(set(completed.stdout.split()))


@pytest.mark.parametrize("platform", ["bilibili", "xhs", "douyin", "weibo"])
def test_search_entrypoint_help_matches_adapter_contract(platform, fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    command = build_engine_command(
        CollectionRequest(platforms=(platform,), count=1, search="synthetic topic"),
        tmp_path,
        layout=layout,
    )
    assert command.script == layout.current / "scripts" / f"scrape_{platform}.py"
    assert_help_accepts(command, layout)


def test_controller_help_matches_adapter_contract(fake_engine_root, tmp_path):
    layout = make_runtime_layout(fake_engine_root)
    command = build_engine_command(
        CollectionRequest(
            platforms=("bilibili", "xhs", "douyin", "weibo"),
            count=1,
            platform_counts={"xhs": 2},
            bilibili_complete=True,
            xhs_complete=True,
            xhs_comments=1,
        ),
        tmp_path,
        layout=layout,
    )
    assert command.script == layout.current / "scripts" / "scrape_all.py"
    assert_help_accepts(command, layout)
