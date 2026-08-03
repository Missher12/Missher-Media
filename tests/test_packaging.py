import os
import re
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"
RUNTIME_SCRIPTS = REPO / "runtime" / "scripts"


def parse_skill_frontmatter(text):
    match = re.match(r"\A---\n(?P<header>.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must use exact YAML frontmatter delimiters"
    parsed = {}
    for line in match.group("header").splitlines():
        field = re.fullmatch(r"([a-z_]+):\s+(\S.*)", line)
        assert field, f"invalid frontmatter line: {line!r}"
        key, value = field.groups()
        assert key not in parsed, f"duplicate frontmatter key: {key}"
        parsed[key] = value
    assert set(parsed) == {"name", "description"}
    return parsed


def parse_openai_interface(text):
    assert text.startswith("interface:\n")
    parsed = {}
    for line in text.splitlines()[1:]:
        field = re.fullmatch(r'  ([a-z_]+): "([^"\n]+)"', line)
        assert field, f"invalid openai.yaml line: {line!r}"
        key, value = field.groups()
        assert key not in parsed, f"duplicate interface key: {key}"
        parsed[key] = value
    return parsed


def test_skill_frontmatter_is_codex_compatible():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = parse_skill_frontmatter(text)
    assert frontmatter["name"] == "media-missher"


@pytest.mark.parametrize(
    "text",
    (
        "---\nname: media-missher\ndescription: valid\n--- trailing\n# Body\n",
        "---\nname: media-missher\nname: duplicate\ndescription: valid\n---\n",
        "---\nname: media-missher\ninvalid line\ndescription: valid\n---\n",
        "---\nname: media-missher\ndescription:\n---\n",
    ),
)
def test_skill_frontmatter_rejects_malformed_metadata(text):
    with pytest.raises(AssertionError):
        parse_skill_frontmatter(text)


def test_skill_has_only_allowed_top_level_entries():
    assert {path.name for path in SKILL.iterdir()} == {
        "SKILL.md",
        "agents",
        "scripts",
        "references",
    }
    for directory in ("agents", "scripts", "references"):
        assert (SKILL / directory).is_dir()


def test_openai_metadata_has_required_interface():
    metadata = SKILL / "agents" / "openai.yaml"
    assert metadata.is_file()
    interface = parse_openai_interface(metadata.read_text(encoding="utf-8"))
    assert set(interface) == {
        "display_name",
        "short_description",
        "default_prompt",
    }
    assert all(interface.values())
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$media-missher" in interface["default_prompt"]


def test_skill_contains_no_bundled_engine_or_generated_artifacts():
    forbidden = {
        "engine",
        ".venv",
        "data",
        "__pycache__",
        ".pytest_cache",
        "openclaw.skill.json",
    }
    assert not forbidden.intersection(path.name for path in SKILL.rglob("*"))
    assert all(path.is_file() for path in (SKILL / "scripts").iterdir())


@pytest.mark.parametrize(
    "script_name",
    (
        "scrape_all.py",
        "scrape_bilibili.py",
        "scrape_xhs.py",
        "scrape_douyin.py",
        "scrape_weibo.py",
    ),
)
def test_all_runtime_entrypoint_help_is_offline_and_has_no_removed_root_flag(script_name):
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(RUNTIME_SCRIPTS / script_name), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=environment,
    )

    assert completed.returncode == 0
    assert "{creator,search}" in completed.stdout
    assert "--engine-root" not in completed.stdout

    creator_help = subprocess.run(
        [sys.executable, str(RUNTIME_SCRIPTS / script_name), "creator", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=environment,
    )
    assert creator_help.returncode == 0
    assert "--allow-navigation" in creator_help.stdout
    assert "--engine-root" not in creator_help.stdout
