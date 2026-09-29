"""Offline, selection-driven export of already verified local run results.

导出只消费已验证的本地结果：它不会打开浏览器、不重新导航、也不补抓任何字段。
用户可以多次筛选重导出。用户要求尚未采集的字段时明确告知缺失，而不是把一次
导出悄悄变成新的采集。

保留的安全约定：

* 私有目录 ``0700``、文件 ``0600``、临时文件原子替换；
* 不覆盖同名文件（除非调用方显式要求）；
* Excel 公式前缀转义，ID 字段一律按文本写出，避免被表格软件当数字截断；
* 不同记录类别使用独立工作表或独立文件；
* 全部导出记录后端、来源 run、所选条件与真实记录数；
* 到达 Excel 的行数/单元格长度上限时分文件，不静默截断。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from .contracts import (
    HISTORICAL_BACKENDS as BACKEND_SET,
    EXPORT_FORMAT_SET,
    EXPORT_FORMATS,
    FIELD_QUALITY_SET,
    PLATFORM_SET,
    RECORD_KIND_SET,
    RECORD_KIND_POSTS,
    RECORD_KIND_TOPIC_PARTICIPANTS,
    RECORD_KIND_USER_PROFILES,
    SCHEMA_VERSION,
    default_field_groups,
)


#: Excel 的硬上限：单表最多 1,048,576 行（含表头），单元格文本最多 32,767 字符。
XLSX_MAX_ROWS = 1_048_576
XLSX_MAX_CELL_CHARS = 32_767
FORMULA_PREFIX = re.compile(r"^[=+\-@\t\r]")
_IDENTIFIER_FIELD = re.compile(
    r"(?:^|_)(?:id|ids|uid|uids)$|^(?:bvid|aweme_id|note_id|mblog_id|dynamic_id|native_id|tweet_id|author_id|conversation_id)$",
    re.IGNORECASE,
)


class ExportError(ValueError):
    """Raised when an export selection cannot be satisfied."""


class ExportOverwriteError(ExportError):
    """Raised instead of silently overwriting an existing output file."""


@dataclass(frozen=True, slots=True)
class ExportSelection:
    """用户对本次导出的明确选择。"""

    run_id: str
    record_kinds: tuple[str, ...]
    format: str = "xlsx"
    platforms: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    field_groups: tuple[str, ...] = ()
    where: Mapping[str, Any] = field(default_factory=dict)
    file_name: str | None = None
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or re.fullmatch(
            r"run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.run_id
        ) is None:
            raise ExportError("export requires an exact run id")
        if not self.record_kinds:
            raise ExportError("export requires at least one record kind")
        for kind in self.record_kinds:
            if kind not in RECORD_KIND_SET:
                raise ExportError(f"unsupported record kind: {kind}")
        if self.format not in EXPORT_FORMAT_SET:
            raise ExportError(f"unsupported export format: {self.format}")
        if not isinstance(self.where, Mapping):
            raise ExportError("export filters must be a mapping")
        if self.file_name is not None:
            name = Path(self.file_name).name
            if name != self.file_name or name in {"", ".", ".."}:
                raise ExportError("export file name must be a plain basename")
        if not isinstance(self.overwrite, bool):
            raise ExportError("overwrite must be an explicit boolean")

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.record_kinds))

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "record_kinds": list(self.kinds),
            "format": self.format,
            "platforms": list(self.platforms),
            "targets": list(self.targets),
            "topics": list(self.topics),
            "fields": list(self.fields),
            "field_groups": list(self.field_groups),
            "where": dict(self.where),
            "file_name": self.file_name,
            "overwrite": self.overwrite,
        }


@dataclass(slots=True)
class ExportResult:
    """导出结果：真实记录数与产出文件。"""

    selection: ExportSelection
    paths: tuple[str, ...]
    counts: Mapping[str, int]
    skipped_fields: tuple[str, ...] = ()
    rows: int = 0
    status: str = "ok"
    warnings: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.selection.run_id,
            "format": self.selection.format,
            "record_kinds": list(self.selection.kinds),
            "platforms": list(self.selection.platforms),
            "topics": list(self.selection.topics),
            "fields": list(self.selection.fields),
            "field_groups": list(self.selection.field_groups),
            "counts": dict(self.counts),
            "rows": self.rows,
            "paths": list(self.paths),
            "missing_fields": list(self.skipped_fields),
            "warnings": list(self.warnings),
            "emitted_at": datetime.now(UTC).isoformat(),
        }


# ---------------------------------------------------------------------------
# field selection
# ---------------------------------------------------------------------------


def group_fields(platform: str, groups: Sequence[str], *, kind: str | None = None) -> tuple[str, ...]:
    """把字段组展开成字段名；未知组名是明确错误而不是静默忽略。"""

    available = default_field_groups(platform)
    if kind == RECORD_KIND_USER_PROFILES:
        available = {
            "identity": ("platform", "type", "uid", "native_id", "link"),
            "profile": (
                "display_name",
                "handle",
                "avatar_url",
                "bio",
                "verified",
                "verify_text",
                "region",
                "website",
                "registered_at",
                "tags",
            ),
            "metrics": (
                "followers",
                "following",
                "posts",
                "followers_display",
                "following_display",
                "posts_display",
            ),
            "evidence": ("backend", "evidence_level", "observed_at", "source_url"),
        }
    elif kind == RECORD_KIND_TOPIC_PARTICIPANTS:
        available = {
            "identity": ("platform", "type", "topic", "uid", "link"),
            "relations": ("post_ids", "topics", "first_observed_at", "last_observed_at", "via_repost"),
            "evidence": ("backend", "evidence_level", "source_url"),
        }
    selected: list[str] = []
    unknown: list[str] = []
    for group in groups:
        fields = available.get(group)
        if fields is None:
            unknown.append(group)
            continue
        for name in fields:
            if name not in selected:
                selected.append(name)
    if unknown:
        raise ExportError(f"unknown field group: {', '.join(sorted(unknown))}")
    return tuple(selected)


def all_fields(platform: str, kind: str | None = None) -> tuple[str, ...]:
    """“全部可用字段”按记录的并集取，而不是逐个询问几十列。"""

    groups = default_field_groups(platform)
    if kind == RECORD_KIND_USER_PROFILES:
        groups = {
            "identity": ("platform", "type", "uid", "native_id", "link"),
            "profile": (),
            "metrics": (),
            "evidence": (),
        }
    names: list[str] = []
    for fields in groups.values():
        for name in fields:
            if name not in names:
                names.append(name)
    return tuple(names)


def missing_fields(
    records: Sequence[Mapping[str, Any]], requested: Sequence[str]
) -> tuple[str, ...]:
    """请求但所有记录都没有的字段。它们是“尚未采集”，不是空值。"""

    present = set()
    for record in records:
        present.update(key for key, value in record.items() if value is not None)
    return tuple(name for name in requested if name not in present)


# ---------------------------------------------------------------------------
# record projection
# ---------------------------------------------------------------------------


def record_kind(record: Mapping[str, Any]) -> str:
    kind = record.get("type")
    if kind in {"user_profile", "profile"}:
        return RECORD_KIND_USER_PROFILES
    if kind in {"topic_participant", "topic_participant_relation"}:
        return RECORD_KIND_TOPIC_PARTICIPANTS
    return RECORD_KIND_POSTS


def matches_filters(record: Mapping[str, Any], selection: ExportSelection) -> bool:
    if selection.platforms:
        platform = record.get("platform")
        if not isinstance(platform, str) or platform not in selection.platforms:
            return False
    if selection.topics:
        topic = record.get("topic")
        topics = record.get("topics")
        candidates = {topic} if isinstance(topic, str) else set()
        if isinstance(topics, (list, tuple)):
            candidates.update(item for item in topics if isinstance(item, str))
        if not candidates or not candidates.intersection(selection.topics):
            return False
    if selection.targets:
        from .best_effort import target_identities
        identity = record.get("target_identity")
        uid = record.get("uid") or record.get("author_id")
        handle = record.get("handle")
        candidates = {
            value
            for value in (identity, uid, handle)
            if isinstance(value, str) and value
        }
        candidates.update(target_identities(record))
        if not candidates.intersection(selection.targets):
            return False
    for key, expected in selection.where.items():
        actual = record.get(key)
        if isinstance(expected, (list, tuple)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def select_records(
    records: Iterable[Mapping[str, Any]],
    selection: ExportSelection,
) -> dict[str, list[dict[str, Any]]]:
    """按记录类别分组筛选；空筛选结果是正常结果，不是错误。"""

    grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in selection.kinds}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        kind = record_kind(record)
        if kind not in grouped:
            continue
        if not matches_filters(record, selection):
            continue
        grouped[kind].append(dict(record))
    return grouped


def project(
    records: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> list[dict[str, Any]]:
    if not fields:
        return [dict(record) for record in records]
    return [{name: record.get(name) for name in fields} for record in records]


def columns_for(
    records: Sequence[Mapping[str, Any]], requested: Sequence[str]
) -> list[str]:
    if requested:
        return list(requested)
    columns: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key in seen:
                continue
            seen.add(key)
            columns.append(key)
    return columns


# ---------------------------------------------------------------------------
# cell safety
# ---------------------------------------------------------------------------


def safe_cell(key: str, value: Any) -> Any:
    """Excel 公式转义 + ID 文本化 + 有限数值校验。"""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ExportError("record contains a non-finite number")
        if _IDENTIFIER_FIELD.search(key):
            return str(value)
        return value
    if isinstance(value, str):
        text = value
        if len(text) > XLSX_MAX_CELL_CHARS:
            text = text[: XLSX_MAX_CELL_CHARS - 1] + "…"
        return f"'{text}" if FORMULA_PREFIX.match(text) else text
    if isinstance(value, (list, tuple, dict)):
        return safe_cell(f"{key}_json", json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return str(value)


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------


def _prepare_parent(path: Path) -> None:
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not parent_existed:
        path.parent.chmod(0o700)


def _atomic_write_text(path: Path, write: Any) -> Path:
    _prepare_parent(path)
    if path.exists() and not path.is_file():
        raise ExportError("export destination is not a file")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    return path


def _exclusive_destination(path: Path, *, overwrite: bool) -> None:
    if os.path.lexists(path) and not overwrite:
        raise ExportOverwriteError(f"refusing to overwrite existing export: {path.name}")


def write_json(path: Path, payload: Any, *, overwrite: bool = False) -> Path:
    _exclusive_destination(path, overwrite=overwrite)
    return _atomic_write_text(
        path, lambda handle: handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
    )


def write_jsonl(
    path: Path, records: Sequence[Mapping[str, Any]], *, overwrite: bool = False
) -> Path:
    _exclusive_destination(path, overwrite=overwrite)
    def emit(handle: Any) -> None:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    return _atomic_write_text(path, emit)


def write_csv(
    path: Path,
    records: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    *,
    overwrite: bool = False,
) -> Path:
    _exclusive_destination(path, overwrite=overwrite)
    def emit(handle: Any) -> None:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({key: safe_cell(key, record.get(key)) for key in columns})
    return _atomic_write_text(path, emit)


def write_sqlite(
    path: Path,
    records: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    *,
    overwrite: bool = False,
) -> Path:
    _exclusive_destination(path, overwrite=overwrite)
    _prepare_parent(path)
    # The database file must not pre-exist as a zero-byte file: sqlite would
    # treat it as corrupt. Create it through sqlite itself.
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    if os.path.lexists(temporary):
        raise ExportError("temporary sqlite path already exists")
    try:
        connection = sqlite3.connect(temporary)
        try:
            quoted = ", ".join(f'"{column}" TEXT' for column in columns)
            schema = '"_position" INTEGER PRIMARY KEY'
            if quoted:
                schema = f"{schema}, {quoted}"
            connection.execute(f'CREATE TABLE "records" ({schema})')
            if columns:
                names = ", ".join(f'"{column}"' for column in columns)
                placeholders = ", ".join("?" for _ in columns)
                for position, record in enumerate(records):
                    values = [
                        json.dumps(safe_cell(column, record.get(column)), ensure_ascii=False, separators=(",", ":"))
                        if not isinstance(safe_cell(column, record.get(column)), str)
                        else safe_cell(column, record.get(column))
                        for column in columns
                    ]
                    connection.execute(
                        f'INSERT INTO "records" ("_position", {names}) VALUES (?, {placeholders})',
                        [position, *values],
                    )
            connection.commit()
        finally:
            connection.close()
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    return path


def pathlib_stem(path: Path) -> str:
    return path.stem


def write_xlsx(
    path: Path,
    sheets: Sequence[tuple[str, Sequence[Mapping[str, Any]], Sequence[str]]],
    *,
    overwrite: bool = False,
    max_rows_per_sheet: int = XLSX_MAX_ROWS,
) -> list[Path]:
    """写出 XLSX。

    One output *file* carries as many record-kind worksheets as fit, because each
    worksheet is its own row space. A worksheet that would reach the Excel row
    limit is continued in an extra file instead of being silently truncated.
    """

    try:
        import openpyxl  # type: ignore[import-not-found]
    except ImportError as error:  # pragma: no cover - exercised when openpyxl is absent
        raise ExportError("xlsx-export-requires-openpyxl") from error

    planned: list[tuple[Path, str, Sequence[Mapping[str, Any]], Sequence[str]]] = []
    file_index = 0
    for sheet_name, records, columns in sheets:
        if not records:
            # A header-only worksheet is how an empty selection stays visible.
            planned.append((path, sheet_name, records, columns))
            continue
        usable = max(1, max_rows_per_sheet - 1)
        chunks = [records[index : index + usable] for index in range(0, len(records), usable)]
        for chunk_index, chunk in enumerate(chunks):
            if chunk_index > 0:
                file_index += 1
            suffix = "" if file_index == 0 else f"-part{file_index + 1}"
            target = path if not suffix else path.with_name(f"{path.stem}{suffix}{path.suffix}")
            planned.append((target, sheet_name, chunk, columns))

    grouped: dict[Path, list[tuple[str, Sequence[Mapping[str, Any]], Sequence[str]]]] = {}
    for target, sheet_name, chunk, columns in planned:
        grouped.setdefault(target, []).append((sheet_name, chunk, columns))

    outputs: list[Path] = []
    for target, target_sheets in grouped.items():
        _exclusive_destination(target, overwrite=overwrite)
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
        try:
            workbook = openpyxl.Workbook()
            workbook.remove(workbook.active)
            for sheet_name, chunk, columns in target_sheets:
                sheet = workbook.create_sheet(title=(sheet_name[:31] or "Records"))
                sheet.append(list(columns))
                for record in chunk:
                    sheet.append([safe_cell(key, record.get(key)) for key in columns])
                for cell in sheet[1]:
                    cell.font = openpyxl.styles.Font(bold=True)
                sheet.freeze_panes = "A2"
            workbook.save(temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            target.chmod(0o600)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)
        outputs.append(target)
    return outputs


# ---------------------------------------------------------------------------
# top-level export
# ---------------------------------------------------------------------------


SHEET_TITLES = {
    RECORD_KIND_POSTS: "Posts",
    RECORD_KIND_TOPIC_PARTICIPANTS: "Topic Participants",
    RECORD_KIND_USER_PROFILES: "User Profiles",
}


def export_records(
    records: Sequence[Mapping[str, Any]],
    selection: ExportSelection,
    *,
    destination_root: Path,
    run_status: str = "complete",
    backend: str | None = None,
    observed_at: str | None = None,
) -> ExportResult:
    """把一次运行里已保存的记录按选择导出。

    ``records`` 必须是本地已验证记录。本函数不接触浏览器，也不因为字段缺失而
    触发补抓。
    """

    if backend is not None and backend not in BACKEND_SET:
        raise ExportError("unsupported backend")
    grouped = select_records(records, selection)
    counts = {kind: len(items) for kind, items in grouped.items()}
    requested_fields = list(selection.fields)
    if selection.field_groups:
        platforms = selection.platforms or tuple(dict.fromkeys(
            record["platform"] for items in grouped.values() for record in items
            if record.get("platform") in PLATFORM_SET
        ))
        grouped_fields: list[str] = []
        for group in selection.field_groups:
            supported_group = False
            for platform in platforms or ("weibo",):
                for kind in selection.kinds:
                    try:
                        names = group_fields(platform, (group,), kind=kind)
                    except ExportError:
                        continue
                    supported_group = True
                    for name in names:
                        if name not in grouped_fields:
                            grouped_fields.append(name)
            if not supported_group:
                raise ExportError(f"unknown field group: {group}")
        requested_fields = list(dict.fromkeys([*requested_fields, *grouped_fields]))
    every = [record for items in grouped.values() for record in items]
    absent = missing_fields(every, requested_fields) if requested_fields else ()
    warnings = ()
    if requested_fields and grouped.get(RECORD_KIND_TOPIC_PARTICIPANTS):
        if not {"topic", "uid", "post_id"}.issubset(requested_fields):
            warnings = ("partial-relation-projection",)

    root = Path(destination_root).expanduser().resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    root.chmod(0o700)
    stem = selection.file_name or f"{selection.run_id}-{selection.format}"
    if Path(stem).suffix.lower() != f".{selection.format}" and selection.format != "xlsx":
        stem = f"{stem}.{selection.format}"
    if selection.format == "xlsx" and Path(stem).suffix.lower() != ".xlsx":
        stem = f"{stem}.xlsx"
    base = root / stem
    if selection.format == "xlsx":
        # Records and the selection summary are different outputs; they must not
        # compete for the same file name.
        base = base.with_name(f"{base.stem}-records{base.suffix}")

    paths: list[Path] = []
    header = {
        "run_id": selection.run_id,
        "run_status": run_status,
        "backend": backend,
        "observed_at": observed_at,
        "platforms": ",".join(selection.platforms),
        "topics": ",".join(selection.topics),
        "record_kinds": ",".join(selection.kinds),
        "format": selection.format,
        "exported_at": datetime.now(UTC).isoformat(),
        "warnings": ",".join(warnings),
    }
    # An explicit field choice restricts every format, so the same selection
    # produces the same columns whichever format the user picks.
    projected = (
        [record for kind in selection.kinds for record in project(grouped[kind], requested_fields)]
        if requested_fields
        else [record for kind in selection.kinds for record in project(grouped[kind], ())]
    )
    payload_records = [
        {**record, "run_id": selection.run_id, "backend": backend or record.get("backend")}
        for record in projected
    ]
    if selection.format == "json":
        paths.append(
            write_json(
                base,
                {"export": header, "counts": counts, "records": payload_records},
                overwrite=selection.overwrite,
            )
        )
    elif selection.format == "jsonl":
        paths.append(write_jsonl(base, payload_records, overwrite=selection.overwrite))
    elif selection.format == "csv":
        paths.append(
            write_csv(
                base,
                payload_records,
                columns_for(payload_records, requested_fields),
                overwrite=selection.overwrite,
            )
        )
    elif selection.format == "sqlite":
        paths.append(
            write_sqlite(
                base,
                payload_records,
                columns_for(payload_records, requested_fields),
                overwrite=selection.overwrite,
            )
        )
    else:
        sheets = [
            (
                SHEET_TITLES.get(kind, kind),
                project(grouped[kind], requested_fields),
                columns_for(project(grouped[kind], requested_fields), requested_fields),
            )
            for kind in selection.kinds
            if grouped[kind]
        ]
        if not sheets:
            # 空筛选也要产出一份带表头的文件，这样用户能看到条件确实生效。
            sheets = [(SHEET_TITLES[selection.kinds[0]], [], list(requested_fields))]
        paths.extend(write_xlsx(base, sheets, overwrite=selection.overwrite))
        summary_path = base.with_name(f"{pathlib_stem(base)}-summary{base.suffix}")
        paths.extend(
            write_xlsx(
                summary_path,
                [("Export", [header], list(header))],
                overwrite=selection.overwrite,
            )
        )

    return ExportResult(
        selection=selection,
        paths=tuple(str(path) for path in paths),
        counts=counts,
        skipped_fields=absent,
        warnings=warnings,
        rows=len(payload_records),
        status="ok" if every or not counts else "empty",
    )


def describe_coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """展示可用字段覆盖情况，供导出前向用户说明。"""

    kinds: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        kind = record_kind(record)
        entry = kinds.setdefault(
            kind, {"records": 0, "platforms": set(), "fields": {}, "quality": {}}
        )
        entry["records"] += 1
        platform = record.get("platform")
        if isinstance(platform, str):
            entry["platforms"].add(platform)
        for key, value in record.items():
            stats = entry["fields"].setdefault(key, {"present": 0, "null": 0})
            if value is None:
                stats["null"] += 1
            else:
                stats["present"] += 1
        quality = record.get("field_quality")
        if isinstance(quality, Mapping):
            for key, value in quality.items():
                if value in FIELD_QUALITY_SET:
                    entry["quality"][value] = entry["quality"].get(value, 0) + 1
    return {
        kind: {
            "records": entry["records"],
            "platforms": sorted(entry["platforms"]),
            "fields": entry["fields"],
            "quality": entry["quality"],
        }
        for kind, entry in kinds.items()
    }


def export_formats() -> tuple[str, ...]:
    return EXPORT_FORMATS


__all__ = [
    "ExportError",
    "ExportOverwriteError",
    "ExportResult",
    "ExportSelection",
    "FORMULA_PREFIX",
    "SHEET_TITLES",
    "XLSX_MAX_CELL_CHARS",
    "XLSX_MAX_ROWS",
    "all_fields",
    "columns_for",
    "describe_coverage",
    "export_formats",
    "export_records",
    "group_fields",
    "matches_filters",
    "missing_fields",
    "project",
    "record_kind",
    "safe_cell",
    "select_records",
    "write_csv",
    "write_json",
    "write_jsonl",
    "write_sqlite",
    "write_xlsx",
]
