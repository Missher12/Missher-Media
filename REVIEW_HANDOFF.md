# Media@Missher：CDP / BrowserSkill 双后端、X 采集与代码精简审查

> **历史审查，方向已更新。** 当前规格为 [CDP + Computer Use + X](docs/CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md)，实施步骤见 [新计划](docs/superpowers/plans/2026-09-20-cdp-computer-use-upgrade.md)。下文“最新决定”和完成状态均属当时记录；BrowserSkill 不再保留为新版执行后端。当前仅规划，保持暂停。

审查日期：2026-09-20，Asia/Shanghai。状态：**设计审查与开发交接，尚未实现 BrowserSkill 主采集器或 X 采集器**。

**最新决定：CDP 和 BrowserSkill 长期共存，显式选择，不再以删除 CDP 为改造目标。** 用户确定的协作只有四步：Codex 审查方向 → 给出 DeepSeek V4 提示词并由用户在 Harness 开发 → Codex 审查、必要修正与验证 → 验证通过后更新 Git。可直接使用 [DeepSeek V4 开发提示词](DEEPSEEK_V4_PROMPT.md)。此决定覆盖旧历史文档中的 Browser-only 或退役 CDP 描述。

**同次补充需求：多平台/同平台多帐号选择、尽量多抓、采集后选择性导出、微博话题参与用户及公开主页采集。** 这些都是本次完整候选的功能，不另增用户协作流程；本文第 4B 节及开发提示词包含具体契约。

## 1. 工作约定与当前基线

- 唯一开发、调试和审核目录：`/Users/missher/Desktop/Media@Missher`。
- 用户使用 DeepSeek V4 在 DeepSeek Harness 中负责完整候选实现；Codex 负责方向审核、代码审查、必要修正和最终验收。共享源码一次只允许一个实现者写入。
- 后续从本目录的实际工作区继续，先核实分支、HEAD 和已有改动。不要用旧 Documents checkout、旧 worktree 或已安装 runtime 替代本目录。
- 当前分支：`codex/media-browser-agent-desktop-20260920`。
- 当前 HEAD：`f87dd8858a0b888f03a7885a1641823af13457bd`；HEAD 中的 `VERSION` 为 `15.2.1`。
- 当前磁盘候选：runtime `15.6.0`、Agent CLI `0.1.0`、Harness Bundle `0.6.0`。新版源码、复制后的调整和清理尚未提交，因此 HEAD 不能代表当前候选内容。
- 审查开始时，排除 Git 元数据、忽略文件、`node_modules`、`.DS_Store` 和已删除路径，214 个普通源码/文档文件的聚合摘要为 `46875af320f4c651c372b17b5b8a4706e4ba72a91f9bd93c82e13b479aa1c526`。算法：相对路径排序，逐项拼接 `path + NUL + sha256(bytes) + LF` 后计算 SHA-256；不包含本轮新增审查文档。
- Git 工具：`2.50.1 (Apple Git-155)`。桌面仓库的 `origin` 当前是本机 `/Users/missher/Documents/Media@Missher`，不是 GitHub；不要把向这个 origin 推送当作备份到远端。

用户原 X 规划已原样保存为 [X 原始提案](docs/references/2026-09-20-x-proposal-original.md)。原文件位于桌面项目旁的 `Media@Missher-X方案.md`，SHA-256 为 `de90219dea78e6d797b4ce2d8d319f486c8f446b918a125d35be1e079bbc68ee`。原提案的“24 条成功”是作者记录；本轮未获得该次可验证运行的原始证据，不能作为 BrowserSkill/X 已验收的结论。

## 2. 审查发现

### R0 / P1：旧辅助桥接的 stale 重试缺少动作间风险门槛

问题：`runtime/media_missher_runtime/browser_skill.py:361` 在 stale-selector 后重新 snapshot 并再次派发同一 click。`platforms/bilibili.py:335` 对 BrowserSkill 辅助显式开启该重试，风险检查在协调调用返回或抛错后才执行。

原因：桥接层没有在第二次动作前接入外层风险观察器；重新 snapshot 本身不代表风险解除或第一次动作未派发。

影响：在风险响应与 stale 返回交错的场景下，外层最终报告停止之前仍可能出现第二次点击派发。此处是现有代码路径审查，未通过真实平台触发。

推荐方案：先补风险事件与 stale 返回交错的离线回归，禁止在风险、超时或结果不明后重放点击。旧辅助路径优先关闭 stale 点击重试；双后端重构后将统一风险状态检查放在每次外部动作前，采集器负责最终的证据与停止状态。

