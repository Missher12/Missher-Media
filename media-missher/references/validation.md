# Validate current-run evidence

Validation accepts only artifacts from one unique run whose modification time is at or after its recorded start. It rejects symlinks, stale files, malformed JSON, duplicate manifest keys, unsafe paths, unknown platforms, and reused output.

## Validate the runtime manifest

The manifest must contain exactly `counts`, `paths`, `platforms`, and `status`. Artifact names must be relative basenames inside the run directory. A platform marked `complete` must have its named JSON artifact.

Accept only documented platform statuses: `complete`, `shortfall`, `incomplete`, `failed`, `risk-stopped`, and `not-run`. A risk status wins over partial evidence. A failed, shortfall, incomplete, or not-run platform prevents a success result.

## Validate content records

Every counted record needs its platform-native content identifier and a non-empty content link. Reject an error or status object even when its filename resembles a platform artifact.

Deduplicate records by native identifier while preserving first-seen order. Compare each selected platform with its requested count. Preserve Python value types and nested values. Keep unknown values as `null`; never convert them to zero.

## Validate Bilibili complete mode

Every requested Bilibili record must contain:

- `complete: true`
- A non-placeholder title
- A date
- Non-null liked, comments, shares, and collected values

Describe engagement as the current API snapshot. Do not claim a field freshness time that the evidence does not support.

## Validate Xiaohongshu complete mode

Every requested Xiaohongshu record must contain:

- `complete: true` and `detail_attempted: true`
- A non-estimated date
- Non-null liked, comments, and collected values
- `engagement_fresh: true`
- A detail, HTML, or CDP source from this run
- An engagement observation time at or after the run start

A cache-only value, stale field, estimated day, failed detail attempt, lock, cooldown, or risk report is not complete.

## Validate Douyin and Weibo

Douyin and Weibo require current, parseable, deduplicated records that meet the requested count. Preserve their native IDs, normalized fields, record order, and null-versus-zero values.

## Report exact results

Return one status: `success`, `partial`, `risk-stopped`, `preflight-failed`, or `failed`. Keep diagnostic reports separate from content evidence.

Show no more than three metadata-only samples containing platform and field count. Never echo collected content, credentials, personal account IDs, browser state, configured secret values, URL query strings, or full environment mappings. Report absolute current-run evidence paths.

The run directory must use mode `0700`; JSON and converted evidence must use mode `0600`. Confirm that no Feishu artifact exists and that Media@Missher made no remote Feishu write.

## Accept a live run

Run `scripts/preflight.py --live` before authorized live acceptance. It proves CDP endpoint reachability and shared layout health, not selected platform login state. The runtime controller checks selected pages and visible login state before output creation.

If the acceptance collection needs exact-host navigation, pass `--allow-navigation` to `scripts/run_collection.py` only with explicit authorization. The offline `scripts/validate_run.py` command does not navigate.

Accept cutover evidence only when every selected platform has the requested native record count, complete-mode fields pass, timestamps belong to the current run, and no risk stop or timeout occurred. Do not retry a risk stop.
