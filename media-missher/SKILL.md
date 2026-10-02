---
name: media-missher
description: Collect, validate, and selectively export private media data with Media@Missher. Use for collection requests, saved-run operations, setup, or runtime diagnostics.
---

# Media@Missher V17.0.2

Operate the installed shared runtime through this skill's standard-library adapter. The runtime home comes from `MEDIA_MISSHER_HOME` and defaults to `~/.local/share/media-missher`.

## Route each request

- Keep code review, audit, explanation, and planning read-only when those are the only requested actions. They do not authorize collection or installation; an explicit request to implement a repair authorizes that repair within the existing operational boundaries.
- Follow the user's current request and the scope already granted in the conversation. Continue authorized work without asking for the same approval again; ask only for missing information that changes the target, navigation scope, or export.
- Use the host's selected model and reasoning settings. This Skill does not select a model; verify the actual entry and capabilities instead of inferring them from a model name.
- Require explicit authorization to collect, an explicit target, and a selected platform plus creator UID, homepage, keyword, or Weibo topic. Planning never grants collection authorization.
- Use a supplied target before a private profile value. Ask when a target is ambiguous. Never guess an ID, and never turn a display name into an identity.
- Limit keyword search to one platform. Reject search combined with complete mode.
- Run selected targets sequentially in one controller process under one browser owner. Never overlap two collections.
- Xiaohongshu creator collection is detail-first and complete by default. For Bilibili, run complete mode once when requested. Do not collect an ordinary pass first.
- Pass `--allow-navigation` only after explicit authorization for browser navigation during that collection or live acceptance run. It uses temporary pages in the existing browser context and closes only those temporary pages after the run. Never use it for a read-only request.

Read [commands](references/commands.md) before collection or installation. Read [configuration](references/configuration.md) when resolving the shared home, output root, backend, Chrome DevTools Protocol (CDP) endpoint, private profile, or creator target. Read [validation](references/validation.md) before accepting evidence. Read [troubleshooting](references/troubleshooting.md) after a preflight, backend, login, timeout, lock, cooldown, or risk failure. Read [licensing](references/licensing.md) before copying, distributing, or licensing a component.

## Chrome CDP only

Chrome CDP is the only active backend. Omit `--backend` or use `--backend cdp`; it attaches through Playwright/CDP to the existing signed-in Chrome endpoint and works independently of the Agent host or DSH.

The backend stays `cdp` in the plan, manifest and export provenance. Explicit CLI values override the private plan, then the profile; omitted values preserve the plan, including explicit `0` and `off`. An old non-CDP preference or plan is refused before collection, never silently rewritten. There is no `auto` or alternate backend.

Computer Use and its lifecycle command are removed. Old requests return `backend-retired-computer-use`; BrowserSkill requests return `backend-retired-browserskill`. Historical runs remain readable and exportable with their original provenance, but cannot resume a retired backend. Never install or invoke an alternative browser controller to work around a failure.

## Retired browser-assist bridge

`--browser-assist browserskill` is retired and is not a backend. The CLI prints exactly one line, `media-missher-diagnostic platform=<p> kind=precondition code=browser-assist-replaced`, and exits 78 before any browser action. Keep `--browser-assist off`; do not replace the retired bridge with a BrowserSkill backend request.

Private screenshots stay available through `--screenshot-mode opened|all --allow-navigation` with `--browser-assist off` on the `cdp` backend. `opened` captures a detail page only when collection already opens it; `all` opens and captures every selected record.

## Collect safely

1. Resolve configuration with command-line values before environment values and the private mode-`0600` profile.
2. Run `scripts/preflight.py --live`. Live preflight probes the existing CDP endpoint in `cdp` mode and checks the shared layout, release markers, Python, dependencies, and five entrypoints. It does not select targets.
3. Run `scripts/run_collection.py` or one plan. The runtime controller checks each selected platform page and login state before creating output. A successful run creates one unique mode-`0700` directory and private mode-`0600` JSON artifacts.
4. Stop immediately on `403`, `429`, `461`, `471`, `999`, `risk`, `locked`, `blocked`, or cooldown signals. Do not retry a risk stop.
5. Validate only artifacts from the current run and its recorded start time. Reject `latest`, reused directories, old artifacts, symlinks, exit codes, and console checkmarks as proof.
6. Report counts, statuses, stop reasons, and absolute evidence paths. Limit samples to three metadata-only objects with platform and field count.

## Bound the collection envelope

