# 2026-09-23 Astra 接入修复交接

用户已授权当前任务处理已发现的版本入口与指令冲突；原开发任务已结束。源码、候选包、验证和回滚依据见 [Astra 迁移记录](docs/ASTRA_MIGRATION_2026-09-23.md)。工作仍在 Desktop 开发目录，保留既有未提交实现；下方历史暂停和测试数字不覆盖本轮范围与结果。

当前模型由宿主选择，项目通过 Skill/CLI 使用共享运行时。用户确认 15.6.0 后，本机正式 Codex Skill/runtime 已同步升级至 15.6.0；Agent 0.1.0 / Bundle 0.6.0 仍为已验证候选，未正式安装。真实平台、Harness/OpenClaw 正式安装与 Git 操作仍按原约定暂停。CU 实际宿主和未完成模式维持原限制。

当前源码修复、候选交付和本机 Codex 正式升级已完成。最终 Harness 与 Agent 归档均通过隔离安装；历史选择导出的独立进程模块路径错误已修复并加入两种布局回归，相关 Python 108 项通过。正式升级沿用原子安装器，Skill/runtime/venv 发布标记一致；离线预检、实际安装入口导出与桌面内置 Codex 的 Skill 发现通过。旧版三份恢复目录及配置/历史/风险状态保持完整。恢复路径与日志见迁移记录中的正式安装章节；不可直接以通用 CLI 同名 Skill 强制覆盖。

---

# 2026-09-20 新交接：跨 Agent / DSH 共用，恢复实现

最新阶段结论：监督已接受下述稳定候选，源码保持不变。只读 DSH 核验完成；当前 Codex/全局 CLI 无法提供活动 provider/Session/window 映射，等待 [DSH 当前会话最小只读回传](docs/DSH_CU_READONLY_GAP_2026-09-20.md)。未实现的多目标/主页/visual 核心工作和宿主格式依赖分开列出，不误写为仅差实测。平台、正式安装和 Git 继续暂停。

稳定候选：见 [离线候选验收记录](docs/CDP_CU_OFFLINE_ACCEPTANCE_2026-09-20.md)。源码聚合 `2b5ded9536c0801170f6fb3e1e054484bce726ae4272e41f339bd8f90d7e75ac`，Agent 包 `025def52…` 已完成对应隔离安装。Python 1295、Harness 293、Agent 54 全套通过。CU 多目标/微博主页/visual 仍未实现，真实 DSH 映射仍阻断，不得扩张为整体完成。

当前处于实现与迁移回归阶段，不是最终验收。BrowserSkill 执行模块已退出；当前 DSH Computer Use 仍不可用，核心准入限制为单一 X accessibility 观察。多目标/微博主页/纯图像模式不冒充支持。Node→Python 固定摘要、调用预留/迟到风险、共享租约与持久风险已有离线回归；全套、重新构建、隔离安装及平台字段/导出收尾仍需按计划完成。用户指定后续默认验收话题为“萤火虫漫展”，不撤销真实平台暂停或已有微博 challenge 风险停止。

用户已授权“各种 Agent、DSH 都能使用，你看着改”。继续遵循 [升级规格](docs/CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md) 和 [实施计划](docs/superpowers/plans/2026-09-20-cdp-computer-use-upgrade.md)，已补宿主无关协议、通用 capabilities/Computer Use CLI、DSH 薄适配、共享计划/导出一致性和无 DSH 依赖验证。原开发任务是唯一源码写入者，监督任务只改规划并审查；代码实现、离线测试、本地构建和隔离验证恢复，真实平台、正式安装升级和 Git 仍暂停。下文暂停记录是历史，不能误阻断已授权开发，也不能被用于恢复未授权平台操作。

---

# 2026-09-20 最新规划交接：仅保留 CDP 与 Computer Use

用户现已要求生成只保留 CDP / Computer Use、包括 X 追加的升级规划。交付为 [升级规格](docs/CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md) 与 [实施计划](docs/superpowers/plans/2026-09-20-cdp-computer-use-upgrade.md)，已更新 AGENTS/README/PROJECT_CONTEXT 入口并标记旧提示词失效。此轮未修改运行源码、未恢复开发或实测，未安装、提交或推送。后续以 CDP 默认独立可用、Computer Use 可选、BrowserSkill 退出运行链且旧数据只读为方向；执行前等待用户恢复指令。

---

# 2026-09-20 Codex 修复收尾与暂停

用户最新要求：改完当前修复后暂停，等待其查看新版 DeepSeek Harness Computer Use。当前不是完整项目验收通过。详细修改、冻结源码身份、最终离线结果、真实 challenge 停止和未验收项见 [暂停交接](docs/CODEX_REPAIR_PAUSE_2026-09-20.md)。禁止自动继续采集、适配、升级或提交推送；下方既有记录保留为历史，不能覆盖本节。

---

# Media@Missher 15.6.0 / Agent CLI 0.1.0 / Bundle 0.6.0 交接 — 2026-09-20

本节为当前状态，下方历史证据保持原样。工作目录为本机桌面副本，分支 `codex/media-browser-agent-desktop-20260920`，HEAD `f87dd8858a0b888f03a7885a1641823af13457bd`，产品版本仍是 15.6.0 / Agent CLI 0.1.0 / Bundle 0.6.0。**本轮所有修改尚未提交，不存在最终发布 SHA，未 push、未打 tag、未发布 Release。** 桌面副本的 `origin` 仍指向本机 Documents 原仓库，Codex 更新 Git 前必须重新核对真正远程。

