from __future__ import annotations

import os
from pathlib import Path


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
