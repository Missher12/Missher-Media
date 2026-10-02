"""The Media@Missher collection CLI.

Two execution paths share one validation and safety front end:

* the **legacy path** runs the four existing per-platform collectors through
  :class:`RuntimeDispatcher`, unchanged in observable behaviour;
* the **plan path** runs a versioned multi-target
  :class:`~media_missher_runtime.contracts.CollectionPlan` through
  :class:`~media_missher_runtime.plan_runner.PlanRunner` (``--targets-json``),
  which is also how a Weibo topic task (``--topic``) and an X target are
  expressed.

Backend selection is frozen per run: this run's ``--backend`` first, then the
saved profile preference, then ``cdp``. ``auto`` never exists, and the
deprecated ``--browser-assist browserskill`` bridge is refused with a fixed
diagnostic instead of being remapped onto the browser-skill backend.

Every refusal that is a *precondition* prints exactly one bounded line::

    media-missher-diagnostic platform=<p> kind=precondition code=<fixed-code>

and returns 78; a platform risk signal returns 75. No diagnostic ever contains a
URL, a target identifier, a page title or any other private text, and no failure
path prints a traceback.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
import math
import os
import re
import secrets
import signal
import stat
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backends import (
    PreconditionLikeError,
    backend_for,
    ensure_supported,
)
from .browser import BrowserRiskError, BrowserSession, PreconditionError
from .capabilities import CapabilityError
from .continuation import apply_exclusions
from .contracts import (
    BACKEND_CDP,
    COUNT_MODE_FIXED,
    COUNT_MODES,
    DEFAULT_BACKEND,
    PLATFORMS as CONTRACT_PLATFORMS,
    TASK_MODE_CREATOR,
    TASK_MODE_SEARCH,
    TASK_MODE_TOPIC,
    CollectionPlan,
    ContractError,
    Target,
    normalize_backend,
)
from .models import CollectionRequest
from .plan_runner import PlanRunner, TaskOutcome
from .platforms import bilibili, douyin, weibo, weibo_topic, x, xhs
from .storage import RunStore
from .xhs_policy import SafetyBlocked, SharedXhsSafetyGate, XhsSafetyGate
from .shared_safety import SharedSafetyError, collection_lease, runtime_home


PLATFORMS = CONTRACT_PLATFORMS
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
        "bsk-session-start",
        "bsk-tab-list",
        "bsk-tab-borrow",
        "bsk-snapshot",
        "bsk-click",
        "bsk-tab-return",
        "bsk-session-stop",
    }
)
#: Diagnostic codes are structurally bounded: lowercase alphanumerics plus
#: ``._-``, at most 64 characters. A code can therefore never carry a URL, a
#: target identifier or any other private text into stderr.
_SAFE_CODE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_TOPIC_CODES = frozenset(
    {
        "topic-container-invalid",
        "topic-container-unsupported",
        "topic-host-unsupported",
        "topic-input-empty",
        "topic-name-empty",
        "topic-path-unsupported",
        "topic-query-invalid",
    }
)
TopicError = weibo_topic.TopicError
_MAX_PLAN_BYTES = 2 * 1024 * 1024
_MAX_CHECKPOINT_RECORDS = 10_000

_COLLECTORS = {
    "bilibili": (bilibili.collect_creator, bilibili.search),
    "xhs": (xhs.collect_creator, xhs.search),
    "douyin": (douyin.collect_creator, douyin.search),
    "weibo": (weibo.collect_creator, weibo.search),
    "x": (x.collect_creator, x.collect_search),
}
_PLATFORM_STOPS = (
    bilibili.CollectionStopped,
    xhs.CollectionStopped,
    douyin.CollectionStopped,
    weibo.CollectionStopped,
    weibo_topic.CollectionStopped,
    x.CollectionStopped,
)
_SOURCE_RESPONSE_ERRORS = (
    bilibili.SourceResponseError,
    xhs.SourceResponseError,
    douyin.SourceResponseError,
    weibo.SourceResponseError,
    weibo_topic.SourceResponseError,
    x.SourceResponseError,
)
_CREATOR_CAPTURE_TIMEOUTS = (
    bilibili.CaptureTimeout,
    douyin.CaptureTimeout,
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


def _safe_code(code: object) -> str:
    """Bound a diagnostic code so no caller can smuggle text into stderr."""

    if isinstance(code, str) and _SAFE_CODE_RE.fullmatch(code):
        return code
    return "unexpected"


def _diagnostic(
    platform: object,
    kind: str,
    code: object,
    *,
    returncode: int | None = None,
) -> int:
    """Print one fixed, model-safe diagnostic line and return its exit code."""

    resolved = platform if isinstance(platform, str) and platform in PLATFORMS else "unknown"
    if kind not in {"precondition", "risk-stop", "not-run"}:
        kind = "precondition"
    safe = _safe_code(code)
    print(
        f"media-missher-diagnostic platform={resolved} kind={kind} code={safe}",
        file=sys.stderr,
    )
    if returncode is not None:
        return returncode
    return 75 if kind == "risk-stop" else 78


class RiskStop(RuntimeError):
    """Signal that no later platform may be run in this invocation."""

    def __init__(self, reason: object = None) -> None:
        self.code = _safe_risk_code(reason)
        super().__init__(self.code)


class CollectorContractError(RuntimeError):
    """Signal that a collector returned a value outside the runtime contract."""


class _Precondition(PreconditionLikeError):
    """Internal carrier for a fixed precondition code."""

    def __init__(self, code: str) -> None:
        super().__init__(_safe_code(code))


class PlatformPreflightError(RuntimeError):
    """A platform page failed the private controller preflight."""

    def __init__(self, platform: str, cause: PreconditionError) -> None:
        if platform not in PLATFORMS or not isinstance(cause, PreconditionError):
            raise ValueError("invalid platform preflight failure")
        self.platform = platform
        self.cause = cause
        self.code = "precondition-failed"
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
        self._partial_records: dict[str, list[dict[str, Any]]] = {}
        self._progress_sink: Any = None
        self._preflight_reservations: set[str] = set()
        from .collection_pacing import CollectionPacing
        self.pacing = CollectionPacing()

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
        platforms = tuple(dict.fromkeys(request.platform for request in requests))
        # Check every selected platform before the first entry-page navigation.
        # New invocations refuse cooldowns immediately; only an already-running
        # bounded plan waits between its batches/targets.
        for platform in platforms:
            if platform != "xhs" and self.pacing.remaining(platform):
                raise SharedSafetyError("platform-cooldown")
        for platform in platforms:
            try:
                if platform != "xhs":
                    self.pacing.reserve(platform)
                    self._preflight_reservations.add(platform)
                await self.browser.require_authenticated_page(platform)
            except BrowserRiskError as error:
                raise PlatformRiskPreflightError(platform, error.code) from error
            except PreconditionError as error:
                raise PlatformPreflightError(platform, error) from error

    async def collect(self, request: CollectionRequest) -> list[dict[str, Any]]:
        if self.browser is None:
            raise RuntimeError("browser dispatcher is not connected")
        self._partial_records[request.platform] = []
        self.browser.last_pages = 0
        self.browser.last_exhausted = False
        self.browser.last_stop_reason = None
        try:
            if request.platform != "xhs":
                if request.platform in self._preflight_reservations:
                    self._preflight_reservations.remove(request.platform)
                    self.pacing.mark_started(request.platform)
                else:
                    await self.pacing.wait_and_reserve(request.platform)
            # Legacy CLI and plan invocations share the same finite batch cap.
            from dataclasses import replace
            from .batch_policy import DEFAULT_POLICIES
            policy = DEFAULT_POLICIES[request.platform]
            request = replace(request,
                batch_limit=min(request.target_count or policy.batch_records, policy.batch_records),
                page_cap=min(request.page_cap or policy.batch_pages, policy.batch_pages))
            return await _collect_with(request, self.browser)
        finally:
            self.last_pages = self.browser.last_pages
            self.last_exhausted = self.browser.last_exhausted
            self.last_stop_reason = self.browser.last_stop_reason

    def bind_store(self, store: RunStore) -> None:
        if self.browser is None:
            raise RuntimeError("browser dispatcher is not connected")
        bind_store = getattr(self.browser, "bind_store", None)
        if bind_store is not None:
            bind_store(store)
        bind_progress = getattr(self.browser, "bind_progress", None)
        if bind_progress is not None:
            bind_progress(self._capture_progress)

    def _capture_progress(
        self, platform: str, records: Sequence[dict[str, Any]]
    ) -> None:
        if platform not in PLATFORMS:
            return
        if not isinstance(records, (list, tuple)) or not all(
            isinstance(record, dict) for record in records
        ):
            return
        self._partial_records[platform] = [dict(record) for record in records]
        if self._progress_sink is not None:
            self._progress_sink(platform, self._partial_records[platform])

    def bind_progress(self, sink: Any) -> None:
        self._progress_sink = sink

    def partial_records(self, platform: str) -> list[dict[str, Any]]:
        return [dict(record) for record in self._partial_records.get(platform, ())]


async def _collect_with(
    request: CollectionRequest, browser: Any
) -> list[dict[str, Any]]:
    """Run the frozen collector for one request through one browser owner."""

    try:
        if request.topic is not None:
            return await weibo_topic.collect_topic(request, browser)
        creator, search = _COLLECTORS[request.platform]
        operation = creator if request.uid is not None else search
        return await operation(request, browser)
    except _PLATFORM_STOPS as exc:
        reason = exc.args[0] if len(exc.args) == 1 else None
        raise RiskStop(reason) from exc


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_int(value: str) -> int:
    parsed = _non_negative_int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = _non_negative_float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
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
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--backend",
        default=None,
        help="Chrome CDP only; retired backend requests are refused",
    )
    parser.add_argument(
        "--count-mode",
        choices=COUNT_MODES,
        default=None,
        help="fixed (default) stops at the requested count; best_effort runs bounded batches",
    )
    parser.add_argument(
        "--run-deadline",
        type=_positive_float,
        default=None,
        help="Total wall-clock budget in seconds for a plan or best_effort run",
    )
    parser.add_argument("--batch-pages", type=_positive_int, default=None)
    parser.add_argument("--batch-interval", type=_non_negative_float, default=None)
    parser.add_argument("--per-target-budget", type=_positive_int, default=None)
    parser.add_argument(
        "--screenshot-mode",
        choices=("off", "opened", "all"),
        default=None,
    )
    parser.add_argument("--output-dir", "--output", dest="output_dir", type=Path, required=True, help="Private JSON output root")
    parser.add_argument("--format", choices=("json",), default="json", help="Runtime staging format (JSON only)")
    parser.add_argument("--no-feishu", action="store_true", help="Compatibility option; remote writes are always disabled")
    parser.add_argument("--exclude-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--resume-run", help="Continue one exact non-risk plan run without changing its evidence")
    parser.add_argument("--profile-digest", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--targets-json",
        type=Path,
        default=None,
        help="Private 0600 plan file with a multi-target collection plan",
    )


def build_parser(*, fixed_platform: str | None = None) -> argparse.ArgumentParser:
    if fixed_platform is not None and fixed_platform not in PLATFORMS:
        raise ValueError("unsupported fixed platform")
    parser = argparse.ArgumentParser(description="Collect media records into private JSON output.")
    commands = parser.add_subparsers(dest="mode", required=True)

    creator = commands.add_parser("creator", help="Collect creator records")
    if fixed_platform is None:
        creator.add_argument("--platforms", "--platform", dest="platforms", help="Comma-separated platform list")
    else:
        creator.set_defaults(platforms=fixed_platform)
        creator.add_argument("--uid", dest=f"{fixed_platform}_uid")
    creator.add_argument("--count", "--max", dest="count", type=_non_negative_int, default=None)
    for platform in PLATFORMS:
        creator.add_argument(f"--{platform}-count", type=_non_negative_int)
        creator.add_argument(f"--{platform}-uid")
    creator.add_argument("--topic", help="Weibo topic name or official topic URL")
    creator.add_argument("--complete", action="store_true")
    creator.add_argument("--bilibili-complete", action="store_true")
    creator.add_argument("--xhs-complete", action="store_true")
    creator.add_argument("--xhs-comments", "--comments", dest="xhs_comments", type=_non_negative_int, default=None)
    creator.add_argument("--platform-timeout", type=_non_negative_float, default=300.0)
    _add_output_options(creator)

    search = commands.add_parser("search", help="Search one platform")
    if fixed_platform is None:
        search.add_argument("--platform", choices=PLATFORMS, required=True)
    else:
        search.set_defaults(platform=fixed_platform)
    search.add_argument("--keyword", default=None)
    search.add_argument("--topic", default=None, help="Weibo topic name or official topic URL")
    search.add_argument("--count", "--max", dest="count", type=_non_negative_int, default=None)
    search.add_argument("--uid", help=argparse.SUPPRESS)
    search.add_argument("--comments", type=_non_negative_int, default=None, help=argparse.SUPPRESS)
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


def _selected_platforms(parser: argparse.ArgumentParser, value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        parser.error("at least one platform is required")
    selected = tuple(item.strip().casefold() for item in value.split(",") if item.strip())
    if not selected:
        parser.error("at least one platform is required")
    unknown = [item for item in selected if item not in PLATFORMS]
    if unknown:
        parser.error(f"unknown platform: {unknown[0]}")
    if len(set(selected)) != len(selected):
        parser.error("duplicate platforms are not allowed")
    return selected


def _requested_platforms(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[str, ...]:
    """The platforms this invocation names, without opening anything."""

    if args.mode == "search":
        return (args.platform,)
    if args.platforms is None:
        if getattr(args, "topic", None) is not None:
            return ("weibo",)
        if getattr(args, "targets_json", None) is not None:
            return ()
        parser.error("at least one platform is required")
    return _selected_platforms(parser, args.platforms)


def _platform_preference() -> str | None:
    """The saved profile backend preference, if it can be read safely."""

    raw = os.environ.get("MEDIA_MISSHER_PROFILE_CONFIG")
    if not raw:
        return None
    try:
        if os.stat(raw).st_size > _MAX_PLAN_BYTES:
            return None
        with open(raw, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    preferred = value.get("backend")
    return preferred if isinstance(preferred, str) else None


def _resolve_backend(args: argparse.Namespace) -> str:
    """This run's explicit backend > profile preference > ``cdp``."""

    try:
        return backend_for(args, _platform_preference())
    except ValueError as error:
        message = str(error)
        raise _Precondition(
            "backend-auto-unsupported"
            if message == "automatic backend switching is not supported"
            else message if message in {"backend-retired-browserskill", "backend-retired-computer-use"} else "backend-invalid"
        ) from error


