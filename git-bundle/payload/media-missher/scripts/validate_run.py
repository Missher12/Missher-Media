#!/usr/bin/env python3
"""Validate and optionally convert one Media@Missher run directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from media_missher_adapter import (
    CollectionRequest,
    ConfigurationError,
    discover_current_json,
    parse_non_negative_int,
    parse_platforms,
    validate_run,
    write_output,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate only JSON evidence created by one current Media@Missher run."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--started-epoch", type=float, required=True)
    parser.add_argument("--platform", required=True, help="One or more comma-separated platforms")
    parser.add_argument("--expected-count", type=parse_non_negative_int, required=True)
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--bilibili-complete", action="store_true")
    parser.add_argument("--xhs-complete", action="store_true")
    parser.add_argument(
        "--xhs-comments",
        type=parse_non_negative_int,
        default=0,
        help="Require this many bounded Xiaohongshu comments in complete evidence.",
    )
    parser.add_argument(
        "--screenshot-mode",
        choices=("off", "opened", "all"),
        default="off",
    )
    parser.add_argument("--format", choices=("json", "csv", "jsonl", "sqlite"), default="json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json-summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.started_epoch < 0:
        parser.error("--started-epoch must be non-negative")
    if args.format != "json" and args.output is None:
        parser.error("--output is required for non-JSON conversion")
    started_ns = int(args.started_epoch * 1_000_000_000)
    try:
        request = CollectionRequest(
            platforms=parse_platforms(args.platform),
            count=args.expected_count,
            complete=args.complete,
            bilibili_complete=args.bilibili_complete,
            xhs_complete=args.xhs_complete,
            xhs_comments=args.xhs_comments,
            collect_as_much_as_safe=args.expected_count == 0,
            screenshot_mode=args.screenshot_mode,
            allow_navigation=args.screenshot_mode != "off",
        )
        paths = discover_current_json(args.run_dir, started_ns=started_ns)
        result = validate_run(paths, request, started_ns)
        output_path = None
        if args.output is not None and result["records"]:
            output_path = write_output(result["records"], args.format, args.output)
    except (ConfigurationError, OSError, ValueError) as exc:
        result = {
            "status": "failed",
            "counts": {},
            "records": [],
            "evidence": [],
            "diagnostics": [],
            "samples": [],
            "errors": [str(exc)],
        }
        output_path = None

    printable = {key: value for key, value in result.items() if key != "records"}
    if output_path is not None:
        printable["output"] = str(output_path)
    if args.json_summary:
        print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"validation: {printable['status']}")
        for platform, count in printable.get("counts", {}).items():
            print(f"  {platform}: {count}")
        for path in printable.get("evidence", []):
            print(f"  evidence: {path}")
        if output_path is not None:
            print(f"  output: {output_path}")
        for sample in printable["samples"]:
            print(f"  sample: {json.dumps(sample, ensure_ascii=False, sort_keys=True)}")
        for error in printable.get("errors", []):
            print(f"  error: {error}")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
