# dsh-media-missher 17.0.0

Media@Missher 的私有 macOS DeepSeek Harness Bundle，内置运行时 17.0.0，仅 Chrome CDP。源码、CLI、Bundle 本次统一版本。© 2026 Missher，原创软件采用专有许可，不公开发布 npm。

可采集字段见随包 [DATA_CAPABILITIES.md](DATA_CAPABILITIES.md)，通用 Agent 流程见 [QUICKSTART.md](QUICKSTART.md)。

| 工具 | 用途 |
| --- | --- |
| `media_missher_setup` | 名单模板、导入预览与选择；明确请求的浏览器打开和连接检查 |
| `media_missher_collect` | 按顺序采集、保存私有证据，仅 cdp |
| `media_missher_runs` | 本地历史、进度、比较和选择导出 |

默认每目标 10 条，同平台可有多个目标。采集不自动创建 Excel，workbookPath 可以为空。小红书每批最多 10 条/3 页，两批开始间隔至少 600 秒，风险暂停持久保存。不自动重试、续采或切换账号。

## 安装

完整交付包保留 `harness-plugin/scripts/` 布局，含安装器和验包器。在完整包根目录运行：

```sh
node harness-plugin/scripts/verify-package.mjs harness-plugin/dist/dsh-media-missher-17.0.0.tgz
node harness-plugin/scripts/install-current-profile.mjs --help
```

核对实际已安装的 macOS Harness、profile 和支持的命令参数后，按 `AGENT.md` 继续。安装器识别已有 Harness 布局，新布局需要已安装的 pnpm，不下载另一套宿主。单独取得 tgz 时，使用本版仓库或完整包附带的安装器。

安装后分别检查工具注册、离线调用和经授权的采集；配置成功不代表原生调用或登录就绪。空设备先导入、预览和选择目标，再按用户要求打开专用 Chrome 并手动登录。

## 兼容与验证

独立 0.6.1 分支的 ctx.subprocess、环境过滤、取消及卸载生命周期修复尚未自动合入。本包不宣称兼容所有 Harness 版本，实际结果见完整包 `VALIDATION.json`。

## 开发

```sh
pnpm install --frozen-lockfile
pnpm test
pnpm exec tsc --noEmit
pnpm run pack:bundle
pnpm run verify:package -- --write-checksum dist/dsh-media-missher-17.0.0.tgz
```

全项目交付由根目录 `tools/build_distribution.mjs` 构建。smoke:native 使用隔离 DSH_HOME 做安装、合成调用及卸载；smoke:browser 使用临时 Chrome 和本地页。二者均不等于真实平台采集。
