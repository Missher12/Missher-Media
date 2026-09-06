# dsh-media-missher 0.1.1 local maintenance candidate

Bundle 版本为 **0.1.1**，内置采集主项目仍为 **15.2.1**。本候选未发布，正式 profile 尚未升级。旧版安装与验收记录见根目录 PROJECT_CONTEXT.md 的历史章节。

当前 macOS Harness 使用 `Contents/Resources/runtime/node/bin/node` 与 `runtime/app/lib/bin.js`。安装器会自动识别此布局，并只使用 `/usr/local/bin/pnpm` 或 `/opt/homebrew/bin/pnpm` 中已经安装的 pnpm；缺少时在修改 profile 前报 `harness_external_pnpm_required`。不会自动下载安装 pnpm。旧版 `app.asar.unpacked` 布局继续使用自带 Electron/CLI/pnpm。自定义路径可通过 `--runtime`、`--cli`、`--pnpm` 提供。

候选 Setup 为 `dist/Media-Missher-Harness-Setup-bundle-v0.1.1.zip`。根目录历史 GitHub bootstrap 仍指向既有 v15.2.1 Release，不用于获取本候选。安装器备份 profile、固定 SHA 命名归档、校验入口字节、实际导入入口并检查有效配置；导入失败不再报告安装成功。失败后保留备份供诊断，不自动重置用户配置。

本版本直接使用 Harness 公开 ToolDefinition/JSON Schema 注册接口，SDK 只参与开发类型检查。工具入口不依赖宿主内部模块在 profile 中可被 Node 解析。保留默认 4x10、正数条数上限、单控制器顺序采集和原有导航默认配置；只有明确授权的采集请求才能调用工具。浏览器辅助和截图仍为控制器默认 off。

新增校验覆盖空平台项、非法类型、未知参数、无小红书平台的评论请求；导出前按原生 ID 优先级保留首次出现的记录，对齐 Python 校验器。计数不足会降为 partial，风险状态优先，不导出请求外平台。证据必须属于本次文件系统时间边界并具有私有权限，诊断只接受固定枚举。字符串长 ID 保持原值，不安全的数值 ID 报错而不制造已损失精度的文本。原始 JSON 不改写。

本版本不自动重试、不接收旧检查点、不合并历史采集结果。超时/取消只终止本次进程组，SIGTERM 后最多一秒转为 SIGKILL；不终止已有 Chrome。真实测试必须另有平台、目标/允许使用的私有配置、条数及导航授权。

验证顺序：`pnpm install --frozen-lockfile`、`pnpm exec tsc --noEmit`、`pnpm test`（会从当前源码重打 Bundle 和 Setup）、`pnpm run smoke:native`。native smoke 使用独立 DSH_HOME，采集部分为合成 fixture，不能视为真实平台验收。

---

# dsh-media-missher

`dsh-media-missher` 是 Media@Missher V15.2.1 的私有 macOS DeepSeek Harness Bundle。它向 Agent 注册一个工具：`media_missher_collect`。

## 用户安装

本候选请使用本地 `Media-Missher-Harness-Setup-bundle-v0.1.1.zip`，解压后双击 `Install Media@Missher Harness Plugin.command`。已经下载候选完整工作树时，也可以直接双击根目录的同名脚本。内层安装器使用 Harness.app 自带运行时；新版宿主还需要本机已有 pnpm，旧版使用内置 pnpm。不要用历史 GitHub bootstrap 安装本候选。

默认无参数调用会顺序抓取 `bilibili,xhs,douyin,weibo`，每个平台 10 条，并在本次私有运行目录中创建 Excel 工作簿。工作簿包含汇总表、全平台合并表和四个平台独立表。控制器以 `validation.diagnostics` 声明精确 manifest；即使一个平台出现非风险失败，Bundle 仍会验证并投影其余平台记录，在汇总表保留短缺诊断。

## Bundle 结构

- `cordis.patch.yml`：Harness profile 的 Cordis 配置片段
- `lib/index.js`：Agent 工具与运行时适配器
- `payload/`：严格白名单暂存的 Media@Missher 15.2.1 运行时
- `scripts/install-current-profile.mjs`：验包、备份、安装和有效配置确认
- `scripts/native-smoke.mjs`：隔离原生安装生命周期验证
- `scripts/build-setup.mjs`：按固定白名单生成可复现的私有 Setup ZIP
- `scripts/verify-setup.mjs`：校验 ZIP 路径、文件集合、来源字节与内层 Bundle

Bundle 只允许 macOS。工具参数中不接受任何 UID 或凭据；这些值只从 mode-`0600` 的私有 `profile.json` 读取。模型侧结果仅包含固定状态、计数和本地证据路径。

## 开发命令

```bash
pnpm install --frozen-lockfile
pnpm test
pnpm exec tsc --noEmit
pnpm run build
pnpm run pack:bundle
pnpm run verify:package -- dist/dsh-media-missher-0.1.1.tgz
pnpm run pack:setup
pnpm run verify:setup -- dist/Media-Missher-Harness-Setup-bundle-v0.1.1.zip
pnpm run smoke:native -- --archive dist/dsh-media-missher-0.1.1.tgz
```

打包会先重建 TypeScript 入口，再从仓库中的精确白名单暂存 V15.2.1 payload。验包器拒绝绝对路径泄露、符号链接、私有 profile、Cookie、凭据、截图、日志、运行目录和非白名单文件。

## 手动 CLI 回退

普通用户不需要此步骤。维护者可以用 Harness CLI 的 `plugin --profile web add <archive>` 与 `remove dsh-media-missher` 做诊断；旧版 CLI 需设置 `DSH_DESKTOP_PNPM_ENTRY` 指向 Harness.app 内置 pnpm；新版 CLI 通过 PATH 调用已有 pnpm。一键安装器会把验过的归档固定到 `~/.dsh/artifacts/media-missher/` 的 SHA 命名文件，避免同版本缓存和仓库移动影响，安装前的 profile 备份位于 `~/.dsh/backups/media-missher-plugin-*/package.json`。

本包为 `UNLICENSED` 私有 Bundle，只能发布到已获授权的同仓库私有 Release，不得公开发布到 npm 或公共 Release。
