# Xiaohongshu CDP-Only Browser Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Xiaohongshu article-detail collection use only Media@Missher's Playwright/CDP page while preserving exact detail fields, bounded comments, private screenshots, and the optional Bilibili BrowserSkill path.

**Architecture:** Reject Xiaohongshu BrowserSkill requests before any platform navigation, then keep the existing `DetailOpenCoordinator` with `bridge=None` as the sole XHS click and popup-resolution authority. Preserve response-listener-before-click ordering, risk-first handling, current-run validation, and screenshot capture. Correct the adapter so diagnostic JSON without accepted content cannot turn a failed zero-record run into `partial`.

**Tech Stack:** Python 3.11+, asyncio, Playwright over Chrome CDP, standard-library adapter, pytest/pytest-asyncio/pytest-socket, Tencent BrowserSkill retained only for Bilibili.

**Repository rule:** The worktree already contains user-approved but uncommitted V15 hardening. Do not stage or commit during this plan unless the user separately authorizes it; use tests and exact diffs as checkpoints instead.

---

## File map

- `runtime/media_missher_runtime/models.py`: reject XHS BrowserSkill at the per-platform request boundary.
- `runtime/media_missher_runtime/cli.py`: reject direct runtime XHS BrowserSkill invocations before creating a dispatcher and retain safe diagnostic enumeration.
- `runtime/media_missher_runtime/platforms/xhs.py`: remove BrowserSkill as a reason to open detail; preserve CDP exact-click detail collection and screenshots.
- `runtime/media_missher_runtime/detail_open.py`: keep one coordinator, with clearer platform-neutral failure text.
- `media-missher/scripts/media_missher_adapter.py`: reject XHS BrowserSkill in the public adapter and fix zero-record status semantics.
- `media-missher/SKILL.md` and `media-missher/references/*.md`: document XHS CDP-only operation and Bilibili-only BrowserSkill.
- `openclaw-media-missher/SKILL.md`: keep the historical compatibility skill consistent without reactivating OpenClaw.
- `PROJECT_CONTEXT.md`: record the selected ownership model and dated live result.
- `tests/test_cli.py`, `tests/test_runtime_cli.py`, `tests/test_runtime_xhs.py`, `tests/test_runtime_browser.py`, `tests/test_runner.py`, `tests/test_packaging.py`, `tests/test_openclaw_packaging.py`: contract, regression, documentation, and packaging gates.

### Task 1: Reject Xiaohongshu BrowserSkill before navigation

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_runtime_cli.py`
- Modify: `runtime/media_missher_runtime/models.py`
- Modify: `runtime/media_missher_runtime/cli.py`
- Modify: `media-missher/scripts/media_missher_adapter.py`

- [ ] **Step 1: Write adapter request tests that fail on XHS assistance and retain Bilibili assistance**

Add tests equivalent to:

```python
def test_xhs_browser_assist_is_rejected_before_execution():
    with pytest.raises(ConfigurationError, match="xhs-browser-assist-unsupported"):
        CollectionRequest(
            platforms=("xhs",), count=1,
            platform_uids={"xhs": "creator"},
            browser_assist="browserskill", allow_navigation=True,
        )


def test_bilibili_browser_assist_remains_supported():
    request = CollectionRequest(
        platforms=("bilibili",), count=1,
        platform_uids={"bilibili": "creator"},
        browser_assist="browserskill", allow_navigation=True,
    )
    assert request.browser_assist == "browserskill"
```

Also cover `platforms=("bilibili", "xhs")` with the same fixed rejection code.

- [ ] **Step 2: Run the focused adapter tests and confirm the new XHS assertions fail**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_cli.py
```

Expected: the new XHS cases fail because `browserskill` is still accepted; the Bilibili case passes.

- [ ] **Step 3: Add the fixed adapter boundary**

In `media-missher/scripts/media_missher_adapter.py`, after validating `browser_assist`, add:

```python
if self.browser_assist == "browserskill" and "xhs" in requested:
    raise ConfigurationError("xhs-browser-assist-unsupported")
```

Retain screenshot validation separately so XHS `--screenshot-mode opened|all` with `browser_assist="off"` remains legal.

- [ ] **Step 4: Add direct-runtime request and CLI rejection tests**

In `tests/test_runtime_cli.py`, cover both the model and the CLI:

```python
def test_runtime_model_rejects_xhs_browser_assist():
    with pytest.raises(ValueError, match="xhs-browser-assist-unsupported"):
        CollectionRequest(
            platform="xhs", count=1, uid="creator",
            browser_assist="browserskill",
        )


def test_runtime_cli_rejects_xhs_browser_assist_before_dispatcher(capsys):
    code = main([
        "creator", "--platform", "xhs", "--xhs-uid", "creator",
        "--count", "1", "--allow-navigation",
        "--browser-assist", "browserskill", "--output", "/unused",
    ])
    assert code == 78
    assert capsys.readouterr().err == (
        "media-missher-diagnostic platform=xhs "
        "kind=precondition code=xhs-browser-assist-unsupported\n"
    )
```

