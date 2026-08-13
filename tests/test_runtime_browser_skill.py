from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest

from runtime.media_missher_runtime.browser_skill import (
    MAX_COMMAND_OUTPUT,
    BrowserSkillBridge,
    BrowserSkillError,
    CommandResult,
)


TARGET_TOKEN = "a" * 32
TARGET_SELECTOR = f'[data-media-missher-target="{TARGET_TOKEN}"]'


def _json_result(value: object, *, returncode: int = 0) -> CommandResult:
    return CommandResult(
        returncode=returncode,
        stdout=json.dumps(value).encode("utf-8"),
        stderr=b"",
    )


def _healthy_status(**browser_changes: object) -> dict[str, object]:
    browser = {
        "instance_id": "8f024870",
        "extension_protocol_version": "1.0",
        "extension_version": "0.1.6",
        "version_skew": False,
        "session_count": 0,
    }
    browser.update(browser_changes)
    return {
        "daemon_version": "0.1.10",
        "protocol_version": "1.0",
        "browsers": [browser],
        "sessions": [],
        "version_skew_browsers": [],
    }


class FakeRunner:
    def __init__(self, responses: Mapping[tuple[str, ...], object]) -> None:
        self.responses = {key: value for key, value in responses.items()}
        self.commands: list[tuple[str, ...]] = []
        self.timeouts: list[float] = []

    async def run(self, *arguments: str, timeout: float) -> CommandResult:
        command = tuple(arguments)
        self.commands.append(command)
        self.timeouts.append(timeout)
        response = self.responses.get(command)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            response = response()
        if not isinstance(response, CommandResult):
            raise AssertionError(f"unexpected fake command: {command!r}")
        return response


class Page:
    async def title(self) -> str:
        return "media-missher-marker"


def _happy_responses(
    *,
    click_results: list[CommandResult] | None = None,
    snapshot_results: list[CommandResult] | None = None,
) -> dict[tuple[str, ...], object]:
    selector = TARGET_SELECTOR
    click_command = (
        "click",
        "--selector",
        selector,
        "--session",
        "abcd",
        "--tab-id",
        "41",
        "--timeout",
        "15s",
        "--json",
        "--quiet",
    )
    clicks = list(click_results or [_json_result({"ok": True})])
    snapshots = list(snapshot_results or [_json_result({"ok": True})])

    def next_click() -> CommandResult:
        if not clicks:
            raise AssertionError("unexpected extra click")
        return clicks.pop(0)

    def next_snapshot() -> CommandResult:
        if not snapshots:
            raise AssertionError("unexpected extra snapshot")
        return snapshots.pop(0)

    return {
        ("status", "--json", "--quiet"): _json_result(_healthy_status()),
        ("session", "list", "--json", "--quiet"): _json_result([]),
        ("session", "start", "--browser", "8f024870", "--json", "--quiet"): _json_result(
            {
                "session_id": "abcd",
                "browser_instance_id": "8f024870",
                "agent_window_id": 73,
            }
        ),
        ("tab", "list", "--session", "abcd", "--scope", "user", "--json", "--quiet"): _json_result(
            {"tabs": [{"tab_id": 41, "title": "media-missher-marker"}]}
        ),
        ("tab", "borrow", "41", "--session", "abcd", "--json", "--quiet"): _json_result({"tab_id": 41}),
        ("snapshot", "--session", "abcd", "--tab-id", "41", "--max-tokens", "4096", "--json", "--quiet"): next_snapshot,
        click_command: next_click,
        ("tab", "return", "41", "--session", "abcd", "--json", "--quiet"): _json_result({"tab_id": 41}),
        ("session", "stop", "abcd", "--quiet"): CommandResult(0, b"", b""),
    }


