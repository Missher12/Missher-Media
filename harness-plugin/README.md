# dsh-media-missher

`dsh-media-missher` 是 Media@Missher V15.2.1 的私有 macOS DeepSeek Harness Bundle。它向 Agent 注册一个工具：`media_missher_collect`。

## 用户安装

推荐把根目录 README 的一键命令交给 Harness Agent：它会用已登录的 `gh` 从私有 `v15.2.1` Release 下载 `Install-Media-Missher-from-GitHub.command`，校验自包含 Setup ZIP 后安装。已经下载完整仓库时，也可以直接双击根目录的 `Install Media@Missher Harness Plugin.command`。内层安装器使用 DeepSeek Harness.app 自带运行时，无需另装 Node.js 或 pnpm。

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
pnpm run verify:package -- dist/dsh-media-missher-0.1.0.tgz
pnpm run pack:setup
pnpm run verify:setup -- dist/Media-Missher-Harness-Setup-v15.2.1.zip
pnpm run smoke:native -- --archive dist/dsh-media-missher-0.1.0.tgz
```

打包会先重建 TypeScript 入口，再从仓库中的精确白名单暂存 V15.2.1 payload。验包器拒绝绝对路径泄露、符号链接、私有 profile、Cookie、凭据、截图、日志、运行目录和非白名单文件。

## 手动 CLI 回退

普通用户不需要此步骤。维护者可以用 Harness CLI 的 `plugin --profile web add <archive>` 与 `remove dsh-media-missher` 做诊断；必须设置 `DSH_DESKTOP_PNPM_ENTRY` 指向 Harness.app 内置 pnpm。一键安装器会把验过的归档固定到 `~/.dsh/artifacts/media-missher/` 的 SHA 命名文件，避免同版本缓存和仓库移动影响，安装前的 profile 备份位于 `~/.dsh/backups/media-missher-plugin-*/package.json`。

本包为 `UNLICENSED` 私有 Bundle，只能发布到已获授权的同仓库私有 Release，不得公开发布到 npm 或公共 Release。