### R1 / 改造前置条件：当前 BrowserSkill 是旧 CDP 流程的辅助，不能仅升级版本号就变成独立后端

问题：桌面副本尚不具备 BrowserSkill 独立采集主路径。

原因：`runtime/media_missher_runtime/browser_skill.py:13` 固定 CLI `0.1.10`、扩展 `0.1.6`；`:209` 起按旧协议字段精确校验版本。`runtime/media_missher_runtime/models.py:58` 明确拒绝 XHS BrowserSkill 模式。旧桥接还依赖 Playwright 页面对象、标记 DOM 和借用原 CDP 页；现有平台采集器依赖响应正文与 listener-before-click 顺序。

影响：直接把本机 bsk 升到 0.3.0 会被旧适配器拒绝；仅放宽版本判断又不能补齐会话、观测和数据来源差异。把目录称为 Browser 版也不会改变这一行为。

推荐方案：保留并封装当前 CDP 后端，新增有明确能力契约的 BrowserSkill 后端；由共用控制器选择且每次只运行一种。BrowserSkill 运行失败时不能自动改走 CDP，两者各有独立的连接检查与会话收尾。

### R2 / P1：X 原提案的 GraphQL 正文方案不受官方 BrowserSkill 0.3.0 network 接口支持

问题：原提案第 206–211 行用 `response.json()` 读取 GraphQL；官方 `bsk network` 没有等价能力。

原因：已核对 0.3.0 的 `NetworkEntry`/`NetworkResult`，只有 URL、状态、类型、时间及游标等元信息，没有响应 body。DSH BrowserSkill 插件也未提供任意脚本 evaluate；CLI 的 evaluate 能力不能当成 DSH 原生工具已支持的功能。

影响：原提案的完整用户资料、精确互动数、长文和媒体原始链接不能被承诺为 BrowserSkill 页面采集的必得字段。

推荐方案：X 的 CDP 后端可在本次已授权页面内被动接收、精确绑定响应正文；BrowserSkill 后端读取页面可见字段，明确字段质量与缺失值。两类观察进入同一 X 标准化与验证流程，不能把 CDP 响应字段冒充 BrowserSkill 能力。官方 API 只列为另行评估的数据源，不在本次双后端范围增加第三套实现。

### R3 / P1：X 示例在无结果时没有退出条件，取消后页面未清理

问题：原提案第 215–219 行仅以数量为循环终点，收尾不在 `finally` 中。

原因：没有截止时间、最大滚动次数、连续无新增判断、平台错误状态或异步响应任务收尾。

影响：空结果、重复页、登录失效或响应解析失败会持续滚动；异常、取消后残留页面及监听任务。离线模拟已复现 `empty_results=timeout`、`closed_on_cancel=False`。

推荐方案：请求级 deadline、滚动/观测预算、连续无新增终止、明确 end/partial/risk 状态；在 `finally` 里停止本次会话或归还本次借用的页。异常情况下保存已验证前缀，等待本次子进程退出后释放采集锁。

### R4 / P1：X 的记录身份、字段语义和接入范围尚不完整

问题：原提案把所有 `x.com/i/api/graphql` 响应一起解析，未绑定当前查询、操作或用户；示例字段也混用推文、被引用内容和作者层级。

原因：缺少外层记录与引用/转发的区分、用户名与用户数字 ID 的区分、分页及数据来源契约；`content_type` 被当作分辨率，媒体预览图被当作视频原文件。话题路径依赖未经证实的 `HashtagTimeline` 名称。

影响：可能混入其他查询、推荐、广告或被引用推文；可能重复计数、错绑作者、把未知指标写成完整值。`legacy.full_text` 也不能被无条件认定为长帖完整正文。

推荐方案：按第 4 节定义 X 记录；话题作为搜索条件复用同一实现，不新增猜测的 API 接口。新增 X 必须覆盖 Python 请求/平台路由/验证/历史、Node CLI/名单/进度/Excel、打包白名单和测试；不能只加一个 `scrape_x.py`。当前脚本实际在 `runtime/scripts/`，不在原提案列出的 `media-missher/scripts/`。

### R5 / P2：历史产物已清理，但旧安装入口、CI 和目录说明未同步收敛

问题：根目录仍存在 Harness `.command` 安装入口及包路径说明，实际 `harness-plugin/dist/` 已为空。

原因：上一轮仅移走 23 个包、校验文件、证据和模板，没有退役消费这些产物的入口。`Install Media@Missher Harness Plugin.command:5` 仍指向 0.6.0 包，历史 GitHub bootstrap 仍下载 15.2.1；CI 仍含 Bundle 打包及 tracked Setup 校验。

