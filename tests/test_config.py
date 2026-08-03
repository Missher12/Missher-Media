import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from media_missher_adapter import (
    CollectionRequest,
    ConfigurationError,
    RuntimeLayout,
    parse_non_negative_int,
    parse_platforms,
    read_profile,
    resolve_data_root,
    resolve_runtime_layout,
)


REPO = Path(__file__).resolve().parents[1]


def write_profile(path: Path, payload: dict, mode: int = 0o600):
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(mode)
    return path


def test_runtime_layout_defaults_to_local_share_home(tmp_path, monkeypatch):
    private_home = tmp_path / "private-home"
    monkeypatch.setenv("HOME", str(private_home))
    runtime_home = private_home / ".local" / "share" / "media-missher"

    assert resolve_runtime_layout(environ={}) == RuntimeLayout(
        home=runtime_home.resolve(),
        current=(runtime_home / "current").resolve(),
        python=(runtime_home / "venv" / "bin" / "python").resolve(),
        state=(runtime_home / "state").resolve(),
    )


def test_runtime_layout_uses_media_missher_home(tmp_path):
    runtime_home = tmp_path / "Media @ Missher Home"

    layout = resolve_runtime_layout(
        environ={"MEDIA_MISSHER_HOME": str(runtime_home)}
    )

    assert layout.home == runtime_home.resolve()
    assert layout.current == (runtime_home / "current").resolve()
    assert layout.python == (runtime_home / "venv" / "bin" / "python").resolve()
    assert layout.state == (runtime_home / "state").resolve()


def test_runtime_layout_preserves_lexical_home_for_symlink_checks(tmp_path):
    actual_home = tmp_path / "actual-runtime"
    actual_home.mkdir()
    linked_home = tmp_path / "linked-runtime"
    linked_home.symlink_to(actual_home, target_is_directory=True)

    layout = resolve_runtime_layout(
        environ={"MEDIA_MISSHER_HOME": str(linked_home)}
    )

    assert layout.home == linked_home.absolute()
    assert layout.home != actual_home.resolve()


def test_runtime_layout_is_frozen(tmp_path):
    layout = resolve_runtime_layout(
        environ={"MEDIA_MISSHER_HOME": str(tmp_path / "runtime-home")}
    )

    with pytest.raises(FrozenInstanceError):
        layout.home = tmp_path / "replacement"


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_navigation_authorization_requires_an_explicit_boolean(value):
    with pytest.raises(ConfigurationError, match="navigation authorization"):
        CollectionRequest(
            platforms=("weibo",),
            search="topic",
            allow_navigation=value,
        )


def test_data_root_has_private_home_default(tmp_path, monkeypatch):
    home = tmp_path / "private-home"
    monkeypatch.setenv("HOME", str(home))
    assert resolve_data_root(None, environ={}, profile={}) == (
        home / ".local" / "share" / "media-missher" / "state" / "runs"
    ).resolve()


@pytest.mark.parametrize("value, expected", [("0", 0), (7, 7), ("12", 12)])
def test_parse_non_negative_int(value, expected):
    assert parse_non_negative_int(value) == expected


@pytest.mark.parametrize("value", ["-1", -2, "not-an-int", True, 1.9])
def test_parse_non_negative_int_rejects_invalid_values(value):
    with pytest.raises(ConfigurationError, match="non-negative integer"):
        parse_non_negative_int(value)


def test_parse_platforms_defaults_and_deduplicates():
    assert parse_platforms(None) == ("bilibili", "xhs", "douyin", "weibo")
    assert parse_platforms(" XHS,bilibili,xhs ") == ("xhs", "bilibili")


def test_parse_platforms_rejects_unknown_before_runtime():
    with pytest.raises(ConfigurationError, match="unknown platform"):
        parse_platforms("bilibili,invalid")


def test_private_profile_rejects_group_or_world_permissions(tmp_path):
    profile = write_profile(tmp_path / "profile.json", {}, 0o644)
    with pytest.raises(ConfigurationError, match="0600"):
        read_profile(profile)


@pytest.mark.parametrize("mode", [0o400, 0o700])
def test_private_profile_requires_exact_mode_0600(tmp_path, mode):
    profile = write_profile(tmp_path / "profile.json", {}, mode)
    with pytest.raises(ConfigurationError, match="0600"):
        read_profile(profile)


def test_private_profile_must_live_outside_repository():
    with pytest.raises(ConfigurationError, match="outside"):
        read_profile(REPO / "private-profile.json")


def test_profile_must_be_json_object(tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text("[]", encoding="utf-8")
    profile.chmod(0o600)
    with pytest.raises(ConfigurationError, match="JSON object"):
        read_profile(profile)


def test_deprecated_engine_configuration_does_not_change_runtime_home(tmp_path, monkeypatch):
    private_home = tmp_path / "private-home"
    monkeypatch.setenv("HOME", str(private_home))

    layout = resolve_runtime_layout(
        environ={"MEDIA_MISSHER_ENGINE_ROOT": str(tmp_path / "obsolete")}
    )

    assert layout.home == (
        private_home / ".local" / "share" / "media-missher"
    ).resolve()
