# Validate current-run evidence

Validation accepts only artifacts from one unique run whose modification time is at or after its recorded start. It rejects symlinks, stale files, malformed JSON, duplicate manifest keys, unsafe paths, unknown platforms, and reused output. Historical export evidence is separate from current-run validation and never receives a freshness claim.

## Validate the runtime manifest

The manifest must contain exactly `counts`, `paths`, `platforms`, `status`, and `diagnostics`. The keys in `counts`, `platforms`, and `diagnostics` must identify the same non-empty subset of `bilibili`, `xhs`, `douyin`, `weibo`, and `x`. A plan run additionally writes its frozen `plan.json`, per-platform records, and a `run_manifest.json` that records the frozen backend, targets, counts, record kinds, and observation times.

Each diagnostic object contains exactly `kind` and `code`. Accept only these kind-to-code pairs:

- `ok`: `ok`
- `result`: `count-shortfall`, `incomplete-record`, `screenshot-shortfall`
- `not-run`: `preflight-aborted`, `prior-risk-stop`
- `dependency`: `module-not-found`
- `precondition`: `precondition-failed`, `browser-assist-replaced`, `platform-collector-missing`, `plan-request-invalid`, `plan-executor-missing`, `plan-manifest-invalid`, `exclude-file-plan-unsupported`, `target-identity-missing`, `target-keyword-missing`, `target-topic-missing`, `topic-collector-unavailable`, `topic-unsupported-platform`, `topic-container-unsupported`, `topic-input-invalid`, `topic-kind-mismatch`, `xhs-cooldown`, `xhs-risk-latched`, `xhs-safety-busy`, `xhs-safety-state-invalid`, `bsk-missing`, `bsk-unhealthy`, `bsk-incompatible`, `bsk-busy`, `bsk-transport`, `bsk-timeout`, `bsk-target-ambiguous`, `bsk-session-start`, `bsk-tab-list`, `bsk-tab-borrow`, `bsk-navigate`, `bsk-observe`, `bsk-get-html`, `bsk-extract`, `bsk-stale-reference`, `bsk-snapshot`, `bsk-click`, `bsk-tab-return`, `bsk-session-stop`, `bsk-risk-signal`, `bsk-navigation-not-authorized`
- `source-response`: `source-response-failed`
- `risk-stop`: `http-403`, `http-429`, `payload-461`, `payload-471`, `payload-999`, `challenge`, `risk-signal`
- `timeout`: `platform-timeout`, `creator-capture-timeout`, `detail-capture-timeout`
- `collector-contract`: `invalid-records`
- `internal`: `unexpected`

The controller and the Harness plugin also recognize the fixed launcher codes `collection-busy` and `shared-state-invalid` as preconditions before a run exists. They are request-boundary codes, not manifest diagnostics, so a manifest must never contain them.

The platform-status-to-kind enum is strict: `complete` accepts `ok`; `shortfall` and `incomplete` accept `result`; `failed` accepts `dependency`, `precondition`, `source-response`, `timeout`, `collector-contract`, or `internal`; `risk-stopped` accepts `risk-stop`; and `not-run` accepts `not-run`. In addition, `complete` requires `ok`/`ok`, `shortfall` requires `result`/`count-shortfall`, and `incomplete` requires either `result`/`incomplete-record` or `result`/`screenshot-shortfall`. The overall status must agree with all platform statuses.

Artifact values must be exact safe basenames with no URL, query, UID, directory, or duplicate path. A selected platform may name only `<platform>.json`; Xiaohongshu may additionally name `xhs_report.json` and `xhs_checkpoint.json` through the `xhs_report` and `xhs_checkpoint` keys. A platform marked `complete` must have its platform content artifact.

Accept only documented platform statuses: `complete`, `shortfall`, `incomplete`, `failed`, `risk-stopped`, and `not-run`. A risk status wins over partial evidence. A failed, shortfall, incomplete, or not-run platform prevents a success result.

## Validate the stop reason

