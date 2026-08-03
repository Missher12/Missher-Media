# Media@Missher Zero-Legacy Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy an independently authored four-platform runtime, preserve the validated Media@Missher behavior, and leave no owner-forbidden legacy markers or active legacy runtime directories.

**Architecture:** Keep the existing Codex adapter as the validation and output-conversion boundary, and add a small source-controlled Python runtime under `runtime/`. The runtime connects only to an existing authenticated Chromium CDP session, implements one focused collector per platform, stages private JSON, and is installed once into a shared local application-data home used by both Codex and OpenClaw launchers. Cutover is gated by offline contract tests, an active-path residual scan, black-box compatibility checks, and a four-platform live acceptance run; obsolete trees are moved to Trash only after those gates pass.

**Tech Stack:** Python 3.11, Playwright 1.45.0, Python standard library, pytest, pytest-asyncio, pytest-socket, SQLite

---

## File map

- `runtime/media_missher_runtime/models.py`: immutable requests, normalized records, result statuses, and count semantics.
- `runtime/media_missher_runtime/safety.py`: pacing, bounded pagination, response-risk classification, and stop propagation.
- `runtime/media_missher_runtime/storage.py`: private run directories, atomic JSON staging, and current-run manifests.
- `runtime/media_missher_runtime/browser.py`: existing-CDP connection, matching-page selection, same-origin requests, and test doubles.
- `runtime/media_missher_runtime/platforms/*.py`: independently authored Bilibili, Xiaohongshu, Douyin, and Weibo parsing and collection.
- `runtime/media_missher_runtime/cli.py`: compatible argument parsing and sequential dispatch.
- `runtime/scripts/*.py`: five minimal executable entrypoints.
- `runtime/requirements.lock`: exact runtime dependency pins.
- `tests/runtime_fixtures/`: synthetic platform payloads with no user data.
- `tests/test_runtime_*.py`: offline contracts, parser behavior, CLI behavior, and security boundaries.
- `tools/scan_active_residuals.py`: literal-marker and legacy-path scanner for the declared active roots.
- `tools/install_media_missher.py`: atomic shared-runtime, Codex Skill, and OpenClaw Skill installer.
- `openclaw-media-missher/`: compact OpenClaw Skill source that launches the shared runtime.
- `media-missher/scripts/media_missher_adapter.py`: resolve and invoke the new shared runtime only.
- `media-missher/scripts/preflight.py`: verify the shared runtime, CDP endpoint, entrypoints, and private output root.
- `media-missher/references/*.md`, `media-missher/SKILL.md`, `PROJECT_CONTEXT.md`: document the final architecture and recovery boundary.

## Non-negotiable implementation boundary

- Do not read, import, copy, transform, or patch either obsolete source tree while implementing `runtime/`.
- Use only this design, synthetic fixtures, existing public adapter tests, and authorized browser observations.
- Do not export cookies, capture credentials, solve captchas, rotate accounts, rotate proxies, or add fingerprint-evasion code.
- Do not remove an active directory until every offline gate and the live acceptance gate is green.
- Assemble owner-forbidden scan terms at runtime from harmless fragments so the active repository itself never contains the literal terms.

### Task 1: Runtime contract, fixtures, and active residual gate

**Files:**
- Create: `runtime/media_missher_runtime/__init__.py`
- Create: `runtime/media_missher_runtime/models.py`
- Create: `tests/test_runtime_models.py`
- Create: `tests/test_active_residuals.py`
- Create: `tools/scan_active_residuals.py`
- Create: `tests/runtime_fixtures/{bilibili,xhs,douyin,weibo}_{creator,search}.json`
- Create: `tests/runtime_fixtures/{bilibili,xhs}_complete.json`

- [ ] **Step 1: Write failing model and scanner tests**

