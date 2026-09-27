# 15.6.0 冻结版本基准

核验日期：2026-09-26，基准整理阶段。本文保留该阶段源码、安装态与冻结归档的核验事实。之后用户要求只保留 Chrome CDP，当前源码已完成精简并与下述冻结内容分化，见 [CDP 精简记录](CDP_ONLY_2026-09-26.md)；安装态与旧归档未改。

后续用户确定下一代为 **V17（目标 17.0.0）**。[V17 研究与开发顺序](V17_RESEARCH_2026-09-26.md) 记录新增问题与离线证据；当前基准和本页历史核验数字不因此改变，V17 尚未实现或安装。

## 应该使用哪一版

**以 `开发版/Media@Missher` 的当前工作区作为唯一主开发基准。** 它包含 9 月 20 日的 CDP/Computer Use 收敛、X、多目标、批次恢复与选择导出，以及 9 月 23 日的指令和独立导出入口修复；本机已安装的 Codex Skill 与共享运行时也来自这一版。

**独立 DSH Bundle 0.6.1 保留为兼容修复来源，尚未合入主开发版。** 该分支的版本号较大，但它基于较早的 15.6.0 内容，不包含主开发版后续的 X、多目标计划及 BrowserSkill 退役等变化。当前不存在同时包含两条线全部成果、且已完成各宿主验收的统一发行版。

本轮不改变版本号、不合并代码、不重打包；通过源码位置、构建日期和完整 SHA-256 消除同版本混淆。

## 组件版本与身份

| 组件 | 主开发基准 | 权威来源 | 当前状态 |
| --- | --- | --- | --- |
| Media 共享运行时 | 15.6.0 | 根目录 `VERSION` | 本机 Codex 已安装，离线预检通过 |
| 通用 Agent CLI | 0.1.0 | `agent-plugin/package.json` | 有冻结候选包，本机 PATH 尚无通用命令 |
| DSH Bundle | 0.6.0 | `harness-plugin/package.json` | 主开发线候选；本机所查 profile 未挂载 |
| DSH 兼容分支 Bundle | 0.6.1 | 独立分支 `harness-plugin/package.json` | 9 月 13 日兼容修复，未合入主开发线 |

这些数字属于不同组件。`15.6.0 / 0.1.0 / 0.6.0` 是一组有效组合，不要求数字相同；同名同版本的归档也必须按摘要区分。

- 真实开发目录：`/Users/missher/Documents/Projects/02-Media@Missher/开发版/Media@Missher`。
- 兼容入口：`/Users/missher/Desktop/Media@Missher`，指向同一真实目录。
- 分支：`codex/media-browser-agent-desktop-20260920`。
- 提交基点：`f87dd8858a0b888f03a7885a1641823af13457bd`。大量功能仍在未提交工作区，HEAD 不能代表完整候选。
- 机器可读核验记录：[VERSION_BASELINE_2026-09-26.json](VERSION_BASELINE_2026-09-26.json)。

## 两条 15.6.0 开发线的区别

| 内容 | 当前主开发版 / Bundle 0.6.0 | 独立兼容分支 / Bundle 0.6.1 |
| --- | --- | --- |
| 主要进展 | 9 月 20 日功能收敛、9 月 23 日修复 | 9 月 13 日官方 Harness 生命周期兼容 |
| X、多目标、版本化计划、选择导出 | 包含对应新增模块 | 不包含这组后续模块 |
| BrowserSkill 活动模块 | 已删除，旧请求明确拒绝 | 仍保留较早的 `browser_skill.py` |
| `ctx.subprocess`、环境过滤、取消与在途卸载 | 专门的官方适配修复尚未合入 | 包含 `host-process.ts` 等实现 |
| 适合用途 | 后续主开发、当前 Codex 安装来源 | 后续提取 DSH 兼容修复与验收方法 |
| 不应进行的操作 | 仅改版本号就宣称已整合 | 用整棵旧源码覆盖主开发版 |

兼容分支位于 `历史基线/Media@Missher/.worktrees/media-official-compat-20260912`。其源码导入提交为 `28364839d72d495f3df8a2199456ff4ca151584f`，适配提交为 `a2d49d820a8751482bab520eb8c097efae1c49c2`，核验时 HEAD 为 `feea7040f60252680024a4f79c4089f00931f5a4`，另有既存 README 修改，本轮保持原样。

该分支的历史记录描述了官方 npm Harness 0.1.5-rc.2 的 macOS 隔离生命周期验证；使用合成解释器，未执行真实采集。参见其 [兼容记录](../../../历史基线/Media@Missher/.worktrees/media-official-compat-20260912/docs/OFFICIAL_HARNESS_COMPAT_20260912.md) 和 [0.6.1 清单](../../../历史基线/Media@Missher/.worktrees/media-official-compat-20260912/harness-plugin/release/0.6.1.json)。这不证明当前 DSH 或主开发线已具备相同兼容性。

