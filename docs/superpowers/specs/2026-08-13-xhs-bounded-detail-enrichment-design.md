# Media@Missher V15 Xiaohongshu Bounded Detail Enrichment Design

**Date:** 2026-08-13

**Target version:** `15.0.0` source hardening

**Status:** Approved and implemented in source; installation and live acceptance pending

**Selected route:** A — action budget plus bounded comment loading

## 1. Goal

Improve Xiaohongshu creator-detail completeness without increasing navigation risk.
For each selected note, Media@Missher may open the exact detail once, collect the
current target-bound response, allow the existing 5–15 second settle, and perform
at most three low-frequency scrolls inside the visible comment container when the
requested comment slice is still short.

The run must stop comment loading as soon as the requested slice is complete, the
visible comments stop growing, the container is unavailable, or any challenge or
risk signal appears. Missing data after that bounded work is a truthful partial
result. It must never cause a refresh, a second detail open, a second click, a
whole-page scroll, a click on “more”, or a risk retry.

This design improves compliant stability. It is not an anti-detection mechanism
and does not bypass platform controls.

## 2. Current confirmed behavior

The current source already:

- makes Xiaohongshu creator collection detail-first and complete by default;
- registers the exact detail-response listener before the exact note click;
- binds captured detail evidence to the expected `note_id`;
- waits 5–15 seconds once after a successfully captured complete-mode detail;
- stops immediately on response, payload, or visible-page risk signals;
- reads one visible comment slice and compares `comments_fetched` with
  `min(comments_requested, comments)` when a reliable total is available;
- captures an optional private article screenshot, with one full-page fallback;
- closes the detail modal or owned temporary page in a `finally` path;
- retains completed record prefixes when a later Xiaohongshu item reaches the
  platform timeout.

The shortfall is narrow: `_read_comments` observes only the comments currently
rendered in the DOM. A requested slice can therefore remain incomplete even when
the same already-open detail could reveal more comments with bounded scrolling.

## 3. Non-goals

This change does not:

- refresh, reload, reopen, or revisit a detail page;
- issue a second BrowserSkill click for Xiaohongshu, including stale-selector
  replay;
- scroll the document, creator feed, or any container other than the uniquely
  resolved visible comment container;
- click “展开”, “更多”, “查看更多”, pagination, reply, login, or verification
  controls;
- recursively expand replies or attempt to exhaust all platform comments;
- change the user-requested comment limit, creator count, or page cap;
- introduce proxies, account switching, fingerprint changes, challenge solving,
  stealth automation, concurrency, or adaptive risk circumvention;
- promote partial DOM evidence to current detail-API evidence;
- change Bilibili, Douyin, or Weibo behavior;
- install, publish, tag, push, or run a real-platform collection as part of the
  implementation task.

## 4. Selected architecture

The existing `XhsCollector._open_record` currently owns click orchestration,
response capture, parsing, comment reading, screenshots, completion, and cleanup.
Adding another ad-hoc loop directly to it would deepen a shallow implementation
instead of deepening the module.

The selected design introduces one private Xiaohongshu detail-enrichment module
behind a narrow interface. The module hides the action budget, comment-container
resolution, deduplication, growth detection, bounded waits, and stop reason. The
collector continues to own the business record, target-bound API merge,
screenshot request, completion decision, and cleanup.

```text
XhsCollector._open_record
        |
        | one exact target and one immutable policy
        v
XhsDetailEnrichment (deep private module)
        |
        +-- exact detail open ............ <= 1
        +-- BrowserSkill click command ... <= 1
        +-- current response merge ....... existing authority
        +-- comment-container scroll ..... <= 3
        +-- screenshot request ........... <= 1
        |
        v
XhsDetailEnrichmentResult
        |
        +-- bounded comments
        +-- comment stop reason
        +-- consumed action counts
```

The interface is intentionally Xiaohongshu-specific. A generic cross-platform
“browser action engine” would expose too much mechanism, weaken target binding,
and create an unnecessary policy surface.

## 5. Action budget

Each note receives a fresh immutable policy with these limits:

| Action | Limit | Notes |
| --- | ---: | --- |
| Exact detail open | 1 | Existing exact `note_id` flow only |
| BrowserSkill click command | 1 | No stale-selector replay on XHS |
| Detail settle | 1 | Existing cryptographic 5–15 second wait |
| Comment-container scroll | 3 | Only while the requested slice is short |
| Wait after a successful scroll | 3 | 1,500 ms once per scroll |
| Screenshot capture request | 1 | Existing article then full-page fallback is one capture request |

