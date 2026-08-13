from __future__ import annotations

import os
from pathlib import Path
import re


ACTIVE_DOCUMENTATION = (
    Path("media-missher/SKILL.md"),
    *tuple(sorted(Path("media-missher/references").glob("*.md"))),
    Path("PROJECT_CONTEXT.md"),
)


def _terms() -> tuple[str, str]:
    return ("".join(("Media", "Crawler")), "".join(("Nanmi", "Coder")))


def test_forbidden_terms_are_assembled_and_absent_from_scanner_source() -> None:
    from tools.scan_active_residuals import forbidden_terms

    source = Path("tools/scan_active_residuals.py").read_text(encoding="utf-8")

    assert forbidden_terms() == _terms()
    assert all(term not in source for term in _terms())


def test_scanner_detects_active_file_names_text_symlinks_shebangs_and_pyvenv(tmp_path: Path) -> None:
    from tools.scan_active_residuals import scan_roots

    first, second = _terms()
    (tmp_path / f"{first}-name.txt").write_text("clear", encoding="utf-8")
    (tmp_path / "text.txt").write_text(second, encoding="utf-8")
    (tmp_path / "script").write_text(f"#! /usr/bin/env {first}\n", encoding="utf-8")
    (tmp_path / "pyvenv.cfg").write_text(f"home = {second}\n", encoding="utf-8")
    os.symlink(f"/tmp/{first}", tmp_path / "linked")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.txt").write_text(first, encoding="utf-8")

    findings = scan_roots([tmp_path])

    assert {(item.relative_path, item.category, item.term) for item in findings} == {
        (f"{first}-name.txt", "filename", first),
        ("text.txt", "text", second),
        ("script", "shebang", first),
        ("pyvenv.cfg", "pyvenv", second),
        ("linked", "symlink", first),
    }


def test_scanner_detects_directory_names_and_directory_symlink_names_and_targets(tmp_path: Path) -> None:
    from tools.scan_active_residuals import scan_roots

    first, second = _terms()
    root = tmp_path / "active"
    root.mkdir()
    (root / f"regular-{first}").mkdir()
    external_target = tmp_path / f"external-{second}"
    external_target.mkdir()
    os.symlink(external_target, root / f"linked-{first}")

    findings = scan_roots([root])

    assert {(item.relative_path, item.category, item.term) for item in findings} == {
        (f"regular-{first}", "dirname", first),
        (f"linked-{first}", "symlink", first),
        (f"linked-{first}", "symlink", second),
    }


def test_scanner_matches_paths_content_and_symlink_targets_case_insensitively(tmp_path: Path) -> None:
    from tools.scan_active_residuals import scan_roots

    first, second = _terms()
    lower_first = first.lower()
    mixed_second = second.swapcase()
    (tmp_path / f"file-{lower_first}.txt").write_text("clear", encoding="utf-8")
    (tmp_path / f"directory-{mixed_second}").mkdir()
    (tmp_path / "text.txt").write_text(lower_first, encoding="utf-8")
    (tmp_path / "script").write_text(f"#! /usr/bin/env {mixed_second}\n", encoding="utf-8")
    (tmp_path / "pyvenv.cfg").write_text(f"home = {lower_first}\n", encoding="utf-8")
    os.symlink(f"/tmp/{mixed_second}", tmp_path / "linked")

    findings = scan_roots([tmp_path])

    assert {(item.relative_path, item.category, item.term) for item in findings} == {
        (f"file-{lower_first}.txt", "filename", first),
        (f"directory-{mixed_second}", "dirname", second),
        ("text.txt", "text", first),
        ("script", "shebang", second),
        ("pyvenv.cfg", "pyvenv", first),
        ("linked", "symlink", second),
    }


def test_active_documentation_has_no_obsolete_root_api_or_personal_absolute_path() -> None:
    first, second = _terms()
    obsolete = (first, second, "MEDIA_MISSHER_ENGINE_ROOT", "--engine-root")
    failures = []
    for path in ACTIVE_DOCUMENTATION:
        text = path.read_text(encoding="utf-8")
        for term in obsolete:
            if term.casefold() in text.casefold():
                failures.append(f"{path}:{term}")
        if re.search(r"/(?:Users|home)/[^/\s`]+", text):
            failures.append(f"{path}:personal absolute path")

    assert failures == []


def test_project_context_scopes_v15_live_acceptance_to_xhs() -> None:
    text = Path("PROJECT_CONTEXT.md").read_text(encoding="utf-8")

    assert "V15 Xiaohongshu live acceptance passed" in text
    assert "Bilibili, Douyin, Weibo, and keyword-search DOM paths were not part" in text
    assert "BrowserSkill remained at zero sessions" in text
