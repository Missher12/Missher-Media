# 2026-09-23 GPT-6 Astra 接入修复

用户授权当前任务修复 Astra 接入中的入口与指令冲突。原开发任务已结束，本轮仅在 Desktop 开发目录继续，保留所有既有未提交实现。当前进展、验证与安装边界见 [Astra 迁移记录](docs/ASTRA_MIGRATION_2026-09-23.md)；下方记录均保留为历史，不能替代本轮证据。

采用宿主模型 + Skill/CLI + 共享运行时。源码为 runtime 15.6.0 / Agent 0.1.0 / Bundle 0.6.0；用户确认 15.6.0 后，本机正式 Codex Skill 与共享运行时已从 15.2.1 同步升级到 15.6.0。指令统一为保存私有证据后按用户选择导出，沿用已有授权，保留 CDP 默认、单一所有者及风险即停。真实平台、Harness/OpenClaw 正式安装和 Git 操作仍暂停。

本轮源码与候选包修复已完成：历史选择导出补齐独立进程的共享核心加载，108 项相关 Python 回归通过；Harness 293、Agent 54 项单元通过，两种最终候选包的隔离安装通过。完整失败记录、重跑范围、包摘要与正式切换限制见上述迁移记录；这些结果不代表真实平台或 Astra 新任务行为验收。

正式安装记录：`20260923T074242322465Z-736a0c4a`。安装后源码一致性、同发布标记、离线 preflight、安装入口合成导出和桌面内置 Codex 的 Skill 发现通过；三份旧版恢复目录完整，267 个受保护文件及 Codex 模型配置保持不变。当前任务的既有 Skill 上下文与真实平台行为没有作为新版验收；新任务使用新版入口。

---

# 2026-09-20 跨 Agent 升级已获实现授权

稳定离线候选已重建并通过 Agent 隔离安装，见 [本轮验收记录](docs/CDP_CU_OFFLINE_ACCEPTANCE_2026-09-20.md)。Python 1295、Harness 293、Agent 54 项全套通过，生产源码与归档已逐文件核对。真实宿主、真实平台及完整 CU 功能仍未验收；下方过程记录不覆盖该验收记录。

实现进度（离线迁移中）：活动枚举已改为 CDP / Computer Use，计划 v2、manifest v3、历史只读兼容和批次 journal 已接入。BrowserSkill 专属执行模块已删除；活动提示/Skill 已同步退休诊断。Computer Use 的实际 DSH 映射仍未核验，离线核心仅支持单一 X 的结构化观察准入，其余模式明确拒绝。下方旧“完整候选已实现”不代表新方向已完成；最新限制见 `docs/DSH_COMPUTER_USE_CAPABILITIES.md`，检查日志在 `.superpowers/sdd/2026-09-20-cdp-computer-use-upgrade/`。

用户最新要求“Agent、DSH 各种都能使用，你看着改”。已据此更新同一规格/计划：通用 CLI + 共享 Skill 是基础，DSH 是薄包装，Computer Use 采用宿主无关协议、按实际能力启用；最终仍只有 CDP / Computer Use。原开发任务恢复唯一源码写入，本任务监督。源码实现、离线测试、本地构建和隔离验证已获授权；真实平台采集、正式宿主安装升级、Git 提交推送/发布仍暂停。此前“仅规划、全部暂停”的状态保留为历史，不覆盖本节。

---

# 2026-09-20 最新升级方向：CDP + Computer Use，仅规划

用户明确要求只保留 CDP 与 Computer Use，并包含 X 追加。最新权威需求见 [升级规格](docs/CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md)，执行拆分见 [实施计划](docs/superpowers/plans/2026-09-20-cdp-computer-use-upgrade.md)。CDP 默认且独立可用，Computer Use 可选接入 DSH；BrowserSkill 将从新版活动代码/依赖退出，只保留历史读取及明确迁移诊断。X、多平台多帐号、微博话题公开主页、有界多抓、可靠续抓及选择导出均保留。

本轮仅更新规划和文档入口，未修改运行源码，未恢复开发任务、自动监督、真实采集、安装或 Git 操作。下一次恢复需先核验实际 DSH provider/工具/权限与工作区差异。下方 CDP/BrowserSkill 及宿主优先记录均属旧方向，不能覆盖本节。

---

# 2026-09-20 Codex 修复收尾与暂停

用户最新要求：改完当前修复后暂停，等待其查看新版 DeepSeek Harness Computer Use。当前不是完整项目验收通过。详细修改、冻结源码身份、最终离线结果、真实 challenge 停止和未验收项见 [暂停交接](docs/CODEX_REPAIR_PAUSE_2026-09-20.md)。禁止自动继续采集、适配、升级或提交推送；下方既有记录保留为历史，不能覆盖本节。

---

# Media@Missher 15.6.0 project context

## 当前任务：双后端、X、多目标、best_effort 与选择导出候选 — 2026-09-20

用户指定统一在本机桌面副本目录工作：Codex 定方向并生成提示词；DeepSeek V4 在 Harness 完整开发；Codex 审改/验证；验证通过后更新 Git。当前仍是 15.6.0 / Agent CLI 0.1.0 / Bundle 0.6.0 的未提交候选，HEAD `f87dd8858a0b888f03a7885a1641823af13457bd`，分支 `codex/media-browser-agent-desktop-20260920`。origin 在复制时指向本机 Documents 原仓库，最终推送前需核对。

