import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from media_missher_adapter import EngineCommand, create_run_directory, execute_engine


ADAPTER_CONTROLLER = r'''#!/usr/bin/env python3
import sys
import shutil
from dataclasses import replace
from pathlib import Path

scripts, runtime, home, run_dir, runtime_pid, heartbeat, term_seen, ready = map(Path, sys.argv[1:])
sys.path.insert(0, str(scripts))

from media_missher_adapter import EngineCommand, RuntimeLayout, _collection_lease, execute_engine

home.mkdir(mode=0o700)
(home / "current" / "media_missher_runtime").mkdir(parents=True)
shutil.copyfile(scripts.parents[1] / "runtime" / "media_missher_runtime" / "shared_safety.py", home / "current" / "media_missher_runtime" / "shared_safety.py")
layout = RuntimeLayout(
    home=home,
    current=home / "current",
    python=Path(sys.executable),
    state=home / "state",
)
command = EngineCommand(
    script=runtime,
    argv=(sys.executable, str(runtime), str(runtime_pid), str(heartbeat), str(term_seen)),
)
with _collection_lease(layout) as lease:
    command = replace(command, pass_fds=lease.pass_fds)
    ready.write_text("ready\n", encoding="ascii")
    execute_engine(command, timeout=30, run_dir=run_dir)
'''


STUBBORN_RUNTIME = r'''#!/usr/bin/env python3
import os
import signal
import sys
import time
from pathlib import Path

pid_path, heartbeat_path, term_seen_path = map(Path, sys.argv[1:])

def ignore_term(_signum, _frame):
    term_seen_path.write_text("term\n", encoding="ascii")

signal.signal(signal.SIGTERM, ignore_term)
temporary_pid = pid_path.with_suffix(".writing")
temporary_pid.write_text(f"{os.getpid()}\n", encoding="ascii")
temporary_pid.replace(pid_path)
with heartbeat_path.open("ab", buffering=0) as heartbeat:
    while True:
        heartbeat.write(b".")
        time.sleep(0.02)
'''


def _write_script(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)
    return path


def _wait_for_path(path: Path, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path.name}")


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_pid_exit(pid: int, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_is_alive(pid):
            return
        time.sleep(0.01)
    raise AssertionError(f"process {pid} remained alive")


def _stop_test_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=3)


