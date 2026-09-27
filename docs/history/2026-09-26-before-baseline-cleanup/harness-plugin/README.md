# dsh-media-missher 0.6.0 local maintenance candidate

© 2026 Missher。保留所有权利。原创部分未经许可禁止修改、衍生及二次传播；第三方依赖保留原许可。详见 LICENSE 与版权说明。

Bundle 版本为 **0.6.0**，内置采集主项目为 **15.6.0**。本候选未发布，正式 profile 尚未升级。旧版安装与验收记录见根目录 PROJECT_CONTEXT.md 的历史章节。

本版把同一工具实现提供给独立 Agent CLI＋Skill，并增加 Linux 浏览器适配；本 Harness 安装包继续限定 macOS。共享锁、小红书风险/冷却、统一版本预检及阶段耗时保持一致。通用接入见仓库 `AGENT_INSTALL.md` 与 `docs/AGENT_ENTRY_15.6.0.md`；既有保护设计见 `docs/SHARED_SAFETY_15.5.0.md`。

给新电脑上的 Harness Agent 的逐步接入契约见 [AGENT.md](AGENT.md)。先按该文件完成安装和只读检查，再进行任何真实采集。Markdown 不会自行注册工具，实际注册由 `package.json`、`cordis.patch.yml` 和 `lib/index.js` 完成。

安装器支持两类 macOS Harness 布局：`Contents/Resources/runtime/node/bin/node` 与 `runtime/app/lib/bin.js` 的布局使用 `/usr/local/bin/pnpm` 或 `/opt/homebrew/bin/pnpm` 中已有的 pnpm；缺少时在修改 profile 前报 `harness_external_pnpm_required`。`app.asar.unpacked` 布局使用自带 Electron/CLI/pnpm，本次 Harness 0.5.5 实机验证采用此布局。安装器自动识别，不自动下载安装 pnpm；自定义路径可通过 `--runtime`、`--cli`、`--pnpm` 提供。

自包含 Setup ZIP 分发（`Media-Missher-Harness-Setup-bundle-*` 与 `SETUP-SHA256.txt`）已退役，本仓库不再构建或分发该安装包。根目录历史 GitHub bootstrap 仍指向既有 v15.2.1 Release，不用于获取本候选。安装器备份 profile、固定 SHA 命名归档、校验入口字节、实际导入入口并检查有效配置；导入失败不再报告安装成功。失败后保留备份供诊断，不自动重置用户配置。

本版本直接使用 Harness 公开 ToolDefinition/JSON Schema 注册接口，SDK 不参与运行时加载；生成的类型声明包含 SDK 声明并保留原 MIT 许可。工具入口不依赖宿主内部模块在 profile 中可被 Node 解析。已有四平台配置保留 4x10；新设备默认只使用已激活的平台，保留正数条数上限、单控制器顺序采集；`allow_navigation` 默认是 `false`，只有明确授权的采集请求才能打开精确目标导航。浏览器辅助和截图仍为控制器默认 off。

新增校验覆盖空平台项、非法类型、未知参数、无小红书平台的评论请求；导出前按原生 ID 优先级保留首次出现的记录，对齐 Python 校验器。计数不足会降为 partial，风险状态优先，不导出请求外平台。证据必须属于本次文件系统时间边界并具有私有权限，诊断只接受固定枚举。字符串长 ID 保持原值，不安全的数值 ID 报错而不制造已损失精度的文本。原始 JSON 不改写。

本版本提供显式创作者续采和离线历史导出/对比，不自动重试。小红书每批最多 10 条和 3 页，实际启动间隔至少 600 秒，风险暂停持久保存；控制器从输出发现风险时也会保存暂停。Stop 先清理适配器拥有的 runtime 进程组，Harness 外层保留 8 秒清理宽限；已有 Chrome 不在终止范围。使用契约见随包的 [AGENT.md](AGENT.md)。真实测试仍需用户给出平台、私有目标配置、条数和导航授权。

验证顺序：`pnpm install --frozen-lockfile`、`pnpm exec tsc --noEmit`、`pnpm test`（只读校验当前源码，不向 `dist/` 写入发布物）、`pnpm run pack:bundle`、`pnpm run verify:package -- --write-checksum dist/dsh-media-missher-0.6.0.tgz`、`pnpm run smoke:native`。native smoke 使用独立 DSH_HOME，采集部分为合成 fixture，不能视为真实平台验收。

需要验证本机 Chrome 启动时，单独执行 `pnpm run smoke:browser -- --confirm-open`。它只打开临时专用资料目录中的本地欢迎页，检查连接、复用和备份，随后清理自己启动的测试进程与目录；不会打开平台或登录。它不属于自动测试默认步骤。

---

# dsh-media-missher

