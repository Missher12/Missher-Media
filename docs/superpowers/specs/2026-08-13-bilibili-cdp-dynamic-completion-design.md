# Media@Missher V15.2 Bilibili CDP Dynamic Completion Design

**Date:** 2026-08-13

**Status:** Approved verbally; pending written-spec review

**Selected route:** Keep Bilibili creator collection as one mixed dynamic feed and use the existing Playwright/CDP detail coordinator only when a non-video dynamic is incomplete.

## 1. Goal

Preserve the current Bilibili creator behavior in which a request for 10 records returns the latest 10 mixed feed items, including videos, text, images, articles, and forwards. Improve strict complete mode so a non-video dynamic with one or more unknown engagement values receives one exact CDP-owned detail open before it is classified as incomplete.

The change must not make BrowserSkill mandatory, start a second browser, change feed counting, invent missing values, or weaken risk stops.

## 2. Confirmed live evidence

The authorized V15.2 Bilibili run for the user-supplied exact creator target requested 10 complete records with BrowserSkill and screenshots off. It returned 10 records in 18.504 seconds:

- nine `DYNAMIC_TYPE_AV` video records were complete through the existing detail API path;
- one `DYNAMIC_TYPE_DRAW` non-video record retained list content, date, liked, comments, and shares but had `collected: null`;
- independent validation reported 9 complete records and one `incomplete-record`;
- the incomplete record had `detail_attempted: false`, `detail_source: list_api`, and `missing_fields: ["collected"]`;
- the run encountered no risk stop or timeout and created no Feishu artifact.

The current `_needs_dynamic_open` condition opens a non-video dynamic only for screenshot mode `all` or for BrowserSkill-assisted missing engagement. Complete mode with BrowserSkill off therefore cannot use the already implemented CDP-only detail path to attempt the missing field.

## 3. Alternatives

### A. Open only incomplete non-video dynamics in complete mode — selected

When a non-video record has a valid `dynamic_id`, strict complete mode is active, and at least one engagement value is unknown, restore the exact creator feed if necessary and open that exact dynamic once through the existing detail coordinator. This minimizes browser actions while preserving strict evidence.

### B. Open every non-video dynamic in complete mode

This is mechanically simple but performs unnecessary clicks when the list API already provides all required values. It increases interaction, time, and exposure without improving accepted evidence.

### C. Treat an unknown collection value as complete

This avoids a detail open but changes `null` from unknown evidence into an accepted result. It weakens the complete contract and is rejected.

## 4. Public behavior

- Bilibili creator collection continues to select all feed content types by default.
- A count of 10 continues to mean the latest 10 mixed records, not 10 records after a content-type filter.
- No new content filter, CLI flag, profile key, environment variable, manifest field, or output schema field is added.
- Video records continue to use the existing video detail API path in complete mode.
- Non-video records whose list evidence is already complete do not open a detail page.
- Non-video records with missing engagement values open their exact detail once in complete mode even when `--browser-assist off` and `--screenshot-mode off`.
- BrowserSkill remains an optional explicitly requested Bilibili helper. It is not selected or started by this change.
- Screenshot behavior remains unchanged: `opened` captures only an already opened detail, while `all` requires every selected record to produce screenshot evidence.

## 5. Data flow

```text
exact creator feed response bound to requested UID
        |
        v
latest mixed records selected up to requested count
        |
        +-- video record + complete mode
        |       -> existing exact BVID detail API path
        |
        +-- non-video record + all engagement known
        |       -> keep list evidence; no click
        |
        +-- non-video record + engagement missing + complete mode
                -> restore exact creator feed if needed
                -> find one exact dynamic_id target
                -> register an exact-detail document-response observer
                -> one DetailOpenCoordinator click
                -> accept only same dynamic_id detail page
                -> stop on exact-detail HTTP 403/429 or visible risk
                -> fill only missing metrics with finite non-negative values
                -> release only Media-owned popup, if any
                -> recompute complete and missing_fields
```

`DetailOpenCoordinator` already supports a bridge-free path: with no BrowserSkill bridge it performs one Playwright element click, resolves either the exact same-page detail or one click-derived exact popup, and rejects ambiguous or mismatched targets. The selected change reuses that path rather than adding a second controller.

Before the click, the Bilibili dynamic-detail path must attach one bounded response observer to the current CDP browser context. It accepts only a main-document response whose exact allowlisted detail URL matches the requested `dynamic_id`, covering both same-page navigation and a click-derived popup. HTTP `403` or `429` on that exact response is a risk stop. A client-side route that emits no main-document response continues through exact-page resolution and the existing visible-risk inspection. The observer is removed after the bounded detail attempt and must not preserve response bodies, query strings, or unrelated traffic.

