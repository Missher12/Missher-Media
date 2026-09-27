# Troubleshoot Media@Missher

Start with the structured preflight or collection status. Preserve private evidence while you correct one concrete cause.

## Shared runtime is missing or incomplete

Run `scripts/preflight.py --json`. Check `MEDIA_MISSHER_HOME`, which defaults to `~/.local/share/media-missher`.

Preflight requires `current/`, `venv/`, mode-`0700` writable `state/`, ownership and matching release markers, Python 3.11 or 3.12, Playwright, runtime imports, and all five entrypoint help checks. It rejects symlinked path components and an unavailable shared install lock. The installer can run under the system Python and selects an available compatible runtime interpreter; if neither supported version exists, install one before retrying.

On the current Codex-only machine, run `python3 tools/install_media_missher.py --codex-only` from the source repository only when installation is authorized. This does not create or require an OpenClaw root. Use `--runtime-only` only for an explicitly adapter-only installation; the two flags are mutually exclusive. Do not create a dependency environment inside an installed skill.

## CDP endpoint is unavailable

This applies to the `cdp` backend only. Run `scripts/preflight.py --live --json` with the configured Chrome DevTools Protocol (CDP) URL. This proves endpoint reachability, not platform page availability or login state. Confirm that the existing debugging session remains open. Do not start, restart, terminate, or reprofile Chrome automatically, and do not switch backends to work around a CDP failure.

## A platform is logged out

Ask for manual login in the existing browser. Do not capture credentials, import cookies, bypass a captcha, switch accounts, or alter browser storage.

## A matching page is unavailable

The runtime controller checks each selected platform page and visible login state before output creation. Passive mode requires an already open matching page. If navigation is needed, request explicit authorization for that collection or live acceptance run, then pass `--allow-navigation` to the collection command. Authorized mode opens temporary pages inside the existing browser context, restricts them to exact platform hosts, and closes only those temporary pages after the run. It does not repurpose or close an existing user page.

When Chrome exposes multiple browser contexts, the controller uses the unique context that already contains a matching platform page. If no unique context can be proven, it fails closed instead of guessing an account environment. Entry navigation must return a successful response; `403`, `429`, or a visible challenge is a non-retryable risk stop even when it occurs before output creation.

Never add `--allow-navigation` to a read-only review. Do not automatically retry collection. For a user-requested non-risk retry, first correct the page or authorization prerequisite and pass live preflight, then make one bounded attempt.

## A browser backend fails closed

Chrome CDP is the only backend. Report its actual failure without switching browser or account.

- `browser-assist-replaced` rejects the retired assist bridge. Keep `--browser-assist off`.
- `backend-retired-browserskill` rejects a new BrowserSkill request or saved preference; it does not invalidate historical read/export. Do not invoke, install or diagnose `bsk` for collection.
- `backend-retired-computer-use` rejects a retired request or preference. Choose Chrome CDP explicitly for a new collection; old results remain readable/exportable. `media-missher capabilities` lists only CDP and does not probe the browser.
- Historical `bsk-*` diagnostics describe old runs only. Never replay those actions.
- Report unsupported CDP platform/mode combinations. Do not invent hidden fields or completeness.
- Risk, challenge and cooldown results never permit retry or backend switching. Shared platform risk survives cancellation and lease expiry.

## A budget pause or deadline stops collection

`budget-exhausted` means the finite per-platform batch budget was used up inside an authorized `best_effort` run. It is a pause with a verified prefix, not a claim that everything was collected. `run-deadline` means the authorized window expired. Keep the checkpoint and report the real stop reason; do not describe either as a completed run, and do not restart the run automatically. The Xiaohongshu 10-notes / 3-pages / 600-seconds policy and a latched risk pause still apply.

## A Weibo topic task is refused or incomplete

`topic-container-unsupported` means the input is a 超话 (super topic). That is a different page contract and is never faked as a keyword search. `topic-input-invalid`, `topic-kind-mismatch`, `target-topic-missing`, and `topic-unsupported-platform` mean the topic input, its kind, or its platform did not match the Weibo topic contract.

A participant is only the outer author of an observed topic post. A homepage that is unavailable, deleted, permission-limited, or login-walled records one fixed reason (`profile-unavailable`, `profile-deleted`, `profile-permission-denied`, `profile-login-required`) and keeps the confirmed user entry with its source relations. Do not fill the missing profile fields from another page, and do not claim all participants.

## Collection times out

Keep the unique private run directory and mode-`0600` logs. Inspect redacted stderr, the manifest, platform status, and the stop reason. Fix the concrete non-risk cause before a user-requested bounded retry. Do not increase concurrency or overlap runs.

## Install lock is busy

Another installer may be rotating the shared release. Wait for that bounded operation to finish, then rerun preflight. Do not delete or replace `.media-missher-install.lock`.

## Collection lock is busy

Another collection owns the dedicated browser profile and the shared collection lease. Let that run finish and validate before starting another. Do not delete, replace, or unlock `.media-missher-collection.lock`, and do not bypass the adapter with a direct runtime entrypoint.

## Runtime reports a lock or cooldown

Return `risk-stopped`. Do not delete locks, checkpoints, cache, reports, or risk state. Wait for the platform cooldown or ask for a later decision.

## Runtime reports a risk response

Treat `403`, `429`, `461`, `471`, `999`, `risk`, `locked`, and `blocked` as stop signals. Do not rotate accounts or network exits, add retries, use proxy rotation, or evade platform controls.

## An export is refused

Export only reads already-saved verified local results. A requested field that was never collected is reported as a missing field instead of being collected now, and an existing output file is refused unless `--overwrite` is passed explicitly. Choose the record kinds (`posts`, `topic_participants`, `user_profiles`) explicitly; an empty or unsupported selection is an error, not an empty file. Export never fixes a missing field by navigating or collecting again.

## Validation reports partial output

Report the exact validated count and failed completeness checks. Keep unknown dates and engagement values as `null`; never fill them with zero.

For a short Xiaohongshu comment slice, inspect the recorded completeness failure rather than adding browser actions. Do not refresh or reopen the detail, click a “more” control, scroll the whole page, or repeat the exact target click. The runtime has already stopped at its comment-container action budget; retain the partial record unless a future separately authorized run is appropriate.

## A release upgrade fails

The installer attempts automatic rollback. If manual recovery is required, use the exact `previous-{release_timestamp}` paths reported by installation. Move a failed current component to a unique Trash path before restoring the matching previous component.

Validate ownership, release markers, install locks, and path boundaries before every move. Use `/bin/mv` with exact arguments. Never use wildcards or recursive deletion.

## Post-cutover preflight fails

Use the private handoff evidence to find the exact Trash recovery path. Restore only that recorded component, rerun both skill preflights, test all five entrypoints, and run the residual scanner.

Do not remove private run evidence during rollback. Recovery never authorizes a remote Feishu write.