```python
def test_zero_count_is_bounded_by_page_cap():
    request = CollectionRequest(platform="bilibili", count=0, page_cap=3)
    assert request.target_count is None
    assert request.page_cap == 3

def test_forbidden_terms_are_assembled_without_embedding_them():
    terms = forbidden_terms()
    assert len(terms) == 2
    assert all(term and term not in Path(__file__).read_text() for term in terms)
```

- [ ] **Step 2: Run the focused tests and observe import failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q tests/test_runtime_models.py tests/test_active_residuals.py`

Expected: FAIL because `runtime.media_missher_runtime.models` and `tools.scan_active_residuals` do not exist.

- [ ] **Step 3: Implement the immutable request/result contract and scanner**

```python
@dataclass(frozen=True)
class CollectionRequest:
    platform: str
    count: int
    page_cap: int = 20
    uid: str | None = None
    keyword: str | None = None
    complete: bool = False
    comment_limit: int = 0

    def __post_init__(self) -> None:
        if self.platform not in {"bilibili", "xhs", "douyin", "weibo"}:
            raise ValueError("unsupported platform")
        if self.count < 0 or self.page_cap < 1 or self.comment_limit < 0:
            raise ValueError("invalid collection limit")
        if bool(self.uid) == bool(self.keyword):
            raise ValueError("exactly one of uid or keyword is required")

    @property
    def target_count(self) -> int | None:
        return self.count or None
```

`forbidden_terms()` must return the two owner-supplied terms by joining tuple fragments. `scan_roots()` must skip `.git`, caches, generated outputs, historical memory/session folders, and Trash; it must scan file names, UTF-8 text, symlink targets, shebangs, and `pyvenv.cfg` metadata, and return structured findings with root, relative path, and match category.

- [ ] **Step 4: Add deterministic synthetic fixtures**

Each fixture must contain two records with distinct native IDs, one explicit zero, one null value, nested author/media data, and a duplicate item across pages. Complete fixtures must also include detail timestamps and engagement fields. Fixtures may contain no live account identifiers, cookies, tokens, or copied payloads.

- [ ] **Step 5: Run model, scanner, and fixture validation tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q tests/test_runtime_models.py tests/test_active_residuals.py`

Expected: PASS with zero findings for the new runtime paths.

- [ ] **Step 6: Commit**

```bash
git add runtime tests/runtime_fixtures tests/test_runtime_models.py tests/test_active_residuals.py tools/scan_active_residuals.py
git commit -m "test: define clean runtime contract"
```

### Task 2: Private storage and safety controls

**Files:**
- Create: `runtime/media_missher_runtime/storage.py`
- Create: `runtime/media_missher_runtime/safety.py`
- Create: `tests/test_runtime_storage.py`
- Create: `tests/test_runtime_safety.py`

- [ ] **Step 1: Write failing private-mode, atomic-write, pagination, and risk tests**

```python
def test_run_store_is_private(tmp_path):
    store = RunStore.create(tmp_path, run_id="fixed")
    output = store.write_json("bilibili", [{"id": "BV1", "liked": 0}])
    assert stat.S_IMODE(store.run_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text())[0]["liked"] == 0

@pytest.mark.parametrize("status,body", [(429, {}), (200, {"code": 461}), (200, {"code": 999})])
def test_risk_classifier_stops(status, body):
    assert classify_response(status, body).stop_all is True
```

- [ ] **Step 2: Run and confirm failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q tests/test_runtime_storage.py tests/test_runtime_safety.py`

Expected: FAIL on missing modules.

- [ ] **Step 3: Implement storage and safety primitives**

`RunStore.create()` must create `run-<id>` with mode `0700`, reject an existing run ID, write through a same-directory temporary file, `fsync`, `os.replace`, and chmod the final file to `0600`. `classify_response()` must return `RiskDecision(stop_all=True, reason=...)` for HTTP `403/429` and payload codes `461/471/999`, plus textual locked/blocked/cooldown/risk markers. `bounded_pages()` must never exceed `page_cap`; `Pacer` must use an injected sleeper and deterministic jitter source in tests.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q tests/test_runtime_storage.py tests/test_runtime_safety.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/media_missher_runtime/storage.py runtime/media_missher_runtime/safety.py tests/test_runtime_storage.py tests/test_runtime_safety.py
git commit -m "feat: add private staging and safety controls"
```