影响：双击现有 Harness 安装入口会报缺包；README 的“当前可安装包”描述不成立。只跑 Agent CLI 测试无法证明这些路径可用。已实际复现 package verifier 对 0.6.0 tgz 返回 ENOENT。

推荐方案：按第 5 节核定双后端开发副本实际保留的交付入口。废弃入口与测试、CI、说明一起退役；保留的 Harness 薄适配器必须能从当前源码重建包。不要为让旧测试通过而恢复所有历史产物。

### R6 / P2：Agent 构建仍依赖 harness-plugin，目录不能直接删除

问题：`agent-plugin/scripts/build.mjs:10` 起先构建 Harness，再复制其 `lib/index.js` 与 `payload`。

原因：名单导入、私有配置、运行控制、进度、Excel 和工具工厂都共用 `harness-plugin/src`。Agent 在运行时不要求 Harness，不代表它的源码构建已与 Harness 解耦。

影响：整删 `harness-plugin` 会令 Agent 构建和下一次更新失败；现有编译文件还能启动不能证明源码可重建。

推荐方案：由 DeepSeek 先把实际共用代码移入轻量公共模块并更新构建依赖、入口测试。CLI 与保留的 Harness 薄适配器消费同一实现，不复制第二套名单解析、验证或工作簿实现；只删除确认已废弃的宿主专用入口。

### R7 / P2：依赖软链接未被忽略，当前候选容易被错误提交

问题：`agent-plugin/node_modules` 是指向 `../harness-plugin/node_modules` 的软链接，但 `.gitignore:51` 的尾部 `/` 只匹配目录，不匹配这个软链接。

原因：依赖目录形态和忽略规则不一致；审查时 `git ls-files --others --exclude-standard` 列出了该链接，`git check-ignore` 未命中。

影响：宽泛 `git add .` 可能把开发机依赖链接纳入源码，也可能遗漏其他忽略的生成文件，从而制造“当前电脑可用、干净检出不可用”的基线。

推荐方案：统一依赖安装方式与忽略规则；检查 staged 清单后再建立候选提交。保持生成物、依赖与源码各自的边界。正式提交前同时确认 origin 的真实目标。

### R8 / P2：正式打包流程依赖测试写入校验文件

问题：`harness-plugin/scripts/build-setup.mjs:91` 要求现成的 `SHA256SUMS.txt`；`pack:bundle` 不生成它，写入逻辑却位于 `tests/setup-release.spec.ts:19` 的 beforeAll。

原因：生产打包和测试都向同一个 dist 写入，清理后缺少独立完整的构建链。

影响：直接从空 dist 执行 `pack:bundle → pack:setup` 会缺文件；运行测试反而重新写回工作区发布物。前轮清理不能算作构建流程已经收敛。

推荐方案：保留的打包流程自行生成并验证校验文件；测试只在自己创建的临时目录产出包。对空生成目录的干净构建做验收，避免依赖先跑测试。

## 3. BrowserSkill 升级方案

### 已核验的上游与版本

| 组件 | 本轮核验结果 | 开发基线 |
| --- | --- | --- |
| 本机 bsk CLI | `0.1.10`，只运行了 version/help | 升级另由实现阶段执行 |
| 本机已连接扩展 | 未实查 | 必须在实际宿主验证，不能从旧代码常量推定 |
| 官方 CLI | `cli-v0.3.0`，2026-09-17 发布 | 固定 0.3.0 |
| 官方扩展 | `ext-v0.3.0`，2026-09-16 发布 | 固定 0.3.0 |
| CLI/扩展共同 tag commit | `75e2c64abaf4b7cc75682d94b0c1fd5db0cbd5e5` | 对此版本开发并记录归档摘要 |
| 官方 DSH 插件 | `@wxg-prc-cpg/browser-skill-dsh-plugin@0.3.0` | 仅在需要原生 browser_* 工具时使用 |

本轮另核对了上游 main `907b455ea678b47a153491188dab30ca176ed404`，它比发布版更新；实现不要把 main 文档中新能力误算进 0.3.0。未安装/升级 bsk、扩展或 DSH 插件。

升级的实质收益：新版观测及引用身份处理、带预算的观测分页、wheel/scroll-to、会话取消及截图收尾。远程网关、Canvas 点击和操作录像不属于本轮采集需求。

0.3.0 改变了借用确认和人工接管设置：扩展保存的用户偏好生效，旧 `--unattended` / `--no-confirm` 不再能覆盖它们。先核验实际设置和返回结构，不能照搬旧桥接参数。

### 推荐实现边界