本轮按 `DEEPSEEK_V4_PROMPT.md` 完成 CDP / BrowserSkill 双后端共存、X 采集、多平台多帐号、`best_effort`、微博话题参与用户与主页采集、以及采集后选择性导出的完整候选。Codex 负责审改与最终验证；有真实验证缺口的部分在下方“待真实验收”明确保留。

## 1. 接手基线与本轮变化

| 项目 | 接手时 | 本轮结束时 |
| --- | --- | --- |
| 分支 | `codex/media-browser-agent-desktop-20260920` | 同左，未变 |
| HEAD | `f87dd8858a0b888f03a7885a1641823af13457bd` | 同左，未提交 |
| 产品版本 | HEAD 15.2.1；磁盘候选 15.6.0 / Agent 0.1.0 / Bundle 0.6.0 | 同左 |
| `origin` | 本机 Documents 原仓库（本地文件路径，不是 GitHub） | 未变，未 push |
| 已跟踪改动 | 66 个文件（接手前已有） | 78 个文件，+4414 / −1182 |
| 未跟踪新文件 | 73 项 | 77 项（含本轮 11 个新源码/测试文件） |

接手前已有的 dirty 内容全部保留；没有执行 `reset`、`checkout --` 或 `clean`。桌面副本早前已删除的 `harness-plugin/dist` 23 项仍在原位删除状态，本轮没有恢复它们。

## 2. 架构与数据流

`Agent 收集意图 → 版本化 CollectionPlan / 多目标队列 → 共享调度与安全门 → 冻结 backend → 平台/模式解析器 → 统一标准化与验证 → 私有存储/检查点 → 导出选择与投影`

**后端选择（每个运行冻结一次）**

- 优先级：本次显式 `--backend` > profile 保存的偏好 > 旧配置兼容默认 `cdp`。
- `auto` 被明确拒绝（`backend_auto_unsupported`）；失败不会静默切换后端。
- backend 写入 `plan.json`、`run_manifest.json`、进度与导出摘要，续采按同一后端绑定。
- `cdp` 沿用现有 Playwright 连接与被动响应观察，**不要求安装 `bsk`**。
- `browserskill` 通过 bsk 会话工作，**不探测也不要求 9222/9223 调试端口**。
- 旧 `--browser-assist browserskill` 混合控制桥接已退役：`CollectionRequest` 仍保留其历史形状，CLI 边界以固定 `media-missher-diagnostic ... code=browser-assist-replaced` 拒绝并返回 78，不再静默改变参数含义。

**新增运行时模块**

| 模块 | 职责 |
| --- | --- |
| `runtime/media_missher_runtime/contracts.py` | 版本化 `CollectionPlan` / `Target` / `TaskState` / `RunManifest`、后端归一化、停止原因、记录类别、字段分组 |
| `runtime/media_missher_runtime/capabilities.py` | 后端 × 平台 × 模式 × 能力矩阵；`require_task` 拒绝无法执行的任务 |
| `runtime/media_missher_runtime/bsk_session.py` | bsk 会话所有权、固定 JSON 错误结构、版本/协议与 skew 检查、只停止自建会话 |
| `runtime/media_missher_runtime/bsk_page.py` | 受能力约束的页面外观；不支持的操作以 `CapabilityError` 明确拒绝，绝不伪造 |
| `runtime/media_missher_runtime/extraction.py` | 有界、确定性的 DOM 提取器，两个后端共用 |
| `runtime/media_missher_runtime/batch_policy.py` | 各平台有限批次预算（XHS 保持 10/3/600） |
| `runtime/media_missher_runtime/best_effort.py` | 分批循环、去重、停滞判定、期限、检查点、取消保留前缀 |
| `runtime/media_missher_runtime/plan_runner.py` | 顺序多目标任务队列、风险全局停止、运行内用户主页去重、清单生成 |
| `runtime/media_missher_runtime/exporting.py` | 离线选择导出（xlsx/csv/json/jsonl/sqlite）、字段组、上限分文件 |
| `runtime/media_missher_runtime/platforms/x.py` | X 采集：响应路线与页面路线共用一个标准化流程 |
| `runtime/media_missher_runtime/platforms/weibo_topic.py` | 话题核验、参与用户、公开主页记录与关系 |
| `harness-plugin/src/plan.ts` | Harness 侧冻结计划与目标解析 |

**配置与历史兼容**

- profile 新增权威 `targets[]` 数组（同平台多帐号）；`platform_uids` 与 `creator_targets` 保留为 version 1 兼容视图，永远不回退覆盖 `targets`；无法表达多帐号的旧 profile 只读兼容。
- `CollectionRequest` 只新增可选字段；旧请求形状、旧 manifest 与旧历史结果读取保持不变。
- `storage.PLATFORMS` 只扩到五个平台名，manifest schema 本身未变。

## 3. 后端 × 平台 × 模式能力矩阵

证据等级只有两级：`response`（能读取页面自身产生的响应正文）与 `page`（只能读取当前会话/标签页真实渲染的内容）。矩阵在 `capabilities.py` 中显式维护，重复且冲突的定义会直接报错。

| 平台 | 模式 | cdp | browserskill |
| --- | --- | --- | --- |
| bilibili | creator / search | full：列表、详情、响应正文、页面观察、目标 HTML、截图、基础媒体 | basic：列表与页面观察；详情/截图/正文/媒体 absent |
| xhs | creator / search | full：同上 | basic：列表与页面观察；详情/截图/正文/媒体 absent |
| douyin | creator / search | full | basic |
| weibo | creator / search | full | basic |
| weibo | topic | full：话题帖 + 可见公开主页字段 | full：话题帖 + 可见公开主页字段（page 证据） |
| x | creator / search / topic | full：响应正文 + 页面观察 + 基础媒体 | full（页面）/ basic（详情）；`response_body` absent |
| 任意 | topic（非微博） | 拒绝：`topic-unsupported-platform` | 同左 |

