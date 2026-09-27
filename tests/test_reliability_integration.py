from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from media_missher_adapter import CollectionRequest, run_collection_request


@pytest.mark.parametrize("latch", [False, True])
def test_actual_adapter_surfaces_xhs_guard_without_browser_work(fake_engine_root: Path, tmp_path: Path, latch: bool) -> None:
    from test_runner import make_runtime_layout, ok_preflight
    from runtime.media_missher_runtime.xhs_policy import XhsSafetyGate
    layout = make_runtime_layout(fake_engine_root)
    runtime_source = Path(__file__).resolve().parents[1] / "runtime"
    (layout.current / "scripts/scrape_all.py").write_text(f'import sys\nsys.path.insert(0, {str(runtime_source)!r})\nfrom media_missher_runtime.cli import main\nraise SystemExit(main())\n')
    with XhsSafetyGate(layout.state).batch() as gate:
        if latch:
            gate.latch("http-429")
    result = run_collection_request(CollectionRequest(("xhs",), count=1, platform_uids={"xhs": "fixture"}, allow_navigation=True), layout=layout, data_root=tmp_path / "runs", preflight_runner=ok_preflight)
    assert result["status"] == "preflight-failed"
    assert result["returncode"] == 78
    assert result["diagnostics"]["xhs"]["code"] == ("xhs-risk-latched" if latch else "xhs-cooldown")
    assert not list(Path(result["run_dir"]).glob("run-*/manifest.json"))


def test_controller_continuation_preserves_old_run_and_counts_only_new_rows(fake_engine_root: Path, tmp_path: Path) -> None:
    from test_runner import make_runtime_layout, ok_preflight
    from media_missher_history import load_run, HistoryError, prepare_continuation
    layout = make_runtime_layout(fake_engine_root)
    script = layout.current / "scripts/scrape_all.py"
    source = script.read_text().replace('parser.add_argument("--search")', 'parser.add_argument("--search")\nparser.add_argument("--exclude-file", type=Path)')
    source = source.replace('args = parser.parse_args()', 'args = parser.parse_args()\nskips = json.loads(args.exclude_file.read_text())["platforms"] if args.exclude_file else {}')
    source = source.replace('for index in range(count)]', 'for index in range(len(skips.get(platform, [])), len(skips.get(platform, [])) + count)]')
    script.write_text(source)
    request = CollectionRequest(("douyin",), count=3, platform_uids={"douyin": "fixture"}, allow_navigation=True)
    root = tmp_path / "runs"
    digest = "a" * 64
    first = run_collection_request(request, layout=layout, data_root=root, preflight_runner=ok_preflight, profile_digest=digest, command_environment={"MEDIA_MISSHER_FAKE_COUNT_CAP": "1"})
    assert first["status"] == "partial"
    parent = Path(first["run_dir"])
    original = {path.relative_to(parent): hashlib.sha256(path.read_bytes()).hexdigest() for path in parent.rglob("*") if path.is_file()}
    second = run_collection_request(request, layout=layout, data_root=root, preflight_runner=ok_preflight, profile_digest=digest, resume_run=parent.name)
    assert second["status"] == "success"
    assert second["run_dir"] != first["run_dir"]
    assert second["continuation"]["prior_counts"] == {"douyin": 1}
    assert second["continuation"]["new_counts"] == {"douyin": 2}
    new = load_run(root, Path(second["run_dir"]).name)
    assert {row["aweme_id"] for row in new["records"]} == {"synthetic-douyin-1", "synthetic-douyin-2"}
    assert original == {path.relative_to(parent): hashlib.sha256(path.read_bytes()).hexdigest() for path in parent.rglob("*") if path.is_file()}
    with pytest.raises(HistoryError, match="no remaining"):
        prepare_continuation(root, Path(second["run_dir"]).name, request, digest)


def test_exclusion_plan_does_not_accept_symlinks_or_unsafe_permissions(tmp_path: Path) -> None:
    from runtime.media_missher_runtime.continuation import apply_exclusions
    from runtime.media_missher_runtime.models import CollectionRequest as RuntimeRequest
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"schema": 1, "platforms": {"xhs": ["old"]}}))
    path.chmod(0o600)
    requests = [RuntimeRequest("xhs", 1, uid="fixture")]
    assert apply_exclusions(path, requests)[0].exclude_ids == ("old",)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        apply_exclusions(link, requests)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="unsafe"):
        apply_exclusions(path, requests)


def test_new_controller_rejects_an_older_runtime_before_live_preflight(fake_engine_root: Path, tmp_path: Path) -> None:
    from test_runner import make_runtime_layout
    layout = make_runtime_layout(fake_engine_root)
    (layout.current / "VERSION").write_text("15.2.1\n")
    def unexpected(*_args, **_kwargs):
        pytest.fail("an old core reached live preflight")
    result = run_collection_request(CollectionRequest(("xhs",), count=1, platform_uids={"xhs": "fixture"}), layout=layout, data_root=tmp_path / "runs", preflight_runner=unexpected)
    assert result["status"] == "preflight-failed"
    assert result["preflight"]["checks"]["runtime_version"] is False


def test_controller_only_risk_signal_persists_xhs_pause_after_owned_child_stops(fake_engine_root, tmp_path):
    import time
    from test_runner import make_runtime_layout, ok_preflight
    from runtime.media_missher_runtime.xhs_policy import XhsSafetyGate
    layout = make_runtime_layout(fake_engine_root)
    source_root = Path(__file__).resolve().parents[1] / "runtime"
    script = layout.current / "scripts/scrape_all.py"
    script.write_text(f'import sys, time\nsys.path.insert(0, {str(source_root)!r})\nfrom media_missher_runtime.xhs_policy import XhsSafetyGate, default_state_dir\nwith XhsSafetyGate(default_state_dir()).batch():\n print("HTTP 429", flush=True)\n time.sleep(60)\n')
    result = run_collection_request(CollectionRequest(("xhs",), count=1, platform_uids={"xhs": "fixture"}), layout=layout, data_root=tmp_path / "runs", preflight_runner=ok_preflight, execution_timeout=5)
    assert result["status"] == "risk-stopped"
    status = XhsSafetyGate(layout.state, clock=lambda: time.time() + 3600).status()
    assert status["reason"] == "xhs-risk-latched"
    assert status["risk"]["code"] == "risk-signal"
