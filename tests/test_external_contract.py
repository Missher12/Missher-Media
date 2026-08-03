import os
import subprocess
from pathlib import Path

import pytest

from media_missher_adapter import CollectionRequest, build_engine_command


DEFAULT_EXTERNAL_ROOT = Path.home() / ".openclaw" / "workspace" / "skills" / "media-missher"
EXTERNAL_ROOT = Path(
    os.environ.get("MEDIA_MISSHER_CONTRACT_ENGINE_ROOT", DEFAULT_EXTERNAL_ROOT)
).expanduser()


def assert_real_help_accepts(command):
    completed = subprocess.run(
        [command.argv[0], str(command.script), "--help"],
        cwd=EXTERNAL_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert completed.returncode == 0, completed.stderr
    flags = {item for item in command.argv[2:] if item.startswith("--")}
    assert flags.issubset(set(completed.stdout.split()))


@pytest.mark.parametrize("platform", ["bilibili", "xhs", "douyin", "weibo"])
def test_real_search_entrypoint_help_matches_adapter_contract(platform, tmp_path):
    assert EXTERNAL_ROOT.is_dir(), f"external contract root missing: {EXTERNAL_ROOT}"
    command = build_engine_command(
        CollectionRequest(platforms=(platform,), count=1, search="synthetic topic"),
        tmp_path,
        engine_root=EXTERNAL_ROOT,
    )
    assert_real_help_accepts(command)


def test_real_controller_help_matches_adapter_contract(tmp_path):
    assert EXTERNAL_ROOT.is_dir(), f"external contract root missing: {EXTERNAL_ROOT}"
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
        engine_root=EXTERNAL_ROOT,
    )
    assert_real_help_accepts(command)
