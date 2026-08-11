from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from typing import Any, Protocol

from .browser import PreconditionError


BSK_CLI_VERSION = "0.1.10"
BSK_EXTENSION_VERSION = "0.1.6"
MAX_COMMAND_OUTPUT = 1_048_576

_COMMAND_TIMEOUT = 20.0
_SESSION_ID = re.compile(r"[a-z]{4}")
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9._-]{1,128}")
_TARGET_SELECTOR = re.compile(
    r'\[data-media-missher-target="[0-9a-f]{32}"\]'
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class Runner(Protocol):
    async def run(self, *arguments: str, timeout: float) -> CommandResult:
        raise NotImplementedError


class BrowserSkillError(PreconditionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _OutputTooLarge(RuntimeError):
    pass


def _positive_i64(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 < value <= 2**63 - 1
    )


def _json_object(result: CommandResult) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrowserSkillError("bsk-transport") from error
    if not isinstance(value, dict):
        raise BrowserSkillError("bsk-transport")
    return value


async def _read_limited(stream: Any) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > MAX_COMMAND_OUTPUT:
            raise _OutputTooLarge
        chunks.append(chunk)


async def _terminate_process(process: Any) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except (TimeoutError, ProcessLookupError):
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()


class SubprocessRunner:
    """Run the fixed local bsk executable without a shell or inherited text."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or shutil.which("bsk")

    async def run(self, *arguments: str, timeout: float) -> CommandResult:
        if self._executable is None:
            raise FileNotFoundError("bsk")
        process = await asyncio.create_subprocess_exec(
            self._executable,
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        tasks = (
            asyncio.create_task(process.wait()),
            asyncio.create_task(_read_limited(process.stdout)),
            asyncio.create_task(_read_limited(process.stderr)),
        )
        try:
            returncode, stdout, stderr = await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=timeout
            )
        except TimeoutError:
            await _terminate_process(process)
            raise
        except BaseException:
            await _terminate_process(process)
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return CommandResult(int(returncode), stdout, stderr)


class BrowserSkillBridge:
    def __init__(self, *, runner: Runner | None = None) -> None:
        self._runner = runner or SubprocessRunner()
        self._browser_id: str | None = None
        self._session_id: str | None = None

    async def _run(self, *arguments: str) -> CommandResult:
        try:
            result = await self._runner.run(*arguments, timeout=_COMMAND_TIMEOUT)
        except FileNotFoundError as error:
            raise BrowserSkillError("bsk-missing") from error
        except TimeoutError as error:
            raise BrowserSkillError("bsk-timeout") from error
        except BrowserSkillError:
            raise
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            raise BrowserSkillError("bsk-transport") from error
        if (
            not isinstance(result, CommandResult)
            or not isinstance(result.stdout, bytes)
            or not isinstance(result.stderr, bytes)
            or len(result.stdout) > MAX_COMMAND_OUTPUT
            or len(result.stderr) > MAX_COMMAND_OUTPUT
        ):
            raise BrowserSkillError("bsk-transport")
        return result

    async def _json(self, *arguments: str, failure_code: str = "bsk-transport") -> Any:
        result = await self._run(*arguments)
        if result.returncode != 0:
            raise BrowserSkillError(failure_code)
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BrowserSkillError("bsk-transport") from error

    async def preflight(self) -> None:
        status = await self._json(
            "status", "--json", "--quiet", failure_code="bsk-unhealthy"
        )
        if not isinstance(status, dict):
            raise BrowserSkillError("bsk-transport")
        browsers = status.get("browsers")
        if (
            not isinstance(browsers, list)
            or len(browsers) != 1
        ):
            raise BrowserSkillError("bsk-unhealthy")
        browser = browsers[0]
        if not isinstance(browser, dict):
            raise BrowserSkillError("bsk-unhealthy")
        if (
            status.get("protocol_version") != "1.0"
            or status.get("daemon_version") != BSK_CLI_VERSION
            or browser.get("extension_protocol_version") != "1.0"
            or browser.get("extension_version") != BSK_EXTENSION_VERSION
            or browser.get("version_skew") is not False
        ):
            raise BrowserSkillError("bsk-incompatible")
        browser_id = browser.get("instance_id")
        if not isinstance(browser_id, str) or _SAFE_IDENTIFIER.fullmatch(browser_id) is None:
            raise BrowserSkillError("bsk-unhealthy")
        status_sessions = status.get("sessions")
        skew_browsers = status.get("version_skew_browsers")
        if not isinstance(status_sessions, list) or not isinstance(skew_browsers, list):
            raise BrowserSkillError("bsk-transport")
        session_count = browser.get("session_count")
        if not isinstance(session_count, int) or isinstance(session_count, bool):
            raise BrowserSkillError("bsk-transport")
        if status_sessions or session_count:
            raise BrowserSkillError("bsk-busy")
        if skew_browsers:
            raise BrowserSkillError("bsk-incompatible")

        sessions = await self._json(
            "session", "list", "--json", "--quiet", failure_code="bsk-unhealthy"
        )
        if not isinstance(sessions, list):
            raise BrowserSkillError("bsk-transport")
        if sessions:
            raise BrowserSkillError("bsk-busy")
        self._browser_id = browser_id

    async def _start_session(self) -> str:
        if self._session_id is not None:
            return self._session_id
        if self._browser_id is None:
            raise BrowserSkillError("bsk-unhealthy")
        result = await self._run(
            "session",
            "start",
            "--browser",
            self._browser_id,
            "--json",
            "--quiet",
        )
        if result.returncode != 0:
            raise BrowserSkillError("bsk-transport")
        payload = _json_object(result)
        session_id = payload.get("session_id")
        agent_window_id = payload.get("agent_window_id")
        if (
            not isinstance(session_id, str)
            or _SESSION_ID.fullmatch(session_id) is None
            or payload.get("browser_instance_id") != self._browser_id
            or (
                agent_window_id is not None
                and not _positive_i64(agent_window_id)
            )
        ):
            raise BrowserSkillError("bsk-transport")
        self._session_id = session_id
        return self._session_id

    async def _snapshot(self, session_id: str, tab_id: str) -> CommandResult:
        command = (
            "snapshot",
            "--session",
            session_id,
            "--tab-id",
            tab_id,
            "--max-tokens",
            "4096",
            "--json",
            "--quiet",
        )
        result = await self._run(*command)
        if result.returncode == 1:
            result = await self._run(*command)
        if result.returncode != 0:
            raise BrowserSkillError("bsk-transport")
        _json_object(result)
        return result

    async def click_marked_tab(self, page: Any, *, selector: str) -> None:
        if not isinstance(selector, str) or _TARGET_SELECTOR.fullmatch(selector) is None:
            raise BrowserSkillError("bsk-target-ambiguous")
        marker = await page.title()
        if not isinstance(marker, str) or not marker.startswith("media-missher-"):
            raise BrowserSkillError("bsk-target-ambiguous")
        session_id = await self._start_session()
        tab_payload = await self._json(
            "tab",
            "list",
            "--session",
            session_id,
            "--scope",
            "user",
            "--json",
            "--quiet",
        )
        tabs = tab_payload.get("tabs") if isinstance(tab_payload, dict) else None
        if not isinstance(tabs, list):
            raise BrowserSkillError("bsk-transport")
        matches = [
            tab
            for tab in tabs
            if isinstance(tab, dict) and tab.get("title") == marker
        ]
        if len(matches) != 1:
            raise BrowserSkillError("bsk-target-ambiguous")
        raw_tab_id = matches[0].get("tab_id")
        if not _positive_i64(raw_tab_id):
            raise BrowserSkillError("bsk-target-ambiguous")
        tab_id = str(raw_tab_id)

        borrow = await self._run(
            "tab",
            "borrow",
            tab_id,
            "--session",
            session_id,
            "--json",
            "--quiet",
        )
        if borrow.returncode != 0:
            raise BrowserSkillError("bsk-transport")
        primary_error: BaseException | None = None
        try:
            _json_object(borrow)
            await self._snapshot(session_id, tab_id)
            click_command = (
                "click",
                "--selector",
                selector,
                "--session",
                session_id,
                "--tab-id",
                tab_id,
                "--timeout",
                "15s",
                "--json",
                "--quiet",
            )
            click = await self._run(*click_command)
            if click.returncode == 1:
                await self._snapshot(session_id, tab_id)
                click = await self._run(*click_command)
            if click.returncode != 0:
                raise BrowserSkillError("bsk-transport")
            _json_object(click)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                returned = await self._run(
                    "tab",
                    "return",
                    tab_id,
                    "--session",
                    session_id,
                    "--json",
                    "--quiet",
                )
                if returned.returncode != 0:
                    raise BrowserSkillError("bsk-transport")
                _json_object(returned)
            except BaseException:
                if primary_error is None:
                    raise

    async def close(self) -> None:
        session_id = self._session_id
        if session_id is None:
            return
        result = await self._run("session", "stop", session_id, "--quiet")
        if result.returncode != 0:
            raise BrowserSkillError("bsk-transport")
        self._session_id = None


__all__ = [
    "BSK_CLI_VERSION",
    "BSK_EXTENSION_VERSION",
    "MAX_COMMAND_OUTPUT",
    "BrowserSkillBridge",
    "BrowserSkillError",
    "CommandResult",
    "Runner",
    "SubprocessRunner",
]
