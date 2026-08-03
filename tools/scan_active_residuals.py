from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".worktrees",
        ".pytest_cache",
        "__pycache__",
        "cache",
        "caches",
        "generated",
        "output",
        "outputs",
        "history",
        "memory",
        "memories",
        "session",
        "sessions",
        ".trash",
        "trash",
    }
)


@dataclass(frozen=True, slots=True)
class Finding:
    root: Path
    relative_path: str
    category: str
    term: str


def forbidden_terms() -> tuple[str, str]:
    return ("".join(("Media", "Crawler")), "".join(("Nanmi", "Coder")))


def _matches(value: str, terms: tuple[str, str]) -> list[str]:
    return [term for term in terms if term in value]


def _finding(root: Path, path: Path, category: str, term: str) -> Finding:
    return Finding(root=root, relative_path=path.relative_to(root).as_posix(), category=category, term=term)


def scan_roots(roots: Iterable[Path | str]) -> list[Finding]:
    terms = forbidden_terms()
    findings: list[Finding] = []
    for raw_root in roots:
        root = Path(raw_root).resolve()
        if not root.exists():
            continue
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if name.casefold() not in _SKIPPED_DIRECTORIES]
            base = Path(directory)
            for name in filenames:
                path = base / name
                for term in _matches(name, terms):
                    findings.append(_finding(root, path, "filename", term))
                if path.is_symlink():
                    for term in _matches(os.readlink(path), terms):
                        findings.append(_finding(root, path, "symlink", term))
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                category = "pyvenv" if name == "pyvenv.cfg" else "shebang" if text.startswith("#!") else "text"
                scan_text = text.splitlines()[0] if category == "shebang" else text
                for term in _matches(scan_text, terms):
                    findings.append(_finding(root, path, category, term))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan active roots for forbidden residuals.")
    parser.add_argument("--root", action="append", required=True, type=Path)
    args = parser.parse_args(argv)
    findings = scan_roots(args.root)
    for item in findings:
        print(f"{item.root}:{item.relative_path}:{item.category}:{item.term}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