本轮的完整候选已实现，等待 Codex 审改与验证。实现范围与契约见下节；“尚未实现”的旧判断已不再成立。

桌面副本的历史 Harness dist 共 23 项已在前轮移到本机废纸篓中的 `Media-Missher-browser-dist-20260920.N39GRy`；Agent 产物与源码保留。失效 Harness Setup 入口、打包依赖测试副作用与共享构建耦合已在本轮整改。

下文均为继承的历史版本记录；其中旧工作树、“当前候选”、单帐号、自动 Excel、`--browser-assist browserskill` 桥接与旧 BrowserSkill 0.1.10/0.1.6 基线的描述均为历史，以本节与 `HANDOVER.md` 为准。

## Implemented candidate: dual backend, X, best_effort, topics and selection export

本轮交付的双后端共存、多目标计划、best_effort、微博话题参与用户与主页采集、X 采集和采集后选择性导出均为新代码；完整的变更清单、能力矩阵、测试结果、待真实验收项与回滚方法见 `HANDOVER.md`。此处只保留当前入口摘要。

架构数据流：`Agent 收集意图 → 版本化 CollectionPlan/多目标队列 → 共享调度与安全门 → 冻结 backend → 平台/模式解析器 → 统一标准化与验证 → 私有存储/检查点 → 导出选择与投影`。

后端选择：`--backend cdp|browserskill`，优先级为本次显式参数 > profile 保存的偏好 > 旧配置兼容默认 `cdp`；`auto` 明确拒绝；运行开始后冻结并写入 `plan.json`、`run_manifest.json`、进度与导出摘要。`cdp` 不要求安装 `bsk`；`browserskill` 不探测 9222/9223 端口。旧的 `--browser-assist browserskill` 混合控制桥接已退役，CLI 以固定 `browser-assist-replaced` 诊断拒绝，不再静默改变参数含义。

运行时新增模块：`contracts.py`（版本化计划/目标/任务/清单与停止原因）、`capabilities.py`（后端 × 平台 × 模式 × 能力矩阵）、`bsk_session.py`（bsk 会话所有权与固定 JSON 错误）、`bsk_page.py`（受能力约束的页面外观）、`extraction.py`（有界确定性 DOM 提取器）、`best_effort.py` 与 `batch_policy.py`（有限分批、停滞、期限、检查点）、`plan_runner.py`（顺序多目标任务队列）、`exporting.py`（离线选择导出）、`platforms/x.py` 与 `platforms/weibo_topic.py`（新平台与话题流程）。

安全不变量保持不变：单一浏览器所有者、顺序采集、精确目标绑定、私有 `0700`/`0600` 输出、风险立即停止且不自动恢复、小红书 10 条/3 页/600 秒与持久风险暂停不可被计划、后端、目标或 runtime home 放宽。

## Current Agent CLI and Skill candidate — 2026-09-08

Product **15.6.0 / Agent CLI 0.1.0 / Harness Bundle 0.6.0**, owned worktree `.worktrees/xhs-reliability-20260907`, branch `codex/media-xhs-reliability-20260907`, baseline `f87dd8858a0b888f03a7885a1641823af13457bd`. Changes are uncommitted; no final release SHA. This section supersedes historical current-state descriptions below. The owner referenced Tencent/BrowserSkill as the installation model: one Agent guide, a CLI and one shared Skill. The source repository remains PRIVATE; public download was selected as a distribution design and has not been deployed.

`agent-plugin/` packages the existing compiled tool factories and the same 40-file collector payload. Its CLI exposes help/version, offline doctor, explicit Skill installation, setup, collection and local runs. JSON stdout and bounded stderr progress are separate. It requires neither a Harness installation nor Cordis/DSH_HOME. `src/skills.mjs` supports explicit known Agent destinations plus a generic root, injects absolute commands and refuses unowned/edited Skill copies; installation is not proof of activation in a current host conversation.

The root `AGENT_INSTALL.md` and delivered Setup guide specify environment checks → Excel/CSV roster preview and selection → explicitly opened dedicated AI browser → manual login → authorized bounded collection → Excel/evidence delivery. Blank devices do not create runtime/output or probe CDP. `install.sh` and `agent-plugin/scripts/install.mjs` verify SHA and the entire allowlist before dependency installation, stage immutable owned releases, verify exact installed bytes and real entry commands, and switch only an owned launcher. Failed/cancelled installation preserves earlier activation. Process-group cleanup is verified before deleting the stage; uncertain cleanup preserves it. No npm lifecycle scripts run.

macOS/Linux use one CLI package with Node >=22.19 and npm; collection uses Python 3.11/3.12. Linux GUI/Chrome discovery is prepared. Windows `install.ps1` delegates to existing WSL2/WSLg, a normal Linux user and native Linux storage beneath the Linux user's home directory. WSL rejects external browser attachment not backed by the dedicated browser ownership marker; mirrored localhost is not proof of a same-OS browser. Native Windows collection is unsupported. Harness's existing dedicated installer remains macOS-only. Existing same-user locks, XHS limits/risk state and platform collectors are reused.

