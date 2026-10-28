# Media@Missher · CDP

**供个人与 Agent 使用的本地媒体采集核心：通过 Chrome CDP 读取明确指定的平台内容，保留来源与质量信息，并按选择导出。**

Media@Missher CDP 将浏览器连接、平台解析、采集节奏、去重、字段校验和结果保存放在同一个 Python 运行时中。你准备 Chrome 和登录状态，指定作者或搜索词，程序按顺序收集当前页面能够提供的内容，保存到本地，再交给分析脚本或 Agent 继续处理。

当前代码基线为 **17.0.2**，采用 **[MIT 许可证](LICENSE)**。本仓提供独立的 Python CDP 核心、命令行入口、测试和文档，可以由支持本地进程调用的 Agent 使用；不依赖某个模型，也不要求安装 DeepSeek Harness。

适合整理指定作者的作品、追踪明确关键词、研究微博普通话题，以及把可取得的字段交给本地数据分析流程。每次采集都有目标、范围和停止条件；缺失字段、部分完成和风险停止会保留在结果中。

## 导航

- [快速开始](docs/quickstart.md)：环境准备、Chrome 配置、采集命令和常见问题。
- [数据能力](docs/data-capabilities.md)：各平台任务、字段、评论、截图及导出范围。
- [Agent 接入](docs/agent-integration.md)：进程调用方式、参数约束与结果处理。
- [架构说明](docs/architecture.md)：模块职责、数据流与维护入口。
- [贡献指南](CONTRIBUTING.md) · [安全说明](SECURITY.md) · [变更记录](CHANGELOG.md)。

## 能采集什么

下表描述代码覆盖的任务与字段。实际结果取决于页面结构、登录权限及平台当时返回的内容，不代表每个平台都已通过当前环境的实采验证。

| 平台 | 任务 | 主要内容 | 互动字段 |
| --- | --- | --- | --- |
| Bilibili | 指定 UP 主、关键词搜索 | 动态 ID / BV 号、标题、简介或动态正文、作者、时间、链接、封面 | 点赞、评论、转发、收藏；视频与动态指标分别保留来源 |
| 小红书 | 指定博主、关键词搜索 | 笔记 ID、标题、正文、作者、时间、标签、图片、可取得的视频链接 | 点赞、收藏、评论数、分享数；评论正文需单独请求 |
| 抖音 | 指定博主、关键词搜索 | 作品 ID、文案、作者、时间、封面、视频时长 | 点赞、评论、分享、收藏；播放数取决于响应 |
| 微博 | 指定博主、关键词搜索、普通话题 | 微博 ID、正文、作者、时间、链接、图片；话题可另存参与关系与公开主页资料 | 点赞、评论、转发 |
| X / Twitter | 指定账号、关键词搜索 | 推文 ID、正文、作者、时间、语言、媒体、回复/引用/转推关系 | 点赞、回复、转发、引用及可见的浏览、书签数 |

评论计数不等于评论正文。截图支持也随平台和任务而异，详见[能力说明](docs/data-capabilities.md)。媒体字段主要保存链接与元数据；本项目没有通用视频下载、转码、OCR 或语音转文字功能。

## 主要特性

- **独立 CDP 运行时**：通过 Playwright 连接使用者准备的 Chrome，复用该专用浏览器会话。
- **明确目标与顺序执行**：支持指定作者、关键词，以及显式多目标计划；校验页面、响应与请求目标之间的对应关系。
- **可追溯数据**：保留原始 ID、原文链接、采集时间、字段来源与质量标记；未知数值与真实的零分开处理。
- **增量与去重**：同一实体可补齐已观察到的缺失字段，保留已有值和来源；适用的计划支持精确续采。
- **有界采集**：使用条数、分页、时间预算和平台间隔限制；风险状态与正常冷却可以跨运行保留。
- **本地保存、按需导出**：采集 CLI 保存 JSON 和运行清单；Python 导出接口可生成 Excel、CSV、JSON、JSONL、SQLite。
- **便于 Agent 调用**：Agent 负责理解请求和呈现结果，运行时负责执行与校验。模型供应商、API Key 和推理设置由调用方管理。

## 五分钟了解入口

下载本仓源码并进入项目目录。推荐 Python 3.12，下面是 Linux / macOS 的虚拟环境示例：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r runtime/requirements.lock
python runtime/scripts/scrape_all.py --help
```

`--help` 只显示命令帮助。首次采集前，按照[快速开始](docs/quickstart.md#准备-chrome)用专用数据目录启动 Chrome，在浏览器内手动登录需要的平台，并确认本机 CDP 地址。

以下示例会实际访问平台；把占位符换成已确认的 Bilibili UP 主 UID：

```bash
python runtime/scripts/scrape_all.py creator \
  --platforms bilibili \
  --bilibili-uid YOUR_CONFIRMED_CREATOR_ID \
  --count 1 \
  --cdp-url http://127.0.0.1:9222 \
  --allow-navigation \
  --output-dir ./outputs
