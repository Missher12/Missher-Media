# Bilibili CDP Dynamic Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Bilibili strict complete mode use one bridge-free exact CDP detail click to fill missing non-video engagement values without changing mixed-feed selection, overwriting precise list metrics, or weakening risk stops.

**Architecture:** Keep request/CLI/output schemas unchanged. Extend only the non-video detail obligation in `bilibili.py`, reuse `DetailOpenCoordinator`, add a bounded exact main-document response observer for detail HTTP risk, and preserve the existing runtime/adapter completeness contracts.

**Tech Stack:** Python 3.11+, Playwright async CDP, pytest/pytest-asyncio/pytest-socket, standard-library adapter.

---

## File map

- Modify `runtime/media_missher_runtime/platforms/bilibili.py`: complete-mode trigger, bridge-free click policy, exact detail HTTP observer, fill-only merge.
- Modify `tests/test_runtime_bilibili_production.py`: collector-level RED/GREEN coverage and response-observer fakes.
- Modify `tests/test_runtime_cli.py`: runtime `incomplete-record` classification for a still-missing Bilibili dynamic.
- Modify `tests/test_validation.py`: adapter `partial` classification while retaining the record.
- Modify `PROJECT_CONTEXT.md`: dated source-only verification record after all gates pass.

No model, CLI, manifest, adapter request, installation, or skill interface file should change for this feature.

### Task 1: Prove the missing bridge-free complete-mode behavior

**Files:**
- Modify: `tests/test_runtime_bilibili_production.py`

- [ ] **Step 1: Make the coordinator fake expose the click-replay policy**

Extend `AssistedCoordinator` with `retry_policies: list[bool]` and accept the real coordinator keyword:

```python
@dataclass
class AssistedCoordinator:
    result_page: CapturePage | None = None
    clicks: list[str] = field(default_factory=list)
    retry_policies: list[bool] = field(default_factory=list)
    released: list[CapturePage] = field(default_factory=list)

    async def click_exact(
        self,
        page: CapturePage,
        element: DynamicElement,
        *,
        platform: str,
        native_id: str,
        retry_stale_selector: bool = True,
    ) -> CapturePage:
        assert platform == "bilibili"
        assert element.dynamic_id == native_id or element.href is not None
        self.clicks.append(native_id)
        self.retry_policies.append(retry_stale_selector)
        target = self.result_page or page
        target.url = f"https://t.bilibili.com/{native_id}"
        return target
```

- [ ] **Step 2: Write the failing complete-mode fill-only test**

Add a test whose list payload contains exact `liked=3`, `comments=4`, `shares=5`, and `collected=None`, while the detail DOM contains deliberately different display values plus `collected=6`:

```python
def test_complete_opens_unknown_dynamic_without_browserskill_and_only_fills_missing_metrics() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    item = _item("123456", comment={"count": 4})
    item["modules"]["module_stat"]["forward"] = {"count": 5}
    page = CapturePage(
        responses=[_feed(item, has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": 30_000,
            "comments": 40_000,
            "shares": 50_000,
            "collected": 6,
        }],
    )
    coordinator = AssistedCoordinator()

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            complete=True,
            browser_assist="off",
        ),
        ProductionBrowser(page, detail_open=coordinator),
    ))[0]

    assert coordinator.clicks == ["123456"]
    assert coordinator.retry_policies == [False]
    assert (record["liked"], record["comments"], record["shares"]) == (3, 4, 5)
    assert record["collected"] == 6
    assert record["detail_attempted"] is True
    assert record["detail_completed"] is True
    assert record["complete"] is True
    assert record["missing_fields"] == []
```

- [ ] **Step 3: Run the test and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_bilibili_production.py::test_complete_opens_unknown_dynamic_without_browserskill_and_only_fills_missing_metrics
```

Expected: FAIL because `coordinator.clicks` is empty. Do not implement until this exact behavioral failure is observed.

- [ ] **Step 4: Write the failing still-missing test**

```python
def test_complete_unknown_dynamic_remains_incomplete_after_one_bridge_free_click() -> None:
    from runtime.media_missher_runtime.platforms.bilibili import collect_creator

    page = CapturePage(
        responses=[_feed(_item("123456"), has_more=False)],
        dynamic_elements=[DynamicElement(dynamic_id="123456")],
        dynamic_details=[{
            "dynamic_id": "123456",
            "risk_text": "",
            "liked": None,
            "comments": None,
            "shares": None,
            "collected": None,
        }],
    )
    coordinator = AssistedCoordinator()
    screenshots = Screenshots()

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            complete=True,
            browser_assist="off",
        ),
        ProductionBrowser(page, detail_open=coordinator, screenshots=screenshots),
    ))[0]

    assert coordinator.clicks == ["123456"]
    assert coordinator.retry_policies == [False]
    assert record["detail_attempted"] is True
    assert record["collected"] is None
    assert record["complete"] is False
    assert record["missing_fields"] == ["collected"]
    assert screenshots.captures == []