def _request_kwargs(args: argparse.Namespace, backend: str) -> dict[str, Any]:
    return {
        "backend": backend,
        "count_mode": args.count_mode or COUNT_MODE_FIXED,
        "best_effort_budget": args.per_target_budget,
    }


def _requests_from_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    *,
    backend: str = DEFAULT_BACKEND,
) -> list[CollectionRequest]:
    # This helper is also the public parser round-trip boundary. Resolve
    # legacy defaults here; private-plan merging never calls this function.
    args.count = 15 if args.count is None else args.count
    args.screenshot_mode = args.screenshot_mode or "off"
    options = _request_kwargs(args, backend)
    if args.mode == "search":
        keyword = (args.keyword or "").strip()
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
        if args.comments and (args.platform != "xhs" or args.screenshot_mode != "all"):
            parser.error("search comments require xhs and screenshot mode all")
        return [
            CollectionRequest(
                platform=args.platform,
                count=args.count,
                keyword=keyword,
                comment_limit=args.comments or 0,
                browser_assist=args.browser_assist,
                screenshot_mode=args.screenshot_mode,
                **options,
            )
        ]

    platforms = _selected_platforms(parser, args.platforms)
    if args.xhs_comments and "xhs" not in platforms:
        parser.error("xhs comments require the xhs platform")
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
            # Creator collection on Xiaohongshu is intentionally detail-first:
            # preview cards are not authoritative for the complete article or
            # engagement values.
            or platform == "xhs"
        )
        requests.append(
            CollectionRequest(
                platform=platform,
                count=count,
                uid=uid.strip(),
                complete=complete,
                comment_limit=(args.xhs_comments or 0) if platform == "xhs" else 0,
                browser_assist=args.browser_assist,
                screenshot_mode=args.screenshot_mode,
                **options,
            )
        )
    return requests