Validation: Python **1105 passed** with one expected socket warning; Bundle **289 / 18 files**; Agent **33 passed**; TypeScript, residual scan, diff check and independent spec/quality reviews passed. Final Agent Setup installs in an isolated macOS HOME via real npm, runs the actual launcher, validates blank-device behavior, installs/idempotently reinstalls a Skill, generates Excel and imports/activates a synthetic CSV. It invokes no Harness, launches no browser and makes no platform requests; the physical host does have Harness installed. Final Bundle 0.6.0 passed real Harness 0.5.5 isolated install/activation/refresh/tools/uninstall; 40-row/six-sheet data, browser actions and guidance services are synthetic/injected. Linux/WSL/Windows and actual Agent session activation remain unverified; CI jobs are prepared but unrun.

Deliverable: `agent-plugin/dist/Media-Missher-Agent-Setup-v0.1.0.zip` plus CLI tgz; native Bundle/Setup 0.6.0 under `harness-plugin/dist/`. Full commands, exact hashes and evidence boundaries are in `docs/AGENT_ENTRY_15.6.0.md` and `agent-plugin/dist/AGENT-ENTRY-EVIDENCE.json`. 50 Agent archive files and both 40-file payloads match source/staging; compiled implementation is identical. The 19 earlier distribution files and four formal-state files remain byte-identical to the start snapshot; the formal runtime remains 15.2.1 and no new shared directory appeared there. No formal install, source publication, push, tag or release occurred. Public hosting and anonymous download validation remain follow-up work, preserving the private source repository.

## Historical 15.5.0 context

## Current shared safety, preflight and progress candidate — 2026-09-08

Product **15.5.0 / Harness Bundle 0.5.0**, private local candidate in `.worktrees/xhs-reliability-20260907`, branch `codex/media-xhs-reliability-20260907`, baseline `f87dd8858a0b888f03a7885a1641823af13457bd`. Source remains uncommitted owned work; no final release SHA. This section supersedes current-state and proposal wording in all historical sections below.

The owner clarified that ordinary upgrades should preserve the product's Agent-facing default: installation/activation carries discoverable tools, parameter descriptions and a native optional `media-missher:agent-guidance` section, independent of maintenance chat history. No separate onboarding project was added. Existing Excel/CSV selection, explicit AI-browser opening, manual human login and proprietary Missher notices remain intact. Blank devices still create no runtime/run and launch no browser.

New shared_safety.py coordinates all 15.5+ entries under one user HOME, independent of runtime home, CDP port or browser session. Verified inherited descriptors preserve the lock through the child lifetime; known legacy locks and XHS states are merged conservatively and dual-written. Case aliases and overlapping shared paths are rejected or deduplicated safely. Another HOME/user and unknown old clients are not automatically coordinated. Existing XHS limits remain 10 notes, 3 pages and a 600-second interval, with persistent risk stop and no automatic retry/reset.

Preflight and collection share a bounded, safe VERSION check before probes/output. Native Python 3.14 installation exposed pinned dependency incompatibility; installer and preflight now require runtime Python 3.11/3.12, discover compatible local interpreters and safely reuse an owned existing compatible venv. Explicit incompatible --python fails; unsupported old venv is rebuilt only in staging with rollback preservation.

Progress uses a fixed bounded stderr protocol and keeps final JSON intact. Per-run phase-timings.json and per-invocation private .progress snapshots contain only fixed phases/platforms/counts/timings. `media_missher_runs action=progress` is local-only and reports last observed state, not liveness. Optional observer/storage failure does not interrupt collection or owned-process cleanup. The six-sheet workbook adds controller/platform timing fields; nested phase times are not additive or end-to-end Harness latency.

Final validation: **1105 Python passed** (one intentional socket-block warning, 193.39 seconds); **283 Bundle passed / 18 files** (114.66 seconds); TypeScript, residual scan and diff check passed. Shared and progress specification/quality reviews passed. Actual Python 3.14.7 bootstrap selected 3.11.15 and completed dependency installation; a separate valid existing-venv-only upgrade with no compatible PATH entry and real offline preflight passed. Actual Harness 0.5.5 isolated install/activation/import/refresh/backup/installed tools/uninstall passed; the collection and phase inputs are synthetic 40 records, not live platform evidence, and the native guidance service hook uses an injected service fixture.

All **40 payload files, 2 compiled files and 29 installed core payload files** match final source bytes; Setup embeds the exact reviewed Bundle and AGENT.md. Formal runtime remains 15.2.1, profile/XHS state/Chrome LaunchAgent hashes are unchanged, actual user shared scope remains absent. Six old 0.2/0.3/0.4 archives and blank templates are unchanged. No new platform request, browser launch, formal profile install, commit, push, tag or publication. Prior 15.4.0 live 4/4 is historical evidence only. Artifacts and complete evidence: `harness-plugin/dist/SHARED-SAFETY-EVIDENCE.json`; workflow: `docs/SHARED_SAFETY_15.5.0.md`.

## Historical 15.4.0 context

## Live acceptance and upgrade assessment — 2026-09-08

