from pathlib import Path
import json
import subprocess
import sys

import pytest

import run_collection
from media_missher_adapter import (
    CollectionRequest,
    ConfigurationError,
    RuntimeLayout,
    build_engine_command,
)


def creator_request(**overrides):
    values = {"platforms": ("bilibili", "xhs"), "count": 5}
    values.update(overrides)
    return CollectionRequest(**values)


def runtime_layout(fake_engine_root, tmp_path):
    return RuntimeLayout(
        home=fake_engine_root,
        current=fake_engine_root,
        python=fake_engine_root / "engine" / ".venv" / "bin" / "python",
        state=tmp_path / "state",
    )


def test_creator_command_forces_json_and_no_feishu(fake_engine_root, tmp_path):
    staging = tmp_path / "staging"
    command = build_engine_command(
        creator_request(), staging, layout=runtime_layout(fake_engine_root, tmp_path)
    )
    assert command.script.name == "scrape_all.py"
    argv = list(command.argv)
    assert argv[argv.index("--format") + 1] == "json"
    assert argv[argv.index("--output") + 1] == str(staging)
    assert "--no-feishu" in argv
    assert argv[argv.index("--platform") + 1] == "bilibili,xhs"
    assert command.environment["PYTHONDONTWRITEBYTECODE"] == "1"


def test_creator_command_preserves_counts_uids_and_complete_flags(fake_engine_root, tmp_path):
    request = creator_request(
        platform_counts={"bilibili": 2, "xhs": 3},
        platform_uids={"bilibili": "bili-user", "xhs": "xhs-user"},
        bilibili_complete=True,
        xhs_complete=True,
        xhs_comments=4,
        platform_timeout=42,
    )
    argv = build_engine_command(
        request, tmp_path, layout=runtime_layout(fake_engine_root, tmp_path)
    ).argv
    for flag, value in (
        ("--bilibili-count", "2"),
        ("--xhs-count", "3"),
        ("--bilibili-uid", "bili-user"),
        ("--xhs-uid", "xhs-user"),
        ("--xhs-comments", "4"),
        ("--platform-timeout", "42"),
    ):
        assert argv[argv.index(flag) + 1] == value
    assert "--bilibili-complete" in argv
    assert "--xhs-complete" in argv


def test_search_uses_single_platform_entrypoint_and_json(fake_engine_root, tmp_path):
    request = CollectionRequest(
        platforms=("weibo",),
        count=5,
        platform_counts={"weibo": 2},
        search="synthetic topic",
    )
    command = build_engine_command(
        request, tmp_path, layout=runtime_layout(fake_engine_root, tmp_path)
    )
    assert command.script.name == "scrape_weibo.py"
    assert "--search" in command.argv
    assert "--no-feishu" not in command.argv
    assert command.argv[command.argv.index("--format") + 1] == "json"
    assert command.argv[command.argv.index("--count") + 1] == "2"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"platforms": ("invalid",)}, "unknown platform"),
        ({"platforms": ()}, "at least one platform"),
        ({"platforms": ("bilibili",), "count": -1}, "non-negative"),
        ({"platforms": ("bilibili",), "platform_timeout": -1}, "non-negative"),
        ({"platforms": ("bilibili", "xhs"), "search": "topic"}, "one platform"),
        ({"platforms": ("bilibili",), "search": "topic", "complete": True}, "complete"),
        ({"platforms": ("weibo",), "xhs_comments": 1}, "xhs"),
        ({"platforms": ("bilibili",), "platform_counts": {"weibo": 1}}, "selected"),
        ({"platforms": ("bilibili",), "count": 0}, "explicit"),
    ],
)
def test_invalid_requests_fail_before_runtime(kwargs, message):
    with pytest.raises(ConfigurationError, match=message):
        CollectionRequest(**kwargs)


def test_count_zero_requires_explicit_safe_intent():
    request = CollectionRequest(
        platforms=("bilibili",), count=0, collect_as_much_as_safe=True
    )
    assert request.count == 0


