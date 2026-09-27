# Run Media@Missher commands

Use these commands for installation, preflight, creator collection, search, a Weibo topic task, export, validation, conversion, and recovery. Resolve the directory containing `SKILL.md` as `SKILL_DIR`.

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

Live preflight never starts, restarts, terminates, or reconfigures Chrome. The CDP probe checks the existing Chrome endpoint. Preflight does not receive selected platforms, so it does not prove page availability or login state. The runtime controller performs those checks before it creates output.

## Use the five entrypoints

The deployed `current/scripts/` directory contains these entrypoints:

- `scrape_all.py`: sequential multi-platform controller, including `x` and a private `--targets-json` plan
- `scrape_bilibili.py`: Bilibili creator or search
- `scrape_xhs.py`: Xiaohongshu creator or search
- `scrape_douyin.py`: Douyin creator or search
- `scrape_weibo.py`: Weibo creator, search, or `--topic`

The adapter selects the correct entrypoint. Do not invoke a platform entrypoint directly for normal skill use.

## Chrome CDP only

Chrome CDP is the only active backend. Omit `--backend` or use `--backend cdp`; it attaches through Playwright/CDP to the existing signed-in Chrome endpoint and works independently of the Agent host or DSH.

The backend stays `cdp` in the plan, manifest and export provenance. Explicit CLI values override the private plan, then the profile; omitted values preserve the plan, including explicit `0` and `off`. An old non-CDP preference or plan is refused before collection, never silently rewritten. There is no `auto` or alternate backend.

Computer Use and its lifecycle command are removed. Old requests return `backend-retired-computer-use`; BrowserSkill requests return `backend-retired-browserskill`. Historical runs remain readable and exportable with their original provenance, but cannot resume a retired backend. Never install or invoke an alternative browser controller to work around a failure.

## Retired browser-assist bridge

`--browser-assist browserskill` is retired. It is not a backend, and it no longer starts a browser, a session, or a click. At the CLI boundary the request prints exactly one line to stderr and exits 78 before any browser action:

```text
media-missher-diagnostic platform=<p> kind=precondition code=browser-assist-replaced
```

Keep `--browser-assist off`. BrowserSkill collection is also retired; historical diagnostic codes are retained only for reading old evidence.

Private screenshots remain available with `--browser-assist off`, the `cdp` backend, and explicit navigation authorization:

```bash
--browser-assist off --backend cdp --screenshot-mode opened --allow-navigation
```

`--screenshot-mode all` is only for CDP runs where every selected record needs private screenshot evidence and every effective count is positive. `opened` never creates an extra open solely for a screenshot and may retain count `0`.

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

For a multi-target or multi-account run, use the runtime controller directly with a private plan:

```bash
python3 "$RUNTIME_HOME/current/scripts/scrape_all.py" creator \
  --targets-json "$PLAN_PATH" \
  --output-dir "$RUN_DIR" \
  --no-feishu
```

X creator collection uses a handle or numeric user id through the same controller:

```bash
python3 "$RUNTIME_HOME/current/scripts/scrape_all.py" creator \
  --platform x --x-uid "$X_HANDLE" --count 20 \
  --backend cdp --output-dir "$RUN_DIR" --no-feishu
```

Without `--allow-navigation`, each runtime controller example above collects passively, so the matching profile, search, or topic page must already be open in the existing browser. Add `--allow-navigation` only with explicit authorization for that run.

Xiaohongshu creator collection is detail-first by default and always applies its complete-record contract; `--xhs-complete` remains accepted for compatibility. Use `--complete` or `--bilibili-complete` when Bilibili also needs complete evidence. Add `--xhs-comments 10` only when Xiaohongshu is selected; the result is incomplete if fewer than the requested comments are available for a note that reports enough comments.

Xiaohongshu complete mode keeps each successfully opened note visible for one randomized 5–15 second settle after the detail response passes its immediate risk check and before collection values, DOM fallbacks, or comments are read. Keep a sufficient `--platform-timeout` for the requested count; the 600-second example above safely accommodates ordinary bounded batches without reducing this dwell.

For each selected record, the runtime performs at most one Xiaohongshu detail open and one click command. If the requested comment slice is still short after the initial visible read, it scrolls only the unique visible comment container at most three times and waits 1,500 ms after each successful scroll. It stops on enough comments, a missing or ambiguous container, non-scrollability, no growth, the exhausted budget, or any risk signal. It does not refresh or reopen the detail. A non-risk comment shortfall remains partial evidence; a risk signal stops the run before screenshot or retry.

Only one collection may own the dedicated browser profile or the shared collection lease at a time. A second run fails before preflight or output creation. If a Xiaohongshu platform timeout occurs after one or more detail records finished, those completed records remain in the failed run's JSON, report, checkpoint, and manifest count; they are partial evidence, not a successful run.

