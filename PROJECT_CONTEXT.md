# Media@Missher V15.2.1 project context

Media@Missher collects and validates Bilibili, Xiaohongshu, Douyin, and Weibo records through one independently authored shared runtime. This file records the architecture, verification workflow, deployment state, and recovery boundaries for future work.

The current source and installed operational candidate version is Media@Missher V15.2.1 (`15.2.1`), recorded once in the repository `VERSION` file. Ordinary Bilibili and Douyin creator collection is live-accepted; the optional Bilibili complete-mode exact-target blocker below remains intentionally unresolved. Product versioning is separate from the installer's unique UTC timestamp-and-random-suffix deployment release so repeated upgrades and exact rollback paths remain collision-free.

## Project goal

Preserve creator collection, single-platform search, complete Bilibili and Xiaohongshu evidence, native identifiers, null-versus-zero values, private output, sequential execution, and immediate risk stops without retaining replaced implementations in active paths.

## DeepSeek Harness Bundle

The current Agent-facing delivery is the private macOS Bundle `dsh-media-missher` version `0.1.0`, built from the exact Media@Missher `15.2.1` source. It is installed into the Harness `web` profile by double-clicking `Install Media@Missher Harness Plugin.command`. The installer uses only the Electron runtime, CLI, and pnpm bundled in `/Applications/DeepSeek Harness.app`; it requires no user-managed Node.js or terminal workflow. Before mutation it verifies the canonical archive and privately backs up the profile package manifest. Installation succeeds only when the effective Cordis configuration contains both `id: media-missher` and `name: dsh-media-missher`.

The Bundle registers one model-visible tool, `media_missher_collect`. A zero-argument call selects Bilibili, Xiaohongshu, Douyin, and Weibo, requests ten records per platform, runs the existing controller sequentially, disables Feishu, and creates one mode-`0600` Excel workbook in the unique private run directory. The workbook has `Summary`, `All Platforms`, `Bilibili`, `Xiaohongshu`, `Douyin`, and `Weibo` sheets. Identifiers remain text, formula-prefixed strings are escaped, nested values are JSON strings, and the destination is linked atomically without overwriting an existing file.

Harness never receives UIDs as tool arguments and the model result contains no raw records. The adapter reads the existing mode-`0600` profile, reuses or atomically provisions only exact runtime version `15.2.1`, validates controller-owned manifest evidence beneath the configured output root, and returns only status, selected platforms, requested and collected counts, and local manifest/workbook/run paths. Existing controller rules remain authoritative for one-browser ownership, exact response binding, risk stops, private output, and navigation cleanup.

The canonical private artifact is `harness-plugin/dist/dsh-media-missher-0.1.0.tgz`. `harness-plugin/scripts/native-smoke.mjs` proves the real Harness CLI lifecycle in a temporary `DSH_HOME`: install, effective-config discovery, default 4x10 synthetic tool projection, six-sheet workbook reopen, uninstall, and preservation of adjacent profile/state files. Public npm or GitHub Release publication remains prohibited until a repository-wide license and provenance review is complete.

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

The runtime home uses `.media-missher-owner.json` to prove installer ownership and `.media-missher-install.lock` to serialize installation against launch. Adapter collections hold a separate private `.media-missher-collection.lock` exclusively through collection and validation so the dedicated browser profile cannot be used by overlapping runs. In the current recommended `--codex-only` mode, one `.media-missher-release` value must match `current/`, `venv/`, and the Codex skill. The backward-compatible default dual-skill mode additionally includes the OpenClaw skill.

V15 retains an optional BrowserSkill bridge for Bilibili creator details while preserving Playwright/CDP as the collection authority. BrowserSkill 0.1.10 with extension 0.1.6 may health-check, create one bounded session, borrow the one exact marked Media@Missher temporary tab, snapshot, click, return, and stop. It never owns response capture, identifiers, risk policy, parsing, screenshots, cookies, browser storage, anti-detection, or verification bypass. Xiaohongshu does not use this bridge.

Bilibili creator collection may request `--browser-assist browserskill`; Xiaohongshu requires `--browser-assist off` and rejects explicit BrowserSkill before navigation with `xhs-browser-assist-unsupported`. Bilibili and Xiaohongshu may request `--screenshot-mode opened|all`; all non-default modes require explicit `--allow-navigation`. Bilibili search rejects these advanced modes. Bilibili pure text/image dynamics are bound by exact `dynamic_id`; Xiaohongshu uses the one existing CDP session for exact-click same-page or popup detail resolution, keeps its exact response listener, and applies the 5–15 second settle only to complete mode. Screenshots remain private mode-`0600` PNG files under the current run and carry run-relative path, `article` or `full_page_fallback` capture kind, `screenshot_observed_at`, and `screenshot_sha256` metadata. `all` requires a positive count; `opened` may retain count `0` because it creates no additional opens.

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