def test_opened_screenshot_mode_allows_explicit_unbounded_creator_collection():
    request = CollectionRequest(
        platforms=("xhs",),
        count=0,
        collect_as_much_as_safe=True,
        platform_uids={"xhs": "creator"},
        screenshot_mode="opened",
        allow_navigation=True,
    )

    assert request.count == 0


def test_adapter_screenshot_all_uses_each_selected_platform_effective_count():
    request = CollectionRequest(
        platforms=("bilibili", "xhs"),
        count=0,
        platform_counts={"bilibili": 2, "xhs": 3},
        platform_uids={"bilibili": "b", "xhs": "x"},
        screenshot_mode="all",
        allow_navigation=True,
    )

    assert request.platform_counts == {"bilibili": 2, "xhs": 3}


@pytest.mark.parametrize(
    "platform_counts",
    (
        {"bilibili": 2},
        {"bilibili": 2, "xhs": 0},
    ),
)
def test_adapter_screenshot_all_rejects_any_zero_effective_count(platform_counts):
    with pytest.raises(ConfigurationError, match="positive"):
        CollectionRequest(
            platforms=("bilibili", "xhs"),
            count=0,
            platform_counts=platform_counts,
            platform_uids={"bilibili": "b", "xhs": "x"},
            collect_as_much_as_safe=True,
            screenshot_mode="all",
            allow_navigation=True,
        )


def test_adapter_request_accepts_xhs_screenshot_without_browser_assist():
    request = CollectionRequest(
        platforms=("xhs",),
        count=1,
        platform_uids={"xhs": "creator"},
        screenshot_mode="opened",
        allow_navigation=True,
    )

    assert request.browser_assist == "off"
    assert request.screenshot_mode == "opened"


def test_adapter_request_retains_bilibili_browser_assist():
    request = CollectionRequest(
        platforms=("bilibili",),
        count=1,
        platform_uids={"bilibili": "creator"},
        browser_assist="browserskill",
        allow_navigation=True,
    )

    assert request.browser_assist == "browserskill"


@pytest.mark.parametrize("platforms", (("xhs",), ("bilibili", "xhs")))
def test_adapter_request_retains_the_deprecated_bridge_shape(platforms, monkeypatch):
    """The legacy bridge stays a well-defined request shape in the adapter.

    Existing bridge coverage keeps its meaning; the collection CLI is what
    refuses a new run with ``browser-assist-replaced``.
    """

    request = CollectionRequest(
        platforms=platforms,
        count=1,
        platform_uids={platform: "creator" for platform in platforms},
        browser_assist="browserskill",
        allow_navigation=True,
    )
    assert request.browser_assist == "browserskill"


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"browser_assist": "stealth"}, "unsupported"),
        ({"screenshot_mode": "background"}, "unsupported"),
        (
            {
                "platforms": ("bilibili",),
                "platform_uids": {"bilibili": "creator"},
                "browser_assist": "browserskill",
            },
            "navigation",
        ),
        ({"screenshot_mode": "all"}, "navigation"),
        (
            {
                "platforms": ("douyin",),
                "platform_uids": {"douyin": "creator"},
                "browser_assist": "browserskill",
                "allow_navigation": True,
            },
            "bilibili and xhs",
        ),
    ),
)
def test_adapter_request_rejects_unsafe_assist_modes(changes, message):
    values = {
        "platforms": ("xhs",),
        "count": 1,
        "platform_uids": {"xhs": "creator"},
    }
    values.update(changes)
    with pytest.raises(ConfigurationError, match=message):
        CollectionRequest(**values)


@pytest.mark.parametrize(
    "changes",
    (
        {
            "platforms": ("xhs",),
            "count": 0,
            "collect_as_much_as_safe": True,
            "screenshot_mode": "all",
            "allow_navigation": True,
        },
        {
            "platforms": ("bilibili",),
            "platform_uids": {},
            "search": "topic",
            "browser_assist": "browserskill",
            "allow_navigation": True,
        },
        {
            "platforms": ("bilibili",),
            "platform_uids": {},
            "search": "topic",
            "screenshot_mode": "all",
            "allow_navigation": True,
        },
    ),
)
def test_adapter_rejects_unbounded_or_bilibili_search_advanced_modes(changes):
    values = {
        "platforms": ("xhs",),
        "count": 1,
        "platform_uids": {"xhs": "creator"},
    }
    values.update(changes)

    with pytest.raises(ConfigurationError, match="positive|not supported"):
        CollectionRequest(**values)