The user selected one record from each configured platform, sequentially. The unchanged 15.4.0 candidate controller/core completed real Bilibili/XHS/Douyin/Weibo collection: **4/4 accepted, 81.855 seconds, no risk stop or timeout**. XHS passed complete current-detail validation. The existing Bundle evidence loader and workbook generator produced and reopened a private six-sheet/four-record workbook. This was an isolated normal runtime-only installation with real CDP and dependencies, not synthetic collection or a formal upgrade; the test driver retained the original browser's collection lease and shared XHS policy state in addition to candidate locks. Formal runtime remains 15.2.1; profile bytes are unchanged, temporary platform pages closed and locks released. Source bytes and prior Bundle archives remain unchanged. Today’s focused offline regressions passed 217 Python and 44 Bundle tests.

Assessment identified a reproduced preflight/version-message inconsistency, plus conditional cross-runtime browser-lock/state scope and missing stage timing/progress. These are recorded proposals, not implemented upgrades. No retry or second platform batch was performed. See `docs/LIVE_ACCEPTANCE_2026-09-08.md` for exact scope, private evidence location, result verification and problem/cause/impact/recommendation details. This new bounded live evidence supersedes “no live collection” statements only for this specific 4-record test; it does not validate scale, release/install migration or future platform risk behavior.

## Current AI browser and copyright candidate — 2026-09-07

Product **15.4.0**, Harness Bundle **0.4.0**, isolated uncommitted local candidate. Worktree `.worktrees/xhs-reliability-20260907`, branch `codex/media-xhs-reliability-20260907`, baseline `f87dd8858a0b888f03a7885a1641823af13457bd`. This section supersedes the current-state wording in all historical sections below. Main, other worktrees, real runtime/profile, user browser data and existing LaunchAgents remain unchanged; no push, tag, formal installation or publication.

The owner authorized the complete fresh-device path and notification to existing task `01a07766-9fe2-7da1-9809-7437205e41c5` (`【DSH】Media@Missher`). Existing offline template/import/preview/selection stays first. `browser-open` requires an explicit user opening request, confirm_open=true and selected targets. It launches installed macOS Chrome with a private dedicated browser/chrome-profile directory, local port 9223 and a static local welcome page. The user clicks official platform links and logs in manually. `browser-check` reads local CDP version/list only; connection and page presence never imply authenticated readiness. Authorized collection preflight, bounded first batch and result reporting follow the AGENT.md contract. Empty devices, status/import/activate and collect never launch the browser automatically.

Ownership is bound to a digest of the current local Chrome session. Unknown folders, occupied unowned ports, conflicting environment settings and stale sessions do not trigger takeover. Opening reuses a verified owned session, otherwise launches only fixed installed Chrome paths. The shared profile mutation lock, exact backup and atomic write preserve other settings. CLI SIGINT/SIGTERM aborts the same tool signal and waits for lock cleanup. Standard macOS admin-group-writable Chrome installations are supported; world-write and unrelated-group-write remain rejected. New code is in browser-setup.ts and setup.ts; setup-device.mjs exposes the same actions for Git.

The owner selected **Copyright (c) 2026 Missher, all rights reserved** with a proprietary notice for original work. Canonical LICENSE, COPYRIGHT.md and THIRD_PARTY_NOTICES.md state the no-unauthorized-modification/derivative/redistribution terms and preserve third-party licenses, applicable law and previous effective grants. Package manifest, build banner, guide, Bundle/Setup and newly installed runtime carry notices; the Git installer also includes them in skill references. Fourteen SDK packages whose declarations are included in index.d.ts retain their original MIT license texts. This is not copyright registration or technical copy prevention. Any future public source/distribution decision remains the owner's; public GitHub forks have platform-term implications documented in COPYRIGHT.md.

Final validation: **1066 Python tests passed** (one intentional socket-block warning, 121.24 seconds); **272 Bundle tests / 16 files passed** (38.68 seconds); TypeScript passed. After the final Git notice-copy directory fix and README wording, three packaging/source regressions passed and rebuilt the final archives. Actual Harness **0.5.5** isolated CLI install/activation/import/refresh/backup/offline tools/uninstall passed; collection is a synthetic 40-record six-sheet workbook and browser launch is an injected fixture. Separate actual Chrome **152.0.7977.76** smoke passed with one local guide page, one launch, session reuse, exact backup, no platform pages or login claim, and verified owned-process/directory cleanup. No real platform collection was performed.

All **37 payload files and two compiled library files** match exact source bytes. Prior 0.2.0/0.3.0 archives, evidence and blank templates remain unchanged. New archives and checksums are in harness-plugin/dist; final hashes and implementation digest are in HANDOVER.md and **AI-BROWSER-EVIDENCE.json**. The new browser/copyright increment passed bounded independent static review. The prior parser final independent follow-up limitation in ONBOARDING-EVIDENCE.json remains; it is not replaced by this narrower review. Before formal installation/release, complete that review and separately authorized real-account acceptance.

## Historical onboarding candidate — 2026-09-07

