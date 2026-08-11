# Media@Missher V15 Browser Assist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Media@Missher `15.0.0` with opt-in Tencent BrowserSkill exact-detail opening and private article/full-page evidence screenshots while preserving V12 defaults and safety controls.

**Architecture:** Keep Playwright/CDP authoritative for platform responses, risk checks, and screenshots. Add a narrow external `bsk` bridge that borrows only Media@Missher's uniquely marked temporary tab and performs one exact click; platform collectors decide when fields are missing and bind every merge to `note_id` or `dynamic_id`. Store PNG evidence atomically inside the current run and validate it through the existing adapter.

**Tech Stack:** Python 3.11+, asyncio, Playwright CDP, Tencent BrowserSkill CLI `0.1.10`/extension `0.1.6`, argparse, pytest/pytest-asyncio/pytest-socket, GitHub Actions.

---

## Execution boundary

Implement on branch `codex/media-missher-v15`. Do not run a real collection, install the runtime, create a release tag, create or modify a GitHub repository, push, or change repository visibility. The supervising task performs final review, full release verification, installation, tagging, and private publication. Keep implementation changes uncommitted so the supervisor can review one complete diff; use the checkpoint commands in each task instead of committing.

Read the approved design first:

```bash
sed -n '1,260p' docs/superpowers/specs/2026-08-11-media-missher-v15-browser-assist-design.md
```

Never weaken navigation authorization, count/page caps, sequential collection, Xiaohongshu's 5-15 second settle, risk stops, or private file modes.

## File map

Create:

- `runtime/media_missher_runtime/browser_skill.py` — bounded `bsk` subprocess protocol, health validation, session lifecycle, exact marked-tab borrow/click/return.
- `runtime/media_missher_runtime/detail_open.py` — missing-engagement policy and platform-neutral exact-element click coordinator.
- `runtime/media_missher_runtime/screenshots.py` — article-container selection, risk-safe full-page fallback, record metadata binding.
- `tests/test_runtime_browser_skill.py` — fake runner contract and lifecycle tests.
- `tests/test_runtime_detail_open.py` — exact marker/click and missing-field policy tests.
- `tests/test_runtime_screenshots.py` — capture selection and private artifact tests.
- `.github/workflows/ci.yml` — offline sockets-disabled CI only.

Modify:

- `runtime/media_missher_runtime/models.py` — runtime request flags.
- `runtime/media_missher_runtime/cli.py` — CLI validation, dispatcher wiring, result/diagnostic handling, run-store binding.
- `runtime/media_missher_runtime/browser.py` — attach the bridge/coordinator/store to the existing temporary-page lifecycle.
- `runtime/media_missher_runtime/storage.py` — atomic private PNG writer.
- `runtime/media_missher_runtime/platforms/xhs.py` — missing-field fallback, assisted exact click, screenshot hook.
- `runtime/media_missher_runtime/platforms/bilibili.py` — pure-text/image dynamic detail open, ID-bound DOM merge, screenshot hook.
- `media-missher/scripts/media_missher_adapter.py` — public request fields, engine argv, screenshot validation, safe diagnostics.
- `media-missher/scripts/run_collection.py` — public CLI flags.
- `tests/fake_engine.py`, `tests/test_cli.py`, `tests/test_runner.py`, `tests/test_runtime_cli.py`, `tests/test_runtime_xhs.py`, `tests/test_runtime_bilibili.py`, `tests/test_runtime_bilibili_production.py`, `tests/test_runtime_storage.py`, `tests/test_validation.py`, `tests/test_security.py`, `tests/test_packaging.py`, `tests/test_installer.py` — end-to-end and regression contracts.
- `media-missher/SKILL.md`, `openclaw-media-missher/SKILL.md`, `media-missher/agents/openai.yaml`, `media-missher/references/commands.md`, `media-missher/references/configuration.md`, `media-missher/references/validation.md`, `media-missher/references/troubleshooting.md`, `media-missher/references/licensing.md`, `PROJECT_CONTEXT.md`, `VERSION`, `.gitignore` — V15 operation, privacy, compatibility, and release documentation.

### Task 1: Carry opt-in modes through both CLIs

