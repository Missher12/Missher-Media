#!/usr/bin/env python3
"""Safely orchestrate one shared Media@Missher collection process."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import stat
from pathlib import Path

from media_missher_adapter import (
    DEFAULT_CDP_URL,
    PLATFORMS,
    CollectionRequest,
    ConfigurationError,
    parse_non_negative_int,
    parse_platforms,
    read_profile,
    resolve_data_root,
    resolve_runtime_layout,
    run_collection_request,
    _profile_identity,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect through the shared Media@Missher runtime with private JSON staging."
    )
    parser.add_argument("--profile", type=Path, help="Private mode-0600 JSON profile")
    parser.add_argument("--data-root", "--output", dest="data_root", type=Path)
    parser.add_argument("--platform", help="Comma-separated platform list")
    parser.add_argument("--count", "--max", dest="count", type=parse_non_negative_int, default=None)
    for platform in PLATFORMS:
        parser.add_argument(f"--{platform}-count", type=parse_non_negative_int)
        parser.add_argument(f"--{platform}-uid")
    parser.add_argument("--search", help="Single-platform keyword search")
    parser.add_argument("--resume-run", help="Explicitly continue this exact non-risk creator run ID using the same profile and original request; no automatic retry")
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--bilibili-complete", action="store_true")
    parser.add_argument("--xhs-complete", action="store_true")
    parser.add_argument("--xhs-comments", type=parse_non_negative_int, default=None)
    parser.add_argument("--platform-timeout", type=float, default=300.0)
    parser.add_argument("--execution-timeout", type=float)
    parser.add_argument("--format", choices=("json", "csv", "jsonl", "sqlite"), default="json")
    parser.add_argument("--cdp-url", help="Existing Chrome CDP base URL")
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
        metavar="cdp",
        default=None,
        help="Chrome CDP only; retired backend requests are refused",
    )
    parser.add_argument(
        "--count-mode",
        choices=("fixed", "best_effort"),
        default=None,
        help="fixed collects the requested count; best_effort is bounded by batches and the run deadline",
    )
    parser.add_argument("--run-deadline", type=parse_non_negative_int)
    parser.add_argument("--topic", help="Weibo topic name or official topic link")
    parser.add_argument("--targets-json", type=Path, help="Private 0600 JSON multi-target plan")
    parser.add_argument(
        "--screenshot-mode",
        choices=("off", "opened", "all"),
        default=None,
    )
    parser.add_argument(
        "--collect-as-much-as-safe",
        action="store_true",
        help="Explicitly authorize count zero within the engine safety cap",
    )
    parser.add_argument(
        "--no-feishu",
        action="store_true",
        default=True,
        help="Accepted for compatibility; this adapter always disables Feishu artifacts",
    )
    parser.add_argument("--json-summary", action="store_true")
    return parser



def _cdp_url(args: argparse.Namespace, profile: dict) -> str:
    return str(
        args.cdp_url
        or os.environ.get("MEDIA_MISSHER_CDP_URL")
        or profile.get("cdp_url")
        or DEFAULT_CDP_URL
    )


def _resolve_backend(explicit: str | None, profile: dict) -> str:
    """Validate the CDP-only entry even when an older runtime is installed."""

    for candidate in (explicit, profile.get("backend")):
        if candidate is None:
            continue
        if not isinstance(candidate, str):
            raise ConfigurationError("backend must be a string")
        value = candidate.strip().casefold()
        if not value:
            continue
        if value in {"browserskill", "computer_use"}:
            suffix = "computer-use" if value == "computer_use" else value
            raise ConfigurationError(f"backend-retired-{suffix}")
        if value != "cdp":
            raise ConfigurationError("only Chrome CDP is supported")
        return "cdp"
    return "cdp"



def _forward_plan(
    args: argparse.Namespace,
    *,
    layout,
    data_root,
    cdp_url: str,
    backend: str,
    profile_digest: str,
) -> int:
    """Hand a multi-target plan or a topic task to the runtime CLI's plan path."""

    argv = [
        str(layout.python),
        str(layout.current / "scripts" / "scrape_all.py"),
        "search" if args.search is not None else "creator",
        "--platform" if args.search is not None else "--platforms",
        "weibo" if args.topic else ",".join(_plan_platforms(args)),
        "--platform-timeout",
        str(args.platform_timeout),
        "--cdp-url",
        cdp_url,
        "--format",
        "json",
        "--output",
        str(data_root),
        "--no-feishu",
    ]
    if args.targets_json is None or args.backend is not None:
        argv.extend(("--backend", backend))
    if args.count is not None:
        argv.extend(("--count", str(args.count)))
    if args.count_mode is not None:
        argv.extend(("--count-mode", args.count_mode))
    argv.extend(("--profile-digest", profile_digest))
    if args.targets_json is None and args.topic is None:
        if args.search is not None:
            argv.extend(("--keyword", args.search))
        for platform in PLATFORMS:
            uid = getattr(args, f"{platform}_uid")
            count = getattr(args, f"{platform}_count")
            if uid is not None:
                argv.extend((f"--{platform}-uid", str(uid)))
            if count is not None:
                argv.extend((f"--{platform}-count", str(count)))
    if args.topic:
        argv.extend(("--topic", args.topic))
    if args.targets_json is not None:
        argv.extend(("--targets-json", str(args.targets_json)))
    if args.run_deadline is not None:
        argv.extend(("--run-deadline", str(args.run_deadline)))
    if args.allow_navigation:
        argv.append("--allow-navigation")
    if args.screenshot_mode is not None:
        argv.extend(("--screenshot-mode", args.screenshot_mode))
    if args.search is not None:
        if args.xhs_comments is not None:
            argv.extend(("--comments", str(args.xhs_comments)))
    else:
        if args.xhs_comments is not None:
            argv.extend(("--xhs-comments", str(args.xhs_comments)))
        for name in ("complete", "bilibili_complete", "xhs_complete"):
            if getattr(args, name):
                argv.append("--" + name.replace("_", "-"))
    if args.resume_run:
        argv.extend(("--resume-run", args.resume_run))
    environment = os.environ.copy()
    environment.update(
        {
            "MEDIA_MISSHER_HOME": str(layout.home),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    selected_profile = _profile_path(args.profile)
    if selected_profile is not None:
        environment["MEDIA_MISSHER_PROFILE_CONFIG"] = str(selected_profile)
    try:
        from media_missher_adapter import EngineCommand, execute_engine
        root = Path(data_root).expanduser().absolute()
        if any(path.is_symlink() for path in (root, *root.parents)):
            raise ConfigurationError("plan output directory is unsafe")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = root.stat()
        if stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.getuid():
            raise ConfigurationError("plan output directory must be private")
        logs = Path(tempfile.mkdtemp(prefix=".execution-", dir=root))
        progress_module = reporter = None
        if (layout.current / "media_missher_runtime" / "progress.py").is_file():
            from media_missher_progress import load_progress
            progress_module = load_progress(layout.current)
            reporter = progress_module.ProgressRecorder()
        result = execute_engine(
            EngineCommand(script=Path(argv[1]), argv=tuple(argv), environment=environment),
            timeout=args.execution_timeout or 900, run_dir=logs,
            progress_module=progress_module, reporter=reporter,
        )
        if result.stdout_path.stat().st_size > 1024 * 1024:
            raise ConfigurationError("plan summary exceeded its output budget")
        completed = subprocess.CompletedProcess(argv, result.returncode, result.stdout_path.read_bytes(), b"")
        summary = _plan_summary(completed)
    except (OSError, subprocess.SubprocessError) as exc:
        summary = _error_summary(ConfigurationError(f"plan execution failed: {type(exc).__name__}"))
    if args.json_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"collection: {summary['status']}")
        for error in summary.get("errors", []):
            print(f"  error: {error}")
    return 0 if summary["status"] == "success" else 1


def _private_plan_value(path: Path) -> dict:
    """Read only a bounded private regular file before resolving precedence."""
    path = path.expanduser().absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ConfigurationError("targets-json-invalid")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 2 * 1024 * 1024:
            raise ConfigurationError("targets-json-invalid")
        raw = os.read(fd, 2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ConfigurationError("targets-json-invalid")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:raise ValueError("duplicate key")
                result[key] = value
            return result
        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict):raise ValueError("plan object required")
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ConfigurationError("targets-json-invalid") from error
    finally:
        os.close(fd)


def _plan_platforms(args: argparse.Namespace) -> tuple[str, ...]:
    if args.targets_json is not None:
        try:
            payload = _private_plan_value(args.targets_json)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"invalid private plan file: {type(exc).__name__}") from exc
        targets = payload.get("targets") if isinstance(payload, dict) else None
        if not isinstance(targets, list) or not targets:
            raise ConfigurationError("the private plan file has no targets")
        ordered = [item.get("platform") for item in targets if isinstance(item, dict)]
        platforms = tuple(dict.fromkeys(item for item in ordered if isinstance(item, str)))
        if not platforms or any(p not in PLATFORMS and p != "x" for p in platforms):
            raise ConfigurationError("the private plan file has no platform")
        return platforms
    return parse_platforms(args.platform)


