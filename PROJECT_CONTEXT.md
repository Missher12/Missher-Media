# Media@Missher project context

Media@Missher collects and validates Bilibili, Xiaohongshu, Douyin, and Weibo records through one independently authored shared runtime. This file records the architecture, verification workflow, deployment state, and recovery boundaries for future work.

## Project goal

Preserve creator collection, single-platform search, complete Bilibili and Xiaohongshu evidence, native identifiers, null-versus-zero values, private output, sequential execution, and immediate risk stops without retaining replaced implementations in active paths.

## Architecture

The repository separates source, deployed runtime, adapters, and installed skills.

### Source boundary

`runtime/` contains platform modules, browser integration, safety controls, storage, models, and five scripts. `tools/install_media_missher.py` installs source-controlled components atomically. Tests use synthetic fixtures and do not read or import replaced source trees.

### Runtime boundary

`MEDIA_MISSHER_HOME` selects the shared runtime home. Its default is `~/.local/share/media-missher`:

```text
~/.local/share/media-missher/
├── current/
├── venv/
└── state/
```

`current/` contains the deployed source and five entrypoints. `venv/` contains Python 3.11 or newer dependencies. Mode-`0700` `state/` contains locks, cache, checkpoints, reports, and default private runs.

The runtime home uses `.media-missher-owner.json` to prove installer ownership and `.media-missher-install.lock` to serialize installation against launch. One `.media-missher-release` value must match `current/`, `venv/`, the Codex skill, and the OpenClaw skill.

### Adapter boundary

`media-missher/` is the Codex skill and standard-library adapter. It resolves `RuntimeLayout`, validates requests, invokes the shared runtime, validates current evidence, and owns CSV, JSONL, and SQLite conversion.

`openclaw-media-missher/` is a compact OpenClaw package. Both installed skills use the same release markers and shared runtime:

- `~/.codex/skills/media-missher`
- `~/.openclaw/workspace/skills/media-missher`

Neither skill contains a platform implementation, dependency environment, user data, or personal absolute path.

## Standalone use

Installed skills are optional. The repository adapter is the supported no-skill entrypoint and invokes the shared Python 3.11-or-newer runtime:

```bash
python3 tools/install_media_missher.py --runtime-only
python3 media-missher/scripts/preflight.py --profile "$PROFILE_PATH" --live --json
python3 media-missher/scripts/run_collection.py \
  --profile "$PROFILE_PATH" \
  --platform bilibili,xhs,douyin,weibo \
  --count 1 \
  --allow-navigation \
  --no-feishu \
  --json-summary
```

Do not invoke `runtime/scripts/*.py` with a system Python older than 3.11. The repository adapter selects the owned shared virtual environment and does not import either installed skill or a replaced source tree.

## Safety contract

Multi-platform creator work runs sequentially. Count `0` requires `--collect-as-much-as-safe` and remains bounded by page caps. The runtime stops on platform risk, lock, block, cooldown, or documented HTTP signals.

The runtime connects only to an existing Chrome DevTools Protocol (CDP) browser. It never starts or reconfigures Chrome. Exact-host navigation requires explicit `--allow-navigation` authorization for the current collection or live acceptance run. Authorized navigation creates temporary pages inside the uniquely proven existing browser context, leaves existing user pages unchanged, and closes only the temporary pages on success or failure. Ambiguous multiple contexts fail closed. Entry `403`, `429`, and visible challenges are non-retryable risk stops before output creation.

Every run uses a unique mode-`0700` directory and mode-`0600` artifacts. Media@Missher never creates Feishu artifacts or performs a remote Feishu write.

## Test commands

Run the complete offline suite with all sockets disabled:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  python -m pytest -q -p no:cacheprovider --disable-socket
```

Run the documentation and active residual tests with:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --with pytest \
  python -m pytest -q -p no:cacheprovider \
  tests/test_packaging.py tests/test_active_residuals.py
```

Run `python3 tools/scan_active_residuals.py --root .` after each documentation or packaging change. Run compile checks and all five entrypoint help commands before deployment.

The current source baseline passes 659 tests with Playwright installed, zero failures, and zero skips. The full suite runs with sockets disabled. All 53 Python source and test files compile, all five runtime entrypoints accept `--help`, the active residual scanner returns zero for the source tree, and the Codex skill validator accepts the package.

