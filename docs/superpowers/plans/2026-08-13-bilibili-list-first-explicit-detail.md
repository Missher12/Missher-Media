# Media@Missher V15.2.1 Bilibili List-First and Explicit-Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Bilibili creator collection validate the creator Feed as complete list evidence without opening details for an absent collection count, while providing an explicit same-CDP temporary-tab detail mode with exact native-ID binding, safe cleanup, and truthful partial results.

**Architecture:** Separate list evidence from detail evidence across the runtime model, CLI, collector, adapter, and validator. The collector first finalizes and publishes a verified list snapshot; only `bilibili_detail` or `screenshot_mode == "all"` creates a Media-owned temporary tab in the source page's existing Chrome context, attaches an exact main-document observer before one allowlisted navigation, validates the final native URL, enriches fill-only engagement fields, and closes that tab. Risk remains non-retryable, while non-risk detail shortfalls retain list records and become incomplete rather than zero-record failures.

**Tech Stack:** Python 3.11+, Playwright async CDP, standard-library dataclasses/argparse, pytest/pytest-asyncio/pytest-socket, existing atomic installer and private run store.

---

## Governing specification

Implement only the approved contract in:

- `docs/superpowers/specs/2026-08-13-bilibili-list-first-explicit-detail-design.md`

The older `docs/superpowers/specs/2026-08-13-bilibili-cdp-dynamic-completion-design.md` and `docs/superpowers/plans/2026-08-13-bilibili-cdp-dynamic-completion.md` are superseded for V15.2.1. Do not preserve their rule that missing `collected` automatically opens a DOM card.

## File map

- Modify `runtime/media_missher_runtime/models.py`: add the explicit `bilibili_detail` request field and reject invalid platform/search combinations.
- Modify `runtime/media_missher_runtime/cli.py`: expose `--bilibili-detail`, forward it only to Bilibili, classify detail shortfalls, and persist published Bilibili list evidence on a risk stop.
- Modify `runtime/media_missher_runtime/browser.py`: expose same-context Media-owned temporary-page creation and release helpers.
- Modify `runtime/media_missher_runtime/platforms/bilibili.py`: compute list completeness first, remove metric-driven DOM opening, implement direct native-ID detail navigation, publish progress, and retain list records on non-risk detail failure.
- Modify `media-missher/scripts/media_missher_adapter.py`: add and validate `bilibili_detail`, forward the flag, and make Bilibili validation type-aware with optional `collected`.
- Modify `media-missher/scripts/run_collection.py`: expose and forward `--bilibili-detail`.
- Modify `media-missher/scripts/validate_run.py`: expose the same validation evidence-level switch without granting navigation.
- Modify `tests/test_runtime_cli.py`: runtime request, manifest, and partial-evidence regression coverage.
- Modify `tests/test_runtime_browser.py`: same-context temporary-page ownership and cleanup coverage.
- Modify `tests/test_runtime_bilibili_production.py`: list-only, direct-detail, risk, mismatch, screenshot, and preservation coverage.
- Modify `tests/test_validation.py`: outer list/detail evidence and metric-type validation.
- Modify `tests/test_cli.py`, `tests/test_runner.py`, and `tests/test_external_contract.py`: public adapter and command-forwarding coverage.
- Modify `media-missher/SKILL.md`, `openclaw-media-missher/SKILL.md`, `media-missher/references/commands.md`, `media-missher/references/validation.md`, `README.md`, and `PROJECT_CONTEXT.md`: document the selected evidence levels and dated verification.

Keep `VERSION` at `15.2.1`. Do not tag, merge, publish a GitHub Release, or replace installed V15.2.0 until live acceptance succeeds.

### Task 1: Add one explicit evidence-level request contract

**Files:**
- Modify: `runtime/media_missher_runtime/models.py`
- Modify: `runtime/media_missher_runtime/cli.py`
- Test: `tests/test_runtime_cli.py`

- [ ] **Step 1: Write RED model tests for the new boolean boundary**

Add tests proving a Bilibili creator request accepts the new field and that search or another platform rejects it:

```python
def test_runtime_model_accepts_explicit_bilibili_creator_detail() -> None:
    request = CollectionRequest(
        platform="bilibili",
        count=10,
        uid="creator",
        complete=True,
        bilibili_detail=True,
    )

    assert request.bilibili_detail is True


@pytest.mark.parametrize(
    ("platform", "identity"),
    [
        ("xhs", {"uid": "creator"}),
        ("bilibili", {"keyword": "topic"}),
    ],
)
def test_runtime_model_rejects_bilibili_detail_outside_bilibili_creator(
    platform: str,
    identity: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="Bilibili detail"):
        CollectionRequest(
            platform=platform,
            count=1,
            bilibili_detail=True,
            **identity,
        )
```