Xiaohongshu creator collection is detail-first and complete by default. It attaches the exact detail-response listener before clicking the exact visible note target through the bridge-free CDP detail coordinator. The coordinator resolves the exact same-page detail or exact popup within the existing browser context; it neither starts nor borrows a BrowserSkill browser. It checks the captured response for HTTP or payload risk immediately, then keeps the opened note visible for one cryptographically sampled 5–15 second settle before parsing collection metrics, using DOM fallbacks, or reading comments. It checks for a visible challenge again after the settle. Complete evidence requires current-detail liked, comments, collected, and shares values plus current-detail body, author, media, and any requested comment slice. Ordinary search, failed clicks, capture timeouts, and risk responses do not incur this dwell; every successfully opened creator note incurs it exactly once. Completed note prefixes are retained as failed partial evidence if a later note reaches the platform timeout.

The installed 2026-08-13 Xiaohongshu hardening adds a per-record action budget without changing the public schema: at most one exact detail open, one CDP click, and three scrolls of the uniquely resolved visible comment container, with a fixed 1,500 ms wait after each successful scroll. It never scrolls the whole page, clicks a “more” control, refreshes, or reopens the detail. Enough comments, missing or ambiguous containers, non-scrollability, no growth, exhausted budget, or risk stop deterministically; non-risk shortfall remains partial, while risk stops before screenshot or retry. The current ten-record acceptance below live-tested this path with BrowserSkill off.

The installed V15 source hardening also binds Bilibili, Douyin, and Weibo creator responses to the requested UID, rejects ambiguous same-platform passive tabs, and limits the Bilibili BrowserSkill click replay to an explicit structured `stale-selector` result. These paths remain offline-tested but were not part of the Xiaohongshu-only live acceptance.

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

Current V15 offline evidence (2026-08-11): the focused sockets-disabled suite passed 605 tests and the final complete sockets-disabled suite passed 871 tests, with zero failures and zero skips. The added regression proves evidence freshness uses the unique private run directory's filesystem timestamp rather than comparing filesystem metadata against a potentially leading process wall clock. The one warning is the expected `pytest-socket` warning from the test that proves AF_INET and AF_INET6 remain blocked while Unix sockets are allowed. Runtime compilation, all five `--help` entrypoints, the active residual scan, installer version output, both skill validators, and `git diff --check` also passed. This remains offline evidence and is not live-platform acceptance; installed-state evidence is recorded separately below.

Unreleased V15 source-hardening evidence (2026-08-12): the complete sockets-disabled suite passed 886 tests with zero failures and the same expected socket-block warning. All 59 Python sources compiled in memory, all five runtime entrypoint help checks passed, the active residual scan returned zero findings, `git diff --check` passed, and the installed runtime's non-live preflight remained healthy. No platform collection, BrowserSkill session, install, commit, tag, or push was performed; the installed runtime therefore still represents the prior V15 cutover, not this worktree diff.

Unreleased Xiaohongshu bounded-detail evidence (2026-08-13): the complete sockets-disabled suite passed 913 tests with zero failures and one expected `pytest-socket` warning. All 61 Python sources compiled in memory, all five actual runtime entrypoint help checks passed, the active residual scan returned zero findings, both skill packages passed their validators, the installer reported `15.0.0`, `git diff --check` passed, and the installed runtime's non-live preflight returned `status: ok`. No real-platform collection, BrowserSkill session, installation, staging, commit, tag, push, or publication was performed. Installed V15 still predates this source hardening, so these results prove offline source behavior only.

Current Xiaohongshu CDP-only evidence (2026-08-13): after removing BrowserSkill from Xiaohongshu and adding the standalone screenshot-validation argument, the complete sockets-disabled suite passed 937 tests with zero failures and one expected `pytest-socket` warning. All 61 Python sources compiled in memory, all five entrypoint help checks passed, both skill validators passed, the active residual scan returned zero findings, and `git diff --check` passed. The source was atomically installed in Codex-only mode as release `20260812T180654757182Z-98de1d3b`; current runtime and skill trees match source apart from deployment metadata, product `VERSION`, and ignored bytecode directories.

