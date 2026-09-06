---
name: media-missher-agent-onboarding
description: Onboard the private Media@Missher Harness Bundle on a fresh macOS computer, then run one authorized creator collection and report verifiable local evidence.
contentType: How-to
bundleId: media-missher
packageName: dsh-media-missher
bundleVersion: 0.1.1
productVersion: 15.2.1
supportedOS: macOS
entryTool: media_missher_collect
---

# 在新电脑接入 Media@Missher

这份文件是给 Harness Agent 的首启契约。它只负责安装、检查和调用私有的 `dsh-media-missher` Bundle。Bundle 0.1.1 内置的采集主项目版本是 15.2.1，当前支持 macOS。

## 先记住这条路径

```text
Agent 读取本文件
  -> 校验本地 Setup 和内层 tgz
  -> 安装到 Harness web profile
  -> 重启 Harness 并确认 Cordis 配置
  -> 读取 mode-0600 私有 profile.json
  -> 获得本次明确授权后调用 media_missher_collect
  -> 只返回状态、计数和私有 manifest/XLSX 路径
```

Markdown 不会自行注册工具。真正的接入由安装包的 `package.json`、`cordis.patch.yml`、`lib/index.js` 和 Harness profile 完成。本文件让 Agent 按同一条可核验路径操作，不能替代安装或授权。

## 1. 首次只做环境检查

先执行只读检查，不发起平台请求，不打开新页面，不安装任何浏览器辅助工具。

- 运行系统必须是 macOS。Windows 或 Linux 直接报告 `unsupported_platform`。
- 必须存在 DeepSeek Harness.app。找不到时报告 `harness_layout_unsupported`。
- 必须有一个已经登录、由用户提供并允许复用的 Media 浏览器和 CDP 端点。不要启动、重配或替换 Chrome。
- 新版 Harness 使用自己的 Node 和 CLI，但可能没有 pnpm。先检查 `/usr/local/bin/pnpm` 或 `/opt/homebrew/bin/pnpm`。缺少时停止并报告 `harness_external_pnpm_required`，不要用 `curl | sh`、npm 全局安装或静默下载来补齐。
- 旧版 Harness 布局可以使用 App 内的 pnpm。不要根据版本号猜路径，交给安装器探测，或把真实路径作为参数传给安装器。
- 只使用用户已经拿到的本地 Setup。不要凭空拼接下载 URL，不要从公开仓库或 npm 获取私有 Bundle。

如果只有 ZIP，必须同时取得其独立的 SHA-256 文件。没有外层校验值时，停在安装前并报告 `setup_checksum_missing`。

## 2. 校验并安装本地 Bundle

先在包含 Setup ZIP 和外层校验文件的目录执行校验。下面的变量只表示本地文件路径，不要把 Cookie、UID 或其他用户数据写进命令行。

```bash
DELIVERY_DIR="/path/to/media-missher-delivery"
/usr/bin/shasum -a 256 -c "$DELIVERY_DIR/SETUP-SHA256.txt"
```

校验通过后，解压并运行 Setup 中的安装器：

```bash
/usr/bin/unzip -q "$DELIVERY_DIR/Media-Missher-Harness-Setup-bundle-v0.1.1.zip" -d "/path/to/unpacked"
/bin/chmod 700 "/path/to/unpacked/Media-Missher-Harness-Setup/Install Media@Missher Harness Plugin.command"
/usr/bin/open "/path/to/unpacked/Media-Missher-Harness-Setup/Install Media@Missher Harness Plugin.command"
```

安装器会在修改 `web` profile 前验证内层 `dsh-media-missher-0.1.1.tgz`，把精确字节放入当前 `DSH_HOME` 的私有 SHA 命名归档，备份已有 profile 清单，并确认入口可以实际导入、有效配置包含 `id: media-missher` 与 `name: dsh-media-missher`。安装失败时保留备份，不要自动删除或重置 profile。

如果 Agent 需要 CLI 诊断，可以使用安装器探测到的同一 Harness CLI：

```bash
dsh --profile web --dump-config
```

输出必须同时出现 `media-missher` 和 `dsh-media-missher`。只看到文件已经复制，或只看到进程退出码为 0，都不足以证明接入成功。安装器完成后重启 Harness，再重新检查工具是否出现。

## 3. 准备私有 profile

Bundle 不从工具参数接收 UID、Cookie 或凭据。创作者采集所需的目标只放在仓库和已安装技能之外的 mode-`0600` 文件中，默认路径是 `~/.config/media-missher/profile.json`。

```json
{
  "cdp_url": "http://127.0.0.1:9222",
  "platform_uids": {
    "bilibili": "your_bilibili_uid",
    "xhs": "your_xhs_uid",
    "douyin": "your_douyin_uid",
    "weibo": "your_weibo_uid"
  }
}
```