1. 保留现有 Python 控制器、顺序采集、共享锁、风险状态、记录验证与私有输出；封装 `cdp` 与 `browserskill` 两个后端。CDP 后端继续用 Playwright 连接明确配置的端点；BrowserSkill 后端通过 bsk 会话工作，不访问 CDP 端点。BrowserSkill 内部仍会使用 Chromium 调试能力。
2. Media CLI 是推荐的会话所有者：创建一次 session，明确选择 browser ID，保存 session/tab 身份，逐平台运行，最终只停止自己创建的 session。DeepSeek Harness 可以调用该 CLI 完成采集。
3. 若选择 DSH 原生 BrowserSkill 工具进行另一套 Agent 交互，则由该插件独占它创建的 session。官方插件拒绝外部 session；不能把 Media 自建 session ID 直接交给插件控制，也不能双向交替点击同一页。不要为了共享会话新增未经审查的私有接口。
4. 首版使用 `observe` 获取新鲜语义引用，必要时对目标卡片 `get-html`，本地确定性解析。尽量每个视口一次观察、一次成批提取，再去重；不要对每个字段单独调用模型/截全页图。
5. 允许动作保持很小：导航、观察、读取目标 HTML、wheel/scroll-to、一次精确详情点击、归还/停止。Cookie、storage、登录凭据、页面 fetch 拦截和任意网络重放均不纳入采集接口。CLI evaluate 即使存在，也不是首版所需能力。
6. 每次导航和 DOM 变化后刷新观察；过期引用先重新观察，已派发且结果不明的点击不重放。所有命令同时核对 exit code、JSON 错误结构、会话/tab 身份和超时。
7. 缺依赖、未连扩展、未登录、需要人工确认应给出固定可操作诊断；不要自动安装 BrowserSkill、借用用户已有页或降级成 CDP。采集只对用户选择的目标和范围执行。
8. 旧 XHS 的“complete 必须有当前详情响应证据”不能被 DOM 结果直接冒充。为页面采集增加明确的 evidence/capture 类型和字段质量；严格完整模式缺少所需证据时返回 partial/unsupported，保留旧格式读取能力。

9. 后端选择优先级：本次 `--backend` / 工具参数 > profile 保存的偏好 > 旧配置兼容默认 `cdp`。运行开始后冻结，写入请求、manifest、进度、续采绑定和 Excel 摘要；禁止 `auto` 静默切换。旧结果缺后端字段时按明确的历史 CDP 格式读取。
10. 共用接口只描述真实共有操作；响应正文捕获是 CDP 的显式 capability，不能让 BrowserSkill 伪造。CDP 模式不应要求 bsk 已安装；BrowserSkill 模式不应探测或要求调试端口。持久风险暂停与共享采集锁位于两后端之外，不能靠切换后端解除。
11. 本轮先支持同一后端内严格绑定的续采；跨后端续采给出明确不支持原因，不把不同证据等级的记录混成完整结果。旧 `browser-assist=browserskill` 混合控制路径应显式弃用或迁移，不偷偷映射为新独立 BrowserSkill 后端。

## 4. 新增 X 采集方案（替代原提案的实施部分）

### 目标、模式与请求

目标：对指定 X 主页或搜索结果，分别支持 CDP 响应观察与 BrowserSkill 页面观察，输出同一记录规范和 Excel，并如实标注后端与证据等级。

CDP 路线必须在页面操作前挂好监听，按精确 host/path、操作类型、当前页面/请求目标绑定响应，校验 HTTP 与 GraphQL 错误并处理异步任务收尾；只消费本次页面产生的响应，不在脚本中复制 Cookie/Token 或重放私有 API。BrowserSkill 路线使用当前 session/tab 的 observe 与必要的卡片 HTML，本地解析，不增加 Playwright 监听器。两条路线复用 X 标准化、去重、质量判定、验证和输出。

支持 **多用户主页任务、单平台搜索子任务**；话题复用搜索。一次计划可含多平台、多帐号，底层拆成目标明确的子任务并顺序执行。同一条搜索不把多个平台混成同一结果来源；不引入评论全文递归、后台定时、媒体下载或关注/点赞等写操作。

