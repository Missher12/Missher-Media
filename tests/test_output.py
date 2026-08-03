import json
import stat
from pathlib import Path

import pytest

from media_missher_adapter import (
    normalize_records,
    read_output,
    redact_for_summary,
    write_output,
)


FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_FIXTURES = tuple(sorted(FIXTURES.glob("*.json")))


def type_tree(value):
    if isinstance(value, dict):
        return {key: type_tree(child) for key, child in value.items()}
    if isinstance(value, list):
        return [type_tree(child) for child in value]
    return type(value)


@pytest.fixture
def sample_records():
    return json.loads((FIXTURES / "xhs_creator.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("format_name", ["json", "csv", "jsonl", "sqlite"])
def test_conversion_round_trip_preserves_normalized_records(
    tmp_path, sample_records, format_name
):
    path = write_output(sample_records, format_name, tmp_path / "out")
    assert path.is_absolute()
    assert read_output(path, format_name) == normalize_records(sample_records)


@pytest.mark.parametrize("format_name", ["json", "csv", "jsonl", "sqlite"])
def test_conversion_preserves_null_zero_and_nested_values(tmp_path, format_name):
    records = [
        {"platform": "xhs", "liked": None, "comments": 0, "nested": {"a": [1, None]}},
        {"platform": "xhs", "liked": 0, "comments": None},
    ]
    path = write_output(records, format_name, tmp_path / "nullable")
    converted = read_output(path, format_name)
    assert converted[0]["liked"] is None
    assert converted[0]["comments"] == 0
    assert converted[0]["nested"] == {"a": [1, None]}
    assert converted[1]["liked"] == 0
    assert converted[1]["comments"] is None


@pytest.mark.parametrize("format_name", ["json", "csv", "jsonl", "sqlite"])
def test_all_golden_outputs_preserve_field_types_and_native_id_order(tmp_path, format_name):
    expected = normalize_records(
        [
            record
            for fixture in GOLDEN_FIXTURES
            for record in json.loads(fixture.read_text(encoding="utf-8"))
        ]
    )
    path = write_output(expected, format_name, tmp_path / "golden-contract")
    converted = read_output(path, format_name)

    assert converted == expected
    assert type_tree(converted) == type_tree(expected)
    assert [
        record.get("dynamic_id")
        or record.get("bvid")
        or record.get("note_id")
        or record.get("aweme_id")
        or record.get("mblog_id")
        for record in converted
    ] == [
        record.get("dynamic_id")
        or record.get("bvid")
        or record.get("note_id")
        or record.get("aweme_id")
        or record.get("mblog_id")
        for record in expected
    ]
    assert any(value is None for record in converted for value in record.values())
    assert any(type(value) is int and value == 0 for record in converted for value in record.values())


def test_normalize_records_rejects_non_object_items():
    with pytest.raises(ValueError, match="JSON object"):
        normalize_records([{"platform": "xhs"}, "invalid"])


def test_redaction_removes_query_tokens_personal_ids_and_secret_canary(sample_records):
    sample_records[0]["author_id"] = "personal-author-id"
    sample_records[0]["environment"] = {"SECRET": "CANARY-SECRET"}
    sample_records[0]["cookie_header"] = "session=CANARY-COOKIE"
    sample_records[0]["api_key"] = "CANARY-API-KEY"
    sample_records[0]["sessionid"] = "CANARY-SESSION"
    redacted = redact_for_summary(
        sample_records,
        secrets={"CANARY-SECRET", "CANARY-TOKEN"},
    )
    rendered = json.dumps(redacted, ensure_ascii=False)
    assert "CANARY-SECRET" not in rendered
    assert "CANARY-TOKEN" not in rendered
    assert "xsec_token" not in rendered
    assert "author_id" not in rendered
    assert "cookie_header" not in rendered
    assert "api_key" not in rendered
    assert "sessionid" not in rendered
    assert "?" not in redacted[0]["link"]


def test_write_output_rejects_unknown_format(tmp_path, sample_records):
    with pytest.raises(ValueError, match="format"):
        write_output(sample_records, "xlsx", tmp_path / "out")


def test_csv_temporary_file_is_private_while_being_written(tmp_path, sample_records, monkeypatch):
    observed_modes = []
    original = __import__("csv").DictWriter.writeheader

    def inspect_mode(writer):
        temporary = next(tmp_path.glob(".*.tmp"))
        observed_modes.append(stat.S_IMODE(temporary.stat().st_mode))
        return original(writer)

    monkeypatch.setattr(__import__("csv").DictWriter, "writeheader", inspect_mode)
    write_output(sample_records, "csv", tmp_path / "private")
    assert observed_modes == [0o600]


def test_sqlite_temporary_file_is_private_when_connected(tmp_path, sample_records, monkeypatch):
    import media_missher_adapter

    observed_modes = []
    original = media_missher_adapter.sqlite3.connect

    def inspect_mode(database, *args, **kwargs):
        connection = original(database, *args, **kwargs)
        observed_modes.append(stat.S_IMODE(Path(database).stat().st_mode))
        return connection

    monkeypatch.setattr(media_missher_adapter.sqlite3, "connect", inspect_mode)
    write_output(sample_records, "sqlite", tmp_path / "private")
    assert observed_modes == [0o600]
