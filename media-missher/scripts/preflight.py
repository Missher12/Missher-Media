#!/usr/bin/env python3
"""Read-only preflight for an external Media@Missher runtime."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

from media_missher_adapter import (
    DEFAULT_CDP_URL,
    ConfigurationError,
    read_profile,
    resolve_engine_root,
    run_preflight,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the external Media@Missher runtime without collecting data."
    )
    parser.add_argument("--engine-root", type=Path, help="External Media@Missher skill root")
    parser.add_argument("--profile", type=Path, help="Private mode-0600 JSON profile")
    parser.add_argument("--live", action="store_true", help="Also probe the existing CDP endpoint")
    parser.add_argument(
        "--cdp-url",
        default=None,
        help="Existing Chrome CDP base URL (default: MEDIA_MISSHER_CDP_URL or localhost)",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-check timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Print a JSON report")
    return parser


def _profile_path(cli_value: Path | None) -> Path | None:
    if cli_value is not None:
        return cli_value
    raw = os.environ.get("MEDIA_MISSHER_PROFILE_CONFIG")
    return Path(raw) if raw else None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        profile = read_profile(_profile_path(args.profile))
        engine_root = resolve_engine_root(args.engine_root, environ=os.environ, profile=profile)
        cdp_url = (
            args.cdp_url
            or os.environ.get("MEDIA_MISSHER_CDP_URL")
            or profile.get("cdp_url")
            or DEFAULT_CDP_URL
        )
        report = run_preflight(
            engine_root,
            live=args.live,
            cdp_url=str(cdp_url),
            timeout=args.timeout,
        )
    except ConfigurationError as exc:
        report = {"status": "failed", "checks": {}, "errors": [str(exc)]}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"preflight: {report['status']}")
        for name, passed in report.get("checks", {}).items():
            print(f"  {name}: {'ok' if passed else 'failed'}")
        for error in report.get("errors", []):
            print(f"  error: {error}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
