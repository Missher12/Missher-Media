---
name: media-missher
description: Use the Media@Missher CLI for authorized media collection, saved-run export, setup, and diagnostics from an Agent with a local shell.
---

# Media@Missher

Use the installed CLI from any Agent with a local shell. It shares the existing Media@Missher collector and safeguards with the separate Harness Bundle. It does not require Harness, Cordis or this maintenance conversation. The software remains Missher's proprietary software; installing this Skill does not grant redistribution rights.

Follow the user's current request and already-granted scope. Continue authorized steps without repeating approval questions; ask only for missing target, navigation or export choices that affect the result. A review or plan alone never authorizes collection or installation. Preserve the host's selected model and reasoning settings; model choice does not establish CLI installation, Skill activation or Chrome readiness.

## Discover the installed entry

Run `media-missher --version` and `media-missher --help`. If PATH does not resolve that command, the installer records this absolute Node + CLI fallback:

```sh
{{MEDIA_MISSHER_COMMAND}} --version
{{MEDIA_MISSHER_COMMAND}} --help
{{MEDIA_MISSHER_COMMAND}} doctor
```

Use that same command prefix for the examples below if PATH is unavailable. Agent package version 17.0.0 and required collection runtime 17.0.0 identify different components. `doctor` reports the installed runtime version and selected platforms without creating files, installing Python, checking CDP, opening Chrome or collecting. Python 3.11/3.12 is needed when provisioning the collection runtime; a reported executable has not been executed by doctor.

All command results are JSON on stdout; collection phase/count/timing events use the fixed `media-missher-progress` prefix on stderr. A successful process exit is 0; partial/failure is 1, invalid arguments 2, needs-setup/preflight 3, risk stop 4, SIGINT 130 and SIGTERM 143. Preserve nonzero results and their current counts. Send cancellation to the CLI and await cleanup; do not kill the browser or retry the interrupted action automatically.

Default private paths are `~/.config/media-missher/profile.json`, runtime `~/.local/share/media-missher`, and output `~/.local/share/media-missher-agent/runs`. `--profile`, `--runtime-home` and `--output-root` accept absolute paths on doctor/setup/collect/runs. Existing `MEDIA_MISSHER_PROFILE_CONFIG` and `MEDIA_MISSHER_HOME` are supported; explicit flags win. Keep the same paths for subsequent commands. Do not change HOME to avoid a collection lock, preflight failure or risk pause.

macOS and Linux use the same CLI; Linux requires a non-root user. On Windows, use the delivered `install.ps1` entry, which checks WSL2, and a WSLg graphical session. Keep HOME beneath `/home/<user>` and the profile, runtime, output and skill destination inside that HOME on native Linux storage. Windows mounts, bind aliases and symlink traversal are unsupported. The Agent shell, CLI, runtime, browser and private files must all use that same Linux environment and HOME. Native Windows execution is unsupported. There is no remote CDP exposure across the Windows boundary.

## Platforms, targets and accounts

The five platforms are `bilibili`, `xhs`, `douyin`, `weibo` and `x`. One plan may contain one or more platforms, and each platform may contain several accounts; the older "one account per platform" and four-row limits no longer exist (up to 200 rows and 200 explicit targets).

A target is written as `PLATFORM:MODE:VALUE` and `--target` may be repeated:

```sh
--target bilibili:creator:12345          # native UID
--target weibo:creator:@somebody          # handle, @ optional
--target x:creator:https://x.com/somebody # verified official homepage
--target x:search:ai                      # keyword, sort latest (default)
--target x:search:top:ai                  # keyword, sort top
--target weibo:topic:旅行                 # plain #话题#
--target weibo:topic:super:旅行超话       # 超话, an explicit different page type
```

Each target carries its own task mode (`creator`, `search`, `topic`), so one plan can mix a creator task on one platform with a search or Weibo topic task on another. The CLI splits the plan into deterministic sub-tasks and the runtime runs them sequentially, so every result stays traceable to its target. `--topic NAME_OR_URL` is shorthand for a Weibo topic target.

A display name is only a label for the user to choose from. It is never an identity, and a nickname is never resolved into a UID, handle or homepage by guessing. Ask for the native identifier or the official homepage when they are missing.

Selecting a creator target is not the same as switching the logged-in account. This tool never switches accounts automatically, never logs in for the user and never borrows another account. An account that is not logged in is a stopping result with a reason, not a target to work around.

## Prepare and select targets offline

For a new device or when `needs-setup` is returned:

```sh
media-missher setup status
media-missher setup template
media-missher setup import --file /absolute/creators.xlsx
```