def _new_run_id() -> str:
    return f"{time.time_ns()}-{secrets.token_hex(4)}"


def _create_store(output_dir: Path, run_id: str | None = None) -> RunStore:
    root = output_dir.expanduser().resolve()
    existed = root.exists()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not existed:
        root.chmod(0o700)
    return RunStore.create(root, run_id or _new_run_id())


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


def _evidence_shortfall(request: CollectionRequest, records: Sequence[dict[str, Any]]) -> str | None:
    if _has_screenshot_shortfall(request, records):
        return "screenshot-shortfall"
    if request.complete and any(record.get("complete") is not True for record in records):
        return "incomplete-record"
    return None


def _result_status(request: CollectionRequest, records: Sequence[dict[str, Any]]) -> str:
    if request.count > 0 and len(records) < request.count:
        return "shortfall"
    if _evidence_shortfall(request, records):
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
    return {"kind": "result", "code": _evidence_shortfall(request, records) or "incomplete-record"}


def _failure_diagnostic(error: BaseException) -> dict[str, str]:
    if isinstance(error, ModuleNotFoundError):
        return {"kind": "dependency", "code": "module-not-found"}
    if isinstance(error, PreconditionError):
        return {"kind": "precondition", "code": "precondition-failed"}
    if isinstance(error, CapabilityError):
        # The declared backend does not have this operation. Reported as a
        # precondition, never emulated.
        return {"kind": "precondition", "code": "precondition-failed"}
    if isinstance(error, _SOURCE_RESPONSE_ERRORS):
        return {"kind": "source-response", "code": "source-response-failed"}
    if isinstance(error, xhs.CaptureTimeout):
        return {"kind": "timeout", "code": error.code}
    if isinstance(error, _CREATOR_CAPTURE_TIMEOUTS):
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
    safety_gate: XhsSafetyGate | None = None,
    emit_progress: bool = True,
) -> int:
    from .progress import ProgressRecorder
    progress = ProgressRecorder(enabled=emit_progress)
    run_phase = progress.start("run")
    preflight_phase = progress.start("browser-preflight")
    selected = [request.platform for request in requests]
    statuses = {platform: "not-run" for platform in selected}
    counts = {platform: 0 for platform in selected}
    paths: dict[str, str] = {}
    diagnostics = {
        platform: {"kind": "not-run", "code": "preflight-aborted"}
        for platform in selected
    }

    try:
        async with dispatcher:
            preflight = getattr(dispatcher, "preflight", None)
            if preflight is not None:
                await preflight(requests)
            progress.finish(preflight_phase)
            store = _create_store(output_dir)
            progress.bind_path(store.path / "phase-timings.json")
            def commit_manifest() -> None:
                overall = (
                    "risk-stopped" if "risk-stopped" in statuses.values()
                    else "complete" if all(value == "complete" for value in statuses.values())
                    else "failed"
                )
                store.write_manifest(
                    counts=counts, paths=paths, platforms=statuses,
                    status=overall, diagnostics=diagnostics,
                )
                store.commit_snapshot()

            def persist_progress(platform: str, records: Sequence[dict[str, Any]]) -> None:
                if platform not in selected:
                    raise CollectorContractError
                path = store.write_json(f"{platform}.json", list(records))
                paths[platform] = path.name
                counts[platform] = len(records)
                # A prefix is durable evidence, but the running platform has not
                # completed. Only the collector's normal return can mark it complete.
                commit_manifest()
                progress.update(platform_phase, len(records))

            commit_manifest()
            bind_store = getattr(dispatcher, "bind_store", None)
            if bind_store is not None:
                bind_store(store)
            bind_progress = getattr(dispatcher, "bind_progress", None)
            if bind_progress is not None:
                bind_progress(persist_progress)
            risk_stopped = False
            failed = False
            for request in requests:
                platform = request.platform
                platform_phase = progress.start("platform-collection", platform=platform, requested=request.count)
                started_at = datetime.now(UTC).isoformat()
                statuses[platform] = "failed"
                diagnostics[platform] = {"kind": "internal", "code": "unexpected"}
                try:
                    if platform == "xhs" and safety_gate is not None:
                        safety_gate.mark_collection_started()
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
                    if isinstance(dispatcher, RuntimeDispatcher):
                        from .shared_safety import record_platform_risk
                        record_platform_risk(platform, error.code)
                    if platform == "xhs" and safety_gate is not None:
                        safety_gate.latch(error.code)
                    statuses[platform] = "risk-stopped"
                    diagnostics[platform] = {
                        "kind": "risk-stop",
                        "code": error.code,
                    }
                    if platform == "xhs":
                        partial_reader = getattr(dispatcher, "partial_records", None)
                        partial = partial_reader(platform) if partial_reader is not None else []
                        if partial:
                            path = store.write_json("xhs.json", partial)
                            counts[platform] = len(partial)
                            paths[platform] = path.name
                        paths.update(
                            _write_xhs_artifacts(
                                store,
                                partial,
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
                    if isinstance(error, _CREATOR_CAPTURE_TIMEOUTS):
                        observation = getattr(error, "observation", "unclassified")
                        if observation in {
                            "no-endpoint",
                            "identity-mismatch",
                            "unclassified",
                        }:
                            print(
                                "media-missher-observation "
                                f"platform={platform} stage=creator-source "
                                f"result={observation}",
                                file=sys.stderr,
                            )
                        routes = getattr(error, "routes", ())
                        if isinstance(routes, tuple):
                            for route in routes[:12]:
                                if (
                                    isinstance(route, str)
                                    and 1 <= len(route) <= 240
                                    and not any(
                                        character in route
                                        for character in ("?", "#", "@", "=", "\\")
                                    )
                                ):
                                    print(
                                        "media-missher-observation "
                                        f"platform={platform} stage=creator-source "
                                        f"route={route}",
                                        file=sys.stderr,
                                    )
                    if platform == "xhs":
                        partial: list[dict[str, Any]] = []
                        partial_reader = getattr(dispatcher, "partial_records", None)
                        if partial_reader is not None:
                            try:
                                candidate = partial_reader(platform)
                                if isinstance(candidate, list) and all(
                                    isinstance(record, dict) for record in candidate
                                ):
                                    partial = [dict(record) for record in candidate]
                            except Exception:
                                partial = []
                        try:
                            if partial:
                                path = store.write_json("xhs.json", partial)
                                counts[platform] = len(partial)
                                paths[platform] = path.name
                            paths.update(
                                _write_xhs_artifacts(
                                    store,
                                    partial,
                                    status="failed",
                                    started_at=started_at,
                                    reason=diagnostic["code"],
                                )
                            )
                        except Exception:
                            pass
                    failed = True
                finally:
                    # Also executes for task cancellation. Previously the manifest
                    # existed only after the entire multi-platform loop returned.
                    phase_state = "cancelled" if isinstance(sys.exc_info()[1], (asyncio.CancelledError, KeyboardInterrupt)) else "completed" if statuses[platform] == "complete" else "failed"
                    progress.finish(platform_phase, phase_state, completed=counts[platform])
                    commit_manifest()

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
            store.commit_snapshot()
        return 75 if risk_stopped else 1 if failed else 0

    finally:
        error = sys.exc_info()[1]
        state = "cancelled" if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)) else "failed" if error is not None or any(value != "complete" for value in statuses.values()) else "completed"
        if not any(event["phase"] == "browser-preflight" for event in progress.timings):
            progress.finish(preflight_phase, state)
        progress.finish(run_phase, state)


