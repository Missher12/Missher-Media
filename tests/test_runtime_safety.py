from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("status", "payload", "text"),
    (
        (403, None, None),
        (429, None, None),
        (200, {"code": 461}, None),
        (200, {"code": "471"}, None),
        (200, {"code": 999}, None),
        (200, None, "account locked"),
        (200, None, "request blocked"),
        (200, None, "risk control"),
        (200, None, "cooldown active"),
    ),
)
def test_risk_response_stops_collection(status: int, payload: object, text: str | None) -> None:
    from runtime.media_missher_runtime.safety import classify_response

    decision = classify_response(status=status, payload=payload, text=text)

    assert decision.stop_all is True
    assert decision.reason


def test_non_risk_response_can_continue() -> None:
    from runtime.media_missher_runtime.safety import classify_response

    assert classify_response(status=200, payload={"code": 0}, text="normal").stop_all is False


def test_bounded_pages_never_exceeds_the_page_cap() -> None:
    from runtime.media_missher_runtime.safety import bounded_pages

    assert list(bounded_pages(requested=100, page_cap=3)) == [1, 2, 3]
    assert list(bounded_pages(requested=0, page_cap=3)) == []


def test_pacer_uses_injected_sleeper_and_deterministic_jitter() -> None:
    from runtime.media_missher_runtime.safety import Pacer

    pauses: list[float] = []
    pacer = Pacer(sleeper=pauses.append, jitter=lambda: 0.25, base_seconds=1.0)

    assert pacer.pause() == 1.25
    assert pauses == [1.25]


@pytest.mark.parametrize("base_seconds", (-1.0, float("nan"), float("inf"), "slow"))
def test_pacer_rejects_invalid_base_seconds(base_seconds: object) -> None:
    from runtime.media_missher_runtime.safety import Pacer

    pauses: list[float] = []
    with pytest.raises(ValueError, match="base_seconds"):
        Pacer(sleeper=pauses.append, jitter=lambda: 0.0, base_seconds=base_seconds)  # type: ignore[arg-type]

    assert pauses == []


def test_pacer_rejects_a_negative_computed_delay_without_sleeping() -> None:
    from runtime.media_missher_runtime.safety import Pacer

    pauses: list[float] = []
    pacer = Pacer(sleeper=pauses.append, jitter=lambda: -2.0, base_seconds=1.0)

    with pytest.raises(ValueError, match="duration"):
        pacer.pause()
    assert pauses == []


@pytest.mark.parametrize("jitter", (float("nan"), float("inf"), "late"))
def test_pacer_rejects_nonfinite_or_nonnumeric_jitter_without_sleeping(jitter: object) -> None:
    from runtime.media_missher_runtime.safety import Pacer

    pauses: list[float] = []
    pacer = Pacer(sleeper=pauses.append, jitter=lambda: jitter, base_seconds=1.0)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="jitter"):
        pacer.pause()
    assert pauses == []