Product **15.4.0**, Harness Bundle **0.3.0**, local candidate only. Same isolated worktree `.worktrees/xhs-reliability-20260907`, branch `codex/media-xhs-reliability-20260907`, baseline `f87dd8858a0b888f03a7885a1641823af13457bd`. This section supersedes current-state wording below; 15.3.0 / 0.2.0 is retained as historical evidence and immutable prior artifacts.

The user selected Excel/CSV template import for new devices. `creator-list.ts` provides offline bounded spreadsheet parsing; `setup.ts` and `private-config.ts` implement status/template/import/activate without Python, CDP, runtime installation or collection. Templates have no real targets. Full official HTTPS homepages determine identity; names are labels. Import IDs include a random component and the exact saved roster digest. Activation verifies both roster and preview, selects at most one creator per platform, backs up exact prior profile bytes and atomically writes the selection. It preserves other targets/settings and records `active_platforms` so retained targets never silently join a default run.

The Bundle reads the selected profile before ensureRuntime or output work, rejects missing/invalid selected targets and uses a private snapshot for each collection. Git CLI defaults to the active selection, or configured targets on legacy profiles. Four-platform legacy configuration preserves its behavior. The controller now requires runtime 15.4.0. `harness-plugin/scripts/setup-device.mjs` exposes the same offline setup implementation for Git checkouts after Node build; no duplicate Python spreadsheet parser was introduced.

Browser behavior remains connect-only. Live read-only inspection found a separate existing com.missher.chrome-cdp LaunchAgent with RunAtLoad and KeepAlive; it is not included in the Bundle and was not changed. Existing historical Excel output was opened for the user from their private saved-runs directory. No fresh platform or login request was performed.

Final new-version validation: Python 1066 passed / one intentional socket-block warning; Bundle 244 passed / 14 files (one worker, 87.72 seconds), including 154 parser checks; TypeScript passed. The final archive passed actual Harness 0.5.5 isolated install/refresh, CSV and XLSX onboarding, active-selection precedence, exact profile backup, offline history, synthetic workbook and uninstall checks. Blank-device runtime calls, runtime/run directory creation, browser launches and live platform requests were zero. Git CLI help/status/template/import/activate passed a separate end-to-end check. All 35 payload and two compiled library files match source; prior 0.2.0 artifact hashes are unchanged. Exact final artifact hashes and implementation digest are in `harness-plugin/dist/ONBOARDING-EVIDENCE.json` and `HANDOVER.md`. The candidate is uncommitted, so no final commit SHA exists.

Specification review passed. All reported correctness findings were fixed: identity length, preview integrity/display, pre-model XLSX structure limits, canonical ZIP part classification and active selection overriding legacy defaults. ZIP scanning now classifies every allowed plain-roster part once and passes that classification to bounded SAX validation before ExcelJS. Embedded objects, cell comments, tables and noncanonical parts are rejected; the template explains this subset. The final independent source-review follow-up was blocked by an automated tool content check for possible cybersecurity risk and returned no verdict. It is not counted as independent approval. The root completed a source-only comparison with local ExcelJS dispatch and existing tests; obtain the remaining independent review before formal installation or release.

Prior 1059 Python / 65 Bundle evidence below belongs to 15.3.0 and must not be counted as 15.4.0 validation. Main, other worktrees, formal runtime/profile, LaunchAgents and browser data remain unchanged; no commit/push/tag/release. New-device usage details are in `docs/NEW_DEVICE_15.4.0.md`.

## Historical reliability candidate — 2026-09-07

Product **15.3.0**, Harness Bundle **0.2.0**, local candidate only. Worktree `.worktrees/xhs-reliability-20260907`, branch `codex/media-xhs-reliability-20260907`, source baseline `f87dd8858a0b888f03a7885a1641823af13457bd`. This section supersedes current-state wording in the historical sections. Main, other worktrees, the installed runtime, and real Harness profiles were not changed. Git CLI and Bundle ship the same Python controller/core; the new controller requires runtime 15.3.0 before live preflight.

The user authorized the reliability upgrade with Xiaohongshu risk reduction as the priority. Each XHS batch accepts at most ten notes and three list pages; extra list pages wait three seconds. Complete detail collection retains its existing five-to-fifteen-second dwell and bounded comment scrolling. A private state file and nonblocking lock enforce ten minutes between batch starts and persist risk pauses across restarts. Risk does not expire automatically. An explicit local operator acknowledgement clears only the pause, preserves the interval, and starts no collection. These are local conservative budgets, not platform-approved safe thresholds.

Accepted prefixes are atomically committed as one `committed.json` envelope containing the strict manifest and declared JSON artifacts. Current-run recovery restores only that run's committed compatibility files after the engine stops. Historical reads use the committed envelope without imposing current-run freshness. Stop forwards signals through the owned adapter/runtime process chain and keeps the collection lease until bounded cleanup completes; adjacent processes and the user's Chrome remain outside that shutdown scope.

New standard-library history operations list, export, and compare exact private runs without browsing. Explicit creator continuation binds the original request (including timeout), private configuration digest, original positive target counts, parent chain, native IDs, completeness and required screenshot evidence. Risk ancestors and invalid/over-counted history are rejected. It creates a new directory and counts only new rows as new collection. Runtime collectors skip accepted historical IDs before expensive details. Harness exposes `media_missher_runs` with list/export/compare/xhs-status, and `media_missher_collect.resume_run`; no model tool can clear the risk pause.