**Files:**
- Modify: `runtime/media_missher_runtime/models.py:25-49`
- Modify: `runtime/media_missher_runtime/cli.py:179-284,456-477`
- Modify: `media-missher/scripts/media_missher_adapter.py:171-260,580-635`
- Modify: `media-missher/scripts/run_collection.py:20-145`
- Modify: `tests/fake_engine.py:12-44`
- Test: `tests/test_runtime_models.py`
- Test: `tests/test_runtime_cli.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_runner.py`

- [x] **Step 1: Write failing request and parser tests**

Add explicit cases with these assertions:

```python
def test_collection_request_accepts_safe_assist_and_screenshot_modes() -> None:
    request = CollectionRequest(
        platform="xhs",
        count=1,
        uid="creator",
        browser_assist="browserskill",
        screenshot_mode="opened",
    )
    assert request.browser_assist == "browserskill"
    assert request.screenshot_mode == "opened"


@pytest.mark.parametrize("field,value", [
    ("browser_assist", "stealth"),
    ("screenshot_mode", "background"),
])
def test_collection_request_rejects_unknown_modes(field: str, value: str) -> None:
    values = {"platform": "xhs", "count": 1, "uid": "creator", field: value}
    with pytest.raises(ValueError, match="unsupported"):
        CollectionRequest(**values)
```

For runtime and adapter parsers, assert defaults are `off`, the exact flags survive into the captured request/engine argv, `all` without `--allow-navigation` is rejected, `browserskill` without `--allow-navigation` is rejected, and any non-`off` value with Douyin or Weibo is rejected before dispatcher/engine execution.

- [x] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_models.py tests/test_runtime_cli.py tests/test_cli.py tests/test_runner.py
```

Expected: failures for missing request fields and unrecognized CLI options.

- [x] **Step 3: Add the minimal request contract**

Use the same field names in both request dataclasses:

```python
_BROWSER_ASSIST_MODES = frozenset({"off", "browserskill"})
_SCREENSHOT_MODES = frozenset({"off", "opened", "all"})

browser_assist: str = "off"
screenshot_mode: str = "off"

if self.browser_assist not in _BROWSER_ASSIST_MODES:
    raise ValueError("unsupported browser assist mode")
if self.screenshot_mode not in _SCREENSHOT_MODES:
    raise ValueError("unsupported screenshot mode")
```

Add both choices to runtime `_add_output_options` and public `run_collection.py`. Validate after platform selection:

```python
assisted = args.browser_assist != "off" or args.screenshot_mode != "off"
if assisted and not args.allow_navigation:
    parser.error("browser assist and screenshots require --allow-navigation")
if assisted and any(platform not in {"bilibili", "xhs"} for platform in platforms):
    parser.error("browser assist and screenshots support only bilibili and xhs")
```

Append these exact engine arguments only when non-default:

```python
if request.browser_assist != "off":
    argv.extend(("--browser-assist", request.browser_assist))
if request.screenshot_mode != "off":
    argv.extend(("--screenshot-mode", request.screenshot_mode))
```

Teach `tests/fake_engine.py` to parse the two options so adapter tests exercise the real argv shape.

- [x] **Step 4: Run the focused tests and checkpoint**

Run the Step 2 command. Expected: all selected tests pass.

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only V15 files are modified.

### Task 2: Implement the bounded BrowserSkill bridge

**Files:**
- Create: `runtime/media_missher_runtime/browser_skill.py`
- Create: `tests/test_runtime_browser_skill.py`

- [x] **Step 1: Write failing fake-runner lifecycle tests**

Define a fake runner that records argument tuples and returns typed results. Cover: exact healthy status, missing executable, daemon failure, multiple browsers, version skew, wrong CLI/extension version, pre-existing session (`bsk-busy`), four-letter session ID parsing, exact title match, zero/multiple title matches, snapshot-before-click, one stale snapshot retry, return in `finally`, stop in `close`, timeout, malformed/oversized JSON, and redacted exceptions.

The happy path assertion must be exact:

```python
assert fake.commands == [
    ("status", "--json", "--quiet"),
    ("session", "list", "--json", "--quiet"),
    ("session", "start", "--browser", "8f024870", "--quiet"),
    ("tab", "list", "--session", "abcd", "--scope", "user", "--json", "--quiet"),
    ("tab", "borrow", "tab-1", "--session", "abcd", "--json", "--quiet"),
    ("snapshot", "--session", "abcd", "--tab-id", "tab-1", "--max-tokens", "4096", "--json", "--quiet"),
    ("click", "--selector", selector, "--session", "abcd", "--tab-id", "tab-1", "--timeout", "15s", "--json", "--quiet"),
    ("tab", "return", "tab-1", "--session", "abcd", "--json", "--quiet"),
    ("session", "stop", "abcd", "--quiet"),
]
```

- [x] **Step 2: Run the bridge tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_browser_skill.py
```