## Live acceptance

Live acceptance is a separate authorized stage. The latest sequential count-`1` run at `~/.local/share/media-missher/state/runs/run-20260803T183331Z-yio893cc` produced one current record for every platform in 51.704 seconds with no timeout, risk signal, or Feishu artifact. Bilibili complete mode passed with 35 fields. Douyin and Weibo passed with 24 and 22 fields. Xiaohongshu matched the expected note, consumed a fresh official detail response, and produced 53 fields including body, author, publish time, location, media, tags, and the other engagement values, but remained incomplete only because `collected` was unknown.

The old active implementation distinguishes a missing or `null` detail API count from an explicitly present empty string: missing/`null` remains unknown, while present-empty means zero. The independent runtime had collapsed both cases to unknown. It now restores that narrow detail-API-only distinction without changing list, search, DOM, or global count parsing. Missing values, `null`, and placeholders remain incomplete; no stale preview value is promoted to fresh detail evidence. The fix passes 109 Xiaohongshu tests, the 659-test full suite, and independent static review.

The safe live artifact intentionally excludes raw payload shape, so the prior run cannot prove whether its source field was absent/`null` or present-empty. The corrected runtime release `20260803T183949270349Z-139870f4` is installed and passes all 14 live preflight checks, but the retry budget is exhausted. One future explicitly authorized fresh four-platform acceptance is still required before active-skill cutover or recovery of replaced directories. Do not treat the prior partial run or the offline compatibility fix as that final live proof.

Before cutover, run live preflight against the existing browser. This probes the CDP endpoint but does not prove platform page or login state. Then run one sequential count-`1` creator collection across all four platforms. The runtime controller checks selected pages and visible login state before creating output. With explicit navigation authorization, the controller prepares one temporary page per selected platform and closes only those pages after the run.

Use Bilibili and Xiaohongshu complete modes with bounded Xiaohongshu comments. Validate native IDs, links, current timestamps, completeness, counts, no timeout, no risk stop, and no Feishu artifact.

Open a temporary page only with explicit navigation authorization. Close only the temporary page after validation. Do not retry a risk stop.

## Cutover

Cutover remains pending until offline, compatibility, staged skill, and live acceptance gates all pass.

The authorized sequence is:

1. Record read-only manifests, sizes, hashes, and versions for exact active targets and freeze a content hash for `runtime/`, `media-missher/`, and `openclaw-media-missher/`
2. Run `python3 tools/install_media_missher.py --runtime-only`
3. Preflight staged Codex and OpenClaw packages against the shared home
4. Complete authorized four-platform live acceptance
5. Prove the frozen source hash is unchanged, then run `python3 tools/install_media_missher.py` for atomic full installation and verify all three installed trees against that same source
6. If old residual-bearing skills are to leave recovery, move only the exact `codex_previous` and `openclaw_previous` paths reported by the installer JSON to unique Trash destinations with exact `/bin/mv` arguments; never move either new `*_current` path
7. Rerun preflight, five help commands, validation, permission checks, and active residual scans

Never use recursive deletion for cutover.

## Recovery

The installer rotates prior runtime components to `previous-{release_timestamp}` and `venv.previous-{release_timestamp}`. Prior Codex and OpenClaw skills move outside their discovery roots into private mode-`0700` `recovery/codex/` and `recovery/openclaw/` directories under the shared runtime home. The installer reports every exact recovery path and attempts automatic rollback when rotation fails.

For manual recovery, validate exact paths, ownership, release markers, and the install lock. Move a failed current component to a unique Trash destination, restore its matching previous component, then rerun all gates. Use the private handoff evidence to restore a component moved during destructive cutover.

Keep runtime outputs and historical evidence during rollback.

## Current limitations

- One fresh post-compatibility-fix four-platform live acceptance and active cutover are pending
- The active OpenClaw skill still contains the recoverable pre-cutover tree; zero replaced-implementation residue is not yet claimed
- Platform response schemas, login markers, and challenge behavior can change without notice
- Creator collection needs a non-empty UID for every selected platform; search does not
- Navigation is disabled unless the current run has explicit authorization
- A failed non-risk prerequisite permits one retry only after correction and fresh preflight
- Do not recover replaced directories until the fresh live run, full installation, permission checks, and active residual scans all pass
