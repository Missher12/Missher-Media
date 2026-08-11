# Troubleshoot Media@Missher

Start with the structured preflight or collection status. Preserve private evidence while you correct one concrete cause.

## Shared runtime is missing or incomplete

Run `scripts/preflight.py --json`. Check `MEDIA_MISSHER_HOME`, which defaults to `~/.local/share/media-missher`.

Preflight requires `current/`, `venv/`, mode-`0700` writable `state/`, ownership and matching release markers, Python 3.11 or newer, Playwright, runtime imports, and all five entrypoint help checks. It rejects symlinked path components and an unavailable shared install lock.

On the current Codex-only machine, run `python3 tools/install_media_missher.py --codex-only` from the source repository only when installation is authorized. This does not create or require an OpenClaw root. Use `--runtime-only` only for an explicitly adapter-only installation; the two flags are mutually exclusive. Do not create a dependency environment inside an installed skill.

## CDP endpoint is unavailable

Run `scripts/preflight.py --live --json` with the configured Chrome DevTools Protocol (CDP) URL. This proves endpoint reachability, not platform page availability or login state. Confirm that the existing debugging session remains open. Do not start, restart, terminate, or reprofile Chrome automatically.

## A platform is logged out

Ask for manual login in the existing browser. Do not capture credentials, import cookies, bypass a captcha, switch accounts, or alter browser storage.

## A matching page is unavailable

The runtime controller checks each selected platform page and visible login state before output creation. Passive mode requires an already open matching page. If navigation is needed, request explicit authorization for that collection or live acceptance run, then pass `--allow-navigation` to the collection command. Authorized mode opens temporary pages inside the existing browser context, restricts them to exact platform hosts, and closes only those temporary pages after the run. It does not repurpose or close an existing user page.

When Chrome exposes multiple browser contexts, the controller uses the unique context that already contains a matching platform page. If no unique context can be proven, it fails closed instead of guessing an account environment. Entry navigation must return a successful response; `403`, `429`, or a visible challenge is a non-retryable risk stop even when it occurs before output creation.

Never add `--allow-navigation` to a read-only review. Retry one non-risk page failure only after the page or authorization prerequisite is corrected and live preflight passes.

## BrowserSkill assistance fails closed

BrowserSkill is optional and is used only when `--browser-assist browserskill` is explicitly requested. The safe preflight codes are `bsk-missing`, `bsk-unhealthy`, `bsk-incompatible`, `bsk-busy`, `bsk-transport`, `bsk-timeout`, and `bsk-target-ambiguous`. They return `preflight-failed` before a runtime run directory is created; raw BrowserSkill stdout and stderr are never copied into the manifest or adapter summary.

Use only read-only diagnosis first: `bsk status --json` and `bsk session list --json`. After correcting one concrete non-risk cause, `bsk doctor` may be run once as a read-only diagnostic before one retry. Do not start a BrowserSkill session manually, inspect cookies or browser storage, or retry any risk/challenge/cooldown result.

BrowserSkill 0.1.10 performs an upstream bundled skill sync whenever an explicitly assisted collection actually runs `bsk session start`. This is upstream behavior, not a Media@Missher preflight action: Media preflight never starts a session and never downloads or upgrades the BrowserSkill binary or extension.

## Collection times out

Keep the unique private run directory and mode-`0600` logs. Inspect redacted stderr, the manifest, and platform status. Fix one non-risk cause before one retry. Do not increase concurrency or overlap runs.

## Install lock is busy

Another installer may be rotating the shared release. Wait for that bounded operation to finish, then rerun preflight. Do not delete or replace `.media-missher-install.lock`.

## Runtime reports a lock or cooldown

Return `risk-stopped`. Do not delete locks, checkpoints, cache, reports, or risk state. Wait for the platform cooldown or ask for a later decision.

## Runtime reports a risk response

Treat `403`, `429`, `461`, `471`, `999`, `risk`, `locked`, and `blocked` as stop signals. Do not rotate accounts or network exits, add retries, use proxy rotation, or evade platform controls.

## Validation reports partial output

Report the exact validated count and failed completeness checks. Keep unknown dates and engagement values as `null`; never fill them with zero.

## A release upgrade fails

The installer attempts automatic rollback. If manual recovery is required, use the exact `previous-{release_timestamp}` paths reported by installation. Move a failed current component to a unique Trash path before restoring the matching previous component.

Validate ownership, release markers, install locks, and path boundaries before every move. Use `/bin/mv` with exact arguments. Never use wildcards or recursive deletion.

## Post-cutover preflight fails

Use the private handoff evidence to find the exact Trash recovery path. Restore only that recorded component, rerun both skill preflights, test all five entrypoints, and run the residual scanner.

Do not remove private run evidence during rollback. Recovery never authorizes a remote Feishu write.
