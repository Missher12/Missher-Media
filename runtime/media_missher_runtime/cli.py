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

from .browser import BrowserSession
from .models import CollectionRequest
from .platforms import bilibili, douyin, weibo, xhs
from .storage import RunStore


PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")
DEFAULT_CDP_URL = "http://127.0.0.1:9222"

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


class RiskStop(RuntimeError):
    """Signal that no later platform may be run in this invocation."""


class RuntimeDispatcher:
    """Own one connection to the user's existing browser for a serial run."""

    def __init__(self, cdp_url: str, *, allow_navigation: bool = False) -> None:
        self.cdp_url = cdp_url
        self.allow_navigation = allow_navigation
        self.browser: BrowserSession | None = None

    async def __aenter__(self) -> "RuntimeDispatcher":
        self.browser = await BrowserSession.connect(
            self.cdp_url, allow_navigation=self.allow_navigation
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.browser is not None:
            await self.browser.close()

    async def preflight(self, requests: Sequence[CollectionRequest]) -> None:
        if self.browser is None:
            raise RuntimeError("browser dispatcher is not connected")
        for platform in dict.fromkeys(request.platform for request in requests):
            await self.browser.require_authenticated_page(platform)

    async def collect(self, request: CollectionRequest) -> list[dict[str, Any]]:
        if self.browser is None:
            raise RuntimeError("browser dispatcher is not connected")
        creator, search = _COLLECTORS[request.platform]
        operation = creator if request.uid is not None else search
        try:
            return await operation(request, self.browser)
        except _PLATFORM_STOPS as exc:
            raise RiskStop(request.platform) from exc


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
        return [CollectionRequest(platform=args.platform, count=args.count, keyword=keyword)]

    platforms = _selected_platforms(parser, args.platforms)
    requests: list[CollectionRequest] = []
    for platform in platforms:
        uid = getattr(args, f"{platform}_uid")
        if uid is None or not uid.strip():
            parser.error(f"--{platform}-uid is required for creator collection")
        override = getattr(args, f"{platform}_count")
        count = args.count if override is None else override
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


def _result_status(request: CollectionRequest, records: Sequence[dict[str, Any]]) -> str:
    if request.count > 0 and len(records) < request.count:
        return "shortfall"
    if request.complete and any(record.get("complete") is not True for record in records):
        return "incomplete"
    return "complete"


def _write_xhs_artifacts(
    store: RunStore,
    records: Sequence[dict[str, Any]],
    *,
    status: str,
    started_at: str,
) -> dict[str, str]:
    finished_at = datetime.now(UTC).isoformat()
    report = xhs.build_run_report(status, records, started_at, finished_at)
    checkpoint = xhs.build_checkpoint(records)
    report_path = store.write_json("xhs_report.json", report)
    checkpoint_path = store.write_json("xhs_checkpoint.json", checkpoint)
    return {"xhs_report": report_path.name, "xhs_checkpoint": checkpoint_path.name}


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

    async with dispatcher:
        preflight = getattr(dispatcher, "preflight", None)
        if preflight is not None:
            await preflight(requests)
        store = _create_store(output_dir)
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
                    raise ValueError("collector returned invalid records")
                path = store.write_json(f"{platform}.json", records)
                counts[platform] = len(records)
                paths[platform] = path.name
                statuses[platform] = _result_status(request, records)
                if platform == "xhs":
                    paths.update(_write_xhs_artifacts(store, records, status=statuses[platform], started_at=started_at))
                if statuses[platform] != "complete":
                    failed = True
            except RiskStop:
                statuses[platform] = "risk-stopped"
                if platform == "xhs":
                    paths.update(_write_xhs_artifacts(store, [], status="risk-stopped", started_at=started_at))
                risk_stopped = True
                break
            except Exception:
                statuses[platform] = "failed"
                if platform == "xhs":
                    try:
                        paths.update(_write_xhs_artifacts(store, [], status="failed", started_at=started_at))
                    except Exception:
                        pass
                failed = True

        overall = "risk-stopped" if risk_stopped else "failed" if failed else "complete"
        store.write_json(
            "manifest.json",
            {"counts": counts, "paths": paths, "platforms": statuses, "status": overall},
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
            args.cdp_url, allow_navigation=args.allow_navigation
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
    except Exception as exc:
        print(f"runtime failed: {type(exc).__name__}", file=sys.stderr)
        return 1


__all__ = ["DEFAULT_CDP_URL", "PLATFORMS", "RiskStop", "RuntimeDispatcher", "build_parser", "main"]
