# Media@Missher V15 Browser Assist and Screenshot Design

**Date:** 2026-08-11  
**Target version:** `15.0.0`  
**Status:** Approved design

## 1. Goal

Media@Missher V15 adds an optional Tencent BrowserSkill-assisted detail-open path for Xiaohongshu and Bilibili, plus private evidence screenshots. The assistant is used only when Media@Missher needs a real detail page to obtain missing target-bound data or an explicitly requested screenshot. It is not an anti-detection mechanism and must not bypass platform restrictions.

V15 must preserve the V12 defaults, data model behavior, sequential execution, private output, exact-target validation, navigation authorization, rate limits, randomized Xiaohongshu settle, and immediate risk stops. Douyin and Weibo behavior remains unchanged.

## 2. Non-goals

V15 does not:

- copy Tencent BrowserSkill source into this repository;
- use BrowserSkill to parse authoritative response bodies or manufacture completeness;
- access, export, replace, or clear browser cookies or local storage;
- bypass captcha, login, challenge, cooldown, account restriction, fingerprinting, or other platform controls;
- add proxy rotation, concurrent platform collection, blind clicking, or repeated risk retries;
- operate pre-existing personal tabs;
- publish a public repository before a repository-wide license and provenance review is complete;
- perform Feishu reads or writes.

## 3. User-facing modes

The existing behavior remains the default. BrowserSkill is opt-in:

```text
--browser-assist off|browserskill
```

`off` is the default. `browserskill` requires the locally installed `bsk` CLI, a healthy extension, the existing Media@Missher browser context, and explicit `--allow-navigation` authorization for a real collection or live acceptance run.

Screenshots are independently opt-in:

```text
--screenshot-mode off|opened|all
```

- `off` is the default and creates no screenshots.
- `opened` captures only records whose exact detail view was already opened by complete mode or missing-field fallback. It never causes an otherwise unnecessary open.
- `all` explicitly opens each selected Xiaohongshu or Bilibili target sequentially so it can be captured. It requires `--allow-navigation`, remains subject to count/page caps and all risk controls, and is never enabled implicitly.

Unsupported platform combinations fail during argument validation rather than silently ignoring the request.

## 4. Architecture

### 4.1 `BrowserSkillBridge`

`BrowserSkillBridge` is a narrow subprocess adapter around the external `bsk` executable. It owns health checks, a single BrowserSkill session, exact tab discovery, tab borrowing, target clicking, return, and session shutdown. Commands use an argument vector without a shell. Parsed JSON and diagnostics are redacted before entering Media@Missher logs.

The bridge does not parse platform records. It does not expose general-purpose browser automation to platform modules. Its public operations are intentionally small so tests can substitute a fake runner.

### 4.2 `DetailOpenCoordinator`

`DetailOpenCoordinator` decides whether a record needs a detail open, binds that operation to one native identifier, registers Media@Missher response observation before the click, invokes the bridge, validates the observed result, and returns structured evidence to the existing platform parser.

Bindings are:

- Xiaohongshu: exact `note_id`;
- Bilibili dynamic: exact `dynamic_id`;
- existing Bilibili video detail handling: unchanged unless it shares common coordinator plumbing without changing behavior.

Zero or multiple target matches fail closed. The coordinator may refresh the BrowserSkill snapshot once for a non-risk stale-reference failure; it must not guess a target or perform blind retries.

### 4.3 `EvidenceScreenshot`

`EvidenceScreenshot` captures the current verified detail page only after native-ID validation and a post-open risk check. It first requires exactly one visible article/content container with sane, non-zero dimensions. If the container is missing, ambiguous, invisible, or geometrically abnormal, it falls back to a full-page screenshot and records `full_page_fallback`.

Visible challenge, captcha, login interception, cooldown, lock, or risk content prevents all screenshot creation. Screenshot failure does not invalidate already verified structured data, but it makes a requested screenshot result partial.

## 5. Browser ownership and lifecycle

