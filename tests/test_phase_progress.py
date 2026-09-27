import asyncio
import json
import sys
from pathlib import Path

from media_missher_adapter import EngineCommand, execute_engine
from runtime.media_missher_runtime.cli import _run_immediate, _run_requests
from runtime.media_missher_runtime.models import CollectionRequest

PREFIX = 'media-missher-progress '


class Dispatcher:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def preflight(self, _requests):
        return None

    async def collect(self, request):
        return [{"platform": request.platform, "mblog_id": "private-id", "text": "private-content"}]


def test_runtime_emits_safe_monotonic_phases_and_durable_timings(tmp_path, capsys):
    code = _run_immediate(_run_requests(
        [CollectionRequest(platform='weibo', uid='private-uid', count=1)],
        output_dir=tmp_path, dispatcher=Dispatcher(), platform_timeout=0,
    ))
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out == ''
    events = [json.loads(line[len(PREFIX):]) for line in captured.err.splitlines() if line.startswith(PREFIX)]
    assert events, 'runtime must publish bounded structured phase events'
    assert {'browser-preflight', 'platform-collection', 'run'} <= {event['phase'] for event in events}
    assert [event['elapsed_ms'] for event in events] == sorted(event['elapsed_ms'] for event in events)
    assert 'private-' not in captured.err
    timings = json.loads(next(tmp_path.glob('run-*/phase-timings.json')).read_text())
    platform = next(event for event in timings if event['phase'] == 'platform-collection')
    assert platform['state'] == 'completed' and platform['completed'] == 1
    assert platform['duration_ms'] >= 0


def test_cancelled_runtime_keeps_terminal_platform_timing(tmp_path):
    class Cancelled(Dispatcher):
        async def collect(self, _request):
            raise asyncio.CancelledError()
    try:
        _run_immediate(_run_requests(
            [CollectionRequest(platform='weibo', uid='private-uid', count=1)],
            output_dir=tmp_path, dispatcher=Cancelled(), platform_timeout=0,
        ))
    except asyncio.CancelledError:
        pass
    files = list(tmp_path.glob('run-*/phase-timings.json'))
    assert files, 'cancellation must retain measured phase timings'
    events = json.loads(files[0].read_text())
    assert next(event for event in events if event['phase'] == 'platform-collection')['state'] == 'cancelled'


def test_engine_relays_only_valid_progress_without_turning_429ms_into_risk(tmp_path, capsys):
    source = tmp_path / 'runtime.py'
    event = {'schema': 1, 'phase': 'platform-collection', 'state': 'completed', 'platform': 'weibo', 'completed': 1, 'requested': 1, 'elapsed_ms': 429, 'duration_ms': 429}
    line = PREFIX + json.dumps(event) + '\n'
    split = line.index('429') + 3
    source.write_text('import sys, time\ntime.sleep(0.45)\nsys.stderr.write(' + repr(line[:split]) + '); sys.stderr.flush(); time.sleep(0.05)\nsys.stderr.write(' + repr(line[split:]) + ')\n')
    from runtime.media_missher_runtime import progress
    result = execute_engine(EngineCommand(source, (sys.executable, str(source))), timeout=3, run_dir=tmp_path, progress_module=progress, reporter=progress.ProgressRecorder())
    assert not result.risk_detected
    assert PREFIX in capsys.readouterr().err


def test_controller_accepts_each_platform_precondition_but_rejects_extra_text():
    from media_missher_adapter import _runtime_precondition_diagnostics
    lines = ''.join(f'media-missher-diagnostic platform={platform} kind=precondition code=collection-busy\n' for platform in ('weibo', 'xhs'))
    assert _runtime_precondition_diagnostics(returncode=78, stderr=lines) == {
        platform: {'kind': 'precondition', 'code': 'collection-busy'} for platform in ('weibo', 'xhs')
    }
    assert _runtime_precondition_diagnostics(returncode=78, stderr=lines + 'private\n') is None
    assert _runtime_precondition_diagnostics(returncode=78, stderr=lines + lines) is None


def test_installed_progress_loader_needs_no_source_tree(tmp_path):
    import shutil
    from media_missher_progress import load_progress
    target = tmp_path / 'current' / 'media_missher_runtime'
    target.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parents[1] / 'runtime/media_missher_runtime/progress.py', target / 'progress.py')
    assert load_progress(target.parent).parse_line((PREFIX + '{"schema":1,"phase":"run","state":"started","elapsed_ms":0}\n').encode())['phase'] == 'run'


