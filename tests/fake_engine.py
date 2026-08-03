#!/usr/bin/env python3
"""Synthetic subprocess target for offline adapter tests."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")


def parser_for(script_name):
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", "--max", dest="count", type=int, default=1)
    parser.add_argument("--format", default="json")
    parser.add_argument("--output", type=Path, required=False)
    parser.add_argument("--platform")
    parser.add_argument("--platform-timeout", type=float, default=300)
    parser.add_argument("--xhs-comments", type=int, default=0)
    parser.add_argument("--comments", type=int, default=0)
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--bilibili-complete", action="store_true")
    parser.add_argument("--xhs-complete", action="store_true")
    parser.add_argument("--no-feishu", action="store_true")
    parser.add_argument("--search")
    for platform in PLATFORMS:
        parser.add_argument(f"--{platform}-count", type=int)
        parser.add_argument(f"--{platform}-uid")
    parser.set_defaults(script_name=script_name)
    return parser


def main():
    script_name = Path(sys.argv[0]).name
    args = parser_for(script_name).parse_args()
    mode = os.environ.get("MEDIA_MISSHER_FAKE_MODE", "ok")
    if mode == "sleep":
        time.sleep(float(os.environ.get("MEDIA_MISSHER_FAKE_SLEEP", "5")))
    if mode == "risk":
        print("risk signal 471: synthetic stop", file=sys.stderr)
        return 75
    if mode == "risk_wait":
        print("risk signal 471: synthetic stop", file=sys.stderr, flush=True)
        time.sleep(float(os.environ.get("MEDIA_MISSHER_FAKE_SLEEP", "5")))
        return 75
    if mode == "blocked_wait":
        print("account blocked: synthetic stop", file=sys.stderr, flush=True)
        time.sleep(float(os.environ.get("MEDIA_MISSHER_FAKE_SLEEP", "5")))
        return 75
    if mode == "fail":
        print("synthetic failure", file=sys.stderr)
        return 3
    if mode == "benign_log":
        print("synthetic unlocked state", file=sys.stderr, flush=True)

    output = args.output or Path.cwd()
    output.mkdir(parents=True, exist_ok=True)
    (output / "received_argv.txt").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
    if script_name == "scrape_all.py":
        platforms = tuple((args.platform or ",".join(PLATFORMS)).split(","))
    else:
        platforms = (script_name.removeprefix("scrape_").removesuffix(".py"),)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    native_id_keys = {
        "bilibili": "dynamic_id",
        "xhs": "note_id",
        "douyin": "aweme_id",
        "weibo": "mblog_id",
    }
    for platform in platforms:
        requested = getattr(args, f"{platform}_count", None)
        count = requested if requested is not None else args.count
        count = max(1, count)
        cap = os.environ.get("MEDIA_MISSHER_FAKE_COUNT_CAP")
        if cap is not None:
            count = min(count, max(0, int(cap)))
        records = [
            {
                "platform": platform,
                "id": f"synthetic-{platform}-{index}",
                native_id_keys[platform]: f"synthetic-{platform}-{index}",
                "title": "synthetic title",
                "link": f"https://example.invalid/{platform}/{index}",
                "date": "2026-01-01",
                "liked": 1,
                "comments": 2,
                "shares": 3,
                "collected": 4,
            }
            for index in range(count)
        ]
        (output / f"{platform}_{stamp}.json").write_text(
            json.dumps(records, ensure_ascii=False), encoding="utf-8"
        )
    print("synthetic collection complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