Media@Missher continues to connect to the existing CDP browser and never starts, restarts, terminates, or reconfigures Chrome.

When BrowserSkill assistance is requested:

1. Preflight verifies Media@Missher CDP as before, then checks `bsk` health and compatibility.
2. A conflicting or unrelated active BrowserSkill session fails preflight with `bsk-busy`; Media@Missher does not take it over.
3. Media@Missher creates its own temporary page only after explicit navigation authorization and marks it with a unique per-run value.
4. The bridge starts one BrowserSkill Agent Window and identifies exactly one tab carrying that value.
5. Only that tab is borrowed. Pre-existing tabs are never borrowed, closed, navigated, or repurposed.
6. In a `finally` path, the bridge returns the borrowed tab, stops its session, and Media@Missher closes only its temporary page.

Lifecycle cleanup runs after success, non-risk failure, risk stop, cancellation, or timeout.

## 6. Platform data flow

### 6.1 Xiaohongshu

Ordinary collection uses the existing list/preview evidence. With BrowserSkill assistance enabled, an exact note is opened only when a required field such as `collected` or `shares` remains unknown and the record has an exact `note_id`.

Complete mode retains its stronger evidence contract: every selected note is opened once even when preview metrics appear populated, because completeness requires a fresh exact detail response. Media@Missher registers the existing exact detail-response listener before BrowserSkill clicks the exact note target. It then validates response URL, request identity, status, payload risk, and `note_id` before merging values. The existing cryptographically sampled 5-15 second settle and post-settle challenge check remain unchanged.

Missing, `null`, placeholder, and explicit zero semantics remain unchanged. A response for another note must never update the current record.

### 6.2 Bilibili dynamics

Existing video detail behavior remains unchanged. For a non-video dynamic, BrowserSkill fallback is eligible only when required data is missing or screenshot mode `all` explicitly requires a detail view, and only when an exact `dynamic_id` is available.

The coordinator opens the exact dynamic and accepts only authoritative response or DOM evidence bound to the same `dynamic_id`. Pure text and image dynamics are valid records; they must not be discarded merely because they have no `bvid`. If required data remains missing after the exact open, the record stays incomplete. A successful click alone never proves completeness.

## 7. Screenshot artifacts and record binding

Screenshots are PNG files written atomically inside the current unique mode-`0700` run directory. Final files are mode `0600`, use sanitized native-ID-based names, reject symlink destinations, and never overwrite another record's evidence.

Each captured record stores:

- `screenshot_path`: run-relative artifact path, not a user-home absolute path;
- `screenshot_mode`: requested CLI mode, `opened` or `all`;
- `screenshot_capture_kind`: `article` or `full_page_fallback`;
- `screenshot_observed_at`: UTC observation timestamp;
- `screenshot_sha256`: SHA-256 of the final PNG.

If no screenshot was requested, these optional fields are absent or null according to the existing serialization convention. Validators resolve the path under the current run only, reject traversal and symlinks, check mode and PNG structure, and verify the stored digest.

## 8. Error and status contract

- Missing `bsk`, unhealthy extension, incompatible BrowserSkill, CDP failure, ambiguous browser context, or `bsk-busy` before output creation returns `preflight-failed`.
- Zero or multiple exact targets, identifier mismatch, or a non-risk click/transport timeout returns a structured assist failure. One retry is permitted only after correcting the concrete cause and passing fresh preflight.
- HTTP `403`, `429`, `461`, `471`, `999`, visible challenge, `risk`, `locked`, `blocked`, or cooldown signals return `risk-stopped` immediately. There is no screenshot or retry.
- Article-container capture failure falls back once to full page. If full-page capture also fails, verified structured data is retained and the requested screenshot shortfall returns `partial`.
- Cleanup errors are reported without masking the primary status and never justify acting on unrelated browser tabs.

## 9. Security and privacy

All new subprocess calls use fixed executable discovery, argument arrays, bounded timeouts, output-size limits, and JSON schema validation. Diagnostic output must not log cookies, authorization headers, local storage, browser profile contents, query secrets, or raw platform payloads.