@pytest.mark.asyncio
async def test_bridge_happy_path_uses_exact_bounded_lifecycle() -> None:
    selector = TARGET_SELECTOR
    fake = FakeRunner(_happy_responses())
    bridge = BrowserSkillBridge(runner=fake)

    await bridge.preflight()
    await bridge.click_marked_tab(Page(), selector=selector)
    await bridge.close()

    assert fake.commands == [
        ("status", "--json", "--quiet"),
        ("session", "list", "--json", "--quiet"),
        ("session", "start", "--browser", "8f024870", "--json", "--quiet"),
        ("tab", "list", "--session", "abcd", "--scope", "user", "--json", "--quiet"),
        ("tab", "borrow", "41", "--session", "abcd", "--json", "--quiet"),
        ("snapshot", "--session", "abcd", "--tab-id", "41", "--max-tokens", "4096", "--json", "--quiet"),
        ("click", "--selector", selector, "--session", "abcd", "--tab-id", "41", "--timeout", "15s", "--json", "--quiet"),
        ("tab", "return", "41", "--session", "abcd", "--json", "--quiet"),
        ("session", "stop", "abcd", "--quiet"),
    ]
    assert all(timeout > 0 for timeout in fake.timeouts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (FileNotFoundError("/private/path/bsk"), "bsk-missing"),
        (_json_result({}, returncode=1), "bsk-unhealthy"),
        (_json_result({**_healthy_status(), "browsers": []}), "bsk-unhealthy"),
        (
            _json_result(
                {**_healthy_status(), "browsers": _healthy_status()["browsers"] * 2}
            ),
            "bsk-unhealthy",
        ),
        (_json_result(_healthy_status(version_skew=True)), "bsk-incompatible"),
        (_json_result(_healthy_status(extension_version="9.9.9")), "bsk-incompatible"),
        (_json_result(_healthy_status(extension_protocol_version="2.0")), "bsk-incompatible"),
        (
            _json_result(
                {
                    **_healthy_status(),
                    "protocol_version": "2.0",
                }
            ),
            "bsk-incompatible",
        ),
        (
            _json_result(
                {
                    **_healthy_status(),
                    "daemon_version": "0.2.0",
                }
            ),
            "bsk-incompatible",
        ),
    ),
)
async def test_preflight_fails_closed_for_health_and_compatibility(
    status: object, expected: str
) -> None:
    fake = FakeRunner({("status", "--json", "--quiet"): status})

    with pytest.raises(BrowserSkillError) as captured:
        await BrowserSkillBridge(runner=fake).preflight()

    assert captured.value.code == expected
    assert str(captured.value) == expected


@pytest.mark.asyncio
async def test_preflight_rejects_preexisting_session() -> None:
    fake = FakeRunner(
        {
            ("status", "--json", "--quiet"): _json_result(_healthy_status()),
            ("session", "list", "--json", "--quiet"): _json_result(
                [{"id": "private-session", "url": "https://private.invalid"}]
            ),
        }
    )

    with pytest.raises(BrowserSkillError) as captured:
        await BrowserSkillBridge(runner=fake).preflight()

    assert captured.value.code == "bsk-busy"
    assert "private" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start_response",
    (
        CommandResult(0, b"not-json private", b""),
        _json_result(
            {
                "session_id": "abcd",
                "browser_instance_id": "wrong-browser",
                "agent_window_id": 73,
            }
        ),
    ),
)
async def test_malformed_session_start_never_claims_or_stops_a_unique_external_session(
    start_response: CommandResult,
) -> None:
    session_lists = [
        _json_result([]),
        _json_result(
            [
                {
                    "session_id": "wxyz",
                    "browser_instance_id": "8f024870",
                    "agent_window_id": 73,
                    "created_at_ms": 1,
                }
            ]
        ),
    ]

    def next_session_list() -> CommandResult:
        return session_lists.pop(0)

    responses = _happy_responses()
    responses[("session", "list", "--json", "--quiet")] = next_session_list
    responses[("session", "start", "--browser", "8f024870", "--json", "--quiet")] = start_response
    fake = FakeRunner(responses)
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(Page(), selector=TARGET_SELECTOR)

    assert captured.value.code == "bsk-session-start"
    assert fake.commands.count(("session", "list", "--json", "--quiet")) == 1
    assert not any(command[:2] == ("session", "stop") for command in fake.commands)


@pytest.mark.asyncio
async def test_malformed_session_start_never_stops_ambiguous_sessions() -> None:
    session_lists = [
        _json_result([]),
        _json_result(
            [
                {
                    "session_id": "wxyz",
                    "browser_instance_id": "8f024870",
                    "agent_window_id": 73,
                    "created_at_ms": 1,
                },
                {
                    "session_id": "lmno",
                    "browser_instance_id": "8f024870",
                    "agent_window_id": 74,
                    "created_at_ms": 2,
                },
            ]
        ),
    ]

    def next_session_list() -> CommandResult:
        return session_lists.pop(0)

    responses = _happy_responses()
    responses[("session", "list", "--json", "--quiet")] = next_session_list
    responses[("session", "start", "--browser", "8f024870", "--json", "--quiet")] = CommandResult(
        0, b"not-json private", b""
    )
    fake = FakeRunner(responses)
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(Page(), selector=TARGET_SELECTOR)

    assert captured.value.code == "bsk-session-start"
    assert fake.commands.count(("session", "list", "--json", "--quiet")) == 1
    assert not any(command[:2] == ("session", "stop") for command in fake.commands)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tabs",
    (
        [],
        [
            {"tab_id": 41, "title": "media-missher-marker"},
            {"tab_id": 42, "title": "media-missher-marker"},
        ],
    ),
)
async def test_click_rejects_zero_or_multiple_exact_title_matches(tabs: list[dict[str, str]]) -> None:
    responses = _happy_responses()
    responses[("tab", "list", "--session", "abcd", "--scope", "user", "--json", "--quiet")] = _json_result(
        {"tabs": tabs}
    )
    fake = FakeRunner(responses)
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(
            Page(), selector=TARGET_SELECTOR
        )

    assert captured.value.code == "bsk-target-ambiguous"
    assert not any(command[:2] == ("tab", "borrow") for command in fake.commands)
    await bridge.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tab_id", (True, 0, -1, 2**63, "41"))