真实可得 vs partial/unsupported 的关键一条：`bsk network` 只有响应元信息、没有响应正文，DSH BrowserSkill 插件也没有任意脚本能力。因此小红书 complete/detail、精确互动数、评论正文与截图，以及 X 的响应字段，在 `browserskill` 后端下是**明确不可得**，不是“字段为空”。矩阵据此拒绝，不降级伪装。

## 4. 实际执行的命令与测试结果

Python（每次都使用固定的离线 wrapper）：

```sh
export PATH="$HOME/.nvm/versions/node/v25.6.0/bin:$HOME/.local/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --python 3.12 \
  --with pytest --with pytest-asyncio --with pytest-socket \
  --with-requirements runtime/requirements.lock \
  python -m pytest -q -p no:cacheprovider --disable-socket --allow-unix-socket tests/
```

- 接手基线：**1102 passed / 3 failed**（3 项均为接手前就存在的失败：`__pycache__` 残留、`PROJECT_CONTEXT.md` 个人绝对路径）。
- 本轮结束：**1273 passed**，0 failed，0 error，0 skipped；唯一警告是既有 `test_security.py` 的 pytest-socket 提示。
- 其中新增测试：`test_runtime_contracts.py` 64、`test_runtime_exporting.py` 24、`test_runtime_plan_runner.py` 33、`test_runtime_bsk_page.py` 28、`test_runtime_x_topic_collectors.py` 14。

TypeScript / Harness Bundle：

```sh
cd harness-plugin && ./node_modules/.bin/tsc --noEmit
cd harness-plugin && ./node_modules/.bin/vitest run --maxWorkers=1 --no-file-parallelism
```

- 接手基线：**287 passed**（`setup-release.spec.ts` 因缺少 `pnpm` 报 suite 级错误）。
- 本轮结束：**287 passed / 17 files**，`tsc --noEmit` 干净。
- 打包路径端到端实测（在 `/tmp` 中进行，`harness-plugin/dist` 未被写入）：`npm pack` 产出 `dsh-media-missher-0.6.0.tgz` 333081 字节，`verify-package.mjs --write-checksum` 返回 `sha256 0f967f97703c1ad6229b7929366ee72d235e03d12a1c460055e21bc4dba82a50` 并自行生成、自行复核 `SHA256SUMS.txt`。

Agent CLI：

```sh
cd agent-plugin && node --test tests/*.test.mjs
```

- 接手基线 **33 passed**；本轮结束 **51 passed / 0 failed**（新增 `tests/targets.test.mjs` 11 项与 7 项 CLI 用例）。

`harness-plugin/dist` 在整个 vitest 全量运行前后逐字节未变（运行前为空目录，运行后仍为空目录，`git status` 的删除行完全一致），测试不再向工作区写 `SHA256SUMS.txt`。

**离线 / 本地浏览器 / 真实平台的分层说明**

- 离线（本机，无浏览器、无网络）：上述全部 1273 + 287 + 51 项，全部通过。
- 本地浏览器：本轮**没有**启动真实浏览器。`browserskill` 会话、CDP 连接与真实页面均在 fake/injected 层验证。
- 真实平台：本轮**没有**任何真实平台请求。开发提示词没有指定真实帐号/话题/查询与授权范围，因此没有用默认 profile 自动开始真实采集。

另外做了一次真实的端到端选择导出探针（临时目录、临时 HOME、不触碰真实 profile 与运行目录）：用 `write_context` 写出标准 run 后，`manage_runs.py export --record-kinds posts --format csv --fields mblog_id,liked,media_width --platforms weibo --topics 旅行` 返回 `rows 1`、`counts {"posts": 1}`、`missing_fields ["media_width"]`，产出 CSV 为 `5001,3,`——ID 文本化、未采集字段明确报告而不是补抓、话题筛选生效、父run 与观察时间写入 metadata sidecar。

## 5. 样例启动与调用方式

**Agent CLI（独立使用，不依赖 Harness）**

```sh
# 名单导入与选择：同一平台可以选择多个帐号，不再限制四行
node agent-plugin/bin/media-missher.mjs setup import --file /absolute/creators.xlsx
node agent-plugin/bin/media-missher.mjs setup activate --import-id import-… --rows 1,2,7 \
  --target 'weibo:topic:旅行' --target 'x:search:latest:ai'

# 多帐号 + 尽量多抓 + 显式后端
node agent-plugin/bin/media-missher.mjs collect \
  --target 'weibo:creator:12345' --target 'weibo:creator:67890' \
  --target 'bilibili:creator:123456' \
  --backend cdp --count-mode best_effort --run-deadline 1800 --allow-navigation

# 采集后离线选择导出（不重新开浏览器）
node agent-plugin/bin/media-missher.mjs runs export --run-id run-… \
  --record-kinds posts,topic_participants,user_profiles \
  --platforms weibo --fields tweet_id,text,liked --format xlsx
```

**Harness 工具**

- `media_missher_setup`：`status` / `template` / `import` / `activate`（`rows` 可与 `targets` 并用，支持同平台多帐号）/ `browser-check` / `browser-open`。
- `media_missher_collect`：新增 `targets`、`count_mode`、`backend`、`run_deadline_seconds`；`platforms` 支持 `x`。
- `media_missher_runs`：`list` / `export`（`record_kinds`、`platforms`、`topics`、`targets`、`fields`、`field_groups`、`format`、`file_name`、`overwrite`）/ `compare` / `xhs-status` / `progress`。

