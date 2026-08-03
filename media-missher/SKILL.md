---
name: media-missher
description: Operate and validate the shared Media@Missher runtime for Bilibili, Xiaohongshu, Douyin, and Weibo. Use for authorized creator collection, single-platform keyword search, complete Bilibili or Xiaohongshu evidence, fresh-run validation, and diagnosis of CDP, login, timeout, lock, cooldown, or risk failures. Keep review and planning read-only, and never perform a remote Feishu write.
---

# Media@Missher

Operate the installed shared runtime through this skill's standard-library adapter. The runtime home comes from `MEDIA_MISSHER_HOME` and defaults to `~/.local/share/media-missher`.

## Route each request

- Keep code review, audit, explanation, and planning read-only. Do not collect data for those requests.
- Require explicit authorization to collect, plus a count and a selected platform, creator UID, homepage, or keyword.
- Use a supplied target before a private profile value. Ask when a target is ambiguous. Never guess an ID.
- Treat count `0` as valid only with an explicit collect-as-much-as-safe request. The runtime page cap still applies.
- Limit keyword search to one platform. Reject search combined with complete mode.
- Run selected platforms sequentially in one controller process. Never overlap Xiaohongshu with another collection.
- Run complete mode once when requested. Do not collect an ordinary pass first.
- Pass `--allow-navigation` only after explicit authorization for browser navigation during that collection or live acceptance run. It uses temporary pages in the existing browser context and closes only those temporary pages after the run. Never use it for a read-only request.

Read [commands](references/commands.md) before collection or installation. Read [configuration](references/configuration.md) when resolving the shared home, output root, Chrome DevTools Protocol (CDP) endpoint, private profile, or creator UID. Read [validation](references/validation.md) before accepting evidence. Read [troubleshooting](references/troubleshooting.md) after a preflight, login, timeout, lock, cooldown, or risk failure. Read [licensing](references/licensing.md) before copying, distributing, or licensing a component.

## Collect safely

1. Resolve configuration with command-line values before environment values and the private mode-`0600` profile.
2. Run `scripts/preflight.py --live`. Live preflight probes the existing CDP endpoint and checks the shared layout, release markers, Python, dependencies, and five entrypoints. It does not select platforms.
3. Run `scripts/run_collection.py` once. The runtime controller checks each selected platform page and login state before creating output. A successful run creates one unique mode-`0700` directory and private mode-`0600` JSON artifacts.
4. Stop immediately on `403`, `429`, `461`, `471`, `999`, `risk`, `locked`, `blocked`, or cooldown signals. Do not retry a risk stop.
5. Validate only artifacts from the current run and its recorded start time. Reject `latest`, reused directories, old artifacts, symlinks, exit codes, and console checkmarks as proof.
6. Report counts, statuses, and absolute evidence paths. Limit samples to three metadata-only objects with platform and field count.

## Preserve safety controls

- Do not start, restart, terminate, or reprofile Chrome. Do not close or repurpose the user's existing pages.
- Do not replace cookies, clear locks, clear state, rotate accounts, rotate network exits, or increase concurrency.
- Do not bypass a captcha, inject stealth behavior, use proxy rotation, defeat fingerprinting controls, or evade platform restrictions.
- Preserve rate limits, jitter, page caps, timeouts, cooldowns, and sequential execution.
- Retry one non-risk failure only after correcting its concrete cause and passing preflight again.

## Keep Feishu separate

The runtime and adapter never read Feishu credentials, create Feishu artifacts, invoke a Feishu client, or perform a remote Feishu write. Always pass `--no-feishu`; local JSON validation is not a remote write. Any Feishu operation is a separate workflow that needs separate explicit authorization.

## Report one status

Use one status:

- `success`: every requested count and completeness check passed
- `partial`: current evidence exists, but a count or completeness check failed
- `risk-stopped`: a risk, lock, block, or cooldown signal stopped the run
- `preflight-failed`: runtime, browser, login, page, or configuration checks failed before output creation
- `failed`: the run produced no acceptable current evidence