### Task 3: Existing-browser CDP boundary

**Files:**
- Create: `runtime/media_missher_runtime/browser.py`
- Create: `tests/test_runtime_browser.py`

- [ ] **Step 1: Write failing tests with fake browser contexts**

```python
@pytest.mark.asyncio
async def test_selects_existing_matching_page_without_navigation(fake_context):
    fake_context.pages = [FakePage("https://example.invalid"), FakePage("https://www.bilibili.com/")]
    session = BrowserSession(fake_context)
    page = await session.require_page("bilibili")
    assert page.url.startswith("https://www.bilibili.com/")
    assert all(not item.goto_calls for item in fake_context.pages)

@pytest.mark.asyncio
async def test_missing_page_is_precondition_failure(fake_context):
    with pytest.raises(PreconditionError, match="open and authenticated"):
        await BrowserSession(fake_context).require_page("xhs")
```

- [ ] **Step 2: Run and confirm the module is absent**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_browser.py`

Expected: FAIL on import.

- [ ] **Step 3: Implement page selection and same-origin request helpers**

`BrowserSession.connect(cdp_url)` must call `async_playwright().start()` and `chromium.connect_over_cdp(cdp_url)` only; it must never launch a browser. `require_page(platform)` must select from an exact hostname allowlist. `page_json(page, url, method, body)` must reject cross-origin destinations, execute `fetch` inside the selected page, return `(status, parsed_json)`, and never return request headers or cookies. `close()` must disconnect Playwright without closing the remote browser, contexts, or pages.

- [ ] **Step 4: Run focused tests with sockets disabled**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket python -m pytest -q --disable-socket tests/test_runtime_browser.py`

Expected: PASS and zero real socket attempts.

- [ ] **Step 5: Commit**

```bash
git add runtime/media_missher_runtime/browser.py tests/test_runtime_browser.py
git commit -m "feat: add existing browser session boundary"
```

### Task 4: Bilibili collector

**Files:**
- Create: `runtime/media_missher_runtime/platforms/__init__.py`
- Create: `runtime/media_missher_runtime/platforms/bilibili.py`
- Create: `tests/test_runtime_bilibili.py`

- [ ] **Step 1: Write failing creator, search, complete, dedupe, and risk tests**

```python
@pytest.mark.asyncio
async def test_bilibili_complete_preserves_native_values(fixture_browser):
    records = await BilibiliCollector(fixture_browser).collect(
        CollectionRequest(platform="bilibili", uid="42", count=2, complete=True)
    )
    assert [item["id"] for item in records] == ["BVfixture1", "BVfixture2"]
    assert records[0]["liked"] == 0
    assert records[1]["liked"] is None
    assert all(item["detail_completed"] for item in records)
```

- [ ] **Step 2: Run and observe failure**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_bilibili.py`

Expected: FAIL because `BilibiliCollector` is absent.

- [ ] **Step 3: Implement only the approved Bilibili contract**

Implement creator pagination, keyword search, native-ID deduplication, and optional detail enrichment. Normalize each record to `platform`, `id`, `url`, `title`, `author`, `published_at`, `liked`, `comments`, `shares`, `collected`, `detail_completed`, and `observed_at`. Stop when the target count is reached, the page cap is reached, or a response is exhausted. Complete mode must reject placeholder titles and must preserve unknown engagement values as null.

- [ ] **Step 4: Run collector and shared safety tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_bilibili.py tests/test_runtime_safety.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/media_missher_runtime/platforms tests/test_runtime_bilibili.py
git commit -m "feat: add Bilibili collector"
```

### Task 5: Douyin collector

**Files:**
- Create: `runtime/media_missher_runtime/platforms/douyin.py`
- Create: `tests/test_runtime_douyin.py`