## 冻结候选包

主开发线以下三份归档的实测 SHA-256 与 2026-09-23 最终记录一致：

| 归档 | SHA-256 |
| --- | --- |
| `harness-plugin/dist/dsh-media-missher-0.6.0.tgz` | `7d64d547c0ec4e6484a2511dac87019ee3b6c06e61c267f428ed8c2b864a3a17` |
| `agent-plugin/dist/missher-media-missher-0.1.0.tgz` | `8278be06a05270e8fbc03694d8fb60444282ebcc19d5e4c4e7095ef7edda96de` |
| `agent-plugin/dist/Media-Missher-Agent-Setup-v0.1.0.zip` | `f3b6ea344f7cead7b9e39ae1fd5fe93c010ec9979c28b19cec39f290e73dc0d0` |

两个 tgz 内的运行时版本均为 15.6.0，包版本分别为 0.6.0 与 0.1.0。两条入口使用的编译实现摘要相同：`bd1fd2e6fea34997c492e8326ee804e765b36b3793ca253349d4f01aa7c566c7`。

独立兼容分支的 0.6.1 tgz 摘要为 `be5adbfe37c13a628accad70e1b71aa2696bdd2f5d5e9933081c112ce8397744`，对应 Setup ZIP 为 `6b2ad3d244fc244be9d02c677ca9a979f5e9e9f8d4c65f87981672fec1a88c70`；它们也已按现有文件复核，不与主开发线归档互换。

**本轮整理后的源码文档尚未进入这些冻结包。** 不应再宣称整份归档与今天的全部文档逐字节相同。运行代码、已安装 Skill 和现有归档均保持原状，后续发行时再统一重建和绑定证据。

`agent-plugin/dist/PACKAGE.json` 和 `SHA256SUMS.txt` 对应当前主线归档；同目录 `AGENT-ENTRY-EVIDENCE.json` 仍是 9 月 8 日旧快照，不作为这些新摘要的验收凭据。9 月 23 日归档与安装记录见 [ASTRA_MIGRATION_2026-09-23.md](ASTRA_MIGRATION_2026-09-23.md)。旧报告中的早期状态必须结合日期和阶段阅读。

## 本机安装态

| 项目 | 本轮核验 |
| --- | --- |
| 共享运行时 `~/.local/share/media-missher/current` | 15.6.0；39 个源文件与安装态一致 |
| Codex Skill `~/.codex/skills/media-missher` | 15.6.0；14 个源文件与安装态一致 |
| runtime / venv / Skill 发布标记 | 三者均为 `20260923T074242322465Z-736a0c4a` |
| 离线 preflight | 版本、布局、Python、依赖及入口检查通过；不含浏览器连接和平台登录 |
| 通用 CLI | 源码入口的版本与能力查询正常；本机 PATH 没有已安装的 `media-missher` |
| Hermes | `~/.hermes/skills/openclaw-custom/media-missher/SKILL.md` 为 15.2.0，仍引用 Codex 和退役 BrowserSkill；当前会话激活未验收 |
| DSH | 所检查的本机 `desktop/web` profile 无 Media 依赖或配置挂载；当前组合原生调用未验收 |
| Computer Use | 能力查询返回 `host-computer-use-unavailable`；不可因接口存在而视为已接通 |

原子安装器管理的 Codex Skill 不应被通用 CLI 的同名 Skill 强制接管。安装态与源码目录分开维护，恢复目录、私有 profile、历史和风险状态均保留。

## 历史目录与文档入口

- `历史基线/Media@Missher`：15.2.1/main，HEAD `9d70e1a3030b1534c464155df618e661b56a1f70`。旧 `~/Documents/Media@Missher` 指向这里。
- `xhs-reliability-20260907`：更早的 15.6.0 工作快照，仍有未提交内容；不得覆盖主开发版。
- `历史备份`：旧版本和恢复材料，非当前安装来源。
- 旧路径链接仍支撑 Git worktree 登记及历史工具引用，本轮不移动源码、改 worktree 登记或删除链接。
- 当前阅读顺序：根 README → PROJECT_CONTEXT → 本基准 → HANDOVER。设计、旧提示词和阶段验收仅按需读取。
- 原始文档保存在[本轮整理前快照](history/2026-09-26-before-baseline-cleanup/INDEX.md)，附 SHA-256；其内容不再承担当前操作入口职责。

## 本轮验证范围

本轮检查源码/安装文件摘要、三个发布标记、五份候选归档身份、路径兼容关系和文档入口。检查原文快照完整性、当前文档本地链接及既有文档回归；详细结果记录在机器可读基准的 `documentationVerification` 中。

没有执行功能合并、版本提升、重新构建、宿主安装、浏览器启动、真实平台采集或 Git 提交发布。9 月 20 日、9 月 23 日及兼容分支的既有测试数字属于历史证据，本轮不冒充重新通过。下一步范围见 [HANDOVER.md](../HANDOVER.md)。
