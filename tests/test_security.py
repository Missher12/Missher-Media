import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"


def installable_text():
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(SKILL.rglob("*"))
        if path.is_file() and path.suffix in {".md", ".py", ".yaml"}
    )


def test_installable_skill_has_no_personal_paths_or_identity_values():
    text = installable_text()
    assert "/Users/" not in text
    assert "~/.openclaw" not in text
    assert not re.search(r"\bou_[A-Za-z0-9]{12,}\b", text)
    assert not re.search(r"(?i)(?:app_token|table_id|open_id)\s*[:=]\s*['\"][^'\"]+", text)


def test_installable_skill_has_no_inherited_source_or_bundled_runtime():
    text = installable_text()
    forbidden_text = (
        "Copyright (c) NanmiCoder",
        "github.com/NanmiCoder/MediaCrawler",
        "NanmiCoder/Media@Missher",
        "openclaw.skill.json",
    )
    assert not any(item in text for item in forbidden_text)
    forbidden_names = {
        "engine",
        ".venv",
        "data",
        "requirements.txt",
        "package-lock.json",
        ".playwright-cli",
    }
    assert not forbidden_names.intersection(path.name for path in SKILL.rglob("*"))
    assert not any(path.suffix.lower() in {".js", ".woff", ".woff2", ".ttf", ".png", ".jpg"} for path in SKILL.rglob("*"))


def test_installable_skill_contains_no_stale_placeholders():
    text = installable_text()
    assert not re.search(r"(?im)\b(?:TODO|TBD|FIXME|YOUR_UID|YOUR_SEC_UID)\b", text)


def test_skill_is_concise_and_all_references_exist():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(skill_text.splitlines()) < 250
    references = set(re.findall(r"references/([a-z_]+\.md)", skill_text))
    assert references == {
        "commands.md",
        "configuration.md",
        "licensing.md",
        "troubleshooting.md",
        "validation.md",
    }
    assert all((SKILL / "references" / name).is_file() for name in references)


def test_skill_preserves_required_safety_contracts():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8").lower()
    required = (
        "read-only",
        "explicit",
        "sequential",
        "preflight",
        "--no-feishu",
        "risk-stopped",
        "current run",
        "captcha",
        "proxy rotation",
    )
    assert all(item in text for item in required)