def test_controller_summary_retains_timings_without_altering_history_schema(fake_engine_root, tmp_path):
    from test_runner import make_runtime_layout, ok_preflight
    from media_missher_adapter import CollectionRequest as Request, _run_collection_request_unlocked
    result = _run_collection_request_unlocked(Request(platforms=('weibo',), platform_uids={'weibo': '12345'}, count=1), layout=make_runtime_layout(fake_engine_root), data_root=tmp_path / 'runs', preflight_runner=ok_preflight)
    assert result['status'] == 'success'
    assert {'controller-preflight', 'engine', 'validation', 'output', 'run'} <= {event['phase'] for event in result.get('phase_timings', [])}
    saved = json.loads((Path(result['run_dir']) / 'phase-timings.json').read_text())
    assert saved == result['phase_timings']
    assert set(json.loads((Path(result['run_dir']) / 'run-result.json').read_text())) == {'schema', 'status'}


def test_optional_reporter_failure_cannot_skip_signal_handler_restoration(tmp_path):
    import signal
    class Broken:
        def start(self, _phase):
            return {}
        def finish(self, *_args):
            raise OSError('private storage failure')
    source = tmp_path / 'short.py'
    source.write_text('pass\n')
    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    result = execute_engine(EngineCommand(source, (sys.executable, str(source))), timeout=3, run_dir=tmp_path, reporter=Broken())
    assert result.returncode == 0
    assert {number: signal.getsignal(number) for number in previous} == previous


def test_progress_storage_failure_leaves_measured_values_available(tmp_path):
    import io
    from runtime.media_missher_runtime.progress import ProgressRecorder
    recorder = ProgressRecorder(stream=io.StringIO())
    recorder.bind_path(tmp_path / 'missing' / 'phase-timings.json')
    token = recorder.start('run')
    recorder.finish(token)
    assert recorder.timings[0]['phase'] == 'run'
    assert recorder.storage_failed is True


def test_ordinary_risk_without_newline_still_stops_promptly(tmp_path):
    from runtime.media_missher_runtime import progress
    source = tmp_path / 'runtime.py'
    source.write_text('import sys, time\nsys.stderr.write("HTTP 429"); sys.stderr.flush(); time.sleep(10)\n')
    result = execute_engine(EngineCommand(source, (sys.executable, str(source))), timeout=3, run_dir=tmp_path, progress_module=progress, reporter=progress.ProgressRecorder())
    assert result.risk_detected and not result.timed_out
    assert result.duration_seconds < 2


def test_progress_parser_bounds_fragmented_unknown_oversized_and_high_rate_events():
    from runtime.media_missher_runtime.progress import ProgressStream
    safe, ordinary = [], []
    parser = ProgressStream(safe.append, ordinary.append)
    event = {'schema': 1, 'phase': 'platform-collection', 'state': 'updated', 'platform': 'weibo', 'completed': 1, 'requested': 2, 'elapsed_ms': 999}
    encoded = (PREFIX + json.dumps(event) + '\n').encode()
    for byte in encoded:
        parser.feed(bytes([byte]))
    parser.feed(encoded * 200)
    parser.feed((PREFIX + json.dumps({**event, 'uid': 'private'}) + '\n').encode())
    parser.feed((PREFIX + 'x' * 2000 + '\n').encode())
    assert len(safe) == 1
    assert b'private' in b''.join(ordinary)
    assert all('private' not in json.dumps(value) for value in safe)
    parser.feed((PREFIX + json.dumps({**event, 'state': 'completed', 'duration_ms': 1}) + '\n').encode() * 200)
    assert len(safe) == 128


def test_missing_installed_progress_is_controlled_before_preflight(fake_engine_root, tmp_path):
    from test_runner import make_runtime_layout
    from media_missher_adapter import CollectionRequest as Request, _run_collection_request_unlocked
    layout = make_runtime_layout(fake_engine_root)
    (layout.current / 'media_missher_runtime' / 'progress.py').unlink()
    def forbidden(*_args, **_kwargs):
        raise AssertionError('preflight must not probe a malformed runtime')
    result = _run_collection_request_unlocked(Request(platforms=('weibo',), platform_uids={'weibo': '12345'}, count=1), layout=layout, data_root=tmp_path / 'runs', preflight_runner=forbidden)
    assert result['status'] == 'preflight-failed'
    assert result['preflight']['code'] == 'progress-module-invalid'