- [ ] **Step 1: Write failing creator/search/cursor/dedupe/risk tests**

```python
@pytest.mark.asyncio
async def test_douyin_cursor_stops_at_requested_count(fixture_browser):
    records = await DouyinCollector(fixture_browser).collect(
        CollectionRequest(platform="douyin", uid="sec_fixture", count=2)
    )
    assert len(records) == 2
    assert len({item["id"] for item in records}) == 2
    assert fixture_browser.request_count == 2
```

- [ ] **Step 2: Run and observe missing collector failure**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_douyin.py`

Expected: FAIL on import.

- [ ] **Step 3: Implement the approved Douyin contract**

Implement creator cursor pagination and keyword search using the browser abstraction. Normalize to the shared fields, retain native IDs and canonical share URLs, treat empty cursors and `has_more=false` as exhaustion, deduplicate before count truncation, and pass every response through the global risk classifier.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_douyin.py tests/test_runtime_safety.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/media_missher_runtime/platforms/douyin.py tests/test_runtime_douyin.py
git commit -m "feat: add Douyin collector"
```

### Task 6: Weibo collector

**Files:**
- Create: `runtime/media_missher_runtime/platforms/weibo.py`
- Create: `tests/test_runtime_weibo.py`

- [ ] **Step 1: Write failing container, search, page-exhaustion, and text-normalization tests**

```python
@pytest.mark.asyncio
async def test_weibo_creator_preserves_zero_and_null(fixture_browser):
    records = await WeiboCollector(fixture_browser).collect(
        CollectionRequest(platform="weibo", uid="fixture_uid", count=2)
    )
    assert records[0]["liked"] == 0
    assert records[1]["liked"] is None
    assert all("<" not in item["text"] for item in records)
```

- [ ] **Step 2: Run and observe missing collector failure**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_weibo.py`

Expected: FAIL on import.

- [ ] **Step 3: Implement the approved Weibo contract**

Implement creator container pagination and keyword search. Parse only content cards, strip markup through `html.parser` rather than regular expressions, normalize canonical post URLs and native IDs, stop on missing cards or exhausted page markers, and classify all status/payload codes before parsing.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_weibo.py tests/test_runtime_safety.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/media_missher_runtime/platforms/weibo.py tests/test_runtime_weibo.py
git commit -m "feat: add Weibo collector"
```

### Task 7: Xiaohongshu collector and complete mode

**Files:**
- Create: `runtime/media_missher_runtime/platforms/xhs.py`
- Create: `tests/test_runtime_xhs.py`

- [ ] **Step 1: Write failing creator, search, detail, freshness, comments, checkpoint, and risk tests**

```python
@pytest.mark.asyncio
async def test_xhs_complete_requires_current_detail_observation(fixture_browser, fixed_clock):
    records = await XiaohongshuCollector(fixture_browser, clock=fixed_clock).collect(
        CollectionRequest(platform="xhs", uid="fixture_uid", count=1, complete=True, comment_limit=2)
    )
    assert records[0]["detail_attempted"] is True
    assert records[0]["engagement_observed_at"] == fixed_clock().isoformat()
    assert len(records[0]["comments_data"]) == 2
    assert records[0]["date_estimated"] is False
```

- [ ] **Step 2: Run and observe missing collector failure**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_xhs.py`

Expected: FAIL on import.

- [ ] **Step 3: Implement the approved Xiaohongshu contract**

Implement creator and keyword-search pagination, detail enrichment, bounded comments, native-ID deduplication, and a current-run checkpoint containing only IDs and observation times. Complete mode must require a detail attempt, non-estimated date, current-run engagement observation, and non-null liked/comments/collected. Any locked, blocked, cooldown, risk code, or incomplete current observation must stop or fail the record instead of inventing values.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio python -m pytest -q tests/test_runtime_xhs.py tests/test_runtime_safety.py tests/test_runtime_storage.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/media_missher_runtime/platforms/xhs.py tests/test_runtime_xhs.py
git commit -m "feat: add Xiaohongshu collector"
```

