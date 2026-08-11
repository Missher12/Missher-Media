# Media@Missher V15 project context

Media@Missher collects and validates Bilibili, Xiaohongshu, Douyin, and Weibo records through one independently authored shared runtime. This file records the architecture, verification workflow, deployment state, and recovery boundaries for future work.

The current source product version is Media@Missher V15 (`15.0.0`), recorded once in the repository `VERSION` file. Product versioning is separate from the installer's unique UTC timestamp-and-random-suffix deployment release so repeated upgrades and exact rollback paths remain collision-free.

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

`current/` contains the deployed source, product `VERSION`, and five entrypoints. `venv/` contains Python 3.11 or newer dependencies. Mode-`0700` `state/` contains locks, cache, checkpoints, reports, and default private runs.

The runtime home uses `.media-missher-owner.json` to prove installer ownership and `.media-missher-install.lock` to serialize installation against launch. In the current recommended `--codex-only` mode, one `.media-missher-release` value must match `current/`, `venv/`, and the Codex skill. The backward-compatible default dual-skill mode additionally includes the OpenClaw skill.

V15 adds an optional BrowserSkill bridge while preserving Playwright/CDP as the collection authority. BrowserSkill 0.1.10 with extension 0.1.6 may health-check, create one bounded session, borrow the one exact marked Media@Missher temporary tab, snapshot, click, return, and stop. It never owns response capture, identifiers, risk policy, parsing, screenshots, cookies, browser storage, anti-detection, or verification bypass.

Bilibili and Xiaohongshu creator collection may request `--browser-assist browserskill` or `--screenshot-mode opened|all`; both default to `off` and any non-default mode requires explicit `--allow-navigation`. Bilibili search rejects these advanced modes. Bilibili pure text/image dynamics are bound by exact `dynamic_id`; Xiaohongshu keeps its exact response listener and applies the 5–15 second settle only to complete mode. Screenshots remain private mode-`0600` PNG files under the current run and carry run-relative path, `article` or `full_page_fallback` capture kind, `screenshot_observed_at`, and `screenshot_sha256` metadata. `all` requires a positive count; `opened` may retain count `0` because it creates no additional opens.

BrowserSkill 0.1.10 performs its own upstream bundled skill sync whenever an explicitly assisted run executes `bsk session start`; JSON output only hides the hint. Media@Missher does not bypass that behavior. Its preflight remains read-only, starts no session, and downloads or upgrades neither the BrowserSkill binary nor its extension.

### Adapter boundary

`media-missher/` is the Codex skill and standard-library adapter. It resolves `RuntimeLayout`, validates requests, invokes the shared runtime, validates current evidence, and owns CSV, JSONL, and SQLite conversion.

`openclaw-media-missher/` is retained as a compact backward-compatibility package. OpenClaw was retired from the current machine and `~/.openclaw` is absent, so current installation must not recreate it. The supported current Codex path is:

- `~/.codex/skills/media-missher`

Historical dual-skill environments may also use `~/.openclaw/workspace/skills/media-missher` through the installer's no-mode compatibility behavior.

Neither skill contains a platform implementation, dependency environment, user data, or personal absolute path.

## Standalone use

Installed skills are optional. The repository adapter is the supported no-skill entrypoint and invokes the shared Python 3.11-or-newer runtime:

```bash
python3 tools/install_media_missher.py --codex-only
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

Xiaohongshu complete mode attaches the exact detail-response listener before clicking the exact visible note target. It checks the captured response for HTTP or payload risk immediately, then keeps the opened note visible for one cryptographically sampled 5–15 second settle before parsing collection metrics, using DOM fallbacks, or reading comments. It checks for a visible challenge again after the settle. Ordinary creator previews, search, failed clicks, capture timeouts, and risk responses do not incur this dwell; every successfully opened complete-mode note incurs it exactly once.

Every run uses a unique mode-`0700` directory and mode-`0600` artifacts. Media@Missher never creates Feishu artifacts or performs a remote Feishu write.

## Test commands

Run the complete offline suite with all sockets disabled:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket
```

