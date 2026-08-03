---
name: media-missher
description: Operate and validate the locally installed Media@Missher collector for Bilibili, Xiaohongshu, Douyin, and Weibo. Use when a user asks to collect a specific number of posts, search a keyword, request complete Bilibili content or fresh Xiaohongshu engagement, validate a fresh run, or diagnose CDP, login, timeout, lock, or risk-cooldown failures. Keep code review read-only and require separate explicit authorization for any remote Feishu write.
---

# Media@Missher

Operate the external Media@Missher runtime through this skill's standard-library adapter. Do not copy, import, patch, replace, or delete the external engine.

## Route the request

- Keep code review, audit, explanation, and planning read-only. Do not collect data for those requests.
- Require explicit authorization to collect, plus a count and a target platform, creator, UID, homepage, or keyword.
- Prefer a user-supplied target over a private profile default. If a named target cannot be resolved uniquely, ask; never guess an ID.
- Treat count `0` as valid only when the user explicitly requests “collect as much as safe”; it remains bounded by the engine safety cap.
- Limit keyword search to exactly one platform. Reject search combined with complete mode.
- Run multi-platform collection sequentially in one controller process. Never overlap collection processes, especially Xiaohongshu.
- When complete mode is requested, run it once. Do not run an ordinary pass first.

Read [references/commands.md](references/commands.md) before collection. Read [references/configuration.md](references/configuration.md) when resolving an engine, data root, CDP endpoint, private profile, or UID. Read [references/validation.md](references/validation.md) before accepting evidence. Read [references/troubleshooting.md](references/troubleshooting.md) after a preflight, login, timeout, lock, cooldown, or risk failure. Read [references/licensing.md](references/licensing.md) before copying, distributing, or licensing any component.

## Collect safely

1. Resolve configuration with CLI values taking precedence over environment values and the private mode-`0600` profile.
2. Run `scripts/preflight.py`. For real collection, require live CDP preflight to pass without starting or restarting Chrome.
3. Run `scripts/run_collection.py` once. It creates a unique private run directory, forces JSON staging, and applies `--no-feishu` to the multi-platform engine.
4. Stop immediately on `403`, `429`, `461`, `471`, `999`, `risk`, `locked`, or cooldown signals. Accept no automatic retry after a risk stop.
5. Validate only files from the current run and its recorded start time. Never accept `latest`, a reused directory, an old artifact, a symlink, an exit code, or a console checkmark as sufficient evidence.
6. Report at most three metadata-only samples (platform and field count) plus absolute current-run evidence paths. Never echo collected content in a summary.

## Preserve platform controls

- Do not restart Chrome, replace cookies, change browser profiles, clear locks, clear risk state, clear checkpoints, rotate accounts, rotate network exits, or increase engine concurrency.
- Do not bypass a captcha, inject stealth behavior, perform proxy rotation, use a proxy pool, defeat fingerprinting controls, or evade platform restrictions.
- Preserve engine rate limits, jitter, page caps, low-resource mode, cooldowns, and sequential execution.
- A non-risk failure may be retried once only after its concrete cause is fixed and preflight passes again.

## Keep Feishu separate

This skill never reads Feishu credentials, invokes a Feishu client, or performs a remote write. Local JSON staging is not a remote write. A remote Feishu operation is a separate workflow requiring separate explicit authorization.

## Report one final status

Use exactly one of:

- `success`: all requested counts and required completeness checks passed;
- `partial`: current evidence exists but a count or completeness check failed;
- `risk-stopped`: a risk, lock, or cooldown signal stopped the child process;
- `preflight-failed`: the runtime or existing CDP session was unavailable before collection;
- `failed`: no acceptable current-run evidence was produced.