```

关键词搜索示例：

```bash
python runtime/scripts/scrape_all.py search \
  --platform bilibili \
  --keyword "城市漫步" \
  --count 3 \
  --cdp-url http://127.0.0.1:9222 \
  --allow-navigation \
  --output-dir ./outputs
```

`--allow-navigation` 允许本次任务按目标导航。更多参数用 `creator --help` 或 `search --help` 查看；示例不是无人值守的默认任务，也不会安装 Chrome 或代替你登录。

## 输出与后续处理

每次运行在所选输出目录下保存记录和运行清单。调用方应同时查看状态、实际条数、缺失字段和停止原因，不能仅凭生成了文件就判断完整成功。

| 方式 | 用途 |
| --- | --- |
| 采集 CLI 的 JSON 输出 | 保存原始结果、供脚本或 Agent 读取 |
| Python 导出接口的 Excel / CSV | 人工筛选、表格分析、工具导入 |
| Python 导出接口的 JSON / JSONL / SQLite | 程序处理、流式读取、本地查询 |

导出接口位于 [exporting.py](runtime/media_missher_runtime/exporting.py)，只读取已保存、已验证的记录，不会为了补齐字段再次抓取。采集 CLI 的 `--format` 目前仅支持 `json`；其他格式通过 Python 接口使用，详见[导出说明](docs/data-capabilities.md#导出接口)。

[示例数据](examples/README.md)使用虚构作者和 `example.invalid` 链接，帮助理解字段含义；不作为真实采集结果或完整协议模板。

## Agent 与宿主

Codex、Hermes、DeepSeek Harness 或其他 Agent，只要具备受控的本地进程调用能力，就可以编写适配器调用这里的 Python 入口。是否能直接调用仍取决于具体宿主的文件权限、进程工具和配置。

本仓没有预装的 DSH Bundle、npm Agent 包或 MCP 服务，不能直接把它填入 DSH 的“添加插件”当作组合包安装。原完整产品的安装器和宿主适配不属于本次 CDP 核心导出。[接入示例与约束](docs/agent-integration.md)。

## 使用边界

登录、验证码和权限问题由使用者在浏览器中处理；检测到相关阻断或目标歧义时，程序停止或返回明确诊断。没有验证码破解、账号轮换、代理池或自动解除风险状态的功能。

当前默认平台开始间隔为 Bilibili / 抖音 60 秒、微博 90 秒、X 120 秒、小红书 600 秒。小红书单批最多 10 条 / 3 页，其他平台最多 20 条 / 3 页；这些是工程限制，不是平台承诺的安全阈值，也不能保证账号不会受到限制。完整行为以源码和任务参数为准。

仅采集你有权访问、处理和保存的内容。CDP 端口、浏览器登录状态和输出数据都应留在本机受控范围内；不要将真实结果或凭据提交到仓库。

## 目录

```text
runtime/
  media_missher_runtime/   连接、平台解析、计划、校验、保存与导出
  scripts/                scrape_all.py 与各平台入口
  requirements.lock       固定版本的直接运行依赖
tests/                    原有核心测试及合成夹具
docs/                     使用、能力、接入与架构说明
examples/                 虚构数据说明
LICENSE                   MIT
THIRD_PARTY_NOTICES.md     第三方组件说明
SOURCE_MANIFEST.json      原样导出的源码与测试摘要
SHA256SUMS.txt             公开文件校验清单
```

## 验证状态与贡献

本次独立导出保留 17.0.2 核心源码及相应测试。当前完成了来源、文件摘要、文档链接和静态一致性检查；**独立导出的运行测试、真实 Chrome 和平台实采仍待验证**。原完整产品的历史测试、宿主加载或安装结果不作为本仓通过证明，见[验证记录](docs/validation.md)。

欢迎通过问题报告和补丁改进解析可靠性、文档和测试。提交时请提供平台、任务类型、版本、复现步骤和脱敏诊断，优先使用合成夹具。[贡献指南](CONTRIBUTING.md)说明了测试方式和变更要求。

## 许可证

Copyright (c) 2026 Missher。本仓实际提供的原创源码和文档采用 [MIT](LICENSE)。第三方组件、平台内容和用户数据分别保留自身权利，参见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
