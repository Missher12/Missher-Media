# Media@Missher 17.0.2 Host 兼容核验

2026-10-14。本轮保留版本 **17.0.2** 和既有归档字节，只补文档、流程图及独立验收证据。

## 接口与版本策略

Bundle 没有 Host 的运行时精确版本锁。`Cordis 4.0.4` 和 `dsh-tools 0.2.0-rc.2` 是开发依赖；运行入口没有导入第二份 Host/Cordis。保留开发锁文件，以便复现构建。

必需能力是 `tools.register` 和 `dshHomePath()`；工具使用参数/输出契约、`execute` 和取消信号。`systemPrompt.section` 为可选能力，缺失时仍可注册三个工具。本轮不改变提示词内容或注入策略。

Media 内部 Python 运行时的 **17.0.2** 检查用于确保载荷协议一致，属于真实的数据保护边界，不能作为 Host 版本锁删除。包清单中的 `os: [darwin]` 同样保留。

## 本轮已验证

| 检查 | Missher 配套旧 rc.2 | Missher 配套新 alpha.2 |
| --- | --- | --- |
| 实际运行包 | DSH 0.2.0-rc.2 / Cordis 4.0.4 / Loader 1.0.5 | DSH 0.2.1-alpha.2 / Cordis 4.0.5-alpha.1 / Loader 1.0.6-alpha.1 |
| 原 17.0.2 Bundle 经实际 profile 解析和 Loader 加载 | 通过 | 通过 |
| 三个 Media 工具注册 | 通过 | 通过 |
| 真实 ToolRuntime 执行 `setup status` | 空目标返回 `needs-setup`，浏览器未检查 | 同左 |
| 无效参数组合 | 工具返回 `failed / setup_arguments_invalid` | 同左 |
| 移除必需 `tools` 服务 | Media 不激活，明确报告等待 `tools` | 同左 |

另有一个**受控缺能力 fixture**：不给 Media 提供 `systemPrompt`，使用真实冻结 Bundle 和合成注册上下文，三个工具仍注册，直接调用 setup 状态检查正常。该项不是完整 Host，也不是纯官方发行包验证。真实 Host 的 ToolRuntime 自身依赖 systemPrompt，不能把此 fixture 混称为整个 Host 无 systemPrompt 仍可运行。

运行材料来源：旧 rc.2 为保留的 Missher 社区 Debian 包解包；新 alpha.2 为已接受的 Missher 社区安装运行件。**二者均非未经修改的纯官方发行包**。已测的是这两份具体社区运行件，不据此宣布所有中间版本或纯官方版本通过。

## 独立与资源边界

- 每个动态用例单独进程、串行执行，使用独立 HOME、DSH_HOME、XDG 和临时目录；不加载日常 profile。
- 初始入口检查限制 384 MiB / Node 堆 192 MiB；Host 检查限制 768 MiB / Node 堆 384 MiB；CPU 上限 100%、swap 为 0、60 秒超时。均核对实际 cgroup，无隔离失败后直接执行的回退。
- 依赖复用中断前已下载的材料；本轮入口检查核对 exceljs 4.4.0 和 saxes 5.0.1 的锁定摘要、缓存归档 SHA-512，以及分别 519 / 5 个已安装文件。没有再次运行 npm，也没有重新打包 Media。
- Node fetch、HTTP(S)、socket connect 和子进程 API 在 Host 验收中均受阻断并计数，实际尝试次数均为 0。此计数不等同于内核级全流量审计。最小 profile 未挂载 LLM/Agent 服务，未发起模型请求、浏览器动作或真实采集。
- 原生开发会话只执行一次正式恢复、取消和回读，保留已落盘用量与原日志前缀；本轮验收没有新增开发模型请求。

中断前的 alpha.2 尝试在依赖准备阶段失败：npm 移除了没有列入依赖声明的测试 Bundle。该旧结果不计为 Loader 通过。本轮改用经过核验的独立包目录和复用依赖，避免 npm 清理测试输入。验收脚手架的元数据入口、环境快照和错误值断言修正均只发生在私有验收材料中，未修改产品。

## 未验证范围

未执行纯官方 Host、普通 Ubuntu 包管理安装、macOS 原生界面、模型驱动工具调用或真实平台抓取；不能由 Linux 上的隔离 Loader 通过推导这些已通过。三个包清单仍声明 macOS，正常安装支持范围未扩大。没有本轮新 Release 或本机插件升级。

冻结 DSH 包 SHA-256：

```text
1f6e19d6cea0c064e6af6de5b501386ffbc9bd61d320cf5c0b8cba3d96f4076b
```

独立验收原始日志、会话恢复回执和机器路径仅保存在维护者本机私有证据中，不加入产品交付。流程图及复现说明见 [图片说明](images/README.md)。