Pass `--allow-navigation` only after explicit authorization to navigate exact allowlisted hosts during this run. The controller opens one temporary page per selected target in the existing browser context, keeps existing pages unchanged, and closes only its temporary pages after the run. Omit it for read-only work and passive collection from already open matching pages.

## Bound count and the collection envelope

Count `0` means collect as much as the safety page cap permits. It requires an explicit flag:

```bash
--count 0 --collect-as-much-as-safe
```

Count `0` cannot be combined with `--screenshot-mode all`, because that would create an unbounded screenshot obligation. `--screenshot-mode opened` remains permitted because it does not open additional records.

`--count-mode fixed` is the default and keeps the existing per-platform count behaviour. `--count-mode best_effort` means collect as much as you can:

```bash
python3 "$RUNTIME_HOME/current/scripts/scrape_all.py" creator \
  --targets-json "$PLAN_PATH" \
  --count-mode best_effort --run-deadline 3600 \
  --per-target-budget 200 --batch-pages 3 --batch-interval 120 \
  --backend cdp --output-dir "$RUN_DIR" --no-feishu
```

`best_effort` has no fixed ten-record total cap and promises no total. It keeps paginating inside the authorized `--run-deadline`, bounded by a finite per-platform batch budget, a stall limit, and cancellation. A budget pause is reported as `budget-exhausted`, not as finished collection. `--batch-pages` and `--batch-interval` may only tighten the platform's own limits and a plan can never relax them; `--per-target-budget` adds an explicit total record cap for a `best_effort` target.

The stop reason is fixed and distinct from the overall status: `natural-end`, `no-new-records`, `budget-exhausted`, `run-deadline`, `count-reached`, `not-logged-in`, `permission-denied`, `risk-stopped`, `timeout`, `cancelled`, `empty-results`, `target-changed`, `session-lost`, `unsupported`, or `error`.

The Xiaohongshu policy of at most 10 notes and 3 pages per batch with at least 600 seconds between batch starts, plus its persistent risk pause, is unchanged. No plan, backend switch, target change, or different runtime home can relax it.

## Run a Weibo topic task

`--topic` accepts a topic name or an official topic URL and runs a real topic task instead of a keyword search:

```bash
python3 "$RUNTIME_HOME/current/scripts/scrape_weibo.py" search \
  --topic "话题名称" \
  --count-mode best_effort --run-deadline 1800 --per-target-budget 300 \
  --backend cdp --output-dir "$RUN_DIR" --no-feishu
```

The task verifies the topic input, pages through the visible topic posts, extracts the outer poster of each visible post, dedups by Weibo UID, then visits each user's public homepage once per run. It saves posts, user records, and topic-to-user relations.

A plain `#话题#` uses the standard topic page. A 超话 (super topic) is a different page contract and is refused with `topic-container-unsupported`; it is never faked as a keyword search. Participants are only the authors of observed topic posts, including a forwarder who really appears in the results; quote authors, recommendation-card authors, viewers, and likers are never participants. The run never claims all participants and never recurses into followers, following, or all posts. A homepage that is unavailable, deleted, permission-limited, or login-walled records a fixed reason and keeps the confirmed user entry and its source relations.

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

Bilibili search does not implement screenshots. Requests combining Bilibili search with a non-`off` `--screenshot-mode` are rejected instead of silently succeeding.

## Convert validated output

Set `--format json`, `csv`, `jsonl`, or `sqlite`. The runtime always creates private JSON first. The adapter validates that JSON before writing one converted output.

Each run uses a unique mode-`0700` directory. JSON, logs, reports, checkpoints, and converted outputs use mode `0600`. The runtime never creates Feishu artifacts or performs a remote Feishu write.

## Export saved results

Export is a separate, selection-driven, offline step. It reads only already-saved verified local results, so it never opens a browser and can be re-filtered and re-exported as often as needed:

```bash
python3 "$SKILL_DIR/scripts/manage_runs.py" export \
  --data-root "$DATA_ROOT" \
  --run-id "$RUN_ID" \
  --record-kinds posts,topic_participants,user_profiles \
  --platforms weibo,x \
  --topics "话题名称" \
  --field-groups identity,metrics,evidence \
  --format xlsx --file-name "export.xlsx"
```

The same selection is available through `media_missher_runs action=export`, which forwards the identical options. Accepted options are `--record-kinds posts|topic_participants|user_profiles`, `--platforms`, `--topics`, `--targets`, `--fields`, `--field-groups`, `--format xlsx|csv|json|jsonl|sqlite`, `--file-name`, and `--overwrite`.

Export rules:

- A requested field that was never collected is reported back as a missing field instead of being collected now.
- Partial, risk-stopped, and cancelled runs still export their independently verified records and keep their status, missing fields, and observation times.
- An existing output file is never overwritten unless `--overwrite` is passed explicitly.
- Export never navigates, retries, resumes, or clears a risk pause, and historical export is labelled rather than counted as fresh collection.

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