- `--count-mode fixed` keeps the existing per-platform count behaviour and stops at the requested count.
- `--count-mode best_effort` means collect as much as you can. It has no fixed ten-record total cap and promises no total: it keeps paginating inside the authorized `--run-deadline`, bounded by a finite per-platform batch budget, a stall limit, and cancellation. A budget pause is reported as `budget-exhausted`, not as finished collection.
- `--run-deadline SECONDS` sets the total authorized window. `--batch-pages N` and `--batch-interval SECONDS` may only tighten the platform's own limits and no plan can relax them, while `--per-target-budget N` adds an explicit total record cap for a `best_effort` target.
- `--targets-json PATH` runs a private mode-`0600` multi-target plan, so one run may carry several accounts, platforms, or a Weibo topic. Targets stay sequential.
- The Xiaohongshu policy of at most 10 notes and 3 pages per batch with at least 600 seconds between batch starts, plus its persistent risk pause, is unchanged. It cannot be relaxed by a plan, a backend switch, a target change, or a different runtime home. A plan may only tighten platform limits.

## Run a Weibo topic task

`--topic NAME_OR_URL` runs a real Weibo topic task instead of a keyword search. It verifies the topic input, pages through the visible topic posts, extracts the outer poster of each visible post, dedups by Weibo UID, then visits each user's public homepage once per run and saves posts, user records, and topic-to-user relations.

- A plain `#话题#` uses the standard topic page. A 超话 (super topic) is a different page contract and is refused with `topic-container-unsupported`; it is never faked as a keyword search.
- Participants are only the authors of observed topic posts, including a forwarder who really appears in the results. Quote authors, recommendation-card authors, viewers, and likers are never participants. Never claim all participants, and never recurse into followers, following, or all posts.
- A homepage that is unavailable, deleted, permission-limited, or login-walled records a fixed reason (`profile-unavailable`, `profile-deleted`, `profile-permission-denied`, `profile-login-required`) and keeps the confirmed user entry and its source relations.

## Collect X

`platform=x` uses Chrome CDP. Its response route binds to the exact observed request; rendered-page evidence retains its own evidence level. Identity, deduplication and field-quality rules apply to both evidence types.

- `tweet_id`, `author_id`, conversation and quote ids are strings. A handle is never used as a numeric user id.
- `comments` is the reply count only and never claims reply bodies. `views` is the post view count, not video play counts. `bookmarks` and `collected` are one same-origin metric. Media preview images are distinguished from a video resource.
- An unknown value stays `null`. A displayed abbreviation such as `1.2K` keeps its original text and a `rounded` precision state instead of being presented as an exact count.

## Bound one record's browser actions

Each record permits at most one Xiaohongshu detail open and one CDP click. The current CDP session registers the exact response listener before that click and resolves either the same-page detail or its exact popup without opening a second browser. When a requested comment slice is short, Playwright may scroll only the unique visible comment container at most three times, with one fixed 1,500 ms wait after each scroll. It stops on enough comments, missing or ambiguous containers, non-scrollability, no growth, exhausted budget, or any risk signal. It never refreshes or reopens the detail; a non-risk shortfall remains partial evidence, while a risk signal stops the run before screenshot or retry.

Screenshots are private PNG evidence available on the `cdp` backend. The runtime prefers one visible article container and falls back once to `full_page_fallback`, with a fresh risk check immediately before that fallback. Each successful record carries `screenshot_path`, `screenshot_mode`, `screenshot_capture_kind`, `screenshot_observed_at`, and `screenshot_sha256`; a failed requested capture yields `screenshot-shortfall` without discarding verified structured fields.

## Preserve safety controls

- Collection attaches to the selected existing browser. Open a dedicated AI browser only through the documented browser-open setup action when the user has requested it; never open one to recover from a failure. Do not restart, terminate, reprofile, close or repurpose the user's existing browser or pages.
- Do not replace cookies, clear locks, clear state, rotate accounts, rotate network exits, or increase concurrency.
- Do not bypass a captcha, inject stealth behavior, use proxy rotation, defeat fingerprinting controls, or evade platform restrictions.
- Preserve rate limits, jitter, page caps, timeouts, cooldowns, sequential execution, and the Xiaohongshu complete-mode 5–15 second randomized open-note settle.
- Preserve the exclusive adapter collection lease. Never overlap two Media@Missher runs against the dedicated browser profile.
- Do not automatically retry or resume collection. If the user requests a retry, correct its concrete non-risk cause and pass preflight before one bounded attempt. A risk stop never authorizes a retry.

