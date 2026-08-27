# Media@Missher

Media@Missher 是 Missher 私用的四平台内容采集工具。当前版本把已经验证过的 Bilibili、小红书、抖音和微博运行时封装成了原生 DeepSeek Harness Bundle：安装后，Agent 可以直接发起抓取，默认一次顺序抓取四个平台各 10 条，并返回可检查的 Excel 表格。

## 一键安装到 DeepSeek Harness

适用环境：macOS，已安装 `/Applications/DeepSeek Harness.app`，且 Media@Missher 的私有浏览器 profile 已配置完成。

1. 下载或克隆这个私有仓库。
2. 双击根目录的 **`Install Media@Missher Harness Plugin.command`**。
3. 安装完成后点击弹窗里的“重启 Harness”。安装器会请求 Harness 正常退出、等待退出完成，再重新打开并载入插件；不会强制结束进程。

安装器直接使用 Harness.app 自带的 Electron、CLI 和 pnpm，不要求用户安装 Node.js、pnpm，也不要求打开终端。它会先校验内置 Bundle，把精确字节复制到按 SHA 命名的私有 `~/.dsh/artifacts/media-missher/` 路径，再备份当前 `web` profile 的 `package.json`；最后同时确认已安装入口字节和有效 Cordis 配置，仓库之后移动或删除也不会破坏依赖来源。

如果 macOS 第一次拦截未签名的私有脚本，请在 Finder 中右键该文件并选择“打开”。这不是公开签名发行版；不要关闭系统安全机制。

## 怎么用

在 Harness 对 Agent 说：

> 用 Media@Missher 抓一下，给我表格。

Agent 不传参数时会调用 `media_missher_collect`，等价于：

- 平台：Bilibili、小红书、抖音、微博
- 数量：每个平台 10 条，共最多 40 条
- 执行：逐平台顺序运行，不并发占用浏览器
- 输出：一个 `.xlsx` 工作簿
- 工作表：`Summary`、`All Platforms` 和四个平台独立表
- 小红书评论：默认不额外抓取
- 页面导航：本次明确调用即授权在既有 Media 浏览器中进行精确目标导航

如果某个平台出现非风险短缺或超时，工具仍会把其余已验证记录写入同样的六表工作簿，并在 `Summary` 中明确标出该平台的请求数、实得数和固定诊断码，不会把已抓到的数据隐藏成 0 条。

也可以明确指定平台和数量，例如“只抓 B 站和抖音，各 5 条”。Agent 结果只返回状态、数量和本地文件路径；原始记录只保存在私有运行目录和工作簿中。

## 数据和安全边界

- 只连接已经存在且已登录的 Media Chrome/CDP 浏览器，不新开或重配浏览器。
- UID、Cookie、凭据、页面正文和原始记录不会进入 Harness 工具参数或结果正文。
- 运行目录权限为 `0700`，工作簿和 profile 权限为 `0600`。
- 平台风险、挑战页、HTTP 403/429、上下文歧义会立即安全停止；不会盲目重试。
- 不启用飞书、不生成公开上传、不包含运行数据、截图、Cookie 或凭据。

## 安装包与开发验证

唯一可安装 Bundle 是：

```text
harness-plugin/dist/dsh-media-missher-0.1.0.tgz
```

开发者在 `harness-plugin/` 下可运行：

```bash
pnpm install --frozen-lockfile
pnpm test
pnpm exec tsc --noEmit
pnpm run build
pnpm run pack:bundle
pnpm run verify:package -- dist/dsh-media-missher-0.1.0.tgz
pnpm run smoke:native -- --archive dist/dsh-media-missher-0.1.0.tgz
```

`smoke:native` 使用临时 `DSH_HOME` 验证真实 Harness CLI 安装、默认工具执行、六表工作簿复开、卸载以及相邻状态保留，不修改正式 profile。

运行时架构、故障边界和历史验收记录见 [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)，Harness Bundle 的设计与实现计划见 `docs/superpowers/`。

## 私有分发边界

本仓库仅供 Missher 私用和备份。仓库没有选定可公开分发的整体许可证；在完成来源与许可证复核之前，请保持仓库和 Bundle 私有，不发布到 npm 或公开 GitHub Release。