Current Xiaohongshu evidence-hardening result (2026-08-13): the outer validator now independently requires exact note/link identity, `detail_completed`, empty `missing_fields`, a detail-proven non-estimated date, non-negative integer engagement values, current per-metric source and observation time, and request-bound safe comment arrays. Screenshot fallback performs a fresh risk check before any full-page capture, and creator pagination may cross a duplicate or pinned page only while `has_more` is true and its cursor advances. Standalone validation now accepts `--xhs-comments N` so it can recheck the same comment contract without navigation. The locked-dependency sockets-disabled suite passed 960 tests with zero failures and zero skips; the sole warning is the intentional socket-block proof. All 61 Python files compiled in memory, all five entrypoint help checks passed, both skill validators passed, the active residual scan returned zero findings, and `git diff --check` passed. The exact earlier ten-article run was revalidated offline by both source and installed validators with `--xhs-comments 10`: 10/10 records remained successful at 61 fields each. No new platform collection or BrowserSkill session was started. The atomic Codex-only cutover installed release `20260812T185538143228Z-15d15f3c`; current runtime, venv, and Codex skill release markers match, source/runtime and source/skill trees are byte-equivalent apart from deployment metadata, installed offline preflight is `status: ok`, BrowserSkill remains at zero sessions, and exact recovery paths were retained. A DOM fallback selector for Xiaohongshu shares remains intentionally deferred until a fixed current-page fixture can prove it does not read an unrelated number.

Media@Missher V15.2 (`15.2.0`) promoted that verified evidence-hardening baseline to its dated product release. It changed no platform-avoidance policy and added no concurrency, retry, proxy, fingerprint, CAPTCHA, or stealth behavior. Xiaohongshu remained single-owner CDP-only; BrowserSkill remained optional and Bilibili-only. Historical V15.0 deployment IDs, tests, tags, and acceptance records remain dated evidence rather than being relabeled as V15.2.

V15.2 cutover completed on 2026-08-13 as Codex-only release `20260813T013103441243Z-308e4694`. The locked-dependency offline suite passed `960 passed` with zero failures and one intentional socket-block warning; 61 Python files compiled, five entrypoint help checks passed, both source skills validated, the residual scan returned zero findings, and `git diff --check` passed. Post-install live preflight was `status: ok` against the existing CDP browser; source and installed versions both reported `15.2.0`, all three release-marker hashes matched, and the installed Codex skill validated with heading `Media@Missher V15.2`. The immediately prior runtime, venv, and Codex skill were preserved at the installer-reported `previous-20260813T013103441243Z-308e4694`, `venv.previous-20260813T013103441243Z-308e4694`, and `recovery/codex/media-missher.previous-20260813T013103441243Z-308e4694` paths; the prior runtime still reports `15.0.0`. The installed V15.2 validator reaccepted the exact earlier ten-article XHS run as `10/10 success`, with 61 fields per record and the original request-bound ten-comment and opened-screenshot contract. This cutover performed no new platform collection, started no BrowserSkill session, and made no Git stage, commit, tag, push, GitHub release, or Feishu write.

V15.2.1 Bilibili CDP dynamic-completion source evidence (2026-08-13): strict complete mode opens one exact non-video dynamic through the existing Playwright/CDP `DetailOpenCoordinator` when a list engagement value is unknown, even with BrowserSkill off. The bridge-free path performs one click without replay; explicitly requested BrowserSkill retains only its existing structured stale-selector compatibility replay. Detail DOM values fill only `null` metrics, exact list API values remain unchanged, and an exact same-page or popup main-document HTTP `403`/`429` stops before DOM merge or screenshot. A metric that remains unavailable stays `null` and produces runtime `incomplete-record` plus outer `partial`. Two regression tests also require the target-wait and feed-risk browser expressions to contain valid single CSS-selector literals; both emitted expressions passed an independent Node JavaScript parse. The final sockets-disabled suite passed 971 tests with zero failures and zero skips, with only the intentional socket-block warning; 61 Python files compiled in memory, all five entrypoint help checks passed, both skill packages validated, the active residual scan returned zero findings, and `git diff --check` passed.

V15.2.1 Bilibili live disposition (2026-08-13): source and installed candidate preflight were healthy against the existing single CDP Chrome, with BrowserSkill and screenshots off. Bounded acceptance and diagnostic runs exposed and removed two invalid JavaScript string splits without recording content or identifiers. The final ten-record candidate run then stopped with the safe `precondition-failed` diagnostic before accepting any record because the free-form dynamic did not expose one unique actionable DOM target satisfying the native-ID binding. It reported no risk status, timeout, BrowserSkill session, second browser, screenshot, or Feishu write. After three bounded fix cycles, no fourth selector patch was attempted: relaxing the exact target rule could click the wrong dynamic. V15.2.1 therefore remains a source-only Draft candidate and was not tagged, released, or merged.

