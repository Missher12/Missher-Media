import socket
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "media-missher" / "scripts"
RUNTIME = REPO / "runtime"
FAKE_ENGINE = REPO / "tests" / "fake_engine.py"
sys.path.insert(0, str(SCRIPTS))
# Appended, not inserted: an installed copy keeps priority, and this only makes
# the checkout importable for tests that do not set PYTHONPATH themselves.
if str(RUNTIME) not in sys.path:
    sys.path.append(str(RUNTIME))


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in (
        "MEDIA_MISSHER_ENGINE_ROOT",
        "MEDIA_MISSHER_DATA_ROOT",
        "MEDIA_MISSHER_PROFILE_CONFIG",
        "MEDIA_MISSHER_CDP_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    def deny_network(*_args, **_kwargs):
        raise AssertionError("offline test attempted a real network connection")

    monkeypatch.setattr(socket, "create_connection", deny_network)


@pytest.fixture
def fake_engine_root(tmp_path):
    root = tmp_path / "external-engine"
    interpreter = root / "engine" / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(Path(sys.executable).resolve())
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    source = FAKE_ENGINE.read_text(encoding="utf-8") if FAKE_ENGINE.exists() else (
        "import argparse\nparser = argparse.ArgumentParser()\nparser.parse_args()\n"
    )
    for name in (
        "scrape_all.py",
        "scrape_bilibili.py",
        "scrape_xhs.py",
        "scrape_douyin.py",
        "scrape_weibo.py",
    ):
        (scripts / name).write_text(source, encoding="utf-8")
    return root