Give the user the returned Excel or CSV template. Its columns are `platform`, `creator_name`, `homepage_url` (or the generated Chinese equivalents). Use full official creator homepages or native identifiers from the user, not keyword search or a guessed name-to-account mapping. Accept `.xlsx` or `.csv`; do not add formulas, embedded objects or credentials.

Read the returned private preview at `artifactPath`, show its row numbers and the selected creators, and use the exact `importId` with the user's intended rows. If that selection was already clear in the current request, proceed with it; otherwise obtain the missing selection. Several chosen rows may belong to the same platform, and `--target` may add explicit targets beside the roster:

```sh
media-missher setup activate --import-id IMPORT_ID_FROM_PREVIEW --rows 1,3,5,7
media-missher setup activate --import-id IMPORT_ID_FROM_PREVIEW --rows 2 --target weibo:topic:旅行
media-missher setup status
```

Import only creates a preview. Activation saves the reviewed selection and backs up an existing profile. At least one of `--rows`/`--target` is required. Template, import and activation neither prepare Python nor open a browser nor authorize collection. Never dump the profile, Cookies, tokens or environment into conversation or artifacts.

## Browser opening and login

When the user requests opening the dedicated AI collection browser, run:

```sh
media-missher setup browser-open --confirm-open
```

The command uses a separate local Chrome profile and a local login guide. Ask the user to log in manually on the required platform pages. Do not automate passwords, verification or CAPTCHA. Opening Chrome is a separate action from authorizing collection.

For an explicit local connectivity check after selection, run `media-missher setup browser-check`. `ready` describes the connection and pages, not account login. Login remains `not-checked` until the user confirms it or the authorized collector verifies an accessible selected target. A missing or busy browser is a stopping result: preserve existing windows and processes. Do not silently open a different browser, rotate an account, change proxy settings or switch CDP ports.

## Chrome CDP only

Chrome CDP is the only active backend. Omit `--backend` or use `--backend cdp`; it attaches through Playwright/CDP to the existing signed-in Chrome endpoint and works independently of the Agent host or DSH.

The backend stays `cdp` in the plan, manifest and export provenance. Explicit CLI values override the private plan, then the profile; omitted values preserve the plan, including explicit `0` and `off`. An old non-CDP preference or plan is refused before collection, never silently rewritten. There is no `auto` or alternate backend.

Computer Use and its lifecycle command are removed. Old requests return `backend-retired-computer-use`; BrowserSkill requests return `backend-retired-browserskill`. Historical runs remain readable and exportable with their original provenance, but cannot resume a retired backend. Never install or invoke an alternative browser controller to work around a failure.

## Collect an authorized batch

Resolve the user's selected platforms, targets, task modes, per-target count, comments and navigation scope before collection. A clear user request authorizes its stated collection; do not request the same permission again. On a first run with missing scope, obtain what is missing. Merely installing, importing a roster, activating this Skill or connecting Chrome is not collection authorization.

```sh
media-missher collect --platforms xhs --count 10 --allow-navigation
media-missher collect --target weibo:topic:旅行 --backend cdp --count-mode best_effort --run-deadline 1800
media-missher collect --target x:search:ai --target x:creator:https://x.com/somebody --backend cdp --count-mode best_effort
```

Omitting platforms and targets uses the active roster. Default count is 10 per platform and `--count` accepts 1–500. `--xhs-comments` is 0–100 per note and defaults to 0; use it only when XHS comments were requested. `--allow-navigation` authorizes exact-target navigation for this request and defaults to false when omitted. Do not invent targets or turn on navigation to repair an unauthorized attempt.

`--count-mode fixed` keeps the requested per-target count. `--count-mode best_effort` means "as much as allowed": it keeps paging and scrolling, de-duplicates, saves verified records and progress, and stays inside a bounded per-batch budget plus `--run-deadline` seconds, so it always has an exit condition. A budget pause, no new results, a timeout, a login or permission limit, a risk stop and a cancellation are different stop reasons. **A budget pause is not "collection finished"** — report the reason and the resume point instead of claiming the target was exhausted. Resume only when the user asks for that exact eligible run.

The shared runtime owns the browser and performs platform collection sequentially. On CAPTCHA, verification, blocking, HTTP risk responses, a cooldown or a persistent risk pause, stop immediately and report the partial evidence. **A risk stop never resumes automatically**: never retry, resume, reset a pause or delete safety/lock state, and never work around it by changing HOME, profile, runtime home, backend or account. A cooldown is not a schedule to retry automatically.

Xiaohongshu keeps 10 notes, 3 pages per batch and at least 600 seconds between batch starts. In `fixed` mode the CLI rejects an xhs count above 10; in `best_effort` mode the runtime batch policy enforces that ceiling instead of failing the request. Never present a policy limit as a collection that finished.

