# Run Media@Missher commands

Use these commands for installation, preflight, creator collection, search, validation, conversion, and recovery. Resolve the directory containing `SKILL.md` as `SKILL_DIR`.

## Install in two stages

Run installation commands from the source repository. The first command installs only `current/`, `venv/`, and private `state/` under `MEDIA_MISSHER_HOME` or `~/.local/share/media-missher`:

```bash
python3 tools/install_media_missher.py --runtime-only
```

Run offline tests, residual scans, staged skill preflight, and authorized live acceptance before full cutover. The second command atomically installs the runtime and both compact skills:

```bash
python3 tools/install_media_missher.py
```

Do not run either command during a read-only review. Do not perform full cutover until every gate passes.

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
  --platform-timeout 600 \
  --json-summary
```

Use `--bilibili-count`, `--xhs-count`, `--douyin-count`, or `--weibo-count` for selected-platform overrides. A matching `--<platform>-uid` overrides the private profile.

Add `--complete` for Bilibili and Xiaohongshu complete collection. You can instead select one with `--bilibili-complete` or `--xhs-complete`. Add `--xhs-comments 10` only when Xiaohongshu is selected.

Pass `--allow-navigation` only after explicit authorization to navigate exact allowlisted hosts during this run. Omit it for read-only work and passive collection from already open matching pages.

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

## Bound count zero

Count `0` means collect as much as the safety page cap permits. It requires an explicit flag:

```bash
--count 0 --collect-as-much-as-safe
```

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

Add the same complete flags used for collection. Add `--format` and `--output` only when converting accepted records.

## Recover a previous release

An upgrade keeps the prior runtime as `previous-{release_timestamp}` and the prior dependency environment as `venv.previous-{release_timestamp}`. Full installation also keeps each prior skill as `media-missher.previous-{release_timestamp}`.

The installer restores prior components automatically if atomic rotation fails. For manual recovery:

1. Stop new Media@Missher launches
2. Read the exact previous paths from the installer result or private handoff evidence
3. Verify ownership, release markers, path boundaries, and the shared install lock
4. Move the failed current component to a unique Trash destination with `/bin/mv`
5. Rename the exact previous component into its current location
6. Run offline preflight, live preflight when authorized, all five help commands, and the residual scanner

Never use a wildcard or recursive deletion. If cutover moved a replaced component to Trash, restore only the exact path recorded in the private handoff evidence.