**运行时刻意拒绝、绝不伪造的路径**（各返回一条固定诊断）

| 场景 | 诊断 code |
| --- | --- |
| 旧的 `--browser-assist browserskill` | `browser-assist-replaced` |
| 冻结后端无法执行该平台/模式 | `platform-collector-missing` / 具体能力码 |
| 超话输入 | `topic-container-unsupported` |
| 非微博话题 | `topic-unsupported-platform` |
| 目标没有可核验身份 | `target-identity-missing` |
| 计划执行器缺失 | `plan-executor-missing` |
| `--exclude-file` 与 `--targets-json` 并用 | `exclude-file-plan-unsupported` |

## 6. 当前产物与源码摘要

- 源码：78 个已跟踪文件被修改（+4414 / −1182），77 项未跟踪（含本轮新增的 11 个源码/测试文件与既有未跟踪文档）。
- 新源码 11 个：`contracts.py`、`capabilities.py`、`bsk_session.py`、`bsk_page.py`、`extraction.py`、`batch_policy.py`、`best_effort.py`、`plan_runner.py`、`exporting.py`、`platforms/x.py`、`platforms/weibo_topic.py`；Harness 侧新增 `harness-plugin/src/plan.ts`；Agent CLI 侧新增 `agent-plugin/src/targets.mjs`。
- 新测试 5 个：`tests/test_runtime_contracts.py`、`tests/test_runtime_exporting.py`、`tests/test_runtime_plan_runner.py`、`tests/test_runtime_bsk_page.py`、`tests/test_runtime_x_topic_collectors.py`；`agent-plugin/tests/targets.test.mjs`。
- 依赖：`runtime/requirements.lock` 现为 `playwright==1.45.0` + `openpyxl==3.1.5`（Excel 导出需要）。安装器从同一个 lock 安装，无需额外步骤。
- 生成物：`harness-plugin/{lib,payload}` 与 `agent-plugin/{lib,payload}` 已按当前源码重新 stage；`harness-plugin/dist` 保持接手前的删除状态，本轮未重新打包发布物。
- 本轮删除：根 `Install Media@Missher Harness Plugin.command`、`harness-plugin/scripts/build-setup.mjs`、`harness-plugin/scripts/verify-setup.mjs`、`harness-plugin/tests/setup-release.spec.ts`（连同 `.gitignore`、CI 与文档引用）。删除理由：这些入口消费的发布物早已清空，双击必然缺包；保留的 Bundle pack/verify 路径（`pack:bundle` → `verify:package`）与 Agent CLI 仍可端到端重建。

## 7. 已知问题与限制

1. **真实平台与真实浏览器未验收。** 没有真实 CDP 页面采集，没有真实 `browserskill` 会话。`bsk` 在 PATH 上的是 **0.1.10**，与本轮固定的 0.3.0 / protocol 1.0 设计基线不一致；`bsk status` 报 `extension 0.3.0 / extension_protocol 1.3 / version_skew true`。`BrowserSkillSession.preflight()` 对这种组合返回 `bsk-incompatible`，即**显式拒绝而不是静默接受**——这正是设计意图，但意味着真实 `browserskill` 采集在升级到一致版本之前不可用。
2. **X 的 GraphQL 结构与真实页面选择器未经真实页面证实。** 两个路线都用 fixture 与合成响应验证；操作名（`SearchTimeline`、`UserTweets`、`TweetResultByRestId`）与 DOM 标记视为待 fixture 证实的结构，不作为稳定公开 API。
3. **平台解析器细节待真实样本复核。** 微博话题页与主页提取器覆盖公开可见字段，但真实页面的类名变化会需要更新选择器。
4. **`--count-mode best_effort` 的期限与批次语义只在合成层验证。** 真实等待 600 秒的 XHS 合法下一批没有实跑。
5. **`plan_runner` 的清单是 `run_manifest.json`（`contracts.RunManifest`），不是四平台严格 `manifest.json`。** 计划路径与旧单请求路径的产物名不同；Codex 需要确认 Harness 工作簿是否需要统一。
6. **继承的历史文档仍有旧描述。** `PROJECT_CONTEXT.md` 中被取代的段落已标注“历史（已被 2026-09-20 候选取代）”，`docs/superpowers/*` 与 `docs/releases/*` 作为历史记录保留，不改写为新版本。
7. **`agent-plugin/dist` 仍是旧 CDP 实现产物**，本轮没有重新打包 Agent Setup；源码与 lib/payload 已同步，但分发包需要在发布时重新构建并核对哈希。
8. **`.gitignore` 的旧 dist 反忽略规则仍在**（历史发布物名），本轮只移除了随 Setup 入口一起退役的 7 条；`SHA256SUMS.txt` 与 `Media-Missher-Harness-Setup-v15.2.1.zip` 的反忽略保留，因为保留的 GitHub bootstrap 仍按 Release asset 名引用它们。

## 8. 待真实验收内容

以下各项在本轮**未执行**，需要明确帐号/话题/查询、数量与当前授权后才能做，不能用合成结果代替：

