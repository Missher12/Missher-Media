# GPT-6 Astra 接入修复 — 2026-09-23

本轮采用宿主接入：GPT-6 Astra → 已安装的 Media Skill / Agent CLI → 共享运行时。项目未内置模型 API 客户端，模型和推理级别由宿主选择。本机只读配置为 `gpt-6-astra` / `max`；配置存在不证明当前任务的有效模型、Skill 激活或实际任务成功。

## 正式 Codex 升级：15.6.0 已完成

用户在确认安装范围后回复“15.6.0”，授权本机 Codex Skill 与共享运行时同步升级。已使用项目原子安装器执行 `--codex-only`，未强制覆盖为通用 CLI 同名 Skill。Harness/OpenClaw 正式安装、真实平台采集和 Git 操作仍暂停。

- 安装来源：当前 Desktop 工作树，安装前 58 个输入文件与上一阶段通过验证的候选一致；版本为 15.6.0。
- 统一发布标记：`20260923T074242322465Z-736a0c4a`，runtime、venv、Codex Skill 三者一致。
- 正式入口：`/Users/missher/.codex/skills/media-missher/SKILL.md`；运行时：`/Users/missher/.local/share/media-missher/current`；Python 3.11.15 环境：`/Users/missher/.local/share/media-missher/venv`。
- 安装后源码逐文件一致；离线 preflight 的版本、布局、租约、依赖与入口检查全部通过。
- 使用实际安装的 Python 和 `manage_runs.py`，在独立临时数据目录完成 1 条合成历史记录的 CSV 选择导出；关闭 PYTHONPATH/site-packages 自动加载后仍通过。未启动浏览器，真实平台请求为 0。
- 使用 `/Applications/ChatGPT.app/Contents/Resources/codex app-server` 的 `skills/list` 强制重扫，发现唯一启用的 Media@Missher V15.6.0，路径正确且无相关发现错误。这证明新进程可发现新版；不表示当前已打开任务自动重载了旧 Skill 上下文，也未做 Astra 模型行为验收。
- 原运行时、venv、Skill 三份备份与升级前内容逐文件相同。配置、历史和风险状态等 267 个受保护文件未变；Codex 配置文件摘要未变，继续使用 `gpt-6-astra` / `max`。

私有安装证据：`.superpowers/sdd/2026-09-23-astra-migration/install-15.6.0-izbnw5p9/`，包含 `before.json`、`receipt.json`、`integrity-after.json`、`preflight.json`、`installed-export.json` 和 `skill-discovery.json`。

| 旧 15.2.1 组件 | 已验证的恢复目录 |
| --- | --- |
| 共享运行时 | `/Users/missher/.local/share/media-missher/previous-20260923T074242322465Z-736a0c4a` |
| Python 环境 | `/Users/missher/.local/share/media-missher/venv.previous-20260923T074242322465Z-736a0c4a` |
| Codex Skill | `/Users/missher/.local/share/media-missher/recovery/codex/media-missher.previous-20260923T074242322465Z-736a0c4a` |

如需恢复，先确认无采集并持有安装锁，将当前三个组件另存后同步恢复以上三份目录，核验旧发布标记一致。配置、历史与平台风险状态不参与回滚。本轮未实际回滚已成功完成的升级。

下方保留源码与候选阶段记录，其中“正式安装暂停”和“已安装 15.2.1”均为此次授权升级前的状态。

## 基线与范围

- 开发目录：`/Users/missher/Desktop/Media@Missher`。
- 分支：`codex/media-browser-agent-desktop-20260920`。
- HEAD：`f87dd8858a0b888f03a7885a1641823af13457bd`。工作区存在未提交实现，HEAD 不能代表完整候选。
- 源码版本：runtime 15.6.0、Agent CLI 0.1.0、Harness Bundle 0.6.0。
- 只读核验时，Documents/main、正式 Codex Skill 和正式运行时均为 15.2.1。正式宿主安装、真实平台与 Git 操作沿用原暂停约定。
- 原开发任务已结束；用户本轮授权当前任务修复入口和指令冲突并做本地验证。旧候选及本轮改动文件已保存私有备份。

## 已修复的入口与指令

- 两种 Skill 缩短发现说明，保留真实操作边界；沿用已有授权，只询问影响结果的缺失信息。
- 源码 Skill、共享 CLI Skill、Harness 指令和操作文档一致描述：采集先保存私有证据，随后按用户选择离线导出；导出完成才交付实际文件链接。
- 显式 browser-open 是用户要求打开独立 AI 浏览器时的 setup 操作；采集不自动开浏览器，不因失败更换浏览器或后端。
- 私有计划入口的参数优先级为显式 CLI > 本次私有计划 > profile > 默认；省略值不覆盖计划，显式 0/off 生效。
- 修正四平台、单平台只选一位、超话已支持及自动工作簿等过期说明；保留各入口实际支持范围。
- Skill 的 openai.yaml 仅用于展示和默认提示，不承担模型切换。保留宿主当前模型与推理设置。
- Harness 原生验收改为检查采集不自动导出，并验证单独发起的历史 CSV 导出；合成采集与历史导出分别记录，不能冒充真实平台采集。
- 修复 `manage_runs.py` 的独立进程入口：初始化包内共享核心路径，并支持已安装 Skill 对应的 `MEDIA_MISSHER_HOME/current`。此前选择导出会因找不到 `media_missher_runtime` 退出，测试预设的模块路径掩盖了该问题。新增两种布局的独立进程回归，不依赖 PYTHONPATH 或 site-packages。

## 安装与回滚边界