Screenshots are private evidence and may contain user-visible account chrome. They are excluded from source control, packages, CI artifacts, release bundles, and GitHub. Tests use synthetic images and fake BrowserSkill responses. CI performs no live platform navigation.

The repository must ignore local brainstorming previews, browser profiles, runtime runs, screenshots, recovery directories, `.env` files, and other private state. Packaging tests enforce these exclusions.

## 10. Test design

### Unit and contract tests

- fake `bsk` runner for health, start, exact tab discovery, borrow, click, return, stop, timeout, malformed JSON, and cleanup;
- fail-closed behavior for zero/multiple tabs and zero/multiple targets;
- missing-field policy proves that populated ordinary records receive no extra click;
- exact `note_id` and `dynamic_id` binding rejects cross-target evidence;
- BrowserSkill click cannot directly mark a record complete;
- subprocess construction, redaction, timeout, and output bounds;
- CLI validation for assist, screenshot, navigation, and supported platform combinations.

### Platform regression tests

- Xiaohongshu listener registration occurs before the assisted click;
- complete mode still opens exactly once per note and preserves the 5-15 second settle;
- ordinary Xiaohongshu opens only for configured missing fields;
- Bilibili pure-text and image dynamics remain valid without a `bvid`;
- Bilibili exact-dynamic fallback does not change existing video detail behavior;
- all risk responses stop immediately without screenshot or retry.

### Screenshot and storage tests

- unique visible article container capture;
- missing, ambiguous, invisible, and abnormal container full-page fallback;
- risk/challenge pages create no PNG;
- atomic write, mode `0600`, digest, native-ID filename, traversal/symlink rejection;
- screenshot failure yields `partial` while preserving verified record data;
- validators reject stale or foreign-run screenshot evidence.

### Release regression gates

1. Focused new tests pass with sockets disabled.
2. The complete offline suite passes with sockets disabled.
3. Compile checks, all five entrypoint help commands, active residual scans, skill validation, installer tests, and packaging tests pass.
4. A clean packaged copy passes its suite and contains no private artifacts.
5. Live preflight may verify CDP and BrowserSkill health without collecting platform data.
6. Any real count-1 Xiaohongshu or Bilibili acceptance requires a new explicit platform, target, count, and navigation authorization; it is not implied by approval of this design.

## 11. Version, installation, and GitHub release

This is a real `15.0.0` release, not a display-only version bump. Source, installed runtime, adapters, documentation, release markers, and validation expectations must agree on the version.

The implementation task writes code and tests in branch `codex/media-missher-v15`, runs focused offline tests, and does not install, tag, publish, or push. The supervising task reviews the diff, runs all release gates, performs the atomic local installation, and only then commits the final implementation, creates the V15 tag, and publishes.

The initial GitHub repository is private at the intended owner/name `Missher12/media-missher`. It contains source, tests, documentation, installer, and offline CI only. It excludes runtime state, credentials, profiles, cookies, screenshots, recovery data, local visual previews, and generated releases. Tencent BrowserSkill remains an external prerequisite documented by name and minimum compatible interface; its source is not vendored.

No public visibility change is permitted until the owner selects a repository-wide license and a provenance review confirms that every distributed component may be published under it.

## 12. Acceptance criteria

V15 is accepted only when all of the following are true:

- default commands without the new flags retain V12 behavior;
- BrowserSkill assistance operates only on the uniquely proven Media@Missher temporary tab;
- ordinary collection produces no extra click when required fields are already known;
- Xiaohongshu and Bilibili merges are bound to exact native identifiers;
- pure-text and image Bilibili dynamics are supported without false completeness;
- article screenshots and full-page fallback are private, current-run-bound, digest-verified evidence;
- every risk signal stops immediately and creates no screenshot;
- no browser credentials, state, screenshots, or personal paths enter Git or release packages;
- all offline, packaging, installation, and validation gates pass;
- the private GitHub repository is created and pushed only after local acceptance succeeds.
