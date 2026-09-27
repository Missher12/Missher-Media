"""History export must work without pytest's shared-runtime import path."""

import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("layout", ["payload", "installed"])
def test_selected_export_in_clean_process(tmp_path, layout):
    root = tmp_path.resolve()
    scripts = root / "skill-root" / "media-missher" / "scripts"
    shutil.copytree(ROOT / "media-missher" / "scripts", scripts)
    runtime_home = root / "runtime-home"
    runtime = scripts.parents[1] / "runtime" if layout == "payload" else runtime_home / "current"
    shutil.copytree(ROOT / "runtime", runtime, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    data_root = root / "runs"
    outer = data_root / "run-history"
    inner = outer / "run-engine"
    for directory in (data_root, outer, inner):
        directory.mkdir(mode=0o700)
    fixture = {
        "douyin.json": [{"platform": "douyin", "aweme_id": "smoke-1", "liked": 1,
                         "link": "https://example.invalid/smoke",
                         "observed_at": "2026-09-07T00:00:00Z"}],
        "manifest.json": {
            "counts": {"douyin": 1}, "paths": {"douyin": "douyin.json"},
            "platforms": {"douyin": "complete"}, "status": "complete",
            "diagnostics": {"douyin": {"kind": "ok", "code": "ok"}},
        },
    }
    for name, value in fixture.items():
        path = inner / name
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)
    result = subprocess.run(
        [sys.executable, "-E", "-S", "-B", str(scripts / "manage_runs.py"), "export",
         "--data-root", str(data_root), "--run-id", "run-history",
         "--record-kinds", "posts", "--format", "csv"],
        cwd=root,
        env={**os.environ, "HOME": str(root / "home"), "MEDIA_MISSHER_HOME": str(runtime_home),
             "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    value = json.loads(result.stdout)
    assert value["status"] == "ok"
    artifact = Path(value["artifactPath"])
    assert artifact.parent == data_root / "exports"
    with artifact.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["aweme_id"] == "smoke-1"
    metadata = json.loads(Path(value["metadataPath"]).read_text(encoding="utf-8"))
    assert metadata["historical"] is True
    assert metadata["source_run_id"] == "run-history"
    assert metadata["rows"] == 1
