# dsh-media-missher 维护交接 — 2026-09-07

当前交付：Bundle **0.1.1 本地候选**，采集主项目 **15.2.1**。独立工作树 `/Users/missher/Documents/Media@Missher/.worktrees/harness-maintenance-20260906`，分支 `codex/media-harness-maintenance-20260906`。私有仓库 `Missher12/media-missher`，基线 `9d70e1a3030b1534c464155df618e661b56a1f70`。

实现与 Agent 首启文档提交：`6799e07624de28fd74cf5b01c4c7c16d098aa8cf`、`9b101b889d955345935fc052c4912e6b545af659`。最终安装包刷新提交：`f8ee0943582136000fde22552de72bf17254e497`。`harness-plugin/AGENT.md` 已进入内层 Bundle 和 Setup 白名单；它描述安装、profile、授权、结果和故障边界，不能替代 Harness 的实际工具注册。

## 已完成

- 严格参数检查、平台选择、评论参数约束；未知参数不传入控制器。
- 本次进程组有界停止；无自动采集重试、无风险停止重试。
- 原生 ID 首次出现去重、成功计数复核、请求外平台拒绝、风险优先。
- 按输出文件系统时间检查证据新鲜度与私有权限；固定诊断枚举阻止私密文本进入工具结果。
- XLSX 长字符串 ID 精确保留；拒绝已超出安全整数范围的数值 ID，保留原始 JSON 不改写。
- 通过公开 ToolDefinition/JSON Schema 注册，SDK 只用于类型检查，消除入口对宿主内部运行依赖的假设。
- Agent 工具描述补充已有浏览器、创作者采集、无凭据参数和 BrowserSkill 默认关闭边界；`allow_navigation` 默认改为 `false`，只有本次调用明确授权才导航。
- 新旧 macOS Harness 布局识别、入口字节校验及实际导入、独立 DSH_HOME 安装/同版本重装/备份/卸载验证。
- 新增 `harness-plugin/AGENT.md`，并由包与 Setup 的精确文件白名单、来源字节校验覆盖。
- 61 个 Bundle 测试、TypeScript 检查、988 个 Python 禁网测试、Bundle 与 Setup 白名单/字节验证通过。

## 文件与产物

主要实现：`harness-plugin/src/{config,index,process,runtime,workbook}.ts`；安装入口、`harness-plugin/scripts/` 和相应 tests；manifest、`AGENT.md`、README；PROJECT_CONTEXT.md。没有修改 `runtime/`、`media-missher/`、`tools/` 采集核心。

| 产物 | 字节 | SHA-256 |
|---|---:|---|
| `harness-plugin/dist/dsh-media-missher-0.1.1.tgz` | 189914 | `3704010bb73e7ad37dc81e4535c175161d7fa9bab316956bbb1354a88a23608e` |
| `harness-plugin/dist/Media-Missher-Harness-Setup-bundle-v0.1.1.zip` | 202365 | `e44571457086b471227819bd35510b92422682876e09c2903cf1e365accbf9e5` |

完整分层证据：`harness-plugin/dist/MAINTENANCE-EVIDENCE.json`。单独校验文件：`SHA256SUMS.txt` 与 `SETUP-SHA256.txt`。旧 0.1.0 tgz 与旧 v15.2.1 Setup 保持原始字节。

## 测试边界

真实 Harness CLI 完成隔离安装、实际模块导入、配置检查、同版本重装及备份核对。工具采集基础设施用合成 fixture 替代：四个平台各请求 10 条、接受 10 条、失败 0 条，六页工作簿重读通过。临时输出与临时 DSH_HOME 在验收后清理；真实 profile 和邻接状态未改。旧布局只做 fixture 测试，未声称另一台宿主或 GUI 双击验收。

Python 全套 988 项通过，唯一警告来自有意触发的 socket 阻断测试。uv 测试依赖与正式采集 venv 隔离，未下载浏览器。真实平台请求 **0**，无账号采集、浏览器导航或 BrowserSkill 操作。本轮不是新版插件的真实平台验收。

## 安装条件与下一步

本机新版 Harness 提供自己的 Node/CLI，但不含 pnpm。安装器只寻找 `/usr/local/bin/pnpm`、`/opt/homebrew/bin/pnpm` 中已有实例；缺失时修改 profile 前停止，报 `harness_external_pnpm_required`。不会自动安装 pnpm。自定义部署允许显式 runtime/cli/pnpm 参数；新版 CLI 仍要求该 pnpm 可从 PATH 启动。没有提供不依赖 pnpm 的通用安装产品。新电脑按 `harness-plugin/AGENT.md` 先做只读环境和校验检查；未取得目标、平台、条数和导航授权前，不做真实采集。

正式 web profile 仍是 0.1.0，主运行时版本为 15.2.1。本轮仅在临时 DSH_HOME 安装候选，没有推送、tag、Release 或主分支合并。根目录 GitHub bootstrap 仍指向历史已发布版本，不用于获取当前候选。

真实联调需当前授权明确平台、目标或允许使用的私有配置、条数，以及必要的导航权限。授权后先对已有 CDP 做 preflight，再顺序小规模采集；记录平台、请求数、成功数、失败原因、当前运行目录、manifest/XLSX 路径。风险停止不得重试；非风险失败只有纠正原因并重新 preflight 后才允许一次有限重试。

新增断点续采尚未实现：现有 XHS 检查点只是输出。PROJECT_CONTEXT.md 已提供具体方案，要求旧运行不可变、绑定配置及原生 ID、风险拒绝、重新获取单控制器租约、分别标注旧证据与新观察。确认该方案并重新核对并行任务归属后，才能修改控制器核心。不要把历史结果计为本次新鲜结果。