def _plan_summary(completed) -> dict:
    """Read the runtime CLI's single JSON summary without echoing raw output."""

    text = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
    if completed.returncode == 78 and not text:
        return {"status": "preflight-failed", "run_dir": None, "evidence": [], "errors": ["platform precondition failed"]}
    if completed.returncode == 75 and not text:
        return {"status": "risk-stopped", "run_dir": None, "evidence": [], "errors": ["risk stop"]}
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return _error_summary(ConfigurationError("the runtime plan summary was not usable JSON"))
    if not isinstance(value, dict):
        return _error_summary(ConfigurationError("the runtime plan summary was not an object"))
    value.setdefault("errors", [])
    return value



def _profile_path(cli_value: Path | None) -> Path | None:
    if cli_value is not None:
        return cli_value
    raw = os.environ.get("MEDIA_MISSHER_PROFILE_CONFIG")
    return Path(raw) if raw else None


def _error_summary(error: Exception) -> dict:
    return {
        "status": "preflight-failed",
        "run_dir": None,
        "evidence": [],
        "errors": [str(error)],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.browser_assist == "browserskill":
            # The deprecated mixed-control bridge is retired: it is not a second
            # browser owner. Refuse by name instead of reinterpreting the flag.
            raise ConfigurationError(
                "browser-assist-replaced: keep --browser-assist off; "
                "BrowserSkill collection is retired"
            )
        profile = read_profile(_profile_path(args.profile))
        layout = resolve_runtime_layout(environ=os.environ)
        data_root = resolve_data_root(args.data_root, environ=os.environ, profile=profile)
        plan_value = _private_plan_value(args.targets_json) if args.targets_json is not None else None
        plan_backend = plan_value.get("backend") if plan_value is not None else None
        backend = _resolve_backend(args.backend, {**profile, **({"backend": plan_backend} if plan_backend is not None else {})})
        if args.topic and args.search is not None:
            raise ConfigurationError("a topic task and --search are different requests")
        if args.targets_json is not None or args.topic is not None:
            if args.targets_json is not None:
                if args.format != "json" or args.collect_as_much_as_safe:
                    raise ConfigurationError("plan-option-unsupported; use plan budgets and separate offline export")
                if args.search is not None or args.topic is not None or any(getattr(args, f"{p}_uid") is not None or getattr(args, f"{p}_count") is not None for p in PLATFORMS):
                    raise ConfigurationError("plan-target-overrides-unsupported")
                if args.platform is not None and set(args.platform.split(",")) != set(_plan_platforms(args)):
                    raise ConfigurationError("plan-platforms-mismatch")
            # A multi-target plan and a topic task are executed by the runtime
            # CLI's plan path, which owns the frozen backend, the target queue,
            # the bounded batches and the run deadline. The adapter forwards the
            # exact private plan instead of reimplementing that path.
            return _forward_plan(
                args,
                layout=layout,
                data_root=data_root,
                cdp_url=str(_cdp_url(args, profile)),
                backend=backend,
                profile_digest=_profile_identity(layout, str(_cdp_url(args, profile)), profile),
            )
        envelope_requested = args.count_mode is not None or args.run_deadline is not None
        args.count = 15 if args.count is None else args.count
        args.count_mode = args.count_mode or "fixed"
        args.xhs_comments = 0 if args.xhs_comments is None else args.xhs_comments
        args.screenshot_mode = args.screenshot_mode or "off"
        platform_counts = {
            platform: value
            for platform in PLATFORMS
            if (value := getattr(args, f"{platform}_count")) is not None
        }
        configured_uids = profile.get("platform_uids", {})
        if configured_uids is None:
            configured_uids = {}
        if not isinstance(configured_uids, dict):
            raise ConfigurationError("profile platform_uids must be a JSON object")
        platform_selection = args.platform
        if args.topic is not None:
            # A topic task is Weibo-only and carries its own target; it must not
            # inherit an unrelated saved platform selection or the creator-UID
            # completeness rule.
            platform_selection = "weibo"
        elif platform_selection is None and args.search is None:
            if "active_platforms" in profile:
                active = profile["active_platforms"]
                if (not isinstance(active, list) or not active
                    or any(not isinstance(item, str) or item not in PLATFORMS for item in active)
                    or len(set(active)) != len(active)):
                    raise ConfigurationError("profile active_platforms must select unique configured platforms")
                platform_selection = ",".join(platform for platform in PLATFORMS if platform in active)
            else:
                configured = [platform for platform in PLATFORMS
                              if str(configured_uids.get(platform) or "").strip()
                              or getattr(args, f"{platform}_uid")]
                if configured:
                    platform_selection = ",".join(configured)
        platforms = parse_platforms(platform_selection)
        platform_uids = {
            platform: str(value)
            for platform, value in configured_uids.items()
            if platform in platforms and value is not None
        }
        for platform in PLATFORMS:
            value = getattr(args, f"{platform}_uid")
            if value is not None:
                platform_uids[platform] = value
        if args.search is None:
            missing_uids = [
                platform
                for platform in platforms
                if not str(platform_uids.get(platform, "")).strip()
            ]
            if missing_uids:
                raise ConfigurationError(
                    "creator collection requires a UID for every selected platform: "
                    + ", ".join(missing_uids)
                )
        backend = _resolve_backend(args.backend, profile)
        if args.topic and args.search is not None:
            raise ConfigurationError("a topic task and --search are different requests")
        if args.topic is not None:
            platform_uids.pop("weibo", None)
        request = CollectionRequest(
            platforms=platforms,
            count=args.count,
            platform_counts=platform_counts,
            platform_uids=platform_uids,
            search=args.search,
            complete=args.complete,
            bilibili_complete=args.bilibili_complete,
            xhs_complete=(
                args.xhs_complete
                or ("xhs" in platforms and args.search is None)
            ),
            xhs_comments=args.xhs_comments,
            platform_timeout=args.platform_timeout,
            output_format=args.format,
            collect_as_much_as_safe=args.collect_as_much_as_safe,
            allow_navigation=args.allow_navigation,
            browser_assist=args.browser_assist,
            screenshot_mode=args.screenshot_mode,
        )
        cdp_url = (
            args.cdp_url
            or os.environ.get("MEDIA_MISSHER_CDP_URL")
            or profile.get("cdp_url")
            or DEFAULT_CDP_URL
        )
        if envelope_requested:
            args.platform = ",".join(platforms)
            for platform, uid in platform_uids.items():
                setattr(args, f"{platform}_uid", uid)
            return _forward_plan(args, layout=layout, data_root=data_root,
                cdp_url=str(cdp_url), backend=backend,
                profile_digest=_profile_identity(layout, str(cdp_url), profile))
        summary = run_collection_request(
            request,
            layout=layout,
            data_root=data_root,
            cdp_url=str(cdp_url),
            execution_timeout=args.execution_timeout,
            resume_run=args.resume_run,
            profile_digest=_profile_identity(layout, str(cdp_url), profile),
        )
    except (ConfigurationError, OSError) as exc:
        summary = _error_summary(exc)

    if args.json_summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"collection: {summary['status']}")
        if summary.get("run_dir"):
            print(f"  run: {summary['run_dir']}")
        for path in summary.get("evidence", []):
            print(f"  evidence: {path}")
        for error in summary.get("errors", []):
            print(f"  error: {error}")
    return 0 if summary["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
