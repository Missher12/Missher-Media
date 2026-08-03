# Validation

Accept only JSON files in the unique current run directory whose modification time is not older than the recorded start time. Reject symlinks, stale files, malformed JSON, unexpected top-level values, unknown platforms, and reused output.

Require every counted record to contain its platform-native content identifier and a non-empty content link. Reject an error/status object even when its filename starts with a platform name. Deduplicate accepted records by native identifier, then compare each selected platform against its requested count. Preserve unknown values as `null`; never convert them to zero.

## Bilibili complete mode

Every requested record must have:

- `complete: true`;
- a non-placeholder title;
- a date;
- non-null liked, comments, shares, and collected values.

Describe engagement as the current API snapshot. Do not claim an unsupported field-level freshness time.

## Xiaohongshu complete mode

Every requested record must have:

- `complete: true` and `detail_attempted: true`;
- a non-estimated date;
- non-null liked, comments, and collected values;
- `engagement_fresh: true`;
- a detail, HTML, or CDP source from this run;
- an engagement observation time at or after the run start.

A cache-only value, stale field, estimated day, failed detail attempt, lock, cooldown, or risk report cannot be called complete.

## Other platforms

Douyin and Weibo require current, parseable, deduplicated records meeting the requested count. Keep their native IDs and normalized content fields in raw or converted evidence.

## Reporting

Return one of `success`, `partial`, `risk-stopped`, `preflight-failed`, or `failed`. Show no more than three metadata-only samples containing only the platform and field count; never echo collected content in a summary. Keep diagnostic reports separate from content evidence. Remove credential-like keys, personal account IDs, configured secret values, URL query strings, and full environment mappings. Always provide absolute current-run evidence paths.