1. `bsk` CLI/扩展升级到 0.3.0 一致版本后，用真实会话跑一次 `--backend browserskill` 的小批量采集（建议 1–3 条），报告字段完整性、实际数量、耗时、停止原因与私有证据路径。
2. `--backend cdp` 对 X 主页与搜索各跑一次小批量，核对响应绑定、字段质量与去重。
3. 微博普通话题一次真实运行：话题帖数、去重用户数、主页完成/失败数、关系记录与导出。
4. 同平台多帐号一次真实运行，核对每个帐号的实际数量与去重后总量。
5. `best_effort` 一次跨批次的真实运行，核对预算暂停、期限、检查点续采与风险停止。
6. 五平台工作簿（Summary / All Platforms / 五个平台表）真实数据核对。

## 9. 回滚方法

- 本轮没有任何提交，因此回滚只需 `git checkout -- <path>` 恢复已跟踪文件、并删除本轮新增的未跟踪文件；**不要**执行 `git reset --hard` 或 `git clean -fdx`，工作区含接手前的大量未提交候选内容。
- 旧 Harness dist 23 项位于本机废纸篓中的 `Media-Missher-browser-dist-20260920.N39GRy`，需要时从这里恢复。
- `harness-plugin/{lib,payload}` 与 `agent-plugin/{lib,payload}` 是可重建产物：`cd harness-plugin && node scripts/stage-payload.mjs` 与 `cd agent-plugin && node scripts/build.mjs` 可重新生成。
- profile 迁移前 `setup activate` 会写出 `setup/backups/profile-<nonce>.json` 备份；旧 profile 不会被覆盖。

## 10. 交接给 Codex

本轮不 push、不改 tag、不公开仓库、不发布 Release。Codex 审改与验证通过后，依据用户既有授权**重新核对真正的 Git 远程**再提交、推送。第 7、8 节列出的真实平台、真实浏览器与版本一致性缺口应作为审改的一部分明确保留，不能提前宣布 Git 版本已交付。



---

# 历史：Media@Missher 15.5.0 / Bundle 0.5.0 交接 — 2026-09-08

本节为当前状态，下方内容保留为历史证据。候选位于 `.worktrees/xhs-reliability-20260907`，分支 `codex/media-xhs-reliability-20260907`，基线 `f87dd8858a0b888f03a7885a1641823af13457bd`。源码未提交，没有最终发布 SHA。用户确认“正常更新，程序最终面向 Agent 安装后使用”；已作为工具描述和可选原生指引保留，没有另建交付流程。

已完成：同 HOME 跨 runtime 共享采集锁及小红书风险/冷却，保留已登记旧锁与状态；预检/采集统一安全 VERSION 门槛；固定阶段进度、私有快照、结果耗时；系统 Python 引导选择 3.11/3.12，安全复用现有兼容 venv，并只在暂存区重建不兼容环境。新设备仍需 Excel/CSV 导入、预览选择，再按用户明确意图开独立 AI 浏览器和手动登录；空设备不自动 CDP/安装/采集。版权声明继续归 Missher，保留第三方许可。

核心改动：runtime/media_missher_runtime/{shared_safety,xhs_policy,progress,cli}.py；media-missher/scripts/{media_missher_adapter,media_missher_progress}.py；tools/install_media_missher.py；harness-plugin/src/{agent-guidance,process,progress,runtime,index,runs,workbook}.ts；版本、使用文档、验证脚本和对应回归。详细设计/计划在 docs/superpowers，产品说明在 docs/SHARED_SAFETY_15.5.0.md。

验收：Python **1105 passed** / 1 个有意验证禁网门槛的警告；Bundle **283 passed / 18 files**；TypeScript、残留扫描、diff check 通过。共享保护和进度均完成独立规格/质量复核。Python 3.14.7 引导实际普通新装自动选 3.11.15、安装真实固定依赖通过；仅现有兼容 venv 的普通重装与实际离线 preflight 通过。真实 Harness **0.5.5** 隔离安装、激活、入口导入、同版本重装备份、三个工具、名单导入选择、progress、历史、卸载通过；工作簿 40 条/六表和阶段输入是合成数据，原生指导服务通过注入服务 fixture 验证，不冒充 LLM 行为验收。

**40 个 payload、2 个编译文件与最终源码逐字节一致，29 个实际安装核心 payload 一致。** 正式 profile、15.2.1 runtime、XHS 状态、Chrome LaunchAgent 哈希未变，真实 HOME 尚无新版共享目录。六个旧归档和空模板哈希未变。15.4.0 早前真实四平台 4/4 仍属于旧版；15.5.0 没有再次请求平台或实际启动浏览器。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| dsh-media-missher-0.5.0.tgz | 247265 | 4e18b57c55e2c996d431b09ef5d8707146352cce353b397fc64cabd9252bae33 |
| Media-Missher-Harness-Setup-bundle-v0.5.0.zip | 268255 | 76a588ae85cd827f1cb9dd1060c5ffce21d0067f3ce450efcbe437ac8add8383 |

当前校验文件 SHA256SUMS.txt / SETUP-SHA256.txt 绑定 0.5.0；完整分层证据和实现文件摘要在 harness-plugin/dist/SHARED-SAFETY-EVIDENCE.json。当前支持 macOS；同用户 HOME 以外及未知旧客户端不自动受新共享保护。阶段快照不是存活探针，嵌套耗时不能相加。正式安装、公开源码方式及发布由用户后续授权；本轮未提交、推送、打 tag、公开或覆盖正式 profile。

已于 2026-09-08 按既有授权调用 send_message_to_thread 通知任务 `【DSH】Media@Missher`（`01a07766-9fe2-7da1-9809-7437205e41c5`），工具返回相同任务 ID，无错误。通知结果记录在 SHARED-SAFETY-EVIDENCE.json。主 checkout 当前新增的未跟踪 AGENTS.md 已读取并保留，本轮没有编辑它。

---

# 2026-09-08 实测补充

