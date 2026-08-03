# Media@Missher Codex Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently authored Codex skill that preserves the installed Media@Missher four-platform collection contract through a safe subprocess adapter without copying or modifying the installed engine.

**Architecture:** Install a thin `media-missher/` skill containing standard-library Python adapters and progressively disclosed references. Resolve the existing OpenClaw engine as an external runtime, validate requests before launching it, force JSON staging with no Feishu artifacts, and perform adapter-owned validation and format conversion. Keep tests at repository level with a synthetic fake engine and no live network by default.

**Tech Stack:** Python 3.11 standard library, pytest for repository tests, Codex skill-creator scripts, subprocess-based integration with the existing engine.

---

## File Map

- `media-missher/SKILL.md`: concise agent contract and reference router.
- `media-missher/agents/openai.yaml`: generated Codex UI metadata.
- `media-missher/scripts/media_missher_adapter.py`: shared configuration, validation, command construction, run-directory, output discovery, conversion, and redaction primitives.
- `media-missher/scripts/preflight.py`: read-only runtime and optional live CDP checks.
- `media-missher/scripts/run_collection.py`: safe child-process orchestration and structured run summary.
- `media-missher/scripts/validate_run.py`: validate an existing run and convert output formats.
- `media-missher/references/*.md`: commands, configuration, licensing boundary, troubleshooting, and validation details.
- `tests/fake_engine.py`: synthetic subprocess target implementing the external CLI contract without network.
- `tests/conftest.py`: isolated filesystem and network-denial fixtures.
- `tests/test_*.py`: CLI, configuration, runner, output, security, validation, and packaging tests.
- `PROJECT_CONTEXT.md`: durable project goal, architecture, progress, and known constraints.

### Task 1: Create the standard skill scaffold and packaging gate

**Files:**
- Create: `tests/test_packaging.py`
- Create: `media-missher/SKILL.md`
- Create: `media-missher/agents/openai.yaml`
- Create: `media-missher/scripts/`
- Create: `media-missher/references/`
- Create: `PROJECT_CONTEXT.md`

- [ ] **Step 1: Write the failing packaging tests**

Create `tests/test_packaging.py` with tests that read the candidate skill and assert:

```python
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"


def test_skill_frontmatter_is_codex_compatible():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    assert match
    lines = match.group(1).splitlines()
    keys = {line.split(":", 1)[0] for line in lines if ":" in line}
    assert keys == {"name", "description"}
    assert "name: media-missher" in lines


def test_skill_has_only_allowed_top_level_entries():
    assert {path.name for path in SKILL.iterdir()} == {
        "SKILL.md", "agents", "scripts", "references"
    }


def test_skill_contains_no_bundled_engine_or_generated_artifacts():
    forbidden = {"engine", ".venv", "data", "__pycache__", ".pytest_cache", "openclaw.skill.json"}
    assert not forbidden.intersection(path.name for path in SKILL.rglob("*"))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_packaging.py
```

Expected: FAIL because `media-missher/SKILL.md` and the skill directories do not exist.

- [ ] **Step 3: Initialize the skill with the official generator**

Read `skill-creator/references/openai_yaml.md`, then run:

```bash
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  media-missher \
  --path "$PWD" \
  --resources scripts,references \
  --interface 'display_name=Media@Missher' \
  --interface 'short_description=Safely collect and verify four-platform media data' \
  --interface 'default_prompt=Use $media-missher to collect and validate 10 recent posts from the configured creator.'
```

Replace the generated placeholders with this minimal valid frontmatter and body skeleton:

```markdown
---
name: media-missher
description: Operate and validate the locally installed Media@Missher collector for Bilibili, Xiaohongshu, Douyin, and Weibo. Use when a user asks to collect a specific number of posts, search a keyword, request complete Bilibili content or fresh Xiaohongshu engagement, validate a fresh run, or diagnose CDP, login, timeout, lock, or risk-cooldown failures. Keep code review read-only and require separate explicit authorization for any remote Feishu write.
---

# Media@Missher

Use the scripts in this skill to preflight, run, and validate the external Media@Missher engine. Never copy or modify the external engine as part of this workflow.
```

Create the empty required resource directories only; do not create `assets/`.

- [ ] **Step 4: Create durable project context**

Create `PROJECT_CONTEXT.md` recording the objective, thin-adapter architecture, external runtime boundary, installed engine path used for local testing, current branch, completed design, current phase, non-commercial external license constraint, known `--no-feishu` legacy behavior, and rollback rule.