```

- [ ] **Step 5: Run the second test and verify RED**

Use the same locked-dependency command with the second node ID. Expected: FAIL because complete mode with BrowserSkill off does not click.

### Task 2: Implement the minimal trigger, no-replay policy, and fill-only merge

**Files:**
- Modify: `runtime/media_missher_runtime/platforms/bilibili.py`
- Test: `tests/test_runtime_bilibili_production.py`

- [ ] **Step 1: Extend only the existing dynamic-open predicate**

Change `_needs_dynamic_open` so missing engagement creates an obligation in strict complete mode or explicit BrowserSkill mode, while `all` remains unconditional:

```python
def _needs_dynamic_open(
    request: CollectionRequest, record: Mapping[str, Any]
) -> bool:
    dynamic_id = record.get("dynamic_id")
    missing = bool(missing_engagement_fields(record))
    return (
        record.get("bvid") is None
        and isinstance(dynamic_id, str)
        and bool(dynamic_id)
        and (
            request.screenshot_mode == "all"
            or (missing and (request.complete or request.browser_assist == "browserskill"))
        )
    )
```

- [ ] **Step 2: Make the bridge-free call non-replaying**

Pass the existing coordinator policy explicitly in `_open_dynamic_record`:

```python
detail_page = await coordinator.click_exact(
    page,
    target,
    platform="bilibili",
    native_id=dynamic_id,
    retry_stale_selector=self.request.browser_assist == "browserskill",
)
```

This keeps the explicit BrowserSkill `stale-selector` compatibility replay and prevents replay on the new bridge-free path.

- [ ] **Step 3: Make dynamic detail merge fill-only**

In `_merge_dynamic_detail`, skip every field that is already known:

```python
for field in ("liked", "comments", "shares", "collected"):
    if record.get(field) is not None:
        continue
    value = detail.get(field)
    # retain the existing finite, non-boolean, non-negative validation
```

Do not alter `_merge_video_detail`; this rule applies only to the display-derived non-video detail DOM.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the two Task 1 node IDs plus these existing guards:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_bilibili_production.py \
  -k 'complete_opens_unknown_dynamic_without_browserskill or complete_unknown_dynamic_remains_incomplete or complete_accepts_authoritative_list_payload_for_nonvideo_dynamic or opened_screenshot_mode_does_not_cause_a_dynamic_open or dynamic_screenshot_modes'
```

Expected: all selected tests PASS. Also assert the existing BrowserSkill-assisted test records `retry_policies == [True]`.

- [ ] **Step 5: Commit the first behavior slice**

```bash
git add runtime/media_missher_runtime/platforms/bilibili.py tests/test_runtime_bilibili_production.py
git commit -m "fix: complete Bilibili non-video dynamics via CDP"
```

### Task 3: Observe exact detail-document HTTP risk

**Files:**
- Modify: `runtime/media_missher_runtime/platforms/bilibili.py`
- Modify: `tests/test_runtime_bilibili_production.py`

- [ ] **Step 1: Add a bounded fake browser-context event source**

Add a small test fake with `on`, `remove_listener`, and `emit_response`. A synthetic response must expose `.url`, `.status`, and `.request.resource_type == "document"`. Attach it to `CapturePage.context` only in observer tests.

- [ ] **Step 2: Write RED tests for exact matching and cleanup**

Add parameterized tests for `403` and `429` where the coordinator emits an exact `https://t.bilibili.com/123456` document response during the one click. Assert `CollectionStopped("http-<status>")`, no DOM merge, no screenshot, one click, and the response listener count returns to zero. Add a second test showing a wrong ID, an API resource, and status `200` do not produce a risk stop.

- [ ] **Step 3: Verify the HTTP-risk tests fail for the expected reason**

Run only the new tests. Expected: FAIL because the current dynamic path has no context response observer and proceeds to DOM parsing.

- [ ] **Step 4: Add a private exact-document observer**

Implement a private helper in `bilibili.py` with this contract:

```python
@dataclass(slots=True)
class _DynamicDetailResponseObserver:
    context: Any
    expected_dynamic_id: str
    risk_code: str | None = None
    _attached: bool = False

    def _on_response(self, response: Any) -> None:
        request = getattr(response, "request", None)
        if getattr(request, "resource_type", None) != "document":
            return
        if not _valid_dynamic_detail_url(
            getattr(response, "url", None), self.expected_dynamic_id
        ):
            return
        status = getattr(response, "status", None)
        if status in {403, 429}:
            self.risk_code = f"http-{status}"

    def __enter__(self) -> "_DynamicDetailResponseObserver":
        on = getattr(self.context, "on", None)
        if callable(on):
            on("response", self._on_response)
            self._attached = True
        return self

    def __exit__(self, *_: object) -> None:
        if self._attached:
            remove = getattr(self.context, "remove_listener", None)
            if callable(remove):
                remove("response", self._on_response)
            self._attached = False
```