Source ownership: controller and history in `media-missher/scripts/`; atomic storage, continuation and XHS policy in `runtime/media_missher_runtime/`; policy operator CLI in `runtime/scripts/xhs_safety.py`; tool registration, validation and workbook projection in `harness-plugin/src/`. Existing sequential collection, explicit navigation, BrowserSkill-off default, private artifact permissions, native-ID validation and risk-first status remain in effect. Search now forwards timeout and supported comment parameters; bounded advancing duplicate pages no longer end collection prematurely.

Candidate packaging: `harness-plugin/dist/dsh-media-missher-0.2.0.tgz` and `harness-plugin/dist/Media-Missher-Harness-Setup-bundle-v0.2.0.zip`. The historical GitHub bootstrap still resolves the released v15.2.1 asset. Installation and release have not been performed for this candidate. Final verification: 1059 Python tests and 65 Bundle tests passed, TypeScript passed, 35 payload files match source, and isolated Harness 0.5.5 CLI install/refresh/remove plus installed offline tools passed. Exact artifacts and layered evidence are recorded in `HANDOVER.md` and `harness-plugin/dist/RELIABILITY-EVIDENCE.json`; older test numbers below are historical. Specification and behavior: `docs/XHS_RELIABILITY_15.3.0.md`.

Live scope: zero actual platform requests in this upgrade. Offline fixtures and isolated Harness CLI lifecycle checks do not establish real account acceptance or guarantee avoidance of platform risk controls.

## Historical Bundle 0.1.1 maintenance — 2026-09-07

Historical source baseline: `9d70e1a3030b1534c464155df618e661b56a1f70`; private remote `Missher12/media-missher` was verified through GitHub metadata. Worktree: `.worktrees/harness-maintenance-20260906`; branch `codex/media-harness-maintenance-20260906`. Main and the pre-existing platform-capture-fix worktree were not edited. No collection-core source changes were necessary in that earlier maintenance task.

Bundle candidate is **0.1.1**; product VERSION and embedded runtime remain **15.2.1**. The real web profile was read-only inspected and still names Bundle 0.1.0. Its entry SHA-256 was `e436e16c8046400d2fd46a19e8a152de885381f555b318b419abc186b6dc5c65`. Installed runtime current/VERSION was 15.2.1. Do not infer byte equality of installed runtime source from VERSION alone.

### Verified source-to-controller path

`harness-plugin/src/index.ts` -> tsdown `lib/index.js` -> allowlisted payload staging -> private `dsh-media-missher-0.1.1.tgz` -> Bundle-specific Setup ZIP -> installer SHA-named archive under the selected DSH_HOME -> profile node_modules -> `payload/media-missher/scripts/run_collection.py` -> existing runtime `venv/bin/python` and `current/scripts/scrape_all.py`. `harness-plugin/AGENT.md` travels inside both the package and Setup as the fresh-machine onboarding contract; it does not replace runtime registration. The existing Python adapter owns runtime/install and browser collection leases, preflight, risk handling and unique-run validation. The Bundle projects declared platform JSON into a private workbook. Runtime provisioning uses the payload installer only if the exact product version is unavailable; this branch did not provision the real runtime.

The local Harness now contains `Contents/Resources/runtime/node/bin/node` and `Contents/Resources/runtime/app/lib/bin.js` (CLI package 0.1.3-alpha.1). There is no bundled pnpm at the old path. The installer now detects this layout and requires an already installed standard-location pnpm; old bundled Electron/CLI/pnpm layout remains supported by fixture tests. No automatic pnpm/BrowserSkill/browser installation occurs. The root historical GitHub bootstrap still downloads the previously released v15.2.1 Setup, not this unpublished candidate.

### Capability and priorities

- Existing creator tool: bilibili/xhs/douyin/weibo, canonical sequential order, default ten per platform, bounded positive count, optional XHS comment count and navigation flag. Navigation now defaults to `false`; `true` requires per-call authorization. No tool UID/credential arguments. XLSX Summary + combined + four platform sheets. Existing standalone search/other conversions were not newly exposed.
- P0 fixed: child cancellation/timeout escalation; malformed/unknown parameters; no-XHS comment mismatch; native-ID duplicate export; successful status with insufficient validated rows; request/platform mismatch; stale or non-private evidence; free-form diagnostic leakage; unsafe numeric identifier export.
- P0 fixed: SDK runtime import assumed host internals were available through peer dependencies. The Bundle now registers a typed public ToolDefinition with full JSON Schema and explicit argument normalization, using SDK packages only at development time. The installer verifies real entry import as well as entry hash and effective config.
- P1 fixed: old/new Harness layout discovery; candidate Bundle/Setup version separation; reproducible test preparation from current source; isolated install/reinstall/backup/uninstall evidence.
- P2 design only: explicit resume and offline re-export. No new collection ability was implemented. Existing checkpoint output is not an implemented resume input.

### Historical resume proposal, implemented in the current candidate above