The machine was atomically restored from Git commit `7040fc0` to stable V15.2.0 deployment `20260813T095717838068Z-516ae522`; runtime, venv, and installed Codex skill release markers match and live preflight is `status: ok`. The stable validator rechecked the earlier same-target ten-record Bilibili run: all 10 records remain readable, 9 video records are complete, and the single free-form image dynamic remains explicitly incomplete only for `collected`. This rollback preserved every V15.2.1 deployment backup and all private run evidence.

V15.2.1 ordinary Bilibili/Douyin repair evidence (2026-08-23): the installed V15.2.0 regression was isolated to creator-source capture before record parsing, while the private profile remained unchanged and Weibo still collected normally. Bilibili and Douyin now classify initial Playwright response timeouts as `creator-capture-timeout`, preserve exact query binding, accept an unbound official response only after exact payload-author identity proof, and keep conflicting identity evidence fail-closed. Safe failure-only observations retain only fixed enums and sanitized official API host/path values without query strings. Current Douyin author pages can omit the legacy post endpoint during the bounded wait, so ordinary creator collection has a fallback that performs one read-only parse of the exact navigated `/user/<id>` page: it requires one unique visible main list, accepts only exact `/video/<aweme_id>` links, performs no click or scroll, and leaves unproven date and engagement values as `null`. The final installed sequential live acceptance collected and independently revalidated 10 of 10 Bilibili records and 10 of 10 Douyin records in 13.361 seconds from `~/.local/share/media-missher/state/runs/run-20260822T182251Z-qrq45ex8`; both platform diagnostics were `ok`, the runtime manifest was `complete`, native IDs were unique, every Douyin record retained non-null title, cover, date, liked, comments, shares, collected, and plays values, and BrowserSkill, screenshots, Feishu, retries, risk signals, timeouts, stdout, and stderr were absent. The sockets-disabled suite passed 988 tests with one intentional socket-block warning; 61 Python sources compiled in memory, all five entrypoint help checks passed, both source skills validated, the active residual scan returned zero findings, and `git diff --check` passed. The final ordinary-collection code was installed atomically in Codex-only mode as release `20260822T182159135628Z-9d1ca35e`; its immediately prior runtime, venv, and Codex skill remain at the installer-reported exact recovery paths.

Historical V12 evidence: the V12 source baseline passed 664 tests with Playwright installed, zero failures, and zero skips. The full suite ran with sockets disabled. All five runtime entrypoints accepted `--help`, the active residual scanner returned zero for the three source package roots, and the official skill validator accepted both packages. These dated results remain historical evidence and are not V15 proof.

## Live acceptance

V15 Xiaohongshu live acceptance passed on 2026-08-13. The exact current run `~/.local/share/media-missher/state/runs/run-20260812T180149Z-khe6zvnn` collected and independently revalidated 10 of 10 detailed articles in 133.343 seconds with `--browser-assist off`, `--screenshot-mode opened`, and a bounded request of at most 10 comments per article. All ten records were complete and fresh, each had 61 fields with current-detail body, author, media, date, liked, comments, collected, and shares, and all ten private article screenshots passed SHA-256 verification. The run retained 13 comments in total according to each article's current available count, produced no risk, timeout, error, symlink, Feishu artifact, or stderr content, and left both Media locks available and BrowserSkill at zero sessions.

Two earlier ten-record BrowserSkill-assisted attempts produced zero accepted records and failed with the bounded safe diagnostics `bsk-transport` and `bsk-tab-borrow`. They are diagnostic failures, not content evidence. Their failure established the single-owner design now enforced in code: Xiaohongshu rejects BrowserSkill before navigation and performs detail opening, response capture, comments, and screenshots through the existing CDP session only.

The following evidence is retained as historical V12 behavior and must not be substituted for the current V15 acceptance above.

Live acceptance is a separate authorized stage. The latest sequential count-`1` run at `~/.local/share/media-missher/state/runs/run-20260803T183331Z-yio893cc` produced one current record for every platform in 51.704 seconds with no timeout, risk signal, or Feishu artifact. Bilibili complete mode passed with 35 fields. Douyin and Weibo passed with 24 and 22 fields. Xiaohongshu matched the expected note, consumed a fresh official detail response, and produced 53 fields including body, author, publish time, location, media, tags, and the other engagement values, but remained incomplete only because `collected` was unknown.

