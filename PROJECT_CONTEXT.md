# Media@Missher 当前项目摘要

## 2026-10-03 当前交付

运行时、Agent CLI、DSH Bundle 本轮统一为 **17.0.2**。实现范围与验证见 [本版记录](docs/releases/v17.0.2.md)，审查起点见 [优化审查](docs/COLLECTION_OPTIMIZATION_REVIEW_2026-10-03.md)。维护目录与唯一后端继续以 AGENTS.md 为准。

已实现精确搜索绑定、B 站增量与继续页修复、抖音完整 mix 展开、展示数值/来源保护、共享可见阻断检测、X 等待超时风险检查、持久正常间隔与单批上限、重复观测补全及计划字段验收。人工维护入口同步解除指定平台风险，保留冷却和其他平台状态。

当前为本地源码与隔离构建候选，日常安装、远端 Git、本地 CDP/真实平台各自单独报告；不能沿用下文历史安装状态当成现状。交付后由共享安装负责人核验新鲜日常基线、备份并安装。源码分支起点为 `95961588634577fd0c0b92a1d7abed2576d9ac61`；不包含任何真实账号或采集数据。

## 以下为此前交付记录

2026-09-29 追加 UI-REFINE：当前 DSH 包名统一为 `@missher/dsh-media-missher`，配置和存储标识保留。此处为源码候选；本轮安装与验收以协调目录 `coordination/2026-09-29/ui-refinements/` 的回执为准，下面的版本与透明空格等描述保留为历史。

更新：2026-09-27。当前交付以 [17.0.0 记录](docs/releases/v17.0.0.md) 为准；[docs/CURRENT_BASELINE.md](docs/CURRENT_BASELINE.md) 保留此前冻结基准；后续工作见 [HANDOVER.md](HANDOVER.md)。原有按日期叠加的完整记录已[原样归档](docs/history/2026-09-26-before-baseline-cleanup/PROJECT_CONTEXT.md)。

## 当前基准

- 开发目录：项目总目录内的 `开发版/Media@Missher`，绝对位置以项目 AGENTS.md 为准。旧 Desktop 路径是该目录的兼容链接。
- 运行时、通用 Agent CLI、DSH Bundle 统一为 17.0.0，Git 交付分支为 `codex/media-v17-cdp-package`。本轮起点为 `f87dd8858a0b888f03a7885a1641823af13457bd` 及其既有开发改动；最终内容以交付分支、源码逐文件摘要及 dist/v17.0.0/SHA256SUMS.txt 为准。
- 本机 Codex Skill 与共享运行时仍安装 15.6.0。此前基准整理时源运行时 39 个文件、Skill 14 个文件与安装态一致；本轮 CDP 精简后源码已分化，安装态未改。不要将此前摘要一致结论用于当前源码。
- 独立 DSH 兼容分支的 Bundle 为 0.6.1，运行时也为 15.6.0，但没有累计包含当前开发版的后续功能。其 `ctx.subprocess`、取消和卸载生命周期修复尚未合入本目录，应保留作为后续修复来源。
- 当前交付为 V17（17.0.0）。用户已授权完整打包、能力说明、测试和私有 Git 提交；Chrome CDP 精简见 [精简记录](docs/CDP_ONLY_2026-09-26.md)，能力字段见根 DATA_CAPABILITIES.md。新包写入 dist/v17.0.0，原安装与旧冻结归档保持原样。

## 架构与边界

**Source boundary**：唯一主开发目录是上述开发版。`历史基线/Media@Missher` 的 15.2.1/main 和各旧 worktree 为只读参考；DSH 0.6.1 分支是仍有价值的兼容修复来源。保护所有既有未提交工作，不按目录名称或版本号大小删除分支。

**Runtime boundary**：`runtime/` 提供共享 Python 核心，唯一活动后端为 Chrome CDP，不依赖 DSH。Computer Use 与 BrowserSkill 均退役，旧请求明确拒绝；保留历史读取、导出和原始来源。单一浏览器所有者、顺序采集、精确身份、共享锁、小红书 10 条/3 页/600 秒及持久风险暂停保持不变。