- [ ] **Step 2: Run the model tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_cli.py -k 'runtime_model_accepts_explicit_bilibili_creator_detail or runtime_model_rejects_bilibili_detail'
```

Expected: FAIL because `CollectionRequest` does not accept `bilibili_detail`.

- [ ] **Step 3: Add the minimal frozen-model field and validation**

Add this field after `complete` in `runtime/media_missher_runtime/models.py`:

```python
bilibili_detail: bool = False
```

Add these guards in `__post_init__`:

```python
if not isinstance(self.bilibili_detail, bool):
    raise ValueError("Bilibili detail must be an explicit boolean")
if self.bilibili_detail and (
    self.platform != "bilibili" or self.keyword is not None
):
    raise ValueError("Bilibili detail requires Bilibili creator collection")
```

Include `self.bilibili_detail` in the existing Bilibili-search advanced-mode rejection so no search caller can bypass the model guard.

- [ ] **Step 4: Write RED parser tests for authorization and forwarding**

Add parser/request tests covering all three cases:

```python
def test_runtime_cli_forwards_explicit_bilibili_detail() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "creator", "--platforms", "bilibili",
        "--bilibili-uid", "creator", "--count", "10",
        "--bilibili-complete", "--bilibili-detail",
        "--allow-navigation", "--output-dir", "/tmp/private-output",
    ])

    request = _requests_from_args(parser, args)[0]
    assert request.complete is True
    assert request.bilibili_detail is True
```

Also assert `--bilibili-detail` without `--allow-navigation` is a parser error and that selecting only XHS with the flag is a parser error.

- [ ] **Step 5: Add the creator-only CLI flag and request routing**

Add to the creator parser:

```python
creator.add_argument(
    "--bilibili-detail",
    action="store_true",
    help="Explicitly open exact Bilibili detail pages in Media-owned temporary tabs",
)
```

Before constructing creator requests, enforce:

```python
if args.bilibili_detail and "bilibili" not in platforms:
    parser.error("Bilibili detail mode requires the Bilibili platform")
if args.bilibili_detail and not args.allow_navigation:
    parser.error("Bilibili detail mode requires --allow-navigation")
```

Forward only to the Bilibili request:

```python
bilibili_detail=(platform == "bilibili" and args.bilibili_detail),
```

- [ ] **Step 6: Run the focused runtime request tests and verify GREEN**

Run the Task 1 node IDs plus existing Bilibili/XHS advanced-mode tests. Expected: PASS, with XHS default complete behavior unchanged.

- [ ] **Step 7: Commit the request-contract slice**

```bash
git add runtime/media_missher_runtime/models.py runtime/media_missher_runtime/cli.py tests/test_runtime_cli.py
git commit -m "feat: add explicit Bilibili detail contract"
```

### Task 2: Prove and implement type-aware list completeness

**Files:**
- Modify: `runtime/media_missher_runtime/platforms/bilibili.py`
- Modify: `tests/test_runtime_bilibili_production.py`

- [ ] **Step 1: Write RED tests for optional collection evidence**

Add one free-form dynamic Feed test with numeric liked/comments/shares and no favorite field:

```python
def test_list_complete_keeps_absent_collected_null_without_detail_open() -> None:
    item = _item("123456", comment={"count": 4})
    item["modules"]["module_stat"]["like"] = {"count": 3}
    item["modules"]["module_stat"]["forward"] = {"count": 5}
    page = CapturePage(responses=[_feed(item, has_more=False)])
    browser = ProductionBrowser(page)

    record = _run(collect_creator(
        CollectionRequest(
            platform="bilibili",
            count=1,
            uid="synthetic-user",
            complete=True,
        ),
        browser,
    ))[0]

    assert record["collected"] is None
    assert record["missing_fields"] == []
    assert record["complete"] is True
    assert record["detail_attempted"] is False
    assert browser.temporary_pages_created == 0
```

Add a parameterized companion test proving `None`, `-1`, `True`, `"4"`, and `1.5` for each required list metric `liked`, `comments`, and `shares` remains incomplete, while `collected=None` is accepted and a supplied `collected` must be a non-negative integer.

- [ ] **Step 2: Run the new list tests and verify RED**

Expected: the absent-collection test FAILS because `collected` is currently appended to `missing_fields` and triggers the old detail path.

- [ ] **Step 3: Introduce one strict count predicate**

Add and reuse this helper:

```python
def _is_nonnegative_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
```

Do not coerce strings, booleans, floats, or unknown values.

- [ ] **Step 4: Make list completion independent of `collected` and detail**

Replace the current detail-centric completion call with a list finalizer:

```python
def _finalize_record(
    record: dict[str, Any],
    *,
    detail_required: bool,
    detail_received: bool,
) -> None:
    missing = _missing_completion_fields(
        record,
        detail_received,
        detail_required=detail_required,
    )
    record["detail_completed"] = detail_received
    record["complete"] = not missing
    record["missing_fields"] = missing
    record["quality_score"] = _quality_score(record)
```

Change `_missing_completion_fields` so only `liked`, `comments`, and `shares` are required counts. Validate `collected` only when non-null:

```python
for field in ("liked", "comments", "shares"):
    if not _is_nonnegative_count(record.get(field)):
        missing.append(field)