The old active implementation distinguishes a missing or `null` detail API count from an explicitly present empty string: missing/`null` remains unknown, while present-empty means zero. The independent runtime had collapsed both cases to unknown. It now restores that narrow detail-API-only distinction without changing list, search, DOM, or global count parsing. Missing values, `null`, and placeholders remain incomplete; no stale preview value is promoted to fresh detail evidence.

The explicitly authorized post-compatibility Xiaohongshu run at `~/.local/share/media-missher/state/runs/run-20260804T011422Z-waihwmir` opened one exact note, captured a current target-bound detail API response, and produced one complete 50-field record with a non-null numeric `collected` value. It finished in 43.997 seconds with no timeout, risk signal, or Feishu artifact.

The later 5–15 second Xiaohongshu open-note settle changes timing only; it does not change target selection, response binding, detail parsing, schema, or other platforms. Its focused tests cover minimum/maximum timing, exactly once per note, ordinary/search exclusion, immediate HTTP risk stop, post-settle challenge stop, modal cleanup, and existing collection fallbacks. The current ten-record acceptance confirms this installed detail path under real sequential use.

Before any future live acceptance, run live preflight against the existing browser. This probes the CDP endpoint but does not prove platform page or login state. The runtime controller checks selected pages and visible login state before creating output. With explicit navigation authorization, it prepares temporary pages and closes only those pages after the run.

Open a temporary page only with explicit navigation authorization. Close only the temporary page after validation. Do not retry a risk stop.

## V15 Cutover

The current local Codex-only atomic cutover completed on 2026-08-13 from the approved working tree with release `20260812T180654757182Z-98de1d3b`. The installer synchronized `current/`, `venv/`, and `~/.codex/skills/media-missher`, left `~/.openclaw` absent, and preserved the immediately prior components at `previous-20260812T180654757182Z-98de1d3b`, `venv.previous-20260812T180654757182Z-98de1d3b`, and `recovery/codex/media-missher.previous-20260812T180654757182Z-98de1d3b`. Post-cutover live preflight passed against Chrome CDP, release markers matched, the standalone validator reaccepted the exact ten-record screenshot run, BrowserSkill remained at zero sessions, and both locks were available.

The initial local V15 Codex-only cutover completed on 2026-08-11 from source commit `8cb93fb` with release `20260811T101916230401Z-56f9de1d`. Its historical recovery paths remain recorded in the installation evidence from that date.

Post-cutover verification proved version `15.0.0`, matching release markers, byte-equivalent runtime and Codex skill source trees apart from deployment metadata, mode-`0700` runtime/state directories, mode-`0600` release markers, all five installed entrypoints, installed runtime and Playwright imports, the installed Codex skill validator, and both offline and existing-CDP live preflight. The optional BrowserSkill bridge passed its installed read-only preflight against CLI 0.1.10 and extension 0.1.6 with one browser and zero sessions before and after the check. This verification started no BrowserSkill session and performed no platform collection.

The private GitHub repository `Missher12/media-missher` is marked for Missher use. Its default `main` branch preserves the complete independently authored source history, and safe local development branches plus the `v12.0.0` and `v15.0.0` tags are mirrored remotely. Historical V7.1/V8 raw bundles are represented only by a hash-and-provenance index because they contain private identifiers, obsolete integration paths, and third-party source without a packaged compatible license. Runtime data, browser material, and installed recovery trees are not source releases and are never uploaded.

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

- V15 Xiaohongshu creator detail is installed and live-accepted for the exact ten-record run above; Bilibili, Douyin, Weibo, and keyword-search DOM paths were not part of that acceptance
- BrowserSkill remains available only for Bilibili creator details and has offline coverage, but its Bilibili live path was not exercised by the Xiaohongshu acceptance
- Xiaohongshu complete batches add 5–15 seconds per successfully opened note; increase `--platform-timeout` for larger counts rather than reducing or removing the dwell
- Platform response schemas, login markers, and challenge behavior can change without notice
- Creator collection needs a non-empty UID for every selected platform; search does not
- Navigation is disabled unless the current run has explicit authorization
- A failed non-risk prerequisite permits one retry only after correction and fresh preflight
- The repository has no selected repository-wide public-distribution license; local installation is complete, but a combined public bundle is not authorized
