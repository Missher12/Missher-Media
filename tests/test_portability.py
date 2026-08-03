import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"


def _run(script: Path, *arguments: str) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )


def test_skill_scripts_work_from_path_with_spaces_and_at_sign(fake_engine_root, tmp_path):
    portable_skill = tmp_path / "Media @ Missher Skill"
    shutil.copytree(SKILL, portable_skill)
    scripts = portable_skill / "scripts"

    for name in ("preflight.py", "run_collection.py", "validate_run.py"):
        completed = _run(scripts / name, "--help")
        assert completed.returncode == 0, completed.stderr

    completed = _run(
        scripts / "preflight.py",
        "--engine-root",
        str(fake_engine_root),
        "--json",
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "ok"