collected = record.get("collected")
if collected is not None and not _is_nonnegative_count(collected):
    missing.append("collected")
```

Keep exact identity, meaningful title/content, and date checks. Do not turn `None` into zero.

- [ ] **Step 5: Finalize every Feed record before any optional detail work**

Immediately after `_collect_feed_pages`, run:

```python
for record in records:
    record["detail_attempted"] = False
    record["detail_source"] = "list_api"
    _finalize_record(
        record,
        detail_required=False,
        detail_received=False,
    )
```

Ordinary requests may carry truthful per-record `complete` evidence even when the runtime was not asked to enforce strict completion.

- [ ] **Step 6: Remove all metric-driven open routing**

Replace `_needs_dynamic_open` with an explicit predicate:

```python
def _needs_explicit_detail(request: CollectionRequest) -> bool:
    return request.bilibili_detail or request.screenshot_mode == "all"
```

`request.complete`, `request.browser_assist`, and `collected is None` must not appear in this predicate. `screenshot_mode == "opened"` does not create an open; it only captures a detail opened for `bilibili_detail`.

- [ ] **Step 7: Run the full Bilibili list-only test group and verify GREEN**

Include mixed video/free-form/image/article/forward Feed fixtures and assert order, exact count, no DOM locator call, no temporary page, no screenshot, and no bridge call.

- [ ] **Step 8: Commit the list-evidence slice**

```bash
git add runtime/media_missher_runtime/platforms/bilibili.py tests/test_runtime_bilibili_production.py
git commit -m "fix: make Bilibili creator evidence list first"
```

### Task 3: Add same-context temporary-page ownership primitives

**Files:**
- Modify: `runtime/media_missher_runtime/browser.py`
- Modify: `tests/test_runtime_browser.py`

- [ ] **Step 1: Write RED ownership tests**

Add tests that call a public helper from a prepared source page and assert:

```python
temporary = _run(session.new_temporary_page(source_page))

assert source_page.context.new_page_calls == 1
assert temporary in session._temporary_pages
assert source_page.closed is False
```

Add rejection tests for a closed source page, a source page not present in its context, and a context not owned by the connected browser.

- [ ] **Step 2: Write RED release and cancellation-safe cleanup tests**

Assert `release_temporary_page` closes and untracks only the Media-owned page; calling it twice is harmless; `BrowserSession.close()` still attempts every owned temporary page after one close failure and never closes the user's source page.

- [ ] **Step 3: Write RED preflight-reuse tests**

Cover the current source of unnecessary tabs explicitly:

```python
def test_authorized_authentication_reuses_one_existing_platform_page() -> None:
    existing = PlatformPage("https://space.bilibili.com/creator/dynamic")
    context = BrowserContext([existing])
    session = BrowserSession(
        Playwright(),
        Browser([context]),
        allow_navigation=True,
    )

    selected = _run(session.require_authenticated_page("bilibili"))

    assert selected is existing
    assert context.new_page_calls == 0
    assert session._temporary_pages == []
```

Retain the existing fallback test proving one Media-owned platform page may be created when there is no Bilibili page and navigation was explicitly authorized. Multiple matching pages or contexts must still fail closed as ambiguous.

- [ ] **Step 4: Run the ownership tests and verify RED**

Expected: FAIL because only private `_register_temporary_page` and `_release_temporary_page` exist, and the current authorized preflight creates a new platform page even when one exact existing page is available.

- [ ] **Step 5: Make authenticated preflight reuse one existing page first**

Refactor `require_authenticated_page` to this decision order:

```python
def _matching_platform_pages(self, platform: str) -> list[Any]:
    hosts = _HOSTS.get(platform)
    if hosts is None:
        raise ValueError("unsupported platform")
    return [
        page
        for context in self._browser.contexts
        for page in context.pages
        if not _page_is_closed(page)
        and urlparse(page.url).hostname in hosts
    ]


prepared = self._prepared_pages.get(platform)
if prepared is not None and not _page_is_closed(prepared):
    page = prepared
else:
    self._prepared_pages.pop(platform, None)
    matches = self._matching_platform_pages(platform)
    if len(matches) > 1:
        raise PreconditionError(
            f"open/authenticated {platform} page is ambiguous"
        )
    if matches:
        page = matches[0]
    elif self.allow_navigation:
        page = await self._open_temporary_platform_page(platform)
    else:
        raise PreconditionError(
            f"open/authenticated {platform} page is required"
        )