def _stop_test_process_group(pid: int) -> None:
    if not _pid_is_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    _wait_for_pid_exit(pid)


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
def test_adapter_signal_stops_owned_runtime_before_releasing_collection_lease(
    tmp_path: Path, stop_signal: int,
) -> None:
    scripts = Path(__file__).resolve().parents[1] / "media-missher" / "scripts"
    controller_script = _write_script(tmp_path / "adapter_controller.py", ADAPTER_CONTROLLER)
    runtime_script = _write_script(tmp_path / "stubborn_runtime.py", STUBBORN_RUNTIME)
    home = tmp_path / "runtime-home"
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    runtime_pid_path = tmp_path / "owned.pid"
    heartbeat_path = tmp_path / "owned.heartbeat"
    term_seen_path = tmp_path / "owned.term"
    ready_path = tmp_path / "adapter.ready"
    adjacent_pid_path = tmp_path / "adjacent.pid"
    adjacent_heartbeat = tmp_path / "adjacent.heartbeat"
    adjacent_term_seen = tmp_path / "adjacent.term"

    adjacent = subprocess.Popen(
        (
            sys.executable,
            str(runtime_script),
            str(adjacent_pid_path),
            str(adjacent_heartbeat),
            str(adjacent_term_seen),
        ),
        start_new_session=True,
    )
    controller = subprocess.Popen(
        (
            sys.executable,
            str(controller_script),
            str(scripts),
            str(runtime_script),
            str(home),
            str(run_dir),
            str(runtime_pid_path),
            str(heartbeat_path),
            str(term_seen_path),
            str(ready_path),
        ),
        start_new_session=True,
    )
    try:
        _wait_for_path(adjacent_pid_path)
        _wait_for_path(runtime_pid_path)
        _wait_for_path(ready_path)
        runtime_pid = int(runtime_pid_path.read_text(encoding="ascii"))

        os.killpg(controller.pid, stop_signal)

        _wait_for_path(term_seen_path, timeout=2.0)
        assert controller.poll() is None
        descriptor = os.open(home / ".media-missher-collection.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)

        assert controller.wait(timeout=4) == -stop_signal
        _wait_for_pid_exit(runtime_pid)
        assert adjacent.poll() is None
        assert not adjacent_term_seen.exists()
    finally:
        if runtime_pid_path.exists():
            _stop_test_process_group(
                int(runtime_pid_path.read_text(encoding="ascii"))
            )
        _stop_test_process(controller)
        _stop_test_process(adjacent)


def test_execute_engine_timeout_escalates_only_its_stubborn_process_group(
    tmp_path: Path,
) -> None:
    runtime_script = _write_script(tmp_path / "stubborn_runtime.py", STUBBORN_RUNTIME)
    owned_pid_path = tmp_path / "owned.pid"
    owned_heartbeat = tmp_path / "owned.heartbeat"
    owned_term_seen = tmp_path / "owned.term"
    adjacent_pid_path = tmp_path / "adjacent.pid"
    adjacent_heartbeat = tmp_path / "adjacent.heartbeat"
    adjacent_term_seen = tmp_path / "adjacent.term"
    adjacent = subprocess.Popen(
        (
            sys.executable,
            str(runtime_script),
            str(adjacent_pid_path),
            str(adjacent_heartbeat),
            str(adjacent_term_seen),
        ),
        start_new_session=True,
    )
    try:
        _wait_for_path(adjacent_pid_path)
        run_dir = create_run_directory(tmp_path / "runs")
        command = EngineCommand(
            script=runtime_script,
            argv=(
                sys.executable,
                str(runtime_script),
                str(owned_pid_path),
                str(owned_heartbeat),
                str(owned_term_seen),
            ),
        )

        completed = execute_engine(command, timeout=1, run_dir=run_dir)

        owned_pid = int(owned_pid_path.read_text(encoding="ascii"))
        assert completed.timed_out is True
        assert completed.returncode == -signal.SIGKILL
        assert completed.duration_seconds < 4
        assert owned_term_seen.exists()
        _wait_for_pid_exit(owned_pid)
        assert adjacent.poll() is None
        assert not adjacent_term_seen.exists()
    finally:
        _stop_test_process(adjacent)


@pytest.mark.parametrize("ignored_term", [False, True])
def test_harness_abort_waits_for_owned_runtime_teardown(tmp_path: Path, ignored_term: bool) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node 22.19+ is needed for the actual Harness wrapper")
    version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    if tuple(map(int, version.split(".")[:2])) < (22, 19):
        pytest.skip("Node 22.19+ native TypeScript support is required")
    root = Path(__file__).resolve().parents[1]
    source = ADAPTER_CONTROLLER
    if ignored_term:
        source = source.replace("import sys", "import sys\nimport signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)", 1)
    controller = _write_script(tmp_path / "controller.py", source)
    runtime = _write_script(tmp_path / "worker.py", STUBBORN_RUNTIME)
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    pid_path = tmp_path / "worker.pid"
    home = tmp_path / "runtime-home"
    argv = list(map(str, [controller, root / "media-missher/scripts", runtime, home, run_dir, pid_path, tmp_path / "beat", tmp_path / "term", tmp_path / "ready"]))
    wrapper = _write_script(tmp_path / "wrapper.mjs", f'''
import {{runProcess}} from {json.dumps((root / "harness-plugin/src/process.ts").as_uri())};
import {{existsSync, readFileSync}} from 'node:fs';
const controller = new AbortController();
const deadline = setTimeout(() => controller.abort(), 4000);
const poll = setInterval(() => {{ if (existsSync({json.dumps(str(pid_path))})) controller.abort(); }}, 10);
let errorCode = '';
try {{ await runProcess({json.dumps(sys.executable)}, {json.dumps(argv)}, {{signal: controller.signal}}); }}
catch (error) {{ errorCode = error.message; }}
finally {{ clearTimeout(deadline); clearInterval(poll); }}
const pid = Number(readFileSync({json.dumps(str(pid_path))}, 'utf8'));
let alive = true;
try {{ process.kill(pid, 0); }} catch (error) {{ if (error.code === 'ESRCH') alive = false; else throw error; }}
process.stdout.write(JSON.stringify({{errorCode, alive}}));
''')
    try:
        result = subprocess.run([node, str(wrapper)], capture_output=True, text=True, timeout=15, check=True)
        observed = json.loads(result.stdout)
        assert observed == {"errorCode": "process_aborted", "alive": False}
        descriptor = os.open(home / ".media-missher-collection.lock", os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
    finally:
        if pid_path.exists():
            _stop_test_process_group(int(pid_path.read_text()))


def test_execute_engine_restores_custom_signal_handlers(tmp_path: Path) -> None:
    script = _write_script(tmp_path / "quick.py", "pass\n")
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
    def custom(_signum, _frame):
        pass
    try:
        for signum in previous:
            signal.signal(signum, custom)
        completed = execute_engine(EngineCommand(script, (sys.executable, str(script))), timeout=2, run_dir=create_run_directory(tmp_path / "runs"))
        assert completed.returncode == 0
        assert all(signal.getsignal(signum) is custom for signum in previous)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def test_risk_stop_terminates_owned_grandchild(tmp_path: Path) -> None:
    child_pid = tmp_path / "grandchild.pid"
    worker = _write_script(tmp_path / "grandchild.py", STUBBORN_RUNTIME)
    script = _write_script(tmp_path / "risk_parent.py", f'''
import subprocess, sys, time
from pathlib import Path
subprocess.Popen([sys.executable, {str(worker)!r}, {str(child_pid)!r}, {str(tmp_path / "heartbeat")!r}, {str(tmp_path / "term")!r}])
while not Path({str(child_pid)!r}).exists(): time.sleep(0.01)
print("risk signal 429", file=sys.stderr, flush=True)
time.sleep(10)
''')
    try:
        result = execute_engine(EngineCommand(script, (sys.executable, str(script))), timeout=5, run_dir=create_run_directory(tmp_path / "runs"))
        assert result.risk_detected is True
        assert result.timed_out is False
        _wait_for_pid_exit(int(child_pid.read_text()))
    finally:
        if child_pid.exists() and _pid_is_alive(int(child_pid.read_text())):
            os.kill(int(child_pid.read_text()), signal.SIGKILL)


@pytest.mark.parametrize("code", ["xhs-cooldown", "xhs-risk-latched"])
def test_local_start_guard_preserves_exit_diagnostic(tmp_path: Path, code: str) -> None:
    script = _write_script(tmp_path / "guard.py", f'import sys\nprint("media-missher-diagnostic platform=xhs kind=precondition code={code}", file=sys.stderr, flush=True)\nraise SystemExit(78)\n')
    result = execute_engine(EngineCommand(script, (sys.executable, str(script))), timeout=3, run_dir=create_run_directory(tmp_path / "runs"))
    assert result.returncode == 78
    assert result.risk_detected is False


@pytest.mark.parametrize("text", [
    "media-missher-diagnostic platform=xhs kind=precondition code=xhs-cooldown forged=1",
    "media-missher-diagnostic platform=xhs kind=precondition code=xhs-cooldown\nrisk signal 429",
])
def test_local_guard_allowlist_does_not_suppress_other_risk(tmp_path: Path, text: str) -> None:
    script = _write_script(tmp_path / "risk.py", f'import sys, time\nprint({text!r}, file=sys.stderr, flush=True)\ntime.sleep(10)\n')
    result = execute_engine(EngineCommand(script, (sys.executable, str(script))), timeout=3, run_dir=create_run_directory(tmp_path / "runs"))
    assert result.risk_detected is True
    assert result.timed_out is False