Use only status, resource type, and the exact allowlisted URL path. Do not read a body or store a query. If a real Playwright context lacks the required listener removal method, fail closed during implementation rather than leaving a listener installed.

- [ ] **Step 5: Wrap the exact click and stop before DOM merge**

Create the observer immediately before `click_exact`, keep it active through exact page resolution, then raise `CollectionStopped(observer.risk_code)` before `_read_dynamic_detail` whenever a risk code was captured. Ensure `finally` still disposes the target and releases a Media-owned popup.

- [ ] **Step 6: Run the whole Bilibili production test file**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_bilibili_production.py
```

Expected: PASS with no failures. Confirm tests cover same-page and click-derived popup exact URLs, wrong-ID rejection, non-document rejection, and listener cleanup on success and exception.

- [ ] **Step 7: Commit the HTTP-risk slice**

```bash
git add runtime/media_missher_runtime/platforms/bilibili.py tests/test_runtime_bilibili_production.py
git commit -m "fix: stop on exact Bilibili detail HTTP risk"
```

### Task 4: Lock runtime and adapter result contracts

**Files:**
- Modify: `tests/test_runtime_cli.py`
- Modify: `tests/test_validation.py`

- [ ] **Step 1: Add the runtime manifest regression**

Use `FakeDispatcher` to return one Bilibili record with a valid identity/link/date/title, `complete=False`, `detail_attempted=True`, `collected=None`, and `missing_fields=["collected"]`. Invoke `main` with `--bilibili-complete`; assert exit code `1`, platform status `incomplete`, and diagnostic `{kind: "result", code: "incomplete-record"}`.

- [ ] **Step 2: Add the outer adapter regression**

Copy the existing Bilibili creator fixture, set one record's `complete=False`, `detail_attempted=True`, `collected=None`, and `missing_fields=["collected"]`, then call `validate_run` with `bilibili_complete=True`. Assert the record count remains one, evidence remains present, status is `partial`, and the error says one Bilibili complete record failed.

- [ ] **Step 3: Run both new tests**

Expected: PASS without production changes because they lock the existing desired classification; they are contract guards rather than RED tests for the collector defect.

- [ ] **Step 4: Run focused Bilibili/runtime/adapter regression**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_bilibili_production.py tests/test_runtime_cli.py \
  tests/test_validation.py tests/test_runner.py
```

Expected: all tests PASS.

- [ ] **Step 5: Commit contract tests**

```bash
git add tests/test_runtime_cli.py tests/test_validation.py
git commit -m "test: lock Bilibili incomplete detail contracts"
```

### Task 5: Complete source verification and documentation

**Files:**
- Modify: `PROJECT_CONTEXT.md`

- [ ] **Step 1: Run the full sockets-disabled suite**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket
```

Expected: zero failures and zero skips; the existing intentional pytest-socket warning may remain. Record the actual test total rather than predicting it.

- [ ] **Step 2: Run compile, entrypoint, skill, residual, and diff gates**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path

roots = (
    Path("runtime"),
    Path("media-missher"),
    Path("openclaw-media-missher"),
    Path("tests"),
    Path("tools"),
)
files = sorted(
    path
    for root in roots
    for path in root.rglob("*.py")
    if "__pycache__" not in path.parts
)
for path in files:
    compile(path.read_bytes(), str(path), "exec")
print(f"compiled={len(files)}")
PY
for script in scrape_all.py scrape_bilibili.py scrape_xhs.py scrape_douyin.py scrape_weibo.py; do
  PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
    --with-requirements runtime/requirements.lock \
    python "runtime/scripts/$script" --help >/dev/null || exit 1
done
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py media-missher
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py openclaw-media-missher
python3 tools/scan_active_residuals.py --root .
git diff --check
```

Expected: compile reports the actual positive file count; all five entrypoints exit `0`; both skills validate; residual findings are zero; `git diff --check` exits `0`.

- [ ] **Step 3: Update the project context with dated source-only evidence**

Append one concise V15.2 Bilibili source-hardening paragraph to `PROJECT_CONTEXT.md` containing the actual test count, changed behavior, BrowserSkill/CDP boundary, and explicit limitations: no installation, no new live collection, no Feishu write, no push/tag/release unless separately authorized.

- [ ] **Step 4: Re-run documentation and active-residual tests**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_packaging.py tests/test_active_residuals.py
```

Expected: PASS, followed by clean `git diff --check`.

- [ ] **Step 5: Commit verified documentation**

```bash
git add PROJECT_CONTEXT.md
git commit -m "docs: record Bilibili CDP completion verification"
```

Do not install, run another real-platform collection, push, tag, publish, or merge as part of this plan. Return the commits, actual test evidence, changed files, and remaining live limitation to the parent task for acceptance.