```

Make `require_page` reuse `_matching_platform_pages` so selection semantics have one implementation. The result must be: one existing exact platform page is reused, zero pages may create one authorized temporary entry page, and ambiguity never creates another page.

- [ ] **Step 6: Add the public same-context helper**

Implement this bounded surface:

```python
async def new_temporary_page(self, source_page: Any) -> Any:
    if _page_is_closed(source_page):
        raise PreconditionError("source page is closed")
    context = getattr(source_page, "context", None)
    if context is None or not any(
        context is candidate for candidate in self._browser.contexts
    ):
        raise PreconditionError("source page context is not browser-owned")
    if not any(source_page is candidate for candidate in context.pages):
        raise PreconditionError("source page is not present in its context")
    page = await context.new_page()
    self._register_temporary_page(page)
    return page

async def release_temporary_page(self, page: Any) -> None:
    await self._release_temporary_page(page)
```

The helper must not select another context, navigate, copy cookies, or close the source page.

- [ ] **Step 7: Use `_register_temporary_page` inside the existing auth helper**

Replace direct `_temporary_pages.append(page)` in `_open_temporary_platform_page` with `_register_temporary_page(page)` so all ownership tracking has one implementation. Do not alter the existing authentication behavior.

- [ ] **Step 8: Run all browser-session tests and verify GREEN**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_browser.py
```

- [ ] **Step 9: Commit the browser-ownership slice**

```bash
git add runtime/media_missher_runtime/browser.py tests/test_runtime_browser.py
git commit -m "feat: own same-context Bilibili detail tabs"
```

### Task 4: Implement exact direct detail navigation without DOM clicks

**Files:**
- Modify: `runtime/media_missher_runtime/platforms/bilibili.py`
- Modify: `tests/test_runtime_bilibili_production.py`

- [ ] **Step 1: Replace obsolete DOM-click fakes with temporary-page fakes**

Extend the production test browser with:

```python
async def new_temporary_page(self, source_page: CapturePage) -> CapturePage:
    assert source_page is self.page
    self.temporary_pages_created += 1
    self.detail_page = self.detail_pages.pop(0)
    return self.detail_page

async def release_temporary_page(self, page: CapturePage) -> None:
    self.released_pages.append(page)
    page.closed = True
```

Record every navigation URL and allowed-host tuple. Do not silently emulate a DOM click.

- [ ] **Step 2: Write RED exact-URL tests for both native types**

Parameterize the expected destination:

```python
@pytest.mark.parametrize(
    ("record_kind", "expected_url"),
    [
        ("video", "https://www.bilibili.com/video/BVdetail1"),
        ("dynamic", "https://t.bilibili.com/123456"),
    ],
)
def test_explicit_detail_uses_one_same_context_temporary_page(
    record_kind: str,
    expected_url: str,
) -> None:
    # Build exact Feed and detail fixtures for each kind.
    # Assert one temporary page, one exact navigation, no locator/click,
    # exact-ID validation, detail_attempted/completed, and one release.
```

Run with `bilibili_detail=True`, `complete=True`, and `allow_navigation=True` on the fake browser.

- [ ] **Step 3: Write RED mismatch and redirect tests**

Add tests where the final video BVID or dynamic ID differs from the Feed native ID. Assert the record retains list values, `detail_attempted is True`, `detail_completed is False`, `complete is False`, `"detail" in missing_fields`, no screenshot occurs, and the temporary page is released.

- [ ] **Step 4: Generalize the exact main-document response observer**

Replace `_DynamicDetailResponseObserver` with an observer accepting one exact URL predicate:

```python
@dataclass(slots=True)
class _DetailResponseObserver:
    context: Any
    matches_expected_url: Callable[[object], bool]
    risk_code: str | None = None

    def _on_response(self, response: Any) -> None:
        request = getattr(response, "request", None)
        if getattr(request, "resource_type", None) != "document":
            return
        if not self.matches_expected_url(getattr(response, "url", None)):
            return
        status = getattr(response, "status", None)
        if status in {403, 429}:
            self.risk_code = f"http-{status}"
```

Retain strict attach/remove behavior. The observer must attach before navigation and never treat API/subresource/wrong-ID responses as exact detail evidence.

- [ ] **Step 5: Implement one direct detail method with unconditional cleanup**

Use this control flow in `_open_detail_record`:

```python
detail_page = await self.browser.new_temporary_page(source_page)
record["detail_attempted"] = True
try:
    observer = _DetailResponseObserver(
        getattr(detail_page, "context", None),
        _detail_url_matcher(record),
    )
    with observer:
        await self._navigate(detail_page, _detail_url(record))
    if observer.risk_code is not None:
        raise CollectionStopped(observer.risk_code)
    detail_received = await self._read_and_merge_exact_detail(detail_page, record)
    record["detail_source"] = "detail_api" if detail_received else "list_api"
    _finalize_record(
        record,
        detail_required=True,
        detail_received=detail_received,
    )
    if detail_received and self.request.screenshot_mode in {"opened", "all"}:
        await self._capture_screenshot(
            detail_page,
            record,
            str(record["native_id"]),
        )
finally:
    await self.browser.release_temporary_page(detail_page)
```

Before navigation, `_detail_url` must reject `/`, query, fragment, empty IDs, or identifiers failing the existing BVID/dynamic-ID grammar. It may return only `_video_page_url(bvid)` or `_dynamic_page_url(dynamic_id)`.

