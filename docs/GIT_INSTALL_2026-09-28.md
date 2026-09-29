# DSH Git 安装入口修复

日期：2026-09-28。状态：本地修复和隔离验证完成，尚未提交、推送或更新生产安装。当前 Git 发布约定要求等待用户新的明确 Git 命令。

## 问题与修复

用户在 DSH「添加插件」中填写整个 Git 仓库地址，收到「这个包没有声明组合包，不能作为插件管理」。旧仓库根目录没有 `package.json`；真正的 `dsh.bundle` 声明在 `harness-plugin/package.json`。DSH 安装整个仓库后检查的是根包，不会自动寻找子目录，所以返回 `not-bundle`。

本轮增加根 `package.json`，保持包名 `dsh-media-missher`、版本 `17.0.0` 和原依赖；组合包补丁与模块入口指向 `git-bundle/`。该目录是冻结 DSH tgz 的完整展开视图：62 个文件，共 1,324,368 字节，逐文件与原包一致。通用 Agent CLI 和采集核心没有修改。

根入口没有 prepare、prepack 或安装生命周期脚本。当前宿主自带 pnpm 11.7.0 会对 Git 依赖的 prepare 脚本检查构建许可，因此交付直接携带可加载文件，避免将安装成功依赖于额外的构建授权。维护脚本 `tools/sync-dsh-git.mjs` 仅用于显式同步发布内容；安装时不会调用。

## 本轮验证

宿主为已安装的 `~/Applications/DeepSeek Harness.app`：DSH/plugin-manager 0.1.7-rc.2，Node 24.18.1，pnpm 11.7.0。调用安装包内实际的 PluginManager 和 Loader，所有 profile、缓存和测试依赖位于临时目录。

| 层级 | 结果 |
| --- | --- |
| 旧 Git 入口复现 | 使用旧提交的本地 Git 地址安装，pnpm 返回 0，PluginManager 返回 `not-bundle`；profile manifest 回滚后字节不变 |
| 根入口回归 | 5 项通过：禁用生命周期脚本仍能完整打包；缺声明、错误校验值、缺校验文件、版本不一致时，维护同步拒绝且保留已有文件 |
| 交付一致性 | 新增 `git-bundle/` 的全部 62 个文件与冻结 tgz 逐字节一致 |
| 宿主 pnpm 打包 | 从隔离副本以 `--config.ignore-scripts=true` 打包成功 |
| 新入口的安装包 | 实际 PluginManager 安装、识别和启用组合包声明、ESM 模块导入、卸载均通过 |
| 原 V17 DSH tgz | 本轮重新通过同一插件管理器的安装、识别、模块导入及卸载；可以直接用于本地文件安装 |
| 保护检查 | 17 个已记录的冻结产物、原 lib、生产 profile 文件和既有审查文件摘要未变；HEAD 未变 |

测试 profile 没有启用 HMR，管理器按协议返回 `restart-required`；这表示配置已登记，不表示已在日常 UI 中热加载。没有重启应用、替换生产 profile、调用真实模型或抓取真实平台。

根入口测试命令：

```sh
node --test tools/tests/git-bundle.test.mjs
```

冻结 DSH 包 SHA-256：`09c0862c5bf56d18681f80b4a34e0b59f5319ef78b095e5276f481f06ad02568`。

本轮根入口候选包 SHA-256：`4f7079c50300ec45b8daaeec26c98c23e7183cacb134c9cbb56eb3bbe9fe0592`。候选只用于隔离验证，没有覆盖 `dist/v17.0.0/` 的既有文件。

## 发布与使用

本轮只读复查的私有远端 `main` 为 `0d05c1b4557ca2b1f0b4d3edce3c832ed5268d79`，仍无根 `package.json`。本地修复没有推送，**新的远端 Git 地址安装尚未验收**；不能把上述根包打包与安装结果表述为远端已修复。

现在可在 DSH「添加插件」选择 `dist/v17.0.0/dsh-media-missher-17.0.0.tgz`。`missher-media-missher-17.0.0.tgz` 是通用 Agent CLI，完整 ZIP 是交付集合。

取得新的 Git 授权后，按私有仓库约定交付根清单、`git-bundle/`、维护脚本、回归和相关文档；然后用已授权访问私有仓库的隔离 profile 验收发布提交。当前生产安装不随源码交付自动更新。

后续发布先构建并校验对应 DSH tgz 和 `SHA256SUMS.txt`，同步根清单版本、入口与依赖，再在隔离副本执行 `node tools/sync-dsh-git.mjs` 和根入口回归。确认展开文件与冻结包一致后，作为新的 Git 交付视图审查；不手工改 `git-bundle/` 内的采集实现。
