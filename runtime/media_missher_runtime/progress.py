"""Bounded, content-free phase measurements; stdout is reserved for results."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

PREFIX = b"media-missher-progress "
PHASES = frozenset({"controller-preflight", "engine", "browser-preflight", "platform-collection", "validation", "output", "run"})
STATES = frozenset({"started", "updated", "completed", "failed", "cancelled"})
PLATFORMS = frozenset({"bilibili", "xhs", "douyin", "weibo", "x"})
MAX_EVENTS = 128
MAX_LINE_BYTES = 512
MAX_MILLISECONDS = 604800000


def valid_event(value):
    if not isinstance(value, dict):
        return None
    required = {"schema", "phase", "state", "elapsed_ms"}
    if value.get("phase") == "platform-collection":
        required |= {"platform", "completed", "requested"}
    if value.get("state") in {"completed", "failed", "cancelled"}:
        required.add("duration_ms")
    if set(value) != required or type(value.get("schema")) is not int or value["schema"] != 1:
        return None
    if value.get("phase") not in PHASES or value.get("state") not in STATES:
        return None
    for key in ("elapsed_ms", "duration_ms", "completed", "requested"):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= (10000 if key in {"completed", "requested"} else MAX_MILLISECONDS)):
            return None
    if "duration_ms" in value and value["duration_ms"] > value["elapsed_ms"]:
        return None
    if value["phase"] == "platform-collection" and value["platform"] not in PLATFORMS:
        return None
    return dict(value)


def parse_line(line):
    if not isinstance(line, bytes) or len(line) > MAX_LINE_BYTES or not line.startswith(PREFIX):
        return None
    try:
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate field")
                value[key] = item
            return value
        return valid_event(json.loads(line[len(PREFIX):], object_pairs_hook=unique))
    except (ValueError, UnicodeError, TypeError):
        return None


class ProgressStream:
    """Keep at most one bounded line; unrecognized bytes retain diagnostic handling."""
    def __init__(self, receive, ordinary=lambda _data: None):
        self.receive = receive
        self.ordinary = ordinary
        self.pending = b""
        self.discarding = False
        self.count = 0
        self.last_elapsed = -1
        self.last_update = -1.0

    def feed(self, chunk):
        for part in chunk.splitlines(keepends=True):
            terminal = part.endswith(b"\n")
            if self.discarding:
                self.ordinary(part)
                if terminal:
                    self.discarding = False
                continue
            self.pending += part
            if not self.pending.startswith(PREFIX) and not PREFIX.startswith(self.pending):
                self.ordinary(self.pending)
                self.pending = b""
                self.discarding = not terminal
                continue
            if len(self.pending) > MAX_LINE_BYTES:
                self.ordinary(self.pending)
                self.pending = b""
                self.discarding = not terminal
            elif terminal:
                line, self.pending = self.pending, b""
                event = parse_line(line)
                if event is None:
                    self.ordinary(line)
                    continue
                now = time.monotonic()
                if self.count >= MAX_EVENTS or event["elapsed_ms"] < self.last_elapsed or (event["state"] == "updated" and now - self.last_update < 0.25):
                    continue
                self.count += 1
                self.last_elapsed = event["elapsed_ms"]
                if event["state"] == "updated":
                    self.last_update = now
                try:
                    self.receive(event)
                except Exception:
                    pass

    def finish(self):
        if self.pending:
            self.feed(b"\n")


class ProgressRecorder:
    def __init__(self, *, stream=None, clock=time.monotonic, enabled=True):
        self.enabled = enabled
        self.clock = clock
        self.started = clock()
        self.stream = sys.stderr if stream is None else stream
        self.timings = []
        self.path = None
        self.storage_failed = False
        self.count = 0
        self.last_elapsed = 0
        self.last_update = -1.0

    def elapsed(self):
        self.last_elapsed = min(MAX_MILLISECONDS, max(self.last_elapsed, int((self.clock() - self.started) * 1000)))
        return self.last_elapsed

    def bind_path(self, path):
        self.path = Path(path)
        self.persist()

    def persist(self):
        if self.path is None or self.storage_failed:
            return
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix=".phase-timings-", dir=self.path.parent)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self.timings, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.is_symlink():
                raise ValueError("progress path invalid")
            os.replace(temporary, self.path)
        except (OSError, ValueError):
            self.storage_failed = True
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def emit(self, event):
        event = valid_event(event)
        if event is None:
            return
        terminal = event["state"] in {"completed", "failed", "cancelled"}
        if terminal and len(self.timings) < 32:
            self.timings.append(event)
            self.persist()
        now = self.clock()
        if self.count >= MAX_EVENTS or (event["state"] == "updated" and now - self.last_update < 0.25):
            return
        self.count += 1
        if event["state"] == "updated":
            self.last_update = now
        if not self.enabled:
            return
        try:
            self.stream.write(PREFIX.decode("ascii") + json.dumps(event, separators=(",", ":")) + "\n")
            self.stream.flush()
        except Exception:
            pass

    def start(self, phase, *, platform=None, requested=0):
        token = {"schema": 1, "phase": phase, "state": "started", "elapsed_ms": self.elapsed()}
        if platform is not None:
            token.update(platform=platform, completed=0, requested=requested)
        self.emit(token)
        return token

    def update(self, token, completed):
        self.emit({**token, "state": "updated", "elapsed_ms": self.elapsed(), "completed": completed})

    def finish(self, token, state="completed", *, completed=0):
        elapsed = self.elapsed()
        event = {**token, "state": state, "elapsed_ms": elapsed, "duration_ms": max(0, elapsed - token["elapsed_ms"])}
        if "platform" in token:
            event["completed"] = completed
        self.emit(event)

    def relay(self, event):
        event = valid_event(event)
        if event is not None and event["phase"] in {"browser-preflight", "platform-collection"}:
            elapsed = self.elapsed()
            if event.get("duration_ms", 0) <= elapsed:
                self.emit({**event, "elapsed_ms": elapsed})