- [ ] **Step 6: Preserve Feed engagement metrics during detail merge**

Keep `_merge_dynamic_detail` fill-only and change video engagement merging to the same rule. Detail content/date may replace list preview content only when `bilibili_detail` is true; screenshot-only `all` must not silently change list fields beyond safe fill-only evidence.

Use an explicit helper instead of assigning all `stat` fields unconditionally:

```python
for field, source in {
    "liked": "like",
    "comments": "reply",
    "shares": "share",
    "collected": "favorite",
}.items():
    if record.get(field) is None:
        value = _metric(stat, source)
        if _is_nonnegative_count(value):
            record[field] = value
```

- [ ] **Step 7: Remove the superseded Bilibili DOM-target route**

After the new tests pass, remove unused Bilibili-only `_ensure_creator_feed`, `_open_dynamic_record`, `_find_exact_dynamic_target`, `_wait_for_exact_dynamic_target`, `_read_dynamic_feed_risk`, `_dispose_element_handle`, `_DYNAMIC_TARGET_TIMEOUT_MS`, and the Bilibili dependency on `missing_engagement_fields`. Do not remove `DetailOpenCoordinator` itself because XHS/other existing paths may still own it.

- [ ] **Step 8: Run direct-detail tests and verify GREEN**

Run Bilibili tests filtered to `explicit_detail`, `detail_http_risk`, `detail_identifier_mismatch`, `screenshot`, and `list_complete`. Assert no test calls a creator-card locator.

- [ ] **Step 9: Commit the direct-detail slice**

```bash
git add runtime/media_missher_runtime/platforms/bilibili.py tests/test_runtime_bilibili_production.py
git commit -m "feat: open Bilibili details by exact native URL"
```

### Task 5: Make failure semantics retain verified list evidence

**Files:**
- Modify: `runtime/media_missher_runtime/platforms/bilibili.py`
- Modify: `runtime/media_missher_runtime/cli.py`
- Modify: `tests/test_runtime_bilibili_production.py`
- Modify: `tests/test_runtime_cli.py`

- [ ] **Step 1: Write RED progress-before-detail tests**

Add a fake `publish_progress` recorder. For two list records, make the first explicit detail fail with a non-risk `PreconditionError`. Assert the first published snapshot contains both finalized list records before any temporary page is created.

- [ ] **Step 2: Write RED non-risk detail-shortfall tests**

For `PreconditionError`, `PlaywrightError`, and `PlaywrightTimeoutError`, assert collection returns the list record with:

```python
assert record["detail_attempted"] is True
assert record["detail_completed"] is False
assert record["complete"] is False
assert "detail" in record["missing_fields"]
```

If screenshot mode made capture obligatory, assert `screenshot_status == "failed"`. Do not catch `CollectionStopped`, `asyncio.CancelledError`, `KeyboardInterrupt`, or `SystemExit` as a partial detail failure.

- [ ] **Step 3: Publish the verified list snapshot before enrichment**

After list finalization, call only the existing bounded callback:

```python
publish = getattr(self.browser, "publish_progress", None)
if callable(publish):
    publish("bilibili", records)
```

Publish again after each successfully or unsuccessfully finalized non-risk detail attempt so timeout recovery sees the newest truthful state.

- [ ] **Step 4: Convert only bounded non-risk detail errors into incomplete records**

Wrap each `_open_detail_record` call in `collect_creator`:

```python
try:
    await self._open_detail_record(page, record)
except (PreconditionError, PlaywrightError, PlaywrightTimeoutError):
    record["detail_completed"] = False
    record["detail_source"] = "list_api"
    _finalize_record(
        record,
        detail_required=True,
        detail_received=False,
    )
    if self.request.screenshot_mode in {"opened", "all"}:
        _mark_screenshot_failed(record)
```

Do not retry and do not fall back to a DOM click or BrowserSkill.

- [ ] **Step 5: Make runtime status enforce explicit detail**

Change `_result_status` so either strict list mode or explicit detail mode enforces record completeness:

```python
strict_records = request.complete or request.bilibili_detail
if strict_records and any(record.get("complete") is not True for record in records):
    return "incomplete"
```

Existing screenshot-shortfall precedence remains unchanged.

- [ ] **Step 6: Write RED risk-stop persistence tests**

Make a Bilibili collector publish two finalized list records and then raise `RiskStop("http-429")`. Assert the runtime writes `bilibili.json`, reports count `2`, keeps platform status `risk-stopped`, emits no later platform work, and stores only safe diagnostic code `http-429`.

- [ ] **Step 7: Generalize private partial-record persistence**

Extract the current XHS-only dispatcher read into a helper:

```python
def _partial_records(dispatcher: Any, platform: str) -> list[dict[str, Any]]:
    reader = getattr(dispatcher, "partial_records", None)
    if reader is None:
        return []
    try:
        records = reader(platform)
    except Exception:
        return []
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        return []
    return [dict(record) for record in records]
```

