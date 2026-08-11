from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[1]
RUNTIME_FIXTURES = REPO / "tests" / "runtime_fixtures"
RUNTIME_SCRIPTS = REPO / "runtime" / "scripts"
PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")
NATIVE_IDS = {
    "bilibili": "dynamic_id",
    "xhs": "note_id",
    "douyin": "aweme_id",
    "weibo": "mblog_id",
}


@dataclass(frozen=True)
class CompatibilityCase:
    platform: str
    mode: str

    @property
    def fixture_mode(self) -> str:
        return "complete" if self.mode == "complete" else self.mode


CASES = tuple(
    CompatibilityCase(platform, mode)
    for platform in PLATFORMS
    for mode in ("creator", "search")
) + (
    CompatibilityCase("bilibili", "complete"),
    CompatibilityCase("xhs", "complete"),
)


FIXTURE_BROWSER_PROVIDER = r'''
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from media_missher_runtime import cli
from media_missher_runtime.platforms import bilibili

NATIVE_IDS = {
    "bilibili": "dynamic_id",
    "xhs": "note_id",
    "douyin": "aweme_id",
    "weibo": "mblog_id",
}


class FixtureBrowser:
    allow_navigation = False

    def __init__(self):
        self.root = Path(os.environ["MEDIA_MISSHER_FIXTURE_ROOT"])

    @classmethod
    async def connect(cls, *_args, **_kwargs):
        return cls()

    def require_page(self, platform):
        if platform not in NATIVE_IDS:
            raise AssertionError("fixture provider received an unknown platform")

    async def require_authenticated_page(self, platform):
        self.require_page(platform)
        return object()

    async def close(self):
        return None

    async def collect(self, request):
        outcome = os.environ.get("MEDIA_MISSHER_FIXTURE_OUTCOME", "ok")
        if outcome == "risk":
            raise bilibili.CollectionStopped("synthetic fixture risk")
        if outcome == "failed":
            raise RuntimeError("synthetic fixture failure")
        mode = "search" if request.keyword is not None else "complete" if request.complete else "creator"
        payload = json.loads((self.root / f"{request.platform}_{mode}.json").read_text(encoding="utf-8"))
        records = []
        seen = set()
        for page in payload["pages"]:
            for item in page["records"]:
                native_id = item["native_id"]
                if native_id in seen:
                    continue
                seen.add(native_id)
                record = {
                    "platform": request.platform,
                    NATIVE_IDS[request.platform]: native_id,
                    "id": native_id,
                    "native_id": native_id,
                    "link": f"https://example.invalid/{request.platform}/{mode}/{native_id}",
                    "author": item["author"],
                    "media": item["media"],
                    "observed_at": datetime.now(UTC).isoformat(),
                }
                if "metric_zero" in item:
                    record["metric_zero"] = item["metric_zero"]
                if "nullable" in item:
                    record["nullable"] = item["nullable"]
                if request.keyword is not None:
                    record["search_keyword"] = request.keyword
                if request.complete:
                    detail = item.get("detail")
                    record["detail"] = detail
                    record["detail_completed"] = detail is not None
                    record["complete"] = detail is not None
                    record["missing_fields"] = [] if detail is not None else ["detail"]
                records.append(record)
                if request.target_count is not None and len(records) >= request.target_count:
                    break
            if request.target_count is not None and len(records) >= request.target_count:
                break
        if outcome == "shortfall":
            return records[:1]
        return records


async def collect(request, browser):
    return await browser.collect(request)


cli.BrowserSession = FixtureBrowser
cli._COLLECTORS = {platform: (collect, collect) for platform in NATIVE_IDS}
'''


FIXTURE_ORACLE = r'''
import json
import sys
from pathlib import Path

NATIVE_IDS = {
    "bilibili": "dynamic_id",
    "xhs": "note_id",
    "douyin": "aweme_id",
    "weibo": "mblog_id",
}

root = Path(sys.argv[1])
platform = sys.argv[2]
mode = sys.argv[3]
payload = json.loads((root / f"{platform}_{mode}.json").read_text(encoding="utf-8"))
seen = set()
records = []
for page in payload["pages"]:
    for item in page["records"]:
        native_id = item["native_id"]
        if native_id in seen:
            continue
        seen.add(native_id)
        record = {
            "platform": platform,
            NATIVE_IDS[platform]: native_id,
            "id": native_id,
            "native_id": native_id,
            "link": f"https://example.invalid/{platform}/{mode}/{native_id}",
            "author": item["author"],
            "media": item["media"],
            "observed_at": "<observed-at>",
        }
        if "metric_zero" in item:
            record["metric_zero"] = item["metric_zero"]
        if "nullable" in item:
            record["nullable"] = item["nullable"]
        if mode == "search":
            record["search_keyword"] = "synthetic topic"
        if mode == "complete":
            detail = item.get("detail")
            record["detail"] = detail
            record["detail_completed"] = detail is not None
            record["complete"] = detail is not None
            record["missing_fields"] = [] if detail is not None else ["detail"]
        records.append(record)
print(json.dumps(records, ensure_ascii=False))
'''