### Task 8: Compatible CLI and five entrypoints

**Files:**
- Create: `runtime/media_missher_runtime/cli.py`
- Create: `runtime/scripts/scrape_all.py`
- Create: `runtime/scripts/scrape_bilibili.py`
- Create: `runtime/scripts/scrape_xhs.py`
- Create: `runtime/scripts/scrape_douyin.py`
- Create: `runtime/scripts/scrape_weibo.py`
- Create: `runtime/requirements.lock`
- Create: `tests/test_runtime_cli.py`
- Create: `tests/test_runtime_entrypoints.py`

- [ ] **Step 1: Write failing parser, sequential-order, risk-stop, and special-path tests**

```python
def test_all_platforms_are_sequential(fake_dispatcher, tmp_path):
    code = main(["creator", "--platforms", "bilibili,xhs,douyin,weibo", "--count", "1", "--output-dir", str(tmp_path)])
    assert code == 0
    assert fake_dispatcher.events == ["start:bilibili", "end:bilibili", "start:xhs", "end:xhs", "start:douyin", "end:douyin", "start:weibo", "end:weibo"]
```

- [ ] **Step 2: Run and observe missing CLI failure**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q tests/test_runtime_cli.py tests/test_runtime_entrypoints.py`

Expected: FAIL on import or missing scripts.

- [ ] **Step 3: Implement compatible routing**

Support creator mode with `--platforms`, per-platform UID arguments, `--count`, per-platform count overrides, `--bilibili-complete`, `--xhs-complete`, `--xhs-comments`, `--cdp-url`, and `--output-dir`; support search mode with one `--platform`, `--keyword`, `--count`, `--cdp-url`, and `--output-dir`. Dispatch platforms sequentially, terminate all further work on `RiskStop`, isolate non-risk failures into the manifest, and return `0` only when all selected platforms succeed.

- [ ] **Step 4: Add dependency lock and executable shims**

`runtime/requirements.lock` must pin `playwright==1.45.0`. Every shim must insert its deployed runtime parent into `sys.path`, import `main`, and pass a fixed platform only for single-platform shims. No shim may embed an absolute user path.

- [ ] **Step 5: Run entrypoints from a copied path containing spaces and `@`**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket python -m pytest -q --disable-socket tests/test_runtime_cli.py tests/test_runtime_entrypoints.py`

Expected: PASS; all five `--help` invocations exit `0` from the special path.

- [ ] **Step 6: Commit**

```bash
git add runtime tests/test_runtime_cli.py tests/test_runtime_entrypoints.py
git commit -m "feat: add clean runtime entrypoints"
```

### Task 9: Migrate the Codex adapter and preflight

**Files:**
- Modify: `media-missher/scripts/media_missher_adapter.py`
- Modify: `media-missher/scripts/preflight.py`
- Modify: `media-missher/scripts/run_collection.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_preflight.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_external_contract.py`
- Modify: `tests/test_portability.py`
- Modify: `tests/test_security.py`

- [ ] **Step 1: Change tests to require the shared runtime home**

Tests must construct the default home with `Path.home() / ".local" / "share" / "media-missher"`, require `current/scripts/scrape_all.py`, the four single-platform shims, and `venv/bin/python`, and assert that no configuration key or diagnostic resolves any obsolete engine root.

- [ ] **Step 2: Run and observe failures against the old resolver**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-socket python -m pytest -q --disable-socket tests/test_config.py tests/test_preflight.py tests/test_runner.py tests/test_external_contract.py tests/test_portability.py tests/test_security.py`

Expected: FAIL because the adapter still resolves the old engine layout.

- [ ] **Step 3: Replace engine resolution with `RuntimeLayout`**

Add a frozen `RuntimeLayout(home, current, python, state)` built from an optional `MEDIA_MISSHER_HOME` or the default local-share path. Preflight must validate exact paths, executable Python, all five scripts, writable private state, Python 3.11+, Playwright import, and a reachable CDP version endpoint. The runner must pass absolute clean-runtime script paths without a shell and keep the existing process-group timeout behavior.

- [ ] **Step 4: Run the migrated adapter suite**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-socket python -m pytest -q --disable-socket tests/test_config.py tests/test_preflight.py tests/test_runner.py tests/test_external_contract.py tests/test_portability.py tests/test_security.py`

