"""Persistent normal start spacing. Caller holds the shared collection lease.

These are engineering budgets, not platform-approved safe rates. Failed starts
still consume their reservation; changing target or runtime home cannot reset
it. XHS retains its existing, stricter shared gate and migration protocol.
"""
from __future__ import annotations

import asyncio
import math
import os
import time

from .batch_journal import atomic_json
from .batch_policy import DEFAULT_POLICIES
from .shared_safety import SharedSafetyError, _read_marker, shared_directory


class CollectionPacing:
    def __init__(self, *, clock=time.time, sleep=asyncio.sleep, interval=0.0):
        self.clock = clock
        self.sleep = sleep
        self.interval = interval
        self.path = shared_directory() / "collection-pacing.json"

    def _read(self):
        try:
            value = _read_marker(self.path) if os.path.lexists(self.path) else {"schema_version": 1, "platforms": {}}
            if not isinstance(value, dict) or set(value) != {"schema_version", "platforms"} or type(value["schema_version"]) is not int or value["schema_version"] != 1 or not isinstance(value["platforms"], dict):
                raise ValueError("pacing schema")
            for platform, stamp in value["platforms"].items():
                if platform not in DEFAULT_POLICIES or not isinstance(stamp, dict) or set(stamp) != {"started_at", "next_start_at"}:
                    raise ValueError("pacing entry")
                if any(type(n) not in {int, float} or not math.isfinite(n) or n < 0 for n in stamp.values()) or stamp["next_start_at"] < stamp["started_at"]:
                    raise ValueError("pacing timestamp")
            return value
        except (ValueError, OSError) as error:
            raise SharedSafetyError("shared-state-invalid") from error

    def _now(self):
        now = self.clock()
        if type(now) not in {int, float} or not math.isfinite(now) or now < 0:
            raise SharedSafetyError("shared-state-invalid")
        return now

    def remaining(self, platform):
        if platform not in DEFAULT_POLICIES:
            raise SharedSafetyError("shared-state-invalid")
        entry = self._read()["platforms"].get(platform)
        return max(0.0, entry["next_start_at"] - self._now()) if entry else 0.0

    def reserve(self, platform):
        if self.remaining(platform):
            raise SharedSafetyError("platform-cooldown")
        self.mark_started(platform)

    def mark_started(self, platform):
        if platform not in DEFAULT_POLICIES or type(self.interval) not in {int, float} or not math.isfinite(self.interval) or self.interval < 0:
            raise SharedSafetyError("shared-state-invalid")
        value = self._read()
        now = self._now()
        interval = max(self.interval, DEFAULT_POLICIES[platform].interval_seconds)
        prior = value["platforms"].get(platform, {})
        value["platforms"][platform] = {
            "started_at": max(now, prior.get("started_at", now)),
            "next_start_at": max(now + interval, prior.get("next_start_at", 0)),
        }
        atomic_json(self.path, value)

    async def wait_and_reserve(self, platform):
        # Cancellation/outer run deadline can interrupt this await before any
        # new page operation. A backward clock change extends the pause.
        while remaining := self.remaining(platform):
            await self.sleep(remaining)
        self.reserve(platform)
