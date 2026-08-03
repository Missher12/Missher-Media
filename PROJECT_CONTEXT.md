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

## Safety contract

Multi-platform creator work runs sequentially. Count `0` requires `--collect-as-much-as-safe` and remains bounded by page caps. The runtime stops on platform risk, lock, block, cooldown, or documented HTTP signals.

The runtime connects only to an existing Chrome DevTools Protocol (CDP) browser. It never starts or reconfigures Chrome. Exact-host navigation requires explicit `--allow-navigation` authorization for the current collection or live acceptance run.

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

Task11 verified 13 normalized compatibility cases and 90 focused packaging, CLI, output, and validation tests. Record the final full-suite count only after all parallel installer hardening is committed and rerun.

## Live acceptance

Live acceptance is a separate authorized stage. It has not run against the new shared runtime during Task12 documentation work.

Before cutover, run live preflight against the existing browser. This probes the CDP endpoint but does not prove platform page or login state. Then run one sequential count-`1` creator collection across all four platforms. The runtime controller checks selected pages and visible login state before creating output.

Use Bilibili and Xiaohongshu complete modes with bounded Xiaohongshu comments. Validate native IDs, links, current timestamps, completeness, counts, no timeout, no risk stop, and no Feishu artifact.

Open a temporary page only with explicit navigation authorization. Close only the temporary page after validation. Do not retry a risk stop.

## Cutover

Cutover remains pending until offline, compatibility, staged skill, and live acceptance gates all pass.

The authorized sequence is:

1. Record read-only manifests, sizes, hashes, and versions for exact active targets
2. Run `python3 tools/install_media_missher.py --runtime-only`
3. Preflight staged Codex and OpenClaw packages against the shared home
4. Complete authorized four-platform live acceptance
5. Run `python3 tools/install_media_missher.py` for atomic full installation
6. Move only approved replaced targets to unique Trash destinations with exact `/bin/mv` arguments
7. Rerun preflight, five help commands, validation, permission checks, and active residual scans

Never use recursive deletion for cutover.

## Recovery

The installer rotates prior components to `previous-{release_timestamp}`, `venv.previous-{release_timestamp}`, and `media-missher.previous-{release_timestamp}` paths. It attempts automatic rollback when rotation fails.

For manual recovery, validate exact paths, ownership, release markers, and the install lock. Move a failed current component to a unique Trash destination, restore its matching previous component, then rerun all gates. Use the private handoff evidence to restore a component moved during destructive cutover.

Keep runtime outputs and historical evidence during rollback.

## Current limitations

- Live acceptance and destructive cutover are pending
- Platform response schemas, login markers, and challenge behavior can change without notice
- Creator collection needs a non-empty UID for every selected platform; search does not
- Navigation is disabled unless the current run has explicit authorization
- A failed non-risk prerequisite permits one retry only after correction and fresh preflight
- Task12 performs no live installation, browser navigation, collection, or Trash move