Goal: recover useful work after a non-risk interruption while preserving truthful freshness. Add an explicit request for a previous owned run, selected platforms and bounded new count. Validate the exact prior manifest/checkpoint, native IDs, private permissions, schema/version, profile identity via a local digest, and absence of a risk/cooldown stop. Keep the previous run immutable. A newly authorized run reacquires the existing lease and passes fresh preflight; it records a parent-run reference and separately labels prior versus newly observed items. It must never count historical items as fresh observations or automatically replay a risk stop. Only after agreeing this contract should controller/checkpoint input change; recheck parallel ownership before touching Python core. Acceptance must cover interrupted partial runs, ID collisions, profile mismatch, stale checkpoints, risk stops and current-run export attribution. Offline re-export should likewise be explicit and labeled historical, without navigation.

### Verification and boundaries

Python sockets-disabled regression: **988 passed**, one intentional pytest-socket warning. Test dependencies were installed only into uv's test environment; no browser binary was downloaded. Source and onboarding commits: `6799e07624de28fd74cf5b01c4c7c16d098aa8cf`, `9b101b889d955345935fc052c4912e6b545af659`; final artifact refresh commit: `f8ee0943582136000fde22552de72bf17254e497`. Bundle regression: **61 passed**; typecheck, package checksums and exact native lifecycle results are recorded in HANDOVER.md and `harness-plugin/dist/MAINTENANCE-EVIDENCE.json` after final packaging. Native lifecycle uses a temporary DSH_HOME and synthetic records; it does not prove platform login or real collection.

Live account/platform requests this session: **0**. No live preflight, navigation, Cookie/profile read, BrowserSkill session or remote write was performed. Required for live acceptance: selected platform(s), exact target or permission to use an existing private profile, per-platform count and explicit navigation permission where needed. Report actual platform/request/success/failure/output counts then; never reuse the historical 40/40 as current proof.

No push, tag, release, main merge, real-profile installation or change to Desktop repositories was performed. Preserve the old working trees, runtime, user profile, browser and private outputs.


Media@Missher collects and validates Bilibili, Xiaohongshu, Douyin, and Weibo records through one independently authored shared runtime. This file records the architecture, verification workflow, deployment state, and recovery boundaries for future work.

The current source and installed operational candidate version is Media@Missher V15.2.1 (`15.2.1`), recorded once in the repository `VERSION` file. Ordinary Bilibili and Douyin creator collection is live-accepted; the optional Bilibili complete-mode exact-target blocker below remains intentionally unresolved. Product versioning is separate from the installer's unique UTC timestamp-and-random-suffix deployment release so repeated upgrades and exact rollback paths remain collision-free.

## Project goal

Preserve creator collection, single-platform search, complete Bilibili and Xiaohongshu evidence, native identifiers, null-versus-zero values, private output, sequential execution, and immediate risk stops without retaining replaced implementations in active paths.

## DeepSeek Harness Bundle

The current Agent-facing delivery is the private macOS Bundle `dsh-media-missher` version `0.1.0`, built from the exact Media@Missher `15.2.1` source. It is installed into the Harness `web` profile by double-clicking `Install Media@Missher Harness Plugin.command`. An authenticated GitHub bootstrap, `Install-Media-Missher-from-GitHub.command`, lets a Harness Agent pull the self-contained `v15.2.1` Setup ZIP from the private `Missher12/media-missher` Release without embedding a token. The bootstrap verifies the Release-provided Setup SHA-256 before extraction. The one-line handoff launches that bootstrap in an independent Terminal process, which then executes the inner installer so Harness can exit and reopen cleanly. The installer uses only the Electron runtime, CLI, and pnpm bundled in `/Applications/DeepSeek Harness.app`; it requires no user-managed Node.js or pnpm. Before mutation it verifies the canonical archive, copies its exact bytes to a mode-`0600` SHA-named artifact beneath `~/.dsh/artifacts/media-missher/`, and privately backs up the profile package manifest. The immutable staged path prevents pnpm from reusing stale bytes for a changed same-version local tarball and keeps the profile independent of the checkout path. Installation succeeds only when the installed entry hash matches the verified archive and the effective Cordis configuration contains both `id: media-missher` and `name: dsh-media-missher`.

The Bundle registers one model-visible tool, `media_missher_collect`. A zero-argument call selects Bilibili, Xiaohongshu, Douyin, and Weibo, requests ten records per platform, runs the existing controller sequentially, disables Feishu, and creates one mode-`0600` Excel workbook in the unique private run directory. The controller declares the exact manifest through its validation diagnostics while platform JSON remains in its evidence list; the adapter validates both beneath the controller-owned run directory. A non-risk partial run still projects every independently validated record and retains the missing platform's fixed diagnostic in `Summary`. The workbook has `Summary`, `All Platforms`, `Bilibili`, `Xiaohongshu`, `Douyin`, and `Weibo` sheets. Identifiers remain text, formula-prefixed strings are escaped, nested values are JSON strings, and the destination is linked atomically without overwriting an existing file.

Harness never receives UIDs as tool arguments and the model result contains no raw records. The adapter reads the existing mode-`0600` profile, reuses or atomically provisions only exact runtime version `15.2.1`, validates controller-owned manifest evidence beneath the configured output root, and returns only status, selected platforms, requested and collected counts, and local manifest/workbook/run paths. Existing controller rules remain authoritative for one-browser ownership, exact response binding, risk stops, private output, and navigation cleanup.