def test_engine_command_forwards_only_non_default_assist_modes(fake_engine_root, tmp_path):
    passive = build_engine_command(
        creator_request(platform_uids={"bilibili": "b", "xhs": "x"}),
        tmp_path / "passive",
        layout=runtime_layout(fake_engine_root, tmp_path),
    )
    assisted = build_engine_command(
        creator_request(
            platforms=("bilibili",),
            platform_uids={"bilibili": "b"},
            browser_assist="browserskill",
            screenshot_mode="all",
            allow_navigation=True,
        ),
        tmp_path / "assisted",
        layout=runtime_layout(fake_engine_root, tmp_path),
    )

    assert "--browser-assist" not in passive.argv
    assert "--screenshot-mode" not in passive.argv
    assert assisted.argv[assisted.argv.index("--browser-assist") + 1] == "browserskill"
    assert assisted.argv[assisted.argv.index("--screenshot-mode") + 1] == "all"


def test_collection_cli_exposes_compatibility_options():
    script = Path(__file__).resolve().parents[1] / "media-missher" / "scripts" / "run_collection.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 0
    for option in (
        "--platform",
        "--count",
        "--search",
        "--complete",
        "--xhs-comments",
        "--allow-navigation",
        "--screenshot-mode",
        "--no-feishu",
        "--json-summary",
    ):
        assert option in completed.stdout
    assert "--browser-assist" not in completed.stdout
    assert "--engine-root" not in completed.stdout


def test_collection_cli_rejects_override_for_unselected_platform(tmp_path):
    script = Path(__file__).resolve().parents[1] / "media-missher" / "scripts" / "run_collection.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--data-root",
            str(tmp_path / "runs"),
            "--platform",
            "bilibili",
            "--weibo-count",
            "1",
            "--json-summary",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 1
    assert "selected platform" in completed.stdout


def _successful_summary():
    return {"status": "success", "run_dir": None, "evidence": [], "errors": []}


def test_creator_cli_rejects_missing_uid_before_creating_output(tmp_path, monkeypatch, capsys):
    output = tmp_path / "runs"
    called = False

    def unexpected_run(*_args, **_kwargs):
        nonlocal called
        called = True
        return _successful_summary()

    monkeypatch.setattr(run_collection, "run_collection_request", unexpected_run)

    returncode = run_collection.main(
        ["--platform", "bilibili", "--data-root", str(output), "--json-summary"]
    )

    summary = json.loads(capsys.readouterr().out)
    assert returncode == 1
    assert summary["status"] == "preflight-failed"
    assert "bilibili" in summary["errors"][0]
    assert called is False
    assert not output.exists()


def test_private_profile_supplies_all_creator_uids(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "platform_uids": {
                    "bilibili": "bili-profile",
                    "xhs": "xhs-profile",
                    "douyin": "douyin-profile",
                    "weibo": "weibo-profile",
                }
            }
        ),
        encoding="utf-8",
    )
    profile.chmod(0o600)
    captured = {}

    def capture(request, **_kwargs):
        captured["request"] = request
        return _successful_summary()

    monkeypatch.setattr(run_collection, "run_collection_request", capture)

    assert run_collection.main(["--profile", str(profile)]) == 0
    assert captured["request"].platform_uids == {
        "bilibili": "bili-profile",
        "xhs": "xhs-profile",
        "douyin": "douyin-profile",
        "weibo": "weibo-profile",
    }


def test_creator_cli_uid_overrides_private_profile(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"platform_uids": {"bilibili": "profile-value"}}),
        encoding="utf-8",
    )
    profile.chmod(0o600)
    captured = {}

    def capture(request, **_kwargs):
        captured["request"] = request
        return _successful_summary()

    monkeypatch.setattr(run_collection, "run_collection_request", capture)

    assert run_collection.main(
        [
            "--profile",
            str(profile),
            "--platform",
            "bilibili",
            "--bilibili-uid",
            "cli-value",
        ]
    ) == 0
    assert captured["request"].platform_uids == {"bilibili": "cli-value"}