async def test_click_rejects_non_positive_or_non_i64_tab_ids(tab_id: object) -> None:
    responses = _happy_responses()
    responses[("tab", "list", "--session", "abcd", "--scope", "user", "--json", "--quiet")] = _json_result(
        {"tabs": [{"tab_id": tab_id, "title": "media-missher-marker"}]}
    )
    fake = FakeRunner(responses)
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(Page(), selector=TARGET_SELECTOR)

    assert captured.value.code == "bsk-target-ambiguous"
    assert not any(command[:2] == ("tab", "borrow") for command in fake.commands)
    await bridge.close()


@pytest.mark.asyncio
async def test_exit_one_refreshes_snapshot_and_retries_click_once() -> None:
    selector = TARGET_SELECTOR
    fake = FakeRunner(
        _happy_responses(
            click_results=[
                _json_result({"error": "stale private selector"}, returncode=1),
                _json_result({"ok": True}),
            ],
            snapshot_results=[_json_result({"ok": True}), _json_result({"ok": True})],
        )
    )
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    await bridge.click_marked_tab(Page(), selector=selector)

    assert sum(command[0] == "snapshot" for command in fake.commands) == 2
    assert sum(command[0] == "click" for command in fake.commands) == 2


@pytest.mark.asyncio
async def test_stale_click_is_not_replayed_when_policy_disables_retry() -> None:
    fake = FakeRunner(
        _happy_responses(
            click_results=[
                _json_result(
                    {"error": {"code": "stale-selector"}},
                    returncode=1,
                )
            ]
        )
    )
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(
            Page(),
            selector=TARGET_SELECTOR,
            retry_stale_selector=False,
        )

    assert captured.value.code == "bsk-click"
    assert sum(command[0] == "snapshot" for command in fake.commands) == 1
    assert sum(command[0] == "click" for command in fake.commands) == 1
    assert any(command[:2] == ("tab", "return") for command in fake.commands)


@pytest.mark.asyncio
async def test_generic_exit_one_click_failure_is_not_retried() -> None:
    fake = FakeRunner(
        _happy_responses(
            click_results=[
                _json_result({"error": {"code": "click-failed"}}, returncode=1)
            ]
        )
    )
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(Page(), selector=TARGET_SELECTOR)

    assert captured.value.code == "bsk-click"
    assert sum(command[0] == "click" for command in fake.commands) == 1
    assert sum(command[0] == "snapshot" for command in fake.commands) == 1
    await bridge.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("returncode", (2, 3, 4, 5))
async def test_non_stale_click_failure_returns_tab_without_retry(returncode: int) -> None:
    fake = FakeRunner(
        _happy_responses(
            click_results=[_json_result({"private": "details"}, returncode=returncode)]
        )
    )
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(
            Page(), selector=TARGET_SELECTOR
        )

    assert captured.value.code == "bsk-click"
    assert sum(command[0] == "click" for command in fake.commands) == 1
    assert any(command[:2] == ("tab", "return") for command in fake.commands)
    assert "private" not in str(captured.value)


@pytest.mark.asyncio
async def test_failed_snapshot_is_not_retried_or_followed_by_click() -> None:
    fake = FakeRunner(
        _happy_responses(
            snapshot_results=[
                _json_result({"error": "stale"}, returncode=1),
                _json_result({"ok": True}),
            ]
        )
    )
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(Page(), selector=TARGET_SELECTOR)

    assert captured.value.code == "bsk-snapshot"
    assert sum(command[0] == "snapshot" for command in fake.commands) == 1
    assert not any(command[0] == "click" for command in fake.commands)
    assert any(command[:2] == ("tab", "return") for command in fake.commands)