Use it for both `RiskStop` and ordinary exception paths on any platform. Write only the platform JSON and count/path already owned by the private `RunStore`; keep XHS report/checkpoint generation exactly as-is.

- [ ] **Step 8: Run manifest and partial-evidence tests and verify GREEN**

Run the new tests plus all existing risk-stop, platform-timeout, partial-XHS, and diagnostic-consistency tests.

- [ ] **Step 9: Commit the evidence-preservation slice**

```bash
git add runtime/media_missher_runtime/platforms/bilibili.py runtime/media_missher_runtime/cli.py tests/test_runtime_bilibili_production.py tests/test_runtime_cli.py
git commit -m "fix: retain Bilibili list evidence on detail failure"
```

### Task 6: Align the adapter, command surface, and independent validator

**Files:**
- Modify: `media-missher/scripts/media_missher_adapter.py`
- Modify: `media-missher/scripts/run_collection.py`
- Modify: `media-missher/scripts/validate_run.py`
- Modify: `tests/test_validation.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_external_contract.py`

- [ ] **Step 1: Write RED adapter request tests**

Add `bilibili_detail=True` tests proving it requires selected Bilibili creator collection and `allow_navigation=True`, rejects search/non-Bilibili use, and does not imply BrowserSkill or screenshots.

- [ ] **Step 2: Add and validate the outer request field**

Add after `bilibili_complete`:

```python
bilibili_detail: bool = False
```

Add these guards:

```python
if not isinstance(self.bilibili_detail, bool):
    raise ConfigurationError("Bilibili detail must be an explicit boolean")
if self.bilibili_detail and "bilibili" not in requested:
    raise ConfigurationError("Bilibili detail mode requires bilibili")
if self.bilibili_detail and search:
    raise ConfigurationError("Bilibili detail mode does not support search")
if self.bilibili_detail and not self.allow_navigation:
    raise ConfigurationError("Bilibili detail mode requires navigation authorization")
```

Include `bilibili_detail` in the adapter's advanced-mode support checks without changing XHS ownership rules.

- [ ] **Step 3: Write and implement command-forwarding tests**

Assert `build_engine_command` appends exactly one `--bilibili-detail` only when requested:

```python
if request.bilibili_detail:
    argv.append("--bilibili-detail")
```

Add the same argparse flag and request forwarding in `run_collection.py`. Add it to `validate_run.py` only as an evidence requirement; independent validation must not add `--allow-navigation` or perform browser work.

- [ ] **Step 4: Write RED outer list-validation tests**

Create a valid Bilibili list record fixture with exact `native_id`, `native_type`, link, author, meaningful title/content, date, integer liked/comments/shares, `collected=None`, `detail_attempted=False`, and `complete=True`. Assert `bilibili_complete=True` validates successfully.

Parameterize invalid required metrics with `None`, `-1`, `True`, `"1"`, and `1.5`. Add a separate optional-collection test proving `None` is accepted but invalid non-null collection values fail.

- [ ] **Step 5: Make `_bilibili_complete` evidence-level aware**

Use explicit type checks rather than mere non-null checks:

```python
def _bilibili_complete(
    record: Mapping,
    *,
    require_detail: bool,
) -> bool:
    title = str(record.get("title") or "").strip()
    collected = record.get("collected")
    list_valid = bool(
        record.get("complete") is True
        and str(record.get("native_id") or "").strip()
        and str(record.get("native_type") or "").strip()
        and str(record.get("link") or "").startswith("https://")
        and str(record.get("author") or "").strip()
        and title not in {"", "无标题", "(无标题)", "动态"}
        and record.get("date")
        and all(
            _is_nonnegative_integer(record.get(field))
            for field in ("liked", "comments", "shares")
        )
        and (
            collected is None
            or _is_nonnegative_integer(collected)
        )
    )
    return list_valid and (
        not require_detail
        or (
            record.get("detail_attempted") is True
            and record.get("detail_completed") is True
            and record.get("detail_source") in {"detail_api", "detail_dom"}
        )
    )
```

Also retain exact platform/link/native-ID validation already present elsewhere; do not accept an arbitrary HTTPS link merely because the compact snippet above starts with HTTPS.

- [ ] **Step 6: Pass the explicit evidence level into validation**

Change the validation loop to:

```python
incomplete = sum(
    not _bilibili_complete(
        record,
        require_detail=request.bilibili_detail,
    )
    for record in deduplicated["bilibili"]
)
```

Run Bilibili validation whenever `complete`, `bilibili_complete`, or `bilibili_detail` is requested.