- [ ] **Step 5: Run packaging and skill validation tests and verify GREEN**

Run:

```bash
python3 -m pytest -q tests/test_packaging.py
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py media-missher
```

Expected: packaging tests PASS and validator prints `Skill is valid!`.

- [ ] **Step 6: Commit**

```bash
git add PROJECT_CONTEXT.md media-missher tests/test_packaging.py
git commit -m "feat: scaffold media-missher Codex skill"
```

### Task 2: Implement configuration and read-only preflight

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`
- Create: `tests/test_preflight.py`
- Create: `media-missher/scripts/media_missher_adapter.py`
- Create: `media-missher/scripts/preflight.py`

- [ ] **Step 1: Write failing configuration tests**

Test CLI-over-environment-over-profile precedence, required private profile permissions, platform allow-list validation, non-negative integer validation, and interpreter derivation:

```python
def test_resolve_engine_root_prefers_cli(tmp_path, monkeypatch):
    env_root = tmp_path / "env"
    cli_root = tmp_path / "cli"
    monkeypatch.setenv("MEDIA_MISSHER_ENGINE_ROOT", str(env_root))
    assert resolve_engine_root(cli_root, environ=os.environ) == cli_root.resolve()


def test_parse_platforms_rejects_unknown_before_runtime():
    with pytest.raises(ConfigurationError, match="unknown platform"):
        parse_platforms("bilibili,invalid")


def test_private_profile_rejects_group_or_world_permissions(tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    profile.chmod(0o644)
    with pytest.raises(ConfigurationError, match="0600"):
        read_profile(profile)
```

- [ ] **Step 2: Run the configuration tests and verify RED**

Run `python3 -m pytest -q tests/test_config.py`.

Expected: collection error because the adapter module does not exist.

- [ ] **Step 3: Implement the minimal configuration API**

Implement these interfaces in `media_missher_adapter.py` using only the standard library. `parse_non_negative_int` converts once and rejects values below zero; `parse_platforms` lowercases a comma-separated value, removes duplicates while preserving order, defaults to all four platforms, and rejects every unknown value; `read_profile` enforces mode `0600`; the two resolvers apply CLI > environment > profile precedence and return absolute paths; `engine_python` returns `<engine>/.venv/bin/python` only when it is an executable regular file:

```python
PLATFORMS = ("bilibili", "xhs", "douyin", "weibo")


class ConfigurationError(ValueError):
    pass


def parse_non_negative_int(value: str | int) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ConfigurationError("value must be non-negative")
    return parsed


def parse_platforms(value: str | None) -> tuple[str, ...]:
    requested = PLATFORMS if value is None else tuple(
        dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip())
    )
    unknown = sorted(set(requested) - set(PLATFORMS))
    if unknown:
        raise ConfigurationError(f"unknown platform: {', '.join(unknown)}")
    if not requested:
        raise ConfigurationError("at least one platform is required")
    return requested
```

`read_profile` must reject files with any group/world permission bits and must return an empty mapping only when no profile path was requested.

- [ ] **Step 4: Write failing preflight tests**

Use a temporary fake engine root and monkeypatched `subprocess.run`/`urllib.request.urlopen` to assert:

```python
def test_preflight_checks_help_without_live_network(fake_engine_root):
    report = run_preflight(fake_engine_root, live=False)
    assert report["status"] == "ok"
    assert report["checks"]["entrypoint_help"] is True