用户已选择四个平台各 1 条。用原 15.4.0 候选的隔离正常安装和真实浏览器完成 **4/4 成功，81.855 秒，无风险/超时**；小红书详情完整性通过。原 Bundle 投影代码生成并重读私有 Excel，6 表 4 条。原正式运行时仍为 15.2.1，profile 不变，未更换浏览器或放宽风控。测试驱动同时持有原环境锁并保留同一 XHS 状态；这不代表产品已经实现跨 runtime 的浏览器统一锁。

今天另跑 **217 Python + 44 Bundle 专项通过**，候选源码和历史包没有变化。完整实测边界、私有证据目录及升级建议见 `docs/LIVE_ACCEPTANCE_2026-09-08.md`。建议依次补齐共享浏览器安全状态、预检/采集统一版本校验、阶段进度与耗时。版本提示问题已在本地复现，无额外平台采集；这些升级本轮仅评估，未实施。下方 2026-09-07 的“未做真实采集”只描述当时证据。

---

# Media@Missher AI 浏览器与版权交接 — 2026-09-07

当前本地候选为产品 **15.4.0 / Bundle 0.4.0**，位于 `.worktrees/xhs-reliability-20260907`；分支 `codex/media-xhs-reliability-20260907`，基线 `f87dd8858a0b888f03a7885a1641823af13457bd`。本节覆盖旧版现状表述；下方 0.3.0 / 0.2.0 及原有归档、证据保持历史用途。源码尚未提交，没有最终发布 SHA。

用户授权补齐新设备完整引导，并明确要求版权归自己、禁止未经许可修改与二传，完成后通知任务 `01a07766-9fe2-7da1-9809-7437205e41c5`（`【DSH】Media@Missher`）。实现流程为：Excel/CSV 模板 → 导入预览与选择 → 用户明确打开独立 AI 浏览器 → 用户手动登录 → 本地连接/平台页面检查 → 按已有授权做采集前检查与首批采集 → 展示 Excel、计数和失败原因。新设备无名单时保持空闲；setup status/import/activate 和 collect 均不自动打开浏览器。

新增 `browser-setup.ts` 与 setup 的 browser-open/browser-check。专用 Chrome 使用私有 profile 同级的 `browser/chrome-profile`、本地端口 9223、当前会话摘要所有权标记。只打开静态本地欢迎页；四平台官方入口由用户点击。检查只访问本地 CDP version/list，不返回 Cookie、页面正文或会话地址，不把页面存在称作登录成功。复用时验证所有权，冲突保留现有进程；成功后逐字节备份原 profile 并原子更新 cdp_url。CLI 取消会释放共用配置锁。macOS 标准 admin 组 0775 Chrome 安装可被识别，其他组写入或世界写入仍拒绝。

新增根 `LICENSE`、`COPYRIGHT.md`、`THIRD_PARTY_NOTICES.md`：© 2026 Missher，原创部分采用专有授权，未经许可禁止修改、衍生、重打包及二传；保留第三方许可、法律例外和此前有效授权。声明随 Bundle、Setup 和新装 runtime 交付，Git 安装也会复制到技能 references。14 个随 DTS 合并的 SDK 包保留原 MIT 声明。作者与许可写入 manifest、编译入口和欢迎页。此为版权/许可声明，不是著作权登记；交付的 Python/JS 仍可被技术上复制或改动，不能承诺绝对防复制。未来公开方式由 Missher 另行决定，公开 GitHub 源码存在平台内 fork 授权边界，详见 COPYRIGHT.md。

最终 Python **1066 passed**（1 个预期 socket 阻断警告，121.24 秒）、Bundle **272 passed / 16 files**（38.68 秒）、TypeScript 通过。最终 Git 版权复制修订后，打包/来源回归 **3 passed / 2 files** 并重建归档。真实 Harness **0.5.5** 在隔离 DSH_HOME 完成安装、入口导入、激活、同版本重装备份、CSV/XLSX 名单导入、浏览器动作注入验证、离线历史工具、合成 40 条/六表工作簿和卸载。该 Harness smoke 没有实际启动 Chrome，其浏览器流程使用注入 fixture。

单独真实 Chrome **152.0.7977.76** 验证通过：临时独立目录、启动一次、只加载一个本地欢迎页、复用同一会话、备份原配置、报告缺平台页且 loginStatus=not-checked；测试进程组与临时目录已清理，9223 已关闭。它只证明本机 Chrome 引导可运行，没有平台导航、登录或采集。复现命令为 `pnpm run smoke:browser -- --confirm-open`，默认测试不会执行此命令。小红书既有批次上限、600 秒间隔和持续风险暂停保持，不能据离线验收承诺规避平台风控。

增量独立源码复核通过，CLI 取消及文案问题已修复；真实启动另发现并修复 Chrome 权限误判，Git 回归发现并修复旧兼容技能缺 references 目录。旧 0.3.0 名单解析器的最终独立复核曾被自动工具内容审核拦截，该历史限制仍保留；本次浏览器/版权增量复核不代替那项结论。正式安装或发布前仍需完成相应复核和真实账户验收。

最终 **37 个 payload 文件及 2 个编译入口与源码逐字节一致**，0.2.0/0.3.0 归档及空模板哈希未变。分层证据：`harness-plugin/dist/AI-BROWSER-EVIDENCE.json`；使用说明：`docs/NEW_DEVICE_15.4.0.md`；新 Agent 完整契约：`harness-plugin/AGENT.md`。实现文件集合摘要为 `99eb51394bed8c770c6b3e6b75770c7ca8b3375f69da446baf74fea90fe045bc`，不是提交 SHA。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `dsh-media-missher-0.4.0.tgz` | 234734 | `2ac0780eb8a2bf0f6fc0a1bbc8f4414c3e8a73cbc1686426b06cbabeb1281270` |
| `Media-Missher-Harness-Setup-bundle-v0.4.0.zip` | 255074 | `793c3a253f5ad338333faf1e209c7e00cf55080cd711826823149884e5c48325` |