- [ ] **Step 7: Run adapter, runner, and external-contract tests and verify GREEN**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_validation.py tests/test_cli.py tests/test_runner.py tests/test_external_contract.py
```

- [ ] **Step 8: Commit the adapter/validator slice**

```bash
git add media-missher/scripts/media_missher_adapter.py media-missher/scripts/run_collection.py media-missher/scripts/validate_run.py tests/test_validation.py tests/test_cli.py tests/test_runner.py tests/test_external_contract.py
git commit -m "feat: validate Bilibili list and detail evidence separately"
```

### Task 7: Update operator documentation without changing the version

**Files:**
- Modify: `media-missher/SKILL.md`
- Modify: `openclaw-media-missher/SKILL.md`
- Modify: `media-missher/references/commands.md`
- Modify: `media-missher/references/validation.md`
- Modify: `README.md`
- Modify: `PROJECT_CONTEXT.md`
- Test: `tests/test_cli.py`
- Test: `tests/test_external_contract.py`

- [ ] **Step 1: Write RED help/contract assertions**

Assert all relevant help surfaces contain `--bilibili-detail`, that validation help carries the same evidence selector, and that no help text claims `--bilibili-complete` opens details or fills an absent collection count.

- [ ] **Step 2: Document the default list contract**

State consistently:

```text
Bilibili creator collection is list-first. `--bilibili-complete` validates
native identity, content/date, liked, comments, and shares from the creator
Feed. `collected` remains null when the Feed does not supply it and does not
cause a detail open.
```

- [ ] **Step 3: Document the explicit detail/screenshot contract**

State consistently:

```text
Use `--bilibili-detail --allow-navigation` only when exact detail evidence is
required. Media opens one temporary tab in the same CDP browser context and
closes it after the record. `--screenshot-mode opened` captures only an
explicitly opened detail; `all` explicitly opens every selected record.
```

Also state that BrowserSkill is never an automatic fallback and list-only mode does not use it.

- [ ] **Step 4: Record version and deployment truth**

Keep `VERSION` as `15.2.1`. In `PROJECT_CONTEXT.md`, distinguish:

- source candidate: V15.2.1;
- installed stable: V15.2.0 until acceptance;
- offline evidence: not live-platform proof;
- live acceptance: pending until Task 9.

- [ ] **Step 5: Run documentation-facing tests and validators**

```bash
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py media-missher
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py openclaw-media-missher
```

Run the help/contract test node IDs and verify GREEN.

- [ ] **Step 6: Commit the documentation slice**

```bash
git add media-missher/SKILL.md openclaw-media-missher/SKILL.md media-missher/references/commands.md media-missher/references/validation.md README.md PROJECT_CONTEXT.md tests/test_cli.py tests/test_external_contract.py
git commit -m "docs: explain Bilibili list-first evidence"
```

### Task 8: Run complete offline release gates and review the diff

**Files:**
- Review: every file changed by Tasks 1-7
- Modify if evidence requires: `PROJECT_CONTEXT.md`

- [ ] **Step 1: Run the full locked sockets-disabled suite**

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket
```

Expected: all tests PASS. Record the exact count and warning count; do not reuse the previous `971 passed` result.

- [ ] **Step 2: Compile every tracked Python file without writing bytecode**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
import subprocess