正式已安装 Skill 由旧的原子运行时安装器管理，与通用 CLI 的同名 Skill 安装入口不同。不能强行覆盖或让两份同名 Skill 竞争。切换前核验归属、版本、待安装包摘要和恢复路径；Skill 与其需要的运行时必须一致。

本轮保持产品候选版本号，归档身份使用新 SHA-256；同版本旧归档已备份。安装后的新任务需要分别验证 Skill 发现、绝对 CLI/adapter 路径和真实工具调用。当前会话已经加载的旧 Skill 文本不会因磁盘更新自动成为新文本。

回滚只恢复本轮修改文件或此前安装入口，保留未提交的其他成果、私有运行历史和平台风险状态。禁止 reset/clean、删除风险状态或切后端绕过停止。

## 验证记录

本轮私有证据与原文件备份：`.superpowers/sdd/2026-09-23-astra-migration/run-ijtir4af/`。`baseline.json` 记录开始时工作树摘要；`backup/` 保留本轮涉及文件及旧归档；`changes.diff` 只描述本轮差异。已保护既有未提交成果，不以 HEAD 代替候选内容。

| 验证层 | 本轮结果与证据 |
| --- | --- |
| Skill / 静态 | 两个 Skill 均通过 `quick_validate.py`；TypeScript 类型检查、原生验收脚本语法检查和 `git diff --check` 通过。验证器的 PyYAML 仅放入隔离 uv 环境。见 `static-final.log`、`typescript.log`。 |
| Harness 单元 | `pnpm exec vitest run --maxWorkers=1 --no-file-parallelism`：18 个文件、293 项通过。原生脚本更新后另跑 installer 相关 4 项通过。见 `harness.log`、`native-script-regression.log`。 |
| Agent 单元 | `node --test tests/*.test.mjs`：54 项通过。见 `agent.log`。 |
| Python 离线 | 首次全套为 1293 通过、2 失败：一项检查只读授权的文本约束，一项独立子进程达到原有 10 秒超时；保留 `python.log`。恢复约束表述后两项重跑通过，未改超时或弱化测试。修复历史导出入口后，新增回归与 history/export/packaging/OpenClaw 相关共 108 项通过，见 `python-affected-final.log`。不把首次全套报告改写为全部通过。 |
| 故障复现 | 原生验收先发现旧脚本遗漏必填 `record_kinds`，补齐后暴露真实模块导入错误。有效历史数据的独立进程回归在修复前两种布局均以 `ModuleNotFoundError` 失败，修复后通过。原始失败记录均保留。 |
| 构建 / 归档 | Bundle 验包与 Agent Setup 构建通过。最终归档与源码逐文件一致：Harness 59 个文件字节相同，package.json 只含 pnpm 的已知字段移除；Agent 64 个文件字节相同。见 `packages-runtime-fix.log`、`archive-source-match-runtime-fix.json`。 |
| Harness 隔离安装 | 最终 Bundle 通过真实 Harness CLI 的临时 profile 安装、同版本刷新、卸载和相邻状态保留；安装包入口执行合成采集、保存历史的 list/export/compare、风险状态与进度检查通过。CSV 导出实际读取包内 Python 代码并得到 1 条选定记录，采集无自动导出。浏览器启动使用注入测试替身，真实浏览器与平台请求均为 0。见 `harness-native-runtime-fix.log`。 |
| Agent 隔离安装 | 最终 Setup 通过临时 HOME 中的实际 shell 安装器、CLI 版本/能力、Skill 安装/幂等/已有编辑保护、合成目标导入与激活。缺失 CU 宿主时按约拒绝；真实浏览器与平台请求均为 0；临时 HOME 已清理。见 `agent-native-runtime-fix.log`。 |

最终候选归档（版本号沿用原候选，以完整摘要区分）：

| 产物 | SHA-256 |
| --- | --- |
| `harness-plugin/dist/dsh-media-missher-0.6.0.tgz` | `7d64d547c0ec4e6484a2511dac87019ee3b6c06e61c267f428ed8c2b864a3a17` |
| `agent-plugin/dist/missher-media-missher-0.1.0.tgz` | `8278be06a05270e8fbc03694d8fb60444282ebcc19d5e4c4e7095ef7edda96de` |
| `agent-plugin/dist/Media-Missher-Agent-Setup-v0.1.0.zip` | `f3b6ea344f7cead7b9e39ae1fd5fe93c010ec9979c28b19cec39f290e73dc0d0` |

正式 Codex 切换应使用当前归属的原子安装器，同步升级源码 Skill 与共享运行时，保留安装器报告的恢复路径；通用 CLI Skill 不能强行覆盖原子安装器管理的同名入口。该切换沿用项目暂停约定，待明确恢复正式安装后执行。

最终只读复核：Documents/main 的 HEAD 与工作区状态保持原状；正式 Skill 和共享运行时仍为 15.2.1；宿主配置仍为 `gpt-6-astra` / `max`。没有正式安装、真实平台操作或 Git 提交推送。见 `protected-targets-final.json`。隔离安装没有证明正式共享 Python 环境升级、宿主新任务 Skill 激活或模型的实际行为。

## 仍需单独验收

Computer Use 的真实宿主映射未通过，离线核心仍限单一 X accessibility 目标；多目标、微博主页阶段和纯 visual 模式并未因更换模型而完成。Astra 原生任务行为、正式安装后的新会话发现、真实平台采集分别验收。CDP、私有历史与离线导出不依赖未就绪的 CU。

## 官方依据

- [GPT-6 迁移指导](https://developers.openai.com/api/docs/guides/latest-model#migration-quickstart)：保留受支持的推理级别；若另行建设 API Agent，Astra 工具调用使用 Responses API。
- [Astra 的 Skill 与提示词指导](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)：收窄发现描述、减少冲突指令，并保留任务所需的具体约束。
