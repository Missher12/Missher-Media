import json
import os
from pathlib import Path

import pytest

from media_missher_adapter import (
    ConfigurationError,
    engine_python,
    parse_non_negative_int,
    parse_platforms,
    read_profile,
    resolve_data_root,
    resolve_engine_root,
)


REPO = Path(__file__).resolve().parents[1]


def write_profile(path: Path, payload: dict, mode: int = 0o600):
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(mode)
    return path


def test_resolve_engine_root_prefers_cli_over_environment_and_profile(tmp_path, monkeypatch):
    cli_root = tmp_path / "cli"
    env_root = tmp_path / "env"
    profile_root = tmp_path / "profile"
    monkeypatch.setenv("MEDIA_MISSHER_ENGINE_ROOT", str(env_root))
    assert resolve_engine_root(
        cli_root,
        environ=os.environ,
        profile={"engine_root": str(profile_root)},
    ) == cli_root.resolve()


def test_resolvers_fall_back_to_environment_then_profile(tmp_path):
    env_root = tmp_path / "env"
    profile_root = tmp_path / "profile"
    environment = {"MEDIA_MISSHER_ENGINE_ROOT": str(env_root)}
    assert resolve_engine_root(None, environ=environment, profile={"engine_root": str(profile_root)}) == env_root.resolve()
    assert resolve_engine_root(None, environ={}, profile={"engine_root": str(profile_root)}) == profile_root.resolve()


def test_data_root_has_private_home_default(tmp_path, monkeypatch):
    home = tmp_path / "private-home"
    monkeypatch.setenv("HOME", str(home))
    assert resolve_data_root(None, environ={}, profile={}) == (home / ".media-missher" / "runs").resolve()


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


def test_engine_python_uses_external_engine_venv(fake_engine_root):
    assert engine_python(fake_engine_root) == fake_engine_root / "engine" / ".venv" / "bin" / "python"


def test_missing_engine_configuration_fails_closed():
    with pytest.raises(ConfigurationError, match="engine root"):
        resolve_engine_root(None, environ={}, profile={})