Expected: PASS with fake shared-runtime fixtures and zero socket access outside explicit preflight fakes.

- [ ] **Step 5: Commit**

```bash
git add media-missher/scripts tests/test_config.py tests/test_preflight.py tests/test_runner.py tests/test_external_contract.py tests/test_portability.py tests/test_security.py
git commit -m "refactor: point adapter at shared runtime"
```

### Task 10: Atomic installer and compact OpenClaw Skill

**Files:**
- Create: `tools/install_media_missher.py`
- Create: `openclaw-media-missher/SKILL.md`
- Create: `openclaw-media-missher/scripts/run_collection.py`
- Create: `openclaw-media-missher/scripts/preflight.py`
- Create: `tests/test_installer.py`
- Create: `tests/test_openclaw_packaging.py`

- [ ] **Step 1: Write failing install, upgrade, rollback, permission, and packaging tests**

```python
def test_install_is_atomic_and_keeps_previous_release(tmp_path):
    result = install(source=PROJECT_ROOT, home=tmp_path / "runtime-home", codex_root=tmp_path / "codex", openclaw_root=tmp_path / "openclaw")
    assert result.current.joinpath("scripts/scrape_all.py").is_file()
    assert result.previous is None
    assert stat.S_IMODE(result.state.stat().st_mode) == 0o700
```

- [ ] **Step 2: Run and observe missing installer/package failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q tests/test_installer.py tests/test_openclaw_packaging.py`

Expected: FAIL because the installer and package are absent.

- [ ] **Step 3: Implement staged installation and rollback metadata**

The installer must copy `runtime/` into a sibling staging directory, scan it, create or reuse `venv`, install from `requirements.lock` with `python -m pip`, validate imports and all `--help` commands, then atomically rename `current` to `previous-<timestamp>` and staging to `current`. Install Codex and OpenClaw Skills through the same staging/rename pattern. On any failure, restore the previous `current`; never delete the old active engine in this task.

- [ ] **Step 4: Implement compact OpenClaw launchers**

The OpenClaw package must contain instructions, a preflight wrapper, and a collection wrapper that resolve the same `RuntimeLayout`. It must contain no platform implementations, dependency environments, copied browser assets, user data, or absolute personal paths.

- [ ] **Step 5: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-socket python -m pytest -q --disable-socket tests/test_installer.py tests/test_openclaw_packaging.py`

Expected: PASS using a fake pip executor; no network and no writes outside `tmp_path`.

- [ ] **Step 6: Commit**

```bash
git add tools/install_media_missher.py openclaw-media-missher tests/test_installer.py tests/test_openclaw_packaging.py
git commit -m "feat: add atomic shared runtime installer"
```

### Task 11: Full offline, compatibility, and residual verification

**Files:**
- Create: `tests/test_runtime_compatibility.py`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_output.py`
- Modify: `tests/test_validation.py`

- [ ] **Step 1: Add black-box normalized compatibility assertions**

For each platform and mode, run the retained oracle and new runtime in separate subprocesses against the same synthetic fixture provider. Normalize run IDs, observed timestamps, and temporary paths, then assert equality of native IDs, record counts, field names, Python value types, null-versus-zero distinctions, ordering, complete flags, and failure statuses. Do not import oracle implementation modules.

- [ ] **Step 2: Run the compatibility test and fix only observable contract differences**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket python -m pytest -q --disable-socket tests/test_runtime_compatibility.py`

Expected: PASS for creator and search on all four platforms and complete mode on Bilibili and Xiaohongshu.

