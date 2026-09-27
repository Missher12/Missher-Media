# Media@Missher

当前候选采用 CDP 主引擎和可选 Computer Use，通用 CLI/共享 Skill 服务可执行本地命令的 Agent，DSH 使用同一核心的薄插件。BrowserSkill 已退出活动运行链，历史数据仍可只读导出。功能规格见[升级规格](docs/CDP_COMPUTER_USE_UPGRADE_SPEC_2026-09-20.md)，Astra 接入与本轮验证见[迁移记录](docs/ASTRA_MIGRATION_2026-09-23.md)。Computer Use 仍需真实宿主适配，离线候选不能作为真实平台通过的证明。

© 2026 Missher。保留所有权利。原创部分未经许可禁止修改、衍生及二次传播；第三方依赖保留原许可。详见 LICENSE 与版权说明。

Media@Missher 是 Missher 的媒体采集工具，候选接口覆盖 Bilibili、小红书、抖音、微博和 X，各模式的可用性与真实验收分别记录。当前本地候选为运行时 **15.6.0**、通用 Agent CLI **0.1.0**、Harness Bundle **0.6.0**。通用入口采用 CLI＋共享 Skill，让能执行本地命令的 Agent 按一份安装指引完成接入。源码仓库继续私有，原创部分采用专有许可；公共下载地址尚未发布。

模型由宿主选择。Codex 使用 GPT-6 Astra 时沿用用户选定的推理级别，通过已安装 Skill 调用同一运行时或 CLI；本项目不内置模型 API 客户端。接入时分别核对宿主模型、Skill 发现、CLI/运行时版本和实际工具调用，不能用配置或安装成功代替运行验证。

## 给任意支持命令行的 Agent 接入

将 `agent-plugin/dist/Media-Missher-Agent-Setup-v0.1.0.zip` 解压后，把文件夹和这句话交给 Agent：

> 按照这个文件夹里的 AGENT_INSTALL.md 安装 Media@Missher，给你自己安装操作 Skill，再带我导入博主名单、登录平台并完成首批授权采集。

[安装指引](AGENT_INSTALL.md) 提供检查、安装、技能发现、Excel/CSV 名单、独立 AI 浏览器登录、采集及结果交付全过程。通用入口不依赖 Harness；`media-missher --help` 提供自描述命令和 JSON 返回值。macOS/Linux 使用同一包，Windows 入口运行于 WSL2/WSLg。Windows 原生采集不在本候选范围，Linux/Windows 原生验证情况见 [本版说明](docs/AGENT_ENTRY_15.6.0.md)。

名单为空时不安装 Python runtime、不启动 CDP、不采集。开浏览器和采集继续依据用户具体意图。既有共享锁、小红书 10 条/3 页/600 秒及持续风险暂停全部保留，背景见 [15.5.0 共享保护](docs/SHARED_SAFETY_15.5.0.md) 和 [15.3.0 小红书说明](docs/XHS_RELIABILITY_15.3.0.md)。

## 给 Harness Agent 的新电脑首启指南

请先阅读 [Harness Agent 首次接入指南](harness-plugin/AGENT.md)，再执行安装或采集。它定义了新电脑上的环境检查、外层和内层校验、Harness profile 接入、私有 profile、明确授权、结果核验和故障处理。Markdown 负责让 Agent 按正确顺序工作；实际工具注册仍由 Bundle 的 `package.json`、`cordis.patch.yml` 和 `lib/index.js` 完成。

此专用 Harness Bundle 仍限定 macOS，独立于上面的通用 CLI 入口。新版 Harness 可能要求本机已经存在 `/usr/local/bin/pnpm` 或 `/opt/homebrew/bin/pnpm`；安装器缺少它时会停止，不会自动下载或安装 pnpm。BrowserSkill 已退役，不由本插件安装或启用。

## 历史 v15.2.1 Release 安装流程（Bundle 0.1.0）

下面的 GitHub bootstrap 只对应历史已发布的 Bundle 0.1.0，不用于获取当前 0.6.0 本地候选。

适用环境：macOS，已安装 `/Applications/DeepSeek Harness.app` 和 GitHub CLI（`gh`），`gh` 已登录并能读取私有仓库 `Missher12/media-missher`，且 Media@Missher 的私有浏览器 profile 已配置完成。命令不接收、显示或保存 GitHub token。

把下面整行交给 DeepSeek Harness Agent 执行，或粘贴到终端：

```bash
MEDIA_BOOTSTRAP_DIR="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/media-missher-github.XXXXXX")" && gh release download v15.2.1 --repo Missher12/media-missher --pattern 'Install-Media-Missher-from-GitHub.command' --dir "$MEDIA_BOOTSTRAP_DIR" && /bin/chmod 700 "$MEDIA_BOOTSTRAP_DIR/Install-Media-Missher-from-GitHub.command" && /usr/bin/open "$MEDIA_BOOTSTRAP_DIR/Install-Media-Missher-from-GitHub.command"
```