- 主页：接受用户提供的完整官方主页，区分 handle 和数字 author ID。固定账号目标；不能把主页推荐帖、引用内层作者或转发对象当成目标作者。
- 搜索：关键词做 URL 编码；明确 `latest`/`top`，建议默认 latest。记录查询、排序和采集时间，不把搜索排名当成时间顺序或“全量”。
- 话题：在同一搜索实现中构造 `#topic`；保留原始条件和编码结果，不假设存在稳定的 HashtagTimeline 接口。
- 请求包括 platform、mode、target/query、count、导航范围、deadline、滚动预算和 desired evidence level。新增字段应通过现有 CLI、profile、history/resume 和验证接口贯通，不能只在最底层脚本临时加参数。
- 第一轮单批工程预算可从 10 条、3 次加载滚动、连续 2 次无新 ID 则停止开始验证，并设置总运行期限；这些不是总采集上限或 X 官方安全阈值。用户选 best_effort 时按预算分批继续，直到自然结束、授权运行期限、取消或实际阻断；不能仍固定截在十条，也不承诺指定大数量必然完整成功。

### 记录和字段契约

| 类别 | 字段/规则 |
| --- | --- |
| 标识 | `platform=x`；`tweet_id`、`author_id`、会话/引用 ID 一律字符串；主键为平台＋tweet_id。数字 author_id 在页面无证据时为 null，不能用 handle 冒充 |
| 目标绑定 | canonical HTTPS `x.com/<handle>/status/<tweet_id>`，只接受核验过的官方主机；精确校验路径 ID 与当前外层卡片，不能仅做 substring 匹配 |
| 内容 | 与现有通用列兼容的 `title`/`date`/`author`/`link`，并保留 `text`、UTC `published_at`、`observed_at`、`text_complete`。长帖未展开必须明确截断；媒体帖可无文本 |
| 指标 | `liked`、`comments`（仅回复数量）、`shares`（转发）、`quotes`、`views`、`bookmarks`。收藏与书签只作同源别名，不统计成两个维度；浏览量不能当成视频播放量 |
| 质量 | 字段来源、原始显示值、观察时间和 exact/rounded/unavailable/truncated 状态。缺失保持 null；`1.2K` 不冒充精确 1200；明确显示的零才是零 |
| 作者 | handle、显示名和主页来自外层作者。粉丝数、简介、注册时间、认证类型等可选，不为每条帖额外访问主页。当前页面没展示的值不补猜 |
| 关系 | 记录普通帖、回复、引用、转发的类型及 referenced IDs；被引用帖不自动作为第二条结果。置顶帖和重复可见卡片按 tweet_id 去重 |
| 媒体 | 区分图片、视频预览图与原始视频。MIME 类型不是分辨率；拿不到宽高/播放地址/时长则 null。只输出页面已展示且可验证的链接，不自动下载 |
| 证据 | 绑定 run、request 摘要、browser/session/tab、页面 URL、采集方法、解析器版本和字段质量。截图仅在请求需要时保存，并绑定目标、时间、相对路径和摘要 |

基础模式是否成功，以其已声明的必需字段和数量为准；可选字段缺失应在字段质量中说明。用户要求完整字段、而能力只能读取基础字段时，必须给出 partial/unsupported，不能降低要求后报告完整。

### 数据流与停止条件

`解析并冻结 backend → 校验目标与能力 → 获取共享采集锁 → 建立选定后端会话 → 导航并核验页面身份/登录状态 → 有界观察与提取 → 独立验证/去重 → 保存已验证前缀 → 按预算滚动 → 写 manifest/Excel → finally 收尾并释放锁`。

- 风险/挑战/锁定/限流信号立即停止，不切换浏览器或自动重试。HTTP 状态只作为适用页面/请求的证据，不能从无关子资源错误推断全部结果。
- 空结果、停滞、超时、取消、页面换目标、会话丢失、截断和内容结构改变分别记录固定原因。
- 不依赖浏览器内长期累积未处理事件。每次观察确认当前 URL/tab，DOM 虚拟列表移除旧卡片后仍以已保存 ID 去重。
- 历史续采必须重新绑定目标、模式、数据来源、版本与保护状态；新抓和历史记录分开计数。保留共享安全状态，不能靠新的 runtime home、浏览器或账号消除原风险暂停。
- 输出沿用私有 run `0700`、文件 `0600`、原子落盘、公式转义及 ID 文本化。含 X 的全平台工作簿应有 Summary、All Platforms 和五个平台表；旧四平台结果仍保持兼容。增加 X 不得让旧 profile 在未选择 X 时自动抓取 X。
- 给 X 单独建立有界批次与持久风险暂停策略，不能假定只适用于 XHS 的 10 条/3 页/600 秒策略会自动覆盖 X；共享锁与风险存储的作用域应独立于后端选择。

### 原提案需要删除的结论

“X 对 CDP 检测较弱”“滚动 2–3 秒即可安全”“公开推文必然合规”都不是本轮可验证结论，不能作为产品保证。X 官方自动化规则明确限制非 API 网站脚本自动化；如果目标是持续、批量、完整数据的正式能力，建议采用官方 X API 路线并另行确定访问条件。BrowserSkill 页面路线按实验能力记录，本轮没有替用户接受平台风险或做真实采集。