- [ ] **Step 3: Run the complete offline suite**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket python -m pytest -q -p no:cacheprovider --disable-socket`

Expected: all retained and new tests PASS; zero socket attempts.

- [ ] **Step 4: Run compile, help, secret, and active-repository scans**

```bash
python3 -m compileall -q runtime media-missher openclaw-media-missher tools
python3 tools/scan_active_residuals.py --root .
git grep -nE '(cookie|authorization|token)[[:space:]]*=' -- ':!tests/runtime_fixtures'
```

Expected: compile succeeds; residual scanner exits `0` with zero findings; secret grep has no hard-coded credential assignments.

- [ ] **Step 5: Commit**

```bash
git add tests tools runtime media-missher openclaw-media-missher
git commit -m "test: prove clean runtime compatibility"
```

### Task 12: Documentation and project context

**Files:**
- Modify: `media-missher/SKILL.md`
- Modify: `media-missher/references/configuration.md`
- Modify: `media-missher/references/commands.md`
- Modify: `media-missher/references/troubleshooting.md`
- Modify: `media-missher/references/validation.md`
- Modify: `media-missher/references/licensing.md`
- Modify: `PROJECT_CONTEXT.md`

- [ ] **Step 1: Update documentation tests to reject obsolete paths and require shared-home commands**

The packaging test must require preflight, creator, search, validation, installation, recovery, output privacy, risk-stop, and no-remote-write documentation. It must reject any absolute user path and any forbidden term.

- [ ] **Step 2: Run and observe documentation failures**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q tests/test_packaging.py tests/test_active_residuals.py`

Expected: FAIL until references describe the new architecture.

- [ ] **Step 3: Rewrite references around the shared runtime**

Document `MEDIA_MISSHER_HOME`, the default derived local-share location, five entrypoints, private output rules, exact preflight failures, authorized existing-browser prerequisites, risk-stop behavior, atomic update, `previous-<timestamp>` recovery, and the fact that Feishu output is validation-only with no remote write.

- [ ] **Step 4: Update `PROJECT_CONTEXT.md`**

Record the four-platform scope, source/runtime/adapter boundaries, installed locations, test commands, live acceptance procedure, known platform volatility, and recoverable cutover process.