Use a fake dispatcher or `tmp_path` in the actual test so no browser or external filesystem side effect occurs.

- [ ] **Step 5: Implement runtime fail-closed behavior before dispatcher construction**

Add `xhs-browser-assist-unsupported` to the fixed safe precondition codes. In `main`, immediately after `_requests_from_args` and before `RuntimeDispatcher(...)`, return the structured code when any XHS request has BrowserSkill:

```python
if args.browser_assist == "browserskill" and any(
    request.platform == "xhs" for request in requests
):
    print(
        "media-missher-diagnostic platform=xhs "
        "kind=precondition code=xhs-browser-assist-unsupported",
        file=sys.stderr,
    )
    return 78
```

In `runtime/media_missher_runtime/models.py`, enforce the same invariant for programmatic callers:

```python
if self.platform == "xhs" and self.browser_assist == "browserskill":
    raise ValueError("xhs-browser-assist-unsupported")
```

- [ ] **Step 6: Run `tests/test_cli.py tests/test_runtime_cli.py`**

Expected: all pass; XHS rejects before dispatcher construction; Bilibili still accepts assistance.

### Task 2: Make XHS detail opening explicitly CDP-only

**Files:**
- Modify: `tests/test_runtime_xhs.py`
- Modify: `tests/test_runtime_browser.py`
- Modify: `runtime/media_missher_runtime/platforms/xhs.py`
- Modify: `runtime/media_missher_runtime/detail_open.py`

- [ ] **Step 1: Replace XHS BrowserSkill behavior tests with CDP ownership tests**

Remove tests that expect `browser_assist="browserskill"` to click XHS. Add complete-detail and screenshot-all cases using a bridge-free coordinator:

```python
def test_complete_xhs_registers_listener_before_cdp_exact_click():
    page = Page(
        responses=[creator_response(note("one")), detail_response("one")],
        cards=[{"note_id": "one"}],
    )
    record = run(collect_creator(
        CollectionRequest(platform="xhs", count=1, uid="u", complete=True),
        Browser(page),
    ))[0]
    assert page.events[-2:] == ["listener", "click"]
    assert record["detail_completed"] is True
    assert record["complete"] is True


def test_xhs_screenshot_all_uses_cdp_detail_without_browser_skill():
    screenshots = Screenshots()
    page = Page(
        responses=[creator_response(note("one")), detail_response("one")],
        cards=[{"note_id": "one"}],
    )
    record = run(collect_creator(
        CollectionRequest(
            platform="xhs", count=1, uid="u",
            complete=True, screenshot_mode="all",
        ),
        Browser(page, screenshots=screenshots),
    ))[0]
    assert page.clicked == ["one"]
    assert screenshots.captures == [("xhs", "one", "all")]
    assert record["screenshot_status"] == "complete"
```

Adjust fake event spelling to the repository's existing `Page` implementation rather than weakening assertions.

- [ ] **Step 2: Run XHS/browser tests before implementation**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_xhs.py tests/test_runtime_browser.py tests/test_runtime_detail_open.py
```

Expected: obsolete XHS assist expectations fail or the new ownership assertions expose BrowserSkill-dependent policy.

- [ ] **Step 3: Remove BrowserSkill from XHS opening policy**

In `runtime/media_missher_runtime/platforms/xhs.py`, reduce `_should_open_detail` to:

```python
def _should_open_detail(request: CollectionRequest, record: Mapping[str, Any]) -> bool:
    return request.complete or request.screenshot_mode == "all"
```

Keep `_click_note_and_check(..., browser=self.browser)` so `DetailOpenCoordinator(bridge=None)` performs the one Playwright click and exact same-page/popup resolution. Change only the misleading failure text from “BrowserSkill detail coordinator” to “detail-open coordinator”.

- [ ] **Step 4: Prove the detailed article contract remains intact**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_xhs.py tests/test_runtime_xhs_detail_enrichment.py \
  tests/test_runtime_detail_open.py tests/test_validation.py
```

Expected: all pass, including current-detail body, author, media, exact date, liked/comments/collected/shares, bounded comments, and screenshots.

### Task 3: Correct zero-record outer status

**Files:**
- Modify: `tests/test_runner.py`
- Modify: `media-missher/scripts/media_missher_adapter.py`

- [ ] **Step 1: Add a regression with diagnostic JSON but zero accepted records**

Construct a failed engine result whose run directory contains only a valid failed manifest and XHS report. Assert:

```python
assert summary["validation"]["counts"]["xhs"] == 0
assert summary["validation"]["status"] == "failed"
assert summary["status"] == "failed"
assert summary["evidence"] == []
```

- [ ] **Step 2: Run the exact regression and confirm current behavior is `partial`**

Expected before implementation: outer `summary["status"]` is `partial` because diagnostic JSON makes `evidence` truthy.

- [ ] **Step 3: Base partial status on accepted records**

Change:

```python
status = "partial" if evidence else "failed"
```

to:

```python
status = "partial" if validation["records"] else "failed"
```

- [ ] **Step 4: Run `tests/test_runner.py tests/test_validation.py`**

