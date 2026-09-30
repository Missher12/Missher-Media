# Media@Missher 17.0.0 快速开始

先阅读 [能采集什么](DATA_CAPABILITIES.md)。本包是私有交付；运行时、通用 CLI、DSH Bundle 均为 17.0.0。模型由所用 Agent 决定。

## 1. 选安装入口

| 使用方式 | 对应文件 |
| --- | --- |
| Codex、Hermes 等支持本地命令的 Agent | `Media-Missher-Agent-Setup-v17.0.0.zip`，解压后按其中 `AGENT_INSTALL.md` 安装 |
| DeepSeek Harness（macOS） | `missher-dsh-media-missher-17.0.0.tgz`；完整包附带 `harness-plugin/scripts/install-current-profile.mjs` 和验包器，按 `harness-plugin/README.md` 操作 |
| 审查源码、自行构建 | `Media-Missher-Source-v17.0.0.zip` 或私有 Git 仓库，执行 `node tools/build_distribution.mjs` |

### DSH「添加插件」

本地文件选择 `missher-dsh-media-missher-17.0.0.tgz`。`missher-media-missher-17.0.0.tgz` 是通用 Agent CLI，完整 ZIP 是交付集合，都不能作为 DSH 组合包安装。

Git 地址需要指向含根目录 `package.json` 和 `git-bundle/` 的修复提交。旧 V17 提交只有 `harness-plugin/` 子目录声明组合包，直接填仓库地址会报「这个包没有声明组合包」。根入口直接携带已校验的冻结 DSH 包，不运行安装构建脚本；所安装的采集运行时与对应 tgz 一致。修复发布前请使用上面的 DSH tgz；修复发布后可在已具备私有仓库访问权限的 DSH 中填写 `https://github.com/Missher12/media-missher.git#main`。

通用 CLI 要求 Node.js >=22.19 和 npm；实际采集需要 Python 3.11/3.12 与 Chrome。macOS/Linux 使用同一 CLI 包；Windows 入口通过 WSL2/WSLg，须让 Agent 命令、Python、文件和浏览器处在同一个 Linux 环境。Windows 原生采集不在此包范围。

在交付目录核对 `SHA256SUMS.txt`，再从解压后的 Agent Setup 安装：

```sh
sh ./install.sh --archive "$PWD/missher-media-missher-17.0.0.tgz" --sha256 "填写 SHA256SUMS.txt 中对应的完整值"
```

安装器返回命令的绝对路径；PATH 尚未包含它时使用该路径。首次安装 Node/Python 依赖需要访问包源，此包不是包含全部依赖的断网安装镜像。

## 2. 让 Agent 发现入口

```sh
media-missher --version
media-missher install-skill --list
media-missher install-skill --agent codex
media-missher doctor
```

按实际宿主选择一个 Skill 目录，不要同时安装到所有 Agent。Hermes 或自定义目录以 `--list` 和宿主的实际目录为准，也可显式传 `--skill-root /absolute/skills`。确认宿主会话能读到 Skill 并调用 CLI；安装完成不代表会话已经加载。

已有同名 Skill 若归属于独立的原子运行时安装器，应沿用其升级入口，不能强制覆盖。仓库源码升级到 17.0.0 不会自动更新机器上的 15.6.0 安装。

## 3. 导入目标，准备登录

```sh
media-missher setup template
media-missher setup import --file /absolute/creators.xlsx
media-missher setup activate --import-id <返回的导入ID> --rows 1,3
media-missher setup status
```

模板需要平台、名称、官方主页链接。预览后选择实际需要的行；名称仅作标签，不按姓名猜账号。

需要打开专用浏览器时：

```sh
media-missher setup browser-open --confirm-open
media-missher setup browser-check
```

在新开的 Chrome 中手动登录所选平台。连接成功只证明 CDP 可用，登录和页面状态会在采集前另行核验。

## 4. 采集并查看结果

例如已选定小红书博主，用户要求取 1 条并允许打开相应页面：

```sh
media-missher collect --platforms xhs --count 1 --backend cdp --allow-navigation
media-missher runs list
```

先查看返回的真实数量、状态、停止原因和私有结果目录。多个目标顺序执行；不要自动重试风险停止的任务。

## 5. 选择导出

```sh
media-missher runs export --run-id <返回的运行ID> --record-kinds posts --format xlsx --file-name results.xlsx
```

按需要选择 `posts`、`topic_participants`、`user_profiles`，可加 `--platforms`、`--topics`、`--targets`、`--fields` 或 `--field-groups`。支持 xlsx、csv、json、jsonl、sqlite。导出只读已有证据，不打开浏览器或补抓。

完整 Agent 使用指南见 [AGENT_INSTALL.md](AGENT_INSTALL.md)。交付包中的 `VALIDATION.json` 给出该包实际通过的验证层级。
