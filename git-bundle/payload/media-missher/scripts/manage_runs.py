#!/usr/bin/env python3
"""Inspect and re-export private runs without connecting to a browser."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from media_missher_adapter import ensure_runtime_on_path, resolve_runtime_layout
from media_missher_history import (
    HistoryError, compare_runs, export_run, export_selected_run, list_history,
    _ensure_exports_dir, _write_json_exclusive,
)

_FORMATS = ("xlsx", "csv", "json", "jsonl", "sqlite")
_RECORD_KINDS = ("posts", "topic_participants", "user_profiles")
_PLATFORMS = ("bilibili", "xhs", "douyin", "weibo", "x")


def _list_argument(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items or len(items) > 64 or len(set(items)) != len(items):
        raise argparse.ArgumentTypeError("must be a bounded, unique comma-separated list")
    return items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "export", "compare"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--format", choices=_FORMATS, default="json")
    # Selection-driven export. These only read saved local results: they never
    # open a browser and never fill a gap by collecting more.
    parser.add_argument("--record-kinds", type=_list_argument)
    parser.add_argument("--platforms", type=_list_argument)
    parser.add_argument("--topics", type=_list_argument)
    parser.add_argument("--targets", type=_list_argument)
    parser.add_argument("--fields", type=_list_argument)
    parser.add_argument("--field-groups", type=_list_argument)
    parser.add_argument("--filter-field")
    parser.add_argument("--filter-value")
    parser.add_argument("--file-name")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Bundles keep the core beside the scripts; installed Skills use the
    # configured shared runtime. Offline history only reads these locations.
    ensure_runtime_on_path()
    runtime = resolve_runtime_layout(environ=os.environ).current
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.append(str(runtime))
    try:
        if args.action == "list":
            runs = list_history(args.data_root)
            result = {"status": "ok", "summary": "\n".join(f"{run['run_id']} {run['status']} {json.dumps(run['counts'], sort_keys=True)}" for run in runs[-50:]) or "No saved runs.", "artifactPath": "", "metadataPath": ""}
        elif args.action == "export":
            if args.record_kinds:
                if any(kind not in _RECORD_KINDS for kind in args.record_kinds):
                    raise HistoryError("unknown record kind")
                if args.platforms and any(item not in _PLATFORMS for item in args.platforms):
                    raise HistoryError("unknown platform")
                value = export_selected_run(
                    args.data_root,
                    args.run_id,
                    record_kinds=args.record_kinds,
                    format_name=args.format,
                    platforms=args.platforms or (),
                    topics=args.topics or (),
                    targets=args.targets or (),
                    fields=args.fields or (),
                    field_groups=args.field_groups or (),
                    filter_field=args.filter_field,
                    filter_value=args.filter_value,
                    file_name=args.file_name,
                    overwrite=args.overwrite,
                )
                missing = value.get("missing_fields") or []
                summary = (
                    f"Selected historical export ({args.format}); rows {value['rows']}; "
                    f"counts {json.dumps(value['counts'], sort_keys=True)}; "
                    f"backend {value.get('source_backend', 'cdp')}"
                )
                if missing:
                    summary += f"; not collected in this run: {', '.join(missing)}"
                result = {
                    "status": "ok",
                    "summary": summary,
                    "artifactPath": value["output_path"],
                    "metadataPath": value["metadata_path"],
                }
            else:
                if args.format not in ("json", "csv", "jsonl", "sqlite"):
                    raise HistoryError("this format requires an explicit --record-kinds selection")
                value = export_run(args.data_root, args.run_id, args.format)
                result = {"status": "ok", "summary": f"Historical export; original observation times retained. {json.dumps(value['counts'], sort_keys=True)}", "artifactPath": value["output_path"], "metadataPath": value["metadata_path"]}
        else:
            import secrets
            value = compare_runs(args.data_root, args.before, args.after)
            root = _ensure_exports_dir(args.data_root.expanduser().absolute())
            path = _write_json_exclusive(root / f"comparison-{secrets.token_hex(8)}.json", value)
            result = {"status": "ok", "summary": f"Historical comparison: {len(value['records'])} content IDs; both observation times retained.", "artifactPath": str(path), "metadataPath": ""}
    except (HistoryError, OSError, ValueError):
        result = {"status": "failed", "summary": "history_evidence_unavailable_or_invalid", "artifactPath": "", "metadataPath": ""}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