下面这条命令从私有 GitHub Release 拉取一个很小的引导器，并在独立的 Terminal 进程中继续安装，所以 Harness 可以正常退出和重启。引导器再下载该 Release 内的完整 Setup ZIP 与独立 SHA-256 文件，校验后才启动其中的内层安装器。安装完成后点击弹窗里的“重启 Harness”；安装器只请求 Harness 正常退出，不会强制结束进程。这是历史 v15.2.1 Release 的路径，本仓库工作树不再自带该 ZIP，也不再分发根目录的一键安装脚本。

安装器直接使用 Harness.app 自带的 Electron、CLI 和 pnpm，不要求用户安装 Node.js、pnpm，也不要求打开终端。它会先校验内置 Bundle，把精确字节复制到按 SHA 命名的私有 `~/.dsh/artifacts/media-missher/` 路径，再备份当前 `web` profile 的 `package.json`；最后同时确认已安装入口字节和有效 Cordis 配置，仓库之后移动或删除也不会破坏依赖来源。

如果 macOS 第一次拦截未签名的私有脚本，请在 Finder 中右键该文件并选择“打开”。这不是公开签名发行版；不要关闭系统安全机制。

## 怎么用

在 Harness 对 Agent 说：

> 用 Media@Missher 抓一下，给我表格。

Agent 根据本次授权调用 `media_missher_collect`；未显式提供的选项使用已选目标和受支持的默认值：

- 目标：使用本次明确目标，或私有 profile 已激活的目标；空设备先补齐目标
- 数量：默认 fixed，每个目标 10 条；同平台可以有多个目标
- 执行：顺序运行，每次冻结 `cdp` 或 `computer_use`，单一浏览器所有者
- 保存：先写私有记录、manifest、检查点和实际停止原因
- 导出：按用户选择的目标、记录类别、字段和格式调用 `media_missher_runs export`
- 小红书评论：默认不额外抓取
- 页面导航：默认关闭，只有本次调用明确传入 `allow_navigation: true` 才允许在既有 Media 浏览器中进行精确目标导航

采集本身不自动创建 Excel。先展示实际数量、字段覆盖和停止原因；用户已说明导出要求时直接沿用，缺少会改变导出内容的选择时再询问。导出只读取已验证的保存结果，支持 xlsx、csv、json、jsonl 和 sqlite，不补抓缺失字段。partial、risk-stopped 和 cancelled 的已验证前缀仍可导出，并保留原状态。

也可以明确指定平台和数量，例如“只抓 B 站和抖音，各 5 条”。Agent 报告状态、数量和本地证据路径；只有导出成功后才提供导出文件链接。原始记录保存在私有运行目录和用户选择的导出文件中。

## 数据和安全边界

- 采集器只连接已有 CDP。新设备选好名单后，可明确使用 browser-open 打开独立 AI 采集浏览器并手动登录；不会自动启动或重配日常 Chrome。
- 显式目标可使用用户提供的官方主页、UID 或 handle；不得猜测身份。Cookie、凭据、页面正文和原始记录不进入工具参数或结果正文。
- 运行目录权限为 `0700`，工作簿和 profile 权限为 `0600`。
- 平台风险、挑战页、HTTP 403/429、上下文歧义会立即安全停止；不会盲目重试。
- 不启用飞书、不生成公开上传、不包含运行数据、截图、Cookie 或凭据。

## 安装包与开发验证

Harness 自包含 Setup ZIP 分发已退役；独立 Agent Setup 保留。Harness 从当前源码重建 Bundle 归档：

```text
harness-plugin/dist/dsh-media-missher-0.6.0.tgz
```

历史 Release 资产（例如 `dsh-media-missher-0.1.0.tgz` 与 `Media-Missher-Harness-Setup-v15.2.1.zip`）只保留在已发布的私有 Release 中，不再随工作树分发；不要将两组版本混用。

开发者在 `harness-plugin/` 下可运行：

```bash
pnpm install --frozen-lockfile
pnpm test
pnpm exec tsc --noEmit
pnpm run build
pnpm run pack:bundle
pnpm run verify:package -- --write-checksum dist/dsh-media-missher-0.6.0.tgz
pnpm run smoke:native -- --archive dist/dsh-media-missher-0.6.0.tgz
```

`pack:bundle` 会通过 `prepack` 重新构建入口并暂存 payload；`verify:package` 自行生成并校验 `dist/SHA256SUMS.txt`，不依赖测试写入工作区。

`smoke:native` 使用临时 `DSH_HOME` 验证真实 Harness CLI 安装、采集工具合成结果、显式离线导出、历史/状态操作、卸载以及相邻状态保留，不修改正式 profile，也不发起平台采集。

运行时架构、故障边界和历史验收记录见 [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)，Harness Bundle 的设计与实现计划见 `docs/superpowers/`。

## 私有分发边界

本仓库仅供 Missher 私用、备份及另行授权的使用。原创部分采用 [LICENSE](LICENSE) 所载的专有授权，未经许可禁止修改、衍生或二传；第三方部分保留原许可。当前仓库、Release 和 Bundle 保持私有。未来公开方式由 Missher 另行决定，发布前核对来源、第三方许可与平台条款，见 [版权与发布约定](COPYRIGHT.md)。历史 `v15.2.1` 资产及此前有效授权不被本声明追溯改写。
