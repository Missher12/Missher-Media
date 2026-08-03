import json
from pathlib import Path

import pytest

from media_missher_adapter import (
    normalize_records,
    read_output,
    redact_for_summary,
    write_output,
)


FIXTURES = Path(__file__).parent / "fixtures"


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


def test_normalize_records_rejects_non_object_items():
    with pytest.raises(ValueError, match="JSON object"):
        normalize_records([{"platform": "xhs"}, "invalid"])


def test_redaction_removes_query_tokens_personal_ids_and_secret_canary(sample_records):
    sample_records[0]["author_id"] = "personal-author-id"
    sample_records[0]["environment"] = {"SECRET": "CANARY-SECRET"}
    redacted = redact_for_summary(
        sample_records,
        secrets={"CANARY-SECRET", "CANARY-TOKEN"},
    )
    rendered = json.dumps(redacted, ensure_ascii=False)
    assert "CANARY-SECRET" not in rendered
    assert "CANARY-TOKEN" not in rendered
    assert "xsec_token" not in rendered
    assert "author_id" not in rendered
    assert "?" not in redacted[0]["link"]


def test_write_output_rejects_unknown_format(tmp_path, sample_records):
    with pytest.raises(ValueError, match="format"):
        write_output(sample_records, "xlsx", tmp_path / "out")
