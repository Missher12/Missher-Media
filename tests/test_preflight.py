import json
import subprocess
import sys
from pathlib import Path

import pytest

import preflight
from media_missher_adapter import run_preflight


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"Browser": "Synthetic/1", "Protocol-Version": "1.3"}).encode()


def test_preflight_checks_help_without_live_network(fake_engine_root):
    report = run_preflight(fake_engine_root, live=False)
    assert report["status"] == "ok"
    assert report["checks"] == {
        "engine_root": True,
        "interpreter": True,
        "entrypoint": True,
        "entrypoint_help": True,
    }


def test_live_preflight_accepts_cdp_version(fake_engine_root, monkeypatch):
    monkeypatch.setattr(preflight.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    report = run_preflight(fake_engine_root, live=True, urlopen=preflight.urllib.request.urlopen)
    assert report["status"] == "ok"
    assert report["checks"]["cdp"] is True
    assert report["cdp"] == {"browser": "Synthetic/1", "protocol_version": "1.3"}


def test_live_preflight_reports_unavailable_cdp_without_starting_chrome(fake_engine_root):
    def failing_urlopen(*_args, **_kwargs):
        raise OSError("connection refused")

    report = run_preflight(fake_engine_root, live=True, urlopen=failing_urlopen)
    assert report["status"] == "failed"
    assert report["checks"]["cdp"] is False
    assert any("connection refused" in error for error in report["errors"])


def test_preflight_fails_when_entrypoint_is_missing(fake_engine_root):
    (fake_engine_root / "scripts" / "scrape_all.py").unlink()
    report = run_preflight(fake_engine_root, live=False)
    assert report["status"] == "failed"
    assert report["checks"]["entrypoint"] is False
    assert report["checks"]["entrypoint_help"] is False


def test_preflight_checks_the_requested_search_entrypoint(fake_engine_root):
    (fake_engine_root / "scripts" / "scrape_xhs.py").unlink()
    report = run_preflight(
        fake_engine_root,
        live=False,
        entrypoint_names=("scrape_xhs.py",),
    )
    assert report["status"] == "failed"
    assert report["checks"]["entrypoint"] is False
    assert report["checks"]["entrypoint_help"] is False
    assert any("scrape_xhs.py" in error for error in report["errors"])


def test_preflight_cli_help_is_offline():
    script = Path(preflight.__file__).resolve()
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 0
    assert "--engine-root" in completed.stdout
    assert "--live" in completed.stdout
