# XHS Evidence Hardening Design

## Goal

Strengthen Media@Missher V15's proof that every accepted Xiaohongshu complete
record came from the exact current detail page, while preserving the current
single-CDP-owner browser flow and its fail-closed risk behavior.

## Stable browser ownership

Xiaohongshu remains CDP-only in production. BrowserSkill 0.1.10 requires an
active session, creates an Agent Window, and borrows a user tab before it can
observe or click. The current public interface cannot prove that the original
window, Playwright context, response listener, and exact CDP target remain
continuous. Multi-controller support therefore remains a future capability-
gated experiment, not a fallback in the live collection path.

A future implementation may be enabled only when it can prove all of the
following: one browser owner at a time, an exact CDP target/native ID mapping,
listener registration before ownership transfer, a total click budget of one,
and no fallback or retry after any uncertain click or risk signal.

## Changes

### Independent complete-record validation

The adapter must not trust a record's aggregate `complete` or
`engagement_fresh` assertions by themselves. It will independently require:

- an exact Xiaohongshu explore link whose path note ID equals `note_id`;
- `detail_attempted` and `detail_completed` to both be true;
- an empty `missing_fields` list and a non-estimated detail date;
- fresh detail provenance and a current observation timestamp for liked,
  comments, collected, and shares;
- detail-proven description, author, and media.

### Request-bound comment validation

The adapter will receive the requested `xhs_comments` value directly. For a
positive request it will require the record to report the same request value,
to provide a list of safe comment objects, and to keep `comments_fetched`
equal to the list length. The list must reach `min(requested, detail total)`.
Only `author`, `text`, `date`, and `liked` are accepted comment keys.

### Screenshot fallback risk gate

When article-region capture cannot produce a payload, the screenshot service
will perform another read-only risk check before document sizing or full-page
capture. A risk signal stops immediately and no PNG is written.

### Duplicate-page pagination

Creator pagination will no longer stop solely because a page adds no new IDs.
It may proceed only when `has_more` is true, the cursor is non-empty and has
advanced, and the page cap remains. This allows a duplicate or pinned page to
be crossed without adding concurrency or unbounded scrolling.

## Deferred work

No new DOM selector for `shares` is added without a reliable fixed fixture or
current-page evidence. Guessing a selector could turn an unrelated number into
an accepted engagement metric, which is worse than an honest partial result.

## Acceptance

- Every missing or contradictory proof above makes XHS complete validation
  partial.
- Comment requests cover zero, fewer-than-requested, exact-target, malformed,
  and unsafe-schema cases.
- Risk appearing after failed article capture causes zero full-page captures.
- A progressing duplicate cursor page reaches a later new note; an empty or
  repeated cursor still stops within the page cap.
- All existing offline tests continue to pass with no network or browser use.
