import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"


def _run(
    script: Path,
    *arguments: str,
    environment_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.update(environment_overrides or {})
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )


def make_runtime_home(fake_engine_root):
    home = fake_engine_root.parent / "Runtime @ Home"
    shutil.copytree(fake_engine_root / "scripts", home / "current" / "scripts")
    interpreter = home / "venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then\n"
        "  case \"$2\" in\n"
        "    *version_info*) printf '%s\\n' '3.12.0'; exit 0 ;;\n"
        "    'import playwright') exit 0 ;;\n"
        "  esac\n"
        "fi\n"
        f"exec {shlex.quote(str(Path(sys.executable).resolve()))} \"$@\"\n",
        encoding="utf-8",
    )
    interpreter.chmod(0o700)
    (home / "state").mkdir(mode=0o700)
    return home


def test_skill_scripts_work_from_path_with_spaces_and_at_sign(fake_engine_root, tmp_path):
    portable_skill = tmp_path / "Media @ Missher Skill"
    shutil.copytree(SKILL, portable_skill)
    scripts = portable_skill / "scripts"

    for name in ("preflight.py", "run_collection.py", "validate_run.py"):
        completed = _run(scripts / name, "--help")
        assert completed.returncode == 0, completed.stderr

    runtime_home = make_runtime_home(fake_engine_root)
    completed = _run(
        scripts / "preflight.py",
        "--json",
        environment_overrides={"MEDIA_MISSHER_HOME": str(runtime_home)},
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "ok"