示例值不是可用目标。没有用户提供的真实目标和已经登录的浏览器时，停在配置检查并报告缺少创作者目标，不要猜 UID、写入凭据或尝试登录。控制器会把这类前置条件失败归类为 `preflight-failed`。写入后检查：

```bash
/bin/chmod 600 "$HOME/.config/media-missher/profile.json"
/usr/bin/stat -f '%Lp %N' "$HOME/.config/media-missher/profile.json"
```

创作者采集要求每个选中平台都有非空 UID。这个 Bundle 暴露的是创作者采集工具，不提供关键词搜索入口。遇到搜索需求时先报告当前 Bundle 不支持该范围，不要把它伪装成创作者采集。

## 4. 取得本次采集授权

每次真实采集前，确认用户已经给出四件事：平台、每个平台条数、要使用的私有 profile 或目标范围、是否允许在现有浏览器上下文中进行精确导航。只给出“抓一下”而没有这些条件时，先回报缺少授权，不发起请求。

先做最小范围、单控制器、逐平台的请求。默认导航是关闭的：

```json
{
  "platforms": "bilibili",
  "count": 1,
  "xhs_comments": 0,
  "allow_navigation": false
}
```

只有用户明确授权本次精确目标导航时，才将 `allow_navigation` 设为 `true`：

```json
{
  "platforms": "bilibili,xhs",
  "count": 2,
  "xhs_comments": 0,
  "allow_navigation": true
}
```

平台值只能是 `bilibili`、`xhs`、`douyin`、`weibo`，不能重复、留空或混入未知值。`count` 为 1 到 50 的整数。请求小红书评论时必须选中 `xhs`，评论数为 0 到 100 的整数。

保持浏览器单一控制者。平台按 Bundle 的规范顺序串行执行，不并发占用浏览器；不要自动启用或安装 BrowserSkill；不要绕过登录、验证码、挑战页、403/429 或平台访问限制。风险信号出现后立即停止，不重试，不导航到未授权主机。

## 5. 按结构核验结果

工具结果必须原样保留以下字段，并向用户报告绝对路径：`status`、`platforms`、`requestedPerPlatform`、`totalCollected`、`runDirectory`、`manifestPath`、`workbookPath`、`summary`。

允许的状态是：

| 状态 | Agent 动作 |
| --- | --- |
| `success` | 报告每个平台请求数、成功数和 XLSX 路径 |
| `partial` | 报告短缺平台、固定诊断码和已经验证的记录；保留 XLSX |
| `risk-stopped` | 报告平台和风险诊断；停止后续平台，不重试 |
| `preflight-failed` | 报告环境或登录前置条件；修正后重新做 preflight |
| `failed` | 报告固定错误和运行目录；不要用“脚本正常退出”代替结果 |

真实测试记录平台、请求数、成功数、失败原因和输出位置。合成 fixture、native smoke、离线测试或安装成功都不能写成真实平台成功。原始 JSON、Cookie、页面正文和凭据不放进 Agent 回复；只引用私有 `runDirectory`、manifest 和 workbook。

## 6. 故障处理和卸载

先按错误码采取单一修正：

| 错误码 | 下一步 |
| --- | --- |
| `setup_checksum_missing` | 获取外层 ZIP 校验文件，停止安装 |
| `harness_external_pnpm_required` | 由用户准备已有 pnpm，或改用已支持的旧版 Harness 布局 |
| `harness_layout_unsupported` | 确认 Harness.app 路径和版本，使用安装器的显式 runtime、CLI、pnpm 参数 |
| `harness_plugin_add_failed` | 保留 profile 备份，读取错误输出，不删除运行目录 |
| `harness_plugin_load_failed` / `harness_plugin_not_active` | 不宣称接入成功，检查入口导入和 `--dump-config` |
| 创作者目标缺失 | 让用户在私有 profile 中补齐选中平台目标，并重新检查权限 |
| `risk-stopped` 或 HTTP 403/429 | 停止，不重试，不绕过限制 |
| `partial` 或超时 | 只在用户修正明确原因后重新 preflight，再允许一次小批量重试 |

需要移除时使用 Harness CLI：

```bash
dsh plugin --profile web remove dsh-media-missher
```

卸载不删除 `~/.config/media-missher/profile.json`、私有运行目录、备份或 SHA 归档。清理这些数据必须由用户单独提出并指定精确路径。

## 给 Agent 的首启提示词

可以把下面这段作为首次交接消息：

```text
请按 harness-plugin/AGENT.md 接入 Media@Missher。先只做 macOS、Harness 布局、外层 ZIP SHA-256、内层 Bundle、pnpm、profile 权限和 --dump-config 检查，不进行真实采集。确认用户明确提供平台、条数、私有目标和本次导航授权后，再用 media_missher_collect 做一个平台的一条记录；默认 allow_navigation=false。结果必须列出 status、平台请求数/成功数、失败原因、runDirectory、manifestPath、workbookPath。不要安装或启用 BrowserSkill，不要读取或回显 Cookie、凭据、原始记录。
```
