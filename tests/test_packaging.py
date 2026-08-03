import os
import re
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"
RUNTIME_SCRIPTS = REPO / "runtime" / "scripts"
DOCUMENTATION = (
    SKILL / "SKILL.md",
    SKILL / "references" / "configuration.md",
    SKILL / "references" / "commands.md",
    SKILL / "references" / "troubleshooting.md",
    SKILL / "references" / "validation.md",
    SKILL / "references" / "licensing.md",
    REPO / "PROJECT_CONTEXT.md",
)


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


def test_documentation_covers_shared_runtime_operations_and_recovery():
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in DOCUMENTATION)
    required = (
        "MEDIA_MISSHER_HOME",
        "~/.local/share/media-missher",
        "platform_uids",
        "0600",
        "0700",
        "scrape_all.py",
        "scrape_bilibili.py",
        "scrape_xhs.py",
        "scrape_douyin.py",
        "scrape_weibo.py",
        "scripts/preflight.py",
        "--live",
        "scripts/run_collection.py",
        "--allow-navigation",
        "scripts/validate_run.py",
        "tools/install_media_missher.py",
        "--runtime-only",
        ".media-missher-owner.json",
        ".media-missher-install.lock",
        ".media-missher-release",
        "previous-",
        "timestamp",
        "Trash",
        "risk-stopped",
        "--collect-as-much-as-safe",
        "remote Feishu write",
    )

    for phrase in required:
        assert phrase in corpus, f"documentation is missing {phrase!r}"


def test_skill_preserves_read_only_requests_and_requires_collection_authorization():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "Keep code review, audit, explanation, and planning read-only" in text
    assert "Require explicit authorization to collect" in text
    assert "--allow-navigation" in text
    assert "separate explicit authorization" in text


def test_documentation_distinguishes_live_cdp_probe_from_controller_page_preflight():
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in DOCUMENTATION)

    assert "Live preflight probes the existing CDP endpoint" in corpus
    assert (
        "The runtime controller checks each selected platform page and login state "
        "before creating output"
    ) in corpus


def test_project_context_records_clean_boundaries_and_pending_live_cutover():
    text = (REPO / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")

    for phrase in (
        "Source boundary",
        "Runtime boundary",
        "Adapter boundary",
        "Live acceptance",
        "Cutover",
        "Current limitations",
        "~/.codex/skills/media-missher",
        "~/.openclaw/workspace/skills/media-missher",
    ):
        assert phrase in text