@pytest.mark.parametrize("active,expected", [(None, ("xhs", "weibo")), (["xhs"], ("xhs",))])
def test_creator_cli_uses_configured_or_active_subset(tmp_path, monkeypatch, active, expected):
    profile = tmp_path / "profile.json"
    value = {"platform_uids": {"xhs": "xhs-fixture", "weibo": "weibo-fixture"}}
    if active is not None:
        value["active_platforms"] = active
    profile.write_text(json.dumps(value), encoding="utf-8")
    profile.chmod(0o600)
    captured = {}

    def capture(request, **_kwargs):
        captured["request"] = request
        return _successful_summary()

    monkeypatch.setattr(run_collection, "run_collection_request", capture)
    assert run_collection.main(["--profile", str(profile)]) == 0
    assert captured["request"].platforms == expected


@pytest.mark.parametrize("active", [[], ["unknown"], ["xhs", "xhs"], "xhs", [None]])
def test_creator_cli_rejects_invalid_active_selection_before_output(tmp_path, monkeypatch, active, capsys):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"platform_uids": {platform: "fixture" for platform in run_collection.PLATFORMS}, "active_platforms": active}), encoding="utf-8")
    profile.chmod(0o600)
    output = tmp_path / "runs"
    monkeypatch.setattr(run_collection, "run_collection_request", lambda *a, **kw: pytest.fail("collection must not start"))
    assert run_collection.main(["--profile", str(profile), "--data-root", str(output), "--json-summary"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "preflight-failed"
    assert not output.exists()


@pytest.mark.parametrize(
    ("navigation_flag", "expected"),
    (([], False), (["--allow-navigation"], True)),
)
def test_collection_cli_requires_explicit_navigation_authorization(
    navigation_flag, expected, monkeypatch
):
    captured = {}

    def capture(request, **_kwargs):
        captured["request"] = request
        return _successful_summary()

    monkeypatch.setattr(run_collection, "run_collection_request", capture)

    assert run_collection.main(
        [
            "--platform",
            "bilibili",
            "--bilibili-uid",
            "creator",
            *navigation_flag,
        ]
    ) == 0
    assert captured["request"].allow_navigation is expected


def test_collection_cli_refuses_the_retired_browser_assist_bridge():
    """The retired bridge is refused by name, with no reinterpreted flag."""

    result = run_collection.main(
        [
            "--platform",
            "bilibili",
            "--bilibili-uid",
            "creator",
            "--browser-assist",
            "browserskill",
            "--allow-navigation",
        ]
    )
    assert result == 1


def test_collection_cli_never_drops_computer_use_into_legacy_cdp(monkeypatch, capsys):
    captured = {}

    def capture(request, **_kwargs):
        captured["request"] = request
        return _successful_summary()

    monkeypatch.setattr(run_collection, "run_collection_request", capture)

    assert run_collection.main(
        [
            "--platform",
            "bilibili",
            "--bilibili-uid",
            "creator",
            "--backend",
            "computer_use",
            "--count-mode",
            "best_effort",
            "--run-deadline",
            "1800",
            "--screenshot-mode",
            "opened",
            "--allow-navigation",
        ]
    ) == 1
    assert captured == {}
    assert "backend-retired-computer-use" in capsys.readouterr().out


def test_collection_cli_forwards_nondefault_envelope_to_plan(monkeypatch):
    captured = {}
    def capture(args, **kwargs):
        captured.update(args=vars(args), **kwargs)
        return 0
    monkeypatch.setattr(run_collection, '_forward_plan', capture)
    monkeypatch.setattr(run_collection, 'run_collection_request', lambda *_a, **_k: pytest.fail('legacy fixed-count path'))
    assert run_collection.main(['--platform','weibo','--weibo-uid','123','--backend','cdp','--count-mode','best_effort','--run-deadline','1800']) == 0
    assert captured['backend'] == 'cdp'
    assert captured['args']['count_mode'] == 'best_effort'
    assert captured['args']['run_deadline'] == 1800
    assert captured['args']['weibo_uid'] == '123'
