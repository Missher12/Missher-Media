from __future__ import annotations

import argparse
import asyncio
import math
import secrets
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .browser import BrowserRiskError, BrowserSession, PreconditionError
from .browser_skill import BrowserSkillError
from .models import CollectionRequest
from .platforms import bilibili, douyin, weibo, xhs
from .storage import RunStore


PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
_SAFE_BROWSER_SKILL_CODES = frozenset(
    {
        "bsk-missing",
        "bsk-unhealthy",
        "bsk-incompatible",
        "bsk-busy",
        "bsk-transport",
        "bsk-timeout",
        "bsk-target-ambiguous",
    }
)

_COLLECTORS = {
    "bilibili": (bilibili.collect_creator, bilibili.search),
    "xhs": (xhs.collect_creator, xhs.search),
    "douyin": (douyin.collect_creator, douyin.search),
    "weibo": (weibo.collect_creator, weibo.search),
}
_PLATFORM_STOPS = (
    bilibili.CollectionStopped,
    xhs.CollectionStopped,
    douyin.CollectionStopped,
    weibo.CollectionStopped,
)
_SOURCE_RESPONSE_ERRORS = (
    bilibili.SourceResponseError,
    xhs.SourceResponseError,
    douyin.SourceResponseError,
    weibo.SourceResponseError,
)
_SAFE_RISK_CODES = frozenset(
    {
        "http-403",
        "http-429",
        "payload-461",
        "payload-471",
        "payload-999",
    }
)
_CHALLENGE_REASONS = frozenset(
    {
        "captcha",
        "challenge",
        "challenge-selector",
        "请完成验证",
        "访问受限",
        "请求过于频繁",
        "账号异常",
        "风控",
        "安全验证",
        "验证码",
    }
)


def _safe_risk_code(value: object) -> str:
    reason = value if isinstance(value, str) else ""
    normalized = reason.strip().casefold()
    if normalized in _SAFE_RISK_CODES:
        return normalized
    if normalized in _CHALLENGE_REASONS:
        return "challenge"
    return "risk-signal"


class RiskStop(RuntimeError):
    """Signal that no later platform may be run in this invocation."""

    def __init__(self, reason: object = None) -> None:
        self.code = _safe_risk_code(reason)
        super().__init__(self.code)


class CollectorContractError(RuntimeError):
    """Signal that a collector returned a value outside the runtime contract."""


class PlatformPreflightError(RuntimeError):
    """A platform page failed the private controller preflight."""

    def __init__(self, platform: str, cause: PreconditionError) -> None:
        if platform not in PLATFORMS or not isinstance(cause, PreconditionError):
            raise ValueError("invalid platform preflight failure")
        self.platform = platform
        self.cause = cause
        self.code = (
            cause.code
            if isinstance(cause, BrowserSkillError)
            and cause.code in _SAFE_BROWSER_SKILL_CODES
            else "precondition-failed"
        )
        super().__init__("platform preflight failed")


class PlatformRiskPreflightError(RuntimeError):
    """A platform page exposed a safe non-retryable risk signal in preflight."""

    def __init__(self, platform: str, code: str) -> None:
        if platform not in PLATFORMS or code not in {
            "http-403",
            "http-429",
            "challenge",
        }:
            raise ValueError("invalid platform risk preflight failure")
        self.platform = platform
        self.code = code
        super().__init__("platform risk preflight failed")


