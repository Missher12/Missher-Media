# Media@Missher 15.6.0 通用 Agent 入口

本地候选：运行时 **15.6.0**、Agent CLI **0.1.0**、Harness Bundle **0.6.0**。参考 [Tencent/BrowserSkill](https://github.com/Tencent/BrowserSkill) 的 CLI＋共享 Skill＋Agent 安装指引设计；没有安装、启用或复制它的浏览器实现。源码仓库 `Missher12/media-missher` 仍为私有，原创部分保持 Missher 的专有许可。

## 给新的 Agent 使用

解压 `agent-plugin/dist/Media-Missher-Agent-Setup-v0.1.0.zip`，把文件夹和这句话交给能执行本地命令的 Agent：

> 按照这个文件夹里的 AGENT_INSTALL.md 安装 Media@Missher，给你自己安装操作 Skill，再带我导入博主名单、登录平台并完成首批授权采集。

安装指引包含真实包 SHA-256，不要求读取私有 GitHub 仓库或本维护会话。安装程序返回绝对 CLI 路径；PATH 不可用时，安装的 Skill 也有绝对 Node＋CLI 命令。新设备先检查环境、导入 Excel/CSV 名单并选择目标，再明确打开独立 AI 浏览器，由用户手动登录，最后采集并展示 Excel。空名单的检查和采集请求均在创建 runtime、结果目录或访问 CDP 前停止。

通用入口需要 Agent 能执行命令并读取 Skill。可明确安装到 Codex、Claude、Cursor、OpenClaw、Hermes 的技能目录，也可指定其他宿主的技能目录或直接阅读同一 Skill。技能文件安装成功和当前会话激活是两项检查；普通聊天界面没有本地执行能力时不能直接运行。

## 实现及文件

- `agent-plugin/bin/media-missher.mjs`：严格参数、离线 doctor、setup/collect/runs、JSON 结果、stderr 阶段进度及取消信号。独立于 DSH_HOME、Cordis 和 Harness 安装。
- `agent-plugin/src/skills.mjs` 与 `skill/SKILL.md`：统一操作契约、宿主目录映射、绝对命令、安装归属摘要、升级备份；不覆盖未知或被用户编辑的 Skill。
- `agent-plugin/scripts/{archive,install,build,build-setup,native-smoke}.mjs`、根 `install.sh`/`install.ps1`：完整 payload 与 SHA 校验、私有版本目录、安装锁、依赖安装失败回退、激活前实际入口检查、安装包构建及隔离验收。取消安装会等待原进程组清理；无法确认清理时保留暂存 release。
- `harness-plugin/src/{index,runtime,browser-setup,setup}.ts`：导出共享工厂、传递进度、准备 Linux GUI/Chrome 检查及 WSL 专用浏览器归属检查。两种入口仍使用同一采集实现，40 个 payload 文件和编译入口逐字节一致。
- `AGENT_INSTALL.md`、README、PROJECT_CONTEXT、HANDOVER、版本契约、相关回归及 CI：完整安装和操作路径，保留历史版本证据。

小红书 10 条/3 页/600 秒、同用户共享锁、持续风险暂停、顺序采集和默认不导航保持原有约束。不会通过重试、换账号或切换浏览器来消除风险状态。首次安装不启动 Chrome，也不把本地 CDP 连通称作平台登录成功。

## 平台与分发范围

macOS/Linux 使用同一 CLI 包，需要 Node >=22.19 和 npm；实际采集 runtime 需要 Python 3.11/3.12。Windows PowerShell 入口委托已有 WSL2，浏览器运行在同一 Linux 用户的 WSLg GUI 中，参见 [Microsoft WSL](https://learn.microsoft.com/en-us/windows/wsl/install) 和 [GUI 应用说明](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)。

WSL 私有文件必须位于 `/home/<user>` 下的原生 Linux 文件系统；拒绝 Windows 挂载和受控目录内的混合挂载、root 用户及未经本工具确认归属的外部浏览器。Windows 原生 Agent 必须明确通过 wsl.exe 调用，不能假定会自动发现 Linux HOME 的 Skill。这里没有提供 Windows 原生采集器。

**实际执行环境只有 Intel macOS。** Linux/Windows 入口有静态及注入环境测试，macOS/Ubuntu 安装 CI 和 PowerShell 语法 CI 已编写但未提交运行；没有 Linux、WSL 或 Windows 原生验收结果。独立 Harness Bundle 的既有安装器仍限定 macOS。

公开下载地址尚未部署。当前一句话入口对应交付的本地文件夹；要成为互联网上可直接读取的安装链接，后续需部署独立的官方分发位置并验证匿名下载。仓库私有性、专有许可和下载范围分别管理。本轮未提交、推送、创建 tag、公开仓库、发布 Release 或写入正式安装环境。

## 2026-09-08 验证

| 验证层 | 实际结果 |
| --- | --- |
| Python 全套，禁止网络 socket | **1105 passed**，1 个故意验证禁网门槛的预期警告 |
| Bundle Vitest | **289 passed / 18 files** |
| Agent CLI、安装器、平台测试 | **33 passed**；包括真实进程取消及完整 payload 缺失回归 |
| TypeScript、残留扫描、Git diff 检查 | 通过 |
| 独立规格与质量复核 | 均通过；质量复核发现的进程残留和缺失控制器问题已修复并重测 |
| 最终 Agent Setup 真实安装 | 隔离 HOME，通过实际 shell 安装、npm 依赖下载、入口版本/帮助、空设备、Skill 安装/幂等/编辑冲突、Excel 模板及合成 CSV 名单导入选择；临时 HOME 已清理 |
| 最终 Harness 0.6.0 真实安装 | Harness 0.5.5、隔离 DSH_HOME，安装/激活/重装/离线工具/卸载通过；40 条、六表工作簿为合成数据，浏览器动作和指导服务为注入 fixture |
| 来源与保留状态 | Agent 50 个文件及两包 40 个 payload 与暂存/源码一致；编译入口相同。19 个历史分发文件、4 个正式状态文件哈希保持；正式 HOME 未出现新版共享目录 |

完整 Python 首次运行曾有一次 10 秒进程启动超时，所属文件 14 项复查通过，随后完整 1105 项重跑通过；未为此放宽测试超时。当前版本的真实平台请求和实际浏览器启动均为 **0**，不将历史 15.4.0 四平台 4/4 或合成数据作为 15.6.0 平台验收。

Agent 原生测试未调用 Harness，也未建立 Harness profile；本机本身装有 Harness，因此不把结果表述为在“物理上从未安装过 Harness 的电脑”验收。未测试所有 Agent 的实际当前会话技能激活。

## 本地交付物

路径相对于本工作树；精确 SHA 和分层记录见 `agent-plugin/dist/AGENT-ENTRY-EVIDENCE.json`。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| agent-plugin/dist/missher-media-missher-0.1.0.tgz | 173207 | 17b3789c94642069d635cb663b57e70412c00f0523d34c26e000c2de4b7d8ff0 |
| agent-plugin/dist/Media-Missher-Agent-Setup-v0.1.0.zip | 190379 | 0a199bb18a2bdbaa3e00d93db306a75b395316de2178ad2f57aa22f9e9973e9a |
| harness-plugin/dist/dsh-media-missher-0.6.0.tgz | 248199 | f1671360ce463973e603a56c28ae0b0bcb254f483616ec8e4e9afb48cdd0ec66 |
| harness-plugin/dist/Media-Missher-Harness-Setup-bundle-v0.6.0.zip | 269190 | e2b2ce3df1240a1d1b8405409cbc435700a10868593e3b3322674f0245516b0d |

工作树 `.worktrees/xhs-reliability-20260907`，分支 `codex/media-xhs-reliability-20260907`，基线 `f87dd8858a0b888f03a7885a1641823af13457bd`。当前修改尚未提交，基线不能当作这些安装包的最终发布 SHA。旧版本归档保持不可变，新文件摘要记录在证据中。