官方 API 路线可复用记录/验证/输出契约，数据源独立为 `x-api`；用户时间线、搜索和分页有正式接口。不要拿这些公开 API 字段文档为私有 GraphQL 字段路径背书。当前不引入 API 凭据、付费配置或第二套实现。

## 4B. 多目标、大量采集、选择导出与微博话题补充

当前存在需要真实改代码的限制：`agent-plugin/bin/media-missher.mjs` 对 activate 的 rows 限制最多四项；`harness-plugin/src/setup.ts` 限制每平台一个帐号；profile 的 `platform_uids` 也是一平台一个值。当前 `runs` 导出接口没有帐号/字段/记录类别筛选，微博只有主页与关键词搜索，没有“话题发现用户 → 用户主页资料”流程。因此这些需求不能靠改 Skill 文案完成。

1. **交互和多目标**：开始时补齐缺少的平台、多个帐号/话题、后端和数量模式。已给定的内容不重复问；同平台允许多个帐号。采用带版本的多目标计划和子任务队列，兼容读取旧名单与 profile，目标快照和进度都要分到帐号级。
2. **best_effort**：用户说尽量多抓时，不设固定十条总数上限；有限批次、运行期限、分页/停滞检测、断点保存和取消共同限制执行。XHS 已有单批/间隔/风险策略保留，跨帐号和跨后端共享保护。可在同一授权期限内正常等待下一批，但风险停止不自动恢复。
3. **先采集、再选择导出**：本地证据自动保存，完成后展示统计和字段覆盖，再询问导出哪些平台/帐号/话题、帖子或用户资料、哪些字段、什么格式。已预先明确的导出要求直接执行；后续筛选重导出完全离线，不触发补抓。
4. **微博话题**：识别普通话题与超话；从可见话题帖子中提取外层发帖用户，按 UID 去重，再顺序采集其可见公开主页字段。同一运行一个用户主页只抓一次，保留多个话题/帖子的关系证据，不递归采其粉丝或全量发帖。
5. **数据与覆盖**：分别存帖子、用户主页、话题参与关系。参与者默认指已观察话题帖发布者，不包括未观察的浏览者/点赞者等；不宣称全部参与用户。未展示资料留 null、缩写指标留精度，主页失败保留来源和固定原因。
6. **验收新增项**：同平台多个 UID、超过四行选择、旧 profile 迁移、best_effort 超过十条的合成数据、预算暂停续采、跨账号保护、话题污染/引用作者过滤、主页运行内去重、字段选择导出及部分结果导出。

字段组、任务实体、全部测试要求以 `DEEPSEEK_V4_PROMPT.md` 为准。本轮未实现上述功能，未收集用户主页资料。

## 5. 清理顺序：先解除依赖，再删源码

| 对象 | 处理结论 | 必须满足的条件 |
| --- | --- | --- |
| `harness-plugin/dist/` 旧发布物 | 前轮已移走，23 个文件、3,112,664 字节 | 恢复位置为 `/Users/missher/.Trash/Media-Missher-browser-dist-20260920.N39GRy`；不要把旧证据算成新验收 |
| `.DS_Store`、测试缓存、临时构建目录 | 可清理并补齐忽略规则 | 确认是本目录产生的普通文件；不递归清理工作区根 |
| `agent-plugin/dist/`、两份 `lib/`/`payload/` | 可重建的候选产物，不能视为源码 | 保留至少一个已核验恢复包；代码变更后重新构建并核对源码对应关系 |
| `node_modules` | 开发依赖，可重建 | 实际必要依赖不是业务垃圾；锁文件保留，去掉它就不能声称完整 CLI/构建可直接运行 |
| 两个根 Harness `.command`、纯 Harness installer/setup/release 脚本 | Browser 专用分支的退役候选 | 同步清理测试、CI、README/AGENT 指引引用；保留通用 `install.sh`/`install.ps1` |
| `harness-plugin/src` | 目前不可整删 | 先抽出共用名单/配置/运行/进度/工作簿及工厂；保留的 Harness 工具层保持轻薄，实际退役入口再移除 |
| `openclaw-media-missher/` | 旧专用兼容包，可作为后续删除候选 | 同步调整 Python 安装器默认双 Skill 分支及相应测试；通用 Agent Skill 的 OpenClaw 目标是另一件事，不能一并误删 |
| CDP 实现及 Playwright 依赖 | 双后端正式功能，必须保留 | 可整理到 CDP 模块；仅在已被等价实现替代、测试和引用均迁移后删除重复旧文件 |
| 旧 BrowserSkill 点击辅助桥接 | 独立 BrowserSkill 后端完成后的退役候选 | 明确旧参数兼容/错误提示，消除双 owner；不能删掉仍需保留的 CDP 能力 |
| 历史计划与长交接记录 | 可归档并保留索引 | 原始证据不能改写为新版本；当前入口保持短，长历史不再默认全量读入 |
| `tests/`、fixtures、校验、安全/存储/续采、许可证 | 保留 | 回归防线和业务逻辑，不是多余产物 |