@pytest.mark.asyncio
async def test_bridge_rejects_arbitrary_selector_before_session_start() -> None:
    fake = FakeRunner(_happy_responses())
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(Page(), selector=".untrusted-selector")

    assert captured.value.code == "bsk-target-ambiguous"
    assert not any(command[:2] == ("session", "start") for command in fake.commands)


@pytest.mark.asyncio
async def test_borrow_rejects_malformed_json_response() -> None:
    responses = _happy_responses()
    responses[("tab", "borrow", "41", "--session", "abcd", "--json", "--quiet")] = CommandResult(
        0, b"not-json private", b""
    )
    fake = FakeRunner(responses)
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.click_marked_tab(Page(), selector=TARGET_SELECTOR)

    assert captured.value.code == "bsk-tab-borrow"
    assert "private" not in str(captured.value)
    assert not any(command[0] == "snapshot" for command in fake.commands)
    assert any(command[:2] == ("tab", "return") for command in fake.commands)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    (
        (TimeoutError("private timeout detail"), "bsk-timeout"),
        (CommandResult(0, b"not-json private", b""), "bsk-transport"),
        (CommandResult(0, b"{" + b"x" * MAX_COMMAND_OUTPUT, b""), "bsk-transport"),
    ),
)
async def test_preflight_redacts_timeout_malformed_and_oversized_output(
    response: object, expected: str
) -> None:
    fake = FakeRunner({("status", "--json", "--quiet"): response})

    with pytest.raises(BrowserSkillError) as captured:
        await BrowserSkillBridge(runner=fake).preflight()

    assert captured.value.code == expected
    assert str(captured.value) == expected


@pytest.mark.asyncio
async def test_close_stops_started_session_only_once() -> None:
    fake = FakeRunner(_happy_responses())
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()
    await bridge.click_marked_tab(
        Page(), selector=TARGET_SELECTOR
    )

    await bridge.close()
    await bridge.close()

    assert fake.commands.count(("session", "stop", "abcd", "--quiet")) == 1


@pytest.mark.asyncio
async def test_close_retries_a_failed_session_stop() -> None:
    stop_results = [
        CommandResult(1, b"", b"private stop failure"),
        CommandResult(0, b"", b""),
    ]

    def next_stop() -> CommandResult:
        return stop_results.pop(0)

    responses = _happy_responses()
    responses[("session", "stop", "abcd", "--quiet")] = next_stop
    fake = FakeRunner(responses)
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()
    await bridge.click_marked_tab(Page(), selector=TARGET_SELECTOR)

    with pytest.raises(BrowserSkillError) as captured:
        await bridge.close()
    await bridge.close()

    assert captured.value.code == "bsk-session-stop"
    assert fake.commands.count(("session", "stop", "abcd", "--quiet")) == 2


@pytest.mark.asyncio
async def test_close_after_malformed_start_never_stops_an_unproven_session() -> None:
    session_lists = [
        _json_result([]),
        _json_result(
            [
                {
                    "session_id": "wxyz",
                    "browser_instance_id": "8f024870",
                    "agent_window_id": 73,
                    "created_at_ms": 1,
                }
            ]
        ),
    ]
    def next_session_list() -> CommandResult:
        return session_lists.pop(0)

    responses = _happy_responses()
    responses[("session", "list", "--json", "--quiet")] = next_session_list
    responses[("session", "start", "--browser", "8f024870", "--json", "--quiet")] = CommandResult(
        0, b"not-json", b""
    )
    fake = FakeRunner(responses)
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(BrowserSkillError):
        await bridge.click_marked_tab(Page(), selector=TARGET_SELECTOR)
    await bridge.close()

    assert fake.commands.count(("session", "list", "--json", "--quiet")) == 1
    assert not any(command[:2] == ("session", "stop") for command in fake.commands)


@pytest.mark.asyncio
async def test_cancellation_still_returns_borrowed_tab() -> None:
    selector = TARGET_SELECTOR
    responses = _happy_responses()
    click = (
        "click",
        "--selector",
        selector,
        "--session",
        "abcd",
        "--tab-id",
        "41",
        "--timeout",
        "15s",
        "--json",
        "--quiet",
    )
    responses[click] = asyncio.CancelledError()
    fake = FakeRunner(responses)
    bridge = BrowserSkillBridge(runner=fake)
    await bridge.preflight()

    with pytest.raises(asyncio.CancelledError):
        await bridge.click_marked_tab(Page(), selector=selector)

    assert any(command[:2] == ("tab", "return") for command in fake.commands)