`dsh-media-missher` 是 Media@Missher V15.6.0 的私有 macOS DeepSeek Harness Bundle。它向 Agent 注册名单配置工具 `media_missher_setup`、采集工具 `media_missher_collect` 和离线历史工具 `media_missher_runs`。

## 用户安装

本仓库不再分发自包含 Setup ZIP，也不再有根目录一键安装脚本。保留的安装方式是用 `pnpm run pack:bundle` 从当前源码重建 `dist/dsh-media-missher-0.6.0.tgz`，再用 `node scripts/install-current-profile.mjs --archive <tgz> --profile web` 安装。安装器使用 Harness.app 自带运行时；新版宿主还需要本机已有 pnpm，旧版使用内置 pnpm。不要用历史 GitHub bootstrap 安装本候选。

默认无参数调用按已授权的 profile 目标顺序采集，每个目标 10 条；同平台允许多个目标。采集先保存私有记录与 manifest，不自动创建 Excel，`workbookPath` 可以为空。Agent 报告实际数量、字段覆盖和停止原因，再按用户已经给出的选择调用 `media_missher_runs action=export`；只有缺少必要选择时才询问。导出只读历史证据，保留 partial/risk-stopped/cancelled 状态及缺失字段，不启动新采集。

## 新设备名单

调用 `media_missher_setup` 的 template → import → activate；填写平台、博主名称和完整官方主页，查看返回的私有预览后选择行号。同平台可一次选多位；用户已明确给出的目标不必重新导入。新激活的平台优先于旧 defaultPlatforms 默认值。空设备和仅导入但未选择的设备不会安装采集 runtime、创建空运行或启动浏览器。导入仅使用 Node/ExcelJS，不依赖 Python、浏览器或网络。

Git 工作树可先 `pnpm run build`，再用 `pnpm run setup:device -- status`、`template`、`import --file /absolute/creators.xlsx`、`activate --import-id <ID> --rows 1,3` 进入同一配置逻辑。可通过 `--profile /absolute/private/profile.json` 指定隔离配置。采集 CLI 使用同一路径的 `--profile`。

名单选择后，明确调用 browser-open（confirm_open=true）打开独立 AI 采集浏览器；欢迎页提供四平台官方入口，用户自行登录。browser-check 只读取本地 CDP 元数据并报告所选平台页面，不把页面存在当作登录成功。导入、激活、status 和 collect 都不会自动打开浏览器；不创建开机启动项。Git CLI 使用 `browser-open --confirm-open`、`browser-check`。完整陪同流程见 [AGENT.md](AGENT.md)。

## Bundle 结构

- `cordis.patch.yml`：Harness profile 的 Cordis 配置片段
- `lib/index.js`：Agent 工具与运行时适配器
- `payload/`：严格白名单暂存的 Media@Missher 15.6.0 运行时
- `scripts/install-current-profile.mjs`：验包、备份、安装和有效配置确认
- `scripts/native-smoke.mjs`：隔离原生安装生命周期验证
- `scripts/verify-package.mjs`：校验 Bundle 归档并生成/校验 `dist/SHA256SUMS.txt`
- `AGENT.md`：新电脑首次接入、授权和结果核验契约

Bundle 只允许 macOS。显式 targets 接受用户提供的官方主页、UID 或 handle，也可使用 mode-`0600` 私有 profile 中已选择的目标。不得猜测身份、传入或回显凭据；模型侧结果仅包含状态、计数和本地证据路径。

## 开发命令

```bash
pnpm install --frozen-lockfile
pnpm test
pnpm exec tsc --noEmit
pnpm run build
pnpm run pack:bundle
pnpm run verify:package -- --write-checksum dist/dsh-media-missher-0.6.0.tgz
pnpm run smoke:native -- --archive dist/dsh-media-missher-0.6.0.tgz
```

打包会先重建 TypeScript 入口，再从仓库中的精确白名单暂存 V15.6.0 payload。归档校验后由 `verify:package` 自行写出并复核 `dist/SHA256SUMS.txt`，测试不再写入 `dist/`。验包器拒绝绝对路径泄露、符号链接、私有 profile、Cookie、凭据、截图、日志、运行目录和非白名单文件。

## 手动 CLI 回退

普通用户不需要此步骤。维护者可以用 Harness CLI 的 `plugin --profile web add <archive>` 与 `remove dsh-media-missher` 做诊断；旧版 CLI 需设置 `DSH_DESKTOP_PNPM_ENTRY` 指向 Harness.app 内置 pnpm；新版 CLI 通过 PATH 调用已有 pnpm。一键安装器会把验过的归档固定到 `~/.dsh/artifacts/media-missher/` 的 SHA 命名文件，避免同版本缓存和仓库移动影响，安装前的 profile 备份位于 `~/.dsh/backups/media-missher-plugin-*/package.json`。

本包采用 `LICENSE` 所载的 Missher 专有授权，只能发布到已获授权的同仓库私有 Release，不得公开发布到 npm 或公共 Release。
