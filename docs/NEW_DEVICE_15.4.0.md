# 新设备名单导入 — 15.4.0 / Bundle 0.4.0

先填写 Excel/CSV 的平台、博主名称、完整主页链接，导入后查看预览，再选择本次博主。只有完成选择才进入采集准备；空配置不会安装采集 runtime、创建空 run 或调用采集进程。名单导入只需要 Bundle 自带的 Node/ExcelJS，与 Python、浏览器、登录和网络无关。

| 入口 | 用途 |
| --- | --- |
| `media_missher_setup status` | 本地目标是否齐全；不会探测浏览器 |
| `template` | 生成空白 XLSX 和 CSV，没有可采集的示例目标 |
| `import` + `input_path` | 解析用户文件，返回私有预览、importId；不改当前目标 |
| `activate` + `import_id` + `rows` | 按预览行号选择，备份旧 profile，再原子保存 |
| `browser-open` + `confirm_open: true` | 用户明确打开独立 AI 浏览器；本地欢迎页引导手动登录 |
| `browser-check` | 只查本地 CDP 连接和所选平台页面；不验证登录、不采集 |

三列支持 `platform,creator_name,homepage_url` 或“平台、博主名称、主页链接”。平台支持 bilibili/xhs/douyin/weibo 及常用中文名。最多 200 位、文件不超过 2 MiB；拒绝空名称、重复主页身份、公式、合并单元格或命名范围、短链、笔记详情链接、非官方主页和异常压缩文件。不同平台或不同身份可以重名，实际识别以完整主页为准。链接的查询串和 fragment 不保存。ZIP 展开前后均限制总量，流式 XML 检查限制深度、节点数、行列坐标及共享字符串/样式数量，避免压缩文件虽小却在表格模型构建时耗尽内存。请在模板 Creators 工作表填写普通单元格，不添加合并单元格、命名范围、嵌入对象或 Excel 数据表。只接受规范的工作簿部件路径，表格内容会在模型构建前统一检查。

支持的主页为 B 站 space 数字 UID、小红书 user/profile 的 24 位十六进制 ID、抖音 user 的 secUid、微博 u/数字 UID 或用户数字主页。无需用户手工提取 UID，也不会按名称联网搜索。

一个名单中可以保存多位同平台博主，每次最多选择其中一位。预览行号从 1 开始，不含表头。激活后 `platform_uids` 兼容原控制器，`creator_targets` 保存显示资料，`active_platforms` 记录本次默认平台，优先于旧 Bundle 的 defaultPlatforms 默认值。其他平台旧目标和 CDP/数据路径等合法设置保留；旧 profile 按原字节备份。当前采集固定私有快照，中途激活其他目标不会改变当前请求。

导入文件和预览位于 profile 同级 `setup/import-<随机值>-<内容摘要>/`，目录 0700、文件 0600；旧 profile 备份位于 `setup/backups/`。上传的原始名单不自动删除。拒绝符号链接、硬链接、不安全权限和越界路径；遇到异常既有配置会保留文件并报错。

Git 工作树先在 `harness-plugin` 执行 `pnpm run build`，然后使用 `pnpm run setup:device -- template` 等同名动作。导入使用 `import --file /absolute/creators.xlsx`，激活使用 `activate --import-id <ID> --rows 1,3`。可额外指定 `--profile /absolute/private/profile.json`；采集 CLI 用同一个 `--profile`，默认平台选择与 Bundle 一致。

采集器仍只连接已有 CDP。新设备选择名单后，可以明确打开“AI 采集专用浏览器”：使用 profile 同级 `browser/chrome-profile/` 的独立私有资料目录和 `127.0.0.1:9223`；不会使用日常 Chrome 资料目录。欢迎页提供四平台官方入口，用户自行登录。此做法也符合 [Chrome 对远程调试使用独立资料目录的要求](https://developer.chrome.com/blog/remote-debugging-port?hl=zh-cn)。

只在 browser-open 成功确认本模块打开的会话后，备份旧 profile 并原子写入 cdp_url。会话摘要保存在私有管理标记中，端口属于其他会话时不接管。浏览器目录保留登录状态，不自动关闭或开机自启；采集 Stop 不关闭 Chrome。名单导入、选择、status、collect 都不自动启动它。

用户在 AI 浏览器手动登录并保持标签页后，返回 Harness 让 Agent 检查。browser-check 只读取本地 version/list 元数据，返回连接状态、所选平台页面是否存在；不会把这些结果冒充登录成功。真正的登录检查保留在有授权的采集前置检查。Agent 要继续引导缺页/登录/验证码处理，按用户已经给出的数量和导航范围执行首批，再展示 Excel、成功数和失败原因。完整陪同契约见 `harness-plugin/AGENT.md`。

Git CLI 同样支持 `pnpm run setup:device -- browser-open --confirm-open` 和 `pnpm run setup:device -- browser-check`。没有 Chrome 时按提示安装官方版本；端口/目录/环境冲突明确停止，不结束其他进程或修改日常浏览器。本机旧的 Chrome CDP LaunchAgent 是另一个既有配置，本轮未修改。


上一版的小红书 10 条/3 页上限、600 秒批次间隔、持续风险暂停、可靠停止和历史复用继续保留，见 [可靠性说明](XHS_RELIABILITY_15.3.0.md)。这些本地限制无法保证平台不会风控。

本地候选保留在隔离工作树中。安装包、模板和分层验收结果位于 `harness-plugin/dist/`；0.2.0/0.3.0 历史候选及其证据保留。未修改正式 profile/runtime，未提交、推送或发布。独立 AI 浏览器增量验收以 AI-BROWSER-EVIDENCE.json 为准；ONBOARDING-EVIDENCE.json 仅属于历史 0.3.0；合成数据和安装 smoke 不代表真实平台采集。

© 2026 Missher。原创软件未经许可禁止修改、衍生和二次传播，所有者及其受托维护工作可以继续；第三方组件保留原许可。完整 LICENSE 与第三方声明随新安装的 Bundle、runtime 和 Git 安装的技能交付。声明不等于著作权登记，也不能从技术上阻止复制或修改；未来公开方式见 [版权约定](../COPYRIGHT.md)。