A plan or `best_effort` task reports one fixed stop reason from this vocabulary: `natural-end`, `no-new-records`, `budget-exhausted`, `run-deadline`, `count-reached`, `not-logged-in`, `permission-denied`, `risk-stopped`, `timeout`, `cancelled`, `empty-results`, `target-changed`, `session-lost`, `unsupported`, and `error`.

`budget-exhausted` is a budget pause with a verified prefix, not finished collection. `run-deadline` means the authorized window expired. `count-reached` and `natural-end` are the only two reasons that may be reported as complete for a fixed target. Never rewrite a pause, a deadline, or a cancellation into a completion, and never restart a stopped run automatically.

## Validate content records

Every counted record needs its platform-native content identifier and a non-empty content link. Reject an error or status object even when its filename resembles a platform artifact.

Deduplicate records by native identifier while preserving first-seen order. Compare each selected platform with its requested count. Preserve Python value types and nested values. Keep unknown values as `null`; never convert them to zero.

Every record carries its source backend and evidence level. A response-observed record (`evidence_level: response`) comes from `cdp` and may satisfy a complete contract. Historical `computer_use` and `browserskill` records retain their original page evidence and provenance; read/export does not authorize execution of either retired backend.

Records are separated by record kind: `posts`, `topic_participants`, and `user_profiles` are different entities and must never be merged into one counted total.

## Validate Weibo topic and user-profile records

A topic task saves the observed posts, the user records of their outer authors, and the topic-to-user relations.

- The topic input must resolve to the standard topic contract. A 超话 is refused with `topic-container-unsupported` and is never validated as a keyword-search result.
- Participants are only the outer authors of observed topic posts, including a forwarder who really appears in the results. Quote authors, recommendation-card authors, viewers, and likers are never participants, and no record may claim to be the complete participant set.
- One user homepage is visited at most once per run. A repeated relation reuses the confirmed user entry instead of visiting again.
- A homepage that is unavailable, deleted, permission-limited, or login-walled keeps the confirmed user entry, records one fixed reason (`profile-unavailable`, `profile-deleted`, `profile-permission-denied`, `profile-login-required`), and leaves unobserved profile fields `null`. Missing profile fields are reported as missing, never filled from another page.
- Never recurse into followers, following, or all posts of a participant.

## Validate X records

X posts, search results, and hashtag tasks use one normalizer for both evidence routes, so a page-observed record can never be reported as a response-observed record.

- `tweet_id`, `author_id`, conversation and quote ids are strings, and a handle is never used as a numeric user id.
- `comments` is the reply count only and never claims reply bodies. `views` is the post view count, not a video play count. `bookmarks` and `collected` are one same-origin metric, not two independent counts.
- Media preview images must be distinguished from a video resource. A media field that is not proven keeps `null`.
- An unknown value stays `null`. A value displayed as an abbreviation such as `1.2K` keeps its original text and a `rounded` precision state, and must not be reported as an exact count.

## Validate screenshot evidence

Screenshots are a `cdp` capability. When screenshot status is `complete`, require the entire metadata group: `screenshot_path`, `screenshot_mode`, `screenshot_capture_kind`, `screenshot_observed_at`, `screenshot_sha256`, and `screenshot_status`. Reject partial groups. Mode must match the request and be `opened` or `all`; capture kind must be `article` or `full_page_fallback`; observation time must be UTC.

Resolve `screenshot_path` only beneath the source engine run. Reject absolute paths, traversal, symlinks, foreign runs, stale files, modes other than `0600`, files larger than 50 MiB, non-PNG content, and SHA-256 mismatches. Read the PNG once. Converted output rewrites the validated reference to `<engine-run-name>/screenshots/<name>.png`, relative to the private outer run, never to a user-home absolute path.

In `all` mode, every record requires screenshot evidence. In `opened` mode, only a record with `detail_attempted: true` requires it. A safe `capture-failed` record remains usable structured evidence but makes the result `partial` through `screenshot-shortfall`.

## Validate Bilibili complete mode

Every requested Bilibili record must contain:

