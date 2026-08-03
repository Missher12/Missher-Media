import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from media_missher_adapter import CollectionRequest, build_engine_command, resolve_runtime_layout
from runtime.media_missher_runtime.cli import (
    _normalize_legacy_argv,
    _requests_from_args,
    build_parser,
)


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
    home.chmod(0o700)
    owner = home / ".media-missher-owner.json"
    owner.write_text(
        json.dumps({"name": "media-missher-runtime-home", "schema": 1}) + "\n",
        encoding="utf-8",
    )
    owner.chmod(0o600)
    lock = home / ".media-missher-install.lock"
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    for root in (home / "current", home / "venv"):
        marker = root / ".media-missher-release"
        marker.write_text("test-release\n", encoding="ascii")
        marker.chmod(0o600)
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


def test_controller_command_round_trips_through_runtime_parser(
    fake_engine_root, tmp_path
):
    layout = make_runtime_layout(fake_engine_root)
    command = build_engine_command(
        CollectionRequest(
            platforms=("weibo",),
            count=2,
            platform_uids={"weibo": "creator"},
            allow_navigation=True,
        ),
        tmp_path,
        layout=layout,
        cdp_url="http://127.0.0.1:9333",
    )

    parser = build_parser()
    args = parser.parse_args(_normalize_legacy_argv(command.argv[2:]))
    requests = _requests_from_args(parser, args)

    assert args.cdp_url == "http://127.0.0.1:9333"
    assert args.allow_navigation is True
    assert [(request.platform, request.uid, request.count) for request in requests] == [
        ("weibo", "creator", 2)
    ]


def test_search_command_round_trips_without_uid_or_navigation(
    fake_engine_root, tmp_path
):
    layout = make_runtime_layout(fake_engine_root)
    command = build_engine_command(
        CollectionRequest(platforms=("xhs",), count=3, search="topic"),
        tmp_path,
        layout=layout,
        cdp_url="http://127.0.0.1:9444",
    )

    parser = build_parser(fixed_platform="xhs")
    args = parser.parse_args(_normalize_legacy_argv(command.argv[2:]))
    requests = _requests_from_args(parser, args)

    assert args.cdp_url == "http://127.0.0.1:9444"
    assert args.allow_navigation is False
    assert [(request.platform, request.uid, request.keyword) for request in requests] == [
        ("xhs", None, "topic")
    ]