## 6. Trigger condition

The non-video detail-open predicate must be true only when all of the following hold:

1. the record has no BVID;
2. the record has one valid non-empty `dynamic_id`;
3. one of these existing obligations requires an open:
   - strict complete mode is active and at least one engagement field is unknown;
   - BrowserSkill assistance was explicitly requested and at least one engagement field is unknown;
   - screenshot mode `all` requires the record to be opened.

Screenshot mode `opened` alone must not create a new detail open. Ordinary non-complete collection with BrowserSkill off must not add a click.

The new bridge-free complete-mode path permits exactly one Playwright click and no retry. Existing explicitly requested BrowserSkill behavior retains its current single `stale-selector` snapshot-and-click replay as the sole compatibility exception; risk, ambiguity, transport failure, and every bridge-free CDP failure remain non-retryable. This change neither broadens nor removes that separately selected BrowserSkill policy.

## 7. Evidence and error handling

- Exact `dynamic_id` binding is mandatory before and after the click.
- Missing or ambiguous exact targets fail closed with the existing precondition diagnostic.
- An exact-detail main-document HTTP `403` or `429`, a visible challenge, risk, lock, block, or cooldown stops the run without retry or screenshot.
- A successful detail read uses fill-only merging: it writes a finite, non-negative detail value only when the corresponding list field is `null`. Existing exact list API values must not be replaced by rounded or display-formatted DOM values.
- Detail values never convert a missing value to zero unless the page provides explicit numeric-zero evidence.
- If the detail page still does not expose `collected` or another required engagement field, retain the verified list/detail values, keep the unknown field as `null`, and report `partial` through `incomplete-record`.
- The run remains subject to the existing adapter collection lease, sequential execution, page cap, timeout, private paths, and mode `0700`/`0600` requirements.
- No Feishu client or remote write is introduced.

## 8. Test strategy

Test-driven implementation must first add failing regressions that prove:

1. complete mode with BrowserSkill off opens one exact non-video dynamic when an engagement value is missing;
2. the same path fills a detail-provided collection value, preserves already known list API metrics byte-for-byte, and produces a complete record;
3. if the exact detail still lacks the requested metric, the collector clicks once, sets `detail_attempted: true`, retains the field as `null`, keeps it in `missing_fields`, emits no screenshot, performs no retry, and remains incomplete;
4. runtime and adapter validation map that still-missing case to `incomplete-record` and outer `partial`, respectively;
5. a non-video record with complete list engagement performs no detail click;
6. non-complete BrowserSkill-off collection performs no new detail click;
7. screenshot mode `opened` alone still performs no detail click;
8. screenshot mode `all` retains its existing exact-open and capture behavior;
9. an exact same-page or popup main-document HTTP `403`/`429` stops as risk before merge, screenshot, or retry;
10. visible risk on the dynamic detail stops before merge, screenshot, or retry;
11. an exact target or detail ID mismatch fails closed;
12. mixed video and non-video feed counting and order remain unchanged;
13. the new bridge-free path performs one click with no replay, while explicitly selected BrowserSkill retains only its existing single structured `stale-selector` compatibility replay;
14. the adapter, runtime CLI, validation contract, and all other BrowserSkill-specific behavior remain compatible.

After focused tests pass, run the complete locked-dependency sockets-disabled suite, compile all Python sources, check all five entrypoint help commands, validate both skill packages, scan active residuals, and run `git diff --check`.

## 9. Live acceptance

Source tests do not prove the current Bilibili DOM. Installation and live acceptance require separate authorization.

After an authorized atomic installation, repeat one Bilibili creator run against the supplied exact UID with:

- count 10;
- Bilibili complete mode;
- BrowserSkill off;
- screenshots off unless separately requested;
- explicit navigation authorization;
- no Feishu.

Accept success only if all 10 current-run records pass the strict complete contract. If the exact detail page does not expose a collection value for a non-video dynamic, accept the run only as truthful `partial`; do not add selectors speculatively, repeat the click, or relabel the missing value as zero.

## 10. Non-goals

This change does not:

- filter Bilibili records into image/text, video, or all modes;
- change the requested count or feed order;
- make BrowserSkill the default or modify Tencent/BrowserSkill;
- add concurrency, retries, refreshes, proxy rotation, CAPTCHA handling, stealth, or fingerprint changes;
- change Xiaohongshu, Douyin, Weibo, Feishu, historical archives, or runtime-private evidence;
- install the modified source, run another live collection, push, tag, publish, or merge without separate authorization.