截图仍受请求级授权和条数约束：`--screenshot-mode all` 要求有效正数条数（positive count），不能与零条数请求混用；非默认截图模式需要明确导航授权。字段与证据格式见 Skill 的命令和验证参考。

**Adapter boundary**：`media-missher/` 提供 Skill 和 Python 入口；`agent-plugin/` 提供本地 CLI + 共享 Skill；`harness-plugin/` 只注册 setup、collect、runs 三个工具。Computer Use 专用的 `shared/` 证据协议已移除。CLI 运行不要求 DSH，现有构建复用关系保留，本轮不展开应用层重构。

模型由宿主选择，保留用户模型和推理设置。Agent 意图经过版本化计划与顺序目标队列，交给冻结的后端执行，再验证并保存私有证据；导出读取已保存结果，按用户选择投影，不自动补抓。

## 安装、验证和限制

**Cutover**：本机 `~/.codex/skills/media-missher` 与 `~/.local/share/media-missher/current` 在 2026-09-23 经原子安装器同步升级到 15.6.0。运行时、venv、Skill 的发布标记为 `20260923T074242322465Z-736a0c4a`，旧版恢复目录保留。通用 CLI 不得强制覆盖该安装归属。

其他入口分别核验：本机 Hermes 的已发现旧 Skill 仍为 15.2.0；本机 PATH 没有通用 `media-missher` 命令；所检查的 DSH `desktop/web` profile 没有挂载 Media Bundle。`~/.openclaw/workspace/skills/media-missher` 是旧部署路径，本轮没有检查或安装，不把它视为当前已接入状态。

**Live acceptance**：2026-09-27 已通过临时 Chrome 本地页与当前 Python 核心 CDP 验证，见 [复验记录](docs/CDP_VERIFICATION_2026-09-27.md)；本轮没有请求真实平台。9 月 23 日的源码、隔离安装和导出证据见 [Astra 修复记录](docs/ASTRA_MIGRATION_2026-09-23.md)；9 月 20 日的离线候选范围见 [离线验收记录](docs/CDP_CU_OFFLINE_ACCEPTANCE_2026-09-20.md)。历史通过结果均绑定当时源码、宿主和归档，不代表本轮重跑或当前宿主实采通过。

旧记录中的 `V15 Xiaohongshu live acceptance passed` 对应 2026-08-13 的小红书验收，完整过程保存在本轮原文快照；这是历史证据，不代表当前 15.6.0、多平台或 Computer Use 已通过真实验收。

该次历史记录的范围说明为 `Bilibili, Douyin, Weibo, and keyword-search DOM paths were not part`；这些路径不属于当时的小红书验收。原文还记录 `BrowserSkill remained at zero sessions`，不能据此声称其旧后端通过实采。

**Current limitations**：Computer Use 已从本轮范围移除，不再列为待补齐能力。DSH 兼容修复尚未整合；DSH 0.1.7-rc.2 隔离安装与合成调用已通过；Linux/WSL 图形浏览器、真实用户 profile 的 LLM 工具行为及各平台实采仍需分别验收。本版交付及隔离安装结果以 dist/v17.0.0/VALIDATION.json 为准，真实宿主安装未替换，软件与分发保持私有。

此前 V17 研究中的升级倒退、Hermes 自定义目录和宿主环境继承问题仍保留记录，按用户最新范围暂不处理。研究当时的 CU 接入建议已被 CDP 单一入口决定取代；历史测试数字不代表本轮重跑。

## 维护时的阅读顺序

1. 本摘要确认工作目录、当前范围和边界。
2. [当前版本基准](docs/CURRENT_BASELINE.md) 核对版本、分支、归档和安装态。
3. [HANDOVER.md](HANDOVER.md) 选择下一项有界工作。
4. 按需要读取相关设计和历史证据；不要把旧文档中的“当前”“已完成”“暂停”直接用于今天的判断。