class RuntimeDispatcher:
    """Own one connection to the user's existing browser for a serial run."""

    def __init__(
        self,
        cdp_url: str,
        *,
        allow_navigation: bool = False,
        browser_assist: str = "off",
    ) -> None:
        self.cdp_url = cdp_url
        self.allow_navigation = allow_navigation
        self.browser_assist = browser_assist
        self.browser: BrowserSession | None = None

    async def __aenter__(self) -> "RuntimeDispatcher":
        self.browser = await BrowserSession.connect(
            self.cdp_url,
            allow_navigation=self.allow_navigation,
            browser_assist=self.browser_assist,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.browser is not None:
            try:
                await self.browser.close()
            except BaseException:
                if not exc or exc[0] is None:
                    raise

    async def preflight(self, requests: Sequence[CollectionRequest]) -> None:
        if self.browser is None:
            raise RuntimeError("browser dispatcher is not connected")
        assist_preflight = getattr(self.browser, "preflight_browser_assist", None)
        if assist_preflight is not None:
            try:
                await assist_preflight()
            except PreconditionError as error:
                platform = requests[0].platform if requests else PLATFORMS[0]
                raise PlatformPreflightError(platform, error) from error
        for platform in dict.fromkeys(request.platform for request in requests):
            try:
                await self.browser.require_authenticated_page(platform)
            except BrowserRiskError as error:
                raise PlatformRiskPreflightError(platform, error.code) from error
            except PreconditionError as error:
                raise PlatformPreflightError(platform, error) from error

    async def collect(self, request: CollectionRequest) -> list[dict[str, Any]]:
        if self.browser is None:
            raise RuntimeError("browser dispatcher is not connected")
        creator, search = _COLLECTORS[request.platform]
        operation = creator if request.uid is not None else search
        try:
            return await operation(request, self.browser)
        except _PLATFORM_STOPS as exc:
            reason = exc.args[0] if len(exc.args) == 1 else None
            raise RiskStop(reason) from exc

    def bind_store(self, store: RunStore) -> None:
        if self.browser is None:
            raise RuntimeError("browser dispatcher is not connected")
        bind_store = getattr(self.browser, "bind_store", None)
        if bind_store is not None:
            bind_store(store)


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL, help="Existing Chrome CDP endpoint")
    parser.add_argument(
        "--allow-navigation",
        action="store_true",
        help="Explicitly authorize exact-host browser navigation for this run",
    )
    parser.add_argument(
        "--browser-assist",
        choices=("off", "browserskill"),
        default="off",
    )
    parser.add_argument(
        "--screenshot-mode",
        choices=("off", "opened", "all"),
        default="off",
    )
    parser.add_argument("--output-dir", "--output", dest="output_dir", type=Path, required=True, help="Private JSON output root")
    parser.add_argument("--format", choices=("json",), default="json", help="Runtime staging format (JSON only)")
    parser.add_argument("--no-feishu", action="store_true", help="Compatibility option; remote writes are always disabled")


def build_parser(*, fixed_platform: str | None = None) -> argparse.ArgumentParser:
    if fixed_platform is not None and fixed_platform not in PLATFORMS:
        raise ValueError("unsupported fixed platform")
    parser = argparse.ArgumentParser(description="Collect four-platform media into private JSON output.")
    commands = parser.add_subparsers(dest="mode", required=True)

    creator = commands.add_parser("creator", help="Collect creator records")
    if fixed_platform is None:
        creator.add_argument("--platforms", "--platform", dest="platforms", required=True, help="Comma-separated platform list")
    else:
        creator.set_defaults(platforms=fixed_platform)
        creator.add_argument("--uid", dest=f"{fixed_platform}_uid")
    creator.add_argument("--count", "--max", dest="count", type=_non_negative_int, default=15)
    for platform in PLATFORMS:
        creator.add_argument(f"--{platform}-count", type=_non_negative_int)
        creator.add_argument(f"--{platform}-uid")
    creator.add_argument("--complete", action="store_true")
    creator.add_argument("--bilibili-complete", action="store_true")
    creator.add_argument("--xhs-complete", action="store_true")
    creator.add_argument("--xhs-comments", "--comments", dest="xhs_comments", type=_non_negative_int, default=0)
    creator.add_argument("--platform-timeout", type=_non_negative_float, default=300.0)
    _add_output_options(creator)

    search = commands.add_parser("search", help="Search one platform")
    if fixed_platform is None:
        search.add_argument("--platform", choices=PLATFORMS, required=True)
    else:
        search.set_defaults(platform=fixed_platform)
    search.add_argument("--keyword", required=True)
    search.add_argument("--count", "--max", dest="count", type=_non_negative_int, default=15)
    search.add_argument("--uid", help=argparse.SUPPRESS)
    search.add_argument("--comments", type=_non_negative_int, default=0, help=argparse.SUPPRESS)
    search.add_argument("--platform-timeout", type=_non_negative_float, default=300.0, help=argparse.SUPPRESS)
    _add_output_options(search)
    return parser


