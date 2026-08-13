# Media@Missher V15.2.1 Bilibili List-First and Explicit-Detail Design

**Date:** 2026-08-13

**Status:** Approved in conversation; pending written-spec review

**Supersedes:** `2026-08-13-bilibili-cdp-dynamic-completion-design.md` for the V15.2.1 release candidate

## 1. Goal

Make ordinary Bilibili creator collection use the creator dynamic Feed as its authoritative source for the fields that the Feed exposes directly. Do not open a dynamic merely because `collected` is absent. Open detail only when the user explicitly requests detail evidence or a screenshot mode requires a detail page.

The default path must keep one Chrome/CDP owner, preserve mixed feed order, avoid BrowserSkill, avoid DOM-card clicks, and return truthful `null` values for metrics that the creator Feed does not guarantee.

## 2. Confirmed evidence

The prior authorized ten-record creator run produced nine video dynamics and one free-form image dynamic. All ten records had current Feed evidence for liked, comments, and shares. The image dynamic was classified incomplete only because `collected` was `null`.

The V15.2.1 draft then attempted to open that image dynamic when complete mode saw the missing collection value. Its final bounded live run stopped safely because the creator page did not expose one unique actionable DOM target satisfying the exact native-ID rule. This was not a login, CDP, timeout, or risk failure. It proved that DOM-card clicking is not a reliable prerequisite for ordinary creator collection.

## 3. Alternatives

### A. List-first evidence plus explicit detail mode — selected

Use the creator Feed for ordinary collection and type-aware validation. Treat liked, comments, and shares as required list-level engagement evidence. Preserve `collected` when present and preserve `null` when absent, without treating that absence alone as a list-level failure. Add an explicit detail request boundary; direct detail navigation occurs only behind that boundary.

This matches the platform response, minimizes browser actions, and keeps missing data honest.

### B. Remove `collected` from one validator only

This is a smaller patch, but it leaves collection routing, runtime completion, adapter validation, documentation, and future callers with conflicting definitions. It could silently reintroduce detail opens elsewhere. It is rejected.

### C. Continue opening incomplete DOM cards

This preserves the existing draft structure but depends on a clickable element shape that the live page does not guarantee. Relaxing the target selector could click the wrong dynamic. It is rejected.

### D. Convert an absent collection count to zero

This would turn unknown evidence into a fabricated measurement. It is rejected.

## 4. Evidence levels

Bilibili creator collection has two explicit evidence levels.

### 4.1 List evidence — default

An ordinary request such as “抓 10 条动态” or “全都抓” uses list evidence only.

- Capture the exact creator Feed response bound to the requested UID.
- Preserve the latest mixed feed order and count; do not filter out videos, text, images, articles, or forwards.
- If the first response contains the requested count, do not paginate.
- If more records are required, retain the existing bounded Feed pagination rules. Pagination is not detail opening.
- Do not open a detail page, create a detail tab, click a card, start BrowserSkill, or take a screenshot.
- A same-creator navigation or reload used to capture the Feed remains subject to explicit `--allow-navigation` authorization.

The list-level required fields are:

- exact `native_id` and `native_type`;
- exact source link derived from BVID or dynamic ID;
- author;
- non-placeholder content or title appropriate to the native type;
- publish date/time evidence available in the Feed;
- non-negative integer liked, comments, and shares.

`collected` is optional at list level for every Bilibili dynamic type because the creator Feed does not guarantee it uniformly. When supplied, it must remain a non-negative integer. When absent, it remains JSON `null`; it is not added to `missing_fields`, does not become zero, and does not trigger detail navigation.

### 4.2 Detail evidence — explicit

Detail evidence is selected only when the request explicitly asks for detail information or a screenshot mode requires a detail page.

