from pathlib import Path
import re


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"


def test_skill_frontmatter_is_codex_compatible():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    assert match
    lines = match.group(1).splitlines()
    keys = {line.split(":", 1)[0] for line in lines if ":" in line}
    assert keys == {"name", "description"}
    assert "name: media-missher" in lines


def test_skill_has_only_allowed_top_level_entries():
    assert {path.name for path in SKILL.iterdir()} == {
        "SKILL.md",
        "agents",
        "scripts",
        "references",
    }


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