def _normalize_legacy_argv(argv: Sequence[str]) -> list[str]:
    values = list(argv)
    if not values or values[0] in {"creator", "search", "-h", "--help"}:
        return values
    if "--search" not in values:
        return ["creator", *values]
    index = values.index("--search")
    if index + 1 >= len(values):
        return ["search", *values]
    keyword = values[index + 1]
    del values[index:index + 2]
    return ["search", "--keyword", keyword, *values]


def _selected_platforms(parser: argparse.ArgumentParser, value: str) -> tuple[str, ...]:
    selected = tuple(item.strip().casefold() for item in value.split(",") if item.strip())
    if not selected:
        parser.error("at least one platform is required")
    unknown = [item for item in selected if item not in PLATFORMS]
    if unknown:
        parser.error(f"unknown platform: {unknown[0]}")
    if len(set(selected)) != len(selected):
        parser.error("duplicate platforms are not allowed")
    return selected


def _requests_from_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> list[CollectionRequest]:
    if args.mode == "search":
        keyword = args.keyword.strip()
        if not keyword:
            parser.error("keyword must not be empty")
        platforms = (args.platform,)
        assisted = args.browser_assist != "off" or args.screenshot_mode != "off"
        if assisted and not args.allow_navigation:
            parser.error("browser assist and screenshots require --allow-navigation")
        if assisted and any(platform not in {"bilibili", "xhs"} for platform in platforms):
            parser.error("browser assist and screenshots support only bilibili and xhs")
        if assisted and args.platform == "bilibili":
            parser.error("Bilibili search advanced modes are not supported")
        if args.screenshot_mode == "all" and args.count == 0:
            parser.error("screenshot mode all requires a positive count")
        return [
            CollectionRequest(
                platform=args.platform,
                count=args.count,
                keyword=keyword,
                browser_assist=args.browser_assist,
                screenshot_mode=args.screenshot_mode,
            )
        ]

    platforms = _selected_platforms(parser, args.platforms)
    assisted = args.browser_assist != "off" or args.screenshot_mode != "off"
    if assisted and not args.allow_navigation:
        parser.error("browser assist and screenshots require --allow-navigation")
    if assisted and any(platform not in {"bilibili", "xhs"} for platform in platforms):
        parser.error("browser assist and screenshots support only bilibili and xhs")
    effective_counts = {
        platform: (
            args.count
            if getattr(args, f"{platform}_count") is None
            else getattr(args, f"{platform}_count")
        )
        for platform in platforms
    }
    if args.screenshot_mode == "all" and any(
        count == 0 for count in effective_counts.values()
    ):
        parser.error("screenshot mode all requires a positive count")
    requests: list[CollectionRequest] = []
    for platform in platforms:
        uid = getattr(args, f"{platform}_uid")
        if uid is None or not uid.strip():
            parser.error(f"--{platform}-uid is required for creator collection")
        count = effective_counts[platform]
        complete = bool(
            (args.complete and platform in {"bilibili", "xhs"})
            or (platform == "bilibili" and args.bilibili_complete)
            or (platform == "xhs" and args.xhs_complete)
        )
        requests.append(
            CollectionRequest(
                platform=platform,
                count=count,
                uid=uid.strip(),
                complete=complete,
                comment_limit=args.xhs_comments if platform == "xhs" else 0,
                browser_assist=args.browser_assist,
                screenshot_mode=args.screenshot_mode,
            )
        )
    return requests