- Add the boolean request field `bilibili_detail` and expose it as `--bilibili-detail` in the runtime CLI and skill adapter. Do not infer it from an absent list metric.
- `--bilibili-complete` continues to request strict evidence, but by itself evaluates the selected list evidence level and does not force detail navigation.
- `--bilibili-detail` may be combined with `--bilibili-complete` when strict detail evidence is required.
- Screenshot mode `opened` captures only a detail page opened for an explicit detail request.
- Screenshot mode `all` remains an explicit request to open every selected record for screenshot evidence.

An explicit detail request requires `detail_attempted: true`, exact native-ID binding, a validated detail URL, a successful detail read, and `detail_completed: true`. A detail-specific shortfall remains partial without invalidating already verified list fields.

## 5. Detail navigation architecture

Explicit detail uses Playwright through the existing Chrome/CDP connection. It does not depend on a list DOM target.

```text
exact creator Feed record
        |
        +-- ordinary request
        |       -> accept type-aware list evidence
        |       -> no detail page
        |
        +-- explicit detail or screenshot-all request
                -> derive exact allowlisted URL from BVID/dynamic_id
                -> select the prepared page's existing browser context
                -> create one Media-owned temporary tab in that context
                -> attach exact main-document response observer
                -> navigate once to exact native URL
                -> stop on exact HTTP 403/429 or visible risk
                -> validate final URL carries the requested native ID
                -> read detail and fill only missing/explicit detail fields
                -> capture screenshot only if requested
                -> close only the Media-owned temporary tab
```

The source feed page remains open and unchanged. The temporary page uses the same Chrome process, browser context, cookies, and signed-in state. It is a new tab, not a second browser.

The direct URLs are derived only from validated native identifiers already accepted from the creator Feed:

- video: `https://www.bilibili.com/video/{bvid}`;
- non-video dynamic: `https://t.bilibili.com/{dynamic_id}`.

No observed arbitrary href, query string, redirect target, or user-supplied free-form URL may become the detail destination.

## 6. Component boundaries

### Bilibili collector

- Parse list fields and compute list-level completeness.
- Read the explicit `bilibili_detail` request field to decide whether detail evidence is requested.
- Never decide to open detail solely from `collected: null`.
- Permit exact detail content and publish evidence to replace list preview content when `bilibili_detail` is true. Engagement metrics remain fill-only: detail may fill a null metric but never overwrite an exact non-null Feed metric.

### Browser session

- Provide a bounded helper that creates and registers one temporary page in the same prepared browser context.
- Navigate only to an exact allowlisted HTTPS destination.
- Ensure the temporary page is closed during normal completion, error handling, cancellation, and session shutdown.
- Never close or repurpose the user's existing page.

### Detail validator

- Validate BVID/dynamic-ID syntax before navigation.
- Bind the document response and final page URL to the expected native ID.
- Reject ambiguous, mismatched, closed, or unrelated pages.
- Keep HTTP and visible risk decisions non-retryable.

### Adapter and outer validator

- Distinguish list-level complete evidence from explicitly requested detail evidence.
- Accept `collected: null` for Bilibili list evidence.
- Reject non-integer, negative, boolean, string, or contradictory metric values.
- Require detail proof only when the explicit detail option or screenshot contract demands it.

## 7. BrowserSkill boundary

BrowserSkill is not part of ordinary Bilibili list collection and is never selected automatically. BrowserSkill-off is the release and live-acceptance path.

The existing explicit BrowserSkill compatibility flag may remain accepted during this focused change, but it must not cause a list-only request to open details. Removing the compatibility surface is a separate deprecation decision and is outside this design.

## 8. Error and risk handling

- Stop immediately on exact-detail HTTP `403` or `429`, CAPTCHA, verification, challenge, risk, lock, block, or cooldown evidence.
- Do not retry a risk stop.
- Do not retry or fall back from direct native-ID navigation to DOM clicking.
- A list-level `collected: null` is not an error.
- A missing required list field produces truthful partial evidence.
- Persist the verified list snapshot before beginning optional detail enrichment. An explicit detail request that later fails for a non-risk reason retains all verified list records, marks the affected detail obligation incomplete, and produces `incomplete-record`/outer `partial` rather than a zero-record internal failure.
- A risk stop retains only already verified private list evidence and reports `risk-stopped`; it never resumes detail work.
- Preserve the exclusive collection lease, sequential execution, page caps, timeouts, private file permissions, and no-Feishu boundary.

