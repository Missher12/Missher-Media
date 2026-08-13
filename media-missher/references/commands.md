# Run Media@Missher commands

Use these commands for installation, preflight, creator collection, search, validation, conversion, and recovery. Resolve the directory containing `SKILL.md` as `SKILL_DIR`.

## Install atomically for the current Codex-only environment

Confirm the source product version before installation:

```bash
python3 tools/install_media_missher.py --version
```

Run installation commands from the source repository. The current machine has retired OpenClaw, so the recommended authorized cutover installs `current/`, `venv/`, private `state/`, and the Codex skill under one release without creating or requiring an OpenClaw root:

```bash
python3 tools/install_media_missher.py --codex-only
```

`--runtime-only` remains available for adapter-only staging. The no-mode default still installs both compact skills for backward compatibility with historical OpenClaw environments:

```bash
python3 tools/install_media_missher.py --runtime-only
python3 tools/install_media_missher.py
```

`--codex-only` and `--runtime-only` are mutually exclusive. Do not run any installation command during a read-only review or before every release gate passes.

## Run read-only preflight

This command checks the shared layout, Python, dependencies, private state, release markers, and five entrypoints without collecting:

```bash
python3 "$SKILL_DIR/scripts/preflight.py" --json
```

Before an authorized collection, add `--live` to probe the existing Chrome DevTools Protocol (CDP) endpoint:

```bash
python3 "$SKILL_DIR/scripts/preflight.py" --live --json
```

Live preflight never starts, restarts, terminates, or reconfigures Chrome. It does not receive selected platforms, so it does not prove page availability or login state. The runtime controller performs those checks before it creates output.

## Use the five entrypoints

The deployed `current/scripts/` directory contains these entrypoints:

- `scrape_all.py`: sequential multi-platform creator controller
- `scrape_bilibili.py`: Bilibili creator or search
- `scrape_xhs.py`: Xiaohongshu creator or search
- `scrape_douyin.py`: Douyin creator or search
- `scrape_weibo.py`: Weibo creator or search

The adapter selects the correct entrypoint. Do not invoke a platform entrypoint directly for normal skill use.

## Collect creator records

Use a mode-`0600` profile containing every selected `platform_uids` value:

```bash
python3 "$SKILL_DIR/scripts/run_collection.py" \
  --profile "$PROFILE_PATH" \
  --platform bilibili,xhs,douyin,weibo \
  --count 10 \
  --allow-navigation \
  --platform-timeout 600 \
  --json-summary
```

Use `--bilibili-count`, `--xhs-count`, `--douyin-count`, or `--weibo-count` for selected-platform overrides. A matching `--<platform>-uid` overrides the private profile.

Xiaohongshu creator collection is detail-first by default and always applies its complete-record contract; `--xhs-complete` remains accepted for compatibility. Use `--complete` or `--bilibili-complete` when Bilibili also needs complete evidence. Add `--xhs-comments 10` only when Xiaohongshu is selected; the result is incomplete if fewer than the requested comments are available for a note that reports enough comments.

Xiaohongshu complete mode keeps each successfully opened note visible for one randomized 5–15 second settle after the detail response passes its immediate risk check and before collection values, DOM fallbacks, or comments are read. Keep a sufficient `--platform-timeout` for the requested count; the 600-second example above safely accommodates ordinary bounded batches without reducing this dwell.

For each selected record, the runtime performs at most one Xiaohongshu detail open and one click command. If the requested comment slice is still short after the initial visible read, it scrolls only the unique visible comment container at most three times and waits 1,500 ms after each successful scroll. It stops on enough comments, a missing or ambiguous container, non-scrollability, no growth, the exhausted budget, or any risk signal. It does not refresh or reopen the detail. A non-risk comment shortfall remains partial evidence; a risk signal stops the run before screenshot or retry.

Only one adapter collection may own the dedicated browser profile at a time. A second run fails before preflight or output creation. If a Xiaohongshu platform timeout occurs after one or more detail records finished, those completed records remain in the failed run's JSON, report, checkpoint, and manifest count; they are partial evidence, not a successful run.