def _create_store(output_dir: Path) -> RunStore:
    root = output_dir.expanduser().resolve()
    existed = root.exists()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not existed:
        root.chmod(0o700)
    run_id = f"{time.time_ns()}-{secrets.token_hex(4)}"
    return RunStore.create(root, run_id)


def _has_screenshot_shortfall(
    request: CollectionRequest,
    records: Sequence[dict[str, Any]],
) -> bool:
    for record in records:
        status = record.get("screenshot_status")
        if status == "failed":
            return True
        required = request.screenshot_mode == "all" or (
            request.screenshot_mode == "opened"
            and record.get("detail_attempted") is True
        )
        if required and status not in {"complete", "failed"}:
            return True
    return False


def _result_status(request: CollectionRequest, records: Sequence[dict[str, Any]]) -> str:
    if request.count > 0 and len(records) < request.count:
        return "shortfall"
    if _has_screenshot_shortfall(request, records):
        return "incomplete"
    if request.complete and any(record.get("complete") is not True for record in records):
        return "incomplete"
    return "complete"


def _write_xhs_artifacts(
    store: RunStore,
    records: Sequence[dict[str, Any]],
    *,
    status: str,
    started_at: str,
    reason: str | None = None,
) -> dict[str, str]:
    finished_at = datetime.now(UTC).isoformat()
    report = xhs.build_run_report(
        status, records, started_at, finished_at, reason=reason
    )
    checkpoint = xhs.build_checkpoint(records)
    report_path = store.write_json("xhs_report.json", report)
    checkpoint_path = store.write_json("xhs_checkpoint.json", checkpoint)
    return {"xhs_report": report_path.name, "xhs_checkpoint": checkpoint_path.name}


def _result_diagnostic(
    request: CollectionRequest,
    status: str,
    records: Sequence[dict[str, Any]] = (),
) -> dict[str, str]:
    if status == "complete":
        return {"kind": "ok", "code": "ok"}
    if status == "shortfall":
        return {"kind": "result", "code": "count-shortfall"}
    if _has_screenshot_shortfall(request, records):
        return {"kind": "result", "code": "screenshot-shortfall"}
    return {"kind": "result", "code": "incomplete-record"}


def _failure_diagnostic(error: BaseException) -> dict[str, str]:
    if isinstance(error, ModuleNotFoundError):
        return {"kind": "dependency", "code": "module-not-found"}
    if (
        isinstance(error, BrowserSkillError)
        and error.code in _SAFE_BROWSER_SKILL_CODES
    ):
        return {"kind": "precondition", "code": error.code}
    if isinstance(error, PreconditionError):
        return {"kind": "precondition", "code": "precondition-failed"}
    if isinstance(error, _SOURCE_RESPONSE_ERRORS):
        return {"kind": "source-response", "code": "source-response-failed"}
    if isinstance(error, xhs.CaptureTimeout):
        return {"kind": "timeout", "code": error.code}
    if isinstance(error, TimeoutError):
        return {"kind": "timeout", "code": "platform-timeout"}
    if isinstance(error, CollectorContractError):
        return {"kind": "collector-contract", "code": "invalid-records"}
    return {"kind": "internal", "code": "unexpected"}