## 9. Compatibility and versioning

- The current source candidate remains `15.2.1`; it has not been tagged, released, or merged, so this design corrects that same candidate rather than creating `15.2.2`.
- The installed stable release remains `15.2.0` until the revised candidate passes live acceptance.
- Output retains the existing `collected` field and uses `null` for unavailable list evidence.
- Existing Bilibili records, mixed ordering, identifiers, links, screenshots, and manifest status vocabulary remain compatible.
- Xiaohongshu, Douyin, Weibo, Feishu, private profiles, and historical archives are unchanged.

## 10. Test-first implementation requirements

Implementation begins only after failing regression tests prove the intended contracts.

### List behavior

1. A mixed ten-record Feed can complete list validation without any detail open.
2. A free-form image/text/article/forward dynamic with numeric liked, comments, and shares and `collected: null` is list-complete.
3. `collected: null` remains null and is absent from list-level `missing_fields`.
4. A supplied collection value must be a non-negative integer and must be preserved exactly.
5. Missing liked, comments, or shares remains incomplete.
6. Ordinary and list-complete requests create no temporary page, perform no DOM click, start no BrowserSkill session, and take no screenshot.
7. Mixed feed count and order remain unchanged.

### Explicit detail behavior

8. An explicit video detail request opens one exact Media-owned temporary tab in the same context and closes it.
9. An explicit non-video detail request derives the exact native URL without locating or clicking a creator-page DOM target.
10. Exact same-ID detail succeeds; mismatched IDs and unrelated redirects fail closed.
11. Exact main-document HTTP `403`/`429` stops before DOM parsing or screenshot.
12. Visible challenge/risk stops before merge or screenshot.
13. Non-risk detail shortfall preserves verified list evidence and reports the correct partial diagnostic.
14. Cancellation and exceptions close only the Media-owned temporary page.
15. Screenshot `opened` and `all` retain their documented explicit behavior.

### Compatibility gates

16. CLI, adapter, request-model, runtime manifest, and standalone validator agree on the selected evidence level.
17. Existing Xiaohongshu ownership, screenshot, risk, comment, and validation contracts remain unchanged.
18. Full sockets-disabled tests, Python compilation, all five help entrypoints, both skill validators, residual scan, privacy scan, and `git diff --check` pass.

## 11. Live acceptance

After an authorized atomic Codex-only installation, run one bounded creator acceptance against the already supplied exact target:

- count 10;
- list evidence only;
- BrowserSkill off;
- screenshot off;
- explicit navigation authorization;
- no Feishu.

Accept the candidate only when:

- exactly 10 current-run mixed records validate;
- every record has exact identity plus required list fields;
- liked, comments, and shares are non-negative integers;
- a missing collection value remains null without causing incompleteness;
- no record has `detail_attempted: true`;
- no detail tab, BrowserSkill session, screenshot, risk stop, timeout, or Feishu artifact occurs;
- independent validation accepts the exact fresh run.

If the candidate fails, do not relax identity binding or invent metrics. Restore stable V15.2.0 atomically and keep the pull request Draft.

## 12. Non-goals

This design does not:

- bypass platform controls or add stealth, fingerprint changes, CAPTCHA handling, proxy rotation, account rotation, or concurrency;
- make `collected` zero when absent;
- remove Bilibili videos or change mixed feed ordering;
- scrape comment contents during ordinary list collection;
- open detail for an ordinary list request;
- broaden BrowserSkill usage;
- publish collected JSON, screenshots, browser state, target identifiers, or credentials;
- tag, create a GitHub Release, merge, or publish the candidate before live acceptance.