- `complete: true`
- A non-placeholder title
- A date
- Non-null liked, comments, shares, and collected values

Describe engagement as the current API snapshot. Do not claim a field freshness time that the evidence does not support.

## Validate Xiaohongshu complete mode

Every requested Xiaohongshu record must contain:

- `complete: true`, `detail_attempted: true`, and `detail_completed: true`
- An empty `missing_fields` list
- An exact `https://www.xiaohongshu.com/explore/<note_id>` link whose path ID matches the record
- A non-estimated date with `date_source: detail_api`
- Non-negative integer liked, comments, collected, and shares values
- Non-empty body and author values proven to come from the current detail payload
- At least one safe image, video, or cover value proven to come from the current detail payload
- `engagement_fresh: true`
- A detail API, detail HTML, or detail CDP source for every engagement metric
- A global engagement observation time and a per-metric observation time at or after the run start
- When comments were requested, `comments_requested` must equal this run's request; `comments_fetched` and the `comments_data` list length must equal the smaller of the request limit and the current detail comment count
- Every comment object must contain only `author`, `text`, `date`, and `liked`, with at least a non-empty author or body

Xiaohongshu detail opening, engagement metrics, comments, and screenshot evidence must come from the response-observed `cdp` session with `--browser-assist off`. Page evidence, including historical BrowserSkill data, is never Xiaohongshu complete evidence.

A cache-only value, stale preview body/media, estimated day, incomplete comment request, failed detail attempt, contradictory proof, lock, cooldown, or risk report is not complete. If bounded comment loading stops because the container is unavailable or ambiguous, is not scrollable, stops growing, or reaches its three-scroll budget, preserve the verified record as partial evidence with `comments_data` in `missing_fields`.

## Validate Douyin and Weibo

Douyin and Weibo require current, parseable, deduplicated records that meet the requested count. Preserve their native IDs, normalized fields, record order, and null-versus-zero values.

## Validate an export

An export is a separate, offline, selection-driven step and is validated as historical evidence, never as fresh collection.

- It reads only already-saved verified local results from one exact run ID. It never navigates, collects, or fills a missing field.
- The requested record kinds must be explicit (`posts`, `topic_participants`, `user_profiles`) and the requested format must be `xlsx`, `csv`, `json`, `jsonl`, or `sqlite`.
- A requested field or field group that was never collected is reported in `missing_fields`; it is never silently dropped and never collected now.
- Partial, risk-stopped, and cancelled runs keep their status, missing fields, and original observation times. The export records its source run, the selection, the real record counts, and `source_backend`.
- An existing output file is never overwritten unless `--overwrite` was passed explicitly. Exported files stay private: mode `0600` files inside mode-`0700` directories.

## Report exact results

Return one status: `success`, `partial`, `risk-stopped`, `preflight-failed`, or `failed`. Keep diagnostic reports separate from content evidence.

Show no more than three metadata-only samples containing platform and field count. Never echo collected content, credentials, personal account IDs, browser state, configured secret values, URL query strings, or full environment mappings. Report absolute current-run evidence paths.

The run directory must use mode `0700`; JSON and converted evidence must use mode `0600`. Confirm that no Feishu artifact exists and that Media@Missher made no remote Feishu write.

## Accept a live run

Run `scripts/preflight.py --live` before authorized live acceptance. It proves shared layout health and, on the `cdp` backend, CDP endpoint reachability. It does not prove selected platform login state. The runtime controller checks selected pages and visible login state before output creation.

If the acceptance collection needs exact-host navigation, pass `--allow-navigation` to `scripts/run_collection.py` only with explicit authorization. The offline `scripts/validate_run.py` command does not navigate.

Accept cutover evidence only when every selected platform has the requested native record count, complete-mode fields pass, timestamps belong to the current run, the frozen backend matches the plan, and no risk stop or timeout occurred. Do not retry a risk stop.

Computer Use and BrowserSkill are retired. Their historical evidence and diagnostics remain readable; current collection uses Chrome CDP only. Offline tests do not establish native host or live platform acceptance.