async def _run_requests(
    requests: Sequence[CollectionRequest],
    *,
    output_dir: Path,
    dispatcher: Any,
    platform_timeout: float,
    enforce_timeout: bool = True,
) -> int:
    selected = [request.platform for request in requests]
    statuses = {platform: "not-run" for platform in selected}
    counts = {platform: 0 for platform in selected}
    paths: dict[str, str] = {}
    diagnostics = {
        platform: {"kind": "not-run", "code": "preflight-aborted"}
        for platform in selected
    }

    async with dispatcher:
        preflight = getattr(dispatcher, "preflight", None)
        if preflight is not None:
            await preflight(requests)
        store = _create_store(output_dir)
        bind_store = getattr(dispatcher, "bind_store", None)
        if bind_store is not None:
            bind_store(store)
        risk_stopped = False
        failed = False
        for request in requests:
            platform = request.platform
            started_at = datetime.now(UTC).isoformat()
            try:
                operation = dispatcher.collect(request)
                records = (
                    await asyncio.wait_for(operation, timeout=platform_timeout)
                    if enforce_timeout and platform_timeout > 0
                    else await operation
                )
                if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
                    raise CollectorContractError
                path = store.write_json(f"{platform}.json", records)
                counts[platform] = len(records)
                paths[platform] = path.name
                statuses[platform] = _result_status(request, records)
                diagnostics[platform] = _result_diagnostic(
                    request, statuses[platform], records
                )
                if platform == "xhs":
                    paths.update(_write_xhs_artifacts(store, records, status=statuses[platform], started_at=started_at))
                if statuses[platform] != "complete":
                    failed = True
            except RiskStop as error:
                statuses[platform] = "risk-stopped"
                diagnostics[platform] = {
                    "kind": "risk-stop",
                    "code": error.code,
                }
                if platform == "xhs":
                    paths.update(
                        _write_xhs_artifacts(
                            store,
                            [],
                            status="risk-stopped",
                            started_at=started_at,
                            reason=error.code,
                        )
                    )
                risk_stopped = True
                break
            except Exception as error:
                statuses[platform] = "failed"
                diagnostic = _failure_diagnostic(error)
                diagnostics[platform] = diagnostic
                if platform == "xhs":
                    try:
                        paths.update(
                            _write_xhs_artifacts(
                                store,
                                [],
                                status="failed",
                                started_at=started_at,
                                reason=diagnostic["code"],
                            )
                        )
                    except Exception:
                        pass
                failed = True

        if risk_stopped:
            for platform, status in statuses.items():
                if status == "not-run":
                    diagnostics[platform] = {
                        "kind": "not-run",
                        "code": "prior-risk-stop",
                    }
        overall = "risk-stopped" if risk_stopped else "failed" if failed else "complete"
        store.write_manifest(
            counts=counts,
            paths=paths,
            platforms=statuses,
            status=overall,
            diagnostics=diagnostics,
        )
    return 75 if risk_stopped else 1 if failed else 0


def _run_immediate(coroutine: Any) -> int:
    """Drive a non-suspending injected dispatcher without opening any sockets."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return int(completed.value)
    coroutine.close()
    raise RuntimeError("injected dispatcher unexpectedly suspended")


def main(argv: Sequence[str] | None = None, *, fixed_platform: str | None = None, dispatcher: Any = None) -> int:
    values = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser(fixed_platform=fixed_platform)
    args = parser.parse_args(_normalize_legacy_argv(values))
    requests = _requests_from_args(parser, args)
    injected = dispatcher is not None
    active_dispatcher = (
        dispatcher
        if injected
        else RuntimeDispatcher(
            args.cdp_url,
            allow_navigation=args.allow_navigation,
            browser_assist=args.browser_assist,
        )
    )
    try:
        operation = _run_requests(
            requests,
            output_dir=args.output_dir,
            dispatcher=active_dispatcher,
            platform_timeout=args.platform_timeout,
            enforce_timeout=not injected,
        )
        return _run_immediate(operation) if injected else asyncio.run(operation)
    except PlatformPreflightError as error:
        print(
            "media-missher-diagnostic "
            f"platform={error.platform} "
            f"kind=precondition code={error.code}",
            file=sys.stderr,
        )
        return 78
    except PlatformRiskPreflightError as error:
        print(
            "media-missher-diagnostic "
            f"platform={error.platform} "
            f"kind=risk-stop code={error.code}",
            file=sys.stderr,
        )
        return 75
    except Exception as exc:
        print(f"runtime failed: {type(exc).__name__}", file=sys.stderr)
        return 1


__all__ = [
    "DEFAULT_CDP_URL",
    "PLATFORMS",
    "PlatformPreflightError",
    "PlatformRiskPreflightError",
    "RiskStop",
    "RuntimeDispatcher",
    "build_parser",
    "main",
]