Expected: import failure for `runtime.media_missher_runtime.browser_skill`.

- [x] **Step 3: Implement the bridge's public interface**

Use these stable types and constants:

```python
BSK_CLI_VERSION = "0.1.10"
BSK_EXTENSION_VERSION = "0.1.6"
MAX_COMMAND_OUTPUT = 1_048_576

@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes

class Runner(Protocol):
    async def run(self, *arguments: str, timeout: float) -> CommandResult:
        raise NotImplementedError

class BrowserSkillError(PreconditionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

```

`BrowserSkillBridge` exposes `async preflight() -> None`, `async click_marked_tab(page, *, selector: str) -> None`, and `async close() -> None`. `preflight()` accepts exactly one browser with `version_skew is False`, protocol `1.0`, CLI `0.1.10`, extension `0.1.6`, and zero sessions. Map failures only to safe codes: `bsk-missing`, `bsk-unhealthy`, `bsk-incompatible`, `bsk-busy`, `bsk-transport`, `bsk-timeout`, and `bsk-target-ambiguous`.

The production runner must use `asyncio.create_subprocess_exec` with `shell=False`, fixed executable discovery through `shutil.which("bsk")`, a clean argument vector, per-command timeout, termination on timeout, and stdout/stderr size rejection. Never copy raw stderr, JSON, URLs, or page text into exception messages.

`click_marked_tab()` obtains the marker from the caller-provided page title, starts one session lazily, lists only `--scope user`, matches exactly one tab whose title equals the marker, borrows it, snapshots before clicking, clicks only the passed unique selector, returns it in `finally`, and leaves session shutdown to `close()`. On exit code `1` from snapshot/click, allow exactly one new snapshot and one repeat click; codes `2-5` fail without a click loop.

- [x] **Step 4: Run tests and perform a read-only live schema check**

Run the Step 2 command. Expected: all bridge tests pass.

Run only diagnostics, not a BrowserSkill session:

```bash
bsk status --json
bsk session list --json
```

Expected: one compatible connected browser and an empty session list. Do not run `bsk session start` in this task.

### Task 3: Add exact-element coordination without changing default clicks

**Files:**
- Create: `runtime/media_missher_runtime/detail_open.py`
- Create: `tests/test_runtime_detail_open.py`
- Modify: `runtime/media_missher_runtime/browser.py:51-135`
- Modify: `runtime/media_missher_runtime/cli.py:114-160,286-455`
- Test: `tests/test_runtime_browser.py`

- [x] **Step 1: Write failing coordinator and cleanup tests**

Cover known-zero versus unknown metrics, unique element marking, marker removal, Playwright default click, BrowserSkill-assisted click, new popup registration, exact allowlisted detail URL, primary-error preservation during cleanup, and bridge shutdown before Playwright disconnect.

Use this policy assertion:

```python
assert missing_engagement_fields({
    "liked": 0,
    "comments": 2,
    "collected": None,
    "shares": None,
}) == ("collected", "shares")
```

- [x] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_detail_open.py tests/test_runtime_browser.py
```

Expected: missing coordinator imports and BrowserSession configuration.

- [x] **Step 3: Implement the coordinator boundary**

Expose only this policy and operation:

```python
ENGAGEMENT_FIELDS = ("liked", "comments", "collected", "shares")