本轮只变更审查与工作区交接文档。源码删除由 DeepSeek 在对应阶段与依赖调整一起提交审查，避免“先删后发现构建仍引用”的重复返工。

## 6. 给 DeepSeek V4 的内部实施顺序与验收

以下是一次完整候选内部的实施顺序，不增加用户的协作步骤。DeepSeek V4 自行逐段推进并自测，最终统一交给 Codex 审改；用户没有要求逐阶段确认。完整可复制提示词见 `DEEPSEEK_V4_PROMPT.md`。

### 阶段 A：固定桌面基线和收敛入口

核实实际 dirty 内容、依赖链接、源/包摘要；按桌面路径更新入口，标清 CDP 已有能力与 BrowserSkill 独立后端待开发状态。优先修复 R0，修复忽略规则及测试/打包副作用，收敛失效安装入口和发布检查。保留四平台核心、测试与恢复能力。处理 Git origin 和最终提交时先复核目标，不向 Documents 原仓库误推送。

验收：干净依赖安装可重建通用 Agent CLI；帮助、版本、离线 doctor 与空名单状态正确；README 指向实际存在的入口；无依赖软链接误入 staged 文件；没有以删除测试掩盖错误。不要在这一阶段删除共享核心。

### 阶段 B：共享控制器与双后端适配层

封装现有 CDP 后端，新增 BrowserSkill 0.3.0 后端，贯通参数/profile/预检/manifest。实现精确版本/协议/能力检查、单 browser/session/tab 绑定、有界命令读取、JSON 错误、取消、单 owner 和最终收尾。用合成页面/命令 fixture 测试列表读取、滚动、过期引用、页面跳转、延迟、失联、输出超限和取消；再做本地静态页面的原生闭环。

验收：一次动作只有一个控制器；用隔离 fixture 模拟调试端点不可用时 BrowserSkill 仍可运行、未安装 bsk 时 CDP 仍可运行，不关闭用户的真实端口/进程做实验；无未经确认的 tab borrow；两后端失败均不自动切换；不会停止共享 daemon 或他人 session；未知版本/结构给出明确诊断。固定实际测试的 CLI/扩展版本。

### 阶段 C：X 基础采集闭环

按两后端能力分别实现 X 主页、单平台搜索与话题包装；补齐跨层 platform/目标/字段/输出/安装白名单。模型只选择任务，解析器确定性处理已观察数据。同一输入分别测试 CDP 响应与 BrowserSkill DOM 来源，明确字段差异。

验收 fixture 至少覆盖：空结果、固定数量上限、重复/置顶、无新增、长文截断、媒体无正文、引用/回复/转发、不同作者、不同查询、缺失值与零、缩写指标、大整数 ID、公式前缀、页面被改目标、登录墙、429/挑战、超时/取消、断点结果、五平台及旧四平台工作簿。

原生验收先本地页面；真实平台验收绑定明确主页/查询、数量和当前授权，建议从 1–3 条开始。分别报告字段完整性、实际数量、耗时、停止原因和私有证据路径；原提案的历史 24 条不抵本阶段验收。

### 阶段 D：原四平台双后端支持与清理

保留原四平台的 CDP 能力，为 BrowserSkill 补齐列表基础字段，再按证据能力处理详情、截图和评论等可选功能。共用核心抽离后，清理已失去引用的重复实现、旧辅助桥接和废弃分发入口。CDP 是长期后端，不作为垃圾删除。每次删除同时检查构建/测试/打包引用，原结果和用户配置可继续使用。

验收：各平台已支持的任务有自己的 fixture 和必要的真实样本；严格完整模式没有被悄悄放宽；原结果可读、风险状态和共享锁仍有效；依赖安装、CLI、配置、构建、私有输出和候选归档可复现。性能记录用同一输入比较耗时、动作数、输出字节和内存；不把“换成 BrowserSkill”直接等同于提速。

### 完整候选交给 Codex 的审核材料

