# Media@Missher 17.0.0

为 Agent 提供媒体采集、私有证据保存和选择导出。**仅使用 Chrome CDP**，支持 Bilibili、小红书、抖音、微博和 X。通用 CLI、共享 Skill、DSH Bundle 共用同一采集核心。

运行时、Agent CLI 和 DSH Bundle 统一为 **17.0.0**。源码和分发保持私有；© 2026 Missher，原创软件采用[专有许可](LICENSE)，第三方依赖遵循[各自许可](THIRD_PARTY_NOTICES.md)。

## 从这里开始

| 目的 | 入口 |
| --- | --- |
| 看能抓什么、字段有哪些条件限制 | [数据能力与字段说明](DATA_CAPABILITIES.md) |
| 安装、导入博主、准备 Chrome、采集和导出 | [中文快速开始](QUICKSTART.md) |
| 让 Codex、Hermes 等 Agent 接入 | [Agent 安装指南](AGENT_INSTALL.md) |
| 给 DeepSeek Harness 接入 | [DSH Bundle 说明](harness-plugin/README.md)、[Agent 操作说明](harness-plugin/AGENT.md) |
| 看结果形态 | [JSON 示例](examples/posts.sample.json)、[CSV 示例](examples/posts.sample.csv)；全部为虚构数据 |
| 查看本版交付及验证边界 | [17.0.0 交付记录](docs/releases/v17.0.0.md) |
| 继续维护 | [项目摘要](PROJECT_CONTEXT.md)、[交接记录](HANDOVER.md) |

## 能力概览

作品字段包括标题/正文、作者、时间、原文链接、平台原生 ID 和可取得的互动数；各平台另有图片、视频链接或其他字段。小红书可按需请求评论明细和截图。微博普通话题分开保存帖子、观察到的发帖者关系与公开主页资料。详情见字段说明，不把缺失值写成零。

支持显式多目标，按顺序执行并精确绑定目标。先保存私有结果和运行清单；随后选择目标、记录类别、字段和格式，离线导出 Excel、CSV、JSON、JSONL 或 SQLite。

保持单一浏览器所有者；遇到风险、挑战、登录墙或身份歧义立即停止。小红书每批最多 10 条/3 页、两批开始间隔至少 600 秒。Computer Use 与 BrowserSkill 已退役，旧请求明确拒绝，历史结果仍可读取和导出。

## 交付文件

产物位于 [`dist/v17.0.0/`](dist/v17.0.0/)，统一校验文件为 `SHA256SUMS.txt`：

- `Media-Missher-v17.0.0.zip`：完整交付包，含安装入口、DSH Bundle、源码、字段文档、示例和验证记录。
- `Media-Missher-Agent-Setup-v17.0.0.zip`：通用 Agent 安装包。
- `missher-media-missher-17.0.0.tgz`：通用 CLI 包。
- `dsh-media-missher-17.0.0.tgz`：macOS DSH Bundle。
- `Media-Missher-Source-v17.0.0.zip`：源码与测试，解压后可重新构建。

首次安装依赖需要可用的包源；本包不是全部依赖离线镜像。打包和上传 Git 不会修改本机已安装的 Skill、运行时或 Harness profile。

## 环境与验证

通用 CLI 要求 Node.js >=22.19、npm；采集运行时支持 Python 3.11/3.12。macOS/Linux 使用同一包，Windows 通过 WSL2/WSLg。浏览器、Agent 命令和私有文件须处于匹配环境。DSH Bundle 当前限定 macOS。模型和推理级别沿用宿主设置，本项目不包含模型 API 客户端。

准确验证结果见交付包 `VALIDATION.json`。离线测试、本地 Chrome CDP、隔离安装、真实宿主注册及真实平台采集分别记录。本次交付没有执行真实平台采集；合成数据和安装成功不代表实采验收。历史 DSH 0.6.1 兼容分支仍保留，未自动合入本版。

## 开发和打包

```sh
pnpm --dir harness-plugin install --frozen-lockfile
npm install --prefix agent-plugin --ignore-scripts --no-audit --no-fund --no-package-lock
node tools/build_distribution.mjs
node tools/verify_distribution.mjs dist/v17.0.0
```

完整测试命令位于 `.github/workflows/ci.yml`。`runtime/` 为 Python 核心，`media-missher/` 为共享 Skill 与入口，`agent-plugin/` 为通用 CLI，`harness-plugin/` 为 DSH 适配。交付排除浏览器目录、凭据、真实采集结果、依赖缓存和本机证据目录。

旧 15.6.0 候选的版本、安装和归档摘要见[历史基准](docs/CURRENT_BASELINE.md)。根目录旧 GitHub bootstrap 只对应 v15.2.1，不用于本版安装。