def missing_engagement_fields(record: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(field for field in ENGAGEMENT_FIELDS if record.get(field) is None)

@dataclass(slots=True)
class DetailOpenCoordinator:
    bridge: BrowserSkillBridge | None = None

    async def click_exact(self, page: Any, element: Any, *, native_id: str) -> Any:
        token = secrets.token_hex(16)
        selector = f'[data-media-missher-target="{token}"]'
        await element.evaluate(
            "(node, value) => node.setAttribute('data-media-missher-target', value)",
            token,
        )
        try:
            if await page.locator(selector).count() != 1:
                raise PreconditionError("exact detail target is ambiguous")
            if self.bridge is None:
                await element.click()
            else:
                await self.bridge.click_marked_tab(page, selector=selector)
            return await resolve_exact_detail_page(page, native_id=native_id)
        finally:
            await page.locator(selector).evaluate_all(
                "nodes => nodes.forEach(node => node.removeAttribute('data-media-missher-target'))"
            )
```

Before bridge tab discovery, set a unique `media-missher-<token>` document title and restore it in `finally` when the page remains open. `resolve_exact_detail_page` accepts the original page or exactly one newly created page in the same browser context only when its HTTPS host is platform-allowlisted and its URL path contains the exact native ID. Register an accepted popup in `BrowserSession._temporary_pages` so existing pages remain untouched.

Extend `BrowserSession.connect`/`RuntimeDispatcher` with `browser_assist` and create `BrowserSkillBridge` only for `browserskill`. Run bridge preflight before `_create_store`; call bridge `close()` from the dispatcher/browser `finally` path even after cancellation.

- [x] **Step 4: Run tests and checkpoint**

Run the Step 2 command. Expected: all selected tests pass and existing default-click assertions remain unchanged.

Run `git diff --check`. Expected: no errors.

### Task 4: Write private screenshot evidence atomically

**Files:**
- Create: `runtime/media_missher_runtime/screenshots.py`
- Create: `tests/test_runtime_screenshots.py`
- Modify: `runtime/media_missher_runtime/storage.py:47-126`
- Modify: `runtime/media_missher_runtime/browser.py`
- Test: `tests/test_runtime_storage.py`

- [x] **Step 1: Write failing storage and capture tests**

Cover PNG signature, atomic replacement, mode `0600`, `screenshots/` mode `0700`, safe native-ID filename, symlink/traversal rejection, one visible sane article container, ambiguous/invisible/zero-size container fallback, full-page failure, challenge/login/risk page rejection, SHA-256, and UTC timestamp.

The expected record binding is:

```python
assert artifact.as_record_fields() == {
    "screenshot_path": "screenshots/xhs-note-123.png",
    "screenshot_mode": "opened",
    "screenshot_capture_kind": "article",
    "screenshot_observed_at": "2026-08-11T00:00:00+00:00",
    "screenshot_sha256": hashlib.sha256(png).hexdigest(),
    "screenshot_status": "complete",
}
```

- [x] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_storage.py tests/test_runtime_screenshots.py
```

Expected: missing private-byte writer and screenshot module.

- [x] **Step 3: Add private binary storage and capture**

Add a `RunStore.write_private_bytes(relative_name: str, payload: bytes) -> Path` method. Accept only `screenshots/<safe-basename>.png`, reject absolute paths, `..`, symlink directories/files, existing targets, non-PNG payloads, and payloads over a documented 50 MiB cap. Use `tempfile.mkstemp`, `os.fchmod(0o600)`, `fsync`, `os.replace`, directory `fsync`, and cleanup in `finally`.

Define:

```python
@dataclass(frozen=True, slots=True)
class ScreenshotArtifact:
    path: str
    request_mode: str
    capture_kind: str
    observed_at: str
    sha256: str

class ScreenshotError(RuntimeError):
    pass
```

`EvidenceScreenshot` accepts a `RunStore` in its constructor and exposes `async capture(page, *, platform: str, native_id: str, request_mode: str) -> ScreenshotArtifact`. Use platform selector tuples but combine them into one locator and require exactly one visible element with a bounding box of at least `100x80` and at most `4096x30000`. Capture that locator first. Otherwise call `page.screenshot(full_page=True, type="png")` exactly once. Before either capture, evaluate challenge/login selectors plus the existing platform risk phrases; raise `ScreenshotError("risk-page")` without writing a file when found.

Bind `RunStore` to the browser after `_create_store` through an explicit `RuntimeDispatcher.bind_store(store)` method. Do not use module globals.

- [x] **Step 4: Run tests and checkpoint**

Run the Step 2 command. Expected: all selected tests pass.

Run `git diff --check`. Expected: no errors.

### Task 5: Integrate Xiaohongshu missing-field opens and screenshots

**Files:**
- Modify: `runtime/media_missher_runtime/platforms/xhs.py:53,94-310,680-790,880-1020,1280-1385`
- Modify: `tests/test_runtime_xhs.py`

- [x] **Step 1: Write failing Xiaohongshu behavior tests**

Add cases proving:

- ordinary `off` behavior remains unchanged;
- ordinary `browserskill` opens once only when any of `liked/comments/collected/shares` is `None`;
- explicit zero never triggers fallback;
- response listener is installed before BrowserSkill click;
- another `note_id` response is rejected;
- complete mode still opens every record exactly once and settles 5-15 seconds exactly once;
- `opened` screenshots completed/assisted detail pages but does not create a new open;
- `all` opens and screenshots every selected record;
- article fallback metadata is attached to the correct record;
- risk response/challenge creates no screenshot and raises `CollectionStopped` immediately;
- screenshot failure preserves structured fields and records `screenshot_status="failed"` with safe `screenshot_error_code="capture-failed"`.

- [x] **Step 2: Run the Xiaohongshu suite and verify failures**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_xhs.py
```

Expected: new fallback/screenshot cases fail; existing tests still pass.

- [x] **Step 3: Route exact clicks through the coordinator**

Keep `_capture_while(page, predicate, action)` unchanged so it installs `expect_response` before invoking `action`. Change `_click_note_and_check` to accept the browser/coordinator and pass the already exact matched card/click target into `DetailOpenCoordinator.click_exact` when assistance is enabled; use its existing Playwright action when assistance is off.

Centralize the open decision:

```python
def _should_open_detail(request: CollectionRequest, record: Mapping[str, Any]) -> bool:
    if request.complete or request.screenshot_mode == "all":
        return True
    return (
        request.browser_assist == "browserskill"
        and bool(missing_engagement_fields(record))
    )
```

For ordinary fallback, merge only an exact `note_id` detail response and preserve `complete=False`; this is enrichment, not complete-mode proof. For complete mode, retain all current completeness fields, freshness checks, DOM fallbacks, comment handling, and randomized settle. After the post-open challenge check, call the bound screenshot service only when mode is `all` or when mode is `opened` and this record was opened.

- [x] **Step 4: Run Xiaohongshu regressions and checkpoint**

Run the Step 2 command. Expected: all Xiaohongshu tests pass.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_xhs.py tests/test_runtime_safety.py tests/test_runtime_browser.py
```

Expected: all pass; no timing or risk-stop regression.

### Task 6: Open and validate Bilibili pure-text/image dynamics

**Files:**
- Modify: `runtime/media_missher_runtime/platforms/bilibili.py:45-175,181-214,360-520,940-1020`
- Modify: `tests/test_runtime_bilibili.py`
- Modify: `tests/test_runtime_bilibili_production.py`

- [x] **Step 1: Write failing dynamic-detail tests**

Add synthetic text-only and image-only records with a `dynamic_id` and no `bvid`. Cover unknown-field fallback, known-zero no-open, exact ID card selection, ambiguous card failure, exact detail URL validation, new popup registration, same-ID DOM merge, cross-ID rejection, incomplete result when metrics remain unknown, existing video complete path unchanged, `opened`/`all` screenshots, and risk pages with no screenshot.

Assert pure dynamics remain valid:

```python
assert record["type"] == "dynamic"
assert record["dynamic_id"] == "123456"
assert record["bvid"] is None
assert record["native_id"] == "123456"
```

- [x] **Step 2: Run Bilibili tests and verify failures**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_bilibili.py tests/test_runtime_bilibili_production.py
```

Expected: new dynamic fallback tests fail; current video/list tests pass.

- [x] **Step 3: Implement exact dynamic opening and ID-bound merge**

Add `_dynamic_page_url(dynamic_id)` and `_find_exact_dynamic_target(page, dynamic_id)`. The finder must inspect only known Bilibili dynamic card/link selectors, compare exact `data-did`/`dyn-id`/`data-dynamic-id` values or parse the final URL path segment, and return exactly one clickable element. Zero/multiple results raise `PreconditionError`.

Add `_read_dynamic_detail(page, expected_dynamic_id)` returning a mapping with exactly `dynamic_id`, `risk_text`, `liked`, `comments`, `shares`, and `collected`. It must first verify the HTTPS host and exact path ID, then query metrics only inside the unique detail container. Merge only numeric values, preserve known zeros, and never replace a known field with `None`.

Use this open decision for non-video dynamics:

```python
needs_dynamic_open = (
    record.get("bvid") is None
    and isinstance(record.get("dynamic_id"), str)
    and (
        request.screenshot_mode == "all"
        or (
            request.browser_assist == "browserskill"
            and bool(missing_engagement_fields(record))
        )
    )
)
```

Route the exact element through `DetailOpenCoordinator`; then perform risk/ID validation, merge detail DOM values, and capture when requested. A click sets `detail_attempted=True`, but `detail_completed` and `complete` remain derived from `_missing_completion_fields`. Do not mark a record complete merely because the click succeeded. Leave the current `bvid` direct-navigation detail path intact.

- [x] **Step 4: Run Bilibili regressions and checkpoint**

Run the Step 2 command. Expected: all selected tests pass.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_bilibili.py tests/test_runtime_bilibili_production.py \
  tests/test_runtime_safety.py tests/test_runtime_compatibility.py
```

Expected: all pass and existing video behavior is unchanged.

### Task 7: Propagate screenshot shortfalls and validate referenced PNGs

**Files:**
- Modify: `runtime/media_missher_runtime/cli.py:286-455`
- Modify: `runtime/media_missher_runtime/storage.py`
- Modify: `media-missher/scripts/media_missher_adapter.py:45-120,754-887,1119-1385`
- Modify: `tests/test_runtime_cli.py`
- Modify: `tests/test_validation.py`
- Modify: `tests/test_security.py`

- [x] **Step 1: Write failing result and validator tests**

Cover: requested screenshot success, opened mode with no detail open and therefore no screenshot obligation, capture failure causing runtime `incomplete`/adapter `partial`, safe relative path, absolute/traversal/symlink/foreign-run/stale/wrong-mode/wrong-hash/non-PNG rejection, and output conversion path rewriting.

The validator must accept raw engine records with `screenshots/name.png` relative to the engine JSON directory, then rewrite accepted records for adapter outputs to `<engine-run-name>/screenshots/name.png` relative to the outer adapter run.

- [x] **Step 2: Run validation tests and verify failures**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_cli.py tests/test_validation.py tests/test_security.py
```

Expected: screenshot metadata is not yet enforced and shortfalls are not reflected.

- [x] **Step 3: Implement strict screenshot validation**

Add `screenshot-shortfall` to result diagnostics. `_result_status` returns `incomplete` when any record has `screenshot_status == "failed"`; it does not change the record's platform data completeness fields.

In adapter validation, require the full metadata group when `screenshot_status == "complete"`, reject partial groups, and verify:

```python
candidate = (source_json.parent / record["screenshot_path"]).resolve()
candidate.relative_to(source_json.parent.resolve())
assert not candidate.is_symlink()
assert stat.S_IMODE(candidate.stat().st_mode) == 0o600
assert candidate.stat().st_mtime_ns >= started_ns
assert candidate.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
assert hashlib.sha256(candidate.read_bytes()).hexdigest() == record["screenshot_sha256"]
```

Read the file once with a 50 MiB size cap rather than twice in production. Validate ISO UTC observation time, request mode `opened|all`, capture kind `article|full_page_fallback`, and exact safe filename. For converted adapter outputs, rewrite only the already validated path to include the engine run directory name; do not emit a user-home absolute path.

- [x] **Step 4: Run validation tests and checkpoint**

Run the Step 2 command. Expected: all selected tests pass.

Run `git diff --check`. Expected: no errors.

### Task 8: Make BrowserSkill failures fail closed with safe diagnostics

**Files:**
- Modify: `runtime/media_missher_runtime/cli.py:38-177,305-455`
- Modify: `media-missher/scripts/media_missher_adapter.py:45-120,1380-1450`
- Modify: `media-missher/references/troubleshooting.md`
- Test: `tests/test_runtime_cli.py`
- Test: `tests/test_runner.py`

- [x] **Step 1: Write failing preflight/risk diagnostic tests**

Test every safe BrowserSkill code, ensure no store is created on preflight failure, ensure raw subprocess output is absent, ensure risk codes still win over assist and screenshot errors, and ensure later platforms remain `not-run` after a risk stop.

- [x] **Step 2: Run tests and verify failures**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_cli.py tests/test_runner.py
```

Expected: new BrowserSkill diagnostic codes are rejected by strict schemas.

- [x] **Step 3: Add only enumerated diagnostics**

Extend precondition codes with:

```python
{
    "bsk-missing",
    "bsk-unhealthy",
    "bsk-incompatible",
    "bsk-busy",
    "bsk-transport",
    "bsk-timeout",
    "bsk-target-ambiguous",
}
```

Map bridge preflight failures to runtime exit `78` and the existing structured `media-missher-diagnostic` line. Keep `403`, `429`, `461`, `471`, `999`, challenge, locked, blocked, risk, and cooldown on the existing non-retryable exit `75` path. Do not invoke `bsk doctor` automatically in collection; troubleshooting may instruct one read-only diagnostic after a corrected non-risk failure.

- [x] **Step 4: Run diagnostic regressions and checkpoint**

Run the Step 2 command. Expected: all selected tests pass.

Run `git diff --check`. Expected: no errors.

### Task 9: Update version, private packaging, docs, and offline CI

**Files:**
- Modify: `VERSION`
- Modify: `.gitignore`
- Create: `.github/workflows/ci.yml`
- Modify: `PROJECT_CONTEXT.md`
- Modify: `media-missher/SKILL.md`
- Modify: `openclaw-media-missher/SKILL.md`
- Modify: `media-missher/agents/openai.yaml`
- Modify: `media-missher/references/commands.md`
- Modify: `media-missher/references/configuration.md`
- Modify: `media-missher/references/validation.md`
- Modify: `media-missher/references/troubleshooting.md`
- Modify: `media-missher/references/licensing.md`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_installer.py`
- Modify: `tests/test_active_residuals.py`

- [x] **Step 1: Write failing V15/privacy documentation tests**

Require exact `15.0.0`, both skill display names `Media@Missher V15`, documented flags/defaults/authorization/compatibility baseline, article/full-page fallback, screenshot metadata, safe diagnostics, private GitHub boundary, and no claim of completed live V15 collection.

Packaging tests must fail if a source/package contains `.superpowers`, `.env`, browser profiles, cookies, runtime `state`, recovery data, `screenshots`, PNG evidence, or BrowserSkill trace files.

- [x] **Step 2: Run packaging tests and verify failures**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_packaging.py tests/test_installer.py tests/test_active_residuals.py
```

Expected: V12 markers and missing V15 documentation/ignore rules fail.

- [x] **Step 3: Apply the V15 release metadata and docs**

Set `VERSION` to exactly:

```text
15.0.0
```

Add exact repository ignores without deleting the existing local preview directory:

```gitignore
.superpowers/
.env
.env.*
*.trace.json
screenshots/
run-*/screenshots/
```

Document BrowserSkill as an external optional dependency and retain the existing statement that public distribution is not authorized without license/provenance review. Do not add a public LICENSE in this task.

Create GitHub Actions CI that checks out source and runs the complete offline pytest command with sockets disabled, compile checks, all five `--help` entrypoints, residual scan, and packaging tests. It must define no secrets, browser service, CDP endpoint, platform navigation, artifact upload, or screenshot upload.

Update `PROJECT_CONTEXT.md` with the V15 architecture and mark live V15 acceptance as not yet performed. Preserve dated V12 evidence as historical evidence rather than rewriting it as V15 proof.

- [x] **Step 4: Run documentation/package tests and checkpoint**

Run the Step 2 command. Expected: all selected tests pass.

Run:

```bash
python3 tools/scan_active_residuals.py --root .
git diff --check
```

Expected: residual scan reports zero active findings and diff check passes.

### Task 10: Complete offline verification and hand back uncommitted code

**Files:**
- Verify all modified files
- Do not install, tag, push, publish, or perform live collection

- [x] **Step 1: Run all focused V15 tests with sockets disabled**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_browser_skill.py tests/test_runtime_detail_open.py \
  tests/test_runtime_screenshots.py tests/test_runtime_browser.py \
  tests/test_runtime_xhs.py tests/test_runtime_bilibili.py \
  tests/test_runtime_bilibili_production.py tests/test_runtime_storage.py \
  tests/test_runtime_cli.py tests/test_cli.py tests/test_runner.py \
  tests/test_validation.py tests/test_security.py tests/test_packaging.py \
  tests/test_installer.py tests/test_active_residuals.py
```

Expected: all pass, zero failures and zero skips.

- [x] **Step 2: Run the complete offline suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket
```

Expected: all tests pass with sockets disabled. Record the exact total.

- [x] **Step 3: Run compile, entrypoint, residual, and skill gates**

Run:

```bash
# Use an existing Python 3.11+ interpreter for runtime source and entrypoints.
task_pycache="$(mktemp -d)"
PYTHONPYCACHEPREFIX="$task_pycache" python3.11 -m compileall -q runtime media-missher openclaw-media-missher tools tests
PYTHONPYCACHEPREFIX="$task_pycache" python3.11 runtime/scripts/scrape_all.py --help >/dev/null
PYTHONPYCACHEPREFIX="$task_pycache" python3.11 runtime/scripts/scrape_bilibili.py --help >/dev/null
PYTHONPYCACHEPREFIX="$task_pycache" python3.11 runtime/scripts/scrape_xhs.py --help >/dev/null
PYTHONPYCACHEPREFIX="$task_pycache" python3.11 runtime/scripts/scrape_douyin.py --help >/dev/null
PYTHONPYCACHEPREFIX="$task_pycache" python3.11 runtime/scripts/scrape_weibo.py --help >/dev/null
PYTHONPYCACHEPREFIX="$task_pycache" python3 tools/scan_active_residuals.py --root .
PYTHONPYCACHEPREFIX="$task_pycache" python3 tools/install_media_missher.py --version
find "$task_pycache" -type f -delete
find "$task_pycache" -depth -type d -exec rmdir {} \;
```

Expected: compile exit `0`; five help commands exit `0`; residual scan returns zero; version output is `Media@Missher 15.0.0`.

- [x] **Step 4: Review scope and leave the worktree for supervision**

Run:

```bash
git diff --check
git status --short
git diff --stat
git diff -- . ':(exclude).superpowers/**'
```

Expected: only the planned V15 files are modified; no credentials, profile data, runtime state, screenshots, PNGs, traces, or generated releases appear. Do not stage or commit. Report exact test totals, changed files, assumptions, and any remaining limitation to task `019fef73-9c82-7023-b42f-e7ac52e41efa` for final supervision.

### Release-review remediation checklist

- [x] Align BrowserSkill lifecycle, numeric tab IDs, malformed-start recovery, and retryable stop behavior with CLI 0.1.10.
- [x] Poll and platform-bind exact detail pages; clean only newly owned pages and release popups per record.
- [x] Bind Xiaohongshu popup responses to the verified page, preserve ordinary timeout fallback, and limit randomized settle to complete mode.
- [x] Restore Bilibili creator feed state between records, dispose every ElementHandle, validate video screenshots, and reject search advanced modes.
- [x] Detect screenshot risk both before and after capture, and reject oversized full-page documents before PNG generation.
- [x] Enforce per-request screenshot obligations and reject `screenshot-mode=all` with count `0`.
- [x] Add atomic `--codex-only` installation without creating or requiring an OpenClaw root.
- [x] Pin CI and plan test environments through `runtime/requirements.lock` and document BrowserSkill upstream bundled skill sync.
- [x] Re-run focused and complete sockets-disabled suites plus compile, help, residual, and diff gates after remediation.

### Final-review remediation checklist

- [x] Accept and release only click-derived popups whose asynchronous opener is the source page; ignore unrelated context pages.
- [x] Fail closed on malformed BrowserSkill start output without guessing or stopping an unproven session.
- [x] Retry BrowserSkill stop at most once during `BrowserSession.close`, then propagate a bounded failure.
- [x] Wait for the next exact Bilibili dynamic target after restoring the creator feed and recheck risk before lookup.
- [x] Reject article and full-page screenshots above 16,777,216 pixels before Playwright generates PNG data.
- [x] Validate creator `screenshot-mode=all` against each selected platform's effective override-or-global count.
- [x] Re-run focused and complete sockets-disabled suites plus compile, help, residual, and diff gates after final review remediation.