Return a clickable link or attachment for `workbookPath` when it exists. Report requested and actually collected counts per target/platform, success/failure/risk status, the stop reason, the run location and any saved phase timings. A missing metric stays unknown, not zero. A partial workbook is useful evidence but is not a successful exact-count collection. Never claim a real platform passed based on offline doctor or synthetic tests. The collection path is read-only against the platforms, and the runtime always runs with `--no-feishu`: remote writes and notifications are disabled, so nothing is posted to Feishu or any other remote service.

## Weibo topic tasks

`--topic NAME_OR_URL` and `--target weibo:topic:...` select a plain `#话题#`. The explicit `super` kind identifies a 超话 request, which the current collector reports as unsupported. A keyword search must never be reported as 超话 collection, and a topic name must not be presented as a super topic. Report the supported mode precisely instead of substituting another page.

The task flow is: verify the topic, page through the visible topic posts, extract the outer posting users, de-duplicate by Weibo UID, visit those users' public homepages, extract the visible profile fields, save posts/users/topic relations, then let the user choose the export.

"Topic participants" means only the authors of the topic posts actually observed in this run, including observed reposters that really appear in the results. Quoted original authors, recommendation cards, viewers, likers and commenters are different scopes: never count them and never silently widen the task to comments. Results must state how many posts were observed and how many users were de-duplicated; never claim to have found "all participants of this topic".

For each user keep the UID, nickname, canonical homepage link, the topics/posts they came from and the first observation time. A nickname is never a unique key. Only public, actually visible homepage fields are read (nickname, bio, avatar, verification, follower/following/public post counts, region/site/registration date/public tags); a field the page does not show stays `null`, and abbreviated numbers keep their original text and precision state. One homepage is fetched once per run per user, and a cached relation must carry its observation time rather than pretending to be fresh.

This task never recurses into those users' full post history, followers or following, and never collects private messages, Cookies, tokens, passwords or data behind a permission wall. An inaccessible, deleted or permission-limited homepage is recorded with a fixed reason while the confirmed user entry and its source are preserved, and the homepage phase can resume from its checkpoint.

## Export after collection

Collection and export are decoupled. Collection saves the private run, manifest, verified records and checkpoints; that evidence is not an export choice. When the run finishes or stops partially, show a short summary with field coverage first, then ask which records, fields and format to export — unless the user already stated the export earlier in the same request.

```sh
media-missher runs export --run-id run-ID --record-kinds posts,topic_participants,user_profiles \
  --platforms weibo --topics 旅行 --fields tweet_id,author_id --field-groups engagement \
  --format xlsx --file-name topic-participants
```

`runs export` only reads already-saved private results. It never collects, navigates, opens a browser or fills a missing field, so the same run can be re-filtered and re-exported as often as needed. Formats are `xlsx` (default), `csv`, `json`, `jsonl` and `sqlite`. `--record-kinds` selects between posts, topic participants and user profiles; `--fields` and `--field-groups` select columns; `--file-name` must be a plain file name without a directory part, and an existing file is not replaced unless `--overwrite` is given. Records from a partial, risk-stopped or cancelled run can still be exported while their status, missing fields and observation time are preserved.

When the user asks for a field that was never collected, say clearly that it is missing from the saved run and offer the available fields; do not turn one export into a new collection and do not imply the field exists. Report the record count that was actually written, and never truncate silently: oversized sheets are split into more files or sheets or a more suitable format is offered.

## Progress and historical runs

```sh
media-missher runs progress
media-missher runs list
media-missher runs xhs-status
media-missher runs compare --before run-EARLIER --after run-LATER
```

Progress is a private last-observed phase/count/timing snapshot, not guaranteed process liveness. History and XHS status use an existing runtime and never install one. Historical exports are not new collections. Use exact IDs returned by the local run list. Compare values at their recorded observation times.

Only explicit user intent to continue a particular eligible run permits `collect --resume-run run-ID`, preserving its original platforms, targets, counts, backend and profile. Old accepted IDs remain historical; only newly observed rows count as this workbook's new collection. Risk-stopped runs cannot be continued, and a resume never switches backend automatically. The CLI exposes no risk-reset action.

## Skill discovery and ownership

`media-missher install-skill --list` lists supported Agent destinations without writing. Install into only the requested Agent with `--agent codex|claude|cursor|openclaw|hermes`, or its known absolute generic `--skill-root`. The installer refuses symlinks, unowned copies and edited files; it preserves an exact private backup before updating an owned copy. On conflict, report the concrete path and preserve the existing skill. Do not remove it or claim ownership to force installation.

Installation does not prove activation in an existing conversation. Use the Agent's normal Skill refresh/new-conversation mechanism and verify that this Skill is discoverable there; availability of a separate Harness tool is a different check. There is no assumed public download URL or automatic all-Agent installation.