# ---------------------------------------------------------------------------
# plan path: multiple targets, best_effort budgets and the topic task
# ---------------------------------------------------------------------------


def _read_private_json(path: Path) -> Mapping[str, Any]:
    """Read one private data-only file, with the same checks as ``--exclude-file``."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as error:
        raise _Precondition("targets-json-invalid") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > _MAX_PLAN_BYTES
        ):
            raise _Precondition("targets-json-permissions")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            value = json.load(handle)
    except _Precondition:
        raise
    except (OSError, ValueError, UnicodeError) as error:
        raise _Precondition("targets-json-invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(value, Mapping):
        raise _Precondition("targets-json-invalid")
    return value


def _plan_overrides(args: argparse.Namespace, value: Mapping[str, Any]) -> dict[str, Any]:
    """CLI knobs that were explicitly given, on top of the plan file."""

    overrides: dict[str, Any] = {}
    if args.count is not None:
        overrides["count"] = args.count
        if "per_target_counts" in value:
            overrides["per_target_counts"] = {}
    if args.count_mode is not None:
        overrides["count_mode"] = args.count_mode
    if args.run_deadline is not None:
        overrides["run_deadline_seconds"] = args.run_deadline
    if args.batch_pages is not None:
        overrides["batch_pages"] = args.batch_pages
    if args.batch_interval is not None:
        overrides["batch_interval_seconds"] = args.batch_interval
    if args.per_target_budget is not None:
        overrides["per_target_budget"] = args.per_target_budget
    if args.allow_navigation:
        overrides["allow_navigation"] = True
    raw_targets = value.get("targets", [])
    if getattr(args, "xhs_complete", False) and not any(t.get("platform") == "xhs" and t.get("mode", "creator") == "creator" for t in raw_targets if isinstance(t, Mapping)):
        raise _Precondition("plan-request-invalid")
    if getattr(args, "complete", False) and any(t.get("platform") in {"bilibili", "xhs"} and t.get("mode") != "creator" for t in raw_targets if isinstance(t, Mapping)):
        raise _Precondition("plan-request-invalid")
    comments = getattr(args, "xhs_comments", getattr(args, "comments", None))
    if comments is not None:
        overrides["xhs_comments"] = comments
    if getattr(args, "bilibili_complete", False) or getattr(args, "complete", False):
        if getattr(args, "bilibili_complete", False) or any(t.get("platform") == "bilibili" for t in raw_targets if isinstance(t, Mapping)):
            overrides["bilibili_complete"] = True
    if args.screenshot_mode is not None:
        overrides["screenshot_mode"] = args.screenshot_mode
    file_backend = value.get("backend")
    if not isinstance(file_backend, str) or not file_backend.strip():
        file_backend = None
    try:
        overrides["backend"] = normalize_backend(
            args.backend, preference=file_backend or _platform_preference()
        )
    except ContractError as error:
        message = str(error)
        raise _Precondition(
            "backend-auto-unsupported"
            if message == "automatic backend switching is not supported"
            else message if message in {"backend-retired-browserskill", "backend-retired-computer-use"} else "backend-invalid"
        ) from error
    return overrides


def _plan_from_file(args: argparse.Namespace) -> CollectionPlan:
    path = args.targets_json
    try:
        value = _read_private_json(path)
        overrides = _plan_overrides(args, value)
        return CollectionPlan.from_json({**value, **overrides})
    except _Precondition:
        raise
    except ContractError as error:
        raise _Precondition("targets-json-unsupported") from error
    except OSError as error:
        raise _Precondition("targets-json-invalid") from error


def _topic_plan(args: argparse.Namespace, backend: str) -> CollectionPlan:
    """Turn a Weibo topic name or URL into a topic task, or refuse it."""

    raw = getattr(args, "topic", None)
    try:
        parsed = weibo_topic.parse_topic_input(raw)
    except weibo_topic.TopicError as error:
        code = error.args[0] if error.args and isinstance(error.args[0], str) else ""
        raise _Precondition(code if code in _TOPIC_CODES else "topic-input-invalid") from error
    if not weibo_topic.supported_topic_kind(parsed.kind):
        # A super topic is a different page contract. Refusing it is the whole
        # point: a normal keyword search must never stand in for it.
        raise _Precondition("topic-container-unsupported")
    target = Target(
        platform="weibo",
        mode=TASK_MODE_TOPIC,
        label=parsed.name,
        topic=parsed.name,
        topic_kind=parsed.kind,
    )
    overrides: dict[str, Any] = {
        "backend": backend,
        "count_mode": args.count_mode or COUNT_MODE_FIXED,
    }
    if args.run_deadline is not None:
        overrides["run_deadline_seconds"] = args.run_deadline
    if args.batch_pages is not None:
        overrides["batch_pages"] = args.batch_pages
    if args.batch_interval is not None:
        overrides["batch_interval_seconds"] = args.batch_interval
    if args.per_target_budget is not None:
        overrides["per_target_budget"] = args.per_target_budget
    overrides.update(_plan_overrides(args, {"backend": backend, "targets": [target.to_json()]}))
    overrides.setdefault("count", args.count)
    return CollectionPlan(targets=(target,), **overrides)


def _plan_from_requests(parser: argparse.ArgumentParser, args: argparse.Namespace, backend: str) -> CollectionPlan:
    """Freeze legacy explicit identities/options when an envelope is requested."""
    requests = _requests_from_args(parser, args, backend=backend)
    targets = tuple(
        Target(platform=r.platform, mode=TASK_MODE_SEARCH, keyword=r.keyword)
        if r.keyword is not None else
        Target(platform=r.platform, mode=TASK_MODE_CREATOR, **(
            {"handle": r.uid} if r.platform == "x" and not (r.uid or "").isdigit() else {"uid": r.uid}
        )) for r in requests
    )
    overrides = _plan_overrides(args, {"backend": backend, "targets": [t.to_json() for t in targets]})
    return CollectionPlan(targets=targets,
        per_target_counts={t.identity:r.count for t,r in zip(targets,requests) if r.count>0 and r.count!=args.count}, **overrides)


class PlanExecutor:
    """Adapt one dispatcher to the plan runner's per-batch contract.

    A task is executed only by the collector that really implements it: the four
    legacy collectors, the X collector, and the Weibo topic collector. A mode the
    frozen backend cannot evidence is refused with a fixed precondition code
    instead of quietly degrading into a keyword search or a page-observed guess.
    """

    def __init__(self, *, dispatcher: Any, plan: CollectionPlan, args: argparse.Namespace, progress: Any = None) -> None:
        self.dispatcher = dispatcher
        self.plan = plan
        self.args = args
        self.progress = progress
        if isinstance(dispatcher, RuntimeDispatcher):
            dispatcher.pacing.interval = plan.batch_interval_seconds

    def _request_for(self, target: Target, context: Any) -> CollectionRequest:
        if target.mode == TASK_MODE_TOPIC:
            if target.platform != "weibo":
                raise _Precondition("topic-unsupported-platform")
            topic = target.topic
            if not isinstance(topic, str) or not topic.strip():
                raise _Precondition("target-topic-missing")
            count = self._count_for(context)
            try:
                return _plan_topic_request(
                    topic=topic,
                    topic_kind=target.topic_kind,
                    count=count,
                    request=self.request_for_plan(context),
                )
            except (TopicError, ValueError) as error:
                raise _Precondition(_topic_code(error)) from error
        if target.platform == "x":
            if target.mode == TASK_MODE_CREATOR:
                if not (target.handle or target.uid or target.homepage):
                    raise _Precondition("target-identity-missing")
            elif not target.keyword:
                raise _Precondition("target-keyword-missing")
            count = self._count_for(context)
            return self._build_request(
                platform="x",
                count=count,
                uid=target.handle or target.uid,
                keyword=target.keyword,
                complete=False,
                context=context,
            )
        if target.platform not in _COLLECTORS:
            raise _Precondition("platform-collector-missing")
        if target.mode == TASK_MODE_CREATOR:
            uid = target.uid
            if not isinstance(uid, str) or not uid.strip():
                # A display name or an unverified homepage is not an identity.
                raise _Precondition("target-identity-missing")
            request_uid, keyword = uid.strip(), None
        else:
            keyword = target.keyword
            if not isinstance(keyword, str) or not keyword.strip():
                raise _Precondition("target-keyword-missing")
            request_uid, keyword = None, keyword.strip()
        return self._build_request(
            platform=target.platform,
            count=self._count_for(context),
            uid=request_uid,
            keyword=keyword,
            complete=target.mode == TASK_MODE_CREATOR and self.plan.backend == BACKEND_CDP and (target.platform == "xhs" or (target.platform == "bilibili" and self.plan.bilibili_complete)),
            context=context,
        )

    def _count_for(self, context: Any) -> int:
        if context.count_mode == COUNT_MODE_FIXED:
            count = context.budget if context.budget else context.count
        else:
            count = context.budget or context.policy.batch_records
        if not isinstance(count, int) or count < 0:
            count = context.policy.batch_records
        return count or context.policy.batch_records

    def request_for_plan(self, context: Any) -> CollectionRequest:
        """The bounded request shape shared by every plan task mode."""

        return CollectionRequest(
            platform="weibo",
            count=self._count_for(context),
            uid="0",
            browser_assist="off",
            screenshot_mode=self.plan.screenshot_mode,
            backend=self.plan.backend,
            count_mode=context.count_mode,
            best_effort_budget=context.target_budget,
            batch_limit=min(self._count_for(context), context.policy.batch_records),
            known_user_ids=context.known_user_ids,
            continue_page=context.batch_index > 0,
            page_cap=context.policy.batch_pages,
            exclude_ids=tuple(key.rsplit(":", 1)[-1] for key in context.excluded_ids),
        )

    def _build_request(
        self,
        *,
        platform: str,
        count: int,
        uid: str | None,
        keyword: str | None,
        complete: bool,
        context: Any,
    ) -> CollectionRequest:
        try:
            return CollectionRequest(
                platform=platform,
                count=count,
                uid=uid,
                keyword=keyword,
                complete=complete,
                sort=context.target.sort,
                comment_limit=self.plan.xhs_comments if platform == "xhs" else 0,
                browser_assist="off",
                screenshot_mode=self.plan.screenshot_mode,
                backend=self.plan.backend,
                count_mode=context.count_mode,
                best_effort_budget=context.target_budget,
                batch_limit=min(count, context.policy.batch_records),
                known_user_ids=context.known_user_ids,
                continue_page=context.batch_index > 0,
                page_cap=context.policy.batch_pages,
                exclude_ids=tuple(key.rsplit(":", 1)[-1] for key in context.excluded_ids),
            )
        except ValueError as error:
            # A request the runtime contract refuses (for example screenshot
            # mode all with a zero count) is a precondition, never a crash.
            raise _Precondition("plan-request-invalid") from error

    async def __call__(self, target: Target, context: Any) -> TaskOutcome:
        token = self.progress.start("platform-collection", platform=target.platform, requested=self._count_for(context)) if self.progress else None
        def accepted(platform, records):
            from .exporting import record_kind
            if platform != target.platform:
                return
            if context.checkpoint:
                context.checkpoint(None, [record for record in records if record_kind(record) == "posts"])
            if token:
                self.progress.update(token, min(10000, len(records)))
        bind = getattr(self.dispatcher, "bind_progress", None)
        if callable(bind):
            bind(accepted)
        try:
            outcome = await self._execute_batch(target, context)
        except BaseException:
            if token:
                self.progress.finish(token, "failed")
            raise
        if token:
            state = "cancelled" if outcome.stop_reason == "cancelled" else "failed" if outcome.risk_code or outcome.stop_reason else "completed"
            self.progress.finish(token, state, completed=min(10000, len(outcome.records)))
        return outcome

    async def _execute_batch(self, target: Target, context: Any) -> TaskOutcome:
        request = self._request_for(target, context)
        pages: int = 0
        risk_code = None
        stop_reason = None
        gate = SharedXhsSafetyGate() if request.platform == "xhs" and isinstance(self.dispatcher, (RuntimeDispatcher,)) else None
        try:
            with ExitStack() as gates:
                if gate is not None:
                    gates.enter_context(gate.batch())
                try:
                    operation = self.dispatcher.collect(request)
                    if isinstance(self.dispatcher, (RuntimeDispatcher,)):
                        records = await asyncio.wait_for(operation, timeout=min(context.deadline_seconds, getattr(self.args, "platform_timeout", context.deadline_seconds)))
                    else:
                        records = await operation
                except (RiskStop, BrowserRiskError, *_PLATFORM_STOPS) as error:
                    risk_code = _safe_risk_code(getattr(error, "code", error.args[0] if error.args else None))
                    if gate is not None:
                        gate.latch(risk_code)
                    if isinstance(self.dispatcher, RuntimeDispatcher):
                        from .shared_safety import record_platform_risk
                        record_platform_risk(request.platform, risk_code)
                    partial = getattr(self.dispatcher, "partial_records", None)
                    records = partial(request.platform) if callable(partial) else []
        except (TimeoutError, asyncio.CancelledError) as error:
            stop_reason = "cancelled" if isinstance(error, asyncio.CancelledError) else "timeout"
            partial = getattr(self.dispatcher, "partial_records", None)
            records = partial(request.platform) if callable(partial) else []
        except SafetyBlocked as error:
            raise _Precondition(error.code) from error
        except TopicError as error:
            # A topic page the page contracts cannot serve is a precondition with
            # a fixed code, never a fabricated keyword search.
            raise _Precondition(_topic_code(error)) from error
        if not isinstance(records, list) or not all(
            isinstance(record, dict) for record in records
        ):
            raise _Precondition("plan-executor-contract")
        pages = int(getattr(self.dispatcher, "last_pages", 0) or 0)
        from .exporting import record_kind
        posts = [record for record in records if record_kind(record) == "posts"]
        shortfall = _evidence_shortfall(request, posts)
        from .observations import missing
        from .contracts import default_field_groups
        missing_fields = {field: sum(missing(record.get(field)) or
                                    (field in {"complete", "text_complete"} and record.get(field) is not True)
                                    for record in posts)
                          for field in self.plan.required_fields}
        missing_fields = {field: count for field, count in missing_fields.items() if count}
        if missing_fields:
            shortfall = shortfall or "required-fields-missing"
        if shortfall:
            # Enough IDs cannot satisfy a requested detail/screenshot contract.
            # Preserve verified fields but never turn incomplete evidence into
            # a successful target merely because its count was reached.
            stop_reason = stop_reason or "error"
        if context.checkpoint is not None:
            coverage = {group: {field: sum(not missing(record.get(field)) for record in posts)
                               for field in default_field_groups(target.platform)[group]}
                        for group in self.plan.field_groups}
            context.checkpoint({"evidence_shortfall": shortfall,
                                "missing_required_fields": missing_fields,
                                "field_group_coverage": coverage}, posts)
        return TaskOutcome(
            records=[dict(record) for record in posts],
            users=[dict(record) for record in records if record_kind(record) != "posts"],
            pages=pages, risk_code=risk_code,
            stop_reason=stop_reason or getattr(self.dispatcher, "last_stop_reason", None),
            exhausted=bool(getattr(self.dispatcher, "last_exhausted", False)),
        )


def _plan_topic_request(
    *,
    topic: str,
    topic_kind: str | None,
    count: int,
    request: CollectionRequest,
) -> CollectionRequest:
    """Build the topic request only after the topic input is really verified."""

    parsed = weibo_topic.parse_topic_input(topic)
    if not weibo_topic.supported_topic_kind(parsed.kind):
        raise TopicError("topic-container-unsupported")
    if topic_kind is not None and topic_kind != parsed.kind:
        raise TopicError("topic-kind-mismatch")
    return replace(
        request,
        platform="weibo",
        topic=parsed.name,
        topic_kind=parsed.kind,
        uid=None,
        count=count,
    )


def _topic_code(error: BaseException) -> str:
    raw = str(error).strip().casefold()
    if _SAFE_CODE_RE.fullmatch(raw or "") is None:
        return "topic-input-invalid"
    return raw


def _read_plan_resume(root: Path, run_id: str, plan: CollectionPlan, profile_digest: str | None) -> list[dict[str, Any]]:
    """Read a committed, exact-plan prefix; no browser work and no parent writes."""
    if re.fullmatch(r"run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) is None:
        raise ValueError("invalid resume id")
    parent = root.expanduser().resolve() / run_id
    metadata = parent.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.getuid():
        raise ValueError("unsafe resume directory")
    if CollectionPlan.from_json(_read_private_json(parent / "plan.json")).to_json() != plan.to_json():
        raise ValueError("resume plan changed")
    binding = _read_private_json(parent / "run-binding.json")
    if binding.get("profile_digest") != profile_digest:
        raise ValueError("resume profile changed")
    if os.path.lexists(parent / "risk-marker.json"):
        _read_private_json(parent / "risk-marker.json")
        raise ValueError("risk-stopped runs cannot resume")
    from .batch_journal import journal_snapshot
    recovered = journal_snapshot(parent) if (parent / "journal").exists() else None
    saved = _read_private_json(parent / "committed.json") if (parent / "committed.json").exists() else recovered
    if not isinstance(saved, dict):
        raise ValueError("resume evidence missing")
    manifest = saved.get("manifest", {})
    artifacts = saved.get("artifacts", {})
    if saved.get("schema") != 1 or not isinstance(manifest, dict) or manifest.get("schema_version") != 3 or manifest.get("backend") != plan.backend or manifest.get("status") not in {"complete", "partial", "failed"}:
        raise ValueError("resume manifest invalid or risk stopped")
    if not isinstance(artifacts, dict) or set(artifacts) != set(plan.platforms) or set(manifest.get("counts", {})) != set(plan.platforms):
        raise ValueError("resume platforms changed")
    from .best_effort import identity_of, target_identities
    targets = {target.identity: target for target in plan.targets}
    records = []
    seen = set()
    for platform, items in artifacts.items():
        if not isinstance(items, list) or len(items) != manifest["counts"][platform]:
            raise ValueError("resume count mismatch")
        for record in items:
            if not isinstance(record, dict) or record.get("platform") != platform or record.get("target_identity") not in targets:
                raise ValueError("resume record target invalid")
            if any(source not in targets or targets[source].platform != platform for source in target_identities(record)):
                raise ValueError("resume record target invalid")
            identity = identity_of(record, platform)
            if identity is None or identity in seen or targets[record["target_identity"]].platform != platform:
                raise ValueError("resume record identity invalid")
            seen.add(identity)
            records.append(dict(record))
    from .exporting import record_kind
    for target, request in zip(plan.targets, _plan_requests(plan, argparse.Namespace()), strict=True):
        accepted = [row for row in records if target.identity in target_identities(row) and record_kind(row) == "posts"]
        if _evidence_shortfall(request, accepted):
            raise ValueError("resume incomplete requested evidence")
    return records


def _run_plan(
    plan: CollectionPlan,
    *,
    args: argparse.Namespace,
    dispatcher: Any,
    injected: bool,
) -> int:
    """Execute one plan and write its private artifacts."""

    diagnostic_platform = plan.platforms[0] if plan.platforms else "unknown"
    run_id = _new_run_id()
    initial_records = []
    parent_id = getattr(args, "resume_run", None)
    if parent_id is not None:
        try:
            initial_records = _read_plan_resume(args.output_dir, parent_id, plan, getattr(args, "profile_digest", None))
        except (ValueError, OSError, _Precondition):
            return _diagnostic(diagnostic_platform, "precondition", "resume-plan-invalid")
    store = _create_store(args.output_dir, run_id)
    store.write_json("plan.json", plan.to_json())
    store.write_json("run-binding.json", {"schema_version": 1, "profile_digest": getattr(args, "profile_digest", None), "parent_run_id": parent_id})

    from .batch_journal import BatchJournal, snapshot_projection
    journal = BatchJournal(store.path)
    sequence = 0
    snapshots = {}
    def checkpoint(state: Any, records: Sequence[Mapping[str, Any]]) -> None:
        nonlocal sequence
        target = getattr(state, "target", None)
        if isinstance(target, Target):
            accepted = [*records, *state.checkpoint.get("user_records", [])]
            snapshots[target.identity] = {"state": state.to_json(), "records": [dict(record, target_identity=target.identity) for record in accepted]}
        from .best_effort import identity_of, add_target_identity, target_identities
        prefix = []
        seen = {}
        for snapshot in snapshots.values():
            for record in snapshot["records"]:
                key = identity_of(record, record.get("platform"))
                if key is not None and key not in seen:
                    copy = dict(record)
                    prefix.append(copy); seen[key] = copy
                elif key is not None:
                    from .observations import merge_observation
                    merge_observation(seen[key], record)
                    for source in target_identities(record):
                        add_target_identity(seen[key], source)
        states = {identity: value["state"] for identity, value in snapshots.items()}
        projection = snapshot_projection(prefix, plan, states)
        if projection["status"] == "risk-stopped":
            store.write_json("risk-marker.json", {"schema_version": 1, "code": "risk-signal"})
        sequence += 1
        journal.commit(sequence, prefix, {"manifest": projection, "plan": plan.to_json(), "profile_digest": getattr(args, "profile_digest", None), "targets": states, "backend": plan.backend, "recovery": "relocate-and-exclude-seen-ids"})
        store.write_json(
            "checkpoint.json",
            {
                "schema_version": 1,
                "run_id": run_id,
                "targets": snapshots,
                "target": target.to_json() if isinstance(target, Target) else None,
                "target_identity": target.identity if isinstance(target, Target) else None,
                "phase": getattr(state, "phase", None),
                "stop_reason": getattr(state, "stop_reason", None),
                "batches": getattr(state, "batches", None),
                "pages": getattr(state, "pages", None),
                "records": [
                    dict(record)
                    for record in list(records)[:_MAX_CHECKPOINT_RECORDS]
                ],
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )

    from .progress import ProgressRecorder
    progress = ProgressRecorder(enabled=not injected)
    if not injected:
        progress.bind_path(store.path / "phase-timings.json")
    executor = PlanExecutor(dispatcher=dispatcher, plan=plan, args=args, progress=progress)
    runner = PlanRunner(
        plan,
        execute_task=executor,
        checkpoint=checkpoint,
        initial_records=initial_records,
        deadline_started_at=time.monotonic() if not injected else None,
        # An injected dispatcher is a test/local shim that never reaches a real
        # platform, so the inter-batch wait must not suspend the driver. A real
        # run always uses the platform's own interval.
        sleep=_no_wait if injected else None,
    )
    try:
        async def execute_plan() -> Any:
            if not injected and "xhs" in plan.platforms:
                status = SharedXhsSafetyGate().status()
                if status["blocked"]:
                    raise SafetyBlocked(status["reason"], status["remaining_seconds"])
            async with dispatcher:
                bind_store = getattr(dispatcher, "bind_store", None)
                if callable(bind_store):
                    bind_store(store)
                preflight = getattr(dispatcher, "preflight", None)
                token = progress.start("browser-preflight")
                try:
                    if preflight is not None:
                        await preflight(_plan_requests(plan, args))
                except BaseException:
                    progress.finish(token, "failed")
                    raise
                progress.finish(token)
                if injected:
                    return await runner.run()
                loop = asyncio.get_running_loop()
                task = asyncio.current_task()
                previous = signal.getsignal(signal.SIGTERM)
                loop.add_signal_handler(signal.SIGTERM, task.cancel)
                try:
                    return await runner.run()
                finally:
                    loop.remove_signal_handler(signal.SIGTERM)
                    signal.signal(signal.SIGTERM, previous)

        summary = (
            _run_immediate_value(execute_plan())
            if injected
            else asyncio.run(execute_plan())
        )
    except PreconditionLikeError as error:
        return _diagnostic(diagnostic_platform, "precondition", error.code)
    except CapabilityError as error:
        return _diagnostic(diagnostic_platform, "precondition", error.code)
    except PlatformRiskPreflightError as error:
        if not injected:
            from .shared_safety import record_platform_risk
            record_platform_risk(error.platform, error.code)
            if error.platform == "xhs":
                SharedXhsSafetyGate().record_risk(error.code)
        return _diagnostic(error.platform, "risk-stop", error.code)
    except PlatformPreflightError as error:
        return _diagnostic(error.platform, "precondition", error.code)

    # Public persisted status is uniform across all artifacts; stop_reason
    # retains cancellation, timeout and budget distinctions.
    if summary.status != "complete" and not summary.risk_code:
        summary.status = "partial" if summary.all_records() else "failed"
    evidence_paths = [
        "plan.json",
        "run_manifest.json",
        "summary.json",
        "checkpoint.json",
    ]
    try:
        manifest = summary.build_manifest(f"run-{run_id}", evidence_paths)
    except (ContractError, ValueError):
        return _diagnostic(diagnostic_platform, "precondition", "plan-manifest-invalid")
    store.write_json("plan.json", plan.to_json())
    store.write_json("summary.json", summary.to_json())
    for platform in plan.platforms:
        platform_records = [
            record
            for record in summary.all_records()
            if record.get("platform") == platform
        ]
        store.write_json(f"{platform}.json", platform_records)
    store.write_json("run_manifest.json", manifest.to_json())
    statuses = {}
    diagnostics = {}
    counts = {}
    for platform in plan.platforms:
        tasks = [task for task in summary.tasks if task["target"]["platform"] == platform]
        reasons = {task.get("stop_reason") for task in tasks}
        shortfall = next((task.get("checkpoint", {}).get("evidence_shortfall") for task in tasks if task.get("checkpoint", {}).get("evidence_shortfall") in {"incomplete-record", "screenshot-shortfall", "required-fields-missing"}), None)
        if "risk-stopped" in reasons:
            statuses[platform] = "risk-stopped"
            diagnostics[platform] = {"kind": "risk-stop", "code": summary.risk_code or "risk-signal"}
        elif shortfall:
            statuses[platform] = "incomplete"
            diagnostics[platform] = {"kind": "result", "code": shortfall}
        elif tasks and all(task.get("phase") == "not-run" for task in tasks):
            statuses[platform] = "not-run"
            diagnostics[platform] = {"kind": "not-run", "code": "prior-risk-stop" if summary.risk_code else "preflight-aborted"}
        elif reasons and reasons <= {"count-reached", "natural-end"}:
            statuses[platform] = "complete"
            diagnostics[platform] = {"kind": "ok", "code": "ok"}
        else:
            statuses[platform] = "shortfall"
            diagnostics[platform] = {"kind": "result", "code": "count-shortfall"}
        counts[platform] = sum(record.get("platform") == platform for record in summary.all_records())
    status = summary.status
    store.write_manifest(
        counts=counts, paths={platform: f"{platform}.json" for platform in plan.platforms},
        platforms=statuses, diagnostics=diagnostics, status=status,
        schema_version=3, backend=plan.backend, record_kinds=dict(summary.record_kinds),
    )
    store.commit_snapshot()
    controller_status = "success" if summary.status == "complete" else "risk-stopped" if summary.risk_code else "partial" if summary.all_records() else "failed"
    store.write_json("run-result.json", {"schema": 1, "status": controller_status})
    print(json.dumps({
        "status": controller_status, "run_dir": str(store.path.resolve()),
        "evidence": [str(path.resolve()) for path in sorted(store.path.iterdir()) if path.is_file()],
        "errors": [], "stop_reason": summary.stop_reason, "resumable": summary.resumable,
        "phase_timings": progress.timings, "phase_timings_persisted": not progress.storage_failed,
        "parent_run_id": parent_id, "prior_records": len(initial_records),
    }, ensure_ascii=False))
    return 0 if controller_status == "success" else 75 if controller_status == "risk-stopped" else 1


def _plan_requests(plan: CollectionPlan, args: argparse.Namespace) -> list[CollectionRequest]:
    """Minimal request view of a plan, used only for dispatcher preflight.

    A target this build cannot express as a request is skipped here; the plan
    executor refuses it later with its own fixed precondition code.
    """

    requests: list[CollectionRequest] = []
    for target in plan.targets:
        try:
            if target.mode == TASK_MODE_TOPIC:
                requests.append(
                    CollectionRequest(
                        platform=target.platform,
                        count=plan.count_for(target),
                        topic=target.topic,
                        topic_kind=target.topic_kind,
                        backend=plan.backend,
                        count_mode=plan.count_mode,
                        best_effort_budget=plan.budget_for(target),
                    )
                )
                continue
            if target.mode == TASK_MODE_CREATOR and not (target.uid or target.handle):
                continue
            if target.mode == TASK_MODE_SEARCH and not target.keyword:
                continue
            requests.append(
                CollectionRequest(
                    platform=target.platform,
                    count=plan.count_for(target),
                    uid=(target.handle or target.uid) if target.mode == TASK_MODE_CREATOR else None,
                    keyword=target.keyword if target.mode == TASK_MODE_SEARCH else None,
                    backend=plan.backend,
                    complete=target.mode == TASK_MODE_CREATOR and (target.platform == "xhs" or (target.platform == "bilibili" and plan.bilibili_complete)),
                    comment_limit=plan.xhs_comments if target.platform == "xhs" else 0,
                    screenshot_mode=plan.screenshot_mode,
                    sort=target.sort,
                    count_mode=plan.count_mode,
                    best_effort_budget=plan.budget_for(target),
                )
            )
        except ValueError:
            continue
    return requests


def _run_immediate_value(coroutine: Any) -> Any:
    """Drive a non-suspending injected dispatcher without opening any sockets."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    coroutine.close()
    raise RuntimeError("injected dispatcher unexpectedly suspended")