Budget exhaustion is not an exception and never resets the budget. It produces
the best verified record available and leaves `comments_data` in
`missing_fields` when the requested slice is still short.

The one-click rule is stricter than the bridge’s existing generic
`stale-selector` replay. The bridge must expose a narrow no-replay option, or the
Xiaohongshu coordinator must use an equivalent one-attempt operation. Bilibili’s
existing policy remains unchanged. A failed pre-action stale selector therefore
returns a structured assist failure for Xiaohongshu; it does not trigger another
click command.

## 6. Comment loading data flow

Comment loading starts only when all of these are true:

1. complete mode is active;
2. `comment_limit > 0`;
3. the exact detail response was accepted and `detail_completed` is true;
4. the post-settle challenge check passed;
5. the exact detail page still matches the expected `note_id`.

The loader then follows this sequence:

1. Read the currently rendered comments and run the existing risk observation.
2. Normalize comment business fields with the existing `_safe_comments` rules.
3. Deduplicate the accumulated slice while preserving visible order.
4. Compute the target as:
   - `min(comment_limit, comments_total)` when `comments_total` is a known
     non-negative integer;
   - otherwise `comment_limit`.
5. Return `complete` immediately when the accumulated slice reaches the target.
6. Resolve exactly one visible, scrollable candidate from `.comments-container`
   and `.comments-el`. Visibility requires a connected node, visible CSS, and
   positive geometry; scrollability requires `scrollHeight > clientHeight`.
   Zero, multiple, hidden, detached, or non-scrollable candidates return a
   partial result without interaction.
7. Check for a challenge, scroll that container by at most one viewport, wait a
   fixed 1,500 ms, and check for a challenge again.
8. Read and merge the newly visible comments.
9. Stop immediately when the unique comment count did not grow.
10. Repeat only until three container scrolls have been consumed.

The loader never assumes that a changed scroll position means new evidence.
Only growth in the normalized, deduplicated visible comment slice justifies the
next bounded scroll.

## 7. Comment identity and deduplication

Raw comment IDs, account IDs, request tokens, and raw payloads remain excluded.
Deduplication therefore uses a private normalized content key made from the
already retained business fields:

```text
(normalized author, normalized text, normalized date, parsed liked count)
```

This is intentionally conservative. Identical visible comments can collapse,
which may leave the record partial, but the runtime must not invent stable IDs or
retain sensitive identifiers merely to claim completeness. The private loader
discards entries that have neither a normalized author nor normalized text before
deduplication; this rule receives its own regression test.

## 8. Result and public record contract

The private enrichment result contains:

- normalized comments in visible order;
- `comments_fetched`;
- consumed scroll count;
- an internal stop reason: `complete`, `not-requested`, `container-missing`,
  `container-ambiguous`, `container-not-scrollable`, `no-growth`, or
  `budget-exhausted`.

The public record keeps the current fields:

- `comments_requested`;
- `comments_data`;
- `comments_detail` as the backward-compatible alias;
- `comments_fetched`;
- `missing_fields`;
- `complete`.

No new public collection field is required in this change. The stop reason and
action counts remain internal structured diagnostics so CSV, JSONL, SQLite, and
existing validator contracts do not expand. When the fetched slice is short,
`_missing_completion` continues to add `comments_data`, which causes the adapter
to report a partial result while preserving the verified record.

## 9. Safety and error behavior

Risk handling has absolute precedence over completeness:

- HTTP or payload risk follows the existing immediate `CollectionStopped` path.
- A visible challenge before or after every comment interaction stops the entire
  collection immediately.
- A challenge creates no screenshot and permits no click, scroll, refresh, or
  retry after detection.
- Comment-container resolution failure, no growth, or action-budget exhaustion is
  a non-risk partial result, not a platform retry.
- A Playwright error during comment reading or scrolling preserves already
  verified detail fields but follows the existing platform-error semantics; it
  must not silently manufacture a complete record.
- Cleanup remains in the existing `finally` path and must not mask a primary risk
  or collection error.

The implementation must pass the expected `note_id` into every detail-page guard.
A mismatched, missing, or ambiguous detail URL disables comment interaction and
fails closed.

## 10. Screenshot ordering

When a screenshot was requested, it is captured after bounded comment enrichment
and a final challenge check. This yields evidence of the current article and the
final safely visible comment state without adding another open.

The existing screenshot service remains authoritative for:

- exact-detail validation;
- unique visible article-container capture;
- one full-page fallback;
- private atomic mode-`0600` PNG storage;
- run-relative path and SHA-256 binding;
- refusing all capture on a risk page.

