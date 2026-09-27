"""Selection-driven offline export: filters, formats, limits and safety."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from media_missher_runtime.contracts import (
    RECORD_KIND_POSTS,
    RECORD_KIND_TOPIC_PARTICIPANTS,
    RECORD_KIND_USER_PROFILES,
)
from media_missher_runtime.exporting import (
    ExportError,
    ExportOverwriteError,
    ExportSelection,
    XLSX_MAX_CELL_CHARS,
    all_fields,
    describe_coverage,
    export_records,
    group_fields,
    missing_fields,
    safe_cell,
    select_records,
    write_xlsx,
)


def _post(**overrides):
    record = {
        "platform": "x",
        "type": "post",
        "tweet_id": "1899999999999999999",
        "title": "hello",
        "link": "https://x.com/alice/status/1899999999999999999",
        "liked": 5,
        "comments": 1,
        "shares": 0,
        "author": "Alice",
        "handle": "alice",
        "topics": ["旅行"],
        "topic": "旅行",
        "target_identity": "x:search:latest:ai",
        "backend": "cdp",
        "evidence_level": "response",
        "observed_at": "2026-09-20T00:00:00+00:00",
        "field_quality": {"liked": "exact", "views": "unknown"},
    }
    record.update(overrides)
    return record


def _profile(**overrides):
    record = {
        "platform": "weibo",
        "type": "user_profile",
        "uid": "1001",
        "link": "https://weibo.com/u/1001",
        "display_name": "某用户",
        "followers": 12000.0,
        "followers_display": "1.2万",
        "observed_at": "2026-09-20T00:00:00+00:00",
    }
    record.update(overrides)
    return record


def _participant(**overrides):
    record = {
        "platform": "weibo",
        "type": "topic_participant",
        "uid": "1001",
        "topic": "旅行",
        "topics": ["旅行"],
        "post_ids": ["5001"],
        "link": "https://weibo.com/u/1001",
        "observed_at": "2026-09-20T00:00:00+00:00",
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def test_record_kinds_are_exported_to_separate_groups():
    selection = ExportSelection(
        run_id="run-1",
        record_kinds=(
            RECORD_KIND_POSTS,
            RECORD_KIND_TOPIC_PARTICIPANTS,
            RECORD_KIND_USER_PROFILES,
        ),
    )
    grouped = select_records([_post(), _profile(), _participant()], selection)
    assert [record["type"] for record in grouped[RECORD_KIND_POSTS]] == ["post"]
    assert [record["type"] for record in grouped[RECORD_KIND_USER_PROFILES]] == [
        "user_profile"
    ]
    assert [record["type"] for record in grouped[RECORD_KIND_TOPIC_PARTICIPANTS]] == [
        "topic_participant"
    ]


def test_platform_and_topic_filters_are_applied():
    selection = ExportSelection(
        run_id="run-1",
        record_kinds=(RECORD_KIND_POSTS,),
        platforms=("weibo",),
        topics=("摄影",),
    )
    grouped = select_records(
        [_post(), _post(platform="weibo", topic="旅行", topics=["旅行"]), _post(platform="weibo", topic="摄影", topics=["摄影"])],
        selection,
    )
    assert len(grouped[RECORD_KIND_POSTS]) == 1
    assert grouped[RECORD_KIND_POSTS][0]["topic"] == "摄影"


def test_target_filter_uses_stable_identity_not_the_display_label():
    selection = ExportSelection(
        run_id="run-1",
        record_kinds=(RECORD_KIND_POSTS,),
        targets=("x:search:latest:ai",),
    )
    grouped = select_records(
        [_post(), _post(target_identity="x:search:latest:other")],
        selection,
    )
    assert len(grouped[RECORD_KIND_POSTS]) == 1


def test_arbitrary_field_filters_are_supported():
    selection = ExportSelection(
        run_id="run-1",
        record_kinds=(RECORD_KIND_POSTS,),
        where={"backend": "browserskill"},
    )
    grouped = select_records([_post(), _post(backend="browserskill")], selection)
    assert [record["backend"] for record in grouped[RECORD_KIND_POSTS]] == [
        "browserskill"
    ]


def test_empty_filter_is_a_valid_empty_export_not_an_error(tmp_path: Path):
    selection = ExportSelection(
        run_id="run-1",
        record_kinds=(RECORD_KIND_POSTS,),
        platforms=("douyin",),
        format="json",
    )
    result = export_records([_post()], selection, destination_root=tmp_path)
    assert result.rows == 0
    payload = json.loads(Path(result.paths[0]).read_text(encoding="utf-8"))
    assert payload["records"] == []
    assert payload["counts"]["posts"] == 0
    assert result.status == "empty"


def test_unknown_record_kind_and_format_are_refused():
    with pytest.raises(ExportError):
        ExportSelection(run_id="run-1", record_kinds=("likes",))
    with pytest.raises(ExportError):
        ExportSelection(run_id="run-1", record_kinds=(RECORD_KIND_POSTS,), format="pdf")
    with pytest.raises(ExportError):
        ExportSelection(run_id="not-a-run", record_kinds=(RECORD_KIND_POSTS,))


def test_file_name_must_be_a_plain_basename():
    with pytest.raises(ExportError):
        ExportSelection(
            run_id="run-1", record_kinds=(RECORD_KIND_POSTS,), file_name="../escape.json"
        )


def test_field_groups_expand_without_asking_for_dozens_of_columns():
    fields = group_fields("x", ("identity", "metrics"))
    assert "tweet_id" in fields
    assert "liked" in fields
    assert "views" in fields
    with pytest.raises(ExportError):
        group_fields("x", ("not-a-group",))


def test_all_fields_covers_the_platform_union():
    fields = all_fields("x")
    for name in ("tweet_id", "text", "liked", "quotes", "views", "bookmarks"):
        assert name in fields


def test_requested_but_uncollected_fields_are_reported_as_missing():
    absent = missing_fields([_post()], ("tweet_id", "media_width"))
    assert absent == ("media_width",)


def test_coverage_summary_keeps_present_and_null_counts():
    coverage = describe_coverage([_post(), _post(liked=None)])
    posts = coverage[RECORD_KIND_POSTS]
    assert posts["records"] == 2
    assert posts["platforms"] == ["x"]
    assert posts["fields"]["liked"] == {"present": 1, "null": 1}


# ---------------------------------------------------------------------------
# cell safety
# ---------------------------------------------------------------------------


def test_formula_prefixes_are_escaped():
    assert safe_cell("title", "=1+1") == "'=1+1"
    assert safe_cell("title", "+cmd") == "'+cmd"
    assert safe_cell("title", "-2") == "'-2"
    assert safe_cell("title", "@x") == "'@x"
    assert safe_cell("title", "plain") == "plain"


def test_identifier_columns_are_written_as_text():
    assert safe_cell("tweet_id", 1899999999999999999) == "1899999999999999999"
    assert isinstance(safe_cell("uid", 1001), str)
    assert safe_cell("liked", 5) == 5


def test_non_finite_numbers_are_refused():
    with pytest.raises(ExportError):
        safe_cell("liked", float("inf"))


def test_over_long_cell_text_is_reduced_not_silently_dropped():
    value = safe_cell("text", "a" * (XLSX_MAX_CELL_CHARS + 50))
    assert isinstance(value, str)
    assert len(value) == XLSX_MAX_CELL_CHARS


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------


def test_json_export_records_the_selection_and_counts(tmp_path: Path):
    selection = ExportSelection(
        run_id="run-1",
        record_kinds=(RECORD_KIND_POSTS,),
        format="json",
        platforms=("x",),
        fields=("tweet_id", "liked"),
    )
    result = export_records(
        [_post()], selection, destination_root=tmp_path, backend="cdp", run_status="partial"
    )
    payload = json.loads(Path(result.paths[0]).read_text(encoding="utf-8"))
    assert payload["export"]["run_id"] == "run-1"
    assert payload["export"]["backend"] == "cdp"
    assert payload["export"]["run_status"] == "partial"
    assert payload["counts"] == {"posts": 1}
    assert payload["records"][0]["tweet_id"] == "1899999999999999999"
    assert "link" not in payload["records"][0]


def test_csv_and_jsonl_and_sqlite_are_available(tmp_path: Path):
    sqlite_path = None
    for fmt, suffix in (("csv", ".csv"), ("jsonl", ".jsonl"), ("sqlite", ".sqlite")):
        selection = ExportSelection(
            run_id=f"run-{fmt}", record_kinds=(RECORD_KIND_POSTS,), format=fmt
        )
        result = export_records([_post()], selection, destination_root=tmp_path)
        path = Path(result.paths[0])
        assert path.suffix == suffix
        assert path.stat().st_mode & 0o777 == 0o600
        if fmt == "sqlite":
            sqlite_path = path
    connection = sqlite3.connect(sqlite_path)
    try:
        rows = connection.execute('SELECT "tweet_id" FROM "records"').fetchall()
    finally:
        connection.close()
    assert rows == [("1899999999999999999",)]


def test_existing_export_is_not_overwritten_by_default(tmp_path: Path):
    selection = ExportSelection(
        run_id="run-1", record_kinds=(RECORD_KIND_POSTS,), format="json"
    )
    export_records([_post()], selection, destination_root=tmp_path)
    with pytest.raises(ExportOverwriteError):
        export_records([_post()], selection, destination_root=tmp_path)
    explicit = ExportSelection(
        run_id="run-1", record_kinds=(RECORD_KIND_POSTS,), format="json", overwrite=True
    )
    assert export_records([_post()], explicit, destination_root=tmp_path).rows == 1


def test_export_directory_is_private(tmp_path: Path):
    target = tmp_path / "private"
    selection = ExportSelection(
        run_id="run-1", record_kinds=(RECORD_KIND_POSTS,), format="json"
    )
    export_records([_post()], selection, destination_root=target)
    assert target.stat().st_mode & 0o777 == 0o700


# ---------------------------------------------------------------------------
# xlsx
# ---------------------------------------------------------------------------


def test_xlsx_has_one_sheet_per_record_kind(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    selection = ExportSelection(
        run_id="run-1",
        record_kinds=(RECORD_KIND_POSTS, RECORD_KIND_USER_PROFILES),
        format="xlsx",
    )
    result = export_records([_post(), _profile()], selection, destination_root=tmp_path)
    workbook = openpyxl.load_workbook(result.paths[0])
    assert "Posts" in workbook.sheetnames
    assert "User Profiles" in workbook.sheetnames


def test_xlsx_identifier_cells_stay_text(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    selection = ExportSelection(
        run_id="run-1", record_kinds=(RECORD_KIND_POSTS,), format="xlsx"
    )
    result = export_records([_post()], selection, destination_root=tmp_path)
    workbook = openpyxl.load_workbook(result.paths[0])
    sheet = workbook["Posts"]
    header = [cell.value for cell in sheet[1]]
    row = [cell.value for cell in sheet[2]]
    record = dict(zip(header, row))
    assert record["tweet_id"] == "1899999999999999999"
    assert isinstance(record["tweet_id"], str)


def test_xlsx_splits_into_extra_files_instead_of_truncating(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    records = [_post(tweet_id=str(1000 + index)) for index in range(23)]
    target = tmp_path / "out.xlsx"
    paths = write_xlsx(
        target,
        [("Posts", records, ["tweet_id"])],
        max_rows_per_sheet=11,
    )
    assert len(paths) == 3
    total = 0
    for path in paths:
        workbook = openpyxl.load_workbook(path)
        total += workbook["Posts"].max_row - 1
    assert total == 23


def test_xlsx_empty_selection_still_produces_a_header_file(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    selection = ExportSelection(
        run_id="run-1",
        record_kinds=(RECORD_KIND_POSTS,),
        format="xlsx",
        fields=("tweet_id", "liked"),
    )
    result = export_records([], selection, destination_root=tmp_path)
    workbook = openpyxl.load_workbook(result.paths[0])
    header = [cell.value for cell in workbook["Posts"][1]]
    assert header == ["tweet_id", "liked"]


def test_offline_export_never_needs_a_browser():
    """The exporter only reads records: it has no browser or navigation import."""

    import media_missher_runtime.exporting as exporting

    source = Path(exporting.__file__).read_text(encoding="utf-8")
    for forbidden in ("playwright", "browser_skill", "bsk_session", "subprocess"):
        assert forbidden not in source