The canonical private artifact is `harness-plugin/dist/dsh-media-missher-0.1.0.tgz`. The self-contained macOS delivery is `harness-plugin/dist/Media-Missher-Harness-Setup-v15.2.1.zip`; its exact checksum is recorded separately in `harness-plugin/dist/SETUP-SHA256.txt`, avoiding a circular checksum inside the ZIP. `harness-plugin/scripts/native-smoke.mjs` proves the real Harness CLI lifecycle in a temporary `DSH_HOME`: install, effective-config discovery, default 4x10 synthetic tool projection, six-sheet workbook reopen, uninstall, and preservation of adjacent profile/state files. The owner-authorized `v15.2.1` GitHub Release must remain in the private repository. Public npm or public GitHub Release publication remains prohibited until a repository-wide license and provenance review is complete.

### Harness live acceptance (2026-08-28)

The final private Bundle SHA-256 is `fc8ab1412d2ae3484dbe24c28c36390137da6b411c815d5b3562e8f819e4fa65`. The one-click installer copied it to `~/.dsh/artifacts/media-missher/dsh-media-missher-0.1.0-fc8ab1412d2ae348.tgz`, installed it into the real `web` profile, preserved `dsh-missher-evolution`, and proved the installed `lib/index.js` hash matches the verified archive. The exact prior profile manifest is retained in the timestamped private backup reported by the installer.

After the installed payload's live preflight passed against Chrome `152.0.7977.64`, the zero-argument installed tool completed the required sequential 4x10 run at `~/.dsh/media-missher/runs/run-20260827T183804Z-qzh734e9`. Its manifest is `complete`; Bilibili, Xiaohongshu, Douyin, and Weibo each contain exactly ten records with `complete` status and `ok/ok` diagnostics. The tool returned 40 total records and created `Media-Missher-全平台抓取结果-20260827T184039577Z.xlsx` in that run. The directory is mode `0700`; the manifest and workbook are mode `0600`; the run contains no symlink or Feishu artifact; and the XLSX ZIP container passes full integrity testing.

Two real-integration defects were found and fixed before this final acceptance. A normal Python virtual environment uses an executable `bin/python` symlink, so the adapter now permits only that executable path to resolve to a regular executable while profile, payload, manifest, and evidence symlink rejection remains unchanged. The controller declares its exact manifest through `validation.diagnostics`, not the platform `evidence` list, so the Harness adapter now validates that declared manifest beneath the controller-owned run directory and creates a workbook even for independently validated partial records. The initial four-platform diagnostic run therefore yielded a truthful 30-record partial workbook after Bilibili's non-risk `creator-capture-timeout`; one fresh-preflight Bilibili-only retry passed 10/10, and the final required zero-argument run then passed 40/40 without another platform failure.

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

**历史（已被 2026-09-20 候选取代）**：V15 retains an optional BrowserSkill bridge for Bilibili creator details while preserving Playwright/CDP as the collection authority. BrowserSkill 0.1.10 with extension 0.1.6 may health-check, create one bounded session, borrow the one exact marked Media@Missher temporary tab, snapshot, click, return, and stop. It never owns response capture, identifiers, risk policy, parsing, screenshots, cookies, browser storage, anti-detection, or verification bypass. Xiaohongshu does not use this bridge.

**历史（已被 2026-09-20 候选取代）**：Bilibili creator collection may request `--browser-assist browserskill`; Xiaohongshu requires `--browser-assist off` and rejects explicit BrowserSkill before navigation with `xhs-browser-assist-unsupported`. Bilibili and Xiaohongshu may request `--screenshot-mode opened|all`; all non-default modes require explicit `--allow-navigation`. Bilibili search rejects these advanced modes. Bilibili pure text/image dynamics are bound by exact `dynamic_id`; Xiaohongshu uses the one existing CDP session for exact-click same-page or popup detail resolution, keeps its exact response listener, and applies the 5–15 second settle only to complete mode. Screenshots remain private mode-`0600` PNG files under the current run and carry run-relative path, `article` or `full_page_fallback` capture kind, `screenshot_observed_at`, and `screenshot_sha256` metadata. `all` requires a positive count; `opened` may retain count `0` because it creates no additional opens.

**历史（已被 2026-09-20 候选取代）**：BrowserSkill 0.1.10 performs its own upstream bundled skill sync whenever an explicitly assisted run executes `bsk session start`; JSON output only hides the hint. Media@Missher does not bypass that behavior. Its preflight remains read-only, starts no session, and downloads or upgrades neither the BrowserSkill binary nor its extension.

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

Post-cutover verification proved version `15.0.0`, matching release markers, byte-equivalent runtime and Codex skill source trees apart from deployment metadata, mode-`0700` runtime/state directories, mode-`0600` release markers, all five installed entrypoints, installed runtime and Playwright imports, the installed Codex skill validator, and both offline and existing-CDP live preflight. Historically the optional BrowserSkill bridge passed a read-only preflight against CLI 0.1.10 and extension 0.1.6 with one browser and zero sessions before and after the check. This verification started no BrowserSkill session and performed no platform collection.

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