“One capture request” means one call from the collector to the screenshot
service. That service may make the existing article attempt followed by its one
full-page fallback when the article attempt cannot produce safe PNG evidence.

Comment shortfall does not suppress a requested screenshot. Screenshot failure
does not discard already verified structured data.

## 11. File and responsibility boundaries

Expected implementation scope:

- `runtime/media_missher_runtime/platforms/xhs.py`
  - integrate the private detail-enrichment interface;
  - keep completion and record mapping authoritative;
  - retain exact-note and risk checks.
- one small private runtime module if extraction materially reduces
  `_open_record` complexity;
  - own immutable action policy, bounded comment loading, growth detection, and
    internal result types;
  - expose no general browser automation API.
- `runtime/media_missher_runtime/browser_skill.py` and/or
  `runtime/media_missher_runtime/detail_open.py`
  - add the narrow Xiaohongshu no-stale-replay seam without changing Bilibili’s
    existing behavior.
- `tests/test_runtime_xhs.py`
  - cover platform integration and completion behavior.
- focused unit tests for any extracted private module or bridge option.
- `PROJECT_CONTEXT.md` and relevant skill references
  - document the bounded action contract and dated offline evidence.

The implementation should not touch unrelated platform collectors, adapters, or
the public CLI unless a failing contract test proves a required compatibility
change.

## 12. Test design

All tests use fake pages, fake response payloads, and synthetic DOM observations
with network sockets disabled.

### Budget and interaction tests

- exact detail open is attempted at most once per record;
- BrowserSkill receives at most one Xiaohongshu click command;
- a structured stale-selector result is not replayed for Xiaohongshu;
- at most three comment-container scrolls occur;
- the document and creator feed are never scrolled by comment loading;
- no “more”, pagination, reply, login, or verification control is clicked;
- screenshot capture is requested at most once.

### Completion tests

- enough initially visible comments cause zero scrolls and a complete record;
- a known total below the requested limit stops at the known total;
- unknown total uses the requested limit;
- one or more growing scrolls reach the target and complete the record;
- duplicate comments do not inflate `comments_fetched`;
- no growth stops after the first non-growing scroll and returns partial;
- missing, ambiguous, hidden, or non-scrollable containers return partial with
  zero scrolls;
- three growing but insufficient scrolls return partial at budget exhaustion;
- `comments_detail` remains equal to `comments_data`.

### Risk and failure tests

- a challenge before the first comment read stops immediately;
- a challenge before or after each scroll stops with no later action;
- risk stop creates no screenshot and is never retried;
- exact-detail URL mismatch permits no comment interaction;
- a Playwright failure does not mark the record complete;
- modal and owned-page cleanup still run after success, partial, error, timeout,
  cancellation, and risk stop;
- completed record prefixes survive a later platform timeout.

### Regression gates

1. Focused Xiaohongshu, detail-open, BrowserSkill, screenshot, and adapter tests
   pass with sockets disabled.
2. The complete offline suite passes with sockets disabled.
3. All Python sources compile.
4. All five runtime entrypoint `--help` commands pass.
5. Active residual scanning, skill validation, packaging checks, and
   `git diff --check` pass.
6. Installed non-live preflight may be inspected read-only, but source changes
   are not described as installed until an explicitly authorized cutover.
7. No real-platform collection or BrowserSkill session is part of offline
   acceptance.

## 13. Acceptance criteria

The change is accepted when:

- Xiaohongshu complete mode still opens each selected exact note at most once;
- Xiaohongshu BrowserSkill assistance issues at most one click command per note;
- the existing target-bound response, 5–15 second settle, and immediate risk-stop
  contracts remain intact;
- requested comments are read initially and enriched with at most three
  comment-container-only scrolls;
- enough comments, missing container, ambiguous container, non-scrollability, no
  growth, budget exhaustion, and risk each stop deterministically;
- incomplete comments produce a truthful partial record with `comments_data` in
  `missing_fields`;
- screenshots remain optional, private, exact-target-bound, and at most one
  capture request per opened note;
- Bilibili, Douyin, Weibo, default CLI behavior, output formats, and validators do
  not regress;
- all offline gates pass and live behavior is described only as unverified until
  a separately authorized live acceptance run occurs.

## 14. Deferred option

Durable per-record progress persistence is deliberately deferred. It could later
use an in-memory adapter in tests and an atomic private-file adapter in production,
but it would expand the run manifest, recovery, retention, and validation
contracts. The current completed-prefix retention remains the recovery boundary
for this implementation wave.
