# Media@Missher 17.0.2：官方 alpha.5 已验证范围

2026-10-17。本次复用冻结的 **17.0.2** DSH Bundle 和现有依赖，仅补充官方 npm Host 的独立验收。没有修改产品运行件、重新构建或重新打包。当前下载见 [Releases](https://github.com/Missher12/Missher-Media/releases)，按版本及校验值核对。

## 材料与结果

宿主使用官方 npm `@deepseek-ai/dsh@0.2.1-alpha.5` 及其实际依赖，沿用已准备的运行目录；不是 Missher 社区扩展包，也不是自行重建的上游源码。对应上游版本为 [dsh-v0.2.1-alpha.5](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.1-alpha.5)。本次校验了准备记录、锁文件和相关包清单摘要，并记录实际入口摘要。

| 项目 | 已验证结果 |
| --- | --- |
| 实际宿主组件 | DSH / app-boot / tools / system-prompt 均为 0.2.1-alpha.5；Cordis 4.0.5；Loader 1.0.6 |
| 实际 profile 解析与 Loader | 冻结 Bundle 被解析并激活，无跳过项 |
| 工具注册 | `media_missher_collect`、`media_missher_runs`、`media_missher_setup` 全部注册 |
| 实际 ToolRuntime 执行 `setup status` | 空目标返回 `needs-setup`、0 行目标，浏览器及登录状态为 `not-checked` |
| 无效参数组合 | 工具返回 `failed / setup_arguments_invalid`，没有打开浏览器 |
| 缺少必需 `tools` 服务 | Media 不激活，Loader 明确报告 `pending (waiting for service: tools)` |

上述检查由两个串行用例完成：正常 profile 和缺少 tools 的 profile。二者均使用真实官方 profile 解析器及 Loader，正常用例通过真实 ToolRuntime 执行工具；profile 内容为隔离的最小配置，数据为空。这是组件集成验收，未执行普通桌面安装或全功能桌面验收。

原 [2026-10-14 社区 Host 验收](HOST_COMPATIBILITY_2026-10-14.md) 保留为历史证据，不重复执行。其中缺少可选 `systemPrompt` 的合成注册 fixture 仍只是该项证据，不能合并声称官方完整 Host 无 systemPrompt 也可运行。

## 隔离与资源

- 每个用例使用独立 HOME、DSH_HOME、XDG、缓存和临时目录；不加载日常 profile，不挂载 LLM/Agent 服务。
- 两个进程串行运行，实际 cgroup 均限制为 768 MiB、swap 0、CPU 100%、最多 32 个进程/线程；Node 堆 384 MiB，单例超时 60 秒。最高 cgroup 内存峰值为 57,958,400 字节，未发生 OOM。
- Node fetch、HTTP(S)、socket connect 和子进程 API 均阻断并计数，实际尝试次数均为 0；这不是内核级全流量审计。没有模型请求、浏览器动作、真实采集或依赖下载。
- 两个测试 scope 均已退出，未操作日常 DSH 进程。原始日志、隔离 profile 和验收脚本只存于维护者私有证据目录，不随产品交付。

## 支持边界

本次证明该冻结 Bundle 能在这份官方 alpha.5 运行件的最小 profile 中加载，并完成所列工具调用与缺能力诊断；不自动覆盖所有中间版本。

包清单仍声明 `os: [darwin]`。在 Linux 上解包进行 Loader 验收，不代表普通 Ubuntu 包管理安装受支持。macOS 原生界面、正常桌面安装、模型驱动调用、Chrome CDP 实际连接和真实平台采集均不属于此次验收；本次也没有升级本机插件。

冻结 DSH 包 SHA-256 保持为：

```text
1f6e19d6cea0c064e6af6de5b501386ffbc9bd61d320cf5c0b8cba3d96f4076b
```
