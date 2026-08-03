# Troubleshoot Media@Missher

Start with the structured preflight or collection status. Preserve private evidence while you correct one concrete cause.

## Shared runtime is missing or incomplete

Run `scripts/preflight.py --json`. Check `MEDIA_MISSHER_HOME`, which defaults to `~/.local/share/media-missher`.

Preflight requires `current/`, `venv/`, mode-`0700` writable `state/`, ownership and matching release markers, Python 3.11 or newer, Playwright, runtime imports, and all five entrypoint help checks. It rejects symlinked path components and an unavailable shared install lock.

Run `python3 tools/install_media_missher.py --runtime-only` from the source repository only when installation is authorized. Do not create a dependency environment inside an installed skill.

## CDP endpoint is unavailable

Run `scripts/preflight.py --live --json` with the configured Chrome DevTools Protocol (CDP) URL. This proves endpoint reachability, not platform page availability or login state. Confirm that the existing debugging session remains open. Do not start, restart, terminate, or reprofile Chrome automatically.

## A platform is logged out

Ask for manual login in the existing browser. Do not capture credentials, import cookies, bypass a captcha, switch accounts, or alter browser storage.

## A matching page is unavailable

The runtime controller checks each selected platform page and visible login state before output creation. Passive mode requires an already open matching page. If navigation is needed, request explicit authorization for that collection or live acceptance run, then pass `--allow-navigation` to the collection command. The runtime restricts navigation to exact platform hosts.

Never add `--allow-navigation` to a read-only review. Retry one non-risk page failure only after the page or authorization prerequisite is corrected and live preflight passes.

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
