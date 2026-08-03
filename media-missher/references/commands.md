# Commands

Resolve the directory containing `SKILL.md` as `SKILL_DIR`. Pass the external runtime explicitly or configure it as described in `configuration.md`.

## Read-only preflight

```bash
python3 "$SKILL_DIR/scripts/preflight.py" \
  --engine-root "$ENGINE_ROOT" \
  --json
```

Add `--live` before real collection. Live preflight only probes the existing CDP endpoint; it does not start Chrome.

## Creator collection

```bash
python3 "$SKILL_DIR/scripts/run_collection.py" \
  --engine-root "$ENGINE_ROOT" \
  --platform bilibili,xhs,douyin,weibo \
  --count 10 \
  --platform-timeout 600 \
  --no-feishu \
  --json-summary
```

Use `--bilibili-count`, `--xhs-count`, `--douyin-count`, or `--weibo-count` for selected-platform overrides. Use the matching `--<platform>-uid` only for a user-authorized target.

For Bilibili and Xiaohongshu complete collection, add `--complete`; or select one with `--bilibili-complete` or `--xhs-complete`. Add `--xhs-comments N` only when Xiaohongshu is selected.

## Keyword search

```bash
python3 "$SKILL_DIR/scripts/run_collection.py" \
  --engine-root "$ENGINE_ROOT" \
  --platform weibo \
  --search "approved keyword" \
  --count 10 \
  --json-summary
```

Search accepts exactly one platform and cannot use complete mode.

## Formats

Set `--format json`, `csv`, `jsonl`, or `sqlite`. The adapter always makes private JSON evidence first, validates it, and then creates one converted file. It never asks the external engine to produce a non-JSON format.

Count `0` additionally requires `--collect-as-much-as-safe` and remains subject to the external engine cap.

## Validate an existing current run

```bash
python3 "$SKILL_DIR/scripts/validate_run.py" \
  --run-dir "$RUN_DIR" \
  --started-epoch "$RUN_STARTED_EPOCH" \
  --platform bilibili,xhs \
  --expected-count 10 \
  --json-summary
```