Expected: all pass; partial runs with real accepted records remain partial, but zero-record diagnostics remain failed.

### Task 4: Align skills and project documentation

**Files:**
- Modify: `media-missher/SKILL.md`
- Modify: `media-missher/references/commands.md`
- Modify: `media-missher/references/configuration.md`
- Modify: `media-missher/references/troubleshooting.md`
- Modify: `media-missher/references/validation.md`
- Modify: `openclaw-media-missher/SKILL.md`
- Modify: `PROJECT_CONTEXT.md`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_openclaw_packaging.py`

- [ ] **Step 1: Add documentation contract tests**

```python
assert "Xiaohongshu uses Playwright/CDP only" in text
assert "xhs-browser-assist-unsupported" in text
assert "Bilibili" in text and "BrowserSkill" in text
assert "--browser-assist off" in commands
```

Keep existing assertions for screenshots, risk stops, no Feishu writes, current-run evidence, and private file modes.

- [ ] **Step 2: Rewrite only affected ownership statements**

Document that XHS complete mode opens exact details through CDP, screenshots work with assistance off, BrowserSkill is Bilibili-only within Media@Missher, explicit XHS assistance rejects before navigation, Tencent/BrowserSkill remains installed, and the two earlier 0/10 attempts are diagnostic rather than accepted evidence.

- [ ] **Step 3: Run documentation and packaging gates**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_packaging.py tests/test_openclaw_packaging.py tests/test_active_residuals.py
python3 tools/scan_active_residuals.py --root .
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py media-missher
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py openclaw-media-missher
git diff --check
```

Expected: all tests and validators pass; residual scan reports zero findings; diff check is silent.

### Task 5: Run complete offline release gates

**Files:**
- Verify only; update `PROJECT_CONTEXT.md` with exact dated totals after the gate.

- [ ] **Step 1: Run the complete sockets-disabled suite**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket
```

Expected: zero failures and only the existing intentional socket-block warning.

- [ ] **Step 2: Compile every Python source in memory**

```bash
/Users/missher/.local/share/media-missher/venv/bin/python - <<'PY'
from pathlib import Path
count = 0
for source_path in sorted(Path('.').rglob('*.py')):
    if any(part in {'.git', '.pytest_cache', '__pycache__'} for part in source_path.parts):
        continue
    compile(source_path.read_bytes(), str(source_path), 'exec')
    count += 1
print(f'compiled_python_files={count}')
PY
```

Expected: no exception and a positive exact count.

- [ ] **Step 3: Run all five entrypoint help checks with Python 3.11**

```bash
for entry in scrape_all.py scrape_bilibili.py scrape_xhs.py scrape_douyin.py scrape_weibo.py; do
  PYTHONPATH=runtime /Users/missher/.local/share/media-missher/venv/bin/python \
    "runtime/scripts/$entry" --help >/dev/null || exit 1
done
```

Expected: all five exit zero.

### Task 6: Atomically install and perform one live XHS acceptance

**Files:**
- Install source into the existing private runtime and Codex skill only after Task 5 passes.
- Update `PROJECT_CONTEXT.md` with the exact current-run result.

- [ ] **Step 1: Confirm locks, BrowserSkill sessions, profile mode, and live CDP**

Read-only checks must prove both Media locks are available, the private profile is mode `0600` with one XHS target, BrowserSkill has zero sessions, and live preflight returns `status: ok`.

- [ ] **Step 2: Install atomically in Codex-only mode**

```bash
python3 tools/install_media_missher.py --codex-only
```

Expected: version `15.0.0`, matching current/venv/Codex release markers, explicit recovery paths, and `openclaw_current: null`.

- [ ] **Step 3: Run one authorized 10-article CDP-only acceptance**

```bash
python3 /Users/missher/.codex/skills/media-missher/scripts/run_collection.py \
  --profile /Users/missher/.config/media-missher/profile.json \
  --platform xhs --count 10 --xhs-complete --xhs-comments 10 \
  --allow-navigation --platform-timeout 600 --execution-timeout 900 \
  --browser-assist off --screenshot-mode opened --no-feishu --json-summary
```

Expected success contract: exactly 10 current-run records; current detail body, author, media, non-estimated date, liked/comments/collected/shares, fresh engagement, complete status, bounded comments, and validated screenshots; zero BrowserSkill sessions; zero Feishu artifacts.

Stop without retry on any risk code, challenge, lock, block, or cooldown. For a non-risk failure, report the exact stage and current evidence; do not silently launch another collection.

- [ ] **Step 4: Validate only the exact returned run directory**

Use the adapter's returned current-run paths and `validate_run.py`; never select `latest`. Confirm mode `0700` on the run directory, `0600` on JSON/PNG artifacts, no symlinks, matching screenshot hashes, released collection lock, and zero BrowserSkill sessions.

- [ ] **Step 5: Report the exact outcome**

Report completed files, implementation boundary, offline test total, installation release/recovery paths, live status, validated count, screenshot count, evidence paths, and limitations. Do not echo article content, creator UID, query strings, cookies, browser state, or credentials.