Run the documentation and active residual tests with:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-project \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_packaging.py tests/test_active_residuals.py
```

Run `python3 tools/scan_active_residuals.py --root .` after each documentation or packaging change. Run compile checks and all five entrypoint help commands before deployment.

Current V15 offline evidence (2026-08-11): the focused sockets-disabled suite passed 605 tests and the complete sockets-disabled suite passed 870 tests, with zero failures and zero skips. The one warning is the expected `pytest-socket` warning from the test that proves AF_INET and AF_INET6 remain blocked while Unix sockets are allowed. Runtime compilation, all five `--help` entrypoints, the active residual scan, installer version output, both skill validators, and `git diff --check` also passed. This is source-only offline evidence and is not installation or live-platform acceptance.

Historical V12 evidence: the V12 source baseline passed 664 tests with Playwright installed, zero failures, and zero skips. The full suite ran with sockets disabled. All five runtime entrypoints accepted `--help`, the active residual scanner returned zero for the three source package roots, and the official skill validator accepted both packages. These dated results remain historical evidence and are not V15 proof.

## Live acceptance

V15 live acceptance has not been performed. No V15 real-platform collection, BrowserSkill session, installation, tag, GitHub push, or release has been executed during implementation. The following evidence is retained solely as historical V12 behavior and must not be presented as current V15 acceptance.

Live acceptance is a separate authorized stage. The latest sequential count-`1` run at `~/.local/share/media-missher/state/runs/run-20260803T183331Z-yio893cc` produced one current record for every platform in 51.704 seconds with no timeout, risk signal, or Feishu artifact. Bilibili complete mode passed with 35 fields. Douyin and Weibo passed with 24 and 22 fields. Xiaohongshu matched the expected note, consumed a fresh official detail response, and produced 53 fields including body, author, publish time, location, media, tags, and the other engagement values, but remained incomplete only because `collected` was unknown.

The old active implementation distinguishes a missing or `null` detail API count from an explicitly present empty string: missing/`null` remains unknown, while present-empty means zero. The independent runtime had collapsed both cases to unknown. It now restores that narrow detail-API-only distinction without changing list, search, DOM, or global count parsing. Missing values, `null`, and placeholders remain incomplete; no stale preview value is promoted to fresh detail evidence.

The explicitly authorized post-compatibility Xiaohongshu run at `~/.local/share/media-missher/state/runs/run-20260804T011422Z-waihwmir` opened one exact note, captured a current target-bound detail API response, and produced one complete 50-field record with a non-null numeric `collected` value. It finished in 43.997 seconds with no timeout, risk signal, or Feishu artifact.

The later 5–15 second Xiaohongshu open-note settle changes timing only; it does not change target selection, response binding, detail parsing, schema, or other platforms. It passes 113 Xiaohongshu tests, including minimum/maximum timing, exactly once per note, ordinary/search exclusion, immediate HTTP risk stop, post-settle challenge stop, modal cleanup, and existing collection fallbacks. To avoid unnecessary additional account traffic, no real collection was repeated immediately after this dwell-only change. A future explicitly authorized live run may confirm wall-clock dwell, but must not be represented as already completed.

Before any future live acceptance, run live preflight against the existing browser. This probes the CDP endpoint but does not prove platform page or login state. The runtime controller checks selected pages and visible login state before creating output. With explicit navigation authorization, it prepares temporary pages and closes only those pages after the run.

Open a temporary page only with explicit navigation authorization. Close only the temporary page after validation. Do not retry a risk stop.

## Historical V12 Cutover

The local atomic cutover completed with release `20260804T014259715054Z-e8a088d6`. Before installation, the three source roots were frozen at SHA-256 `af820b6ca4fa62f291d179a4f0aefe931e7719935233c54f8a7cd3206fb2a07b`; the hash was unchanged after staged installation and before full cutover.

The installer synchronized the shared runtime, dependency environment, Codex skill, and OpenClaw skill to the same release. Both installed skills pass live CDP preflight, every installed tree matches its source tree apart from release markers and caches, active residual scans return zero, state is mode `0700`, and release markers are mode `0600`.

The prior residual-bearing 578MB OpenClaw recovery tree was moved recoverably to `~/.Trash/Media-Missher-old-openclaw-20260804T014259Z/`. The active OpenClaw skill is a compact 24KB package; the active Codex skill is 136KB. The zero-residual claim applies to the repository source roots and active installed Media@Missher trees, not intentionally retained Trash contents or third-party packages in the owned virtual environment.

Never use recursive deletion for cutover or recovery.

## Recovery

The installer rotates prior runtime components to `previous-{release_timestamp}` and `venv.previous-{release_timestamp}`. Prior Codex and OpenClaw skills move outside their discovery roots into private mode-`0700` `recovery/codex/` and `recovery/openclaw/` directories under the shared runtime home. The installer reports every exact recovery path and attempts automatic rollback when rotation fails.

For manual recovery, validate exact paths, ownership, release markers, and the install lock. Move a failed current component to a unique Trash destination, restore its matching previous component, then rerun all gates. Use the private handoff evidence to restore a component moved during destructive cutover.

Keep runtime outputs and historical evidence during rollback.

## Current limitations

- V15 live acceptance, installation, and release remain pending final supervision; offline tests do not prove current platform DOM compatibility
- The randomized Xiaohongshu open-note dwell is fully offline-tested in the V15 source but V15 is not installed; do not claim installed or live post-dwell proof without a future explicitly authorized cutover and collection
- Xiaohongshu complete batches add 5–15 seconds per successfully opened note; increase `--platform-timeout` for larger counts rather than reducing or removing the dwell
- Platform response schemas, login markers, and challenge behavior can change without notice
- Creator collection needs a non-empty UID for every selected platform; search does not
- Navigation is disabled unless the current run has explicit authorization
- A failed non-risk prerequisite permits one retry only after correction and fresh preflight
- The repository has no selected repository-wide public-distribution license; local installation is complete, but a combined public bundle is not authorized