正式 profile/runtime、日常浏览器资料、主分支和其他工作树保持原样。既有 Chrome CDP LaunchAgent 未修改，新入口不创建开机启动项。没有提交、推送、打 tag、正式安装、公开仓库或对外发布。

完成通知已于 2026-09-07 通过 send_message_to_thread 成功发送给用户指定的 `【DSH】Media@Missher`（`01a07766-9fe2-7da1-9809-7437205e41c5`），包括精确候选位置、版本、包哈希、测试范围、版权约定及后续接入契约；工具返回目标任务 ID，无错误。这是交接通知，不是正式安装或发布。

---

# 历史：Media@Missher 新设备名单导入交接 — 2026-09-07

当前候选为产品 **15.4.0 / Bundle 0.3.0**，位于 `.worktrees/xhs-reliability-20260907`；分支 `codex/media-xhs-reliability-20260907`，基线 `f87dd8858a0b888f03a7885a1641823af13457bd`。此前 15.3.0 / 0.2.0 内容保留在下方作为历史记录。

用户要查看已有抓取结果、核实空设备 CDP 行为，并明确选择 Excel/CSV 模板导入。已展示 2026-08-31 的历史八条记录工作簿和两条小红书指标；没有新采集。程序仅 connect_over_cdp；本机单独的 Chrome 登录启动项 RunAtLoad/KeepAlive 为 true，本轮未修改。

新增 `media_missher_setup` 的 status/template/import/activate。完整主页离线提取身份，名单可含多位同平台博主，预览后每次每平台最多选一位。导入 ID 绑定原始规范名单摘要，激活前同时核对预览，私有备份后原子更新 profile。active_platforms 限定默认范围，旧目标和合法设置保留。空设备、空名单或所选平台缺目标在 runtime 安装和创建输出前停止；当前采集固定目标快照。Git CLI 消费相同 profile 与默认平台范围；维护者可用 setup-device.mjs 操作同一导入实现。

核心文件：harness-plugin/src/creator-list.ts、private-config.ts、setup.ts、index.ts、runtime.ts；media-missher/scripts/run_collection.py；harness-plugin/scripts/setup-device.mjs；对应新增/回归测试、安装 smoke、版本/包和说明。没有新增自动 Chrome 启动或浏览器下载功能。小红书保护与历史续采保持上一版约束。

新版本 Python 全套 **1066 passed**（1 个预期 socket 阻断警告，135.41 秒）、最终 Bundle **244 passed / 14 files**（单 worker，87.72 秒）、TypeScript 均通过；其中名单解析专项 154 项。最终包在真实 Harness 0.5.5 隔离 DSH_HOME 完成安装、激活、同版本重装备份、CSV/XLSX 名单导入与选择、历史工具、合成 40 条/六表工作簿和卸载。空设备 runtime 调用、runtime/run 目录创建、浏览器启动及真实平台请求均为 0；激活选择优先于旧默认平台、原配置逐字节备份均通过。Git CLI 的 help/status/template/import/activate 另通过端到端检查。最终 35 个 payload 与 2 个编译入口文件逐字节匹配，旧 0.2.0 包哈希未变。分层证据见 `harness-plugin/dist/ONBOARDING-EVIDENCE.json`；下方数字只属于旧版。

规格复核通过，发现的超长 UID、预览后内容变动和多行名称显示问题已修复。质量复核发现的模型构建前 XLSX 结构限制、规范 ZIP 部件分类、旧默认平台遮蔽本次选择问题均已修复并覆盖回归。最后一次独立源码复核被工具自动审核以“可能涉及网络安全风险”拦截，没有给出结论，不能记录为独立批准。根任务完成了对本地 ExcelJS 分发逻辑和现有回归的源码检查；不以此替代独立复核。

新产物：`harness-plugin/dist/dsh-media-missher-0.3.0.tgz`、`Media-Missher-Harness-Setup-bundle-v0.3.0.zip`、两种 `Media-Missher-Creators-Template` 模板；当前 SHA256SUMS.txt / SETUP-SHA256.txt 绑定 0.3.0，0.2.0 哈希保留在下面历史表和 RELIABILITY-EVIDENCE.json。尚无提交或发布 SHA。正式配置、运行时、登录态、主分支和其他工作树保持原样。

最终 0.3.0 Bundle 为 223124 字节，SHA-256 `ab56d94cf979b048a285ba18f4e171714dd665d8c7f206b0ce51ef852605613b`；Setup 为 236852 字节，SHA-256 `42f27ba297c16c8c601ff2867c85908f449b0e46f0a606d028b7708df09edec1`。实现文件集合摘要为 `40b95e66a28ff3984b1dcf09a9e8ef7b0351d0c4d4e8d9aec9203f831398f54c`，不是 Git 提交 SHA。使用说明见 `docs/NEW_DEVICE_15.4.0.md`。后续若准备正式安装或发布，应补齐独立复核；真实平台验收仍需明确的目标、预算和导航权限。

---

# 历史：Media@Missher 小红书可靠性升级交接 — 2026-09-07