分支、完整 HEAD、相对接手基线的 diff、变更文件与删除理由、执行过的测试命令/实际结果、未测范围、后端×平台×模式能力矩阵、依赖版本、原生/真实平台证据路径及已知限制。Codex 在同一目录审查并修正、验证；验证通过后按用户既有授权核对远程、提交并推送。Git 更新不自动包含公开仓库、打 tag 或发布 Release。

可直接给 DeepSeek 的起始指令：

> 在 `/Users/missher/Desktop/Media@Missher`，按 `DEEPSEEK_V4_PROMPT.md` 完成 CDP / BrowserSkill 双后端共存、X 采集与代码精简的完整候选。你负责开发和自测；完成后交给 Codex 审改与最终验证，再由 Codex 更新 Git。

## 7. 本轮验证记录与限制

- Python：禁外网 socket、允许 Unix socket；BrowserSkill 桥接、请求模型、浏览器、详情协调和验证器共 **186 passed**。
- TypeScript：config、creator-list、browser-setup、workbook、onboarding-gate 五个文件共 **227 passed**。浏览器测试为注入动作/本地回环服务，未启动真实浏览器或访问平台。
- Agent 原有 tgz：严格归档检查通过，**50/50 成员与桌面 Agent 打包目录逐字节一致**；SHA-256 `17b3789c94642069d635cb663b57e70412c00f0523d34c26e000c2de4b7d8ff0`；两份已编译 `index.js` 一致。它仍是旧 CDP runtime 候选。
- X 原示例：内存模拟空列表，外层超时才结束，取消后 `close()` 未调用；没有接触 X。
- 现有 Harness 0.6.0 包验证：复现 ENOENT，与前轮清理结果一致，未重新打包。
- `git diff --check` 在审查前通过。之前会话 Agent **33/33** 通过是同次桌面准备工作的已有证据，本轮未重复运行该全套。
- 之前 `browser-check` 返回的是 `browserIdentity=configured-external`，这是既有 CDP 连接检查，不能称为 BrowserSkill 已接通或专用 BrowserSkill session 已验收。
- 没有运行完整 Python/Bundle 总矩阵、没有本轮真实平台采集、没有 BrowserSkill 新版安装或真实会话、没有正式 runtime 升级、提交、push/tag/release。以上通过项不覆盖尚未实现的迁移和 X 功能。

可复查的本轮命令：

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --python 3.12 \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket \
  tests/test_runtime_browser_skill.py tests/test_runtime_models.py \
  tests/test_runtime_browser.py tests/test_runtime_detail_open.py tests/test_validation.py

cd harness-plugin
pnpm exec vitest run tests/config.spec.ts tests/creator-list.spec.ts \
  tests/browser-setup.spec.ts tests/workbook.spec.ts tests/onboarding-gate.spec.ts \
  --maxWorkers=1 --no-file-parallelism
```

## 8. 官方资料（2026-09-20 核验）

- [BrowserSkill CLI 0.3.0 Release](https://github.com/Tencent/BrowserSkill/releases/tag/cli-v0.3.0)；[扩展 0.3.0 Release](https://github.com/Tencent/BrowserSkill/releases/tag/ext-v0.3.0)。
- [0.3.0 changelog](https://github.com/Tencent/BrowserSkill/blob/cli-v0.3.0/CHANGELOG.md)：版本统一、交互/取消及用户设置变化。
- [0.3.0 network 协议](https://github.com/Tencent/BrowserSkill/blob/cli-v0.3.0/crates/bsk-protocol/src/tools/network.rs)：没有 response body 字段；[扩展 network 实现](https://github.com/Tencent/BrowserSkill/blob/cli-v0.3.0/apps/extension/src/tools/network.ts)。
- [0.3.0 DSH 插件说明](https://github.com/Tencent/BrowserSkill/blob/cli-v0.3.0/packages/dsh-plugin-browserskill/README.md)：工具范围、无 arbitrary evaluate、只操作插件自建会话。
- [0.3.0 使用 Skill](https://github.com/Tencent/BrowserSkill/blob/cli-v0.3.0/skill/SKILL.md)：会话/引用/借用/观测边界，作为外部参考，不覆盖本项目授权。
- [X 用户时间线](https://docs.x.com/x-api/posts/timelines/introduction)、[X 搜索](https://docs.x.com/x-api/posts/search/introduction)、[X 数据字典](https://docs.x.com/x-api/fundamentals/data-dictionary)、[X 分页](https://docs.x.com/xdks/python/pagination)。官方数据字典只用于字段语义校对，不证明私有 GraphQL 路径稳定或页面能取全字段。
- [X 自动化规则](https://help.x.com/en/rules-and-policies/x-automation)：原提案的无条件合规表述不可保留。