def _run_oracle(case: CompatibilityCase, tmp_path: Path) -> list[dict[str, Any]]:
    """Run the committed fixture contract without importing implementation modules."""
    oracle = tmp_path / "fixture_oracle.py"
    oracle.write_text(FIXTURE_ORACLE, encoding="utf-8")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(oracle),
            str(RUNTIME_FIXTURES),
            case.platform,
            case.fixture_mode,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        cwd=REPO,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _type_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _type_tree(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_type_tree(child) for child in value]
    return type(value).__name__


def _normalized_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    observed_at = normalized.get("observed_at")
    assert isinstance(observed_at, str)
    datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    normalized["observed_at"] = "<observed-at>"
    return normalized


def _provider_environment(provider_root: Path, outcome: str = "ok") -> dict[str, str]:
    environment = os.environ.copy()
    pythonpath = [str(provider_root), str(REPO / "runtime"), str(REPO)]
    if environment.get("PYTHONPATH"):
        pythonpath.append(environment["PYTHONPATH"])
    environment.update(
        {
            "MEDIA_MISSHER_FIXTURE_ROOT": str(RUNTIME_FIXTURES),
            "MEDIA_MISSHER_FIXTURE_OUTCOME": outcome,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(pythonpath),
        }
    )
    return environment


def _run_cli(
    case: CompatibilityCase,
    tmp_path: Path,
    *,
    outcome: str = "ok",
    count: int = 2,
) -> tuple[subprocess.CompletedProcess[str], Path, dict[str, Any], list[dict[str, Any]]]:
    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    (provider_root / "sitecustomize.py").write_text(
        FIXTURE_BROWSER_PROVIDER, encoding="utf-8"
    )
    output = tmp_path / "output"
    argv = [
        sys.executable,
        str(RUNTIME_SCRIPTS / f"scrape_{case.platform}.py"),
        case.mode if case.mode != "complete" else "creator",
    ]
    if case.mode == "search":
        argv.extend(("--keyword", "synthetic topic"))
    else:
        argv.extend(("--uid", "synthetic-creator"))
    if case.mode == "complete":
        argv.append("--complete")
    argv.extend(("--count", str(count), "--output-dir", str(output)))
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=REPO,
        env=_provider_environment(provider_root, outcome),
    )
    run_dirs = list(output.glob("run-*"))
    assert len(run_dirs) == 1, completed.stderr
    run_dir = run_dirs[0]
    manifest_path = run_dir / "manifest.json"
    assert manifest_path.exists(), completed.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = run_dir / f"{case.platform}.json"
    records = json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else []
    return completed, run_dir, manifest, records


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.platform}-{case.mode}")
def test_runtime_cli_matches_committed_synthetic_contract(
    case: CompatibilityCase, tmp_path: Path
) -> None:
    completed, run_dir, manifest, records = _run_cli(case, tmp_path)
    expected = _run_oracle(case, tmp_path)
    normalized = [_normalized_record(record) for record in records]

    assert normalized == expected
    assert _type_tree(normalized) == _type_tree(expected)
    assert len(normalized) == 2
    assert [record[NATIVE_IDS[case.platform]] for record in normalized] == [
        "synthetic-a",
        "synthetic-b",
    ]
    assert normalized[1]["metric_zero"] == 0
    assert type(normalized[1]["metric_zero"]) is int
    assert normalized[1]["nullable"] is None
    assert run_dir.name.startswith("run-")
    assert set(manifest["paths"]) == (
        {case.platform, "xhs_report", "xhs_checkpoint"}
        if case.platform == "xhs"
        else {case.platform}
    )
    assert manifest["counts"] == {case.platform: 2}
    if case.mode == "complete":
        assert completed.returncode == 1
        assert [record["complete"] for record in normalized] == [True, False]
        assert manifest["platforms"] == {case.platform: "incomplete"}
        assert manifest["status"] == "failed"
    else:
        assert completed.returncode == 0
        assert manifest["platforms"] == {case.platform: "complete"}
        assert manifest["status"] == "complete"


@pytest.mark.parametrize(
    ("outcome", "expected_code", "expected_platform", "expected_status"),
    (
        ("shortfall", 1, "shortfall", "failed"),
        ("failed", 1, "failed", "failed"),
        ("risk", 75, "risk-stopped", "risk-stopped"),
    ),
)
def test_runtime_cli_preserves_normalized_failure_statuses(
    outcome: str,
    expected_code: int,
    expected_platform: str,
    expected_status: str,
    tmp_path: Path,
) -> None:
    case = CompatibilityCase("bilibili", "creator")
    completed, run_dir, manifest, records = _run_cli(
        case, tmp_path, outcome=outcome, count=2
    )

    assert completed.returncode == expected_code
    assert run_dir.name.startswith("run-")
    assert manifest["platforms"] == {"bilibili": expected_platform}
    assert manifest["status"] == expected_status
    assert manifest["counts"] == {"bilibili": 1 if outcome == "shortfall" else 0}
    if outcome == "shortfall":
        assert [record["dynamic_id"] for record in records] == ["synthetic-a"]
    else:
        assert records == []