- [ ] **Step 5: Run packaging and residual tests**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest python -m pytest -q tests/test_packaging.py tests/test_active_residuals.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add media-missher PROJECT_CONTEXT.md tests/test_packaging.py tests/test_active_residuals.py
git commit -m "docs: document clean shared runtime"
```

### Task 13: Staged local deployment and four-platform live acceptance

**Files:**
- Generated outside repository: `~/.local/share/media-missher/{current,venv,state}`
- Staged outside repository: temporary Codex and OpenClaw Skill directories
- Evidence: private run manifest under the configured output root

- [ ] **Step 1: Record read-only pre-cutover manifests**

Run explicit `find`, `du`, `shasum`, current preflight, browser CDP version, Python version, and five entrypoint checks. Store only file lists, sizes, hashes, and versions; do not record cookies, browser storage, headers, or content payloads.

- [ ] **Step 2: Install the clean runtime without touching the old active engine**

Run: `python3 tools/install_media_missher.py --runtime-only`

Expected: shared `current`, `venv`, and private `state` exist; all five `--help` checks and the runtime-only residual scan pass.

- [ ] **Step 3: Preflight staged Codex and OpenClaw launchers**

Point both staged packages at the shared home and run their preflight commands. Expected: same runtime root, same interpreter, reachable existing CDP endpoint, all five scripts executable, output root private.

- [ ] **Step 4: Run one authorized sequential creator acceptance**

Select Bilibili, Xiaohongshu, Douyin, and Weibo with count `1`, Bilibili complete mode, Xiaohongshu complete mode, bounded Xiaohongshu comments, JSON staging, and no Feishu write. If one matching page is absent, open one temporary authorized page for that platform, validate once, and close only that temporary page afterward.

- [ ] **Step 5: Validate live evidence**

Run the existing `validate_run.py` against the current run and assert one native record per platform, non-placeholder IDs/links, current observation timestamps, complete-mode fields, no risk stop, no timeout, no credential material, and no Feishu artifact or remote write.

- [ ] **Step 6: Stop on any failed gate**

Do not cut over if any platform fails, any risk signal appears, any required field is missing, or the residual scan is nonzero. Preserve the old active directories unchanged and report the exact failed gate.

### Task 14: Atomic cutover and recoverable removal

**Files:**
- Installed: `/Users/missher/.codex/skills/media-missher`
- Installed: `/Users/missher/.openclaw/workspace/skills/media-missher`
- Moved only after all gates: the two exact obsolete active trees identified in the approved manifest

- [ ] **Step 1: Validate exact destructive targets**

Resolve each target with `realpath`, require exact equality with the two approved manifest roots, reject `/`, the home directory, either workspace root, symlinks, missing paths, and paths containing glob characters. Print the target, size, and destination before moving.

- [ ] **Step 2: Stage both replacement Skills and run their preflight**

Install to sibling temporary directories, run both preflights against the shared runtime, and scan the staged packages. Expected: all checks PASS and zero residual findings.

- [ ] **Step 3: Move obsolete trees to unique recoverable Trash destinations**

Use `/bin/mv` with exact absolute source and destination arguments. Destinations must include an ISO timestamp and must not pre-exist. Move the separate obsolete project and the replaced OpenClaw active Skill only after Step 2 passes; never use recursive deletion.

- [ ] **Step 4: Atomically place the replacement Skills**

Rename the staged Codex and OpenClaw Skill directories into their exact active locations. Run preflight immediately. If either preflight fails, move the replacement aside and restore the prior OpenClaw Skill from Trash before returning failure.

- [ ] **Step 5: Re-run every active-path gate**

Scan the repository, installed Codex Skill, installed OpenClaw Skill, shared runtime `current`, shared runtime `state`, and virtual-environment metadata. Confirm both obsolete original locations are absent, all five entrypoints work, both preflights pass, and a non-network validation of the retained live evidence passes.

- [ ] **Step 6: Record recovery locations**

Write the exact Trash destinations and restoration commands to private local handoff evidence outside the installed Skill. Do not copy old names or paths into the active repository or Skill documentation.

### Task 15: Final reviews and completion verification

**Files:**
- Modify only if reviewers find defects: files already listed in Tasks 1-14

- [ ] **Step 1: Request specification review**

Reviewer checks every design success criterion against committed code and fresh command output, with special attention to four-platform behavior, no remote write, safety stops, active residual count, and recoverable removal.

- [ ] **Step 2: Request code-quality and security review**

Reviewer checks path validation, subprocess argument construction, permissions, atomic updates, symlink handling, JSON parsing, null preservation, pagination bounds, Playwright lifecycle, and absence of credential capture or platform-control bypasses.

- [ ] **Step 3: Run the final offline suite from a clean checkout**

Run: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest --with pytest-asyncio --with pytest-socket python -m pytest -q -p no:cacheprovider --disable-socket`

Expected: all tests PASS.

- [ ] **Step 4: Run final installed-state verification**

Run both installed preflights, all five runtime `--help` commands, compile checks, the active-path residual scanner, permission checks, original-location absence checks, and current-run validation. Expected: every check PASS and residual count `0`.

- [ ] **Step 5: Commit reviewer fixes and completion evidence**

```bash
git add runtime media-missher openclaw-media-missher tools tests PROJECT_CONTEXT.md docs
git commit -m "chore: complete clean runtime cutover"
```

- [ ] **Step 6: Hand off concise evidence**

Report changed files by subsystem, exact offline test count, four live platform statuses, active residual count, installed preflight status, Trash recovery status, and any current platform limitation. Do not claim complete until all fresh evidence exists.
