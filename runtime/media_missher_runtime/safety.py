from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RiskDecision:
    stop_all: bool
    reason: str | None = None


_RISK_CODES = frozenset({461, 471, 999})
_RISK_MARKERS = ("risk", "locked", "blocked", "cooldown")


def classify_response(*, status: int, payload: object = None, text: str | None = None) -> RiskDecision:
    if status in {403, 429}:
        return RiskDecision(True, f"http-{status}")
    if isinstance(payload, Mapping) and str(payload.get("code", "")).isdigit():
        code = int(payload["code"])
        if code in _RISK_CODES:
            return RiskDecision(True, f"payload-{code}")
    lowered = (text or "").casefold()
    marker = next((item for item in _RISK_MARKERS if item in lowered), None)
    return RiskDecision(marker is not None, marker)


def bounded_pages(*, requested: int, page_cap: int) -> Iterator[int]:
    if requested < 0 or page_cap < 1:
        raise ValueError("requested must be nonnegative and page_cap must be positive")
    yield from range(1, min(requested, page_cap) + 1)


@dataclass(slots=True)
class Pacer:
    sleeper: Callable[[float], object]
    jitter: Callable[[], float]
    base_seconds: float = 0.0

    def pause(self) -> float:
        duration = self.base_seconds + self.jitter()
        self.sleeper(duration)
        return duration