Pass `--allow-navigation` only after explicit authorization to navigate exact allowlisted hosts during this run. The controller opens one temporary page per selected platform in the existing browser context, keeps existing pages unchanged, and closes only its temporary pages after the run. Omit it for read-only work and passive collection from already open matching pages.

## Add optional Bilibili assistance and private screenshots

Both options default to `off`. BrowserSkill assistance is limited to Bilibili creator collection and requires explicit navigation authorization:

```bash
--browser-assist browserskill --screenshot-mode opened --allow-navigation
```

For Xiaohongshu, keep `--browser-assist off`. Its detailed article page, bounded comments, and screenshots use only the existing Playwright/CDP browser session:

```bash
--browser-assist off --screenshot-mode opened --allow-navigation
```

An explicit Xiaohongshu BrowserSkill request is rejected before navigation with `xhs-browser-assist-unsupported`. Use `--screenshot-mode all` only when every selected record needs private screenshot evidence and every effective count is positive. `opened` never creates an extra open solely for a screenshot and may retain count `0`. BrowserSkill 0.1.10 with extension 0.1.6 is the tested external Bilibili compatibility baseline. It is not installed by Media@Missher. Playwright/CDP registers Xiaohongshu responses before the exact click, binds the native ID, checks risks before and after capture, bounds full-page dimensions, and captures the PNG without creating a BrowserSkill session.

## Search one platform

Search accepts one platform and cannot use complete mode:

```bash
python3 "$SKILL_DIR/scripts/run_collection.py" \
  --platform weibo \
  --search "approved keyword" \
  --count 10 \
  --json-summary
```

Search does not require `platform_uids`. Use `--allow-navigation` only with the same explicit navigation authorization required for creator mode.

Bilibili search does not implement advanced browser assistance or screenshots. Requests combining Bilibili search with non-`off` `--browser-assist` or `--screenshot-mode` are rejected instead of silently succeeding.

## Bound count zero

Count `0` means collect as much as the safety page cap permits. It requires an explicit flag:

```bash
--count 0 --collect-as-much-as-safe
```

Count `0` cannot be combined with `--screenshot-mode all`, because that would create an unbounded screenshot obligation. `--screenshot-mode opened` remains permitted because it does not open additional records.

## Convert validated output

Set `--format json`, `csv`, `jsonl`, or `sqlite`. The runtime always creates private JSON first. The adapter validates that JSON before writing one converted output.

Each run uses a unique mode-`0700` directory. JSON, logs, reports, checkpoints, and converted outputs use mode `0600`. The runtime never creates Feishu artifacts or performs a remote Feishu write.

## Validate a current run

Use the exact run directory and recorded start epoch:

```bash
python3 "$SKILL_DIR/scripts/validate_run.py" \
  --run-dir "$RUN_DIR" \
  --started-epoch "$RUN_STARTED_EPOCH" \
  --platform bilibili,xhs \
  --expected-count 10 \
  --json-summary
```

Add the same complete flags used for collection. If the source Xiaohongshu run requested comments, pass the same `--xhs-comments N` value so standalone validation rechecks the request-bound comment contract. Add `--format` and `--output` only when converting accepted records.
When the source run requested screenshots, also pass its exact `--screenshot-mode opened|all`; validation remains offline and this flag does not navigate.

## Recover a previous release

An upgrade keeps the prior runtime as `previous-{release_timestamp}` and the prior dependency environment as `venv.previous-{release_timestamp}`. Full installation keeps prior skills outside both discovery roots under the private shared-home paths `recovery/codex/media-missher.previous-{release_timestamp}` and `recovery/openclaw/media-missher.previous-{release_timestamp}`. The installer JSON reports every exact current and recovery path.

The installer restores prior components automatically if atomic rotation fails. For manual recovery:

1. Stop new Media@Missher launches
2. Read the exact previous paths from the installer result or private handoff evidence
3. Verify ownership, release markers, path boundaries, and the shared install lock
4. Move the failed current component to a unique Trash destination with `/bin/mv`
5. Rename the exact previous component into its current location
6. Run offline preflight, live preflight when authorized, all five help commands, and the residual scanner

Never use a wildcard or recursive deletion. If cutover moved a replaced component to Trash, restore only the exact path recorded in the private handoff evidence.
