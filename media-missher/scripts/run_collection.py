#!/usr/bin/env python3
"""Safely orchestrate one external Media@Missher collection process."""

from __future__ import annotations

import argparse
import json
import os
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
    resolve_engine_root,
    run_collection_request,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect through an external Media@Missher engine with private JSON staging."
    )
    parser.add_argument("--engine-root", type=Path, help="External Media@Missher skill root")
    parser.add_argument("--profile", type=Path, help="Private mode-0600 JSON profile")
    parser.add_argument("--data-root", "--output", dest="data_root", type=Path)
    parser.add_argument("--platform", help="Comma-separated platform list")
    parser.add_argument("--count", "--max", dest="count", type=parse_non_negative_int, default=15)
    for platform in PLATFORMS:
        parser.add_argument(f"--{platform}-count", type=parse_non_negative_int)
        parser.add_argument(f"--{platform}-uid")
    parser.add_argument("--search", help="Single-platform keyword search")
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--bilibili-complete", action="store_true")
    parser.add_argument("--xhs-complete", action="store_true")
    parser.add_argument("--xhs-comments", type=parse_non_negative_int, default=0)
    parser.add_argument("--platform-timeout", type=float, default=300.0)
    parser.add_argument("--execution-timeout", type=float)
    parser.add_argument("--format", choices=("json", "csv", "jsonl", "sqlite"), default="json")
    parser.add_argument("--cdp-url", help="Existing Chrome CDP base URL")
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
        profile = read_profile(_profile_path(args.profile))
        engine_root = resolve_engine_root(args.engine_root, environ=os.environ, profile=profile)
        data_root = resolve_data_root(args.data_root, environ=os.environ, profile=profile)
        platforms = parse_platforms(args.platform)
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
        platform_uids = {
            platform: str(value)
            for platform, value in configured_uids.items()
            if platform in platforms and value is not None
        }
        for platform in PLATFORMS:
            value = getattr(args, f"{platform}_uid")
            if value is not None:
                platform_uids[platform] = value
        request = CollectionRequest(
            platforms=platforms,
            count=args.count,
            platform_counts=platform_counts,
            platform_uids=platform_uids,
            search=args.search,
            complete=args.complete,
            bilibili_complete=args.bilibili_complete,
            xhs_complete=args.xhs_complete,
            xhs_comments=args.xhs_comments,
            platform_timeout=args.platform_timeout,
            output_format=args.format,
            collect_as_much_as_safe=args.collect_as_much_as_safe,
        )
        cdp_url = (
            args.cdp_url
            or os.environ.get("MEDIA_MISSHER_CDP_URL")
            or profile.get("cdp_url")
            or DEFAULT_CDP_URL
        )
        summary = run_collection_request(
            request,
            engine_root=engine_root,
            data_root=data_root,
            cdp_url=str(cdp_url),
            execution_timeout=args.execution_timeout,
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
