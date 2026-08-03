import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"
ALLOWED_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/commands.md",
    "references/configuration.md",
    "references/licensing.md",
    "references/troubleshooting.md",
    "references/validation.md",
    "scripts/media_missher_adapter.py",
    "scripts/preflight.py",
    "scripts/run_collection.py",
    "scripts/validate_run.py",
}
ALLOWED_DIRECTORIES = {"agents", "references", "scripts"}


def installable_text():
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(SKILL.rglob("*"))
        if path.is_file() and path.suffix in {".md", ".py", ".yaml"}
    )


def assert_exact_installable_allowlist(root):
    files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    directories = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir()
    }
    assert files == ALLOWED_FILES
    assert directories == ALLOWED_DIRECTORIES


def assert_no_sensitive_values(text):
    assert not re.search(r"\bou_[A-Za-z0-9]{12,}\b", text)
    assert not re.search(r"\bBV[A-Za-z0-9]{8,}\b", text)
    assert not re.search(r"\bMS4w\.[A-Za-z0-9_-]{12,}\b", text)
    assert not re.search(r"\b[0-9a-fA-F]{24}\b", text)
    credential_assignment = re.compile(
        r"(?i)(?:api[_-]?key|app[_-]?token|access[_-]?token|refresh[_-]?token|"
        r"password|passwd|secret|cookie|sessionid|authorization)\s*[:=]\s*"
        r"['\"][^'\"\n]{4,}['\"]"
    )
    assert not credential_assignment.search(text)


def test_installable_skill_has_no_personal_paths_or_identity_values():
    text = installable_text()
    assert "/Users/" not in text
    assert "~/.openclaw" not in text
    assert_no_sensitive_values(text)


def test_installable_tree_is_an_exact_allowlist():
    assert_exact_installable_allowlist(SKILL)


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
        "blocked",
        "current run",
        "captcha",
        "proxy rotation",
    )
    assert all(item in text for item in required)


def test_allowlist_rejects_representative_artifacts(tmp_path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "runtime.log").write_text("synthetic", encoding="utf-8")
    with __import__("pytest").raises(AssertionError):
        assert_exact_installable_allowlist(root)


def test_sensitive_scan_rejects_representative_credential_value():
    with __import__("pytest").raises(AssertionError):
        assert_no_sensitive_values('api_key = "CANARY-REAL-VALUE"')