def _run_immediate(coroutine: Any) -> int:
    return int(_run_immediate_value(coroutine))


async def _no_wait(seconds: float) -> None:
    """A no-op inter-batch wait used only for injected (non-network) runs."""

    return None


def _dispatcher_for(
    args: argparse.Namespace, *, injected: Any
) -> Any:
    if injected is not None:
        return injected
    return RuntimeDispatcher(
        args.cdp_url,
        allow_navigation=args.allow_navigation,
        browser_assist="off",
    )


def main(argv: Sequence[str] | None = None, *, fixed_platform: str | None = None, dispatcher: Any = None) -> int:
    values = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser(fixed_platform=fixed_platform)
    args = parser.parse_args(_normalize_legacy_argv(values))
    if args.targets_json is None:
        args.count = 15 if args.count is None else args.count
        args.screenshot_mode = args.screenshot_mode or "off"
    requested_platforms = _requested_platforms(parser, args)
    diagnostic_platform = requested_platforms[0] if requested_platforms else "unknown"

    # The deprecated CDP browser-assist bridge is not a backend. It is refused
    # with a fixed diagnostic instead of being remapped onto browser-skill.
    if args.browser_assist != "off":
        return _diagnostic(diagnostic_platform, "precondition", "browser-assist-replaced")

    try:
        backend = DEFAULT_BACKEND if args.targets_json is not None else _resolve_backend(args)
    except _Precondition as error:
        return _diagnostic(diagnostic_platform, "precondition", error.code)

    if args.topic is not None and args.targets_json is not None:
        parser.error("provide exactly one of --targets-json or --topic")
    if args.topic is not None and args.mode == "search" and args.keyword:
        parser.error("provide exactly one of --keyword or --topic")
    if args.topic is not None and args.mode == "creator":
        if any(
            (getattr(args, f"{platform}_uid") or "").strip()
            for platform in PLATFORMS
            if hasattr(args, f"{platform}_uid")
        ):
            parser.error("provide exactly one of --uid or --topic")
    if args.topic is not None and requested_platforms not in {(), ("weibo",)}:
        # A topic task is a Weibo page contract. Refuse it rather than running
        # the request as a keyword search on another platform.
        return _diagnostic(diagnostic_platform, "precondition", "topic-unsupported")
    if args.targets_json is None and args.screenshot_mode != "off" and not args.allow_navigation:
        parser.error("browser assist and screenshots require --allow-navigation")

    plan: CollectionPlan | None = None
    if args.targets_json is not None:
        if args.exclude_file is not None:
            # The continuation exclusion plan is a legacy per-platform shape; a
            # plan run must not appear to honour it while ignoring it.
            return _diagnostic(
                diagnostic_platform, "precondition", "exclude-file-plan-unsupported"
            )
        try:
            plan = _plan_from_file(args)
        except _Precondition as error:
            return _diagnostic(diagnostic_platform, "precondition", error.code)
    elif args.topic is not None:
        try:
            plan = _topic_plan(args, backend)
        except _Precondition as error:
            return _diagnostic(diagnostic_platform, "precondition", error.code)
        except ContractError:
            return _diagnostic(diagnostic_platform, "precondition", "plan-request-invalid")
    elif any(value is not None for value in (args.count_mode, args.run_deadline, args.batch_pages, args.batch_interval, args.per_target_budget)):
        try:
            plan = _plan_from_requests(parser, args, backend)
        except ContractError:
            return _diagnostic(diagnostic_platform, "precondition", "plan-request-invalid")

    if plan is not None:
        backend = plan.backend
        args.allow_navigation = plan.allow_navigation
        try:
            for target in plan.targets:
                ensure_supported(backend, target.platform, target.mode)
        except PreconditionLikeError as error:
            return _diagnostic(
                plan.platforms[0] if plan.platforms else diagnostic_platform,
                "precondition",
                error.code,
            )
        active = _dispatcher_for(args, injected=dispatcher)
        injected = dispatcher is not None
        try:
            with ExitStack() as leases:
                if not injected:
                    leases.enter_context(collection_lease(runtime_home(), inherit=True))
                return _run_plan(
                    plan, args=args, dispatcher=active, injected=injected
                )
        except SharedSafetyError as error:
            code = (
                str(error)
                if str(error) in {"collection-busy", "platform-cooldown", "platform-risk-latched"}
                else "shared-state-invalid"
            )
            return _diagnostic(diagnostic_platform, "precondition", code)
        except SafetyBlocked as error:
            return _diagnostic("xhs", "precondition", error.code)
        except Exception as exc:
            print(f"runtime failed: {type(exc).__name__}", file=sys.stderr)
            return 1

    requests = _requests_from_args(parser, args, backend=backend)
    unsupported = [
        request.platform
        for request in requests
        if request.platform not in _COLLECTORS
    ]
    if unsupported:
        # The platform is accepted by the model, but no collector is wired for
        # it yet. Refusing is the honest outcome; a keyword search would not be.
        return _diagnostic(unsupported[0], "precondition", "platform-collector-missing")
    try:
        for request in requests:
            ensure_supported(backend, request.platform, request.mode)
    except PreconditionLikeError as error:
        return _diagnostic(
            requests[0].platform if requests else diagnostic_platform,
            "precondition",
            error.code,
        )

    if args.exclude_file is not None:
        try:
            requests = apply_exclusions(args.exclude_file, requests)
        except (OSError, ValueError, UnicodeError):
            parser.error("invalid private continuation plan")
    injected = dispatcher is not None
    active_dispatcher = _dispatcher_for(args, injected=dispatcher)
    try:
        gate = SharedXhsSafetyGate() if not injected and "xhs" in requested_platforms else None
        with ExitStack() as leases:
            if not injected:
                leases.enter_context(collection_lease(runtime_home(), inherit=True))
            if gate is not None:
                leases.enter_context(gate.batch())
            operation = _run_requests(
                requests,
                output_dir=args.output_dir,
                dispatcher=active_dispatcher,
                platform_timeout=args.platform_timeout,
                enforce_timeout=not injected,
                safety_gate=gate,
                emit_progress=not injected,
            )
            try:
                return _run_immediate(operation) if injected else asyncio.run(operation)
            except PlatformRiskPreflightError as error:
                if not injected:
                    from .shared_safety import record_platform_risk
                    record_platform_risk(error.platform, error.code)
                if error.platform == "xhs" and gate is not None:
                    gate.latch(error.code)
                raise
    except SharedSafetyError as error:
        code = str(error) if str(error) in {"collection-busy", "platform-cooldown", "platform-risk-latched"} else "shared-state-invalid"
        for platform in requested_platforms:
            print(f"media-missher-diagnostic platform={platform} kind=precondition code={code}", file=sys.stderr)
        return 78
    except SafetyBlocked as error:
        print(
            f"media-missher-diagnostic platform=xhs kind=precondition code={error.code}",
            file=sys.stderr,
        )
        return 78
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
    "PlanExecutor",
    "PlatformPreflightError",
    "PlatformRiskPreflightError",
    "RiskStop",
    "RuntimeDispatcher",
    "build_parser",
    "main",
]
