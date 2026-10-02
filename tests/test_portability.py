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
        [sys.executable, "-B", str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )


def make_runtime_home(fake_engine_root):
    home = fake_engine_root.parent / "Runtime @ Home"
    shutil.copytree(fake_engine_root / "scripts", home / "current" / "scripts")
    (home / "current" / "VERSION").write_text("17.0.2\n", encoding="ascii")
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
    home.chmod(0o700)
    owner = home / ".media-missher-owner.json"
    owner.write_text(
        json.dumps({"name": "media-missher-runtime-home", "schema": 1}) + "\n",
        encoding="utf-8",
    )
    owner.chmod(0o600)
    lock = home / ".media-missher-install.lock"
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    for root in (home / "current", home / "venv"):
        marker = root / ".media-missher-release"
        marker.write_text("portable-release\n", encoding="ascii")
        marker.chmod(0o600)
    return home


def test_skill_scripts_work_from_path_with_spaces_and_at_sign(fake_engine_root, tmp_path):
    portable_skill = tmp_path / "Media @ Missher Skill"
    shutil.copytree(SKILL, portable_skill)
    scripts = portable_skill / "scripts"

    for name in ("preflight.py", "run_collection.py", "validate_run.py"):
        completed = _run(scripts / name, "--help")
        assert completed.returncode == 0, completed.stderr

    runtime_home = make_runtime_home(fake_engine_root)
    skill_marker = portable_skill / ".media-missher-release"
    skill_marker.write_text("portable-release\n", encoding="ascii")
    skill_marker.chmod(0o600)
    completed = _run(
        scripts / "preflight.py",
        "--json",
        environment_overrides={"MEDIA_MISSHER_HOME": str(runtime_home)},
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "ok"