paths = [
    Path(line)
    for line in subprocess.check_output(
        ["git", "ls-files", "*.py"], text=True
    ).splitlines()
]
for path in paths:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
print(f"compiled {len(paths)} tracked Python files")
PY
```

- [ ] **Step 3: Run every public help entrypoint**

Run `--help` for the runtime creator entrypoint, `run_collection.py`, `validate_run.py`, `scrape_all.py`, and the Bilibili wrapper under the locked runtime. Confirm the new flag is present only where supported.

- [ ] **Step 4: Run skill, residual, privacy, and whitespace gates**

```bash
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py media-missher
python3 /Users/missher/.codex/skills/.system/skill-creator/scripts/quick_validate.py openclaw-media-missher
python3 tools/scan_active_residuals.py --root .
git diff --check
```

Run the repository's existing privacy scan/test target as located by `rg -n "privacy|secret|credential" tests tools .github`. Never print or commit private UID, cookies, run JSON, screenshots, browser state, or credentials.

- [ ] **Step 5: Perform a spec and implementation self-review**

Check each approved requirement against code and tests. Specifically search for forbidden automatic routes:

```bash
rg -n 'request\.complete.*open|missing_engagement_fields|_find_exact_dynamic_target|retry.*browserskill|collected.*0' runtime/media_missher_runtime/platforms/bilibili.py
rg -n 'bilibili_detail' runtime media-missher tests README.md PROJECT_CONTEXT.md
rg -n 'TODO|TBD|FIXME|placeholder' docs/superpowers/plans/2026-08-13-bilibili-list-first-explicit-detail.md runtime/media_missher_runtime/platforms/bilibili.py
```

Expected: no metric-driven detail-open path, no DOM-target fallback, and no unknown-to-zero conversion. Review all new public booleans for runtime/adapter/validator type and naming consistency.

- [ ] **Step 6: Review the exact diff and commit any evidence-only correction**

```bash
git status --short
git diff --stat origin/codex/media-missher-v15...HEAD
git diff --check origin/codex/media-missher-v15...HEAD
git log --oneline --decorate -10
```

If `PROJECT_CONTEXT.md` needs exact fresh counts, commit only that evidence correction. Do not fold unrelated user changes into the branch.

### Task 9: Install, preflight, run one bounded live acceptance, and update Draft PR

**Files:**
- Installed target after acceptance: `/Users/missher/.codex/skills/media-missher`
- Private evidence target: configured Media@Missher run root outside Git
- Modify after acceptance: `PROJECT_CONTEXT.md`

- [ ] **Step 1: Reconfirm the clean candidate and stable rollback source**

Verify `git status --short` is empty, `VERSION` is `15.2.1`, the installed stable still reports V15.2.0, and commit `7040fc0` remains the known V15.2.0 rollback source. If any of these drifted, stop and resolve provenance before installation.

- [ ] **Step 2: Atomically install the Codex-only candidate**

```bash
python3 tools/install_media_missher.py --codex-only
```

Record the unique deployment release ID separately from product version. Do not install to OpenClaw, Feishu, or another agent runtime.

- [ ] **Step 3: Run live preflight without collection**

```bash
python3 /Users/missher/.codex/skills/media-missher/scripts/preflight.py --live --json
```

Require the existing Chrome CDP endpoint, signed-in Bilibili context, private paths, and safety checks to pass. Do not start BrowserSkill.

- [ ] **Step 4: Inject the already supplied target without logging it**

Resolve the exact Bilibili creator UID from the user's current private profile or the already supplied URL and set it only in the current shell:

```bash
test -n "$BILIBILI_ACCEPTANCE_UID"
```

Do not echo the value and do not write it into Git files.

- [ ] **Step 5: Run exactly one ten-record list-only acceptance**

```bash
python3 /Users/missher/.codex/skills/media-missher/scripts/run_collection.py \
  --platform bilibili \
  --bilibili-uid "$BILIBILI_ACCEPTANCE_UID" \
  --count 10 \
  --bilibili-complete \
  --browser-assist off \
  --screenshot-mode off \
  --allow-navigation \
  --platform-timeout 600 \
  --json-summary
```

Do not add `--bilibili-detail`. Do not rerun automatically after any risk, challenge, timeout, or ambiguous ownership result.

- [ ] **Step 6: Independently validate only the fresh run**

Capture the command start epoch before Step 5 and validate the returned exact run directory:

```bash
python3 /Users/missher/.codex/skills/media-missher/scripts/validate_run.py \
  --run-dir "$BILIBILI_ACCEPTANCE_RUN_DIR" \
  --started-epoch "$BILIBILI_ACCEPTANCE_STARTED_EPOCH" \
  --platform bilibili \
  --expected-count 10 \
  --bilibili-complete \
  --json-summary
```

Accept only 10 fresh ordered records with exact identities, required integer list metrics, optional-null `collected`, `detail_attempted == false`, no screenshot, no BrowserSkill session, no risk/timeout, and no Feishu artifact.

- [ ] **Step 7: Apply the bounded rollback rule on failure**

If live acceptance fails, do not weaken validators, retry risk, open details, or invent metrics. Atomically restore V15.2.0 from a clean temporary checkout of commit `7040fc0`, verify the installed version, keep the PR Draft, and document only the safe failure code and evidence layer.

- [ ] **Step 8: Record live truth and rerun documentation gates on success**

On success, update `PROJECT_CONTEXT.md` with the exact date, deployment release ID, fresh test count, live run status, and the distinction between list-only and explicit-detail evidence. Do not include the UID, record content, run JSON, screenshot paths, cookies, or browser state. Commit this evidence update.

- [ ] **Step 9: Push the reviewed branch and refresh the existing Draft PR**

```bash
git push origin codex/media-missher-v15
```

Update the existing Draft PR description with the approved design, exact offline evidence, live acceptance outcome, rollback status, and remaining non-goals. Do not tag, merge, create a release, or publish private collected evidence.

## Final acceptance checklist

- [ ] `--bilibili-complete` alone opens no detail and accepts `collected: null`.
- [ ] `--bilibili-detail` is explicit, creator-only, Bilibili-only, and navigation-authorized.
- [ ] Exact detail uses one new tab in the existing source page's CDP context, never a second browser.
- [ ] No Bilibili detail path locates or clicks a creator-page DOM card.
- [ ] Exact main-document `403`/`429` and visible risk stop without retry.
- [ ] Non-risk detail failure retains list records and reports incomplete/partial.
- [ ] Required Bilibili list metrics are non-negative integers; optional collection remains null when absent.
- [ ] Screenshot `opened` and `all` retain explicit, documented obligations.
- [ ] XHS remains Playwright/CDP-only and unchanged.
- [ ] Full offline gates pass with fresh evidence.
- [ ] Installed stable changes only after authorized atomic install and bounded live acceptance.
- [ ] GitHub receives source/docs/tests only; no private runtime evidence or third-party code is added.