## Keep Feishu separate

The runtime and adapter never read Feishu credentials, create Feishu artifacts, invoke a Feishu client, or perform a remote Feishu write. Always pass `--no-feishu`; local JSON validation is not a remote write. Any Feishu operation is a separate workflow that needs separate explicit authorization.

## Report one status

Use one status:

- `success`: every requested count and completeness check passed
- `partial`: current evidence exists, but a count or completeness check failed
- `risk-stopped`: a risk, lock, block, or cooldown signal stopped the run
- `preflight-failed`: runtime, browser, backend, login, page, or configuration checks failed before output creation
- `failed`: the run produced no acceptable current evidence

Report the actual stop reason as well. The fixed vocabulary is `natural-end`, `no-new-records`, `budget-exhausted`, `run-deadline`, `count-reached`, `not-logged-in`, `permission-denied`, `risk-stopped`, `timeout`, `cancelled`, `empty-results`, `target-changed`, `session-lost`, `unsupported`, and `error`.

## Export saved results

Export is a separate, selection-driven, offline step: `media_missher_runs action=export`, or the CLI `runs export`.

- Choose `--record-kinds posts|topic_participants|user_profiles`, plus optional `--platforms`, `--topics`, `--targets`, `--fields`, `--field-groups`, `--format xlsx|csv|json|jsonl|sqlite`, `--file-name`, and `--overwrite`.
- Export only reads already-saved verified local results. It never opens a browser, never collects a missing value, and can be re-filtered and re-exported as often as needed.
- A requested field that was never collected is reported instead of being collected now. Partial, risk-stopped, and cancelled runs keep their status, missing fields, and observation times.
- An existing file is never overwritten unless `--overwrite` is passed explicitly.

## 15.3.0 小红书与历史结果规则

小红书每批最多 10 条、3 页，批次启动至少间隔 600 秒；翻页前等待并重新检查风险，保持原来的单次精确详情打开和 5–15 秒停留。风险暂停持久保存，不自动重试、到期清除或切换账号/浏览器。预算仅是本地保守限制，不保证平台安全。

`media_missher_runs` 可离线列出、导出或比较历史运行，以及查询 `xhs-status`；它不能发起采集或清除风险暂停。仅在用户明确要求继续时，才给采集工具传 `resume_run`，并保持原平台、总目标数、后端和私有配置。拒绝风险祖先和无绑定的旧运行；历史已验收数与本次新采数分别报告，原记录不改写。

解除风险暂停不属于自动修复步骤，只能由用户检查账号后明确执行本地 `xhs_safety.py --acknowledge-risk`。这不会清除批次间隔，不会启动采集，也不会允许继续风险旧运行。详情见仓库 `docs/XHS_RELIABILITY_15.3.0.md`。

## 17.0.2 新设备名单

新设备先在 Harness 使用 media_missher_setup 生成 Excel/CSV 模板，导入平台、博主名称和完整官方主页，查看预览后选择行号。同平台每次可选多位；名称不是身份。名单导入和选择完全离线，不启动浏览器或采集。Git 维护入口为 harness-plugin/scripts/setup-device.mjs，构建后使用同一工具实现。profile 的 active_platforms 限定默认范围；旧 profile 无此字段时使用已配置平台。空目标在 runtime 安装和采集前停止。采集只使用 Chrome CDP，连接已有登录会话；旧 Computer Use 请求返回 backend-retired-computer-use，不自动改写。不添加开机启动项，不调用已退休的 BrowserSkill。选好名单后，用户明确要求打开浏览器时可使用 browser-open（confirm_open=true）启动独立 AI 采集浏览器及本地登录指引；用户手动登录后 browser-check 只核对连接和平台页面，登录状态仍待授权采集的前置检查。按已有授权继续首批采集并展示结果，不因连接成功而自动扩展数量、导航范围或切换后端。

## 17.0.2 共享保护

同一用户 HOME 下的新版入口共用 `~/.local/share/media-missher-shared` 的锁与小红书状态。当前、默认及已登记 runtime home 的旧状态保守合并、同步写回；旧客户端不会自动获得全部保护。换端口、后端、浏览器或 runtime home 不会重置新版冷却。不要删除状态或切换 HOME/用户规避暂停。预检与采集共用 17.0.2 版本门槛，版本错误在 CDP 请求前停止；使用配套安装器修正。安装激活后根据本技能或已注册工具说明工作，不依赖维护对话。