当前产品 15.3.0 / Bundle 0.2.0 本地候选。工作树 `.worktrees/xhs-reliability-20260907`，分支 `codex/media-xhs-reliability-20260907`，基线 `f87dd8858a0b888f03a7885a1641823af13457bd`。用户已确认实施推荐升级，优先小红书风控。本轮尚无源码提交或最终发布 SHA；主分支、其他工作树、正式 runtime 和 Harness profile 未改动。

## 已实现

- 小红书每批最多 10 条、3 页；翻页等待 3 秒；完整详情保留 5–15 秒停留。默认不读评论，明确请求时仍受原有滚动预算约束。
- 同一 runtime home 的批次启动至少间隔 600 秒，独立私有锁覆盖整批，风险暂停跨重启保留。仅本地操作者明确确认可解除暂停；不清除批次间隔、不启动采集、风险旧运行仍禁止续采。
- 控制器要求 runtime 15.3.0，避免新 Git 代码启动旧核心绕过保护。Harness 按内置版本安装自己的 payload。
- 真正停止自己创建的 runtime 进程组及子进程，等待清理完成才释放 collection lease；外层 8 秒宽限大于内层有界清理预算。
- 每个已接受进度前缀写入原子 committed.json，包含严格 manifest 与声明 JSON 数据。当前运行在进程结束后恢复兼容文件；历史读取不把旧观测当新鲜结果。
- 搜索超时和受支持的评论参数完整传递；API 分页仅在游标前进、仍有页数预算时跨过重复内容页。
- 私有 run-context.json 绑定原请求摘要、配置摘要、目标、版本和父运行。续采只支持显式选择的非风险创作者运行和正数原始目标，验证最多 32 层祖先、总量、原生 ID、语义完整性和截图。
- 新旧结果分开保存、分别计数；原运行不可变。离线历史列表、JSON/CSV/JSONL/SQLite 导出、双运行指标对比不发起浏览器请求。
- Harness 新增 media_missher_runs（list/export/compare/xhs-status），collect 增加 resume_run；工作簿区分历史接受数与本批新记录。模型工具没有解除风险暂停入口。

## 修改范围

`media-missher/scripts/` 控制器/历史/CLI；`runtime/media_missher_runtime/` 模型、分发、存储、四平台采集器、XHS 策略及排除计划；`runtime/scripts/xhs_safety.py`；`harness-plugin/src/` 工具、校验、停止和工作簿；版本、包/Setup/CI、技能引导及相应测试。详细行为见 `docs/XHS_RELIABILITY_15.3.0.md`，设计与实施步骤在 `docs/superpowers/`。

## 验证状态

最终 Python 禁网全套 **1059 passed**，一个有意验证 socket 阻断的警告；Bundle **65 passed / 11 files**；TypeScript 通过。最后文档/包边界修订后，相关 Python **41 passed**。33 个 Python 源文件内存编译、8 个 CLI help、残留扫描和 git diff --check 通过。最终 Bundle 的 35 个 payload 文件与源码逐字节一致，Bundle/Setup 白名单和来源字节验证通过。规格与独立质量复核通过；质量复核另独立运行新增 10 个回归并通过。

真实 Harness **0.5.5**（Electron / app.asar.unpacked 布局）在隔离 DSH_HOME 完成 CLI 安装、激活、入口实际导入、同版本重装及原清单备份、卸载和邻接状态保留。采集投影为四平台各 10 条合成记录，六表工作簿重读通过；已安装的新工具实际执行 list/export/compare/xhs-status 全部通过，历史观测时间保留。初次 smoke 的规范化配置和 macOS 临时目录别名问题已在测试脚本修复，最终候选字节的 smoke 全通过。全部临时输出清理，正式 runtime/profile 未改。

分层证据及 35 个源文件哈希见 `harness-plugin/dist/RELIABILITY-EVIDENCE.json`。历史 0.1.1 的 MAINTENANCE-EVIDENCE.json 保留，不作为本候选证据。

真实平台请求 0，无账号采集或 BrowserSkill 操作。合成 fixture 通过不等于小红书登录、真实数据完整性或风控验收。本次不声称 Windows 原生支持；Bundle 仍限定 macOS。已安装 Harness 的布局以本次实际发现为准，不使用旧任务的布局结论。

## 产物与后续

候选 Bundle：`harness-plugin/dist/dsh-media-missher-0.2.0.tgz`。
候选 Setup：`harness-plugin/dist/Media-Missher-Harness-Setup-bundle-v0.2.0.zip`。
校验：同目录 SHA256SUMS.txt 与 SETUP-SHA256.txt。根 GitHub bootstrap 仍指向历史已发布 v15.2.1；本地候选尚未安装、推送、打 tag 或发布。

若进行实际账号验收，先明确本次平台、目标、条数和导航权限，再用已有浏览器做 preflight 和顺序小批量采集。风险必须停止，不能自动重试或自动解除。十分钟间隔与数量上限属于本地保守预算，无法保证平台不会风控。发生保护阻断时，保留安全状态文件与历史结果。

## 最终候选校验

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `dsh-media-missher-0.2.0.tgz` | 209563 | `aa47161f3ecae4cbd1c9a87eca1ac8caff1694255193e17ca9b498c1b7a0191f` |
| `Media-Missher-Harness-Setup-bundle-v0.2.0.zip` | 222550 | `02caeb8b830b1d79c76705a4fe226757db687aecd117ca38f3a0ebc6867ef861` |

实现文件集合摘要：`35e755a8ff9fdc22f8f09885cdbe7bf0089fc44c12022b61a8ab4f871ed07cdf`。这不是 Git 提交 SHA；当前工作树保留可审查的未提交修改。