def test_live_preflight_reports_unavailable_cdp_without_starting_chrome(fake_engine_root, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    report = run_preflight(fake_engine_root, live=True)
    assert report["status"] == "failed"
    assert report["checks"]["cdp"] is False
```

- [ ] **Step 5: Run preflight tests and verify RED**

Run `python3 -m pytest -q tests/test_preflight.py`.

Expected: FAIL because `run_preflight` and the CLI do not exist.

- [ ] **Step 6: Implement preflight**

Implement `run_preflight(engine_root, *, live, cdp_url, timeout)` to verify the engine interpreter, `scripts/scrape_all.py`, `--help`, and optional CDP `/json/version`. Use subprocess argument lists, bounded timeouts, and structured JSON-compatible results. Implement `preflight.py` with `--engine-root`, `--profile`, `--live`, `--cdp-url`, and `--json` options. It must never start Chrome or mutate the engine.

- [ ] **Step 7: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_config.py tests/test_preflight.py
python3 media-missher/scripts/preflight.py --help
```

Then commit:

```bash
git add media-missher/scripts tests/conftest.py tests/test_config.py tests/test_preflight.py
git commit -m "feat: add portable configuration and preflight"
```

### Task 3: Implement safe collection command construction and orchestration

**Files:**
- Create: `tests/fake_engine.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_runner.py`
- Modify: `media-missher/scripts/media_missher_adapter.py`
- Create: `media-missher/scripts/run_collection.py`

- [ ] **Step 1: Write the synthetic fake engine**

Create a no-network executable fixture that accepts the installed engine's relevant arguments, records received argv, writes synthetic timestamped JSON for requested platforms, supports `--help`, and can be directed through environment variables to fail, sleep, or emit a risk signal. Use only invented records such as:

```python
SAMPLE = {
    "title": "synthetic title",
    "link": "https://example.invalid/item/1",
    "date": "2026-01-01",
    "liked": 1,
    "comments": 2,
    "shares": 3,
    "collected": 4,
}
```

- [ ] **Step 2: Write failing CLI and command-construction tests**

Cover unknown platforms, negative values, search requiring one platform, search/complete incompatibility, shared/per-platform counts, explicit UIDs, complete flags, comments, timeout, JSON forcing, and unconditional `--no-feishu` for `scrape_all.py`:

```python
def test_creator_command_forces_json_and_no_feishu(request, staging_dir):
    command = build_engine_command(request, staging_dir)
    assert command.script.name == "scrape_all.py"
    assert command.argv[command.argv.index("--format") + 1] == "json"
    assert command.argv[command.argv.index("--output") + 1] == str(staging_dir)
    assert "--no-feishu" in command.argv


def test_search_requires_exactly_one_platform():
    with pytest.raises(ConfigurationError, match="one platform"):
        CollectionRequest(platforms=("bilibili", "xhs"), search="topic")
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run `python3 -m pytest -q tests/test_cli.py tests/test_runner.py`.

Expected: FAIL because request, command, and runner APIs are missing.

- [ ] **Step 4: Implement request and command APIs**

Add immutable dataclasses:

```python
@dataclass(frozen=True)
class CollectionRequest:
    platforms: tuple[str, ...]
    count: int = 15
    platform_counts: Mapping[str, int] = field(default_factory=dict)
    platform_uids: Mapping[str, str] = field(default_factory=dict)
    search: str | None = None
    complete: bool = False
    bilibili_complete: bool = False
    xhs_complete: bool = False
    xhs_comments: int = 0
    platform_timeout: float = 300.0
    output_format: str = "json"


@dataclass(frozen=True)
class EngineCommand:
    script: Path
    argv: tuple[str, ...]
    environment: Mapping[str, str]


@dataclass(frozen=True)
class CompletedRun:
    returncode: int | None
    stdout_path: Path
    stderr_path: Path
    timed_out: bool
    duration_seconds: float
```

Validate in `CollectionRequest.__post_init__`. Build creator requests through `scrape_all.py`; build single-platform search through the matching platform script. Never use `shell=True`.

- [ ] **Step 5: Write failing orchestration tests**

Test unique mode-`0700` run directories, bounded timeouts, captured evidence, child-only termination, current-run file discovery, stale-file rejection, structured statuses, and the absence of `feishu_*` files.

- [ ] **Step 6: Implement orchestration and CLI**

Implement the following concrete orchestration contract. `create_run_directory` uses UTC timestamp plus a random suffix, refuses collisions, and creates mode `0700`; `execute_engine` launches `command.argv` with `Popen(shell=False, start_new_session=True)`, writes stdout/stderr inside the run directory, enforces the supplied timeout, terminates only the child process group on timeout, and returns `CompletedRun`; `discover_current_json` returns only regular JSON files inside that run directory whose `st_mtime_ns` is not older than `started_ns`:

```python
def create_run_directory(data_root: Path, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    run_dir = data_root / f"run-{timestamp}-{secrets.token_hex(4)}"
    run_dir.mkdir(parents=True, mode=0o700)
    run_dir.chmod(0o700)
    return run_dir


def discover_current_json(run_dir: Path, *, started_ns: int) -> tuple[Path, ...]:
    return tuple(sorted(
        path for path in run_dir.glob("*.json")
        if path.is_file() and path.stat().st_mtime_ns >= started_ns
    ))
```

`run_collection.py` must parse the compatibility CLI, call preflight before live execution, create the run directory, execute exactly one engine child process, classify results, and print a JSON summary when `--json-summary` is requested. It must not invoke Feishu or read credentials.

- [ ] **Step 7: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_cli.py tests/test_runner.py
python3 media-missher/scripts/run_collection.py --help
```

Commit:

```bash
git add media-missher/scripts tests/fake_engine.py tests/test_cli.py tests/test_runner.py
git commit -m "feat: add safe Media@Missher runner"
```

### Task 4: Implement output validation, conversion, and redaction

**Files:**
- Create: `tests/fixtures/bilibili_creator.json`
- Create: `tests/fixtures/bilibili_search.json`
- Create: `tests/fixtures/xhs_creator.json`
- Create: `tests/fixtures/xhs_search.json`
- Create: `tests/fixtures/douyin_creator.json`
- Create: `tests/fixtures/douyin_search.json`
- Create: `tests/fixtures/weibo_creator.json`
- Create: `tests/fixtures/weibo_search.json`
- Create: `tests/test_output.py`
- Create: `tests/test_validation.py`
- Modify: `media-missher/scripts/media_missher_adapter.py`
- Create: `media-missher/scripts/validate_run.py`

- [ ] **Step 1: Create synthetic schema fixtures**

Write invented records matching the accepted field shapes. Include null/zero distinctions, Bilibili title/date/complete metadata, Xiaohongshu freshness/source/report metadata, Douyin cursor/search fields, and Weibo normalized HTML/API card fields. Do not use real user IDs, links, cookies, tokens, or collected content.

- [ ] **Step 2: Write failing validator and converter tests**

Test malformed JSON, unexpected top-level types, count shortfalls, null preservation, risk-stopped/partial/success statuses, secret canary redaction, current-run filtering, and round-trip output:

```python
@pytest.mark.parametrize("format_name", ["json", "csv", "jsonl", "sqlite"])
def test_conversion_round_trip_preserves_normalized_records(tmp_path, sample_records, format_name):
    path = write_output(sample_records, format_name, tmp_path / "out")
    assert read_output(path, format_name) == normalize_records(sample_records)


def test_redaction_removes_query_tokens_and_secret_canary(sample_records):
    redacted = redact_for_summary(sample_records, secrets={"CANARY-SECRET"})
    assert "CANARY-SECRET" not in json.dumps(redacted)
    assert "xsec_token" not in json.dumps(redacted)
```

- [ ] **Step 3: Run tests and verify RED**

Run `python3 -m pytest -q tests/test_output.py tests/test_validation.py`.

Expected: FAIL because validation/conversion functions and CLI are missing.

- [ ] **Step 4: Implement validation and conversion**

Implement standard-library JSON/CSV/JSONL/SQLite writers and corresponding test readers. Build CSV columns from the ordered union of keys. Encode nested values as JSON text. Preserve `None` as null/empty according to the format and never coerce unknown engagement to zero.

Implement `validate_run(paths, request, started_ns)` with platform-specific count and completeness checks and status classification. Implement `redact_for_summary` so query strings, token-like keys, configured secrets, personal IDs, and full environments are not printed.

- [ ] **Step 5: Implement `validate_run.py`**

Support `--run-dir`, `--started-epoch`, `--platform`, `--expected-count`, `--format`, `--output`, and `--json-summary`. Limit human-readable samples to three redacted records and always print absolute evidence paths.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_output.py tests/test_validation.py
python3 media-missher/scripts/validate_run.py --help
```

Commit:

```bash
git add media-missher/scripts tests/fixtures tests/test_output.py tests/test_validation.py
git commit -m "feat: validate and convert collection output"
```

### Task 5: Complete skill instructions, references, and security gates

**Files:**
- Modify: `media-missher/SKILL.md`
- Create: `media-missher/references/commands.md`
- Create: `media-missher/references/configuration.md`
- Create: `media-missher/references/licensing.md`
- Create: `media-missher/references/troubleshooting.md`
- Create: `media-missher/references/validation.md`
- Create: `tests/test_security.py`
- Modify: `tests/test_packaging.py`
- Modify: `PROJECT_CONTEXT.md`

- [ ] **Step 1: Write failing security and documentation tests**

Scan the installable skill for personal paths, Open IDs, default UIDs, credential names with values, inherited source headers, bundled engine files, third-party binaries, `openclaw.skill.json`, and stale placeholders. Assert `SKILL.md` is below 250 lines and every reference it names exists.

- [ ] **Step 2: Run tests and verify RED**

Run `python3 -m pytest -q tests/test_security.py tests/test_packaging.py`.

Expected: FAIL because references and the complete skill workflow are missing.

- [ ] **Step 3: Write the final concise SKILL.md**

Use imperative language and preserve these contracts:

- code review is read-only;
- real collection requires explicit count/target authorization;
- unknown targets are never guessed;
- count zero requires explicit collect-as-much-as-safe intent;
- search is single-platform and incompatible with complete mode;
- multi-platform work is sequential;
- complete mode runs once, not ordinary then complete;
- preflight runs before collection;
- no Chrome restart, cookie replacement, lock/risk clearing, account rotation, proxy rotation, captcha bypass, or stealth injection;
- risk codes/signals stop the run;
- remote Feishu writes are out of scope;
- only current-run evidence may be accepted;
- final status is success, partial, risk-stopped, preflight-failed, or failed.

Route detailed commands, configuration, validation, licensing, and troubleshooting to the five reference files without duplicating their bodies.

- [ ] **Step 4: Write references and update project context**

Document exact adapter commands and external settings. Explain that no external engine source is distributed, the external runtime keeps its own license, and the adapter repository license remains unselected. Include troubleshooting for missing engine, missing venv, CDP unavailable, logged-out page, timeout, active lock/cooldown, and risk stop. Do not instruct users to bypass platform controls.

- [ ] **Step 5: Regenerate UI metadata and verify GREEN**

Run:

```bash
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py \
  media-missher \
  --interface 'display_name=Media@Missher' \
  --interface 'short_description=Safely collect and verify four-platform media data' \
  --interface 'default_prompt=Use $media-missher to collect and validate 10 recent posts from the configured creator.'
python3 -m pytest -q tests/test_security.py tests/test_packaging.py
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py media-missher
```

- [ ] **Step 6: Commit**

```bash
git add media-missher PROJECT_CONTEXT.md tests/test_security.py tests/test_packaging.py
git commit -m "docs: finalize Media@Missher skill workflow"
```

### Task 6: Run full verification and independent reviews

**Files:**
- Modify only files required to address verified review findings.

- [ ] **Step 1: Run the complete default offline suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

Expected: all tests PASS, zero unexpected skip/xfail, and no external network or out-of-scope writes.

- [ ] **Step 2: Run skill and packaging verification**

Run:

```bash
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py media-missher
git diff --check
rg -n '/Users/missher|ou_[A-Za-z0-9]+|legacy[[:space:]-]+upstream|openclaw.skill.json|xsec_token[^[:space:]]*[:=][^[:space:]]+' media-missher
find media-missher -type d \( -name .venv -o -name __pycache__ -o -name data \) -print
```

Expected: validator succeeds; diff check succeeds; secret/provenance scan shows only the deliberate explanatory licensing reference, not copied source or personal values; forbidden-directory scan is empty.

- [ ] **Step 3: Run smoke tests from a special-character path**

Copy only the installable skill to a temporary directory whose name contains a space and `@`, then run all three `--help` commands and offline preflight against the fake engine. Use a temporary copy, not the installed skill.

- [ ] **Step 4: Run read-only preflight against the installed engine**

Run:

```bash
python3 media-missher/scripts/preflight.py \
  --engine-root /Users/missher/.openclaw/workspace/skills/media-missher \
  --json
```

Expected: engine/interpreter/entrypoint checks pass without collection or source changes.

- [ ] **Step 5: Dispatch spec-compliance review**

Give a fresh reviewer the design, implementation plan, commit range, and candidate files. Require a line-by-line assessment of compatibility, provenance, safety, packaging, and rollback. Address every Critical or Important finding and request re-review.

- [ ] **Step 6: Dispatch code-quality review**

After spec compliance is approved, give a fresh reviewer the same commit range and ask for correctness, maintainability, error-handling, security, and test-quality review. Address every Critical or Important finding and request re-review.

- [ ] **Step 7: Run final fresh verification**

Repeat the complete offline suite, skill validator, `git diff --check`, packaging scan, all CLI smoke tests, and installed-engine read-only preflight after review fixes.

- [ ] **Step 8: Commit review fixes**

```bash
git add media-missher tests PROJECT_CONTEXT.md
git commit -m "test: verify Media@Missher skill compatibility"
```

Do not install the Codex skill or perform live platform collection until the fresh offline gates pass. The user's current request authorizes one sequential count-1 compatibility run per platform with no Feishu once those gates pass. Read and validate each current-run artifact; only then install the skill into the configured Codex skills directory, preserving any existing target as a recoverable timestamped backup, and rerun `quick_validate.py` against the installed copy.
